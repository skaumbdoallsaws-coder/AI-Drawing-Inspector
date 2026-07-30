from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.api import create_facility_layout_router
from ai_inspector.facility_layout.authorization import (
    FacilityPrincipal,
    local_facility_principal,
)
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.identity import FacilityPrincipalResolver
from ai_inspector.facility_layout.transaction_adapter import (
    deterministic_facility_proposal_id,
    facility_transaction_target,
)
from ai_inspector.facility_layout.validate import validate_layout
from ai_inspector.transactions import (
    ExactBinding,
    JsonReceiptStore,
    PreparedRecord,
    PrincipalBinding,
    TransactionReceipt,
    canonical_json_bytes,
)
from ai_inspector.transactions.stores import MAX_RECORD_BYTES


SESSION = "facility-layout-p8-session"
FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"


def _pilot_resolver() -> FacilityPrincipalResolver:
    return FacilityPrincipalResolver(
        (
            (
                "a" * 64,
                FacilityPrincipal(
                    principal_id="proposal-maker",
                    tenant_id="local",
                    allowed_site_ids=(LOCAL_SITE_ID,),
                    roles=("layout_admin",),
                ),
            ),
            (
                "b" * 64,
                FacilityPrincipal(
                    principal_id="proposal-checker",
                    tenant_id="local",
                    allowed_site_ids=(LOCAL_SITE_ID,),
                    roles=("approver",),
                ),
            ),
        ),
        LOCAL_SITE_ID,
    )


def _client(root: Path) -> tuple[TestClient, LocalFacilityLayoutHost]:
    host = LocalFacilityLayoutHost(root)
    app = FastAPI()
    app.include_router(host.create_router())
    return TestClient(app), host


def _service_client(host: LocalFacilityLayoutHost) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_facility_layout_router(
            service=host.service,
            principal_resolver=lambda _request: host.principal(),
        )
    )
    return TestClient(app)


def _request(bootstrap: dict, *, alternatives: int = 2) -> dict:
    layout = bootstrap["layout"]["layout"]
    assets = bootstrap["assetCatalog"][:3]
    return {
        "schemaVersion": 1,
        "requestId": "request-p8-product-proof",
        "objective": "place_asset_set",
        "assetSet": [
            {
                "itemId": f"item-{index + 1}",
                "assetId": asset["assetId"],
                "assetDefinitionRevision": (
                    asset["assetDefinitionRevision"]
                ),
                "quantity": 1,
                "stage": index,
            }
            for index, asset in enumerate(assets)
        ],
        "strategies": ["compact_rows", "balanced_grid"][:alternatives],
        "maximumAlternatives": alternatives,
        "spacingMeters": 1.0,
        "cleanup": {
            "enabled": False,
            "moveAuto": True,
            "movableManualPlacementIds": [],
        },
        "zoneSizing": [],
        "routes": [],
        "sourceRevisions": {
            "shell": layout["sourceShellRef"]["shellRevision"],
            "policy": layout["policySetRef"]["policySetRevision"],
        },
    }


def _proposal(
    client: TestClient,
    bootstrap: dict,
) -> tuple[dict, dict]:
    response = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/proposals"
        ),
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "request": _request(bootstrap),
        },
    )
    assert response.status_code == 200, response.text
    proposal_set = response.json()
    selected = next(
        item
        for item in proposal_set["alternatives"]
        if item["proposalId"] == proposal_set["selectedProposalId"]
    )
    return proposal_set, selected


def _approve(
    client: TestClient,
    selected: dict,
    *,
    session: str = SESSION,
    idempotency_key: str = "p8-product-approval-001",
) -> dict:
    response = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/approvals"
        ),
        headers={"X-InspectorPro-Session": session},
        json={
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": idempotency_key,
            "explicitApproval": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _apply(
    client: TestClient,
    selected: dict,
    approval: dict,
    *,
    session: str = SESSION,
    idempotency_key: str = "p8-product-approval-001",
):
    return client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/apply"
        ),
        headers={"X-InspectorPro-Session": session},
        json={
            "approvalToken": approval["approvalToken"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": idempotency_key,
        },
    )


def _layout_files(root: Path) -> dict[str, bytes]:
    layout_root = root / "layouts"
    return {
        path.relative_to(layout_root).as_posix(): path.read_bytes()
        for path in sorted(layout_root.rglob("*"))
        if path.is_file()
    }


