"""Real repository/transaction tests; no model, renderer, or user data."""
import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID
from ai_inspector.facility_layout.host import _revision
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.operation_proposals import create
from ai_inspector.facility_layout.routing import persisted_route_fingerprint, routing_layout_fingerprint
from ai_inspector.facility_layout.api import create_facility_layout_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def context(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    yield host.service, host.principal()
    host.close()


def current(context):
    service, principal = context
    return service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)


def propose(context, **kwargs):
    service, principal = context
    return create(service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, current(context)["revision"], **kwargs)


def approve(context, proposal, *, explicit=True, key="test-key"):
    service, principal = context
    return service.approve_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
        proposal["proposalId"], proposal["alternative"]["transactionBinding"],
        session_id="test-session", idempotency_key=key, explicit_approval=explicit)


def apply(context, proposal, approval, *, key="test-key"):
    service, principal = context
    return service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
        approval["approvalToken"], proposal["alternative"]["transactionBinding"],
        session_id="test-session", idempotency_key=key)


def test_preview_approval_commit_replay_and_exact_undo(context):
    before = current(context)
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Approved layout"}])
    assert current(context) == before
    assert proposal["approvalRequired"] and proposal["previewPure"]
    with pytest.raises(FacilityLayoutError):
        approve(context, proposal, explicit=False)
    approval = approve(context, proposal)
    saved = apply(context, proposal, approval)
    assert current(context)["layout"]["displayName"] == "Approved layout"
    replay = apply(context, proposal, approval)
    assert replay["replayed"] and replay["revision"] == saved["revision"]
    undo = propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    assert current(context)["revision"] == saved["revision"]
    restored = apply(context, undo, approve(context, undo, key="undo-key"), key="undo-key")
    expected, actual = deepcopy(before["layout"]), deepcopy(restored["layout"])
    expected["updatedAt"] = actual["updatedAt"]
    assert expected == actual


