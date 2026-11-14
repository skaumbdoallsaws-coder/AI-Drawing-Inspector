"""Stable identities and owner-persisted three-way refresh contracts."""
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
    assert loaded["scene"]["schemaVersion"] == 8
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
    def capture(document, **kwargs):
        if document["documentType"] == kind and "aliasMap" not in document:
            raw_inputs.append(deepcopy(document))
        return compiler(document, **kwargs)
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


# P1c-2a: pure policy, owning-store transactions and real route recovery.
from ai_inspector.documentation.refresh import (
    inventory, refresh, three_way, exposure, REFRESH_RECEIPT_LIMIT,
)
from ai_inspector.documentation.commands import digest


def generated(value, evidence=None):
    payload = {"text": value}
    return {"payload": payload, "hash": digest(payload), "evidence": evidence or {}}


@pytest.mark.parametrize("old,current,new,policy", [
    ("B", "B", "N", "adopted"),
    ("B", "C", "B", "preserved"),
    ("B", "N", "N", "kept"),
    ("B", "C", "N", "value"),
    ("B", "B", "B", "kept"),
    (None, "C", "N", "missing_baseline"),
    (None, "N", "N", "kept"),
    ("B", "C", None, "orphan"),
])
def test_three_way_policy(old, current, new, policy):
    assert three_way(generated(old) if old is not None else None, {"text": current},
                     generated(new) if new is not None else None) == policy


def test_three_way_evidence_change_is_not_source_acceptance():
    assert three_way(generated("B", {"claimIds": ["old"]}), {"text": "C"},
                     generated("B", {"claimIds": ["new"]})) == "preserved"


def write_text(repo, doc, alias="table.r0.c1", text="Manual value"):
    doc = compile_identities(doc)
    loaded = load(repo, doc)
    key = doc["aliasMap"][PAGE][alias]["targetId"]
    return repo.apply_command(NUMBER, doc["sourceRevision"], doc["manualPlanRevision"],
        base_revision=loaded["revision"], identity_document=doc,
        page_targets={PAGE: {"page_element": [alias, key]}}, command={"operation": "update_text",
        "pageId": PAGE, "targetType": "page_element", "targetId": key, "text": text})


def next_source(doc, value="200"):
    result = deepcopy(doc)
    result["sourceRevision"] = "source-b"
    result["pages"][0]["layoutBlocks"][0]["rows"][0]["cells"][1] = value
    result["pages"][0]["layoutBlocks"][0]["rows"].reverse()
    return compile_identities(result)


def refresh_repo(repo, doc, **kwargs):
    return repo.refresh(NUMBER, doc["sourceRevision"], doc["manualPlanRevision"],
        base_revision=load(repo, doc)["revision"], identity_document=doc, **kwargs)


def test_first_baseline_is_retained_and_old_shape_read_does_not_save(tmp_path):
    doc = compile_identities(source_document())
    repo = DocumentationSceneRepository(tmp_path, KIND)
    first = write_text(repo, doc)
    key = compiled_target(doc, "table.r0.c1")
    original = deepcopy(first["scene"]["generatedBaseline"][key])
    second = write_text(repo, doc, text="Later manual value")
    assert second["scene"]["generatedBaseline"][key] == original
    path = repo._scene_path(NUMBER)
    old = json.loads(path.read_bytes())
    old.pop("generatedBaseline")
    path.write_text(json.dumps(old), encoding="ascii")
    raw = path.read_bytes()
    assert load(repo, doc)["scene"]["generatedBaseline"][key] == original
    assert path.read_bytes() == raw
    assert not list(path.parent.glob("sr-*.json"))


def test_conflict_persists_on_reopen(tmp_path):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    original = write_text(repo, doc)
    new = next_source(doc)
    refreshed = refresh_repo(repo, new)
    conflict = refreshed["conflicts"][0]
    assert conflict["kind"] == "value" and conflict["status"] == "open"
    assert [conflict[side]["payload"]["text"] for side in ("B", "C", "N")] == ["100", "Manual value", "200"]
    assert refreshed["openConflictCount"] == 1
    identity._CATALOGS.clear()
    reopened = load(DocumentationSceneRepository(tmp_path, KIND), new)
    assert reopened["conflicts"] == refreshed["conflicts"]
    assert reopened["revision"] == refreshed["revision"]
    key = compiled_target(doc, "table.r0.c1")
    bound, _ = bind_document(new, reopened["scene"])
    assert bound["pages"][0]["identityOverrides"][key]["text"] == "Manual value"
    # An old named inverse cannot bypass a current refresh conflict.
    with pytest.raises(DocumentEditError) as error:
        repo.undo_change(NUMBER, new["sourceRevision"], PLAN,
            change_id=original["command"]["commandId"], expected_revision=reopened["scene"]["editRevision"],
            request_id="blocked-inverse", identity_document=new)
    assert error.value.code == "manual_edit_conflict"


def test_refresh_is_idempotent_and_later_refresh_updates_only_proposal(tmp_path):
    repo = DocumentationSceneRepository(tmp_path, KIND)
    doc = source_document()
    write_text(repo, doc)
    new = next_source(doc)
    first = refresh_repo(repo, new)
    path = repo._scene_path(NUMBER)
    raw = path.read_bytes()
    repeat = refresh_repo(repo, new)
    assert repeat["refreshReceipt"] is None and path.read_bytes() == raw
    later = next_source(doc, "300")
    later["sourceRevision"] = "source-c"
    second = refresh_repo(repo, later)
    left, right = first["conflicts"][0], second["conflicts"][0]
    assert right["B"] == left["B"] and right["C"] == left["C"]
    assert right["conflictId"] == left["conflictId"]
    assert right["N"]["payload"]["text"] == "300"
    assert len(second["scene"]["refreshReceipts"]) == 2


def test_missing_baseline_preserves_orphan(tmp_path):
    doc = source_document()
    path, raw = install_old(tmp_path, doc)
    repo = DocumentationSceneRepository(tmp_path, KIND)
    new = next_source(doc)
    loaded = load(repo, new)
    assert path.read_bytes() == raw
    result = refresh_repo(repo, new)
    assert result["orphans"]
    orphan = result["orphans"][0]
    assert orphan["C"]["payload"]["text"] == "Manual value"
    assert orphan["link"]["status"] == "stale"


def test_stale_stable_edit_without_baseline_is_a_conflict(tmp_path):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    write_text(repo, doc)
    path = repo._scene_path(NUMBER)
    old = json.loads(path.read_bytes())
    old.pop("generatedBaseline")
    path.write_text(json.dumps(old), encoding="ascii")
    result = refresh_repo(repo, next_source(doc))
    conflict = result["conflicts"][0]
    assert conflict["kind"] == "missing_baseline" and conflict["B"] is None
    assert conflict["targetId"] not in result["scene"].get("generatedBaseline", {})
    assert conflict["C"]["payload"]["text"] == "Manual value"


@pytest.mark.parametrize("change,deleted", [(False, False), (True, False), (False, True)])
def test_revision_scoped_refresh_uses_exact_value_only(tmp_path, change, deleted):
    doc = source_document()
    doc["pages"][0]["layoutBlocks"][1]["items"] = [{"text": "Exact original action"}]
    repo = DocumentationSceneRepository(tmp_path, KIND)
    original = write_text(repo, doc, alias="steps.i0")
    new = next_source(doc, "100")
    if change:
        new["pages"][0]["layoutBlocks"][1]["items"][0]["text"] += " "
    if deleted:
        new["pages"][0]["layoutBlocks"][1]["items"] = []
    refreshed = refresh_repo(repo, new)
    if deleted:
        assert refreshed["orphans"][0]["reason"] == "parent_or_ordinal_deleted"
    elif change:
        assert refreshed["conflicts"][0]["kind"] == "revision_scoped"
    else:
        assert refreshed["openConflictCount"] == 0
        assert refreshed["refreshReceipt"]["counts"]["carriedRevisionScoped"] == 1
        key = compile_identities(new)["aliasMap"][PAGE]["steps.i0"]["targetId"]
        assert refreshed["scene"]["pages"][PAGE]["pageElementOverrides"][key]["text"] == "Manual value"
        assert original["command"]["targetId"] != key