def _request_proposals(
    client: TestClient,
    bootstrap: dict,
    *,
    request: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    response = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/proposals"
        ),
        headers=headers,
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "request": request or _request(bootstrap),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _selected(proposal_set: dict) -> dict:
    return next(
        item
        for item in proposal_set["alternatives"]
        if item["proposalId"] == proposal_set["selectedProposalId"]
    )


def _publish_test_vehicle(host: LocalFacilityLayoutHost):
    documents = json.loads(
        (FIXTURES / "p0_authority_documents.json").read_text(
            encoding="ascii"
        )
    )
    vehicle = next(
        deepcopy(item)
        for item in documents
        if item.get("documentKind") == "vehicle_profile"
    )
    vehicle["tenantId"] = "local"
    vehicle["siteId"] = LOCAL_SITE_ID
    vehicle["status"] = "draft"
    return host._ensure_published(
        host.vehicle_repository,
        vehicle,
        "vehicleProfileId",
    )


def test_product_proposal_preview_is_pure_and_apply_is_exact(tmp_path):
    root = tmp_path / "facility"
    client, host = _client(root)
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    assert bootstrap["capabilities"]["fullLayoutProposals"] is True
    assert bootstrap["capabilities"]["atomicProposalApply"] is True
    before = _layout_files(root)

    proposal_set, selected = _proposal(client, bootstrap)

    assert proposal_set["previewPure"] is True
    assert proposal_set["layoutRevision"] == bootstrap["layout"]["revision"]
    assert len(proposal_set["alternatives"]) == 2
    assert selected["metrics"]["completeAssetSet"] is True
    assert selected["metrics"]["createdPlacementCount"] == 3
    assert selected["newHardFindingIds"] == []
    assert _layout_files(root) == before

    preview = client.get(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            f"/proposals/{selected['proposalId']}/preview"
        )
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["previewPure"] is True
    assert (
        preview.json()["alternative"]["ghostPreview"]["layout"]
        == selected["ghostPreview"]["layout"]
    )
    assert _layout_files(root) == before

    approval = _approve(client, selected)
    applied = _apply(client, selected, approval)
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["operationResult"]["document"] == (
        selected["ghostPreview"]["layout"]
    )
    assert result["alternativeId"] == selected["alternativeId"]
    assert result["metrics"] == selected["metrics"]
    assert result["layout"]["placements"] == (
        selected["ghostPreview"]["layout"]["placements"]
    )

    receipt_id = result["receipt"]["receiptId"]
    receipt = client.get(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            f"/receipts/{receipt_id}"
        )
    )
    assert receipt.status_code == 200
    assert receipt.json() == result["receipt"]

    replay = _apply(client, selected, approval)
    assert replay.status_code == 200
    assert replay.json()["receipt"]["receiptId"] == receipt_id
    assert replay.json()["replayed"] is True
    assert replay.json()["recovered"] is True

    host.close()
    reopened, reopened_host = _client(root)
    try:
        durable = reopened.get(
            (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
                f"/receipts/{receipt_id}"
            )
        )
        assert durable.status_code == 200
        assert durable.json() == result["receipt"]
        restarted_replay = _apply(
            reopened,
            selected,
            approval,
        )
        assert restarted_replay.status_code == 200
        assert restarted_replay.json()["receipt"] == result["receipt"]
        assert restarted_replay.json()["replayed"] is True
        assert restarted_replay.json()["recovered"] is True
    finally:
        reopened_host.close()


def test_exact_repeated_request_reuses_deterministic_proposals(tmp_path):
    client, host = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    first = _request_proposals(client, bootstrap)
    second = _request_proposals(client, bootstrap)

    assert second == first
    assert first["selectedProposalId"].startswith("flp-")
    assert [item["proposalId"] for item in first["alternatives"]] == [
        item["proposalId"] for item in second["alternatives"]
    ]
    assert [item["alternativeId"] for item in first["alternatives"]] == [
        item["alternativeId"] for item in second["alternatives"]
    ]
    for alternative in first["alternatives"]:
        stored = host.transaction_runtime.kernel.get_proposal(
            alternative["proposalId"]
        )
        assert stored.principal is not None
        assert stored.principal_claimable is False
    host.close()


