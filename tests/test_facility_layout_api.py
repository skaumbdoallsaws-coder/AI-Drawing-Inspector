import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.api import create_facility_layout_router
from ai_inspector.facility_layout.authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
)
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.repository import FacilityLayoutRepository
from ai_inspector.facility_layout.service import (
    FacilityLayoutService,
    coordinate_frame_fingerprint,
)


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"
NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def _resolved_asset(asset_id, revision):
    return {
        "revision": revision,
        "definition": {
            "assetId": asset_id,
            "assetDefinitionRevision": revision,
            "category": "operators" if asset_id == "asset-operator" else "machine",
            "geometry": {
                "footprintPolygons": [[
                    {"x": -0.5, "z": -0.5},
                    {"x": 0.5, "z": -0.5},
                    {"x": 0.5, "z": 0.5},
                    {"x": -0.5, "z": 0.5},
                ]],
                "heightInterval": {"minimumY": 0, "maximumY": 1},
            },
            "clearances": [],
        },
    }


def _principal(role="admin"):
    return FacilityPrincipal(
        principal_id=f"principal-{role}",
        tenant_id="tenant-a",
        allowed_site_ids=("site-a",),
        roles=(role,),
    )


def _authority_documents():
    values = json.loads(
        (FIXTURES / "p0_authority_documents.json").read_text(encoding="ascii")
    )
    return {
        value["documentKind"]: deepcopy(value)
        for value in values
        if value["documentKind"]
        in {"facility_shell", "policy_set", "vehicle_profile"}
    }


def _publish(repository, document, id_field):
    principal = _principal()
    candidate = deepcopy(document)
    candidate["status"] = "draft"
    created = repository.create(
        principal,
        site_id="site-a",
        document=candidate,
    )
    reviewed = repository.review(
        principal,
        site_id="site-a",
        authority_id=candidate[id_field],
        expected_revision=created.envelope.revision,
    )
    return repository.publish(
        principal,
        site_id="site-a",
        authority_id=candidate[id_field],
        expected_revision=reviewed.envelope.revision,
    ).envelope


def _client(tmp_path):
    documents = _authority_documents()
    clock = lambda: NOW
    shell_repository = FacilityShellRepository(
        tmp_path / "authority" / "shells",
        clock=clock,
    )
    policy_repository = PolicySetRepository(
        tmp_path / "authority" / "policies",
        clock=clock,
    )
    vehicle_repository = VehicleProfileRepository(
        tmp_path / "authority" / "vehicles",
        clock=clock,
    )
    shell = _publish(
        shell_repository,
        documents["facility_shell"],
        "shellId",
    )
    policy = _publish(
        policy_repository,
        documents["policy_set"],
        "policySetId",
    )
    _publish(
        vehicle_repository,
        documents["vehicle_profile"],
        "vehicleProfileId",
    )
    service = FacilityLayoutService(
        layout_repository=FacilityLayoutRepository(
            tmp_path / "layouts",
            clock=clock,
        ),
        shell_repository=shell_repository,
        policy_repository=policy_repository,
        vehicle_repository=vehicle_repository,
        asset_definition_resolver=(
            lambda _principal, _site, asset_id, revision: _resolved_asset(
                asset_id,
                revision,
            )
        ),
    )

    def resolve_principal(request: Request):
        return _principal(request.headers.get("X-Test-Role", "admin"))

    app = FastAPI()
    app.include_router(
        create_facility_layout_router(
            service=service,
            principal_resolver=resolve_principal,
        )
    )
    return TestClient(app), service, shell, policy


def _layout(shell, policy):
    frame = deepcopy(shell.document["coordinateFrame"])
    return create_layout_document(
        layout_id="fl-api-cell",
        display_name="API Cell",
        association={"siteId": "site-a", "areaId": "cell-api"},
        coordinate_frame=frame,
        source_shell_ref={
            "shellId": shell.document["shellId"],
            "shellRevision": shell.revision,
            "coordinateFrameFingerprint": coordinate_frame_fingerprint(frame),
        },
        policy_set_ref={
            "policySetId": policy.document["policySetId"],
            "policySetRevision": policy.revision,
        },
        created_at="browser-time",
    )


def _placement_operation():
    fixture = json.loads(
        (FIXTURES / "two_asset_cell.json").read_text(encoding="ascii")
    )
    return {
        "op": "place_asset",
        "placement": deepcopy(fixture["placements"][0]),
    }


def _generated_placement_operation():
    operation = _placement_operation()
    operation["placement"].pop("placementId", None)
    return operation