def test_deleted_part_keeps_commentary(tmp_path):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    write_text(repo, doc)
    current = load(repo, doc)
    note = {"objectId": "document-object-note", "type": "text", "name": "Service note", "content": "Keep my note",
            "frame": {"x": .1, "y": .2, "width": .3, "height": .1}}
    repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=current["revision"], identity_document=doc,
        page_targets={PAGE: {"document_object": []}}, command={"operation": "add_object", "pageId": PAGE,
        "targetType": "document_object", "targetId": note["objectId"], "documentObject": note})
    before = load(repo, doc)["scene"]["pages"][PAGE]["documentObjects"]
    new = next_source(doc)
    new["pages"][0]["layoutBlocks"][0]["rows"] = []
    result = refresh_repo(repo, new)
    assert result["orphans"][0]["C"]["payload"]["text"] == "Manual value"
    assert result["scene"]["pages"][PAGE]["documentObjects"] == before
    # If the containing page disappears, frame, order and identity are unplaced intact.
    newer = {**new, "sourceRevision": "source-c", "pages": []}
    gone = refresh_repo(repo, newer)
    orphan = next(o for o in gone["orphans"] if o.get("targetId") == note["objectId"])
    assert orphan["C"]["payload"] == before[note["objectId"]]


def test_failed_generation_commits_nothing(tmp_path):
    repo = DocumentationSceneRepository(tmp_path, KIND)
    doc = source_document()
    write_text(repo, doc)
    path = repo._scene_path(NUMBER)
    raw = path.read_bytes()
    def failed(candidate):
        raise ValueError("Compiler failed after staging")
    with pytest.raises(ValueError, match="Compiler failed"):
        refresh_repo(repo, next_source(doc), validate_candidate=failed)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("operation", ["command", "batch", "confirmation", "named_undo", "history"])
def test_open_conflict_refuses_every_scene_write(tmp_path, operation):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    original = write_text(repo, doc)
    new = next_source(doc)
    current = refresh_repo(repo, new)
    key = compiled_target(doc, "table.r0.c1")
    command = {"operation": "update_text", "pageId": PAGE, "targetType": "page_element", "targetId": key, "text": "Blocked"}
    raw = repo._scene_path(NUMBER).read_bytes()
    with pytest.raises(DocumentEditError) as error:
        if operation == "command":
            repo.apply_command(NUMBER, new["sourceRevision"], PLAN, base_revision=current["revision"], command=command,
                page_targets={PAGE: {"page_element": [key]}}, identity_document=new)
        elif operation in {"batch", "confirmation"}:
            repo.apply_batch(NUMBER, new["sourceRevision"], PLAN, base_revision=current["revision"],
                expected_revision=current["scene"]["editRevision"], request_id=operation,
                commands=[command], page_targets={PAGE: {"page_element": [key]}},
                expected_hashes={key: "hash"}, current_hashes={key: "hash"}, hashes_revision=current["revision"],
                allow_confirmation=operation == "confirmation", identity_document=new)
        elif operation == "named_undo":
            repo.undo_change(NUMBER, new["sourceRevision"], PLAN, change_id=original["command"]["commandId"],
                expected_revision=current["scene"]["editRevision"], request_id="blocked", identity_document=new)
        else:
            repo.move_history(NUMBER, new["sourceRevision"], PLAN, base_revision=current["revision"], direction="undo", identity_document=new)
    assert error.value.code == "manual_edit_conflict"
    assert repo._scene_path(NUMBER).read_bytes() == raw


def test_reset_requires_preview_and_user_and_keeps_recovery(tmp_path):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    write_text(repo, doc)
    preview = repo.reset_preview(NUMBER, SOURCE, PLAN, identity_document=doc)
    assert preview["counts"]["targets"] == 1
    raw = repo._scene_path(NUMBER).read_bytes()
    options = dict(base_revision=preview["expectedRevision"], preview_hash=preview["previewHash"], identity_document=doc)
    with pytest.raises(DocumentEditError):
        repo.rebaseline(NUMBER, SOURCE, PLAN, **options)
    result = repo.rebaseline(NUMBER, SOURCE, PLAN, user_authorized=True, **options)
    assert result["scene"]["pages"] == {} and result["scene"]["commands"] == []
    backup = repo._scene_path(NUMBER).with_name("sr-" + result["recoveryId"] + ".json")
    assert backup.read_bytes() == raw


def test_refresh_receipts_are_bounded():
    doc = compile_identities(source_document())
    state = DocumentationSceneRepository.new_scene(NUMBER, "old", PLAN)
    for index in range(REFRESH_RECEIPT_LIMIT + 2):
        doc["sourceRevision"] = str(index)
        state, receipt = refresh(state, doc, refresh_id="r-" + str(index), actor="user", at="time")
    assert len(state["refreshReceipts"]) == REFRESH_RECEIPT_LIMIT
    assert state["refreshReceipts"][0]["refreshId"] == "r-2"


def slot_document(value="Generated title", source=SOURCE):
    return compile_identities({"schemaVersion": 3, "documentType": "product_specification_sheet",
        "product": {"assemblyNumber": NUMBER}, "sourceRevision": source, "manualPlanRevision": PLAN,
        "slots": {"title": {"value": value, "source": "library", "default": {"value": value, "source": "library"}}},
        "pages": [{"pageId": "page-product-specification", "pageNumber": 1, "layoutBlocks": [
            {"blockId": "spec-title", "blockType": "paragraph", "slot": "title", "text": value}]}]})


def test_p1c1_slot_shape_derives_baseline_without_writing(tmp_path):
    store = SlotStore(tmp_path, NUMBER)
    store.path.parent.mkdir(parents=True)
    raw = (FIXTURE.parent / "slots-v3-pre-refresh.json").read_bytes()
    store.path.write_bytes(raw)
    doc = slot_document()
    state = store.read(identity_document=doc, binding_is_current=True)
    assert state["values"]["title"]["value"] == "Old manual title"
    assert state["generatedBaseline"]["slot:title"]["payload"] == {"value": "Generated title"}
    assert store.path.read_bytes() == raw
    store.identity_document, store.binding = doc, {"sourceRevision": SOURCE, "manualPlanRevision": PLAN}
    store.set_values([{"slot": "title", "value": "Second title"}], "workspace")
    assert store.read()["generatedBaseline"]["slot:title"]["payload"] == {"value": "Generated title"}


@pytest.mark.parametrize("operation", ["value", "batch", "accept", "confirmation", "undo", "redo", "rows"])
def test_specification_slot_conflict_blocks_all_mutations(tmp_path, operation):
    doc = slot_document()
    store = SlotStore(tmp_path, NUMBER)
    store.identity_document, store.binding = doc, {"sourceRevision": SOURCE, "manualPlanRevision": PLAN}
    store.set_values([{"slot": "title", "value": "Manual title"}], "sage_draft")
    change = store.last_receipt["changeId"]
    new = slot_document("New generated title", "source-b")
    store.refresh(new, expected_revision=store.read()["editRevision"])
    store.identity_document, store.binding = new, {"sourceRevision": "source-b", "manualPlanRevision": PLAN}
    raw = store.path.read_bytes()
    conflict = store.read()["conflicts"][0]
    assert conflict["B"]["payload"] == {"value": "Generated title"}
    assert conflict["C"]["payload"] == {"value": "Manual title"}
    assert SlotStore(tmp_path, NUMBER).read()["conflicts"] == [conflict]
    with pytest.raises(DocumentEditError) as error:
        if operation == "value":
            store.set_values([{"slot": "title", "value": "Blocked"}], "workspace")
        elif operation == "batch":
            store.apply_batch([{"slot": "title", "value": "Blocked"}], "sage_draft",
                expected_revision=store.read()["editRevision"], request_id="blocked-slot",
                expected_hashes={"slot:title": "hash"}, current_hashes={"slot:title": "hash"})
        elif operation == "accept":
            store.accept(["title"], "user")
        elif operation == "confirmation":
            store.confirm_values([], by="user", expected_revision=store.read()["editRevision"], request_id="confirm-blocked",
                expected_hashes={"slot:title": "hash"}, current_hashes={"slot:title": "hash"}, payload={})
        elif operation in {"undo", "redo"}:
            # Both named undo and redo are the same guarded inverse API. Supply
            # the selected record even when its old source binding has changed.
            store.undo_change(change, expected_revision=store.read()["editRevision"], request_id=operation)
        else:
            store.set_rows([])
    assert error.value.code == "manual_edit_conflict"
    assert store.path.read_bytes() == raw


