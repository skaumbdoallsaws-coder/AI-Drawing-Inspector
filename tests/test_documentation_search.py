"""P3a-4 code-point search, pre-image ranges and approved engineering symbols."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

import pytest

from ai_inspector.documentation import rich_text as rich
from ai_inspector.documentation.commands import DocumentEditError, operation_store, canonical_bytes
from ai_inspector.documentation.search import (boundary, matches, context, find_document_text,
    check_range, edit_rich, coalesce_ranges, MARK_FEATURES)
from ai_inspector.documentation.symbols import SYMBOL_GROUPS
from ai_inspector.documentation.targets import ReadBindings, rich_text_capabilities, text_targets
from tests.test_documentation_rich_text import scene, envelope, KIND, NUMBER, PAGE, OBJECT
from tests.test_documentation_rich_blocks import narrative
from tests.test_documentation_refresh import mmle_client

ROOT = Path(__file__).resolve().parents[1]
CAPS = {"schemaVersions": [1, 2], "features": list(rich.FEATURES), "listDepth": 6}


def operation(text, start, end, replacement="X", **extra):
    return {"operation": "replace_range", "targetId": OBJECT, "expectedContentHash": "h",
            "start": start, "end": end, "expectedText": text[start:end], "text": replacement, **extra}


def refused(code, callback):
    with pytest.raises(DocumentEditError) as caught:
        callback()
    assert caught.value.code == code


@pytest.mark.parametrize("text,query,sensitive,expected", [
    ("aaaaa", "aa", False, [(0, 2), (2, 4)]),
    ("Aa aA", "aa", False, [(0, 2), (3, 5)]),
    ("Aa aA", "Aa", True, [(0, 2)]),
    ("Straße STRASSE ẞ ß", "ss", False, [(11, 13)]),
    ("ß ẞ ss", "ß", False, [(0, 1)]),
    ("Σ σ ς", "σ", False, [(0, 1), (2, 3), (4, 5)]),
    ("🙂x🙂x", "x", False, [(1, 2), (3, 4)]),
    ("a e\u0301 e", "e", False, [(5, 6)]),
])
def test_literal_nonoverlap_and_length_preserving_folds(text, query, sensitive, expected):
    assert list(matches(text, query, sensitive)) == expected


@pytest.mark.parametrize("cluster", ["🙂", "🇺🇸", "👍🏽", "👩‍🔧", "1️⃣", "e\u0301", "\r\n",
    "\u1100\u1161\u11a8", "\uac00\u11a8", "\u0600A", "A\U000e0100", "🏴\U000e0067\U000e007f",
    # Extend and SpacingMark characters outside Mn/Mc/Me, and a Prepend character outside the Arabic block.
    "e\u200c", "\u0e01\u0e33", "\u0e81\u0eb3", "\uff76\uff9e", "\uff8a\uff9f", "\u0d4eA"])
def test_grapheme_sequences_and_code_point_offsets(cluster):
    text = "x" + cluster + "y"
    assert boundary(text, 1) and boundary(text, 1 + len(cluster))
    for offset in range(2, 1 + len(cluster)):
        assert not boundary(text, offset)
        refused("invalid_grapheme_boundary", lambda: check_range(text, operation(text, 1, offset)))
    if "\r" not in cluster:
        assert list(matches(text, cluster)) == [(1, len(cluster) + 1)]
        assert check_range(text, operation(text, 1, len(cluster) + 1)) == (1, len(cluster) + 1)


def test_regional_pairs_prepend_hangul_and_context():
    assert [boundary("🇺🇸🇬🇧🇫", n) for n in range(6)] == [True, False, True, False, True, True]
    for a, b in [("L", "L"), ("L", "V"), ("L", "LV"), ("L", "LVT"), ("LV", "V"), ("V", "T"), ("T", "T")]:
        chars = {"L": "\u1100", "V": "\u1161", "T": "\u11a8", "LV": "\uac00", "LVT": "\uac01"}
        assert not boundary(chars[a] + chars[b], 1)
    for code in [0x600, 0x605, 0x6dd, 0x70f, 0x890, 0x891, 0x8e2, 0x110bd, 0x110cd, 0xd4e, 0x111c2, 0x111c3, 0x113d1,
                 0x1193f, 0x11941, 0x11a3a, 0x11a84, 0x11a89, 0x11d46, 0x11f02]:
        assert not boundary(chr(code) + "a", 1)
    text = "e\u0301" * 30 + "X" + "e\u0301" * 30
    snippet = context(text, 60, 61)
    assert snippet == {"before": "e\u0301" * 20, "match": "X", "after": "e\u0301" * 20}
    assert len(context("e\u0301" + "a" * 39 + "X", 41, 42)["before"]) == 39


@pytest.mark.parametrize("query", ["", "a" * 201, "a\n", "\r", "\t", "\x00", "\x7f", "\u0085", None, 5])
def test_invalid_queries(scene, query):
    state, _, targets = scene.snapshot()
    refused("invalid_search_query", lambda: find_document_text(state, targets, {"query": query}))


def test_search_order_scope_pagination_revision_and_read_authority(scene):
    scene.command({"operation": "update_text", "text": "plain plain"})
    state, _, targets = scene.snapshot()
    first, captured = find_document_text(state, targets, {"query": "plain", "limit": 1})
    # Compiled generated blocks precede authored objects on this page.
    assert first["total"] == 3 and first["matches"][0]["targetId"] != OBJECT
    assert first["documentId"] == state["documentId"] and first["revision"] == state["revision"]
    second, _ = find_document_text(state, targets, {"query": "plain", "limit": 1, "cursor": first["cursor"]})
    assert second["matches"][0]["targetId"] == OBJECT and second["matches"][0]["start"] == 0
    scoped, captured = find_document_text(state, targets, {"query": "plain", "scopeIds": [OBJECT]})
    assert scoped["total"] == 2 and all(m["editable"] and m["operations"] == ["replace_range", "format_range"] for m in scoped["matches"])
    page, _ = find_document_text(state, targets, {"query": "plain", "scopeIds": [PAGE]})
    assert page["total"] == 3
    empty, _ = find_document_text(state, targets, {"query": "plain", "scopeIds": []})
    assert empty["total"] == 0
    bindings = ReadBindings("search")
    bindings.record(KIND, captured)
    args = {"documentId": state["documentId"], "expectedRevision": state["revision"], "requestId": "range",
            "operations": [operation("plain plain", 0, 5)]}
    assert bindings.bind_operations(KIND, args)["operations"][0]["targetId"] == OBJECT
    refused("full_read_required", lambda: bindings.bind_operations(KIND, {**args, "operations": [
        {"operation": "replace_text", "targetId": OBJECT, "text": "whole", "expectedContentHash": "h"}]}))
    scene.command({"operation": "update_text", "text": "new"})
    state, _, targets = scene.snapshot()
    refused("stale_search_cursor", lambda: find_document_text(state, targets, {"query": "plain", "cursor": first["cursor"]}))
    refused("stale_search_cursor", lambda: find_document_text(state, targets, {"query": "different", "cursor": first["cursor"]}))


@pytest.mark.parametrize("start,end,text,code", [(0, 4, "x", "invalid_text_range"), (-1, 1, "x", "invalid_text_range"),
    (True, 2, "x", "invalid_text_range"), (1, 0, "x", "invalid_text_range"), (0, 1, "x\n", "invalid_text_range")])
def test_range_bounds(start, end, text, code):
    refused(code, lambda: check_range("abc", operation("abc", start, end, text)))


def test_expected_text_and_line_breaks():
    refused("expected_text_mismatch", lambda: check_range("abc", operation("abc", 0, 1, expectedText="z")))
    for text in ["a\nb", "a\rb", "a\r\nb"]:
        refused("invalid_text_range", lambda: check_range(text, operation(text, 0, len(text))))
    assert check_range("abc", operation("abc", 1, 1, "")) == (1, 1)


def char_marks(value):
    """Each code point of the first block with its marks; run boundaries are not significant."""
    return [(char, node.get("marks", [])) for node in value["doc"]["content"][0]["content"]
            if node["type"] == "text" for char in node["text"]]


def styled():
    value = envelope("ab")
    value["doc"]["content"][0]["content"] = [
        {"type": "text", "text": "ab", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "cd", "marks": [{"type": "italic"}]},
        {"type": "text", "text": "ef", "marks": [{"type": "underline"}]}]
    return rich.validate(value)


@pytest.mark.parametrize("start,end,replacement,expected,marks", [
    (1, 4, "X", "aXef", [{"type": "bold"}]),
    (2, 2, "X", "abXcdef", [{"type": "bold"}]),
    (0, 0, "X", "Xabcdef", [{"type": "bold"}]),
    (6, 6, "X", "abcdefX", [{"type": "underline"}]),
    (2, 4, "", "abef", None),
])
def test_rich_replace_inheritance_neighbors_and_ids(start, end, replacement, expected, marks):
    value = styled()
    result = edit_rich(value, operation("abcdef", start, end, replacement), CAPS, OBJECT)
    assert rich.plain_text(result) == expected and rich.node_ids(result) == rich.node_ids(value)
    assert value == styled() and result["schemaVersion"] == 1
    marked = char_marks(result)
    if marks:
        assert [found for char, found in marked if char == "X"] == [marks]
    assert [found for char, found in marked if char in "ef"] == [[{"type": "underline"}]] * 2
    # Neighbouring runs with equal marks are stored as one run, as the editor does on load.
    leaves = result["doc"]["content"][0]["content"]
    assert all(a.get("marks", []) != b.get("marks", []) for a, b in zip(leaves, leaves[1:]))


def test_range_edits_store_merged_runs():
    value = envelope("needles here")
    result = edit_rich(value, operation("needles here", 0, 6, "pin"), CAPS, OBJECT)
    assert result["doc"]["content"][0]["content"] == [{"type": "text", "text": "pins here"}]
    op = operation("pins here", 0, 3, operation="format_range", add=[{"feature": "bold"}])
    bold = edit_rich(result, op, CAPS, OBJECT)
    assert [node["text"] for node in bold["doc"]["content"][0]["content"]] == ["pin", "s here"]
    plain = edit_rich(bold, {**op, "add": [], "remove": ["bold"]}, CAPS, OBJECT)
    assert canonical_bytes(plain) == canonical_bytes(result)


def test_empty_format_range_is_refused():
    refused("invalid_text_range", lambda: edit_rich(envelope("abc"), operation("abc", 1, 1, operation="format_range",
        add=[{"feature": "bold"}]), CAPS, OBJECT))


def test_insertion_empty_block_after_break_and_structural_refusal():
    value = envelope("")
    result = edit_rich(value, operation("", 0, 0, "🙂"), CAPS, OBJECT)
    assert rich.plain_text(result) == "🙂" and rich.node_ids(result) == rich.node_ids(value)
    value = envelope("a\nb")
    value["doc"]["content"][0]["content"][-1]["marks"] = [{"type": "italic"}]
    result = edit_rich(value, operation("a\nb", 2, 2), CAPS, OBJECT)
    assert dict(char_marks(result))["X"] == [{"type": "italic"}]
    value["doc"]["content"].append(envelope("other", start=20)["doc"]["content"][0])
    text = rich.plain_text(value)
    refused("invalid_text_range", lambda: edit_rich(value, operation(text, 0, len(text)), CAPS, OBJECT))


def test_format_across_blocks_preserves_break_marks_and_ids():
    value = envelope("ab\ncd")
    value["doc"]["content"].append(envelope("ef", start=20)["doc"]["content"][0])
    br = value["doc"]["content"][0]["content"][1]
    br["marks"] = [{"type": "italic"}]
    text = rich.plain_text(value)
    op = operation(text, 1, len(text) - 1, operation="format_range", add=[{"feature": "strike"}, {"feature": "color", "value": "#ABCDEF"}])
    result = edit_rich(value, op, CAPS, OBJECT)
    assert rich.plain_text(result) == text and rich.node_ids(result) == rich.node_ids(value)
    assert result["doc"]["content"][0]["content"][2] == br
    assert result["schemaVersion"] == 2
    assert result["doc"]["content"][0]["content"][0] == {"type": "text", "text": "a"}
    assert result["doc"]["content"][-1]["content"][-1] == {"type": "text", "text": "f"}
    result = edit_rich(result, operation(text, 0, len(text), operation="format_range", remove=["strike", "color"]), CAPS, OBJECT)
    assert result["schemaVersion"] == 1


@pytest.mark.parametrize("feature,value", [("bold", None), ("italic", None), ("underline", None), ("strike", None),
    ("subscript", None), ("superscript", None), ("highlight", "#abcdEF"), ("color", "#abcdef"),
    ("fontFamily", "Courier New"), ("fontSize", 9.5), ("link", "https://example.com")])
def test_format_feature_validation_and_removal(feature, value):
    add = {"feature": feature, **({"value": value} if value is not None else {})}
    op = operation("abc", 0, 2, operation="format_range", add=[add])
    formatted = edit_rich(envelope("abc"), op, CAPS, OBJECT)
    assert feature in rich.used_features(formatted)["features"]
    cleared = edit_rich(formatted, {**op, "add": [], "remove": [feature]}, CAPS, OBJECT)
    assert feature not in rich.used_features(cleared)["features"]
    refused("unsupported_rich_text_feature", lambda: edit_rich(envelope("abc"), op, {**CAPS, "features": []}, OBJECT))


def test_format_script_exclusion_and_capabilities(narrative):
    value = envelope("abc")
    value["schemaVersion"] = 2
    value["doc"]["content"][0]["content"][0]["marks"] = [{"type": "subscript"}]
    result = edit_rich(value, operation("abc", 0, 3, operation="format_range", add=[{"feature": "superscript"}]), CAPS, OBJECT)
    assert rich.used_features(result)["features"] == ["superscript"]
    state, _, targets = narrative.snapshot()
    for alias in ["note", "status_panel", "cad_figure"]:
        target = next(t for t in targets.values() if t["alias"] == alias)
        text = target["text"]
        refused("unsupported_rich_text_feature", lambda: coalesce_ranges(targets, [operation(text, 0, 1,
            operation="format_range", targetId=target["targetId"], add=[{"feature": "fontSize", "value": 12}])]))


@pytest.mark.parametrize("ranges", [[(0, 2), (1, 3)], [(1, 1), (1, 1)], [(0, 1), (1, 1)], [(1, 1), (1, 2)]])
def test_overlapping_ranges(scene, ranges):
    state, _, targets = scene.snapshot()
    text = targets[OBJECT]["text"]
    refused("overlapping_ranges", lambda: coalesce_ranges(targets, [operation(text, a, b) for a, b in ranges]))


def test_many_ranges_same_preimage_and_limits(scene):
    scene.command({"operation": "update_text", "text": "abc def ghi"})
    _, _, targets = scene.snapshot()
    ops = [operation("abc def ghi", 0, 3, "x"), operation("abc def ghi", 8, 11, "longer")]
    assert operation_store(ops) == "scene"
    assert coalesce_ranges(targets, ops)[0]["text"] == "x def longer"
    assert len(coalesce_ranges(targets, ops)) == 1
    assert operation_store([operation("abc", 0, 1)] * 200) == "scene"
    refused("invalid_document_operation", lambda: operation_store([operation("abc", 0, 1)] * 201))
    refused("overlapping_ranges", lambda: operation_store([*ops, {"operation": "replace_text", "targetId": OBJECT}]))
    refused("invalid_document_operation", lambda: operation_store([{"operation": "replace_text", "targetId": str(n)} for n in range(13)]))


def test_locked_and_typed_found_but_not_replaced(scene):
    state, document, _ = scene.snapshot()
    state["scene"]["pages"][PAGE]["documentObjects"][OBJECT]["locked"] = True
    document["slots"] = {"title": {"value": "Original", "kind": "text"}}
    targets = text_targets(state, document)
    result, _ = find_document_text(state, targets, {"query": "Original"})
    assert len(result["matches"]) == 2 and all(not x["editable"] and x["reason"] == "read_only_derived_field" for x in result["matches"])
    for item in result["matches"]:
        refused("read_only_derived_field", lambda: coalesce_ranges(targets, [operation("Original", 0, 8, targetId=item["targetId"])]))


def test_full_find_batch_read_retry_stale_and_one_undo(mmle_client, monkeypatch):
    import server
    from tests.test_codex_documentation_tools import gateway, call
    monkeypatch.setenv(rich.FEATURE_FLAG, "on")
    host = server._DocumentationAgentHost()
    reader = gateway(host, number="MMLE-50D")
    snapshot = host.document_snapshot("MMLE-50D", KIND)
    chosen = next(t for t in snapshot["targets"].values() if t.get("richField") and t["attributes"].get("blockType") == "paragraph")
    full = call(reader, "read_document_pages", {"documentType": KIND, "targets": [{"targetId": chosen["targetId"]}]})["data"]
    value = styled()
    value["doc"]["content"][0]["content"] = [
        {"type": "text", "text": "needle ", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "needle", "marks": [{"type": "italic"}]}]
    seeded = call(reader, "apply_document_edits", {"documentId": full["documentId"], "expectedRevision": full["revision"],
        "requestId": "seed-range", "operations": [{"operation": "replace_rich_text", "targetId": chosen["targetId"],
            "expectedContentHash": full["targets"][0]["contentHash"], "richText": value}]})
    assert seeded["ok"], seeded
    found = call(reader, "find_document_text", {"documentType": KIND, "query": "needle", "scopeIds": [chosen["targetId"]]})
    assert found["ok"], found
    data = found["data"]
    args = {"documentId": data["documentId"], "expectedRevision": data["revision"], "requestId": "range-group",
        "operations": [operation("needle needle", item["start"], item["end"], "pin", targetId=item["targetId"],
                       expectedContentHash=item["contentHash"]) for item in data["matches"]]}
    invalid = deepcopy(args)
    invalid["requestId"] = "invalid-range-group"
    invalid["operations"][-1]["expectedText"] = "wrong pre-image"
    before_hashes = host.document_snapshot("MMLE-50D", KIND)["hashes"]
    failure = call(reader, "apply_document_edits", invalid)
    assert failure["error"]["code"] == "expected_text_mismatch"
    assert host.document_snapshot("MMLE-50D", KIND)["hashes"] == before_hashes
    applied = call(reader, "apply_document_edits", args)
    assert applied["ok"], applied
    assert call(reader, "apply_document_edits", args) == applied
    receipt = applied["data"]["receipt"]
    assert receipt["revision"] == receipt["beforeRevision"] + 1 and len(receipt["changedIds"]) == 1
    row = host.document_snapshot("MMLE-50D", KIND)["targets"][chosen["targetId"]]
    assert row["text"] == "pin pin" and rich.node_ids(row["richField"]["richText"]) == rich.node_ids(value)
    assert row["richField"]["richText"]["doc"]["content"][0]["content"][-1]["marks"] == [{"type": "italic"}]
    stale = call(reader, "apply_document_edits", {**args, "requestId": "stale-range"})
    assert stale["error"]["code"] == "content_hash_mismatch"
    host.undo_document_change("MMLE-50D", KIND, {"documentId": data["documentId"], "changeId": receipt["changeId"],
        "expectedRevision": receipt["revision"], "requestId": "undo-range"})
    restored = host.document_snapshot("MMLE-50D", KIND)["targets"][chosen["targetId"]]["richField"]["richText"]
    assert canonical_bytes(restored) == canonical_bytes(value)


def test_approved_symbol_glyphs_and_mirror():
    import fitz
    assert sum(len(g["symbols"]) for g in SYMBOL_GROUPS) == 69
    symbols = {item["text"] for group in SYMBOL_GROUPS for item in group["symbols"]}
    assert len(symbols) == 68 and "Ω" not in symbols and "⌀" not in symbols
    for family in ("helv", "hebo", "heit", "hebi", "tiro", "tibo", "tiit", "tibi", "cour", "cobo", "coit", "cobi"):
        font = fitz.Font(family)
        for symbol in symbols:
            assert font.has_glyph(ord(symbol), fallback=False), (family, symbol)
    source = (ROOT / "static/documentation_symbols.js").read_text(encoding="utf-8")
    mirror = json.loads(source.split("const groups = ", 1)[1].split(";\n", 1)[0])
    assert mirror == SYMBOL_GROUPS


def test_workspace_batch_over_twelve_targets_reopens_and_undoes(mmle_client):
    import server
    host = server._DocumentationAgentHost()
    snapshot = host.document_snapshot("MMLE-50D", KIND)
    chosen = [t for t in snapshot["targets"].values() if t["operation"] == "replace_text" and t["text"]
              and boundary(t["text"], 1) and t["text"][0] not in "Z\r\n"][:13]
    assert len(chosen) == 13
    state = snapshot["state"]
    args = {key: state[key] for key in ("documentId", "sourceRevision", "manualPlanRevision", "sceneRevision")}
    args.update(expectedRevision=state["revision"], requestId="thirteen-range-targets", operations=[
        operation(t["text"], 0, 1, "Z", targetId=t["targetId"], expectedContentHash=snapshot["hashes"][t["targetId"]]) for t in chosen])
    response = mmle_client.post(f"/api/documentation/{KIND}/MMLE-50D/ranges", json=args)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["receipt"]["changedIds"]) == 13
    current = host.document_snapshot("MMLE-50D", KIND)
    assert current["state"]["scene"]["commands"][-1]["rangeBatch"] is True
    assert all(current["targets"][t["targetId"]]["text"] == "Z" + t["text"][1:] for t in chosen)
    assert result["rangeBinding"]["hashes"] == {t["targetId"]: current["hashes"][t["targetId"]] for t in chosen}
    host.undo_document_change("MMLE-50D", KIND, {"documentId": state["documentId"], "changeId": result["receipt"]["changeId"],
        "expectedRevision": result["receipt"]["revision"], "requestId": "undo-thirteen"})
    current = host.document_snapshot("MMLE-50D", KIND)
    assert all(current["targets"][t["targetId"]]["text"] == t["text"] for t in chosen)


def test_two_hundred_ranges_use_preimage_and_empty_format_converts_losslessly(scene):
    text = "x " * 200
    scene.command({"operation": "update_text", "text": text})
    _, _, targets = scene.snapshot()
    result = coalesce_ranges(targets, [operation(text, n * 2, n * 2 + 1, "abc") for n in range(200)])
    assert len(result) == 1 and result[0]["text"] == "abc " * 200
    result = coalesce_ranges(targets, [operation(text, 0, 1, operation="format_range", add=[{"feature": "bold"}])])
    assert rich.plain_text(result[0]["richText"]) == text


@pytest.mark.parametrize("feature,value,code", [("fontSize", 6.25, "invalid_rich_text"), ("fontSize", 49, "invalid_rich_text"),
    ("fontFamily", "Georgia", "invalid_rich_text"), ("highlight", "red", "invalid_rich_text"),
    ("link", "file:///private", "unsafe_rich_text_link"), ("heading", 2, "unsupported_rich_text_feature")])
def test_invalid_range_formats_use_server_schema(feature, value, code):
    refused(code, lambda: edit_rich(envelope("x"), operation("x", 0, 1, operation="format_range",
        add=[{"feature": feature, "value": value}]), CAPS, OBJECT))


def test_notice_signal_is_not_searchable_content(narrative):
    block = next(b for b in narrative.base["pages"][0]["layoutBlocks"] if b["blockId"] == "note")
    block["signalWord"] = "DANGER"
    state, _, targets = narrative.snapshot()
    key = next(t["targetId"] for t in targets.values() if t["alias"] == "note")
    found, _ = find_document_text(state, targets, {"query": "DANGER", "scopeIds": [key]})
    assert found["total"] == 0


def test_search_reads_matching_targets_in_one_batch(scene, monkeypatch):
    import ai_inspector.documentation.targets as module
    scene.command({"operation": "update_text", "text": "plain plain"})
    state, _, targets = scene.snapshot()
    calls, original = [], module.read_targets
    def counted(*args, **kwargs):
        calls.append(len(args[2]))
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "read_targets", counted)
    result, _ = find_document_text(state, targets, {"query": "plain"})
    assert result["total"] == 3 and calls == [2]


def test_typed_workspace_range_refusal_precedes_scene_owner_revision(mmle_client):
    import server
    kind = "product_specification_sheet"
    snapshot = server._DocumentationAgentHost().document_snapshot("MMLE-50D", kind)
    target = next(t for t in snapshot["targets"].values() if t["operation"] == "set_slot_value")
    state = snapshot["state"]
    args = {key: state[key] for key in ("documentId", "sourceRevision", "manualPlanRevision", "sceneRevision")}
    args.update(expectedRevision=state["revision"] + 100, requestId="typed-range", operations=[
        operation(target["text"], 0, 0, "X", targetId=target["targetId"], expectedContentHash=snapshot["hashes"][target["targetId"]])])
    response = mmle_client.post(f"/api/documentation/{kind}/MMLE-50D/ranges", json=args)
    assert response.status_code != 200
    assert response.json()["error"] == "read_only_derived_field"
