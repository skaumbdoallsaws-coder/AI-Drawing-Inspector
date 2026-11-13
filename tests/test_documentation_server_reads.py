"""P5a carried server contracts: request presence, compile reuse and compact table reads."""
from copy import deepcopy
import json

import pytest

from ai_inspector.documentation.commands import DocumentEditError, canonical_bytes, digest
from ai_inspector.documentation.targets import read_targets, ReadBindings, summarize_page
from tests.test_documentation_rich_text import scene, KIND, PAGE, OBJECT, NUMBER
from tests.test_documentation_tables import table_value, table_of, cells, modify


def test_table_structure_read_has_addresses_lengths_and_no_cell_text(scene, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "1")
    value = table_value(2, 3)
    first = cells(value)[0]
    first["content"][0]["content"][0]["text"] = "secret \U0001f600"
    value, _ = modify(value, "merge_cells", cellIds=[c["attrs"]["id"] for c in cells(value)[:2]])
    scene.edit(value)
    state, document, targets = scene.snapshot()
    full = read_targets(state, targets, [{"targetId": OBJECT}])
    compact = read_targets(state, targets, [{"targetId": OBJECT}], table_structure_only=True)
    item, prior = compact["targets"][0], full["targets"][0]
    assert item["contentHash"] == prior["contentHash"] and item["binding"] == prior["binding"]
    assert not {"text", "richText", "provenance"} & item.keys()
    assert item["structureOnly"] and item["isExcerpt"]
    table = item["tables"][0]; stored = table_of(value)
    assert table["columns"] == stored["attrs"]["columns"]
    assert [r["rowId"] for r in table["rows"]] == [r["attrs"]["id"] for r in stored["content"]]
    assert table["rows"][0]["headers"][0] and table["rows"][0]["textLengths"][0] == len("secret \U0001f600\nR0C1")
    assert table["mergedRanges"] == [{"cellId": first["attrs"]["id"], "row": 0, "column": 0, "rowspan": 1, "colspan": 2}]
    assert "secret" not in json.dumps(compact)
    summary, captured = summarize_page(document["pages"][0], {"blocks": []}, state, targets, table_structure_only=True)
    assert "secret" not in json.dumps(summary)
    assert next(i for i in captured if i["targetId"] == item["targetId"])["tables"] == item["tables"]
    assert read_targets(state, targets, [{"targetId": OBJECT}], table_structure_only=False) == full


def test_structure_only_read_authorizes_table_structure_but_not_unread_text(scene, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "1")
    scene.edit(table_value(1, 2))
    state, _, targets = scene.snapshot()
    result = read_targets(state, targets, [{"targetId": OBJECT}], table_structure_only=True)
    bindings = ReadBindings("compact"); bindings.record(KIND, result)
    item = result["targets"][0]
    common = {"documentId": result["documentId"], "expectedRevision": result["revision"], "requestId": "compact"}
    operation = {"targetId": item["targetId"], "expectedContentHash": item["contentHash"],
                 "operation": "modify_table", "tableId": item["tables"][0]["tableId"], "action": "delete_table"}
    assert bindings.bind_operations(KIND, {**common, "operations": [operation]})["operations"][0]["tableId"] == operation["tableId"]
    for name in ("replace_text", "replace_rich_text", "replace_range", "format_range"):
        with pytest.raises(DocumentEditError) as caught:
            bindings.bind_operations(KIND, {**common, "operations": [{**operation, "operation": name}]})
        assert caught.value.code == "full_read_required"


def test_gateway_structure_only_pages_and_targets_do_not_leak_text(scene, monkeypatch):
    from tests.test_codex_documentation_tools import Host, gateway, call
    from ai_inspector.documentation.targets import hash_values
    from ai_inspector.documentation.commands import content_hash
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "1")
    value = table_value(1, 2); cells(value)[0]["content"][0]["content"][0]["text"] = "UNREAD_CELL_SENTINEL"
    scene.edit(value)
    state, document, targets = scene.snapshot()
    host = Host()
    host.document_snapshot = lambda *args: {"state": state, "document": document, "targets": targets,
        "hashes": {k: content_hash(state, k, v) for k, v in hash_values(targets).items()}}
    for wanted in ({"pageCount": 1}, {"targets": [{"targetId": OBJECT}]}):
        result = call(gateway(host), "read_document_pages", {"documentType": KIND, "tableStructureOnly": True, **wanted})
        assert result["ok"], result
        assert "UNREAD_CELL_SENTINEL" not in json.dumps(result)
        assert '"textLengths"' in json.dumps(result)


