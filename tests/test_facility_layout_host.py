from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.host import (
    LOCAL_ASSET_CATALOG,
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
    build_private_local_asset_catalog,
)
from ai_inspector.facility_layout.authorization import (
    FacilityPrincipal,
    local_facility_principal,
)
from ai_inspector.facility_layout.canonical import canonical_layout_bytes
from ai_inspector.facility_layout.identity import FacilityPrincipalResolver
from ai_inspector.facility_layout.repository import _read_bytes

PILOT_MAKER_TOKEN = "host-maker-token-" + ("m" * 48)
PILOT_CHECKER_TOKEN = "host-checker-token-" + ("c" * 48)


def _pilot_resolver() -> FacilityPrincipalResolver:
    return FacilityPrincipalResolver(
        (
            (
                hashlib.sha256(
                    PILOT_MAKER_TOKEN.encode("utf-8")
                ).hexdigest(),
                FacilityPrincipal(
                    principal_id="host-maker",
                    tenant_id="local",
                    allowed_site_ids=(LOCAL_SITE_ID,),
                    roles=("layout_admin",),
                ),
            ),
            (
                hashlib.sha256(
                    PILOT_CHECKER_TOKEN.encode("utf-8")
                ).hexdigest(),
                FacilityPrincipal(
                    principal_id="host-checker",
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


def test_local_host_bootstraps_persistent_authority_and_empty_layout(tmp_path):
    client, host = _client(tmp_path / "facility")
    response = client.get("/api/facility-layout-bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["siteId"] == LOCAL_SITE_ID
    assert body["layoutId"] == LOCAL_LAYOUT_ID
    assert len(body["assetCatalog"]) == len(host._catalog)
    assert {
        "asset-cnc-mill",
        "asset-pallet-rack",
        "asset-workbench",
        "asset-forklift",
    } <= {
        item["assetId"] for item in body["assetCatalog"]
    }
    assert body["layout"]["layout"]["placements"] == []
    assert body["worldBounds"] == {
        "minX": 0,
        "minZ": 0,
        "maxX": 40,
        "maxZ": 30,
        "floorY": 0.0,
    }
    assert body["grid"] == {
        "units": "m",
        "originMode": "corner",
        "snapSpacing": 0.5,
        "minorSpacing": 1,
        "majorSpacing": 5,
    }
    first_revision = body["layout"]["revision"]

    reopened, _ = _client(tmp_path / "facility")
    repeated = reopened.get("/api/facility-layout-bootstrap")
    assert repeated.status_code == 200
    assert repeated.json()["layout"]["revision"] == first_revision


def test_g1_generation_api_builds_review_draft_then_saves_explicitly(
    tmp_path,
    monkeypatch,
):
    for name in (
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT",
        "INSPECTORPRO_SAGE_PROVIDER",
        "INSPECTORPRO_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    client, host = _client(tmp_path / "facility-generation")
    headers = {"X-InspectorPro-Session": "host-g1-session"}
    try:
        base = client.get("/api/facility-layout-bootstrap").json()["layout"]
        started = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/g1",
            headers=headers,
            json={
                "prototypeMode": True,
                "executionMode": "authorized_draft_run",
                "facilityEnvelope": {
                    "width": 100,
                    "depth": 80,
                    "sourceUnit": "m",
                    "displayName": "Generated Facility",
                },
                "departments": {
                    "count": 4,
                    "labels": [
                        "Receiving",
                        "Machining",
                        "Assembly",
                        "Inspection",
                    ],
                    "arrangement": "deterministic_grid",
                },
            },
        )
        assert started.status_code == 200, started.text
        run = started.json()
        for expected_stage in (
            "facility_envelope",
            "macro_departments",
            "primary_circulation",
            "department_subdivisions",
            "department_resources",
            "seed_cells",
            "repeated_modules",
            "floor_communication",
            "deterministic_validation",
            "review_and_save",
        ):
            continued = client.post(
                f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
                f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/continue",
                headers=headers,
                json={},
            )
            assert continued.status_code == 200, continued.text
            run = continued.json()
            assert run["completedStageId"] == expected_stage
        assert run["status"] == "complete"
        assert run["saveEligibility"] == "eligible"
        assert len(run["draftLayout"]["zones"]) == 4

        circulated = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/circulation",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "circulation": {
                    "action": "create",
                    "route_kind": "material",
                    "width": 6,
                    "source_unit": "m",
                    "source_department": "Receiving",
                    "target_department": "Inspection",
                    "via_departments": ["Machining", "Assembly"],
                    "direction": "two_way",
                    "label": "Primary material aisle",
                    "execution_mode": "authorized_draft_run",
                },
            },
        )
        assert circulated.status_code == 200, circulated.text
        run = circulated.json()
        assert run["status"] == "complete"
        assert run["saveEligibility"] == "eligible"
        assert len(run["draftLayout"]["routes"]) == 1
        route = run["draftLayout"]["routes"][0]
        assert route["corridorWidth"] == 6.0
        assert route["extensions"]["facilityAisle"]["areaAccounting"] == (
            "overlay"
        )
        obstacle_checked = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/circulation",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "circulation": {
                    "action": "avoid_obstacles",
                    "obstacle_scope": "static_geometry",
                    "minimum_clearance": None,
                    "clearance_unit": None,
                    "preserve_departments": True,
                    "preserve_route_identity": True,
                    "route_id": route["routeId"],
                    "vehicle_profile_id": None,
                    "vehicle_profile_revision": None,
                    "allow_reverse": None,
                    "execution_mode": "authorized_draft_run",
                },
            },
        )
        assert obstacle_checked.status_code == 200, obstacle_checked.text
        run = obstacle_checked.json()
        assert run["circulation"]["obstacleAvoidance"] == {
            "status": "clear",
            "routeId": route["routeId"],
            "minimumClearanceMeters": 0.0,
            "clearanceAuthority": "geometric_non_overlap_only",
            "vehicleTurningValidated": False,
            "preservedDepartments": True,
            "preservedRouteIdentity": True,
        }
        assert run["draftLayout"]["routes"][0]["routeId"] == route["routeId"]
        subdivided = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/subdivisions",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "subdivision": {
                    "parent_department": "Assembly",
                    "count": 4,
                    "labels": [
                        "Kitting",
                        "Mechanical Build",
                        "Electrical Build",
                        "Test",
                    ],
                    "proportions": None,
                    "arrangement": "deterministic_grid",
                    "orientation": "auto",
                    "rows": None,
                    "preserve_parent": True,
                    "execution_mode": "authorized_draft_run",
                },
            },
        )
        assert subdivided.status_code == 200, subdivided.text
        run = subdivided.json()
        assert run["subdivisions"]["parentDepartment"] == "Assembly"
        assert run["subdivisions"]["parentPreserved"] is True
        assert len(run["draftLayout"]["zones"]) == 8
        assert run["draftLayout"]["routes"][0]["routeId"] == route["routeId"]
        machine = host._catalog["asset-cnc-mill"]
        assets = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/assets",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "assetPlacement": {
                    "asset_id": machine["assetId"],
                    "asset_definition_revision": machine[
                        "assetDefinitionRevision"
                    ],
                    "quantity": 2,
                    "target_area": "Mechanical Build",
                    "orientation_mode": "long_side_east_west",
                    "facing_direction": None,
                    "resource_role": "production",
                    "access_requirement": "physical_only",
                    "preserve_hierarchy": True,
                    "execution_mode": "authorized_draft_run",
                },
            },
        )
        assert assets.status_code == 200, assets.text
        run = assets.json()
        assert run["assetPlacements"]["quantity"] == 2
        assert run["assetPlacements"]["accessUnverifiedCount"] == 2
        assert len(run["draftLayout"]["placements"]) == 2
        assert len(run["draftLayout"]["zones"]) == 8
        assert run["draftLayout"]["routes"][0]["routeId"] == route["routeId"]
        cells = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/cells",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "cellComposition": {
                    "target_area": "Mechanical Build",
                    "candidate_strategies": ["line"],
                    "selected_strategy": "line",
                    "objective": "shortest_travel",
                    "preferred_gap_meters": 1.0,
                    "invert_u": False,
                    "process_sequence_placement_ids": [],
                    "preserve_departments": True,
                    "preserve_routes": True,
                    "preserve_markings": True,
                    "preserve_locked_and_manual": True,
                    "execution_mode": "authorized_draft_run",
                },
            },
        )
        assert cells.status_code == 200, cells.text
        run = cells.json()
        assert run["cellComposition"]["selectedStrategy"] == "line"
        assert run["cellComposition"]["memberPlacementCount"] == 2
        assert run["cellComposition"]["preferredGapAuthority"] == (
            "user_authored"
        )
        assert run["cellComposition"]["saved"] is False
        assert len(run["draftLayout"]["placements"]) == 2
        assert len(run["draftLayout"]["zones"]) == 8
        assert run["draftLayout"]["routes"][0]["routeId"] == route["routeId"]
        replicated = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/cell-replication",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "cellReplication": {
                    "source_cell": "Mechanical Build",
                    "target_areas": ["Electrical Build"],
                    "copy_current_edited_state": False,
                    "preserve_departments": True,
                    "preserve_routes": True,
                    "preserve_markings": True,
                    "preserve_source_cell": True,
                    "preserve_manual_and_locked": True,
                    "execution_mode": "authorized_draft_run",
                },
            },
        )
        assert replicated.status_code == 200, replicated.text
        run = replicated.json()
        assert run["cellReplication"]["replicaCount"] == 1
        assert run["cellReplication"]["copiedPlacementCount"] == 2
        assert run["cellReplication"]["sourceCell"] == (
            "Mechanical Build"
        )
        assert run["cellReplication"]["targetAreas"] == [
            "Electrical Build"
        ]
        assert run["cellReplication"]["saved"] is False
        assert len(run["draftLayout"]["placements"]) == 4
        assert len(run["draftLayout"]["zones"]) == 8
        assert run["draftLayout"]["routes"][0]["routeId"] == route["routeId"]
        unchanged = client.get(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        ).json()
        assert unchanged["revision"] == base["revision"]
        assert unchanged["layout"]["zones"] == []
        assert unchanged["layout"]["routes"] == []

        saved = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/save",
            headers=headers,
            json={
                "explicitApproval": True,
                "cumulativeDiffHash": run["cumulativeProposal"][
                    "cumulativeDiffHash"
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["run"]["status"] == "saved"
        reopened = client.get(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        ).json()
        assert reopened["layout"]["displayName"] == "Generated Facility"
        assert [zone["label"] for zone in reopened["layout"]["zones"]] == [
            "Receiving",
            "Machining",
            "Assembly",
            "Inspection",
            "Kitting",
            "Mechanical Build",
            "Electrical Build",
            "Test",
        ]
        assert len(reopened["layout"]["routes"]) == 1
        assert len(reopened["layout"]["placements"]) == 4
    finally:
        client.close()
        host.close()


def test_g1_generation_explicitly_supersedes_owned_unsaved_draft_after_reload(
    tmp_path,
    monkeypatch,
):
    for name in (
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT",
        "INSPECTORPRO_SAGE_PROVIDER",
        "INSPECTORPRO_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    client, host = _client(tmp_path / "facility-generation-supersede")
    first_headers = {"X-InspectorPro-Session": "host-g1-first-browser"}
    second_headers = {"X-InspectorPro-Session": "host-g1-reloaded-browser"}

    def request_payload(*, width, depth, labels, supersede=False):
        return {
            "prototypeMode": True,
            "supersedeActiveDraft": supersede,
            "executionMode": "authorized_draft_run",
            "facilityEnvelope": {
                "width": width,
                "depth": depth,
                "sourceUnit": "m",
                "displayName": "Generated Facility",
            },
            "departments": {
                "count": len(labels),
                "labels": labels,
                "arrangement": "deterministic_grid",
            },
        }

    try:
        base = client.get("/api/facility-layout-bootstrap").json()["layout"]
        first = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/g1",
            headers=first_headers,
            json=request_payload(
                width=100,
                depth=80,
                labels=["Receiving", "Machining", "Assembly", "Inspection"],
            ),
        )
        assert first.status_code == 200, first.text
        first_run = first.json()
        for _ in range(10):
            continued = client.post(
                f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
                f"{LOCAL_LAYOUT_ID}/runs/{first_run['runId']}/continue",
                headers=first_headers,
                json={},
            )
            assert continued.status_code == 200, continued.text
            first_run = continued.json()
        assert first_run["status"] == "complete"

        blocked = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/g1",
            headers=second_headers,
            json=request_payload(
                width=120,
                depth=90,
                labels=["Receiving", "Machining", "Assembly"],
            ),
        )
        assert blocked.status_code == 409, blocked.text

        replacement = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/g1",
            headers=second_headers,
            json=request_payload(
                width=120,
                depth=90,
                labels=["Receiving", "Machining", "Assembly"],
                supersede=True,
            ),
        )
        assert replacement.status_code == 200, replacement.text
        replacement_run = replacement.json()
        assert replacement_run["runId"] != first_run["runId"]
        assert replacement_run["supersededRunId"] == first_run["runId"]
        assert len(replacement_run["supersededReceiptIds"]) == 10

        prior = client.get(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{first_run['runId']}",
            headers=first_headers,
        )
        assert prior.status_code == 200, prior.text
        assert prior.json()["status"] == "cancelled"
        unchanged = client.get(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
        ).json()
        assert unchanged["revision"] == base["revision"]
        assert unchanged["layout"] == base["layout"]
    finally:
        client.close()
        host.close()