@pytest.fixture
def asset_host(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    try:
        yield host
    finally:
        host.close()


def _place_review_assets(host):
    context = host.service, host.principal()
    assets = host.ensure_bootstrap()["assetCatalog"]
    placements = [{
        "placementId": identifier,
        "assetId": asset["assetId"],
        "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "transform": {"position": {"x": x, "y": 0, "z": 6},
            "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
        "positionMode": "manual", "snapRelationship": None, "metadata": {},
    } for identifier, asset, x in [
        ("pl-undo-target", assets[2], 6), ("pl-undo-unrelated", assets[1], 18)]]
    host.service.apply_operations(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
        current(context)["revision"], [{"op": "place_asset", "placement": item} for item in placements])
    return context, placements


def _advance_asset_head(host, asset_id):
    previous = host._catalog[asset_id]
    updated = deepcopy(previous)
    updated["definition"]["description"] += " Updated catalog authority."
    updated["assetDefinitionRevision"] = _revision(updated["definition"])
    assert updated["assetDefinitionRevision"] != previous["assetDefinitionRevision"]
    host._catalog[asset_id] = updated
    host._asset_versions[(asset_id, updated["assetDefinitionRevision"])] = deepcopy(updated)
    assert (asset_id, previous["assetDefinitionRevision"]) in host._asset_versions


def _ordinary_review_route_context(asset_host, *, stale):
    context, placements = _place_review_assets(asset_host)
    before = current(context)
    document = deepcopy(before["layout"])
    for index, z in enumerate((14, 16)):
        points = [{"x": 2, "y": 0, "z": z}, {"x": 10, "y": 0, "z": z}]
        route = {
            "routeId": f"rt-undo-ordinary-{index}", "routeKind": "material",
            "sourceEndpoint": {"kind": "world_point", "position": points[0]},
            "targetEndpoint": {"kind": "world_point", "position": points[-1]},
            "routingMode": "polyline", "centerline": points, "corridorWidth": 1,
            "sourceRevisions": {
                "layout": "0" * 64 if stale else routing_layout_fingerprint(document),
                "shell": document["sourceShellRef"]["shellRevision"],
                "policy": document["policySetRef"]["policySetRevision"],
            },
            "requirements": [], "evidence": [],
        }
        route["routeFingerprint"] = persisted_route_fingerprint(route)
        document["routes"].append(route)
    asset_host.service.layout_repository.save_layout(asset_host.principal(), LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID, document, before["revision"])
    return context, placements, current(context)


@pytest.mark.parametrize("stale", [False, True])
def test_ordinary_route_sources_survive_approved_move_and_undo(asset_host, stale):
    context, placements, before = _ordinary_review_route_context(asset_host, stale=stale)
    proposal = propose(context, operations=[{"op": "move_placement",
        "placementId": placements[0]["placementId"], "position": {"x": 10, "y": 0, "z": 6}}])
    assert current(context) == before
    saved = apply(context, proposal, approve(context, proposal))
    for route in saved["layout"]["routes"]:
        assert route["sourceRevisions"]["layout"] == routing_layout_fingerprint(saved["layout"])
        assert route["routeFingerprint"] == persisted_route_fingerprint(route)
    undo = propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    restored = apply(context, undo, approve(context, undo, key="undo-route-key"), key="undo-route-key")
    expected = deepcopy(before["layout"])
    expected["updatedAt"] = restored["layout"]["updatedAt"]
    for route in expected["routes"]:
        route["sourceRevisions"]["layout"] = routing_layout_fingerprint(expected)
        route["routeFingerprint"] = persisted_route_fingerprint(route)
    assert restored["layout"] == expected
    assert asset_host.service._diagnose_routing(asset_host.principal(), LOCAL_SITE_ID, expected)["valid"]


@pytest.mark.parametrize("defect", ["shell", "policy", "fingerprint", "endpoint"])
def test_ordinary_route_undo_does_not_refresh_invalid_historical_routes(asset_host, defect):
    context, _, before = _ordinary_review_route_context(asset_host, stale=True)
    document = deepcopy(before["layout"])
    route = document["routes"][0]
    if defect in {"shell", "policy"}:
        route["sourceRevisions"][defect] = "9" * 64
    elif defect == "endpoint":
        route["centerline"][0]["x"] += 0.5
    route["routeFingerprint"] = ("9" * 64 if defect == "fingerprint"
        else persisted_route_fingerprint(route))
    asset_host.service.layout_repository.save_layout(asset_host.principal(), LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID, document, before["revision"])
    proposal = propose(context, operations=[{"op": "delete_route", "routeId": route["routeId"]}])
    saved = apply(context, proposal, approve(context, proposal))
    before_undo = current(context)
    with pytest.raises(FacilityLayoutError) as caught:
        propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    assert caught.value.code == "routing_validation_failed"
    expected_code = {"fingerprint": "stale_route_geometry", "endpoint": "route_endpoint_geometry_mismatch"}.get(
        defect, "stale_route_source_revision")
    assert any(finding["code"] == expected_code for finding in caught.value.details["findings"])
    assert current(context) == before_undo


@pytest.mark.parametrize("phase", ["create", "preview", "apply"])
@pytest.mark.parametrize("edit", ["move", "replace"])
def test_undo_rejects_stale_restored_asset_at_each_boundary(asset_host, phase, edit):
    host = asset_host
    context, placements = _place_review_assets(host)
    target = placements[0]
    if edit == "move":
        operation = {"op": "move_placement", "placementId": target["placementId"],
            "position": {"x": 10, "y": 0, "z": 6}}
    else:
        replacement = host.ensure_bootstrap()["assetCatalog"][0]
        operation = {"op": "replace_asset", "placementId": target["placementId"],
            "assetId": replacement["assetId"],
            "assetDefinitionRevision": replacement["assetDefinitionRevision"]}
    proposal = propose(context, operations=[operation])
    saved = apply(context, proposal, approve(context, proposal))
    receipt_id = saved["receipt"]["receiptId"]
    if phase != "create":
        undo = propose(context, undo_receipt_id=receipt_id)
        approval = approve(context, undo, key="undo-stale-asset")
    _advance_asset_head(host, target["assetId"])
    before = current(context)
    with pytest.raises(FacilityLayoutError) as raised:
        if phase == "create":
            propose(context, undo_receipt_id=receipt_id)
        elif phase == "preview":
            host.service.get_layout_proposal_preview(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                undo["proposalId"])
        else:
            apply(context, undo, approval, key="undo-stale-asset")
    assert raised.value.code == "stale_asset_definition_revision"
    assert raised.value.details["dependencyId"] == target["assetId"]
    assert current(context) == before


@pytest.mark.parametrize("edit", ["move", "rename"])
def test_undo_keeps_unrelated_historical_asset_revisions_valid(asset_host, edit):
    host = asset_host
    context, placements = _place_review_assets(host)
    _advance_asset_head(host, placements[1]["assetId"])
    before = current(context)
    operation = ({"op": "move_placement", "placementId": placements[0]["placementId"],
        "position": {"x": 10, "y": 0, "z": 6}} if edit == "move"
        else {"op": "rename_layout", "displayName": "Rename with pinned assets"})
    proposal = propose(context, operations=[operation])
    saved = apply(context, proposal, approve(context, proposal))
    undo = propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    restored = apply(context, undo, approve(context, undo, key="undo-pinned-assets"), key="undo-pinned-assets")
    expected = deepcopy(before["layout"])
    expected["updatedAt"] = restored["layout"]["updatedAt"]
    assert restored["layout"] == expected


def _disable_agent_preview(service):
    enabled = FacilityLayoutFeatureFlags.all_enabled()
    disabled = FacilityLayoutFeatureFlags(tuple((name, value and name !=
        "INSPECTORPRO_FACILITY_LAYOUT_AGENT_PREVIEW") for name, value in enabled.values))
    service.capability_gate = disabled.require


@pytest.mark.parametrize("undo", [False, True])
def test_disabled_feature_blocks_direct_operation_and_undo_creation(context, undo):
    service, _ = context
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "First approved"}])
    saved = apply(context, proposal, approve(context, proposal))
    arguments = ({"undo_receipt_id": saved["receipt"]["receiptId"]} if undo else
        {"operations": [{"op": "rename_layout", "displayName": "Blocked"}]})
    before = current(context)
    _disable_agent_preview(service)
    with pytest.raises(FacilityLayoutError) as raised:
        propose(context, **arguments)
    assert raised.value.code == "facility_feature_disabled"
    assert raised.value.details["capability"] == "agent_preview"
    assert current(context) == before


