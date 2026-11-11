"""Versioned authored text. JSON is user data, never HTML or model instructions.

Only content of scene-owned text objects can hold this envelope. Stored values
are never repaired on read. The client allocates rt-<UUID> block/break IDs; text
leaves and the document root have no identity (ProseMirror splits text leaves).
"""
from __future__ import annotations

import math
import os
import re
from urllib.parse import urlsplit
import uuid

from .commands import DocumentEditError, canonical_bytes
from .rich_fonts import FONT_MAP

FEATURE_FLAG = "INSPECTORPRO_DOCUMENTATION_RICH_TEXT"
MAX_BYTES = 24 * 1024
MAX_NODES = 512
MAX_LIST_DEPTH = 6
MAX_DEPTH = 14
NODE_ID_PATTERN = r"rt-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
LINK_ATTRIBUTES = {"target": "_blank", "rel": "noopener noreferrer nofollow", "class": None}
PLAIN_EDIT_CONSEQUENCE = "Whole-field replacement removes all rich formatting and node IDs and stores one plain string."
_BLOCKS = {"paragraph", "heading", "bulletList", "orderedList"}
_MARKS = ("bold", "italic", "underline", "strike", "subscript", "superscript", "highlight", "textStyle", "link")
_PARAGRAPH_ATTRS = {"textAlign", "indent", "spaceBefore", "spaceAfter", "lineHeight"}


