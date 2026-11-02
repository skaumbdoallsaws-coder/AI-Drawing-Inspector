"""Direct consent uses real saved-layout validation, transactions and receipt Undo."""
import asyncio
from dataclasses import replace

import pytest

from ai_inspector.facility_layout.direct_edit_policy import evaluate
from tools.check_codex_facility_authoring import SavedGym, SOURCE_ROOT, LAYOUT_RELATIVE, case_operations


@pytest.fixture(scope="module")
def gym(tmp_path_factory):
    if not (SOURCE_ROOT / LAYOUT_RELATIVE).is_file():
        pytest.skip("Saved Private Gym fixture unavailable")
    value = SavedGym(tmp_path_factory.mktemp("direct") / "isolated")
    try:
        yield value
    finally:
        value.close()


def stage(gym, operations=None, receipt_id=None, mode="direct"):
    gateway = gym.gateway(gym.current()["revision"])
    gateway.edit_mode = mode
    name, args = (("preview_facility_undo", {"receiptId": receipt_id}) if receipt_id else
                  ("preview_facility_operations", {"operations": operations}))
    result = asyncio.run(gateway.call(name, args))
    assert result["ok"], result
    response = gym.client.get(gym.url + f'/proposals/{result["data"]["proposalId"]}/preview')
    assert response.status_code == 200, response.text
    return response.json()


def authorize(gym, preview, key, **overrides):
    return gym.client.post(gym.url + "/approvals", json={
        "proposalId": preview["proposalId"], "binding": preview["transactionBinding"],
        "idempotencyKey": key, "authorizationMode": "direct", "directConsent": True,
        "explicitApproval": False, **overrides})


def test_real_gym_direct_batch_replay_and_one_receipt_undo(gym):
    before = gym.current()
    operations = case_operations(gym, "floor_marking_generated_id")
    operations += [{"op": "rename_layout", "displayName": "Direct edit verification"}]
    proposal = stage(gym, operations)
    assert gym.current() == before
    assert proposal["alternative"]["directApplyPolicy"]["eligible"]
    approval = authorize(gym, proposal, "direct-gym-batch")
    assert approval.status_code == 200, approval.text
    assert approval.json()["authorizationMode"] == "direct"
    committed = gym.commit(proposal, approval.json(), "direct-gym-batch")
    assert committed.status_code == 200, committed.text
    assert committed.json()["requestedEditMode"] == "direct"
    replay = gym.commit(proposal, approval.json(), "direct-gym-batch")
    assert replay.status_code == 200 and replay.json()["replayed"]
    undo = stage(gym, receipt_id=committed.json()["receipt"]["receiptId"])
    undo_approval = authorize(gym, undo, "direct-gym-undo")
    assert undo_approval.status_code == 200, undo_approval.text
    restored = gym.commit(undo, undo_approval.json(), "direct-gym-undo")
    assert restored.status_code == 200, restored.text
    after = gym.current()["layout"]
    after["updatedAt"] = before["layout"]["updatedAt"]
    assert after == before["layout"]
    gym.assert_source()


@pytest.mark.parametrize("case", ["floor_surface_color", "zone_color"])
def test_broad_settings_or_geometry_edit_requires_review(gym, case):
    before = gym.current()
    proposal = stage(gym, case_operations(gym, case))
    assert not proposal["alternative"]["directApplyPolicy"]["eligible"]
    response = authorize(gym, proposal, "direct-denied-" + case)
    assert response.status_code >= 400
    assert "direct_review_required" in response.text
    assert gym.current() == before


@pytest.mark.parametrize("mode,consent", [("preview", True), ("direct", False)])
def test_direct_mode_and_current_consent_are_both_required(gym, mode, consent):
    before = gym.current()
    proposal = stage(gym, [{"op": "rename_layout", "displayName": "No save"}], mode=mode)
    response = authorize(gym, proposal, "direct-mode-" + mode, directConsent=consent)
    assert response.status_code >= 400
    assert gym.current() == before


def test_direct_cannot_bypass_permissions_or_stale_revision(gym):
    proposal = stage(gym, [{"op": "rename_layout", "displayName": "Stale"}])
    before = gym.current()
    gym.authority["principal"] = replace(gym.principal, roles=("viewer",))
    try:
        assert authorize(gym, proposal, "direct-viewer").status_code == 403
    finally:
        gym.authority["principal"] = gym.principal
    other = stage(gym, [{"op": "rename_layout", "displayName": "Concurrent edit"}])
    approval = authorize(gym, other, "direct-concurrent")
    committed = gym.commit(other, approval.json(), "direct-concurrent")
    assert committed.status_code == 200
    assert authorize(gym, proposal, "direct-stale").status_code >= 400
    undo = stage(gym, receipt_id=committed.json()["receipt"]["receiptId"])
    approval = authorize(gym, undo, "direct-concurrent-undo")
    assert gym.commit(undo, approval.json(), "direct-concurrent-undo").status_code == 200
    after = gym.current()["layout"]
    after["updatedAt"] = before["layout"]["updatedAt"]
    assert after == before["layout"]


def test_policy_counts_actual_affected_objects_and_denies_unknown_or_destructive_operations():
    assert not evaluate([{"op": "set_appearance"}], {"affectedIds": [str(i) for i in range(21)]})["eligible"]
    assert not evaluate([{"op": "move_placement"}] * 21, {})["eligible"]
    for op in ["delete_zone", "replace_asset", "set_ground", "set_plan_settings", "future_operation",
               "set_snap_relationship"]:
        assert not evaluate([{"op": op}], {})["eligible"]
    # The server's own planned packages: a stack or a surface sets snap relationships (plan_facility_stack).
    assert evaluate([{"op": "duplicate_placement"}, {"op": "set_snap_relationship"}], {}, planned=True)["eligible"]
