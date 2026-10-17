"""Real preview -> shared Apply/Undo/Save transaction, without provider calls."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.service import FacilityLayoutService
from tests.test_facility_generation_admission import case, preview, correct, assert_code
from tests.test_facility_layout_design_loop_contracts import _editor_frame


def selected(case):
    result = preview(case)
    request = {key: result[key] for key in ("previewId", "previewRevision")}
    return case["host"].generation_draft_adapter.publish(case["principal"], **case["options"], request=request), request


def client_for(case):
    app = FastAPI()
    app.include_router(case["host"].create_router())
    return TestClient(app)


def apply_http(case, client):
    selection, _ = selected(case)
    frame = _editor_frame({"document": case["saved"]})
    base = "/api/facility-layout-design/site-local/fl-main"
    response = client.post(base + "/proposals/" + selection["proposalId"] + "/apply/prepare", json={
        "proposalRevision": selection["proposalRevision"], "rootUndoFrame": frame,
        "previousInstallationState": frame, "expectedResultEditorGenerationId": "editor-applied",
        "expectedResultCommandJournalHash": "8" * 64})
    assert response.status_code == 200, response.text
    prepared = response.json()
    transaction = prepared["transaction"]
    endpoint = base + "/transactions/" + transaction["transaction"]["transactionId"]
    committed = client.post(endpoint + "/apply/commit", json={
        "expectedTransactionRevision": transaction["transactionRevision"], "adoptionToken": prepared["adoption"]["adoptionToken"]})
    assert committed.status_code == 200, committed.text
    acknowledged = client.post(endpoint + "/apply/acknowledge", json={
        "expectedTransactionRevision": committed.json()["transaction"]["transactionRevision"],
        "adoptionToken": prepared["adoption"]["adoptionToken"],
        "observedInstallationFingerprint": prepared["expectedInstallationFingerprint"]})
    assert acknowledged.status_code == 200, acknowledged.text
    return endpoint, prepared, acknowledged.json(), frame


def test_exact_selection_is_idempotent_and_stale_ledger_rejected(case):
    first, request = selected(case)
    adapter = case["host"].generation_draft_adapter
    assert adapter.publish(case["principal"], **case["options"], request=request) == first
    assert not case["service"].leases.inspect(case["principal"].tenant_id, "site-local", "fl-main")["active"]
    correct(case, quantity=3)
    assert_code("generation_ledger_superseded", lambda: adapter.publish(case["principal"], **case["options"], request=request))


def test_shared_apply_undo_round_trip(case):
    with client_for(case) as client:
        endpoint, prepared, active, frame = apply_http(case, client)
        assert layout_revision(prepared["candidateLayout"]) != frame["draftRevision"]
        assert case["host"].service.get_layout(case["principal"], "site-local", "fl-main")["layout"] == case["saved"]
        service = case["host"].design_loop_service
        undo = service.prepare_undo(tenant_id=case["principal"].tenant_id, site_id="site-local",
            transaction_id=active["transaction"]["transaction"]["transactionId"],
            expected_transaction_revision=active["transaction"]["transactionRevision"])
        assert undo["rootUndoFrame"] == frame
        assert undo["readiness"] == "undo_acknowledgment_pending"
        restored = service.acknowledge_undo(tenant_id=case["principal"].tenant_id, site_id="site-local",
            transaction_id=undo["transaction"]["transaction"]["transactionId"],
            expected_transaction_revision=undo["transaction"]["transactionRevision"],
            observed_draft_revision=frame["draftRevision"], observed_command_journal_hash=frame["commandJournalHash"])
        assert restored["transaction"]["transaction"]["status"] == "undone"


def test_selection_requires_write_before_artifact_access(case, monkeypatch):
    _, request = selected(case)
    def gate(capability):
        if capability == "agent_write":
            from ai_inspector.facility_layout.errors import FacilityAuthorizationError
            raise FacilityAuthorizationError("facility_feature_disabled", "write disabled")
    monkeypatch.setattr(case["service"], "require_capability", gate)
    monkeypatch.setattr(case["service"], "get_preview", lambda *a, **k: pytest.fail("Read before write gate"))
    assert_code("facility_feature_disabled", lambda: case["host"].generation_draft_adapter.publish(
        case["principal"], **case["options"], request=request))


def test_explicit_save_persists_only_selected_candidate(case, monkeypatch):
    saves = []
    def save(*args, **kwargs):
        saves.append(1)
        return FacilityLayoutService.save_layout(case["host"].service, *args, **kwargs)
    monkeypatch.setattr(case["host"].service, "save_layout", save)
    with client_for(case) as client:
        endpoint, prepared, active, frame = apply_http(case, client)
        payload = {"expectedTransactionRevision": active["transaction"]["transactionRevision"],
            "observedDraftRevision": layout_revision(prepared["candidateLayout"]),
            "observedCommandJournalHash": "8" * 64, "explicitApproval": False}
        rejected = client.post(endpoint + "/save", json=payload)
        assert rejected.status_code != 200
        assert saves == []
        payload["explicitApproval"] = True
        saved = client.post(endpoint + "/save", json=payload)
        assert saved.status_code == 200, saved.text
        assert len(saves) == 1
        current = case["host"].service.get_layout(case["principal"], "site-local", "fl-main")
        assert current["revision"] == saved.json()["savedLayout"]["revision"]
        assert {key: value for key, value in current["layout"].items() if key != "updatedAt"} == {
            key: value for key, value in prepared["candidateLayout"].items() if key != "updatedAt"}


def test_selection_cannot_be_applied_after_source_revision_changes(case, monkeypatch):
    selection, _ = selected(case)
    proposal = case["host"].design_loop_service.inspect_proposal(tenant_id=case["principal"].tenant_id,
        site_id="site-local", proposal_id=selection["proposalId"], proposal_revision=selection["proposalRevision"])["proposal"]
    monkeypatch.setattr(case["service"], "_fingerprint", lambda *args: "0" * 64)
    assert_code("generation_sources_changed", lambda: case["host"].generation_draft_adapter.validate(
        case["principal"], "site-local", "fl-main", proposal))


def test_concept_destination_is_separate_idempotent_and_bounded(case):
    body = {"workspaceId": "new-destination", "editorContext": case["options"]["editor_context"],
        "request": {"requestKey": "destination-1", "expectedBaseRevision": layout_revision(case["saved"]),
                    "displayName": "Concept review", "widthMeters": 55, "depthMeters": 35, "confirmConceptualFloor": True}}
    with client_for(case) as client:
        url = "/api/facility-layout-planning/site-local/fl-main/destination"
        first = client.post(url, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["layoutId"] != "fl-main"
        second = client.post(url, json=body)
        assert second.status_code == 200, second.text
        assert second.json()["layoutId"] == first.json()["layoutId"]
        assert not second.json()["created"]
        created = case["host"].service.get_layout(case["principal"], "site-local", first.json()["layoutId"])["layout"]
        assert created["placements"] == []
        assert created["extensions"]["facilityPlan"]["widthMeters"] == 55
        assert case["host"].service.get_layout(case["principal"], "site-local", "fl-main")["layout"] == case["saved"]
        body["request"]["widthMeters"] = 99
        conflict = client.post(url, json=body)
        assert conflict.status_code != 200
        assert conflict.json()["detail"]["error"]["code"] == "generation_destination_retry_conflict"


@pytest.mark.parametrize("mutation", [{"confirmConceptualFloor": False}, {"widthMeters": True},
                                      {"widthMeters": -1}, {"displayName": ""}])
def test_destination_requires_explicit_valid_dimensions(case, mutation):
    request = {"requestKey": "destination-invalid", "expectedBaseRevision": layout_revision(case["saved"]),
               "displayName": "Concept", "widthMeters": 40, "depthMeters": 30, "confirmConceptualFloor": True, **mutation}
    with client_for(case) as client:
        result = client.post("/api/facility-layout-planning/site-local/fl-main/destination",
            json={"workspaceId": "destination-invalid", "request": request, "editorContext": case["options"]["editor_context"]})
        assert result.status_code != 200