def workspace_edit(client, url, state, page, target, text):
    result = client.post(url + "/commands", json={"baseRevision": state["revision"],
        "sourceRevision": state["document"]["sourceRevision"], "manualPlanRevision": state["document"]["manualPlanRevision"],
        "pageId": page, "targetType": "page_element", "operation": "update_text", "targetId": target, "text": text})
    assert result.status_code == 200, result.text
    return result.json()


def _parts_route_conflict(mmle_client, monkeypatch):
    import server
    if not (server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json").is_file():
        pytest.skip("needs the local approved MMLE manual plan")
    url = "/api/parts-manual/MMLE-50D/documentation-scene"
    state = mmle_client.get(url).json()
    page, row = next((p, r) for p in state["document"]["pages"] for r in p.get("bom", []) if r.get("definitionId"))
    target = row["cellIds"]["description"]
    state = workspace_edit(mmle_client, url, state, page["pageId"], target, "Manual service description")
    note_page = state["document"]["pages"][0]["pageId"]
    note_target = state["document"]["aliasMap"][note_page]["cover_subtitle"]["targetId"]
    state = workspace_edit(mmle_client, url, state, note_page, note_target, "Unrelated service note")
    old_source = state["document"]["sourceRevision"]
    assembly, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    catalog = deepcopy(catalog)
    # Parts plans require a SHA-256 source revision.
    catalog["sourceRevision"] = __import__("hashlib").sha256(b"fixture-refreshed-source").hexdigest()
    catalog["occurrences"].reverse()
    for occurrence in catalog["occurrences"]:
        if occurrence.get("definitionId") == row["definitionId"]:
            occurrence["description"] = "Changed generated description"
            occurrence["displayPartNumber"] = "ZZZ-reordered-definition"
            occurrence["partNumber"] = "ZZZ-reordered-definition"
    monkeypatch.setattr(server, "_parts_manual_catalog_for_assembly", lambda number: (assembly, deepcopy(catalog)))
    assert mmle_client.get(url).status_code == 409
    preview = mmle_client.get(url + "/refresh")
    assert preview.status_code == 200, preview.text
    binding = {key: preview.json()[key] for key in ("expectedRevision", "expectedPlanRevision")}
    result = mmle_client.post(url + "/refresh", json=binding)
    assert result.status_code == 200, result.text
    refreshed = result.json()
    conflict = next(c for c in refreshed["conflicts"] if c["targetId"] == target)
    assert conflict["kind"] == "value" and conflict["C"]["payload"]["text"] == "Manual service description"
    assert conflict["N"]["payload"]["text"] == "Changed generated description"
    assert refreshed["refreshReceipt"]["fromBinding"]["sourceRevision"] == old_source
    identity._CATALOGS.clear()
    monkeypatch.setattr(server, "_DOCUMENTATION_READ_BINDINGS", {})
    reopened = mmle_client.get(url)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["conflicts"] == refreshed["conflicts"]
    snapshot = server._DocumentationAgentHost().document_snapshot("MMLE-50D", "illustrated_parts_manual")
    assert snapshot["targets"][note_target]["text"] == "Unrelated service note"
    assert snapshot["targets"][target]["text"] == "Manual service description"
    read = read_targets(snapshot["state"], snapshot["targets"], [{"targetId": target}])
    assert read["openConflictCount"] == 1 and read["targets"][0]["hasOpenConflict"]
    raw = (server.PARTS_MANUAL_ROOT / "mmle-50d" / "documentation-scene.json").read_bytes()
    again = mmle_client.get(url + "/refresh").json()
    repeat = mmle_client.post(url + "/refresh", json={k: again[k] for k in binding})
    assert repeat.status_code == 200 and repeat.json()["refreshReceipt"] is None
    assert (server.PARTS_MANUAL_ROOT / "mmle-50d" / "documentation-scene.json").read_bytes() == raw


def test_parts_route_refresh_keeps_note_and_persists_description_conflict(mmle_client, monkeypatch):
    _parts_route_conflict(mmle_client, monkeypatch)


def test_parts_plan_carry_refuses_missing_occurrences_without_partial_write(mmle_client, monkeypatch):
    import server
    plan_path = server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json"
    if not plan_path.is_file():
        pytest.skip("needs the local approved MMLE manual plan")
    raw = plan_path.read_bytes()
    plan = json.loads(raw)
    missing = plan["sections"][0]["occurrenceIds"][0]
    assembly, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    catalog = deepcopy(catalog)
    catalog["sourceRevision"] = "missing-source"
    catalog["occurrences"] = [row for row in catalog["occurrences"] if row["occurrenceId"] != missing]
    monkeypatch.setattr(server, "_parts_manual_catalog_for_assembly", lambda number: (assembly, catalog))
    response = mmle_client.post("/api/parts-manual/MMLE-50D/documentation-scene/refresh", json={})
    assert response.status_code == 409
    assert missing in response.json()["details"]["missingOccurrences"]
    assert plan_path.read_bytes() == raw
    assert not (plan_path.parent / "documentation-scene.json").exists()


def test_rebind_manual_plan_still_preserves_captures(tmp_path, monkeypatch):
    from tests.test_parts_manual import test_moving_parts_between_sections_recaptures_only_the_figures_it_changes
    test_moving_parts_between_sections_recaptures_only_the_figures_it_changes(tmp_path, monkeypatch)


def test_reset_route_requires_user_boundary_and_preview(mmle_client, monkeypatch):
    import server
    from types import SimpleNamespace
    kind = KIND
    scene_url = "/api/operations-manual/MMLE-50D/documentation-scene"
    state = mmle_client.get(scene_url).json()
    page, alias = next((page, alias) for page, entries in state["document"]["aliasMap"].items()
                       for alias, info in entries.items() if info.get("safe") and alias.endswith(".r0.c1"))
    workspace_edit(mmle_client, scene_url, state, page, alias, "Reset this manual value")
    url = "/api/documentation/" + kind + "/MMLE-50D/reset"
    preview = mmle_client.get(url)
    assert preview.status_code == 200, preview.text
    body = {key: preview.json()[key] for key in ("expectedRevision", "previewHash")}
    assert mmle_client.post(url, json=body, headers={"origin": "https://untrusted.invalid"}).status_code == 403
    assert mmle_client.post(url, json={**body, "actor": "sage"}).status_code == 422
    monkeypatch.setattr(server, "_FACILITY_PRINCIPAL_RESOLVER", lambda request: SimpleNamespace(principal_id="reviewer"))
    result = mmle_client.post(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["resetBy"] == "reviewer" and result.json()["recoveryId"]
    assert not hasattr(server._DocumentationAgentHost(), "reset_document")


def test_real_specification_slot_refresh_and_sage_batch_refusal(mmle_client, monkeypatch):
    import server
    from ai_inspector.specification_sheet import document as compiler
    url = "/api/specification-sheet/MMLE-50D"
    response = mmle_client.post(url + "/values", json={"values": [{"slot": "feature.1.text", "value": "Manual feature value"}]})
    assert response.status_code == 200, response.text
    original_profile = compiler._read_profile
    def changed_profile(*args, **kwargs):
        profile = deepcopy(original_profile(*args, **kwargs))
        profile["features"][0]["text"] = "New generated feature value"
        return profile
    monkeypatch.setattr(compiler, "_read_profile", changed_profile)
    refreshed = mmle_client.post(url + "/generate?rebaseline=true")
    assert refreshed.status_code == 200, refreshed.text
    payload = refreshed.json()
    conflict = next(c for c in payload["conflicts"] if c["targetId"] == "slot:feature.1.text")
    assert conflict["kind"] == "value"
    assert conflict["C"]["payload"] == {"value": "Manual feature value"}
    assert conflict["N"]["payload"] == {"value": "New generated feature value"}
    assert payload["document"]["slots"]["feature.1.text"]["value"] == "Manual feature value"
    identity._CATALOGS.clear()
    assert mmle_client.get(url + "/documentation-scene").json()["conflicts"] == payload["conflicts"]
    refused = mmle_client.post(url + "/values", json={"values": [{"slot": "feature.1.text", "value": "Blocked"}]})
    assert refused.status_code == 409 and refused.json()["error"] == "manual_edit_conflict"
    # The old viewport command is an alternate address for the same native slot.
    current = mmle_client.get(url + "/documentation-scene").json()
    page = current["document"]["pages"][0]
    block = next(b for b in page["layoutBlocks"] if (b.get("slots") or {}).get("text") == "feature.1.text")
    refused = mmle_client.post(url + "/documentation-scene/commands", json={
        "baseRevision": current["revision"], "sourceRevision": current["document"]["sourceRevision"],
        "manualPlanRevision": current["document"]["manualPlanRevision"], "pageId": page["pageId"],
        "operation": "update_text", "targetType": "page_element", "targetId": block["blockId"], "text": "Blocked"})
    assert refused.status_code == 409 and refused.json()["error"] == "manual_edit_conflict"
    host, kind = server._DocumentationAgentHost(), "product_specification_sheet"
    snapshot = host.document_snapshot("MMLE-50D", kind)
    read = read_targets(snapshot["state"], snapshot["targets"], [{"targetId": "slot:feature.1.text"}])
    assert read["openConflictCount"] == 1 and read["targets"][0]["hasOpenConflict"]
    reader = ReadBindings("refresh-conflict")
    reader.record(kind, read)
    observed = reader.bind_operations(kind, {"documentId": read["documentId"], "expectedRevision": read["revision"],
        "requestId": "blocked-refresh-batch", "operations": [{"operation": "set_slot_value", "targetId": "slot:feature.1.text",
        "value": "Blocked", "expectedContentHash": read["targets"][0]["contentHash"]}]})
    with pytest.raises(DocumentEditError) as error:
        host.apply_document_edits("MMLE-50D", kind, observed)
    assert error.value.code == "manual_edit_conflict"


@pytest.mark.parametrize("route,kind", [("operations-manual", KIND), ("work-instructions", "work_instructions")])
def test_failed_regeneration_route_keeps_original_bytes(mmle_client, monkeypatch, route, kind):
    import server
    url = "/api/" + route + "/MMLE-50D"
    state = mmle_client.get(url + "/documentation-scene").json()
    page, alias = next((p, a) for p, entries in state["document"]["aliasMap"].items() for a, entry in entries.items()
                       if entry.get("safe") and (a.endswith(".r0.c1") if route == "operations-manual" else "-actions.i0" in a))
    workspace_edit(mmle_client, url + "/documentation-scene", state, page, alias, "Keep on failed generation")
    repository = server._DocumentationAgentHost()._edit_repository(kind)
    path = repository._scene_path("MMLE-50D")
    raw = path.read_bytes()
    assembly, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    catalog = deepcopy(catalog)
    catalog["sourceRevision"] = "changed-fixture-source"
    monkeypatch.setattr(server, "_parts_manual_catalog_for_assembly", lambda number: (assembly, catalog))
    name = "build_operations_manual_document" if route == "operations-manual" else "_work_instruction_document_for_scene"
    compiler = getattr(server, name)
    def fail_after_baseline(*args, **kwargs):
        if kwargs.get("documentation_scene") is not None or kwargs.get("scene") is not None:
            raise ValueError("fixture compiler validation failed")
        return compiler(*args, **kwargs)
    monkeypatch.setattr(server, name, fail_after_baseline)
    response = mmle_client.post(url + "/generate?rebaseline=true")
    assert response.status_code == 422, response.text
    assert path.read_bytes() == raw


def test_refresh_adopts_generated_payload_but_preserves_formatting(tmp_path):
    doc = source_document()
    table = doc["pages"][0]["layoutBlocks"][0]
    table["evidenceBindingVersion"] = 1
    table["rows"][0].update(claimIds=["capacity-claim"], sourceIds=["capacity-source"])
    repo = DocumentationSceneRepository(tmp_path, KIND)
    first = write_text(repo, doc, text="100")
    key = compiled_target(doc, "table.r0.c1")
    repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=first["revision"], identity_document=doc,
        page_targets={PAGE: {"page_element": [key]}}, command={"operation": "update_style", "pageId": PAGE,
        "targetType": "page_element", "targetId": key, "style": {"fontWeight": 700}})
    refreshed = refresh_repo(repo, next_source(doc))
    override = refreshed["scene"]["pages"][PAGE]["pageElementOverrides"][key]
    assert "text" not in override and override["style"]["fontWeight"] == 700
    assert refreshed["scene"]["generatedBaseline"][key]["payload"] == {"text": "200"}
    assert not refreshed["conflicts"]
    compiled, scene = bind_document(next_source(doc), refreshed["scene"])
    projected = project_document(compiled, scene)
    row = next(r for r in projected["pages"][0]["layoutBlocks"][0]["rows"] if r["sourceKey"] == "capacity")
    # Adoption takes exactly the generated row: the same projection as the new source with no scene.
    generated_compiled, generated_scene = bind_document(next_source(doc), None)
    generated = next(r for r in project_document(generated_compiled, generated_scene)["pages"][0]["layoutBlocks"][0]["rows"]
                     if r["sourceKey"] == "capacity")
    for key in ("cells", "claimIds", "sourceIds", "activeEvidenceClaimIds", "provenance"):
        assert row.get(key) == generated.get(key), key


@pytest.mark.parametrize("route,kind", [("operations-manual", KIND), ("work-instructions", "work_instructions")])
def test_real_regeneration_preserves_edits(mmle_client, monkeypatch, route, kind):
    import server
    url = "/api/" + route + "/MMLE-50D"
    state = mmle_client.get(url + "/documentation-scene").json()
    page, alias = next((p, a) for p, entries in state["document"]["aliasMap"].items() for a, entry in entries.items()
                       if entry.get("safe") and (a == "spec-table-1.r0.c1" if route == "operations-manual"
                                                 else "-actions.i" in a and entry.get("scope") == "revision"))
    workspace_edit(mmle_client, url + "/documentation-scene", state, page, alias, "Survives regeneration")
    assembly, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    catalog = deepcopy(catalog)
    catalog["sourceRevision"] = "new-fixture-source"
    monkeypatch.setattr(server, "_parts_manual_catalog_for_assembly", lambda number: (assembly, catalog))
    response = mmle_client.post(url + "/generate?rebaseline=true")
    assert response.status_code == 200, response.text
    identity._CATALOGS.clear()
    snapshot = server._DocumentationAgentHost().document_snapshot("MMLE-50D", kind)
    key = snapshot["document"]["aliasMap"][page][alias]["targetId"]
    assert snapshot["targets"][key]["text"] == "Survives regeneration"
    assert response.json()["openConflictCount"] == 0
    if kind == "work_instructions":
        assert response.json()["refreshReceipt"]["counts"]["carriedRevisionScoped"] >= 1


def test_refresh_validation_failure_and_denied_replace_are_atomic(tmp_path, monkeypatch):
    import ai_inspector.parts_manual.documentation as owner
    repo = DocumentationSceneRepository(tmp_path, KIND)
    doc = source_document()
    write_text(repo, doc)
    raw = repo._scene_path(NUMBER).read_bytes()
    original = owner._write_atomic
    def denied(path, payload):
        if path == repo._scene_path(NUMBER):
            raise PermissionError("fixture denied replace")
        return original(path, payload)
    monkeypatch.setattr(owner, "_write_atomic", denied)
    with pytest.raises(PermissionError):
        refresh_repo(repo, next_source(doc))
    assert repo._scene_path(NUMBER).read_bytes() == raw


def test_invalid_refresh_metadata_refuses_without_rewriting(tmp_path):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    write_text(repo, doc)
    path = repo._scene_path(NUMBER)
    stored = json.loads(path.read_bytes())
    key = next(iter(stored["generatedBaseline"]))
    stored["generatedBaseline"][key]["hash"] = "corrupt"
    path.write_text(json.dumps(stored), encoding="ascii")
    raw = path.read_bytes()
    with pytest.raises(DocumentEditError) as error:
        load(repo, doc)
    assert error.value.code == "unsupported_document_schema" and path.read_bytes() == raw


def test_refresh_advances_baseline_after_earlier_undo(tmp_path):
    doc = source_document()
    repo = DocumentationSceneRepository(tmp_path, KIND)
    changed = write_text(repo, doc)
    repo.move_history(NUMBER, SOURCE, PLAN, base_revision=changed["revision"], direction="undo", identity_document=doc)
    new = next_source(doc)
    refreshed = refresh_repo(repo, new)
    key = compiled_target(doc, "table.r0.c1")
    assert refreshed["scene"]["generatedBaseline"][key]["payload"] == {"text": "200"}
    assert refreshed["openConflictCount"] == 0


def test_slot_reset_keeps_recovery_and_refuses_stale_preview(tmp_path):
    store = SlotStore(tmp_path, NUMBER)
    store.set_values([{"slot": "title", "value": "Manual"}], "workspace")
    preview = store.reset_preview()
    raw = store.path.read_bytes()
    with pytest.raises(DocumentEditError):
        store.reset(expected_revision=preview["expectedRevision"], preview_hash=preview["previewHash"])
    with pytest.raises(DocumentEditError):
        store.reset(expected_revision=preview["expectedRevision"] - 1, preview_hash=preview["previewHash"], user_authorized=True)
    result = store.reset(expected_revision=preview["expectedRevision"], preview_hash=preview["previewHash"], user_authorized=True)
    assert store.read()["values"] == {} and store.read()["journal"] == []
    assert store.path.with_name("sl-" + result["recoveryId"] + ".json").read_bytes() == raw


def test_authored_slot_rows_keep_values_and_order_without_generated_baseline(tmp_path):
    store = SlotStore(tmp_path, NUMBER)
    store.transaction(lambda candidate: (candidate.set_rows([{"key": "note", "label": "Service note", "source": "workspace"}]),
        candidate.set_values([{"slot": "spec.note.value", "value": "Authored value"}], "workspace")))
    before = store.read()
    assert "generatedBaseline" not in before
    store.refresh(slot_document(source="source-b"), expected_revision=before["editRevision"])
    after = store.read()
    assert after["rows"] == before["rows"] and after["values"] == before["values"]
    assert not after["conflicts"] and after["identities"]["slot:spec.note.value"]["ownership"] == "authored"


# P1c-2b: one resolution transaction, shared by HTTP and Sage, with guarded inverses.
from types import SimpleNamespace
from ai_inspector.documentation.resolution import conflict_hash, with_hash, RESOLUTION_HISTORY_LIMIT


@pytest.fixture(params=["scene", "slots"])
def resolution_case(tmp_path, request):
    slots = request.param == "slots"
    if slots:
        old = slot_document()
        old["slots"]["title"]["claimIds"] = ["claim-title"]
        new = slot_document("New generated title", "source-b")
        new["slots"]["title"]["claimIds"] = ["claim-title-new"]
        owner = SlotStore(tmp_path, NUMBER)
        owner.identity_document, owner.binding = old, {"sourceRevision": SOURCE, "manualPlanRevision": PLAN}
        owner.set_values([{"slot": "title", "value": "Manual value"}], "workspace")
        owner.refresh(new, expected_revision=owner.read()["editRevision"])
        owner.identity_document, owner.binding = new, {"sourceRevision": "source-b", "manualPlanRevision": PLAN}
        key, kind, path = "slot:title", "product_specification_sheet", owner.path
    else:
        old = source_document()
        old["pages"][0]["layoutBlocks"][0]["evidenceBindingVersion"] = 1
        old["pages"][0]["layoutBlocks"][0]["rows"][0].update(claimIds=["capacity"], sourceIds=["source"])
        old = project_document(compile_identities(old), {"pages": {}})
        new = next_source(old)
        owner = DocumentationSceneRepository(tmp_path, KIND)
        write_text(owner, old)
        refresh_repo(owner, new)
        key, kind, path = compiled_target(old, "table.r0.c1"), KIND, owner._scene_path(NUMBER)
    def state():
        stored = owner.read() if slots else load(owner, new)["scene"]
        return {**stored, "scene": stored, "documentId": document_id(kind, NUMBER), "revision": stored["editRevision"]}
    def projected():
        current = state()
        if slots:
            from ai_inspector.specification_sheet.slots import resolve as slot_values
            from ai_inspector.documentation.provenance import project_slots
            document = deepcopy(new)
            document["slots"] = slot_values({slot: value["default"] | {"claimIds": value.get("claimIds", [])}
                                            for slot, value in new["slots"].items()}, current["values"], new["slots"])
            return project_slots(document, current)
        document, view = bind_document(new, current)
        return project_document(document, view)
    def resolve_request(arguments):
        current, document = state(), projected()
        targets = text_targets(current, document)
        hashes = {k: content_hash(current, k, v) for k, v in hash_values(targets).items()}
        if slots:
            return owner.resolve_conflicts(arguments, targets=targets, hashes=hashes)
        return owner.resolve_conflicts(NUMBER, new["sourceRevision"], PLAN, arguments=arguments,
            targets=targets, hashes=hashes, identity_document=new)
    def undo(change, request_id="resolution-undo"):
        options = {"change_id": change, "expected_revision": state()["revision"], "request_id": request_id, "actor": "user"}
        return owner.undo_change(**options) if slots else owner.undo_change(NUMBER, new["sourceRevision"], PLAN,
            identity_document=new, **options)
    def history(direction):
        if slots:
            return owner.move_history(expected_revision=state()["revision"], direction=direction)
        return owner.move_history(NUMBER, new["sourceRevision"], PLAN,
            base_revision=load(owner, new)["revision"], direction=direction, identity_document=new)
    return SimpleNamespace(owner=owner, state=state, projected=projected, resolve=resolve_request, undo=undo,
        history=history, path=path, key=key, kind=kind, old=old, new=new, slots=slots)


def resolution_request(case, choice="keep_manual", *, request_id="resolve-test", **extra):
    state = case.state()
    item = exposure(state)["conflicts"][0]
    return {"documentId": state["documentId"], "expectedRevision": state["revision"], "requestId": request_id,
            "resolutions": [{"conflictId": item["conflictId"], "expectedConflictHash": item["conflictHash"],
                             "choice": choice, **extra}]}


def test_resolution_requires_current_hash(resolution_case):
    case = resolution_case
    before = case.path.read_bytes()
    request = resolution_request(case)
    request["resolutions"][0]["expectedConflictHash"] = "0" * 64
    with pytest.raises(DocumentEditError) as error:
        case.resolve(request)
    assert error.value.code == "manual_edit_conflict"
    assert case.path.read_bytes() == before
    request = resolution_request(case)
    request["expectedRevision"] -= 1
    with pytest.raises(DocumentEditError) as error:
        case.resolve(request)
    assert error.value.code == "stale_revision" and case.path.read_bytes() == before
    current = exposure(case.state())["conflicts"][0]
    assert conflict_hash(current) == current["conflictHash"]
    assert exposure(case.state())["conflicts"][0]["conflictHash"] == current["conflictHash"]


@pytest.mark.parametrize("choice", ["keep_manual", "use_generated", "merge_text"])
def test_resolution_choices_and_retry(resolution_case, choice):
    case = resolution_case
    conflict = deepcopy(exposure(case.state())["conflicts"][0])
    arguments = resolution_request(case, choice, **({"mergedText": "Merged manual value"} if choice == "merge_text" else {}))
    result = case.resolve(arguments)
    current = case.state()
    assert not exposure(current)["conflicts"]
    audit = current["resolutionHistory"][-1]
    assert audit["status"] == "resolved" and audit["resolution"]["choice"] == choice
    assert audit["resolutionReceipt"] == result["receipt"]
    assert current["generatedBaseline"][case.key]["payload"] == conflict["N"]["payload"]
    assert [audit[k] for k in ("B", "C", "N")] == [conflict[k] for k in ("B", "C", "N")]
    expected = (conflict["N"]["payload"].get("value", conflict["N"]["payload"].get("text")) if choice == "use_generated"
                else "Merged manual value" if choice == "merge_text" else "Manual value")
    targets = text_targets(current, case.projected())
    assert targets[case.key]["text"] == expected
    meta = targets[case.key]["attributes"]["provenance"]
    assert meta["origin"] == ("generated" if choice == "use_generated" else "manual")
    assert meta["evidenceStatus"] == ("source_backed" if choice == "use_generated" else "edited_unverified")
    assert "confirmation" not in meta
    raw = case.path.read_bytes()
    assert case.resolve(arguments)["receipt"] == result["receipt"]
    assert case.path.read_bytes() == raw
    reused = deepcopy(arguments)
    reused["resolutions"][0]["choice"] = "detach"
    reused["resolutions"][0].pop("mergedText", None)
    with pytest.raises(DocumentEditError) as error:
        case.resolve(reused)
    assert error.value.code == "request_id_reused" and case.path.read_bytes() == raw
    # Reopen with a fresh owner, not a process catalogue.
    identity._CATALOGS.clear()
    reopened = (SlotStore(case.path.parent.parent, NUMBER).read() if case.slots else
                load(DocumentationSceneRepository(case.path.parent.parent, case.kind), case.new)["scene"])
    assert reopened["resolutionHistory"] == current["resolutionHistory"]
    # A later refresh with the same generated payload does not re-raise this conflict.
    later = {**case.new, "sourceRevision": "source-c"}
    refreshed, _ = refresh(current, later, refresh_id="after-resolution", actor="user", at="later", slots=case.slots)
    assert not exposure(refreshed)["conflicts"]


@pytest.mark.parametrize("history", [False, True], ids=["named", "history"])
@pytest.mark.parametrize("choice", ["keep_manual", "use_generated", "merge_text"])
def test_resolution_undo(resolution_case, history, choice):
    case = resolution_case
    before = exposure(case.state())["conflicts"][0]
    result = case.resolve(resolution_request(case, choice, **({"mergedText": "Merged value"} if choice == "merge_text" else {})))
    undone = case.history("undo") if history else case.undo(result["receipt"]["changeId"])
    restored = exposure(case.state())["conflicts"][0]
    assert restored == before
    assert not case.state().get("resolutionHistory")
    if history:
        case.history("redo")
    else:
        case.undo(undone["receipt"]["changeId"], "resolution-redo")
    assert not exposure(case.state())["conflicts"]
    assert case.state()["resolutionHistory"][-1]["resolution"]["choice"] == choice


def test_resolution_batch_failure_is_atomic(resolution_case):
    case = resolution_case
    request = resolution_request(case)
    request["resolutions"].append({"conflictId": "missing", "expectedConflictHash": "0" * 64, "choice": "keep_manual"})
    raw = case.path.read_bytes()
    with pytest.raises(DocumentEditError):
        case.resolve(request)
    assert case.path.read_bytes() == raw


def test_merge_requires_text(resolution_case):
    with pytest.raises(DocumentEditError) as error:
        resolution_case.resolve(resolution_request(resolution_case, "merge_text"))
    assert error.value.code == "invalid_document_operation"


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("baseline", [None, "B"])
def test_equal_generated_value_keeps_manual_status_without_baseline(scoped, baseline):
    assert three_way(generated(baseline) if baseline else None, {"text": "N"}, generated("N"),
                     revision_scoped=scoped) == "kept"


def test_evidence_only_refresh_preserves_current_and_advances_baseline(tmp_path):
    doc = source_document()
    row = doc["pages"][0]["layoutBlocks"][0]["rows"][0]
    row.update(claimIds=["old-claim"], sourceIds=["old-source"])
    repo = DocumentationSceneRepository(tmp_path, KIND)
    old = write_text(repo, doc)
    key = compiled_target(doc, "table.r0.c1")
    new = next_source(doc, "100")
    new["pages"][0]["layoutBlocks"][0]["rows"][1].update(claimIds=["new-claim"], sourceIds=["new-source"])
    current = refresh_repo(repo, new)
    assert not current["conflicts"]
    assert current["scene"]["pages"][PAGE]["pageElementOverrides"][key] == old["scene"]["pages"][PAGE]["pageElementOverrides"][key]
    assert current["scene"]["generatedBaseline"][key]["evidence"]["claimIds"] == ["new-claim"]


@pytest.mark.parametrize("slots", [False, True])
@pytest.mark.parametrize("choice", ["detach", "restore"])
def test_orphan_resolution_and_undo(tmp_path, slots, choice):
    if slots:
        old = slot_document()
        new = slot_document("Caption", "source-b")
        new["slots"] = {"caption": {"value": "Caption", "source": "layout", "default": {"value": "Caption", "source": "layout"}}}
        new["pages"][0]["layoutBlocks"] = [{"blockId": "caption", "blockType": "paragraph", "slot": "caption", "text": "Caption"}]
        owner = SlotStore(tmp_path, NUMBER)
        owner.identity_document, owner.binding = old, {"sourceRevision": SOURCE, "manualPlanRevision": PLAN}
        owner.set_values([{"slot": "title", "value": "Orphaned value"}], "workspace")
        owner.refresh(new, expected_revision=owner.read()["editRevision"])
        owner.identity_document, owner.binding = new, {"sourceRevision": "source-b", "manualPlanRevision": PLAN}
        state, destination, kind = owner.read(), "slot:caption", "product_specification_sheet"
    else:
        old = source_document()
        owner = DocumentationSceneRepository(tmp_path, KIND)
        write_text(owner, old, text="Orphaned value")
        new = next_source(old)
        new["pages"][0]["layoutBlocks"][0]["rows"] = new["pages"][0]["layoutBlocks"][0]["rows"][:1]
        state = refresh_repo(owner, new)["scene"]
        destination, kind = compiled_target(new, "table.r0.c1"), KIND
    orphan = exposure(state)["orphans"][0]
    body = {"documentId": document_id(kind, NUMBER), "expectedRevision": state["editRevision"], "requestId": "orphan-resolution",
        "resolutions": [{"conflictId": orphan["orphanId"], "expectedConflictHash": orphan["conflictHash"], "choice": choice,
                         **({"targetId": destination, "expectedContentHash": "observed"} if choice == "restore" else {})}]}
    targets = text_targets({"documentId": body["documentId"], "scene": state}, new)
    def submit(arguments):
        if slots:
            return owner.resolve_conflicts(arguments, targets=targets, hashes={destination: "observed"})
        return owner.resolve_conflicts(NUMBER, new["sourceRevision"], PLAN, arguments=arguments,
            targets=targets, hashes={destination: "observed"}, identity_document=new)
    path = owner.path if slots else owner._scene_path(NUMBER)
    raw = path.read_bytes()
    if choice == "restore":
        stale = deepcopy(body)
        stale["resolutions"][0]["expectedContentHash"] = "stale"
        with pytest.raises(DocumentEditError) as error:
            submit(stale)
        assert error.value.code == "content_hash_mismatch" and path.read_bytes() == raw
        if not slots:
            wrong = deepcopy(body)
            wrong["resolutions"][0].update(targetId=compiled_target(new, "steps.i0"), expectedContentHash="different-kind")
            with pytest.raises(DocumentEditError) as error:
                owner.resolve_conflicts(NUMBER, new["sourceRevision"], PLAN, arguments=wrong,
                    targets=targets, hashes={wrong["resolutions"][0]["targetId"]: "different-kind"}, identity_document=new)
            assert error.value.code == "invalid_document_operation" and path.read_bytes() == raw
    result = submit(body)
    current = owner.read() if slots else load(owner, new)["scene"]
    assert not current["orphans"]
    assert current["resolutionHistory"][-1]["status"] == ("restored" if choice == "restore" else "detached")
    if choice == "restore":
        assert (current["values"]["caption"]["value"] if slots else current["pages"][PAGE]["pageElementOverrides"][destination]["text"]) == "Orphaned value"
    options = dict(change_id=result["receipt"]["changeId"], expected_revision=current["editRevision"], request_id="undo-orphan", actor="user")
    if slots:
        owner.undo_change(**options)
        restored = owner.read()
    else:
        restored = owner.undo_change(NUMBER, new["sourceRevision"], PLAN, identity_document=new, **options)["scene"]
    assert exposure(restored)["orphans"] == [orphan]


@pytest.mark.parametrize("choice", ["keep_manual", "use_generated", "merge_text"])
def test_parts_resolution_route_and_sage_agree_on_twin_store(mmle_client, monkeypatch, choice):
    import asyncio
    import server
    from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway
    _parts_route_conflict(mmle_client, monkeypatch)
    kind = "illustrated_parts_manual"
    url = "/api/documentation/" + kind + "/MMLE-50D/conflicts"
    review = mmle_client.get(url).json()
    assert review["success"] and review["openConflictCount"] == 1
    conflict = review["conflicts"][0]
    body = {"documentId": review["documentId"], "expectedRevision": conflict["revision"], "requestId": "route-resolution",
            "resolutions": [{"conflictId": conflict["conflictId"], "expectedConflictHash": conflict["conflictHash"], "choice": choice,
                             **({"mergedText": "Merged service description"} if choice == "merge_text" else {})}]}
    path = server._DocumentationAgentHost()._edit_repository(kind)._scene_path("MMLE-50D")
    original = path.read_bytes()
    response = mmle_client.post(url + "/resolve", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    first = json.loads(path.read_bytes())
    assert result["reload"] and not result["openConflictCount"]
    assert first["resolutionHistory"][-1]["resolution"]["actor"] == "user"
    saved = path.read_bytes()
    assert mmle_client.post(url + "/resolve", json=body).json()["receipt"] == result["receipt"]
    assert path.read_bytes() == saved
    # The twin starts from exactly the same isolated store, with a new gateway and cleared catalogue.
    path.write_bytes(original)
    identity._CATALOGS.clear()
    gateway = DocumentationGateway(server._DocumentationAgentHost(),
        SimpleNamespace(tenant_id="test", principal_id="sage-test", roles=(), allowed_site_ids=()),
        {"assemblyNumber": "MMLE-50D", "documentType": kind}, turn_id="conflict-resolution", user_message="Resolve this description: " + choice)
    def call(name, arguments):
        payload = asyncio.run(gateway.call(name, arguments))
        assert payload["ok"], payload
        return payload["data"]
    call("read_document_pages", {"documentType": kind, "targets": [{"targetId": conflict["targetId"]}]})
    seen = call("read_document_conflicts", {"documentId": review["documentId"]})
    assert seen["conflicts"][0]["conflictHash"] == conflict["conflictHash"]
    call("resolve_document_conflicts", body)
    second = json.loads(path.read_bytes())
    assert second["resolutionHistory"][-1]["resolution"]["actor"] == "sage"
    assert second["pages"] == first["pages"] and second["generatedBaseline"] == first["generatedBaseline"]
    assert second["conflicts"] == first["conflicts"] == []
    for side in ("B", "C", "N"):
        assert second["resolutionHistory"][-1][side] == first["resolutionHistory"][-1][side]
    identity._CATALOGS.clear()
    reopened = mmle_client.get(url).json()
    assert reopened["openConflictCount"] == 0 and reopened["resolutionHistory"][-1]["status"] == "resolved"
    assert json.loads(path.read_bytes()) == second


@pytest.mark.parametrize("choice", ["keep_manual", "use_generated", "merge_text"])
def test_native_specification_resolution_route(mmle_client, monkeypatch, choice):
    import server
    test_real_specification_slot_refresh_and_sage_batch_refusal(mmle_client, monkeypatch)
    kind = "product_specification_sheet"
    url = "/api/documentation/" + kind + "/MMLE-50D/conflicts"
    review = mmle_client.get(url).json()
    conflict = next(c for c in review["conflicts"] if c["targetId"] == "slot:feature.1.text")
    assert conflict["owner"] == "slots"
    arguments = {"documentId": review["documentId"], "expectedRevision": conflict["revision"], "requestId": "slot-route-resolve",
        "resolutions": [{"conflictId": conflict["conflictId"], "expectedConflictHash": conflict["conflictHash"], "choice": choice,
                         **({"mergedText": "Merged feature"} if choice == "merge_text" else {})}]}
    result = mmle_client.post(url + "/resolve", json=arguments)
    assert result.status_code == 200, result.text
    snapshot = server._DocumentationAgentHost().document_snapshot("MMLE-50D", kind)
    expected = "Manual feature value" if choice == "keep_manual" else "New generated feature value" if choice == "use_generated" else "Merged feature"
    assert snapshot["document"]["slots"]["feature.1.text"]["value"] == expected
    assert snapshot["state"]["openConflictCount"] == 0
    undo = mmle_client.post("/api/specification-sheet/MMLE-50D/slots/undo", json={
        "expectedRevision": snapshot["state"]["revision"], "sourceRevision": snapshot["state"]["sourceRevision"],
        "manualPlanRevision": snapshot["state"]["manualPlanRevision"]})
    assert undo.status_code == 200, undo.text
    assert mmle_client.get(url).json()["openConflictCount"] == 1


def _spread_balloons(valid_balloon, items):
    """The parts fixture stacks balloons in one column over y 0.20-0.80, which overlaps above 13 callouts
    (MMLE pages carry up to 16). Shift each balloon's geometry as one piece onto y 0.08-0.92."""
    balloons = []
    for index, item in enumerate(items):
        balloon = valid_balloon(item, index, len(items))
        assert not balloon["branches"]
        dy = (0.08 + index * 0.84 / (len(items) - 1) if len(items) > 1 else 0.50) - balloon["balloon"]["y"]
        seen = set()
        def shift(node, keys):
            if id(node) not in seen:
                seen.add(id(node))
                for key in keys:
                    node[key] += dy
        for point in (balloon["target"], balloon["balloon"], *balloon["leaderPath"],
                      *(anchor["target"] for anchor in balloon["anchors"])):
            shift(point, ("y",))
        for bounds in (balloon["targetBounds"], *(anchor["targetBounds"] for anchor in balloon["anchors"]),
                       *(region["bounds"] for region in balloon["projectedRegions"])):
            shift(bounds, ("top", "bottom"))
        balloons.append(balloon)
    return balloons


@pytest.mark.parametrize("kind,route", MMLE_ROUTES)
def test_conflict_review_export_and_customer_blocking(mmle_client, tmp_path, kind, route):
    import fitz
    import server
    from ai_inspector.documentation.conflict_exports import project_review, CONFLICT_MARKER
    from ai_inspector.documentation.provenance import check_export
    from ai_inspector.operations_manual.artifacts import store_draft_render_artifact, attach_draft_render_artifacts
    from ai_inspector.operations_manual.exports import build_prototype_pdf_bytes, build_prototype_docx_bytes
    from tests.test_operations_manual_workspace import _png
    from tools.documentation_baseline import specification_capture, docx_paragraphs
    if route == "parts-manual" and not (server.PARTS_MANUAL_ROOT / "mmle-50d" / "manual-plan.json").is_file():
        pytest.skip("needs the local approved MMLE manual plan")
    snapshot = server._DocumentationAgentHost().document_snapshot("MMLE-50D", kind)
    document = snapshot["document"]
    key = next(k for k in snapshot["targets"] if (k.endswith(".description") if route == "parts-manual" else
               k == "slot:title" if route == "specification-sheet" else True))
    target = snapshot["targets"][key]
    conflict = {"conflictId": "c-export", "targetId": key, "pageId": target["pageId"], "alias": target["alias"], "status": "open"}
    annotated = project_review(document, {"conflicts": [conflict], "orphans": [{"orphanId": "o-export"}]})
    for mode in ("customer", "controlled"):
        with pytest.raises(DocumentEditError) as error:
            check_export(annotated, mode)
        assert error.value.code == "manual_edit_conflict" and error.value.details["conflictIds"] == ["c-export"]
    # No-conflict projection is an identity operation: existing export text stays unchanged.
    assert project_review(document, {}) is document
    check_export(project_review(document, {"orphans": [{"orphanId": "o-only"}]}), "customer")
    root = tmp_path / "export"
    if route == "parts-manual":
        from ai_inspector.parts_manual.artifacts import store_render_artifact, attach_render_artifacts
        from ai_inspector.parts_manual.pdf import build_manual_pdf_bytes
        from tests.test_parts_manual import _png as _parts_png, _valid_balloon
        for page in annotated["pages"]:
            if page.get("renderRequest"):
                items = page["renderRequest"].get("calloutItems", [])
                balloons = _spread_balloons(_valid_balloon, items)
                # Parts captures must contain visible line geometry (render validation).
                store_render_artifact(root, "MMLE-50D", annotated, page["pageId"], _parts_png(), balloons=balloons)
        annotated = attach_render_artifacts(root, "MMLE-50D", annotated)
        pdf_bytes = build_manual_pdf_bytes(root, "MMLE-50D", annotated)
        word = None
    elif route == "specification-sheet":
        from ai_inspector.specification_sheet.exports import build_specification_pdf_bytes, build_specification_docx_bytes
        annotated = specification_capture(root, "MMLE-50D", annotated, _png(2200, 2200))
        pdf_bytes = build_specification_pdf_bytes(annotated, render_root=root, assembly_number="MMLE-50D")
        word = build_specification_docx_bytes(annotated, render_root=root, assembly_number="MMLE-50D")
    else:
        for page in annotated["pages"]:
            if page.get("renderRequest"):
                store_draft_render_artifact(root, "MMLE-50D", annotated, page["pageId"], _png(1920, 1080),
                    source_revision=annotated["sourceRevision"], manual_plan_revision=annotated["manualPlanRevision"], api_route=route)
        annotated = attach_draft_render_artifacts(root, "MMLE-50D", annotated)
        pdf_bytes = build_prototype_pdf_bytes(root, "MMLE-50D", annotated)
        word = build_prototype_docx_bytes(root, "MMLE-50D", annotated)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    assert CONFLICT_MARKER in text and "c-export" in text
    assert "Open manual edit conflicts: 1; unplaced manual content: 1" in text
    if word is not None:
        text = "\n".join(docx_paragraphs(word))
        assert CONFLICT_MARKER in text and "c-export" in text
        assert "Open manual edit conflicts: 1; unplaced manual content: 1" in text



def test_p1c2a_conflict_hash_is_derived_without_save(resolution_case):
    case = resolution_case
    old = json.loads(case.path.read_bytes())
    for conflict in old["conflicts"]:
        conflict.pop("conflictHash", None)
    old.pop("resolutionHistory", None)
    raw = (json.dumps(old, indent=2) + "\n").encode("ascii")
    case.path.write_bytes(raw)
    before = exposure(case.state())["conflicts"][0]
    assert before["conflictHash"] == conflict_hash(before)
    assert case.path.read_bytes() == raw
    assert exposure(case.state())["conflicts"][0] == before
    assert case.path.read_bytes() == raw


def test_resolution_audit_is_bounded_and_keeps_detached_payloads():
    from ai_inspector.documentation.resolution import resolve
    doc = compile_identities(source_document())
    state = DocumentationSceneRepository.new_scene(NUMBER, SOURCE, PLAN)
    for index in range(RESOLUTION_HISTORY_LIMIT + 2):
        payload = {"text": "Orphan " + str(index)}
        orphan = with_hash({"orphanId": "o-" + str(index), "targetId": "removed-" + str(index),
                           "C": {"payload": payload, "hash": digest(payload)}, "reason": "target_deleted"})
        state.setdefault("orphans", []).append(orphan)
        state, _, _ = resolve(state, doc, [{"conflictId": orphan["orphanId"], "expectedConflictHash": orphan["conflictHash"], "choice": "detach"}],
            receipt={"requestId": "detach-" + str(index), "changeId": "change-" + str(index)}, actor="user", at="time", targets={}, hashes={})
    assert len(state["resolutionHistory"]) == RESOLUTION_HISTORY_LIMIT
    assert state["resolutionHistory"][0]["orphanId"] == "o-2"
    assert state["resolutionHistory"][-1]["C"]["payload"] == {"text": "Orphan 101"}


def test_use_generated_slot_suppresses_old_viewport_fallback(resolution_case):
    case = resolution_case
    if not case.slots:
        return
    case.resolve(resolution_request(case, "use_generated"))
    from ai_inspector.specification_sheet.document import _legacy_text_values
    page = {"layoutBlocks": [{"blockId": "spec-title", "slot": "title"}],
            "documentationComposition": {"pageElementOverrides": {"spec-title": {"text": "Old viewport text"}}},
            "renderRequest": {"composition": {}}}
    assert _legacy_text_values(page, case.state()["values"]) == {}
    assert case.projected()["slots"]["title"]["value"] == "New generated title"
    assert case.projected()["slots"]["title"]["provenance"]["origin"] == "generated"


def test_later_proposal_invalidates_resolution_hash(resolution_case):
    case = resolution_case
    request = resolution_request(case)
    if case.slots:
        later = slot_document("Later generated title", "source-c")
        case.owner.refresh(later, expected_revision=case.state()["revision"])
        case.owner.identity_document, case.owner.binding = later, {"sourceRevision": "source-c", "manualPlanRevision": PLAN}
        state = case.owner.read()
        targets = text_targets({"scene": state, "documentId": request["documentId"]}, later)
        request["expectedRevision"] = state["editRevision"]
        raw = case.path.read_bytes()
        with pytest.raises(DocumentEditError) as error:
            case.owner.resolve_conflicts(request, targets=targets, hashes={})
    else:
        later = next_source(case.old, "300")
        later["sourceRevision"] = "source-c"
        refreshed = refresh_repo(case.owner, later)
        request["expectedRevision"] = refreshed["scene"]["editRevision"]
        raw = case.path.read_bytes()
        with pytest.raises(DocumentEditError) as error:
            case.owner.resolve_conflicts(NUMBER, "source-c", PLAN, arguments=request, targets={}, hashes={}, identity_document=later)
    assert error.value.code == "manual_edit_conflict" and case.path.read_bytes() == raw



def test_named_resolution_undo_preserves_another_resolution(tmp_path):
    repo = DocumentationSceneRepository(tmp_path, KIND)
    old = source_document()
    write_text(repo, old)
    write_text(repo, old, alias="steps.i0", text="Manual action")
    new = next_source(old)
    new["pages"][0]["layoutBlocks"][1]["items"][0]["text"] = "New action"
    refreshed = refresh_repo(repo, new)
    conflicts = refreshed["conflicts"]
    assert len(conflicts) == 2
    receipts = []
    for index, conflict in enumerate(conflicts):
        state, document, targets = snapshot(repo, new)
        body = {"documentId": state["documentId"], "expectedRevision": state["revision"], "requestId": "resolve-" + str(index),
                "resolutions": [{"conflictId": conflict["conflictId"], "expectedConflictHash": conflict["conflictHash"], "choice": "keep_manual"}]}
        result = repo.resolve_conflicts(NUMBER, new["sourceRevision"], PLAN, arguments=body,
                                       targets=targets, hashes={}, identity_document=new)
        receipts.append(result["receipt"])
    repo.undo_change(NUMBER, new["sourceRevision"], PLAN, change_id=receipts[0]["changeId"],
        expected_revision=load(repo, new)["scene"]["editRevision"], request_id="undo-first-resolution", identity_document=new)
    current = load(repo, new)
    assert [c["conflictId"] for c in current["conflicts"]] == [conflicts[0]["conflictId"]]
    assert [c["conflictId"] for c in current["resolutionHistory"]] == [conflicts[1]["conflictId"]]


def test_detach_deleted_conflict_closes_linked_blocker_and_undo_reopens(tmp_path):
    repo = DocumentationSceneRepository(tmp_path, KIND)
    old = source_document()
    write_text(repo, old)
    new = next_source(old)
    refresh_repo(repo, new)
    deleted = deepcopy(new)
    deleted["sourceRevision"] = "source-c"
    deleted["pages"][0]["layoutBlocks"][0]["rows"] = deleted["pages"][0]["layoutBlocks"][0]["rows"][:1]
    current = refresh_repo(repo, deleted)
    orphan = current["orphans"][0]
    assert orphan["relatedConflicts"]
    body = {"documentId": document_id(KIND, NUMBER), "expectedRevision": current["scene"]["editRevision"], "requestId": "detach-deleted",
            "resolutions": [{"conflictId": orphan["orphanId"], "expectedConflictHash": orphan["conflictHash"], "choice": "detach"}]}
    result = repo.resolve_conflicts(NUMBER, "source-c", PLAN, arguments=body, targets={}, hashes={}, identity_document=deleted)
    assert not result["conflicts"] and not result["orphans"] and len(result["resolutionHistory"]) == 2
    undone = repo.undo_change(NUMBER, "source-c", PLAN, change_id=result["receipt"]["changeId"],
        expected_revision=result["scene"]["editRevision"], request_id="undo-deleted-detach", identity_document=deleted)
    assert undone["conflicts"] == current["conflicts"] and undone["orphans"] == current["orphans"]