def _file_snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_layout_http_round_trip_and_operation_batch(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={
            "tenantId": "tenant-forged",
            "makeDefault": True,
            "layout": _layout(shell, policy),
        },
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["layout"]["association"]["siteId"] == "site-a"
    assert created_body["isDefault"] is True

    updated = client.put(
        "/api/facility-layouts/site-a/fl-api-cell",
        json={
            "baseRevision": created_body["revision"],
            "operations": [_placement_operation()],
        },
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert len(updated_body["layout"]["placements"]) == 1
    assert updated_body["operationResult"]["changed"] is True

    reopened = client.get(
        "/api/facility-layouts/site-a/fl-api-cell"
    )
    assert reopened.status_code == 200
    assert reopened.json()["revision"] == updated_body["revision"]
    validated = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/validate",
        json={},
    )
    assert validated.status_code == 200
    assert validated.json()["valid"] is True


def test_routing_http_surface_is_revision_bound_and_read_only(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={"layout": _layout(shell, policy)},
    ).json()
    before = _file_snapshot(tmp_path)

    diagnosed = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/routing/diagnostics",
        json={
            "baseRevision": created["revision"],
            "operations": [],
        },
    )
    assert diagnosed.status_code == 200
    assert diagnosed.json()["valid"] is True
    assert diagnosed.json()["metrics"]["routeCount"] == 0

    unresolved = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/routing/connectors",
        json={
            "baseRevision": created["revision"],
            "request": {
                "routeKind": "material",
                "sourceEndpoint": {
                    "kind": "zone_anchor",
                    "zoneId": "zn-missing",
                    "anchorId": "za-missing",
                },
            },
        },
    )
    assert unresolved.status_code == 200
    assert unresolved.json()["candidates"] == []
    assert unresolved.json()["findings"][0]["code"] == "dangling_zone_anchor"
    assert _file_snapshot(tmp_path) == before

    stale = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/routing/diagnostics",
        json={"baseRevision": "f" * 64, "operations": []},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"