@pytest.mark.parametrize("initial_paper", [None, "Letter"])
def test_page_setup_distinct_compiles_and_checked_document_are_reused(scene, monkeypatch, tmp_path, initial_paper):
    import server
    from ai_inspector.operations_manual import exports
    from ai_inspector.documentation.layout import normalize_page_setup
    from ai_inspector.parts_manual.documentation import documentation_scene_revision
    calls = []
    def compile_scene(value):
        calls.append(documentation_scene_revision(value))
        return {"documentType": KIND, "pages": [{"pageId": PAGE}], "documentRevision": digest(value),
                "documentationSceneRevision": documentation_scene_revision(value), "pageSetup": value.get("pageSetup")}
    monkeypatch.setattr(exports, "fit_report", lambda *args: [])
    if initial_paper:
        scene.command({"operation": "set_page_setup", "targetType": "document_page_setup", "targetId": "page-setup",
            "pageSetup": normalize_page_setup(KIND, {"paper": initial_paper, "orientation": "landscape"})})
    before = scene.load()
    current = compile_scene(before["scene"])
    command = {"operation": "set_page_setup", "pageId": PAGE, "targetType": "document_page_setup", "targetId": "page-setup",
               "pageSetup": normalize_page_setup(KIND, {"paper": "A4", "orientation": "landscape"})}
    check = server._documentation_page_setup_check(command, compile_scene, tmp_path, NUMBER, current=(before["scene"], current))
    result = scene.repo.apply_command(NUMBER, scene.base["sourceRevision"], scene.base["manualPlanRevision"],
        base_revision=before["revision"], command=command, page_targets={PAGE: {}}, identity_document=scene.base, check_candidate=check)
    assert len(calls) <= 2 and len(set(calls)) == len(calls)
    # Same bytes a fresh caller would have compiled, including the final history-dependent revision.
    expected = compile_scene(result["scene"])
    assert canonical_bytes(check.document) == canonical_bytes(expected)
    count = len(calls)
    check(before["scene"], result["scene"])
    assert len(calls) == count


def test_refused_page_setup_compiles_each_of_current_design_candidate_at_most_once(scene, monkeypatch, tmp_path):
    import server
    from ai_inspector.operations_manual import exports
    from ai_inspector.documentation.layout import normalize_page_setup
    scene.command({"operation": "set_page_setup", "targetType": "document_page_setup", "targetId": "page-setup",
        "pageSetup": normalize_page_setup(KIND, {"paper": "Letter", "orientation": "landscape"})})
    before = scene.load(); calls = []
    def compile_scene(value):
        calls.append(digest(value))
        return {"documentType": KIND, "pages": [{"pageId": PAGE}], "paper": value.get("pageSetup", {}).get("paper")}
    def report(root, number, document):
        return [{"pageId": PAGE, "targetId": "new", "reason": "outside_page"}] if document["paper"] == "A4" else []
    monkeypatch.setattr(exports, "fit_report", report)
    candidate = deepcopy(before["scene"]); candidate["pageSetup"] = normalize_page_setup(KIND, {"paper": "A4", "orientation": "landscape"})
    check = server._documentation_page_setup_check({"operation": "set_page_setup"}, compile_scene, tmp_path, NUMBER)
    with pytest.raises(DocumentEditError) as caught: check(before["scene"], candidate)
    assert caught.value.code == "layout_overflow" and len(calls) <= 3 and len(calls) == len(set(calls))
    assert scene.load() == before


from tests.test_documentation_refresh import mmle_client, MMLE_ROUTES


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_page_setup_route_reuses_candidate_and_equals_fresh_read(mmle_client, monkeypatch, kind, route):
    import server
    from tests.test_documentation_page_setup import _real, command, setup, WI, PARTS, OPS
    before = _real(mmle_client, route)
    name = {PARTS: "build_manual_document", OPS: "build_operations_manual_document",
            WI: "build_work_instruction_document"}.get(kind, "_specification_sheet_compile")
    original = getattr(server, name); states = []
    def counted(*args, **kwargs):
        value = kwargs.get("documentation_scene")
        if value is not None: states.append(digest(value))
        return original(*args, **kwargs)
    monkeypatch.setattr(server, name, counted)
    response = command(mmle_client, route, before, setup(kind))
    assert response.status_code == 200, response.text
    # Count scene-state builds, not the separate generated identity catalogue (no scene).
    assert len(states) <= 2 and len(states) == len(set(states)), states
    after = response.json()
    reread = _real(mmle_client, route)
    assert canonical_bytes(after["document"]) == canonical_bytes(reread["document"])
    assert after["scene"] == reread["scene"] and after["revision"] == reread["revision"]


def test_sage_page_setup_reuses_its_current_document(mmle_client, monkeypatch):
    import server
    from tests.test_documentation_page_setup import _sage_reader, _sage_read, _sage_setup, OPS
    reader = _sage_reader(); data = _sage_read(reader, OPS)
    original = server.build_operations_manual_document; states = []
    def counted(*args, **kwargs):
        value = kwargs.get("documentation_scene")
        if value is not None: states.append(digest(value))
        return original(*args, **kwargs)
    monkeypatch.setattr(server, "build_operations_manual_document", counted)
    result = _sage_setup(reader, data, {"paper": "A4", "orientation": "landscape"}, "counted-paper")
    assert result["ok"], result
    assert len(states) <= 2 and len(states) == len(set(states)), states



def test_largest_table_structure_read_fits_tool_ceiling(scene, monkeypatch):
    # Supervisor: one text box stores at most 96 KiB, which stops an empty table near 46 x 12 (P3b); 50 x 12 cannot
    # exist in a box. 45 x 12 is the largest whole-row table every box accepts.
    monkeypatch.setenv("INSPECTORPRO_DOCUMENTATION_RICH_TEXT", "1")
    value = table_value(45, 12, text=False)
    scene.edit(value)
    state, _, targets = scene.snapshot()
    result = read_targets(state, targets, [{"targetId": OBJECT}], table_structure_only=True)
    table = result["targets"][0]["tables"][0]
    assert len(table["rows"]) == 45 and len(table["columns"]) == 12
    assert sum(len(row["cellIds"]) for row in table["rows"]) == 540
    assert len(json.dumps({"ok": True, "data": result}, ensure_ascii=False).encode("utf-8")) <= 65536
    assert all(n == 0 for row in table["rows"] for n in row["textLengths"])
