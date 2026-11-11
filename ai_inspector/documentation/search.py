"""Literal code-point search and edits; no Unicode normalization.

The boundary predicate is a deliberately bounded UAX #29 subset: combining
marks and the other Extend/SpacingMark characters, selectors, emoji
modifiers/tags, ZWJ, CRLF, RI pairs, Hangul and Prepend. It is stricter than
UAX #29 around ZWJ and Prepend (never a boundary after either). Indic conjunct
joining (GB9c) is not modelled. Checked against a full UAX #29 implementation
over every code point: the only other differences are code points unassigned
in this runtime's Unicode data. Python positions are Unicode code points,
never UTF-16 units. A search read authorizes ranges, not whole fields.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import json
import unicodedata

from .commands import DocumentEditError, binding, digest
from . import rich_text

RANGE_OPERATIONS = {"replace_range", "format_range"}
# Extend or SpacingMark characters whose general category is not Mn, Mc or Me (ZWNJ, Thai and Lao SARA AM,
# the halfwidth katakana sound marks). static/documentation_search.js mirrors both tables.
_EXTEND_OTHER = frozenset({0x200c, 0x0e33, 0x0eb3, 0xff9e, 0xff9f})
_PREPEND = ((0x0600, 0x0605), (0x06dd, 0x06dd), (0x070f, 0x070f), (0x0890, 0x0891), (0x08e2, 0x08e2),
            (0x0d4e, 0x0d4e), (0x110bd, 0x110bd), (0x110cd, 0x110cd), (0x111c2, 0x111c3), (0x113d1, 0x113d1),
            (0x1193f, 0x1193f), (0x11941, 0x11941), (0x11a3a, 0x11a3a), (0x11a84, 0x11a89), (0x11d46, 0x11d46),
            (0x11f02, 0x11f02))
MARK_FEATURES = ("bold", "italic", "underline", "strike", "subscript", "superscript",
                 "highlight", "color", "fontFamily", "fontSize", "link")


def _hangul(code):
    if 0x1100 <= code <= 0x115f or 0xa960 <= code <= 0xa97c:
        return "L"
    if 0x1160 <= code <= 0x11a7 or 0xd7b0 <= code <= 0xd7c6:
        return "V"
    if 0x11a8 <= code <= 0x11ff or 0xd7cb <= code <= 0xd7fb:
        return "T"
    if 0xac00 <= code <= 0xd7a3:
        return "LVT" if (code - 0xac00) % 28 else "LV"
    return ""


def boundary(text, offset):
    if type(offset) is not int or not 0 <= offset <= len(text):
        return False
    if offset in {0, len(text)}:
        return True
    left, right = ord(text[offset - 1]), ord(text[offset])
    if (unicodedata.category(text[offset]) in {"Mn", "Mc", "Me"} or right in _EXTEND_OTHER
            or 0xfe00 <= right <= 0xfe0f or 0xe0100 <= right <= 0xe01ef
            or 0x1f3fb <= right <= 0x1f3ff or 0xe0020 <= right <= 0xe007f
            or 0x200d in {left, right} or (left == 13 and right == 10)):
        return False
    if any(low <= left <= high for low, high in _PREPEND):
        return False
    a, b = _hangul(left), _hangul(right)
    if (a == "L" and b in {"L", "V", "LV", "LVT"} or a in {"LV", "V"} and b in {"V", "T"}
            or a in {"LVT", "T"} and b == "T"):
        return False
    if 0x1f1e6 <= right <= 0x1f1ff:
        count, index = 0, offset - 1
        while index >= 0 and 0x1f1e6 <= ord(text[index]) <= 0x1f1ff:
            count, index = count + 1, index - 1
        if count % 2:
            return False
    return True


def fold(text):
    return "".join(folded if len(folded := char.casefold()) == 1 else char for char in text)


def query_value(query):
    if (not isinstance(query, str) or not 1 <= len(query) <= 200
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in query)):
        raise DocumentEditError("invalid_search_query", "Find requires 1-200 literal code points without controls.")
    return query


def matches(text, query, case_sensitive=False):
    haystack, needle = (text, query) if case_sensitive else (fold(text), fold(query))
    offset = 0
    while (start := haystack.find(needle, offset)) >= 0:
        end = start + len(query)
        if boundary(text, start) and boundary(text, end):
            yield start, end
            offset = end
        else:
            offset = start + 1


def context(text, start, end):
    left, right = max(0, start - 40), min(len(text), end + 40)
    while left < start and not boundary(text, left):
        left += 1
    while right > end and not boundary(text, right):
        right -= 1
    return {"before": text[left:start], "match": text[start:end], "after": text[end:right]}


def find_document_text(state, targets, arguments):
    from .targets import read_targets
    query = query_value(arguments.get("query"))
    limit, sensitive = arguments.get("limit", 50), arguments.get("caseSensitive", False)
    scope = arguments.get("scopeIds")
    if (type(limit) is not int or not 1 <= limit <= 200 or type(sensitive) is not bool
            or scope is not None and (not isinstance(scope, list) or any(not isinstance(x, str) for x in scope))
            or "cursor" in arguments and not isinstance(arguments["cursor"], str)):
        raise DocumentEditError("invalid_search_query", "Invalid search scope, case option or limit.")
    if arguments.get("documentId", state["documentId"]) != state["documentId"]:
        raise DocumentEditError("document_binding_changed", "That search belongs to another document.")
    # Include both owner revisions (specification slots and authored objects).
    stamp = digest({**binding(state), "sceneRevision": state.get("sceneRevision"),
                    "query": query, "caseSensitive": sensitive, "scopeIds": scope})
    offset = 0
    if arguments.get("cursor"):
        try:
            cursor = json.loads(base64.urlsafe_b64decode(arguments["cursor"].encode("ascii")))
            if set(cursor) != {"stamp", "offset"} or cursor["stamp"] != stamp or type(cursor["offset"]) is not int or cursor["offset"] < 0:
                raise ValueError()
            offset = cursor["offset"]
        except (ValueError, TypeError, UnicodeError, KeyError):
            raise DocumentEditError("stale_search_cursor", "Find again; this cursor belongs to another search revision.") from None
    found, reads, candidates = [], [], []
    for key, target in targets.items():
        if scope is not None and not ({key, *target.get("pageIds", [target["pageId"]])} & set(scope)):
            continue
        positions = list(matches(target["text"], query, sensitive))
        if not positions:
            continue
        candidates.append((key, target, positions))
    rows = read_targets(state, targets, [{"targetId": key, "pageId":
        next((page for page in target.get("pageIds", [target["pageId"]]) if page in scope), target["pageId"])
        if scope and key not in scope else target["pageId"]} for key, target, _ in candidates],
                        limit=None, internal=True)["targets"] if candidates else []
    for (key, target, positions), row in zip(candidates, rows):
        operations = [name for name in row["capabilities"] if name in RANGE_OPERATIONS]
        reason = ("manual_edit_conflict" if row.get("hasOpenConflict") else
                  "read_only_derived_field" if not operations else None)
        for start, end in positions:
            found.append({"pageId": row["pageId"], "targetId": key, "contentHash": row["contentHash"],
                          "targetLabel": str(target["attributes"].get("label") or target["attributes"].get("blockType") or target["alias"])[:160],
                          "start": start, "end": end, "revision": row["revision"], **context(row["text"], start, end),
                          "editable": "replace_range" in operations, "operations": operations, "reason": reason})
        # This is deliberately an excerpt read. Only range operations may use it.
        reads.append({**row, "text": "", "isExcerpt": True, "rangeRead": True})
    page = found[offset:offset + limit]
    visible = {item["targetId"] for item in page}
    next_cursor = (base64.urlsafe_b64encode(json.dumps({"stamp": stamp, "offset": offset + limit},
                   separators=(",", ":")).encode()).decode() if offset + limit < len(found) else None)
    return ({**binding(state), "sceneRevision": state.get("sceneRevision"),
             "rangeRevision": state.get("scene", {}).get("editRevision", state["revision"]), "total": len(found),
             "matches": page, "cursor": next_cursor},
            {**binding(state), "sceneRevision": state.get("sceneRevision"), "aliasRevision": state.get("aliasRevision"),
             "targets": [row for row in reads if row["targetId"] in visible]})


def check_range(text, operation):
    start, end = operation.get("start"), operation.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
        raise DocumentEditError("invalid_text_range", "Use code-point offsets within the complete text.")
    if not boundary(text, start) or not boundary(text, end):
        raise DocumentEditError("invalid_grapheme_boundary", "A range cannot split a grapheme.")
    if operation.get("expectedText") != text[start:end]:
        raise DocumentEditError("expected_text_mismatch", "The exact range text changed; find again.")
    if operation["operation"] == "replace_range":
        replacement = operation.get("text")
        if not isinstance(replacement, str) or any(c in text[start:end] + replacement for c in "\r\n"):
            raise DocumentEditError("invalid_text_range", "Range replacement cannot contain or cross a line break.")
        try:
            replacement.encode("utf-8")
        except UnicodeError:
            raise DocumentEditError("invalid_text_range", "Replacement must be valid Unicode.") from None
    return start, end


def _spans(doc):
    """Mutable leaf and block spans in exactly plain_text's projection order."""
    leaves, blocks = [], []
    def visit(node, offset, parent=None):
        kind = node["type"]
        if kind in {"text", "hardBreak"}:
            length = len(node["text"]) if kind == "text" else 1
            leaves.append((offset, offset + length, node, parent))
            return offset + length
        start = offset
        children = node.get("content", [])
        for index, child in enumerate(children):
            if index and kind not in {"paragraph", "heading"}:
                offset += 1
            offset = visit(child, offset, node)
        if kind in {"paragraph", "heading"}:
            blocks.append((start, offset, node))
        return offset
    visit(doc, 0)
    return leaves, blocks