def enabled(environ=None):
    source = os.environ if environ is None else environ
    return str(source.get(FEATURE_FLAG, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def require_enabled():
    if not enabled():
        raise DocumentEditError("documentation_rich_text_disabled", "Rich text editing is disabled.", featureFlag=FEATURE_FLAG)


def is_rich(value):
    # Any non-string payload must fail closed, including unrecognized envelopes.
    return value is not None and not isinstance(value, str)


def _invalid(message, code="invalid_rich_text"):
    raise DocumentEditError(code, message)


def _keys(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        _invalid("Unsupported rich text keys or missing required keys.")


def _href(value):
    # Mailto is deliberately excluded in this proof: only navigable web sources.
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048
            or re.search(r"[\s\x00-\x1f\x7f\\]", value)):
        _invalid("Links must be absolute HTTP or HTTPS URLs.", "unsafe_rich_text_link")
    try:
        url = urlsplit(value)
        valid = (url.scheme.lower() in {"http", "https"} and url.netloc and url.hostname
                 and url.username is None and url.password is None)
        url.port
    except ValueError:
        valid = False
    if not valid:
        _invalid("Links must be absolute HTTP or HTTPS URLs.", "unsafe_rich_text_link")
    return value


def validate(value, *, reserved_ids=()):
    """Return canonical JSON; reject unsupported shapes instead of stripping data."""
    _keys(value, {"format", "schemaVersion", "doc"}, {"format", "schemaVersion", "doc"})
    if value["format"] != "tiptap" or type(value["schemaVersion"]) is not int or value["schemaVersion"] not in {1, 2}:
        _invalid("Unsupported rich text envelope.", "unsupported_rich_text_schema")
    ids, reserved, count = set(), set(reserved_ids), 0
    uses_v2 = False

    def feature_v2():
        nonlocal uses_v2
        if value["schemaVersion"] == 1:
            _invalid("Schema-2 formatting requires schemaVersion 2.", "unsupported_rich_text_schema")
        uses_v2 = True

    def number(raw, minimum, maximum, step):
        if (type(raw) not in {int, float} or not minimum <= raw <= maximum or not math.isfinite(raw)
                or abs(raw / step - round(raw / step)) > 1e-9):
            _invalid("Typography value is outside its range or step.")
        canonical = round(round(raw / step) * step, 2)
        return int(canonical) if canonical == int(canonical) else canonical

    def color(raw):
        if not isinstance(raw, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", raw) is None:
            _invalid("Color must be a six-digit hex color.")
        return raw.lower()

    def mark(raw):
        _keys(raw, {"type", "attrs"}, {"type"})
        kind, attrs = raw["type"], raw.get("attrs", {})
        if not isinstance(kind, str) or kind not in _MARKS:
            _invalid("Unsupported rich text mark.")
        if kind in {"strike", "subscript", "superscript", "highlight"}:
            feature_v2()
        if kind in {"bold", "italic", "underline", "strike", "subscript", "superscript"}:
            _keys(attrs, {})
            return {"type": kind}
        if kind == "highlight":
            _keys(attrs, {"color"}, {"color"})
            return {"type": kind, "attrs": {"color": color(attrs["color"])}}
        if kind == "textStyle":
            _keys(attrs, {"color", "fontFamily", "fontSize"})
            if not attrs:
                _invalid("Text style requires at least one attribute.")
            result = {}
            if "color" in attrs:
                result["color"] = color(attrs["color"])
            if "fontFamily" in attrs:
                feature_v2()
                if not isinstance(attrs["fontFamily"], str) or attrs["fontFamily"] not in FONT_MAP:
                    _invalid("Unsupported rich text font family.")
                result["fontFamily"] = attrs["fontFamily"]
            if "fontSize" in attrs:
                feature_v2()
                result["fontSize"] = number(attrs["fontSize"], 6, 48, .5)
            return {"type": kind, "attrs": result}
        _keys(attrs, {"href", *LINK_ATTRIBUTES}, {"href"})
        # Persist only server-owned attributes. Unknown attributes (including
        # style, title and event handlers) are refused, never passed through.
        return {"type": kind, "attrs": {"href": _href(attrs["href"]), **LINK_ATTRIBUTES}}

    def node(raw, depth=0, lists=0):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            _invalid("Rich text exceeds its node or depth bound.", "rich_text_too_large")
        _keys(raw, {"type", "attrs", "content", "text", "marks"}, {"type"})
        kind = raw["type"]
        if not isinstance(kind, str) or kind not in {"doc", "text", "hardBreak", "listItem", *_BLOCKS} or (kind == "doc") != (depth == 0):
            _invalid("Unsupported rich text node.")
        result = {"type": kind}
        attrs = raw.get("attrs", {})
        if kind in {"doc", "text"}:
            _keys(attrs, {})
        else:
            extra = {"level"} if kind == "heading" else {"start"} if kind == "orderedList" else set()
            if kind in {"paragraph", "heading"}:
                extra |= _PARAGRAPH_ATTRS
            _keys(attrs, {"id", *extra}, {"id"})
            identity = attrs["id"]
            if not isinstance(identity, str) or re.fullmatch(NODE_ID_PATTERN, identity) is None:
                _invalid("Authored node IDs must be rt- followed by a lowercase UUID.", "invalid_rich_text_node_id")
            if identity in ids or identity in reserved:
                _invalid("Authored node IDs must be unique across this document.", "rich_text_node_id_collision")
            ids.add(identity)
            result["attrs"] = {"id": identity}
            if kind in {"paragraph", "heading"}:
                for name in sorted(_PARAGRAPH_ATTRS & attrs.keys()):
                    feature_v2()
                    attr_value = attrs[name]
                    if name == "textAlign":
                        if not isinstance(attr_value, str) or attr_value not in {"left", "center", "right"}:
                            _invalid("Paragraph alignment must be left, center or right.")
                        result["attrs"][name] = attr_value
                    else:
                        limits = (1, 2, .05) if name == "lineHeight" else (0, 72 if name == "indent" else 36, .5)
                        result["attrs"][name] = number(attr_value, *limits)
            if kind == "heading":
                if type(attrs.get("level")) is not int or not 1 <= attrs["level"] <= 3:
                    _invalid("Heading levels are limited to 1-3.")
                result["attrs"]["level"] = attrs["level"]
            if kind == "orderedList":
                start = attrs.get("start", 1)
                if type(start) is not int or not 1 <= start <= 9999:
                    _invalid("Ordered list start must be 1-9999.")
                result["attrs"]["start"] = start
        if kind == "text":
            if "content" in raw or not isinstance(raw.get("text"), str) or not raw["text"]:
                _invalid("Text leaves require nonempty text and no children.")
            result["text"] = raw["text"]
        elif "text" in raw:
            _invalid("Only text leaves contain text.")
        if "marks" in raw:
            if kind not in {"text", "hardBreak"} or not isinstance(raw["marks"], list) or len(raw["marks"]) > len(_MARKS):
                _invalid("Invalid rich text marks.")
            marks = [mark(item) for item in raw["marks"]]
            if len({item["type"] for item in marks}) != len(marks):
                _invalid("Duplicate rich text mark.")
            if {"subscript", "superscript"} <= {item["type"] for item in marks}:
                _invalid("Subscript and superscript cannot be combined.")
            if marks:
                result["marks"] = sorted(marks, key=lambda item: _MARKS.index(item["type"]))
        children = raw.get("content", [])
        if not isinstance(children, list) or len(children) > MAX_NODES:
            _invalid("Invalid rich text children.")
        if kind in {"text", "hardBreak"}:
            if "content" in raw:
                _invalid("Inline leaves cannot have children.")
        else:
            if kind in {"bulletList", "orderedList"}:
                lists += 1
                if lists > MAX_LIST_DEPTH:
                    _invalid("List nesting exceeds six levels.", "rich_text_too_large")
                if lists > 3:
                    feature_v2()
            content = [node(child, depth + 1, lists) for child in children]
            types = [child["type"] for child in content]
            allowed = {"text", "hardBreak"} if kind in {"paragraph", "heading"} else {"listItem"} if kind in {"bulletList", "orderedList"} else _BLOCKS
            if any(t not in allowed for t in types) or (kind in {"doc", "bulletList", "orderedList", "listItem"} and not types):
                _invalid("Invalid rich text child structure.")
            if kind == "listItem" and types[0] != "paragraph":
                _invalid("A list item must start with a paragraph.")
            if content:
                result["content"] = content

        return result

    doc = node(value["doc"])
    result = {"format": "tiptap", "schemaVersion": 2 if uses_v2 else 1, "doc": doc}
    try:
        size = len(canonical_bytes(result))
    except (ValueError, UnicodeError, TypeError):
        _invalid("Rich text must be valid UTF-8 JSON.")
    if size > MAX_BYTES:
        _invalid("Rich text exceeds 24 KiB of canonical JSON.", "rich_text_too_large")
    return result


def node_ids(value):
    """Bounded best-effort inventory also reserves IDs in malformed stored fields."""
    pending, result, visited = [value], set(), 0
    while pending and visited < 8192:
        item = pending.pop()
        visited += 1
        if isinstance(item, dict):
            identity = item.get("attrs", {}).get("id") if isinstance(item.get("attrs"), dict) else None
            if isinstance(identity, str):
                result.add(identity)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return result


def object_values(pages):
    for page_id, page in pages.items():
        for key, item in page.get("documentObjects", {}).items():
            if item.get("type") == "text":
                yield page_id, key, item.get("content", "")


def reserved_ids(pages, page_id, target_id):
    return {identity for page, key, value in object_values(pages) if (page, key) != (page_id, target_id)
            for identity in node_ids(value)}


def guard_restored_fields(before, after):
    """Undo/orphan restore cannot introduce an invalid or cross-field identity."""
    old = {(page, key): value for page, key, value in object_values(before.get("pages", {}))}
    pages = after.get("pages", {})
    for page, key, value in object_values(pages):
        if is_rich(value) and value != old.get((page, key)):
            validate(value, reserved_ids=reserved_ids(pages, page, key))


def plain_text(value):
    if not is_rich(value):
        return value or ""
    doc = validate(value)["doc"]

    def project(node):
        kind = node["type"]
        if kind == "text":
            return node["text"]
        if kind == "hardBreak":
            return "\n"
        separator = "" if kind in {"paragraph", "heading"} else "\n"
        return separator.join(project(child) for child in node.get("content", []))

    return project(doc)


def from_plain(text, *, id_factory=None):
    """One paragraph, LF hard breaks, literal CR/tabs/spaces/code points retained.

    P2a-2 must mirror this conversion with client IDs and full whitespace parsing.
    No old string is converted by a read. Text leaves may contain literal CR.
    """
    if not isinstance(text, str):
        _invalid("Plain conversion requires a string.")
    allocate = id_factory or (lambda: "rt-" + str(uuid.uuid4()))
    content = []
    for index, line in enumerate(text.split("\n")):
        if index:
            content.append({"type": "hardBreak", "attrs": {"id": allocate()}})
        if line:
            content.append({"type": "text", "text": line})
    return validate({"format": "tiptap", "schemaVersion": 1, "doc": {"type": "doc", "content": [
        {"type": "paragraph", "attrs": {"id": allocate()}, "content": content}]}})


def field_read(value, *, reserved=()):
    if not is_rich(value):
        return {"text": value or "", "isRichText": False, "richText": None, "richTextError": None}
    try:
        rich = validate(value, reserved_ids=reserved)
        return {"text": plain_text(rich), "isRichText": True, "richText": value, "richTextError": None}
    except DocumentEditError as error:
        return {"text": "", "isRichText": True, "richText": None, "richTextError": error.code}


def project_objects(document):
    """Disposable display text for the existing canvas and its thumbnails.

    The canonical value remains in the scene/composition. No legacy renderer
    receives an envelope where it expects a string. Saves still hit the guard.
    """
    for page in document.get("pages", []):
        for item in page.get("documentationObjects", {}).values():
            if item.get("type") == "text" and is_rich(item.get("content")):
                status = field_read(item["content"])
                item["content"] = status["text"]
                item["isRichText"] = True
                item["richTextError"] = status["richTextError"]
    return document


def rich_targets(document):
    found = {}
    for page in document.get("pages", []):
        composition = page.get("documentationComposition") or (page.get("renderRequest") or {}).get("composition") or {}
        for objects in (page.get("documentationObjects", {}), composition.get("documentObjects", {})):
            for key, item in objects.items():
                if item.get("type") == "text" and (is_rich(item.get("content")) or item.get("isRichText")):
                    found[(page["pageId"], key)] = {"pageId": page["pageId"], "targetId": key}
    return list(found.values())


def refuse_export(document, *, format):
    # format is required: an exporter that forgets it must fail, not skip the refusal.
    if format in {"pdf", "docx"}:
        return
    found = rich_targets(document)
    if found:
        raise DocumentEditError("unsupported_export_feature", "Rich text is not supported by this export format.",
                                targets=found, feature="rich_text", format=format)