@pytest.mark.parametrize("undo", [False, True])
def test_disabled_feature_blocks_existing_preview_and_approved_commit(context, undo):
    service, principal = context
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Approved"}])
    if undo:
        saved = apply(context, proposal, approve(context, proposal))
        proposal = propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    approval = approve(context, proposal, key="disable-before-apply")
    before = current(context)
    _disable_agent_preview(service)
    with pytest.raises(FacilityLayoutError) as preview_error:
        service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal["proposalId"])
    assert preview_error.value.code == "facility_feature_disabled"
    with pytest.raises(FacilityLayoutError) as apply_error:
        apply(context, proposal, approval, key="disable-before-apply")
    assert apply_error.value.code == "facility_feature_disabled"
    assert current(context) == before


@pytest.mark.parametrize("undo", [False, True])
def test_assisted_gateway_cannot_bypass_disabled_preview_feature(asset_host, undo):
    pytest.importorskip("jsonschema", reason="Requires optional Codex pilot dependencies")
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway

    host = asset_host
    context = host.service, host.principal()
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Gateway base"}])
    saved = apply(context, proposal, approve(context, proposal))
    gateway = FacilityEditGateway(host.agent_runtime, host.principal(), {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]},
        turn_id="disabled-operation-preview")
    tool, arguments = (("preview_facility_undo", {"receiptId": saved["receipt"]["receiptId"]}) if undo else
        ("preview_facility_operations", {"operations": [{"op": "rename_layout", "displayName": "Blocked"}]}))

    async def run():
        assert (await gateway.call(tool, arguments))["ok"]
        assert gateway.proposal
        _disable_agent_preview(host.service)
        result = await gateway.call(tool, arguments)
        assert result["ok"] is False
        assert result["error"]["code"] == "facility_feature_disabled"
        assert gateway.proposal is None

    asyncio.run(run())
    assert current(context)["revision"] == saved["revision"]