def _merge_runs(node):
    """Join neighbouring text nodes with identical marks, as the editor does on load."""
    children = node.get("content")
    if not isinstance(children, list):
        return
    if node["type"] not in {"paragraph", "heading"}:
        for child in children:
            _merge_runs(child)
        return
    merged = []
    for child in children:
        last = merged[-1] if merged else None
        if (last is not None and last["type"] == child["type"] == "text"
                and set(last) | set(child) <= {"type", "text", "marks"}
                and last.get("marks", []) == child.get("marks", [])):
            merged[-1] = {**last, "text": last["text"] + child["text"]}
        else:
            merged.append(child)
    node["content"] = merged


def _format_marks(marks, operation, capabilities, target_id):
    add, remove = operation.get("add", []), operation.get("remove", [])
    if not isinstance(add, list) or not isinstance(remove, list) or any(not isinstance(x, str) for x in remove):
        raise DocumentEditError("invalid_rich_text", "Invalid range formatting.")
    if any(not isinstance(x, dict) or set(x) - {"feature", "value"} or not isinstance(x.get("feature"), str) for x in add):
        raise DocumentEditError("invalid_rich_text", "Invalid added range feature.")
    requested = set(remove) | {x["feature"] for x in add}
    refused = requested - (set(MARK_FEATURES) & set(capabilities.get("features", [])))
    if refused:
        raise DocumentEditError("unsupported_rich_text_feature", "This target does not support these range features.",
                                targets=[target_id], features=sorted(refused))
    result = {mark["type"]: deepcopy(mark) for mark in marks}
    def discard(feature):
        if feature in {"color", "fontFamily", "fontSize"}:
            style = result.get("textStyle", {}).get("attrs", {})
            style.pop(feature, None)
            if not style:
                result.pop("textStyle", None)
        else:
            result.pop(feature, None)
    for feature in remove:
        discard(feature)
    for item in add:
        feature = item["feature"]
        if feature in {"color", "fontFamily", "fontSize"}:
            result.setdefault("textStyle", {"type": "textStyle", "attrs": {}})["attrs"][feature] = item.get("value")
        elif feature in {"highlight", "link"}:
            result[feature] = {"type": feature, "attrs": {"color" if feature == "highlight" else "href": item.get("value")}}
        else:
            if "value" in item:
                raise DocumentEditError("invalid_rich_text", "This mark takes no value.")
            result[feature] = {"type": feature}
            if feature in {"subscript", "superscript"}:
                discard("superscript" if feature == "subscript" else "subscript")
    # Validate even empty selections, using the same mark rules as stored data.
    probe = rich_text.from_plain("x")
    probe["schemaVersion"] = 2
    probe["doc"]["content"][0]["content"][0]["marks"] = list(result.values())
    return rich_text.validate(probe)["doc"]["content"][0]["content"][0].get("marks", [])