def test_proposal_id_is_pinned_to_the_approved_contract_fields():
    values = {
        "layout_id": "fl-contract",
        "base_revision": "a" * 64,
        "proposal_type": "layout-alternative:compact_rows",
        "semantic_plan_hash": "b" * 64,
        "dependency_fingerprint": "c" * 64,
    }
    proposal_id = deterministic_facility_proposal_id(**values)

    assert proposal_id == (
        "flp-e449a59ef338f057c16b295e157deb17"
        "e74776573f161cf3ce4f13251fc528dc"
    )
    for field, replacement in (
        ("layout_id", "fl-other"),
        ("base_revision", "d" * 64),
        ("proposal_type", "layout-alternative:balanced_grid"),
        ("semantic_plan_hash", "e" * 64),
        ("dependency_fingerprint", "f" * 64),
    ):
        changed = {**values, field: replacement}
        assert deterministic_facility_proposal_id(**changed) != proposal_id


def test_proposal_owner_and_tenant_site_target_fail_closed(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility")
    bootstrap = host.ensure_bootstrap()
    app = FastAPI()

    def principal(request: Request):
        roles = tuple(
            item
            for item in request.headers.get(
                "X-Test-Roles",
                "admin",
            ).split(",")
            if item
        )
        return FacilityPrincipal(
            principal_id=request.headers.get("X-Test-Principal", "owner"),
            tenant_id=request.headers.get("X-Test-Tenant", "local"),
            allowed_site_ids=(LOCAL_SITE_ID,),
            roles=roles,
        )

    app.include_router(
        create_facility_layout_router(
            service=host.service,
            principal_resolver=principal,
        )
    )
    client = TestClient(app)
    proposal_set = _request_proposals(client, bootstrap)
    selected = _selected(proposal_set)
    preview_path = (
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        f"/proposals/{selected['proposalId']}/preview"
    )
    approval_path = (
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/approvals"
    )
    approval_body = {
        "proposalId": selected["proposalId"],
        "binding": selected["transactionBinding"],
        "idempotencyKey": "p8-owned-proposal-001",
        "explicitApproval": True,
    }

    other_user = {
        "X-Test-Principal": "other-user",
        "X-Test-Roles": "viewer",
    }
    assert client.get(preview_path, headers=other_user).status_code == 403
    other_approval = client.post(
        approval_path,
        headers={
            **other_user,
            "X-InspectorPro-Session": SESSION,
        },
        json=approval_body,
    )
    assert other_approval.status_code == 403
    other_cancel = client.delete(
        preview_path.removesuffix("/preview"),
        headers={
            **other_user,
            "X-InspectorPro-Session": SESSION,
        },
    )
    assert other_cancel.status_code == 403

    foreign = {
        "X-Test-Tenant": "foreign-tenant",
        "X-Test-Principal": "owner",
    }
    foreign_preview = client.get(preview_path, headers=foreign)
    assert foreign_preview.status_code == 404
    foreign_approval = client.post(
        approval_path,
        headers={
            **foreign,
            "X-InspectorPro-Session": SESSION,
        },
        json=approval_body,
    )
    assert foreign_approval.status_code == 404
    foreign_cancel = client.delete(
        preview_path.removesuffix("/preview"),
        headers={
            **foreign,
            "X-InspectorPro-Session": SESSION,
        },
    )
    assert foreign_cancel.status_code == 404

    approval_response = client.post(
        approval_path,
        headers={"X-InspectorPro-Session": SESSION},
        json=approval_body,
    )
    assert approval_response.status_code == 200, approval_response.text
    approval = approval_response.json()
    foreign_apply = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/apply",
        headers={
            **foreign,
            "X-InspectorPro-Session": SESSION,
        },
        json={
            "approvalToken": approval["approvalToken"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p8-owned-proposal-001",
        },
    )
    assert foreign_apply.status_code == 404
    foreign_binding = deepcopy(selected["transactionBinding"])
    foreign_binding["target"] = facility_transaction_target(
        tenant_id="foreign-tenant",
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
    ).to_dict()
    forged_foreign_apply = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/apply",
        headers={
            **foreign,
            "X-InspectorPro-Session": SESSION,
        },
        json={
            "approvalToken": approval["approvalToken"],
            "binding": foreign_binding,
            "idempotencyKey": "p8-owned-proposal-001",
        },
    )
    assert forged_foreign_apply.status_code == 404

    applied = _apply(
        client,
        selected,
        approval,
        idempotency_key="p8-owned-proposal-001",
    )
    assert applied.status_code == 200, applied.text
    receipt_id = applied.json()["receipt"]["receiptId"]
    foreign_receipt = client.get(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            f"/receipts/{receipt_id}"
        ),
        headers=foreign,
    )
    assert foreign_receipt.status_code == 404
    host.close()