def test_stale_approved_operations_do_not_overwrite_manual_edits(context):
    service, principal = context
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Agent name"}])
    approval = approve(context, proposal)
    manual = service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, current(context)["revision"],
        [{"op": "rename_layout", "displayName": "Manual name"}])
    with pytest.raises(FacilityLayoutError):
        apply(context, proposal, approval)
    assert current(context)["revision"] == manual["revision"]


def test_changed_binding_is_not_approved(context):
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Proposed"}])
    proposal["alternative"]["transactionBinding"]["diffHash"] = "0" * 64
    with pytest.raises(FacilityLayoutError):
        approve(context, proposal)


@pytest.mark.parametrize("operations", [[], [{"op": "clear_layout_contents"}],
    [{"op": "rename_layout", "displayName": "Partial"}, {"op": "move_placement", "placementId": "missing", "position": {"x": 1, "y": 0, "z": 1}}]])
def test_invalid_or_forbidden_batch_has_no_partial_save(context, operations):
    before = current(context)
    with pytest.raises(FacilityLayoutError):
        propose(context, operations=operations)
    assert current(context) == before


def test_undo_refuses_to_clobber_subsequent_changes(context):
    service, principal = context
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "First"}])
    saved = apply(context, proposal, approve(context, proposal))
    later = service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
        [{"op": "rename_layout", "displayName": "Second"}])
    with pytest.raises(FacilityLayoutError):
        propose(context, undo_receipt_id=saved["receipt"]["receiptId"])
    assert current(context)["revision"] == later["revision"]


def test_viewer_cannot_create_or_approve_changes(context):
    service, principal = context
    viewer = replace(principal, roles=("viewer",))
    with pytest.raises(FacilityLayoutError):
        propose((service, viewer), operations=[{"op": "rename_layout", "displayName": "Unauthorized"}])
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Proposed"}])
    with pytest.raises(FacilityLayoutError):
        approve((service, viewer), proposal)


def test_cross_site_proposal_does_not_leak_document(context):
    service, principal = context
    with pytest.raises(FacilityLayoutError):
        create(service, principal, "site-other", LOCAL_LAYOUT_ID, current(context)["revision"],
            operations=[{"op": "rename_layout", "displayName": "Wrong site"}])


def test_undo_http_contract_is_preview_only_and_principal_bound(context):
    service, principal = context
    proposal = propose(context, operations=[{"op": "rename_layout", "displayName": "Approved"}])
    saved = apply(context, proposal, approve(context, proposal))
    authority = {"principal": principal}
    app = FastAPI()
    app.include_router(create_facility_layout_router(service=service,
        principal_resolver=lambda request: authority["principal"]))
    body = {"baseRevision": saved["revision"], "receiptId": saved["receipt"]["receiptId"]}
    url = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/operation-undo-preview"
    with TestClient(app) as client:
        response = client.post(url, json=body)
        assert response.status_code == 200
        assert response.json()["approvalRequired"] is True
        assert response.json()["alternative"]["strategy"] == "exact-undo-v1"
        assert current(context)["revision"] == saved["revision"]
        for invalid in ({**body, "approved": True}, {"receiptId": body["receiptId"]},
                        {**body, "baseRevision": False}):
            assert client.post(url, json=invalid).status_code == 422
        authority["principal"] = replace(principal, roles=("viewer",))
        assert client.post(url, json=body).status_code == 403
    assert current(context)["revision"] == saved["revision"]