def edit_rich(value, operation, capabilities, target_id):
    value = deepcopy(value)
    start, end = check_range(rich_text.plain_text(value), operation)
    leaves, blocks = _spans(value["doc"])
    if operation["operation"] == "format_range":
        if start == end:
            raise DocumentEditError("invalid_text_range", "Formatting needs a range of at least one code point.")
        _format_marks([], operation, capabilities, target_id)
        for left, right, node, parent in leaves:
            if node["type"] != "text" or right <= start or left >= end:
                continue
            a, b = max(0, start - left), min(right - left, end - left)
            pieces = []
            if a:
                pieces.append({**deepcopy(node), "text": node["text"][:a]})
            middle = {"type": "text", "text": node["text"][a:b]}
            marks = _format_marks(node.get("marks", []), operation, capabilities, target_id)
            if marks:
                middle["marks"] = marks
            pieces.append(middle)
            if b < right - left:
                pieces.append({**deepcopy(node), "text": node["text"][b:]})
            index = next(i for i, item in enumerate(parent["content"]) if item is node)
            parent["content"][index:index + 1] = pieces
    else:
        block = next((node for left, right, node in blocks if left <= start <= end <= right), None)
        if block is None:
            raise DocumentEditError("invalid_text_range", "Replacement must stay within one block.")
        text_leaves = [(a, b, node) for a, b, node, parent in leaves if parent is block and node["type"] == "text"]
        chosen = next((node for a, b, node in text_leaves if a <= start < b), None)
        if start == end:
            before = next((node for a, b, node in text_leaves if a < start <= b), None)
            # A hard break ends the preceding inline segment.
            if before is not None and (start == 0 or rich_text.plain_text(value)[start - 1] not in "\r\n"):
                chosen = before
        new = {"type": "text", "text": operation["text"]}
        if chosen and chosen.get("marks"):
            new["marks"] = deepcopy(chosen["marks"])
        result, inserted = [], False
        spans = {id(node): (a, b) for a, b, node, parent in leaves if parent is block}
        for node in block.get("content", []):
            a, b = spans[id(node)]
            if b <= start and not (a == b == start):
                result.append(node)
                continue
            if a >= end and inserted:
                result.append(node)
                continue
            if node["type"] == "text" and a < start < b:
                result.append({**deepcopy(node), "text": node["text"][:start - a]})
            if not inserted:
                if new["text"]:
                    result.append(new)
                inserted = True
            if a >= end:
                result.append(node)
            elif node["type"] == "text" and a < end < b:
                result.append({**deepcopy(node), "text": node["text"][end - a:]})
        if not inserted and new["text"]:
            result.append(new)
        block["content"] = result
    value["schemaVersion"] = max(2, value["schemaVersion"])
    value = rich_text.validate(value)
    # Validation put every mark list in canonical order, so equal neighbours now compare equal.
    _merge_runs(value["doc"])
    rich_text.require_capabilities(value, capabilities, targets=[target_id])
    return value