def test_stale_layout_and_wrong_session_fail_closed(tmp_path):
    client, _ = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    approval = _approve(
        client,
        selected,
        idempotency_key="p8-stale-approval-001",
    )

    wrong_session = _apply(
        client,
        selected,
        approval,
        session="another-editor-session",
        idempotency_key="p8-stale-approval-001",
    )
    assert wrong_session.status_code == 403
    assert wrong_session.json()["error"]["code"] == (
        "transaction_principal_mismatch"
    )

    renamed = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": [
                {
                    "op": "rename_layout",
                    "displayName": "Changed after approval",
                }
            ],
        },
    )
    assert renamed.status_code == 200
    stale = _apply(
        client,
        selected,
        approval,
        idempotency_key="p8-stale-approval-001",
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert stale.json()["error"]["details"]["currentRevision"] == (
        renamed.json()["revision"]
    )


def test_unrelated_catalog_change_does_not_invalidate_proposal(tmp_path):
    client, host = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    request = _request(bootstrap, alternatives=1)
    request["assetSet"] = request["assetSet"][:1]
    response = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/proposals"
        ),
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "request": request,
        },
    )
    assert response.status_code == 200, response.text
    selected = response.json()["alternatives"][0]
    approval = _approve(
        client,
        selected,
        idempotency_key="p8-unrelated-catalog-001",
    )

    unrelated_id = next(
        asset_id
        for asset_id in host._catalog
        if asset_id != request["assetSet"][0]["assetId"]
    )
    host._catalog[unrelated_id]["description"] = (
        "Compatible unrelated catalog presentation change."
    )
    referenced_id = request["assetSet"][0]["assetId"]
    host._catalog[referenced_id]["renderBundleRevision"] = "f" * 64
    host._catalog[referenced_id]["renderBundle"] = {
        "revision": "f" * 64,
        "compatibility": "definition-independent",
    }

    applied = _apply(
        client,
        selected,
        approval,
        idempotency_key="p8-unrelated-catalog-001",
    )
    assert applied.status_code == 200, applied.text


