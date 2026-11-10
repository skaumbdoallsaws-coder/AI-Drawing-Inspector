"""P1b-3 guarded store inverses and real compiled MMLE slot confirmation."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import server
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway
from ai_inspector.documentation.commands import DocumentEditError
from ai_inspector.documentation.provenance import EDITED_MARKER, check_export
from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
from ai_inspector.specification_sheet.slots import SlotStore
from tests.test_documentation_transactions import (
    SceneHarness, SlotHarness, request_for, disk as store_disk, NUMBER, SOURCE, PLAN, PAGE as UNIT_PAGE,
)
from tests.test_documentation_provenance import (
    operations, capacity, sage, call, disk, KIND, PAGE, CELL, BASE,
    test_sage_cannot_confirm_value as check_scene_authority_boundary,
)

SPEC = "product_specification_sheet"
SLOT = "spec.rated_capacity.value"
SBASE = "/api/specification-sheet/MMLE-50D"


def undo(store, change_id, request_id="undo-test", expected_revision=None):
    state, _ = store.snapshot()
    kwargs = dict(change_id=change_id, expected_revision=state["revision"] if expected_revision is None else expected_revision, request_id=request_id)
    if isinstance(store, SceneHarness):
        return store.repo.undo_change(NUMBER, SOURCE, PLAN, **kwargs)["receipt"]
    return store.repo.undo_change(**kwargs)["receipt"]


def test_slot_batch_one_undo(tmp_path):
    store = SlotHarness(tmp_path)
    receipt = store.commit(request_for(store, {"title": "one change", "caption": "two changes"}))
    assert receipt["undoable"]
    assert len(store.repo.read()["journal"]) == 1
    undone = undo(store, receipt["changeId"])
    assert store.values() == {"title": "one", "caption": "two"}
    assert undone["revision"] == receipt["revision"] + 1
    redone = undo(store, undone["changeId"], "redo-test")
    assert store.values() == {"title": "one change", "caption": "two changes"}
    assert redone["undoable"]


@pytest.mark.parametrize("factory", [SceneHarness, SlotHarness], ids=["scene", "slots"])
def test_named_undo_preserves_later_human_edit(tmp_path, factory):
    store = factory(tmp_path)
    first = store.commit(request_for(store, {"title": "named"}))
    store.commit(request_for(store, {"caption": "later human"}))
    revision = store.snapshot()[0]["revision"]
    inverse = undo(store, first["changeId"], expected_revision=revision)
    assert store.values() == {"title": "one", "caption": "later human"}
    snapshot = store_disk(store)
    assert undo(store, first["changeId"], expected_revision=revision) == inverse  # identical retry, even after revision advances
    assert store_disk(store) == snapshot
    undo(store, inverse["changeId"], "redo")
    assert store.values() == {"title": "named", "caption": "later human"}


@pytest.mark.parametrize("factory", [SceneHarness, SlotHarness], ids=["scene", "slots"])
def test_overlapping_undo_conflicts(tmp_path, factory):
    store = factory(tmp_path)
    first = store.commit(request_for(store, {"title": "named", "caption": "batch"}))
    store.commit(request_for(store, {"title": "later human"}))
    snapshot = store_disk(store)
    with pytest.raises(DocumentEditError) as caught:
        undo(store, first["changeId"])
    assert caught.value.code == "undo_conflict" and caught.value.details["targets"]
    assert store_disk(store) == snapshot
    assert store.values() == {"title": "later human", "caption": "batch"}


def test_undo_restores_provenance(operations):
    edited = operations.edit()
    change = edited["command"]["commandId"]
    gateway = sage(operations)
    read = call(gateway, "read_document_pages", {"documentType": KIND,
                "targets": [{"pageId": PAGE, "targetId": CELL}]})
    summary = call(gateway, "inspect_document_change", {"documentId": read["documentId"], "changeId": change})
    assert summary["fields"] and summary["before"] and summary["after"] and summary["undoable"]
    assert any(field[0] == "fieldMeta" for field in summary["fields"])
    assert str(operations.root) not in json.dumps(summary)
    result = call(gateway, "undo_document_change", {"documentId": read["documentId"], "changeId": change,
        "expectedRevision": read["revision"], "requestId": "restore-source"})
    row = capacity(operations.state()["document"])["rows"][0]
    assert row["provenance"]["evidenceStatus"] == "source_backed"
    assert row["claimIds"] == ["CLM-SPEC-001"]
    assert result["receipt"]["undoable"]


def test_old_command_history_migrates(tmp_path):
    store = SceneHarness(tmp_path)
    initial, _ = store.snapshot()
    store.repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=initial["sceneRevision"],
        page_targets=store.page_targets, command={"operation": "update_text", "targetType": "page_element",
            "pageId": UNIT_PAGE, "targetId": "title", "text": "old edit"})
    old = json.loads(store.path.read_bytes())
    old["schemaVersion"] = 2
    for key in ("editRevision", "editEpoch", "receipts", "receiptOrder", "fieldVersions", "fieldMeta"):
        old.pop(key, None)
    for command in old["commands"]:
        command.pop("change", None)
    original = (json.dumps(old, indent=2) + "\n").encode()
    store.path.write_bytes(original)
    state = store.repo.read(NUMBER, SOURCE, PLAN)
    assert store.path.read_bytes() == original
    change = state["changes"][-1]["changeId"]
    inspected = store.repo.inspect_change(NUMBER, SOURCE, PLAN, change)
    assert inspected["fields"] and store.path.read_bytes() == original
    store.repo.undo_change(NUMBER, SOURCE, PLAN, change_id=change, expected_revision=0, request_id="old-undo")
    assert store.values()["title"] == "one"
    assert store.path.with_name("documentation-scene.v2.json").read_bytes() == original


def test_old_slot_journal_is_additive_and_pure(tmp_path):
    store = SlotStore(tmp_path, NUMBER)
    store.path.parent.mkdir()
    original = b'{"schemaVersion":2,"values":{"title":{"value":"before","source":"workspace"}}}\n'
    store.path.write_bytes(original)
    assert store.read()["journal"] == [] and store.path.read_bytes() == original
    store.set_values([{"slot": "title", "value": "after"}], "workspace")
    change = store.last_receipt["changeId"]
    store.undo_change(change, expected_revision=store.read()["editRevision"], request_id="old-slot")
    assert store.read()["values"]["title"]["value"] == "before"
    assert store.read()["schemaVersion"] == 2


def test_compound_slot_row_undo_checks_dependencies(tmp_path):
    store = SlotStore(tmp_path, NUMBER)
    store.transaction(lambda candidate: (candidate.set_rows([{"key": "new", "label": "New", "provisional": True}]),
        candidate.set_values([{"slot": "spec.new.value", "value": "100"}], "workspace")))
    before = store.read()
    store.transaction(lambda candidate: (candidate.name_new_row("new", "Capacity"),
        candidate.set_values([{"slot": "spec.capacity.value", "value": "200"}], "workspace")))
    named = store.last_receipt["changeId"]
    store.undo_change(named, expected_revision=store.read()["editRevision"], request_id="compound-undo")
    for key in ("rows", "values", "fieldMeta"):
        assert store.read()[key] == before[key]
    redo = store.last_receipt["changeId"]
    store.set_values([{"slot": "spec.new.value", "value": "human"}], "workspace")
    snapshot = store.path.read_bytes()
    with pytest.raises(DocumentEditError) as error:
        store.undo_change(redo, expected_revision=store.read()["editRevision"], request_id="conflict")
    assert error.value.code == "undo_conflict" and store.path.read_bytes() == snapshot


def slot_edit(operations, value="1,000 lb"):
    response = operations.client.post(SBASE + "/values", json={"values": [{"slot": SLOT, "value": value}]})
    assert response.status_code == 200, response.text
    return response.json()


def slot_read(operations):
    response = operations.client.get(f"/api/documentation/{SPEC}/{NUMBER}/confirmation-targets")
    assert response.status_code == 200, response.text
    read = response.json()
    return read, {"expectedRevision": read["revision"], "requestId": "slot-confirm",
        "targets": [{"targetId": item["targetId"], "expectedContentHash": item["contentHash"]} for item in read["targets"]]}


def slot_confirm(operations, read, body):
    return operations.client.post(f"/api/documentation/{read['documentId']}/confirm-values", json=body)


def slot_document(operations):
    return operations.client.get(SBASE + "/documentation-scene").json()["document"]


def test_slot_sage_cannot_confirm(operations):
    check_scene_authority_boundary(operations)  # Scan both complete registries and the host class.
    slot_edit(operations)
    gateway = DocumentationGateway(server._DocumentationAgentHost(),
        SimpleNamespace(tenant_id="test", principal_id="sage", roles=(), allowed_site_ids=()),
        {"assemblyNumber": NUMBER, "documentType": SPEC}, turn_id="slot-proof")
    read = call(gateway, "read_document_pages", {"documentType": SPEC, "fromPage": 1, "pageCount": 1})
    args = {"documentId": read["documentId"], "targets": [{"targetId": row["targetId"],
        "expectedContentHash": row["contentHash"]} for row in read["confirmationTargets"]]}
    assert args["targets"]
    snapshot = disk(server.SPECIFICATION_SHEET_ROOT)
    assert call(gateway, "propose_document_value_confirmation", args)["status"] == "awaiting_user"
    assert disk(server.SPECIFICATION_SHEET_ROOT) == snapshot
    denied = asyncio.run(gateway.call("confirm_document_values", args))
    assert denied["error"]["code"] == "codex_tool_denied"
    source = (Path(__file__).resolve().parents[1] / "static/documentation_commands.js").read_text()
    assert "if (model?.documentType === 'product_specification_sheet') return" not in source


def test_slot_confirmation_stale_click_and_hostile_origin_rejected(operations):
    slot_edit(operations)
    read, body = slot_read(operations)
    denied = operations.client.post(f"/api/documentation/{read['documentId']}/confirm-values", json=body,
                                    headers={"Origin": "https://hostile.example"})
    assert denied.status_code == 403
    slot_edit(operations, "900 lb")
    snapshot = disk(server.SPECIFICATION_SHEET_ROOT)
    denied = slot_confirm(operations, read, body)
    assert denied.status_code == 422 and denied.json()["error"] == "stale_revision"
    assert disk(server.SPECIFICATION_SHEET_ROOT) == snapshot


def test_slot_confirmation_undo_and_edit_clears_confirmation(operations):
    edited = slot_edit(operations)
    read, body = slot_read(operations)
    confirmed = slot_confirm(operations, read, body)
    assert confirmed.status_code == 200, confirmed.text
    receipt = confirmed.json()["receipt"]
    meta = slot_document(operations)["slots"][SLOT]["provenance"]
    assert meta["evidenceStatus"] == "entered_by_user" and not meta["activeClaimIds"]
    assert meta["confirmation"]["by"] == "test-reviewer" and meta["confirmation"]["changeId"] == receipt["changeId"]
    snapshot = disk(server.SPECIFICATION_SHEET_ROOT)
    assert slot_confirm(operations, read, body).json()["receipt"] == receipt
    assert disk(server.SPECIFICATION_SHEET_ROOT) == snapshot
    host = server._DocumentationAgentHost()
    # A confirmation is a provenance edit: the earlier value edit cannot bypass it.
    with pytest.raises(DocumentEditError) as error:
        host.undo_document_change(NUMBER, SPEC, {"changeId": edited["receipt"]["changeId"],
            "expectedRevision": receipt["revision"], "requestId": "overlap-confirm"})
    assert error.value.code == "undo_conflict"
    undone = host.undo_document_change(NUMBER, SPEC, {"changeId": receipt["changeId"],
        "expectedRevision": receipt["revision"], "requestId": "undo-confirm"})
    assert slot_document(operations)["slots"][SLOT]["provenance"]["evidenceStatus"] == "edited_unverified"
    host.undo_document_change(NUMBER, SPEC, {"changeId": undone["receipt"]["changeId"],
        "expectedRevision": undone["receipt"]["revision"], "requestId": "redo-confirm"})
    assert slot_document(operations)["slots"][SLOT]["provenance"]["evidenceStatus"] == "entered_by_user"
    changed = slot_edit(operations, "800 lb")["document"]["slots"][SLOT]["provenance"]
    assert changed["evidenceStatus"] == "edited_unverified" and "confirmation" not in changed


def test_slot_confirmed_export_clean_and_acceptance_stays_separate(operations):
    from tools.documentation_baseline import specification_capture, docx_paragraphs
    from tests.test_operations_manual_workspace import _png
    import fitz

    slot_edit(operations)
    read, body = slot_read(operations)
    assert slot_confirm(operations, read, body).status_code == 200
    document = slot_document(operations)
    specification_capture(server.SPECIFICATION_SHEET_ROOT, NUMBER, document, _png(2200, 2200))
    check_export(document, "customer")
    response = operations.client.post(SBASE + "/pdf?mode=customer")
    assert response.status_code == 200, response.text
    exports = response.json()
    with fitz.open(stream=operations.client.get(exports["pdf"]["url"]).content, filetype="pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
    word = "\n".join(docx_paragraphs(operations.client.get(exports["docx"]["url"]).content))
    assert "1,000 lb" in text and "1,000 lb" in word
    assert EDITED_MARKER not in text + word
    slot = document["slots"][SLOT]
    assert not slot["activeClaimIds"] and slot["overrides"]["source"] == "evidence"
    assert "overrides_evidence" in {finding["topic"] for finding in document["releaseGate"]["findings"]}
    store = SlotStore(server.SPECIFICATION_SHEET_ROOT, NUMBER)
    store.set_values([{"slot": SLOT, "value": "750 lb"}], "sage_draft")
    assert not store.read()["values"][SLOT].get("accepted")
    read, body = slot_read(operations)
    body["requestId"] = "draft-confirm"
    assert slot_confirm(operations, read, body).status_code == 200
    assert not store.read()["values"][SLOT].get("accepted")
    store.accept([SLOT], "test-reviewer")
    assert store.read()["values"][SLOT]["accepted"]


@pytest.mark.parametrize("factory", [SceneHarness, SlotHarness], ids=["scene", "slots"])
def test_redo_is_guarded_and_future_revision_is_rejected(tmp_path, factory):
    store = factory(tmp_path)
    receipt = store.commit(request_for(store, {"title": "one change"}))
    before = store_disk(store)
    with pytest.raises(DocumentEditError) as error:
        undo(store, receipt["changeId"], "future", expected_revision=999)
    assert error.value.code == "stale_revision" and store_disk(store) == before
    reverted = undo(store, receipt["changeId"])
    store.commit(request_for(store, {"title": "new human"}))
    before = store_disk(store)
    with pytest.raises(DocumentEditError) as error:
        undo(store, reverted["changeId"], "guarded-redo")
    assert error.value.code == "undo_conflict" and store_disk(store) == before


def test_legacy_cursor_redo_adopts_without_a_read_write(tmp_path):
    from ai_inspector.parts_manual.documentation import (
        replay_documentation_commands, replay_documentation_theme,
    )
    store = SceneHarness(tmp_path)
    store.commit(request_for(store, {"title": "legacy title"}))
    store.commit(request_for(store, {"caption": "legacy caption"}))
    old = json.loads(store.path.read_bytes())
    for command in old["commands"]:
        command.pop("change", None)
    old["historyCursor"] = 0
    old["pages"] = replay_documentation_commands([])
    old["theme"], old["pageMasters"] = replay_documentation_theme([])
    old["fieldMeta"] = {}
    original = json.dumps(old).encode()
    store.path.write_bytes(original)
    state = store.repo.read(NUMBER, SOURCE, PLAN)
    assert state["canRedo"] and store.path.read_bytes() == original
    first = store.repo.move_history(NUMBER, SOURCE, PLAN, base_revision=state["revision"], direction="redo")
    assert first["receipt"]["undoable"] and first["canRedo"]
    assert store.values() == {"title": "legacy title", "caption": "two"}
    second = store.repo.move_history(NUMBER, SOURCE, PLAN, base_revision=first["revision"], direction="redo")
    assert second["receipt"]["undoable"] and store.values()["caption"] == "legacy caption"


def test_scene_object_deletion_checks_its_contents(tmp_path):
    store = SceneHarness(tmp_path)
    state, _ = store.snapshot()
    added = store.repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=state["sceneRevision"],
        page_targets=store.page_targets, command={"operation": "add_object", "targetType": "document_object",
            "targetId": "document-object-note", "pageId": UNIT_PAGE, "documentObject": {"objectId": "document-object-note", "type": "text",
            "name": "Note", "content": "original", "frame": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}}})
    # The inverse of insertion is a deletion and depends on the complete object.
    store.page_targets[UNIT_PAGE]["document_object"] = ["document-object-note"]
    store.repo.apply_command(NUMBER, SOURCE, PLAN, base_revision=added["revision"], page_targets=store.page_targets,
        command={"operation": "update_text", "targetType": "document_object", "targetId": "document-object-note",
                 "pageId": UNIT_PAGE, "text": "human content"})
    before = store_disk(store)
    with pytest.raises(DocumentEditError) as error:
        undo(store, added["command"]["commandId"])
    assert error.value.code == "undo_conflict" and store_disk(store) == before