def coalesce_ranges(targets, operations):
    """Validate against a common pre-image, then emit one existing write per target.

    Same-position insertions and an insertion on either edge of another range
    are rejected as overlapping: their ordering would otherwise be ambiguous.
    """
    from .targets import capabilities, rich_text_capabilities
    grouped = {}
    for operation in operations:
        grouped.setdefault(operation["targetId"], []).append(operation)
    output = []
    for key, group in grouped.items():
        if not any(item["operation"] in RANGE_OPERATIONS for item in group):
            output.extend(group)
            continue
        target = targets.get(key)
        if target is None:
            raise DocumentEditError("target_not_found", "The range target no longer exists.", targetId=key)
        if any(item["operation"] not in RANGE_OPERATIONS for item in group):
            raise DocumentEditError("overlapping_ranges", "Do not combine whole-field and range edits on one target.")
        caps = capabilities(target)
        for item in group:
            if item["operation"] not in caps:
                raise DocumentEditError("read_only_derived_field", "This target does not permit this range edit.", targetId=key)
            check_range(target["text"], item)
        ordered = sorted(group, key=lambda item: (item["start"], item["end"]))
        for a, b in zip(ordered, ordered[1:]):
            if b["start"] < a["end"] or b["start"] == a["end"] and (a["start"] == a["end"] or b["start"] == b["end"]):
                raise DocumentEditError("overlapping_ranges", "Ranges refer to one pre-image and must not overlap.", targetId=key)
        rich = target.get("richField") or {}
        use_rich = rich.get("isRichText") or any(item["operation"] == "format_range" for item in group)
        value = (rich.get("richText") or rich_text.from_plain(target["text"])) if use_rich else target["text"]
        for item in reversed(ordered):
            if use_rich:
                value = edit_rich(value, item, rich_text_capabilities(target), key)
            else:
                value = value[:item["start"]] + item["text"] + value[item["end"]:]
        output.append({"operation": "replace_rich_text" if use_rich else "replace_text", "targetId": key,
                       "expectedContentHash": group[0]["expectedContentHash"],
                       "richText" if use_rich else "text": value})
    return output