@pytest.mark.parametrize(
    (
        "dependency_kind",
        "repository_name",
        "reference_name",
        "identifier_name",
        "revision_name",
        "expected_code",
    ),
    [
        (
            "shell",
            "shell_repository",
            "sourceShellRef",
            "shellId",
            "shellRevision",
            "stale_shell_revision",
        ),
        (
            "policy",
            "policy_repository",
            "policySetRef",
            "policySetId",
            "policySetRevision",
            "stale_policy_revision",
        ),
    ],
)
def test_apply_rejects_stale_shell_and_policy_dependencies(
    tmp_path,
    dependency_kind,
    repository_name,
    reference_name,
    identifier_name,
    revision_name,
    expected_code,
):
    client, host = _client(tmp_path / dependency_kind)
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    key = f"p8-stale-{dependency_kind}-001"
    approval = _approve(client, selected, idempotency_key=key)
    reference = bootstrap["layout"]["layout"][reference_name]
    repository = getattr(host, repository_name)
    repository.deprecate(
        host.principal(),
        site_id=LOCAL_SITE_ID,
        authority_id=reference[identifier_name],
        expected_revision=reference[revision_name],
    )

    rejected = _apply(
        _service_client(host),
        selected,
        approval,
        idempotency_key=key,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == expected_code
    host.close()


def test_apply_rejects_stale_referenced_asset_definition(tmp_path):
    client, host = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    request = _request(bootstrap, alternatives=1)
    request["assetSet"] = request["assetSet"][:1]
    selected = _selected(
        _request_proposals(client, bootstrap, request=request)
    )
    key = "p8-stale-asset-definition-001"
    approval = _approve(client, selected, idempotency_key=key)
    asset_id = request["assetSet"][0]["assetId"]
    host._catalog[asset_id]["assetDefinitionRevision"] = "f" * 64

    rejected = _apply(
        client,
        selected,
        approval,
        idempotency_key=key,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == (
        "stale_asset_definition_revision"
    )
    host.close()


def test_apply_rejects_stale_process_map_revision(tmp_path):
    client, host = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    expected_revision = "7" * 64
    current_revision = {"value": expected_revision}

    def process_map_resolver(
        _principal,
        _site_id,
        _product_id,
        _map_id,
        _revision,
    ):
        return {
            "revision": current_revision["value"],
            "document": {
                "canvasNodes": [
                    {"id": "process-node-test", "type": "process_step"}
                ],
                "canvasEdges": [],
            },
        }

    host.service.process_map_resolver = process_map_resolver
    asset = bootstrap["assetCatalog"][0]
    updated = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": [
                {
                    "op": "place_asset",
                    "placement": {
                        "placementId": "pl-process-test",
                        "assetId": asset["assetId"],
                        "assetDefinitionRevision": (
                            asset["assetDefinitionRevision"]
                        ),
                        "transform": {
                            "position": {"x": 5, "y": 0, "z": 5},
                            "quaternion": {
                                "x": 0,
                                "y": 0,
                                "z": 0,
                                "w": 1,
                            },
                            "scale": 1,
                        },
                        "positionMode": "manual",
                        "snapRelationship": None,
                        "metadata": {},
                    },
                },
                {
                    "op": "attach_process_binding",
                    "processBinding": {
                        "processBindingId": "pb-process-test",
                        "productId": "product-process-test",
                        "processMapId": "map-process-test",
                        "processMapRevision": expected_revision,
                        "processNodeIds": ["process-node-test"],
                        "processEdgeIds": [],
                        "placementIds": ["pl-process-test"],
                        "routeIds": [],
                        "bindingRole": "resource",
                    },
                },
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    proposal_bootstrap = deepcopy(bootstrap)
    proposal_bootstrap["layout"] = updated.json()
    selected = _selected(
        _request_proposals(
            client,
            proposal_bootstrap,
            request=_request(proposal_bootstrap, alternatives=1),
        )
    )
    key = "p8-stale-process-map-001"
    approval = _approve(client, selected, idempotency_key=key)
    current_revision["value"] = "8" * 64

    rejected = _apply(
        client,
        selected,
        approval,
        idempotency_key=key,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == (
        "stale_process_map_revision"
    )
    host.close()


def test_apply_rejects_stale_vehicle_profile_revision(tmp_path):
    client, host = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    vehicle = _publish_test_vehicle(host)
    aisle = {
        "zoneId": "zn-p8-vehicle-aisle",
        "zoneType": "aisle",
        "label": "Vehicle proposal aisle",
        "boundary": [
            {"x": 2, "z": 8},
            {"x": 32, "z": 8},
            {"x": 32, "z": 14},
            {"x": 2, "z": 14},
        ],
        "floorElevation": 0,
        "anchors": [
            {
                "anchorId": "za-p8-vehicle-start",
                "anchorKind": "forklift",
                "position": {"x": 4, "y": 0, "z": 11},
                "facing": {"x": 1, "y": 0, "z": 0},
                "allowedRouteKinds": ["forklift"],
                "evidence": [],
            },
            {
                "anchorId": "za-p8-vehicle-end",
                "anchorKind": "forklift",
                "position": {"x": 30, "y": 0, "z": 11},
                "facing": {"x": 1, "y": 0, "z": 0},
                "allowedRouteKinds": ["forklift"],
                "evidence": [],
            },
        ],
        "evidence": [],
    }
    updated = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": [{"op": "add_zone", "zone": aisle}],
        },
    )
    assert updated.status_code == 200, updated.text
    proposal_bootstrap = deepcopy(bootstrap)
    proposal_bootstrap["layout"] = updated.json()
    request = _request(proposal_bootstrap, alternatives=1)
    request["assetSet"] = request["assetSet"][:1]
    request["routes"] = [
        {
            "routeRequestId": "route-p8-stale-vehicle",
            "routeKind": "forklift",
            "sourceEndpoint": {
                "kind": "zone_anchor",
                "zoneId": aisle["zoneId"],
                "anchorId": "za-p8-vehicle-start",
            },
            "targetEndpoint": {
                "kind": "zone_anchor",
                "zoneId": aisle["zoneId"],
                "anchorId": "za-p8-vehicle-end",
            },
            "vehicleProfileId": vehicle.document["vehicleProfileId"],
            "vehicleProfileRevision": vehicle.revision,
            "allowReverse": False,
        }
    ]
    selected = _selected(
        _request_proposals(
            client,
            proposal_bootstrap,
            request=request,
        )
    )
    key = "p8-stale-vehicle-profile-001"
    approval = _approve(client, selected, idempotency_key=key)
    host.vehicle_repository.deprecate(
        host.principal(),
        site_id=LOCAL_SITE_ID,
        authority_id=vehicle.document["vehicleProfileId"],
        expected_revision=vehicle.revision,
    )

    rejected = _apply(
        _service_client(host),
        selected,
        approval,
        idempotency_key=key,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == (
        "stale_vehicle_profile_revision"
    )
    host.close()


def test_proposal_binding_and_consent_are_exact(tmp_path):
    client, _ = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    endpoint = (
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/approvals"
    )
    headers = {"X-InspectorPro-Session": SESSION}

    missing_consent = client.post(
        endpoint,
        headers=headers,
        json={
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p8-no-consent-001",
            "explicitApproval": False,
        },
    )
    assert missing_consent.status_code == 403
    assert missing_consent.json()["error"]["code"] == (
        "explicit_approval_required"
    )

    altered = deepcopy(selected["transactionBinding"])
    altered["diffHash"] = "f" * 64
    wrong_diff = client.post(
        endpoint,
        headers=headers,
        json={
            "proposalId": selected["proposalId"],
            "binding": altered,
            "idempotencyKey": "p8-wrong-diff-001",
            "explicitApproval": True,
        },
    )
    assert wrong_diff.status_code == 409
    assert wrong_diff.json()["error"]["code"] == (
        "transaction_binding_mismatch"
    )


def test_editor_and_approver_authority_remain_separate(tmp_path):
    host = LocalFacilityLayoutHost(
        tmp_path / "facility",
        require_distinct_approver=True,
        principal_resolver=_pilot_resolver(),
    )
    bootstrap = host.ensure_bootstrap()
    app = FastAPI()

    def principal(request: Request):
        return FacilityPrincipal(
            principal_id=request.headers.get(
                "X-Test-Principal",
                "viewer-1",
            ),
            tenant_id="local",
            allowed_site_ids=(LOCAL_SITE_ID,),
            roles=(request.headers.get("X-Test-Role", "viewer"),),
        )

    app.include_router(
        create_facility_layout_router(
            service=host.service,
            principal_resolver=principal,
        )
    )
    client = TestClient(app)
    request = _request(bootstrap, alternatives=1)
    created = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/proposals"
        ),
        headers={
            "X-Test-Principal": "editor-1",
            "X-Test-Role": "editor",
        },
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "request": request,
        },
    )
    assert created.status_code == 200, created.text
    selected = created.json()["alternatives"][0]
    preview_path = (
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        f"/proposals/{selected['proposalId']}/preview"
    )
    approver_headers = {
        "X-Test-Principal": "approver-1",
        "X-Test-Role": "approver",
        "X-InspectorPro-Session": SESSION,
    }
    assert client.get(
        preview_path,
        headers=approver_headers,
    ).status_code == 403

    direct_write = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        headers=approver_headers,
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": [
                {
                    "op": "rename_layout",
                    "displayName": "Forbidden direct edit",
                }
            ],
        },
    )
    assert direct_write.status_code == 403

    same_maker = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/approvals"
        ),
        headers={
            "X-Test-Principal": "editor-1",
            "X-Test-Role": "admin",
            "X-InspectorPro-Session": "maker-admin-session",
        },
        json={
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p11-same-maker-rejected",
            "explicitApproval": True,
        },
    )
    assert same_maker.status_code == 403
    assert same_maker.json()["error"]["code"] == (
        "maker_checker_required"
    )

    approval = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/approvals"
        ),
        headers=approver_headers,
        json={
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p8-role-split-001",
            "explicitApproval": True,
        },
    )
    assert approval.status_code == 200, approval.text
    second_approver = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/approvals"
        ),
        headers={
            "X-Test-Principal": "approver-2",
            "X-Test-Role": "approver",
            "X-InspectorPro-Session": "second-approver-session",
        },
        json={
            "proposalId": selected["proposalId"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p8-role-split-002",
            "explicitApproval": True,
        },
    )
    assert second_approver.status_code == 403
    assert second_approver.json()["error"]["code"] == (
        "transaction_principal_mismatch"
    )
    creator_apply = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/apply"
        ),
        headers={
            "X-Test-Principal": "editor-1",
            "X-Test-Role": "layout_admin",
            "X-InspectorPro-Session": SESSION,
        },
        json={
            "approvalToken": approval.json()["approvalToken"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p8-role-split-001",
        },
    )
    assert creator_apply.status_code == 403
    assert creator_apply.json()["error"]["code"] == (
        "transaction_principal_mismatch"
    )
    applied = client.post(
        (
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
            "/apply"
        ),
        headers=approver_headers,
        json={
            "approvalToken": approval.json()["approvalToken"],
            "binding": selected["transactionBinding"],
            "idempotencyKey": "p8-role-split-001",
        },
    )
    assert applied.status_code == 200, applied.text
    assert len(applied.json()["layout"]["placements"]) == 3
    host.close()