def test_g1_generation_supersedes_owned_draft_after_base_revision_changes(
    tmp_path,
    monkeypatch,
):
    for name in (
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT",
        "INSPECTORPRO_SAGE_PROVIDER",
        "INSPECTORPRO_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    client, host = _client(tmp_path / "facility-generation-stale-base")
    first_headers = {"X-InspectorPro-Session": "host-g1-stale-first"}
    second_headers = {"X-InspectorPro-Session": "host-g1-stale-second"}
    endpoint = (
        f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
        f"{LOCAL_LAYOUT_ID}/g1"
    )

    def payload(width, depth):
        return {
            "prototypeMode": True,
            "supersedeActiveDraft": True,
            "executionMode": "authorized_draft_run",
            "facilityEnvelope": {
                "width": width,
                "depth": depth,
                "sourceUnit": "m",
                "displayName": "Generated Facility",
            },
            "departments": {
                "count": 2,
                "labels": ["Inbound", "Dispatch"],
                "arrangement": "deterministic_grid",
            },
        }

    try:
        bootstrap = client.get("/api/facility-layout-bootstrap").json()
        first = client.post(
            endpoint,
            headers=first_headers,
            json=payload(100, 80),
        )
        assert first.status_code == 200, first.text
        first_run = first.json()

        changed = client.put(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
            json={
                "baseRevision": bootstrap["layout"]["revision"],
                "operations": [
                    {
                        "op": "set_plan_settings",
                        "planSettings": {
                            "widthMeters": 60,
                            "depthMeters": 40,
                            "gridSpacingMeters": 1,
                            "majorGridSpacingMeters": 5,
                        },
                    }
                ],
            },
        )
        assert changed.status_code == 200, changed.text
        changed_revision = changed.json()["revision"]
        assert changed_revision != first_run["baseLayoutRevision"]

        replacement = client.post(
            endpoint,
            headers=second_headers,
            json=payload(150, 100),
        )
        assert replacement.status_code == 200, replacement.text
        replacement_run = replacement.json()
        assert replacement_run["baseLayoutRevision"] == changed_revision
        assert replacement_run["supersededRunId"] == first_run["runId"]

        prior = client.get(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{first_run['runId']}",
            headers=first_headers,
        )
        assert prior.status_code == 200, prior.text
        assert prior.json()["status"] == "cancelled"
    finally:
        client.close()
        host.close()


def test_local_host_upgrades_valid_noncanonical_layout_storage(tmp_path):
    root = tmp_path / "facility"
    client, host = _client(root)
    try:
        bootstrap = client.get("/api/facility-layout-bootstrap").json()
        canonical_revision = bootstrap["layout"]["revision"]
    finally:
        client.close()
        host.close()

    scope = root / "layouts" / "local" / LOCAL_SITE_ID / "layouts"
    asset = scope / f"{LOCAL_LAYOUT_ID}.json"
    registry_path = scope / "registry.json"
    noncanonical = json.loads(asset.read_text(encoding="ascii"))
    noncanonical["coordinateFrame"]["floorElevation"] = -0.0
    noncanonical_payload = json.dumps(
        noncanonical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    assert noncanonical_payload != canonical_layout_bytes(noncanonical)
    noncanonical_revision = hashlib.sha256(noncanonical_payload).hexdigest()
    registry = json.loads(registry_path.read_text(encoding="ascii"))
    registry["layouts"][0]["currentRevision"] = noncanonical_revision
    asset.write_bytes(noncanonical_payload)
    registry_path.write_bytes(
        json.dumps(
            registry,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    )

    reopened, reopened_host = _client(root)
    try:
        response = reopened.get("/api/facility-layout-bootstrap")
        assert response.status_code == 200
        receipt = response.json()["layout"]
        assert receipt["revision"] == canonical_revision
        assert asset.read_bytes() == canonical_layout_bytes(receipt["layout"])
        backup = (
            scope
            / "backups"
            / LOCAL_LAYOUT_ID
            / f"{noncanonical_revision}.json"
        )
        assert _read_bytes(backup) == noncanonical_payload
    finally:
        reopened.close()
        reopened_host.close()


def test_private_local_catalog_binds_only_available_web_glbs(tmp_path):
    expected = {
        "asset-cnc-mill": (
            "generated/industrial_assets/p0_spike/cnc_vmc/"
            "User Library-CNC Milling machine_colored.glb"
        ),
        "asset-pallet-rack": (
            "generated/industrial_assets/p0_spike/rack_prototypes/"
            "Pallet Racking_colored.glb"
        ),
        "asset-workbench": (
            "generated/industrial_assets/p0_spike/wa01_workstation/"
            "RF--WA01-W48-D36-H34-T0_375-UF-F0-P5002_colored.glb"
        ),
        "asset-forklift": (
            "generated/industrial_assets/p0_spike/toyota_forklift/"
            "User Library-Toyota Forklift_colored.glb"
        ),
    }
    for relative in expected.values():
        artifact = tmp_path / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"private-glb")
        (artifact.parent / "thumbnail.webp").write_bytes(b"thumbnail")

    catalog = build_private_local_asset_catalog(tmp_path)
    assert {item["assetId"] for item in catalog} == set(expected)
    for item in catalog:
        assert item["privateLocalVisual"] == {
            "enabled": True,
            "available": True,
        }
        assert item["overview"]["path"].startswith("/generated/")
        assert " " not in item["overview"]["path"]
        assert item["overview"]["byteSize"] == len(b"private-glb")
        assert item["thumbnail"]["path"].startswith("/generated/")
        assert item["thumbnail"]["path"].endswith("/thumbnail.webp")
        assert item["thumbnail"]["mediaType"] == "image/webp"
        matrix = item["overview"]["sourceToCanonical"]
        assert len(matrix) == 16
        assert matrix == item["definition"]["coordinateFrame"][
            "sourceToCanonical"
        ]


def test_private_local_catalog_falls_back_when_artifact_is_absent(tmp_path):
    catalog = build_private_local_asset_catalog(tmp_path)
    assert len(catalog) == 4
    assert all("overview" not in item for item in catalog)
    assert all(
        item["privateLocalVisual"]["available"] is False
        for item in catalog
    )


def test_private_local_catalog_loads_generated_manifest_assets(tmp_path):
    artifact = (
        tmp_path
        / "generated"
        / "industrial_assets"
        / "local_library"
        / "cnc-lathe"
        / "cnc-lathe_colored.glb"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"private-glb")
    (artifact.parent / "thumbnail.webp").write_bytes(b"thumbnail")
    manifest = {
        "schemaVersion": 1,
        "assets": [{
            "artifact": artifact.relative_to(tmp_path).as_posix(),
            "assetId": "asset-cnc-lathe",
            "category": "Machines",
            "description": "Private CNC turning-center model.",
            "dimensions": {
                "depth": 2.0,
                "height": 1.7,
                "width": 2.1,
            },
            "displayName": "CNC Lathe",
            "sourceToCanonical": [
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0.9, 0, -1.0, 1,
            ],
            "supportSurfaces": [{
                "surfaceId": "worktop",
                "label": "Worktop",
                "localFrame": {
                    "origin": {"x": 0, "y": 1.2, "z": 0},
                    "xAxis": {"x": 1, "y": 0, "z": 0},
                    "zAxis": {"x": 0, "y": 0, "z": 1},
                    "normal": {"x": 0, "y": 1, "z": 0},
                },
                "bounds": {
                    "minimumX": -0.8,
                    "maximumX": 0.8,
                    "minimumZ": -0.6,
                    "maximumZ": 0.6,
                },
                "allowedSides": ["above"],
                "evidenceStatus": "derived",
            }],
            "tags": ["turning", "lathe"],
        }],
    }
    manifest_path = (
        tmp_path
        / "generated"
        / "industrial_assets"
        / "local_library"
        / "catalog.json"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    catalog = build_private_local_asset_catalog(tmp_path)
    assert len(catalog) == 5
    item = next(
        entry for entry in catalog
        if entry["assetId"] == "asset-cnc-lathe"
    )
    assert item["tags"] == ["turning", "lathe"]
    assert item["definition"]["tags"] == ["turning", "lathe"]
    assert item["overview"]["path"].endswith("cnc-lathe_colored.glb")
    assert item["thumbnail"]["path"].endswith("thumbnail.webp")
    assert item["privateLocalVisual"]["available"] is True
    assert item["supportSurfaces"] == item["definition"]["supportSurfaces"]
    assert item["supportSurfaces"][0]["surfaceId"] == "worktop"
    assert item["supportSurfaces"][0]["bounds"]["maximumX"] == 0.8


def test_private_local_catalog_rejects_unsafe_manifest_artifact(tmp_path):
    manifest_path = (
        tmp_path
        / "generated"
        / "industrial_assets"
        / "local_library"
        / "catalog.json"
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({
        "schemaVersion": 1,
        "assets": [{
            "artifact": "../protected/model.glb",
            "assetId": "asset-unsafe",
            "category": "Machines",
            "description": "Unsafe fixture.",
            "dimensions": {"depth": 1, "height": 1, "width": 1},
            "displayName": "Unsafe",
            "sourceToCanonical": [
                1, 0, 0, 0,
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            ],
            "tags": [],
        }],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact is invalid"):
        build_private_local_asset_catalog(tmp_path)


def test_private_catalog_preserves_resolvable_legacy_asset_revisions(tmp_path):
    host = LocalFacilityLayoutHost(
        tmp_path / "facility",
        private_assets=True,
        private_asset_root=tmp_path,
    )
    try:
        legacy = LOCAL_ASSET_CATALOG[0]
        current = host._catalog[legacy["assetId"]]
        assert current["assetDefinitionRevision"] != legacy[
            "assetDefinitionRevision"
        ]
        resolved_legacy = host._resolve_asset_definition(
            host.principal(),
            LOCAL_SITE_ID,
            legacy["assetId"],
            legacy["assetDefinitionRevision"],
        )
        resolved_current = host._resolve_asset_definition(
            host.principal(),
            LOCAL_SITE_ID,
            current["assetId"],
            current["assetDefinitionRevision"],
        )
        assert resolved_legacy["revision"] == legacy[
            "assetDefinitionRevision"
        ]
        assert resolved_current["revision"] == current[
            "assetDefinitionRevision"
        ]
    finally:
        host.close()


def test_bootstrap_reports_optional_maker_checker_policy(tmp_path):
    default_client, default_host = _client(
        tmp_path / "default-facility"
    )
    try:
        default = default_client.get(
            "/api/facility-layout-bootstrap"
        ).json()
        assert default["capabilities"]["makerCheckerRequired"] is False
        assert default["capabilities"]["manualPlacementApproval"] is False
    finally:
        default_client.close()
        default_host.close()

    root = tmp_path / "pilot-facility"
    pilot_host = LocalFacilityLayoutHost(
        root,
        require_distinct_approver=True,
        principal_resolver=_pilot_resolver(),
    )
    pilot_app = FastAPI()
    pilot_app.include_router(pilot_host.create_router())
    pilot_client = TestClient(pilot_app)
    try:
        pilot = pilot_client.get(
            "/api/facility-layout-bootstrap",
            headers={
                "Authorization": f"Bearer {PILOT_MAKER_TOKEN}",
            },
        ).json()
        assert pilot["capabilities"]["makerCheckerRequired"] is True
        assert (
            pilot_host.transaction_runtime.require_distinct_approver
            is True
        )
    finally:
        pilot_client.close()
        pilot_host.close()


def test_local_host_uses_revision_bound_preview_and_apply(tmp_path):
    client, _ = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    asset = bootstrap["assetCatalog"][0]
    revision = bootstrap["layout"]["revision"]
    operation = {
        "op": "place_asset",
        "placement": {
            "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {
                "position": {"x": 5, "y": 0, "z": 4},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {},
        },
    }
    preview = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/preview",
        json={"baseRevision": revision, "operations": [operation]},
    )
    assert preview.status_code == 200
    assert preview.json()["baseRevision"] == revision
    assert preview.json()["changed"] is True

    before = client.get(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}"
    ).json()
    assert before["layout"]["placements"] == []

    applied = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        json={"baseRevision": revision, "operations": [operation]},
    )
    assert applied.status_code == 200
    assert len(applied.json()["layout"]["placements"]) == 1
    assert applied.json()["revision"] != revision


def test_bootstrap_uses_persisted_plan_dimensions_and_grid(tmp_path):
    client, host = _client(tmp_path / "facility")
    try:
        bootstrap = client.get("/api/facility-layout-bootstrap").json()
        operation = {
            "op": "set_plan_settings",
            "planSettings": {
                "widthMeters": 55,
                "depthMeters": 36,
                "gridSpacingMeters": 2,
                "majorGridSpacingMeters": 10,
            },
        }
        applied = client.put(
            f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
            json={
                "baseRevision": bootstrap["layout"]["revision"],
                "operations": [operation],
            },
        )
        assert applied.status_code == 200

        refreshed = client.get("/api/facility-layout-bootstrap").json()
        assert refreshed["worldBounds"] == {
            "minX": 0.0,
            "minZ": 0.0,
            "maxX": 55.0,
            "maxZ": 36.0,
            "floorY": 0.0,
        }
        assert refreshed["grid"] == {
            "units": "m",
            "originMode": "corner",
            "snapSpacing": 2.0,
            "minorSpacing": 2.0,
            "majorSpacing": 10.0,
        }
        assert refreshed["layout"]["layout"]["extensions"][
            "facilityPlan"
        ] == operation["planSettings"]
    finally:
        client.close()
        host.close()


def test_local_host_rejects_unknown_asset_and_cross_site_scope(tmp_path):
    client, _ = _client(tmp_path / "facility")
    bootstrap = client.get("/api/facility-layout-bootstrap").json()
    operation = {
        "op": "place_asset",
        "placement": {
            "assetId": "asset-unknown",
            "assetDefinitionRevision": "f" * 64,
            "transform": {
                "position": {"x": 1, "y": 0, "z": 1},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {},
        },
    }
    rejected = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/preview",
        json={
            "baseRevision": bootstrap["layout"]["revision"],
            "operations": [operation],
        },
    )
    assert rejected.status_code == 404
    hidden = client.get("/api/facility-layouts/site-other")
    assert hidden.status_code == 404
    hidden_assets = client.get(
        "/api/industrial-assets",
        params={"siteId": "site-other"},
    )
    assert hidden_assets.status_code == 404


def test_local_host_resolves_revision_bound_named_process_maps(tmp_path):
    from ai_inspector.process_map.repository import load_process_map

    process_root = tmp_path / "training"
    product_dir = process_root / "fixture-product"
    product_dir.mkdir(parents=True)
    legacy_asset = product_dir / "fixture_process_map_working_draft.json"
    legacy_asset.write_text(
        json.dumps(
            {
                "schemaVersion": "fixture-process-map-1",
                "productId": "fixture-product",
                "productName": "Fixture Product",
                "nodes": [
                    {
                        "nodeId": "root",
                        "level": 0,
                        "name": "Fixture Product",
                        "parentNodeId": None,
                        "partIds": [],
                    },
                    {
                        "nodeId": "part",
                        "level": 1,
                        "name": "Fixture Part",
                        "parentNodeId": "root",
                        "partIds": ["P-001"],
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    host = LocalFacilityLayoutHost(
        tmp_path / "facility",
        process_map_root=process_root,
    )
    try:
        current = load_process_map(process_root, "fixture-product")
        missing = host._resolve_process_map(
            host.principal(),
            LOCAL_SITE_ID,
            "fixture-product",
            "default",
            "0" * 64,
        )
        resolved = host._resolve_process_map(
            host.principal(),
            LOCAL_SITE_ID,
            "fixture-product",
            "default",
            current["revision"],
        )
    finally:
        host.close()
    assert missing is None
    assert resolved is not None
    assert resolved["revision"] == current["revision"]
    assert resolved["document"]["mapId"] == "default"
    assert resolved["document"]["association"]["productId"] == "fixture-product"
