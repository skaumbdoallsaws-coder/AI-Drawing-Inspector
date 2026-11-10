"""P1c-1 identities only. No refresh/conflict policy is implemented in this round."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.documentation import identity
from ai_inspector.documentation.commands import DocumentEditError, content_hash, document_id
from ai_inspector.documentation.identity import (
    bind_document, compile_identities, check_alias_binding, catalog_from, migrate_scene,
)
from ai_inspector.documentation.provenance import project_document
from ai_inspector.documentation.targets import ReadBindings, hash_values, read_targets, text_targets
from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
from ai_inspector.specification_sheet.slots import SlotStore

FIXTURE = Path(__file__).parent / "fixtures/documentation_editor/scene-v3-positional.json"
KIND = "operations_and_maintenance_manual"
NUMBER, SOURCE, PLAN = "IDENTITY", "source-a", "plan-a"
PAGE = "page-source"


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch):
    from collections import OrderedDict
    monkeypatch.setattr(identity, "_CATALOGS", OrderedDict())


def source_document():
    return {"schemaVersion": 2, "documentType": KIND, "product": {"assemblyNumber": NUMBER},
        "sourceRevision": SOURCE, "manualPlanRevision": PLAN, "pages": [{"pageId": PAGE, "pageNumber": 1,
        "layoutBlocks": [{"blockId": "table", "blockType": "table", "columnKeys": ["label", "value"],
            "columns": ["Label", "Value"], "rows": [
                {"sourceKey": "capacity", "cells": ["Capacity", "100"]},
                {"sourceKey": "travel", "cells": ["Travel", "20"]}]},
            {"blockId": "steps", "blockType": "list", "items": [
                {"sourceKey": "isolate", "text": "Isolate"}, {"sourceKey": "inspect", "text": "Inspect"}]}]}]}


def install_old(root, document=None, *, version=3, page=PAGE, alias="table.r0.c1"):
    document = document or source_document()
    old = json.loads(FIXTURE.read_bytes())
    number = document["product"]["assemblyNumber"]
    old.update(schemaVersion=version, assemblyNumber=number,
               sourceRevision=document["sourceRevision"], manualPlanRevision=document["manualPlanRevision"])
    command = old["commands"][0]
    command.update(pageId=page, targetId=alias)
    command["change"]["changes"][0]["path"] = ["pages", page, "pageElementOverrides", alias]
    version_key = page + "/page_element/" + alias
    command["change"]["versionKeys"] = [version_key]
    old["fieldVersions"] = {version_key: 1}
    old["pages"] = {page: {"pageElementOverrides": {alias: {"text": "Manual value"}}}}
    if version < 3:
        command.pop("change")
        for key in ("editRevision", "editEpoch", "fieldVersions", "receipts", "receiptOrder"):
            old.pop(key)
    path = root / number.lower() / "documentation-scene.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = ("  " + json.dumps(old, indent=2) + "\n").encode("ascii")
    path.write_bytes(raw)
    return path, raw


def load(repo, document):
    return repo.read(document["product"]["assemblyNumber"], document["sourceRevision"], document["manualPlanRevision"],
                     identity_document=document)


def snapshot(repo, document):
    compile_identities(document)
    loaded = load(repo, document)
    current, scene = bind_document(document, loaded["scene"])
    current = project_document(current, scene)
    state = {**scene, "scene": scene, "documentId": document_id(KIND, NUMBER),
        "revision": scene["editRevision"], "sceneRevision": loaded["revision"], "aliasRevision": current["aliasRevision"]}
    targets = text_targets(state, current)
    return state, current, targets


def test_reorder_follows_ids(tmp_path):
    original = source_document()
    compile_identities(original)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    install_old(tmp_path)
    state, current, targets = snapshot(repo, original)
    edited = current["aliasMap"][PAGE]["table.r0.c1"]["targetId"]
    assert targets[edited]["text"] == "Manual value"
    reordered = deepcopy(original)
    reordered["pages"][0]["layoutBlocks"][0]["rows"].reverse()
    reordered["pages"][0]["layoutBlocks"][1]["items"].reverse()
    # Use the already migrated scene. A still-positional old file cannot be
    # reinterpreted against another compiler baseline at an unchanged binding.
    compiled, migrated = bind_document(reordered, state["scene"])
    after = text_targets({**state, "scene": migrated}, project_document(compiled, migrated))
    assert compiled["aliasMap"][PAGE]["table.r1.c1"]["targetId"] == edited
    assert after[edited]["text"] == "Manual value"
    assert after[compiled["aliasMap"][PAGE]["table.r0.c1"]["targetId"]]["text"] == "20"
    assert current["aliasMap"][PAGE]["steps.i0"]["targetId"] == compiled["aliasMap"][PAGE]["steps.i1"]["targetId"]


def test_duplicate_rows_are_not_guessed(tmp_path):
    doc = source_document()
    rows = doc["pages"][0]["layoutBlocks"][0]["rows"]
    rows[:] = [{"sourceKey": "repeated", "cells": ["Same", "same"]},
               {"sourceKey": "repeated", "cells": ["Same", "same"]}]
    compiled = compile_identities(doc)
    assert not compiled["aliasMap"][PAGE]["table.r0.c1"]["safe"]
    install_old(tmp_path, doc)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    loaded = load(repo, doc)
    assert loaded["scene"]["orphans"] and PAGE not in loaded["scene"]["pages"]
    # Explicit relation IDs distinguish shared sources; their order is immaterial.
    rows[0]["relationId"], rows[1]["relationId"] = "intake", "outlet"
    distinct = compile_identities(doc)
    before = [row["rowId"] for row in distinct["pages"][0]["layoutBlocks"][0]["rows"]]
    assert len(set(before)) == 2
    rows.reverse()
    after = compile_identities(doc)
    assert before[::-1] == [row["rowId"] for row in after["pages"][0]["layoutBlocks"][0]["rows"]]
    # Equal legacy fingerprints are still ambiguous despite newly assigned keys.
    assert after["aliasMap"][PAGE]["table.r0.c1"]["legacyAmbiguous"]


@pytest.mark.parametrize("version", [1, 2, 3])
def test_old_shape_no_save_on_read(tmp_path, version):
    document = source_document()
    compile_identities(document)
    path, raw = install_old(tmp_path, version=version)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    loaded = load(repo, document)
    assert loaded["scene"]["schemaVersion"] == 4
    stable = compiled_target(document, "table.r0.c1")
    command = loaded["scene"]["commands"][0]
    assert command["targetId"] == stable
    assert command["identityMigration"]["fingerprint"]
    assert command["identityMigration"]["sourceBinding"] == {"sourceRevision": SOURCE, "manualPlanRevision": PLAN}
    assert list(path.parent.iterdir()) == [path] and path.read_bytes() == raw
    again = DocumentationSceneRepository(tmp_path, KIND)
    assert load(again, document)["scene"] == loaded["scene"]
    result = repo.undo_change(NUMBER, SOURCE, PLAN, change_id="before-identities",
        expected_revision=loaded["scene"]["editRevision"], request_id="legacy-undo", identity_document=document)
    assert stable not in result["scene"]["pages"].get(PAGE, {}).get("pageElementOverrides", {})
    backup = "documentation-scene.v3.json" if version == 3 else "documentation-scene.v2.json"
    assert path.with_name(backup).read_bytes() == raw
    redo = repo.undo_change(NUMBER, SOURCE, PLAN, change_id=result["receipt"]["changeId"],
        expected_revision=result["scene"]["editRevision"], request_id="legacy-redo", identity_document=document)
    assert redo["scene"]["pages"][PAGE]["pageElementOverrides"][stable]["text"] == "Manual value"


def compiled_target(document, alias):
    return compile_identities(document)["aliasMap"][PAGE][alias]["targetId"]


def test_positional_alias_refused_after_reorder(tmp_path):
    repo, doc = DocumentationSceneRepository(tmp_path, KIND), source_document()
    state, current, targets = snapshot(repo, doc)
    reader = ReadBindings("before-reorder")
    reader.record(KIND, read_targets(state, targets, [{"pageId": PAGE, "targetId": "table.r0.c1"}]))
    write = reader.bind(KIND, {"edits": [{"pageId": PAGE, "targetId": "table.r0.c1", "text": "mine"}]})
    reordered = deepcopy(doc)
    reordered["pages"][0]["layoutBlocks"][0]["rows"].reverse()
    new = compile_identities(reordered)
    with pytest.raises(DocumentEditError) as error:
        check_alias_binding(write, {"aliasRevision": new["aliasRevision"]})
    assert error.value.code == "ambiguous_legacy_target"
    assert write["operations"][0]["targetId"] == current["aliasMap"][PAGE]["table.r0.c1"]["targetId"]
    assert not (tmp_path / NUMBER.lower()).exists()


def test_identity_stable_across_regeneration_and_restart():
    doc = source_document()
    before = compile_identities(doc)
    identity._CATALOGS.clear()  # No persistent IDs depend on process memory.
    after = compile_identities(json.loads(json.dumps(doc)))
    assert before["aliasMap"] == after["aliasMap"]
    assert compile_identities(before)["aliasMap"] == before["aliasMap"]
    moved = deepcopy(doc)
    moved["sourceRevision"], moved["manualPlanRevision"] = "new-source", "new-plan"
    moved["pages"][0]["pageId"] = "page-moved"
    moved["pages"][0]["layoutBlocks"][0]["rows"][0]["cells"][1] = "Different visible words"
    changed = compile_identities(moved)
    assert before["aliasMap"][PAGE]["table.r0.c1"]["targetId"] == changed["aliasMap"]["page-moved"]["table.r0.c1"]["targetId"]


@pytest.mark.parametrize("reason", ["missing", "changed-source", "changed-plan"])
def test_missing_or_changed_baseline_orphans_and_undo_refuses(tmp_path, reason):
    doc = source_document()
    path, raw = install_old(tmp_path)
    if reason == "changed-source":
        doc["sourceRevision"] = "other"
    if reason == "changed-plan":
        doc["manualPlanRevision"] = "other"
    repo = DocumentationSceneRepository(tmp_path, KIND)
    loaded = repo.read(NUMBER, doc["sourceRevision"], doc["manualPlanRevision"],
                       identity_document=None if reason == "missing" else doc)
    assert loaded["scene"]["orphans"][0]["command"]["text"] == "Manual value"
    with pytest.raises(DocumentEditError) as error:
        repo.undo_change(NUMBER, SOURCE, PLAN, change_id="before-identities", expected_revision=1, request_id="no-guess")
    assert error.value.code == "undo_conflict" and path.read_bytes() == raw


def test_deleted_identity_is_tombstoned_and_can_be_recovered():
    doc = source_document()
    compiled = compile_identities(doc)
    catalog = catalog_from(doc)
    scene = migrate_scene(DocumentationSceneRepository.new_scene(NUMBER, SOURCE, PLAN), catalog)
    removed = compiled["aliasMap"][PAGE]["table.r0.c1"]["targetId"]
    doc["pages"][0]["layoutBlocks"][0]["rows"].pop(0)
    compile_identities(doc)
    after = migrate_scene(scene, catalog_from(doc))
    assert after["identities"][removed]["state"] == "tombstone"
    column = compiled["pages"][0]["layoutBlocks"][0]["columnIds"][1]
    assert scene["identities"][column]["state"] == "active"
    doc["pages"][0]["layoutBlocks"].pop(0)
    compile_identities(doc)
    after = migrate_scene(after, catalog_from(doc))
    assert after["identities"][column]["state"] == "tombstone"


def test_slot_v2_byte_backup_and_deleted_row_tombstone(tmp_path):
    store = SlotStore(tmp_path, NUMBER)
    store.path.parent.mkdir()
    raw = b'{"schemaVersion":2,"values":{},"rows":[{"key":"fixture","label":"Fixture"}]}\n'
    store.path.write_bytes(raw)
    assert store.read()["schemaVersion"] == 3 and store.path.read_bytes() == raw
    store.set_rows([])
    assert store.path.with_name("slots.v2.json").read_bytes() == raw
    assert store.read()["identities"]["slot:spec.fixture.value"]["state"] == "tombstone"


@pytest.mark.parametrize("kind", ["illustrated_parts_manual", KIND, "work_instructions", "product_specification_sheet"])
def test_old_json_migration_with_real_compilers(tmp_path, monkeypatch, kind):
    import server
    from ai_inspector.parts_manual.document import build_manual_document
    from tests.test_parts_manual import _caster_fixture, _assembly_profile

    # All mutable roots stay under this test's own temporary directory.
    for key in ("PARTS_MANUAL_ROOT", "OPERATIONS_MANUAL_ROOT", "WORK_INSTRUCTION_ROOT", "SPECIFICATION_SHEET_ROOT", "INSPECTION_SHEET_ROOT"):
        monkeypatch.setattr(server, key, tmp_path / key, raising=False)
    if kind == "illustrated_parts_manual":
        rows, plan = _caster_fixture()
        def build(scene=None):
            return build_manual_document(plan, rows, _assembly_profile(), plan_revision="fixture-plan", documentation_scene=scene)
    else:
        assembly, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
        if kind == KIND:
            from ai_inspector.operations_manual.document import build_operations_manual_document
            def build(scene=None):
                return build_operations_manual_document(assembly, catalog, evidence_root=server.OPERATIONS_MANUAL_EVIDENCE_ROOT,
                                                        documentation_scene=scene)
        elif kind == "work_instructions":
            from ai_inspector.work_instructions.document import build_work_instruction_document
            package, revision = server._work_instruction_process_inputs(catalog)
            def build(scene=None):
                return build_work_instruction_document(assembly, catalog, resolved_package=package,
                    process_map_revision=revision, nomenclature_root=server.OPERATIONS_MANUAL_EVIDENCE_ROOT, documentation_scene=scene)
        else:
            def build(scene=None):
                return server._specification_sheet_compile(assembly, catalog, documentation_scene=scene)
    baseline = build()
    candidates = [(page, alias, entry) for page, aliases in baseline["aliasMap"].items()
                  for alias, entry in aliases.items() if entry.get("safe") and not entry.get("legacyAmbiguous")
                  and (".r0.c1" in alias or ".i0" in alias)]
    if kind == "illustrated_parts_manual":
        # Parts never generated positional BOM aliases. Fabricated old aliases
        # cannot be inferred from BOM offsets; definition-keyed fields stay intact.
        page, alias = baseline["pages"][0]["pageId"], "bom.r0.c1"
        stable = None
    else:
        assert candidates
        page, alias, entry = candidates[0]
        stable = entry["targetId"]
    root = tmp_path / "legacy"
    path, raw = install_old(root, baseline, page=page, alias=alias)
    repo = DocumentationSceneRepository(root, kind)
    loaded = load(repo, baseline)
    reopened = build(loaded["scene"])
    assert path.read_bytes() == raw and list(path.parent.iterdir()) == [path]
    if stable is None:
        assert loaded["scene"]["orphans"]
        assert all(row["cellIds"]["description"].startswith("part.") for p in reopened["pages"] for row in p.get("bom", []) if row.get("definitionId"))
    else:
        assert loaded["scene"]["commands"][0]["targetId"] == stable
        current_page = next(p for p in reopened["pages"] if p["pageId"] == page)
        if kind == "product_specification_sheet":
            assert reopened["slots"][stable.removeprefix("slot:")]["value"] == "Manual value"
        else:
            assert current_page["identityOverrides"][stable]["text"] == "Manual value"


def test_anonymous_items_have_revision_scoped_editable_ids():
    document = source_document()
    document["pages"][0]["layoutBlocks"][1]["items"] = [{"text": "Same"}, {"text": "Same"}]
    compiled = compile_identities(document)
    entries = [compiled["aliasMap"][PAGE]["steps.i" + str(i)] for i in range(2)]
    assert all(entry["safe"] and entry["scope"] == "revision" for entry in entries)
    assert len({entry["targetId"] for entry in entries}) == 2
    assert catalog_from(compiled) == catalog_from(document)
    # Text is not identity within a binding; refresh's future exact-value policy
    # must decide whether this edit can cross a binding change.
    document["pages"][0]["layoutBlocks"][1]["items"][0]["text"] = "Changed generated action"
    assert compile_identities(document)["aliasMap"][PAGE]["steps.i0"]["targetId"] == entries[0]["targetId"]
    document["sourceRevision"] = "different-source"
    assert compile_identities(document)["aliasMap"][PAGE]["steps.i0"]["targetId"] != entries[0]["targetId"]


def test_edit_after_page_move_uses_original_storage_address(tmp_path):
    doc = source_document()
    compile_identities(doc)
    install_old(tmp_path)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    loaded = load(repo, doc)
    stable = compiled_target(doc, "table.r0.c1")
    # First explicit write persists the migrated source addresses.
    repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=loaded["revision"],
        command={"operation": "update_text", "pageId": PAGE, "targetType": "page_element", "targetId": stable, "text": "First"},
        page_targets={PAGE: {"page_element": [stable]}}, identity_document=doc)
    moved = deepcopy(doc)
    moved["pages"][0]["pageId"] = "page-moved"
    compile_identities(moved)
    current = load(repo, moved)
    result = repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=current["revision"],
        command={"operation": "update_text", "pageId": "page-moved", "targetType": "page_element", "targetId": stable, "text": "Second"},
        page_targets={"page-moved": {"page_element": [stable]}}, identity_document=moved)
    assert result["command"]["pageId"] == PAGE
    compiled, _ = bind_document(moved, result["scene"])
    assert compiled["pages"][0]["identityOverrides"][stable]["text"] == "Second"
    assert "page-moved" not in result["scene"]["pages"]


def test_migrated_receipt_has_stable_addresses_and_retry_is_original():
    from ai_inspector.documentation.commands import prior_receipt
    doc = compile_identities(source_document())
    scene = DocumentationSceneRepository.new_scene(NUMBER, SOURCE, PLAN)
    legacy = identity._legacy_uuid(KIND, NUMBER, SOURCE, PLAN, PAGE, "table.r0.c1")
    receipt = {"changedIds": [legacy, PAGE + "/page_element/steps.i0"], "requestId": "retry"}
    scene["receipts"] = {"retry": {"receipt": deepcopy(receipt), "payloadHash": "original"}}
    scene["receiptOrder"] = ["retry"]
    current = migrate_scene(scene, catalog_from(doc))
    assert current["receipts"]["retry"]["receipt"]["changedIds"] == [
        doc["aliasMap"][PAGE]["table.r0.c1"]["targetId"], doc["aliasMap"][PAGE]["steps.i0"]["targetId"]]
    assert prior_receipt(current, "retry", "original") == receipt


def test_authored_identity_is_allocated_once_and_tombstoned(tmp_path):
    repo = DocumentationSceneRepository(tmp_path, KIND)
    state = repo.read(NUMBER, SOURCE, PLAN)
    object_id = "document-object-authored"
    targets = {PAGE: {"document_object": [object_id]}}
    result = repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=state["revision"],
        page_targets={PAGE: {"document_object": []}}, command={"operation": "add_object", "pageId": PAGE,
        "targetType": "document_object", "targetId": object_id,
        "documentObject": {"objectId": object_id, "type": "text", "name": "Note", "content": "Authored",
                           "frame": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}}})
    assert load(repo, source_document())["scene"]["identities"][object_id]["state"] == "active"
    result = repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=result["revision"], page_targets=targets,
        command={"operation": "remove_object", "pageId": PAGE, "targetType": "document_object", "targetId": object_id})
    assert result["scene"]["identities"][object_id]["state"] == "tombstone"


def test_column_roles_survive_column_reorder():
    original = source_document()
    before = compile_identities(original)["aliasMap"][PAGE]["table.r0.c1"]["targetId"]
    table = original["pages"][0]["layoutBlocks"][0]
    table["columnKeys"].reverse()
    table["columns"].reverse()
    for row in table["rows"]:
        row["cells"].reverse()
    assert compile_identities(original)["aliasMap"][PAGE]["table.r0.c0"]["targetId"] == before


def test_identity_migration_does_not_depend_on_display_text():
    document = source_document()
    first = compile_identities(document)
    for block in document["pages"][0]["layoutBlocks"]:
        for row in block.get("rows", []):
            row["cells"] = ["Changed label", "Changed value"]
        for item in block.get("items", []):
            item["text"] = "Completely different text"
    second = compile_identities(document)
    assert {alias: item["targetId"] for alias, item in first["aliasMap"][PAGE].items()} == {
        alias: item["targetId"] for alias, item in second["aliasMap"][PAGE].items()}


MMLE_ROUTES = [
    ("illustrated_parts_manual", "parts-manual"),
    (KIND, "operations-manual"),
    ("product_specification_sheet", "specification-sheet"),
    ("work_instructions", "work-instructions"),
]


@pytest.fixture
def mmle_client(tmp_path, monkeypatch):
    import server
    from fastapi.testclient import TestClient

    # The parts manual needs its approved plan, a local git-ignored input. Copy only that file into the
    # temporary root (never the saved scene), so every case starts from a fresh scene.
    plan = server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json"
    for key in ("PARTS_MANUAL_ROOT", "OPERATIONS_MANUAL_ROOT", "WORK_INSTRUCTION_ROOT",
                "SPECIFICATION_SHEET_ROOT", "INSPECTION_SHEET_ROOT"):
        monkeypatch.setattr(server, key, tmp_path / key)
    if plan.is_file():
        copied = server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json"
        copied.parent.mkdir(parents=True)
        copied.write_bytes(plan.read_bytes())
    monkeypatch.setattr(server, "_DOCUMENTATION_READ_BINDINGS", {})
    client = TestClient(server.app, base_url="http://127.0.0.1:8023")
    yield client
    client.close()


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_real_compiler_catalog_idempotence_and_mmle_inventory(mmle_client, monkeypatch, kind, route):
    from collections import Counter
    if route == "parts-manual":
        import server
        if not (server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json").is_file():
            pytest.skip("needs the local approved MMLE manual plan")

    raw_inputs = []
    compiler = identity.compile_identities
    def capture(document):
        if document["documentType"] == kind and "aliasMap" not in document:
            raw_inputs.append(deepcopy(document))
        return compiler(document)
    monkeypatch.setattr(identity, "compile_identities", capture)
    response = mmle_client.get(f"/api/{route}/MMLE-50D/documentation-scene")
    assert response.status_code == 200, response.text
    payload = response.json()
    raw, document = raw_inputs[0], payload["document"]
    first = compiler(raw)
    expected = catalog_from(raw)
    assert catalog_from(compiler(first)) == expected
    bound, _ = bind_document(raw, payload["scene"])
    assert catalog_from(bound) == expected
    assert catalog_from(document) == expected  # Includes real provenance/artifact projection.
    identity._CATALOGS.clear()
    assert catalog_from(document) == expected
    counts = Counter("unresolved" if row["state"] == "unresolved" else
                     "revisionScoped" if row["scope"] == "revision" else "sourceKeyed"
                     for row in expected["identities"].values())
    alias_counts = Counter("unresolved" if not row["safe"] else
                           "revisionScoped" if row["scope"] == "revision" else "sourceKeyed"
                           for aliases in expected["aliasMap"].values() for row in aliases.values())
    report = {"documentType": kind,
              "identities": {key: counts[key] for key in ("sourceKeyed", "revisionScoped", "unresolved")},
              "aliases": {key: alias_counts[key] for key in ("sourceKeyed", "revisionScoped", "unresolved")}}
    print("MMLE_IDENTITY_COUNTS " + json.dumps(report, sort_keys=True))
    assert counts["unresolved"] == 0 and alias_counts["unresolved"] == 0
    if kind == "work_instructions":
        actions = [entry for aliases in expected["aliasMap"].values() for alias, entry in aliases.items()
                   if "-actions.i" in alias and entry["scope"] == "revision"]
        assert len(actions) == 20
    for page, targets in payload["editableTargets"].items():
        for target in targets.get("page_element", []):
            entry = expected["aliasMap"].get(page, {}).get(target)
            assert entry is None or entry["safe"], (page, target)


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
@pytest.mark.parametrize("cache_action", ["clear", "evict"])
def test_workspace_first_alias_edit_survives_cache_loss(mmle_client, monkeypatch, kind, route, cache_action):
    if route == "parts-manual":
        import server
        if not (server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json").is_file():
            pytest.skip("needs the local approved MMLE manual plan")
    response = mmle_client.get(f"/api/{route}/MMLE-50D/documentation-scene")
    assert response.status_code == 200, response.text
    before = response.json()
    document = before["document"]
    entries = [(page, alias, entry) for page, aliases in document["aliasMap"].items()
               for alias, entry in aliases.items()
               if entry["safe"] and alias in before["editableTargets"].get(page, {}).get("page_element", [])]
    if kind == "illustrated_parts_manual":
        page, alias, entry = next(row for row in entries if row[1] == "header_title")
    elif kind == "work_instructions":
        page, alias, entry = next(row for row in entries if "-actions.i" in row[1] and row[2]["scope"] == "revision")
    else:
        page, alias, entry = next(row for row in entries if ".r0.c1" in row[1])
    identity._CATALOGS.clear()
    if cache_action == "evict":
        for index in range(40):
            unrelated = source_document()
            unrelated["product"]["assemblyNumber"] = f"UNRELATED-{index}"
            compile_identities(unrelated)
    def forbidden_cache_read(*args, **kwargs):
        raise AssertionError("A mutation must not read the diagnostic catalog cache")
    monkeypatch.setattr(identity, "catalog_for", forbidden_cache_read)
    # Also clear at the inner owner boundary, after the POST has compiled its document.
    apply = DocumentationSceneRepository.apply_command
    def cleared_apply(owner, *args, **kwargs):
        identity._CATALOGS.clear()
        assert kwargs.get("identity_document") is not None
        return apply(owner, *args, **kwargs)
    monkeypatch.setattr(DocumentationSceneRepository, "apply_command", cleared_apply)
    edited = mmle_client.post(f"/api/{route}/MMLE-50D/documentation-scene/commands", json={
        "baseRevision": before["revision"], "sourceRevision": document["sourceRevision"],
        "manualPlanRevision": document["manualPlanRevision"], "operation": "update_text",
        "pageId": page, "targetType": "page_element", "targetId": alias, "text": "Round 2 edited value"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["command"]["targetId"] == entry["targetId"]
    scene = edited.json()["scene"]
    assert any(values.get("pageElementOverrides", {}).get(entry["targetId"], {}).get("text") == "Round 2 edited value"
               for values in scene["pages"].values())
    # Named inverse must also receive an explicit catalogue after cache loss.
    import server
    identity._CATALOGS.clear()
    host = server._DocumentationAgentHost()
    inverse = host.undo_document_change("MMLE-50D", kind, {
        "changeId": edited.json()["command"]["change"]["changeId"],
        "expectedRevision": scene["editRevision"], "requestId": "round2-named-undo"}) if kind != "product_specification_sheet" else None
    if inverse:
        assert inverse["receipt"]["changedIds"]


def test_revision_scoped_action_hashes_and_named_undo(tmp_path):
    doc = source_document()
    doc["pages"][0]["layoutBlocks"][1]["items"] = [{"text": "Original action"}]
    repo = DocumentationSceneRepository(tmp_path, KIND)
    state, current, targets = snapshot(repo, doc)
    entry = current["aliasMap"][PAGE]["steps.i0"]
    before_hash = content_hash(state, entry["targetId"], hash_values(targets)[entry["targetId"]])
    from ai_inspector.documentation.provenance import prepare_text_command
    command = prepare_text_command(current, {"operation": "update_text", "pageId": PAGE,
        "targetType": "page_element", "targetId": "steps.i0", "text": "Edited action"})
    identity._CATALOGS.clear()
    result = repo.apply_batch(NUMBER, SOURCE, PLAN, base_revision=state["sceneRevision"], expected_revision=0,
        request_id="action-edit", commands=[command], page_targets={PAGE: {"page_element": ["steps.i0"]}},
        expected_hashes={entry["targetId"]: before_hash}, current_hashes={entry["targetId"]: before_hash},
        hashes_revision=state["sceneRevision"], identity_document=current)
    after, rendered, current_targets = snapshot(repo, doc)
    assert current_targets[entry["targetId"]]["text"] == "Edited action"
    assert content_hash(after, entry["targetId"], hash_values(current_targets)[entry["targetId"]]) != before_hash
    identity._CATALOGS.clear()
    repo.undo_change(NUMBER, SOURCE, PLAN, change_id=result["receipt"]["changeId"],
        expected_revision=after["revision"], request_id="action-undo", identity_document=rendered)
    assert snapshot(repo, doc)[2][entry["targetId"]]["text"] == "Original action"
    changed_binding = deepcopy(doc)
    changed_binding["manualPlanRevision"] = "new-plan"
    changed, _ = bind_document(changed_binding, result["scene"])
    assert changed["aliasMap"][PAGE]["steps.i0"]["targetId"] != entry["targetId"]
    assert not changed["pages"][0]["identityOverrides"]


def test_split_logical_values_are_revision_scoped_and_editable(tmp_path):
    from ai_inspector.operations_manual.flow import FlowLayoutEngine
    from ai_inspector.documentation.identity import editable_targets

    sections = [{"sectionId": "split", "title": "Split", "blocks": [
        {"blockId": "long-text", "blockType": "paragraph", "readingOrder": 1,
         "payload": {"text": "Long logical paragraph. " * 1200}},
        {"blockId": "long-row", "blockType": "table", "readingOrder": 2,
         "payload": {"columnKeys": ["label", "value"], "columns": ["Label", "Value"],
                     "rows": [{"sourceKey": "instruction", "cells": ["Label", "Long row value. " * 1200]}]}}]}]
    doc = source_document()
    doc["pages"] = FlowLayoutEngine().layout(sections)
    compiled = compile_identities(doc)
    paragraphs = [(page, block) for page in compiled["pages"] for block in page["layoutBlocks"]
                  if block.get("sourceBlockId") == "long-text"]
    assert len(paragraphs) > 1
    assert len({block["stableId"] for _, block in paragraphs}) == len(paragraphs)
    assert all(block["identityScope"] == "revision" for _, block in paragraphs)
    rows = [row for page in compiled["pages"] for block in page["layoutBlocks"] for row in block.get("rows", [])]
    assert len(rows) > 1 and len({row["rowId"] for row in rows}) == len(rows)
    assert all(row["identityScope"] == "revision" and row["identityStatus"] == "stable" for row in rows)
    assert catalog_from(compiled) == catalog_from(doc)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    loaded = load(repo, doc)
    page, block = paragraphs[0]
    targets = editable_targets(compiled, {page["pageId"]: {"page_element": [block["blockId"]]}})
    changed = repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=loaded["revision"],
        command={"operation": "update_text", "pageId": page["pageId"], "targetType": "page_element",
                 "targetId": block["blockId"], "text": "Edited fragment"}, page_targets=targets, identity_document=compiled)
    bound, _ = bind_document(doc, changed["scene"])
    assert bound["pages"][0]["identityOverrides"][block["stableId"]]["text"] == "Edited fragment"


def test_unresolved_targets_are_not_advertised_editable():
    from ai_inspector.documentation.identity import editable_targets
    doc = source_document()
    rows = doc["pages"][0]["layoutBlocks"][0]["rows"]
    rows[1]["sourceKey"] = rows[0]["sourceKey"]
    compiled = compile_identities(doc)
    advertised = editable_targets(compiled, {PAGE: {"page_element": ["table.r0.c1", "steps.i0"]}})
    assert "table.r0.c1" not in advertised[PAGE]["page_element"]
    assert "steps.i0" in advertised[PAGE]["page_element"]



def test_rebind_migrates_against_explicit_previous_catalog(tmp_path, monkeypatch):
    doc = source_document()
    install_old(tmp_path)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    stable = compiled_target(doc, "table.r0.c1")
    identity._CATALOGS.clear()
    monkeypatch.setattr(identity, "catalog_for", lambda *args: pytest.fail("cache read during rebind"))
    assert repo.rebind_manual_plan(NUMBER, SOURCE, PLAN, "plan-b", identity_document=doc)
    next_doc = {**doc, "manualPlanRevision": "plan-b"}
    loaded = load(repo, next_doc)
    assert loaded["scene"]["commands"][0]["targetId"] == stable
    rendered, _ = bind_document(next_doc, loaded["scene"])
    assert rendered["pages"][0]["identityOverrides"][stable]["text"] == "Manual value"


def test_bound_provenance_and_authored_objects_do_not_change_catalog(tmp_path):
    # A source-derived relation can remain identifiable after an unbound block's
    # provenance projection suppresses its active child claim/source IDs.
    doc = source_document()
    row = doc["pages"][0]["layoutBlocks"][0]["rows"][0]
    row.pop("sourceKey")
    row.update(claimIds=["claim-a"], sourceIds=["source-a"])
    compiled = compile_identities(doc)
    expected = catalog_from(compiled)
    projected = project_document(compiled, {"pages": {}})
    assert catalog_from(projected) == expected
    projected["pages"][0]["documentationObjects"] = {
        "document-object-existing": {"type": "text", "content": "Authored note"}}
    assert catalog_from(projected) == expected
    assert catalog_from(bind_document(projected, {"pages": {}})[0]) == expected


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_workspace_repeated_edits_and_undo_share_scene_free_baseline(mmle_client, kind, route):
    import server
    if route == "parts-manual" and not (server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json").is_file():
        pytest.skip("needs the local approved MMLE manual plan")
    url = f"/api/{route}/MMLE-50D/documentation-scene"
    response = mmle_client.get(url)
    assert response.status_code == 200, response.text
    current = response.json()
    document = current["document"]
    if route == "parts-manual":
        targets = [("page-cover", "header_title"), ("page-cover", "cover_subtitle")]
    elif route == "specification-sheet":
        targets = [(document["pages"][0]["pageId"], alias) for alias in ("spec-title", "spec-feature-2")]
    else:
        candidates = [(page, alias) for page, aliases in document["aliasMap"].items()
                      for alias, entry in aliases.items() if entry["safe"]
                      and alias in current["editableTargets"].get(page, {}).get("page_element", [])
                      and ("-actions.i" in alias if route == "work-instructions" else ".r" in alias and alias.endswith(".c1"))]
        targets = candidates[:2]
    assert len(targets) == 2

    def edit(state, target, text):
        page, alias = target
        result = mmle_client.post(url + "/commands", json={
            "baseRevision": state["revision"], "sourceRevision": document["sourceRevision"],
            "manualPlanRevision": document["manualPlanRevision"], "pageId": page,
            "targetType": "page_element", "operation": "update_text", "targetId": alias, "text": text})
        assert result.status_code == 200, result.text
        assert "identity_document" not in result.json()["document"]
        return result.json()

    first = edit(current, targets[0], "Round three first edit")
    second = edit(first, targets[1], "Round three second edit")
    reopened = mmle_client.get(url)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["revision"] == second["revision"]
    host = server._DocumentationAgentHost()
    snapshot = host.document_snapshot("MMLE-50D", kind)
    assert snapshot["state"]["aliasRevision"] == reopened.json()["scene"]["aliasRevision"]
    # Scene-free: work instructions stamp their pre-existing "baseline" sentinel when compiled without a scene.
    assert snapshot["identity_document"].get("documentationSceneRevision") in (None, "baseline")
    assert "Round three first edit" not in json.dumps(snapshot["identity_document"])
    undone = mmle_client.post(url + "/undo", json={
        "baseRevision": reopened.json()["revision"], "sourceRevision": document["sourceRevision"],
        "manualPlanRevision": document["manualPlanRevision"]})
    assert undone.status_code == 200, undone.text
    assert mmle_client.get(url).json()["revision"] == undone.json()["revision"]
    third = edit(undone.json(), targets[0], "Round three after undo")
    assert mmle_client.get(url).json()["revision"] == third["revision"]


def test_binding_leaves_owner_composition_untouched():
    doc = source_document()
    doc["pages"][0]["documentationComposition"] = {"ownerApplied": True}
    doc["pages"][0]["renderRequest"] = {"composition": {"ownerApplied": True}}
    scene = {"sourceRevision": SOURCE, "manualPlanRevision": PLAN,
             "pages": {PAGE: {"occurrenceOverrides": {"part-a": {"translation": [1, 0, 0]}}}}}
    bound, projected = bind_document(doc, scene)
    assert bound["pages"][0]["documentationComposition"] == {"ownerApplied": True}
    assert bound["pages"][0]["renderRequest"]["composition"] == {"ownerApplied": True}
    # The binder returns addresses; it does not decide an owner's cover policy.
    assert projected["pages"][PAGE]["occurrenceOverrides"]



def test_work_instruction_cover_keeps_owner_composition_policy(mmle_client):
    import server
    assembly, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    baseline = server._work_instruction_base_document(assembly, catalog)
    cover = next(page for page in baseline["pages"] if page["pageType"] == "operations_cover")
    occurrence = cover["renderRequest"]["occurrenceIds"][0]
    scene = {"pages": {cover["pageId"]: {
        "occurrenceOverrides": {occurrence: {"translation": [1.0, 2.0, 3.0]}},
        "manualGroupOverrides": {"group-a": {"translation": [1.0, 0.0, 0.0]}},
        "figureOverride": {"cameraPreset": "front"}}}}
    document = server._work_instruction_document_for_scene(assembly, catalog, scene=scene, scene_revision="cover-policy")
    rebuilt = next(page for page in document["pages"] if page["pageId"] == cover["pageId"])
    for composition in (rebuilt["documentationComposition"], rebuilt["renderRequest"]["composition"]):
        assert "occurrenceOverrides" not in composition and "manualGroupOverrides" not in composition
        assert composition["figureOverride"]["cameraPreset"] == "front"