def test_committed_layout_recovers_receipt_after_finalize_failure(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "facility"
    client, host = _client(root)
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    approval = _approve(
        client,
        selected,
        idempotency_key="p11-finalize-recovery-001",
    )
    receipt_store = host.transaction_runtime.kernel.receipt_store

    def fail_finalize(_prepared, _receipt):
        raise OSError("simulated receipt finalization failure")

    monkeypatch.setattr(receipt_store, "finalize", fail_finalize)
    with pytest.raises(
        OSError,
        match="simulated receipt finalization failure",
    ):
        _apply(
            client,
            selected,
            approval,
            idempotency_key="p11-finalize-recovery-001",
        )

    committed = client.get(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
    ).json()
    assert committed["revision"] != bootstrap["layout"]["revision"]
    assert len(committed["layout"]["placements"]) == 3
    committed_layout_files = _layout_files(root)
    host.close()

    reopened, reopened_host = _client(root)
    try:
        recovered = _apply(
            reopened,
            selected,
            approval,
            idempotency_key="p11-finalize-recovery-001",
        )
        assert recovered.status_code == 200, recovered.text
        result = recovered.json()
        assert result["revision"] == committed["revision"]
        assert result["layout"] == committed["layout"]
        assert result["replayed"] is True
        assert result["recovered"] is True
        assert _layout_files(root) == committed_layout_files

        receipt = result["receipt"]
        durable = reopened.get(
            (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
                f"/receipts/{receipt['receiptId']}"
            )
        )
        assert durable.status_code == 200
        assert durable.json() == receipt

        exact_retry = _apply(
            reopened,
            selected,
            approval,
            idempotency_key="p11-finalize-recovery-001",
        )
        assert exact_retry.status_code == 200
        assert exact_retry.json()["receipt"] == receipt
        assert exact_retry.json()["replayed"] is True
        assert exact_retry.json()["recovered"] is True
        assert _layout_files(root) == committed_layout_files
    finally:
        reopened_host.close()


def test_legacy_small_recovery_record_remains_reconcilable(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "facility"
    client, host = _client(root)
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    approval = _approve(
        client,
        selected,
        idempotency_key="p11-legacy-recovery-001",
    )
    compact_payload = host.service._proposal_commit_payload

    def legacy_recovery(alternative, prepared, dependencies):
        return {
            "schemaVersion": 1,
            "kind": "facility-layout-commit",
            "expectedChanged": bool(prepared.get("changed")),
            "expectedLayout": deepcopy(prepared["document"]),
            "commitPayload": compact_payload(
                alternative,
                prepared,
                dependencies,
            ),
        }

    monkeypatch.setattr(
        host.service,
        "_proposal_recovery_context",
        legacy_recovery,
    )
    receipt_store = host.transaction_runtime.kernel.receipt_store

    def fail_finalize(_prepared, _receipt):
        raise OSError("simulated legacy receipt finalization failure")

    monkeypatch.setattr(receipt_store, "finalize", fail_finalize)
    with pytest.raises(
        OSError,
        match="simulated legacy receipt finalization failure",
    ):
        _apply(
            client,
            selected,
            approval,
            idempotency_key="p11-legacy-recovery-001",
        )
    committed = client.get(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
    ).json()
    host.close()

    reopened, reopened_host = _client(root)
    try:
        recovered = _apply(
            reopened,
            selected,
            approval,
            idempotency_key="p11-legacy-recovery-001",
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["revision"] == committed["revision"]
        assert recovered.json()["layout"] == committed["layout"]
        assert recovered.json()["recovered"] is True
    finally:
        reopened_host.close()


def test_maximum_placement_recovery_and_receipt_stay_bounded(
    tmp_path,
):
    client, host = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    principal = host.principal()
    proposal = host.transaction_runtime.get_proposal(
        selected["proposalId"],
        tenant_id=principal.tenant_id,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        principal_id=principal.principal_id,
    )
    alternative, binding, prepared, dependencies = (
        host.service._regenerate_proposal(
            principal,
            proposal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
        )
    )

    placement = deepcopy(prepared["document"]["placements"][0])
    placements = []
    created_ids = []
    operation_results = []
    for index in range(5000):
        placement_id = f"pl-large-{index:04d}"
        item = deepcopy(placement)
        item["placementId"] = placement_id
        item["transform"]["position"]["x"] = float(index * 2)
        item["metadata"] = {
            "label": "x" * 128,
            "sequence": index,
        }
        placements.append(item)
        created_ids.append(placement_id)
        operation_results.append(
            {
                "index": index,
                "op": "place_asset",
                "createdIds": [placement_id],
                "affectedIds": [placement_id],
            }
        )
    maximum_document = deepcopy(prepared["document"])
    maximum_document["placements"] = placements
    validate_layout(maximum_document)

    maximum_prepared = deepcopy(prepared)
    maximum_prepared["document"] = maximum_document
    maximum_prepared["createdIds"] = created_ids
    maximum_prepared["affectedIds"] = created_ids
    maximum_prepared["operationResults"] = operation_results
    recovery = host.service._proposal_recovery_context(
        alternative,
        maximum_prepared,
        dependencies,
    )
    commit_payload = host.service._proposal_commit_payload(
        alternative,
        maximum_prepared,
        dependencies,
    )

    assert recovery["schemaVersion"] == 2
    assert "expectedLayout" not in recovery
    assert "document" not in commit_payload["operationResult"]
    assert len(canonical_json_bytes(recovery)) < MAX_RECORD_BYTES
    assert len(canonical_json_bytes(commit_payload)) < MAX_RECORD_BYTES

    store = JsonReceiptStore(tmp_path / "bounded-receipts")
    prepared_record = PreparedRecord(
        receipt_id="flr-large-layout",
        proposal_id=proposal.proposal_id,
        action=proposal.action,
        binding=ExactBinding.from_dict(binding.to_dict()),
        principal=PrincipalBinding(
            principal_id=principal.principal_id,
            session_id="large-layout-session",
        ),
        idempotency_key="large-layout-idempotency",
        request_fingerprint="a" * 64,
        prepared_at=1000.0,
        recovery=recovery,
    )
    stored = store.prepare(prepared_record)
    receipt = TransactionReceipt(
        receipt_id=prepared_record.receipt_id,
        proposal_id=prepared_record.proposal_id,
        action=prepared_record.action,
        binding=prepared_record.binding,
        principal=prepared_record.principal,
        idempotency_key=prepared_record.idempotency_key,
        request_fingerprint=prepared_record.request_fingerprint,
        revision="b" * 64,
        created_at=1001.0,
        payload=commit_payload,
    )
    finalized = store.finalize(prepared_record, receipt)
    assert finalized.state == "finalized"
    assert (
        store.lookup(
            prepared_record.idempotency_key,
            prepared_record.request_fingerprint,
        )
        == finalized
    )
    host.close()


def test_unapproved_proposal_authority_fails_closed_after_restart(tmp_path):
    root = tmp_path / "facility"
    client, host = _client(root)
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    _, selected = _proposal(client, bootstrap)
    host.close()

    reopened, reopened_host = _client(root)
    try:
        preview = reopened.get(
            (
                f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
                f"/proposals/{selected['proposalId']}/preview"
            )
        )
        assert preview.status_code == 404
        assert preview.json()["error"]["code"] == "proposal_not_found"
        assert reopened.get(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        ).json()["revision"] == bootstrap["layout"]["revision"]
    finally:
        reopened_host.close()