def test_manual_navigation_validation_http_surface_uses_unsaved_draft(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={"layout": _layout(shell, policy)},
    ).json()
    operation = _placement_operation()
    operation["placement"].update({
        "placementId": "pl-api-operator",
        "assetId": "asset-operator",
    })
    operation["placement"]["transform"]["position"].update({
        "x": 2.0,
        "z": 2.0,
    })
    revision = operation["placement"]["assetDefinitionRevision"]
    before = _file_snapshot(tmp_path)

    validated = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/"
        "navigation/manual-path/validate",
        json={
            "baseRevision": created["revision"],
            "operations": [operation],
            "request": {
                "actorPlacementId": "pl-api-operator",
                "actorClass": "pedestrian",
                "actorProfileRef": {
                    "profileKind": "pedestrian",
                    "profileId": "pedestrian-profile:asset-operator",
                    "profileRevision": revision,
                },
                "constraintMode": "complete_override",
                "direction": "forward",
                "points": [{"x": 2, "z": 2}, {"x": 12, "z": 2}],
            },
        },
    )
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert validated.json()["mutated"] is False
    assert _file_snapshot(tmp_path) == before

    stale = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/"
        "navigation/manual-path/validate",
        json={
            "baseRevision": "f" * 64,
            "operations": [],
            "request": {},
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"


def test_http_operation_preview_is_read_only_and_matches_put(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={"layout": _layout(shell, policy)},
    ).json()
    operations = [_generated_placement_operation()]
    before = _file_snapshot(tmp_path)

    preview_response = client.post(
        "/api/facility-layouts/site-a/fl-api-cell/preview",
        json={
            "baseRevision": created["revision"],
            "operations": operations,
        },
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert _file_snapshot(tmp_path) == before
    assert preview["baseRevision"] == created["revision"]
    assert preview["createdIds"][0].startswith("pl-")
    assert preview["document"]["placements"][0]["placementId"] == (
        preview["createdIds"][0]
    )

    applied = client.put(
        "/api/facility-layouts/site-a/fl-api-cell",
        json={
            "baseRevision": created["revision"],
            "operations": operations,
        },
    )

    assert applied.status_code == 200
    applied_body = applied.json()
    assert applied_body["operationResult"] == {
        key: value
        for key, value in preview.items()
        if key not in {"baseRevision", "dependencies"}
    }
    assert applied_body["dependencies"] == preview["dependencies"]


def test_http_operation_preview_errors_are_structured_and_fail_closed(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={"layout": _layout(shell, policy)},
    ).json()
    endpoint = "/api/facility-layouts/site-a/fl-api-cell/preview"
    before = _file_snapshot(tmp_path)

    stale = client.post(
        endpoint,
        json={
            "baseRevision": "f" * 64,
            "operations": [_generated_placement_operation()],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == {
        "code": "revision_conflict",
        "message": "Facility Layout revision conflict.",
        "details": {"currentRevision": created["revision"]},
    }

    for body in (
        {"baseRevision": created["revision"]},
        {"baseRevision": created["revision"], "operations": {}},
    ):
        malformed = client.post(endpoint, json=body)
        assert malformed.status_code == 422
        assert malformed.json()["error"]["code"] == "invalid_request_body"

    malformed_operation = client.post(
        endpoint,
        json={
            "baseRevision": created["revision"],
            "operations": ["not-an-operation"],
        },
    )
    assert malformed_operation.status_code == 422
    assert malformed_operation.json()["error"]["code"] == (
        "operation_not_object"
    )

    viewer = client.post(
        endpoint,
        headers={"X-Test-Role": "viewer"},
        json={
            "baseRevision": created["revision"],
            "operations": [_generated_placement_operation()],
        },
    )
    assert viewer.status_code == 403
    assert viewer.json()["error"]["code"] == "role_not_authorized"

    cross_site = client.post(
        "/api/facility-layouts/site-b/fl-api-cell/preview",
        json={
            "baseRevision": created["revision"],
            "operations": [_generated_placement_operation()],
        },
    )
    assert cross_site.status_code == 404
    assert cross_site.json()["error"]["code"] == "not_found"
    assert _file_snapshot(tmp_path) == before


def test_stale_http_save_returns_current_revision(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={"layout": _layout(shell, policy)},
    ).json()

    stale = client.put(
        "/api/facility-layouts/site-a/fl-api-cell",
        json={
            "baseRevision": "f" * 64,
            "operations": [_placement_operation()],
        },
    )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert (
        stale.json()["error"]["details"]["currentRevision"]
        == created["revision"]
    )


def test_cross_site_and_viewer_writes_fail_closed(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    cross_site = client.post(
        "/api/facility-layouts/site-b",
        json={"layout": _layout(shell, policy)},
    )
    assert cross_site.status_code == 404
    assert cross_site.json()["error"]["code"] == "not_found"

    viewer = client.post(
        "/api/facility-layouts/site-a",
        headers={"X-Test-Role": "viewer"},
        json={"layout": _layout(shell, policy)},
    )
    assert viewer.status_code == 403
    assert viewer.json()["error"]["code"] == "role_not_authorized"


def test_invalid_request_identity_is_rejected(tmp_path):
    client, _, shell, policy = _client(tmp_path)
    created = client.post(
        "/api/facility-layouts/site-a",
        json={"layout": _layout(shell, policy)},
    ).json()
    replacement = deepcopy(created["layout"])
    replacement["layoutId"] = "fl-other"

    response = client.put(
        "/api/facility-layouts/site-a/fl-api-cell",
        json={
            "baseRevision": created["revision"],
            "layout": replacement,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_identity_mismatch"


def test_top_level_array_body_uses_domain_error_envelope(tmp_path):
    client, _, _, _ = _client(tmp_path)

    response = client.post(
        "/api/facility-layouts/site-a",
        json=["not", "an", "object"],
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request_body",
            "message": "Request body must be a JSON object.",
        }
    }


def test_authority_http_lifecycle_and_revision_read(tmp_path):
    client, _, _, _ = _client(tmp_path)
    shell = _authority_documents()["facility_shell"]
    shell["shellId"] = "shell-api-second"
    shell["status"] = "draft"

    created = client.post(
        "/api/facility-shells/site-a",
        json={"tenantId": "tenant-forged", "document": shell},
    )
    assert created.status_code == 200
    revision = created.json()["revision"]
    reviewed = client.post(
        "/api/facility-shells/site-a/shell-api-second/review",
        json={"baseRevision": revision},
    )
    assert reviewed.status_code == 200
    published = client.post(
        "/api/facility-shells/site-a/shell-api-second/publish",
        json={"baseRevision": reviewed.json()["revision"]},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    historical = client.get(
        f"/api/facility-shells/site-a/shell-api-second/revisions/{revision}"
    )
    assert historical.status_code == 200
    assert historical.json()["status"] == "draft"
