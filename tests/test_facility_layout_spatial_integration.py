from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_inspector.facility_layout.errors import (
    FacilityConflictError,
    FacilityValidationError,
)
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.spatial_executor import (
    FacilitySpatialExecutor,
    SpatialExecutionCancelled,
)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _request(asset: dict, *, x: float = 5, z: float = 5) -> dict:
    return {
        "assetId": asset["assetId"],
        "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "requestedPosition": {"x": x, "y": 0, "z": z},
    }


def _host(tmp_path: Path):
    host = LocalFacilityLayoutHost(tmp_path / "facility")
    bootstrap = host.ensure_bootstrap()
    return host, bootstrap


def test_candidate_generation_preview_and_apply_are_exact_and_revision_bound(
    tmp_path,
):
    host, bootstrap = _host(tmp_path)
    principal = host.principal()
    revision = bootstrap["layout"]["revision"]
    asset = bootstrap["assetCatalog"][1]
    request = _request(asset)
    before = _snapshot(host.root)

    candidates = host.service.generate_spatial_candidates(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
    )
    repeated = host.service.generate_spatial_candidates(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
    )

    assert candidates == repeated
    assert candidates["candidates"]
    assert _snapshot(host.root) == before
    selected = candidates["candidates"][0]
    preview = host.service.preview_spatial_candidate(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
        selected["candidateId"],
    )
    assert _snapshot(host.root) == before
    assert preview["candidate"] == selected
    assert preview["preview"]["spatialDiagnostics"]["valid"] is True
    operation = preview["operation"]
    binding = operation["placement"]["snapRelationship"]["spatialCandidate"]
    assert binding["candidateId"] == selected["candidateId"]
    assert binding["layoutFingerprint"] == selected["layoutFingerprint"]

    applied = host.service.apply_operations(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        [operation],
    )

    assert applied["changed"] is True
    assert applied["spatialDiagnostics"]["valid"] is True
    applied_layout = deepcopy(applied["layout"])
    preview_layout = deepcopy(preview["preview"]["document"])
    applied_layout.pop("updatedAt")
    preview_layout.pop("updatedAt")
    assert applied_layout == preview_layout
    assert applied["operationResult"]["diffHash"] == preview["preview"]["diffHash"]
    assert len(applied["layout"]["placements"]) == 1


def test_candidate_dismiss_is_byte_identical_and_tampering_fails_closed(tmp_path):
    host, bootstrap = _host(tmp_path)
    principal = host.principal()
    revision = bootstrap["layout"]["revision"]
    request = _request(bootstrap["assetCatalog"][0])
    candidates = host.service.generate_spatial_candidates(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
    )
    before = _snapshot(host.root)

    # Dismissal is intentionally no mutation call.
    assert _snapshot(host.root) == before

    preview = host.service.preview_spatial_candidate(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
        candidates["candidates"][0]["candidateId"],
    )
    tampered = deepcopy(preview["operation"])
    tampered["placement"]["transform"]["position"]["x"] += 0.25

    with pytest.raises(FacilityConflictError) as raised:
        host.service.apply_operations(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
            revision,
            [tampered],
        )

    assert raised.value.code == "spatial_candidate_stale"
    assert _snapshot(host.root) == before


def test_pre_p6_hard_finding_does_not_deadlock_unrelated_candidate_apply(
    tmp_path,
):
    host, bootstrap = _host(tmp_path)
    principal = host.principal()
    base_revision = bootstrap["layout"]["revision"]
    legacy = deepcopy(bootstrap["layout"]["layout"])
    asset = bootstrap["assetCatalog"][0]
    legacy["placements"].append(
        {
            "placementId": "pl-legacy-origin",
            "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {
                "position": {"x": 0, "y": 0, "z": 0},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                "scale": 1,
            },
            "positionMode": "manual",
            "snapRelationship": None,
            "metadata": {"authoredBeforeSpatialValidation": True},
        }
    )
    stored = host.layout_repository.save_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        legacy,
        base_revision,
    )
    request = _request(bootstrap["assetCatalog"][2], x=8, z=8)

    candidates = host.service.generate_spatial_candidates(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        stored["revision"],
        request,
    )
    assert candidates["candidates"]
    assert {
        item["code"]
        for item in candidates["spatialDiagnostics"]["findings"]
        if item["severity"] == "error"
    } == {"placement_outside_floor"}

    preview = host.service.preview_spatial_candidate(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        stored["revision"],
        request,
        candidates["candidates"][0]["candidateId"],
    )
    applied = host.service.apply_operations(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        stored["revision"],
        [preview["operation"]],
    )

    assert len(applied["layout"]["placements"]) == 2
    errors = [
        item
        for item in applied["spatialDiagnostics"]["findings"]
        if item["severity"] == "error"
    ]
    assert [item["code"] for item in errors] == ["placement_outside_floor"]
    assert errors[0]["subjectRefs"] == ["pl-legacy-origin"]


def test_direct_collision_and_zone_escape_are_rejected_before_draft(tmp_path):
    host, bootstrap = _host(tmp_path)
    principal = host.principal()
    revision = bootstrap["layout"]["revision"]
    asset = bootstrap["assetCatalog"][2]
    request = _request(asset, x=10, z=10)
    candidates = host.service.generate_spatial_candidates(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
    )
    first = host.service.preview_spatial_candidate(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        request,
        candidates["candidates"][0]["candidateId"],
    )
    applied = host.service.apply_operations(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        revision,
        [first["operation"]],
    )
    current_revision = applied["revision"]
    duplicate = deepcopy(first["operation"]["placement"])
    duplicate["placementId"] = "pl-overlapping-copy"
    duplicate["snapRelationship"] = None
    before = _snapshot(host.root)

    with pytest.raises(FacilityValidationError) as collision:
        host.service.preview_operations(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
            current_revision,
            [{"op": "place_asset", "placement": duplicate}],
        )
    assert collision.value.code == "spatial_validation_failed"
    assert {
        item["code"] for item in collision.value.details["findings"]
    } == {"placement_collision"}
    assert _snapshot(host.root) == before

    zone = {
        "zoneType": "workcell",
        "label": "Bounded workcell",
        "boundary": [
            {"x": 0, "z": 0},
            {"x": 4, "z": 0},
            {"x": 4, "z": 4},
            {"x": 0, "z": 4},
        ],
        "floorElevation": 0,
        "anchors": [],
        "evidence": [],
    }
    zone_preview = host.service.preview_operations(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        current_revision,
        [{"op": "add_zone", "zone": zone}],
    )
    assert any(
        item["code"] == "zone_containment_violation"
        for item in zone_preview["spatialDiagnostics"]["findings"]
    )
    assert _snapshot(host.root) == before

    # Existing equipment is grandfathered so a zone can be authored
    # incrementally. Equipment introduced by the same draft still has to be
    # contained by that zone.
    with pytest.raises(FacilityValidationError) as outside:
        host.service.preview_operations(
            principal,
            LOCAL_SITE_ID,
            LOCAL_LAYOUT_ID,
            current_revision,
            [
                {"op": "add_zone", "zone": zone},
                {
                    "op": "duplicate_placement",
                    "sourcePlacementId": first["operation"]["placement"][
                        "placementId"
                    ],
                    "position": {"x": 20, "y": 0, "z": 20},
                    "positionMode": "manual",
                },
            ],
        )
    assert outside.value.code == "spatial_validation_failed"
    assert any(
        item["code"] == "zone_containment_violation"
        for item in outside.value.details["findings"]
    )


def test_spatial_http_contract_rejects_screen_coordinates_and_stale_revision(
    tmp_path,
):
    host, bootstrap = _host(tmp_path)
    app = FastAPI()
    app.include_router(host.create_router())
    client = TestClient(app)
    revision = bootstrap["layout"]["revision"]
    asset = bootstrap["assetCatalog"][3]
    base = f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/spatial"

    diagnostics = client.post(
        base + "/diagnostics",
        json={"baseRevision": revision, "operations": []},
    )
    assert diagnostics.status_code == 200
    assert diagnostics.json()["spatialEngineVersion"] == 1
    assert diagnostics.json()["safetyStatus"] == "unverified"
    assert diagnostics.json()["safe"] is False

    forbidden = client.post(
        base + "/candidates",
        json={
            "baseRevision": revision,
            "operations": [],
            "request": {**_request(asset), "clientX": 800},
        },
    )
    assert forbidden.status_code == 422
    assert forbidden.json()["error"]["code"] == "screen_coordinates_forbidden"

    candidates = client.post(
        base + "/candidates",
        json={
            "baseRevision": revision,
            "operations": [],
            "request": _request(asset),
        },
    )
    assert candidates.status_code == 200
    repeated = client.post(
        base + "/candidates",
        json={
            "baseRevision": revision,
            "operations": [],
            "request": _request(asset),
        },
    )
    assert repeated.status_code == 200
    assert [
        item["candidateId"] for item in repeated.json()["candidates"]
    ] == [
        item["candidateId"] for item in candidates.json()["candidates"]
    ]
    candidate = candidates.json()["candidates"][0]
    preview = client.post(
        base + "/candidates/preview",
        json={
            "baseRevision": revision,
            "operations": [],
            "request": _request(asset),
            "candidateId": candidate["candidateId"],
        },
    )
    assert preview.status_code == 200
    assert preview.json()["candidate"]["candidateId"] == candidate["candidateId"]
    assert preview.json()["preview"]["spatialDiagnostics"]["valid"] is True
    operation = preview.json()["operation"]
    assert operation["op"] == "place_asset"
    binding = operation["placement"]["snapRelationship"]["spatialCandidate"]
    assert binding["candidateId"] == candidate["candidateId"]
    assert binding["layoutFingerprint"] == candidate["layoutFingerprint"]
    assert binding["obstacleFingerprint"] == candidate["obstacleFingerprint"]

    ordinary_preview = client.post(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/preview",
        json={
            "baseRevision": revision,
            "operations": [operation],
        },
    )
    assert ordinary_preview.status_code == 200
    assert (
        ordinary_preview.json()["diffHash"]
        == preview.json()["preview"]["diffHash"]
    )

    applied = client.put(
        f"/api/facility-layouts/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}",
        json={
            "baseRevision": revision,
            "operations": [operation],
        },
    )
    assert applied.status_code == 200
    applied_layout = deepcopy(applied.json()["layout"])
    preview_layout = deepcopy(preview.json()["preview"]["document"])
    applied_layout.pop("updatedAt")
    preview_layout.pop("updatedAt")
    assert applied_layout == preview_layout
    assert (
        applied.json()["operationResult"]["diffHash"]
        == preview.json()["preview"]["diffHash"]
    )

    stale = client.post(
        base + "/candidates",
        json={
            "baseRevision": "f" * 64,
            "operations": [],
            "request": _request(asset),
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"


def _review_zone(zone_id, *, side=4):
    return {"zoneId": zone_id, "zoneType": "workcell", "label": "Containment review",
        "boundary": [{"x": 0, "z": 0}, {"x": side, "z": 0},
            {"x": side, "z": side}, {"x": 0, "z": side}],
        "floorElevation": 0, "anchors": [], "evidence": []}


@pytest.mark.parametrize("zoned", [False, True])
@pytest.mark.parametrize("route", ["manual-preview", "manual-apply", "exact-proposal"])
def test_add_zone_cannot_grandfather_a_placement_moved_in_same_batch(tmp_path, zoned, route):
    from ai_inspector.facility_layout.operation_proposals import create

    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        bootstrap = host.ensure_bootstrap()
        principal = host.principal()
        asset = bootstrap["assetCatalog"][2]
        placement = {"placementId": "pl-zone-batch", "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": 10, "y": 0, "z": 10},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
            "positionMode": "manual", "snapRelationship": None, "metadata": {}}
        seed = [{"op": "place_asset", "placement": placement}]
        if zoned:
            seed.insert(0, {"op": "add_zone", "zone": _review_zone("zn-existing", side=14)})
        saved = host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
            bootstrap["layout"]["revision"], seed)
        operations = [{"op": "add_zone", "zone": _review_zone("zn-new")},
            {"op": "move_placement", "placementId": placement["placementId"],
                "position": {"x": 20, "y": 0, "z": 20}}]
        before = _snapshot(host.root)
        with pytest.raises(FacilityValidationError) as raised:
            if route == "exact-proposal":
                create(host.service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
                    operations=operations)
            else:
                operation = (host.service.preview_operations if route == "manual-preview"
                    else host.service.apply_operations)
                operation(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], operations)
        assert raised.value.code == "spatial_validation_failed"
        assert any(item["code"] == "zone_containment_violation" and
            item["subjectRefs"] == [placement["placementId"]] for item in raised.value.details["findings"])
        assert _snapshot(host.root) == before
    finally:
        host.close()


def test_add_zone_cannot_exempt_containment_after_shrinking_an_existing_zone(tmp_path):
    from ai_inspector.facility_layout.operation_proposals import create

    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    try:
        bootstrap = host.ensure_bootstrap()
        principal = host.principal()
        asset = bootstrap["assetCatalog"][2]
        placement = {"placementId": "pl-unchanged-zone-batch", "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": 10, "y": 0, "z": 10},
                "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
            "positionMode": "manual", "snapRelationship": None, "metadata": {}}
        saved = host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
            bootstrap["layout"]["revision"], [
                {"op": "add_zone", "zone": _review_zone("zn-existing", side=14)},
                {"op": "place_asset", "placement": placement}])
        before = _snapshot(host.root)
        with pytest.raises(FacilityValidationError) as raised:
            create(host.service, principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], operations=[
                {"op": "add_zone", "zone": _review_zone("zn-new", side=3)},
                {"op": "edit_zone", "zoneId": "zn-existing",
                    "patch": {"boundary": _review_zone("zn-existing")["boundary"]}}])
        assert raised.value.code == "spatial_validation_failed"
        assert any(item["code"] == "zone_containment_violation" for item in raised.value.details["findings"])
        assert _snapshot(host.root) == before
    finally:
        host.close()


def test_spatial_executor_cooperatively_cancels_bounded_job():
    def slow_generate(*_args, cancel_check, **_kwargs):
        while True:
            cancel_check()
            time.sleep(0.001)

    executor = FacilitySpatialExecutor(generate=slow_generate)
    try:
        job = executor.submit_candidates(
            {},
            {},
            {"x": 0, "z": 0},
            {},
        )
        time.sleep(0.01)
        job.cancel()
        with pytest.raises(SpatialExecutionCancelled):
            job.result(timeout=1)
    finally:
        executor.close()


def test_spatial_executor_rejects_work_beyond_the_bounded_capacity():
    started = Event()
    release = Event()

    def blocked_diagnose(*_args, cancel_check, **_kwargs):
        started.set()
        while not release.wait(0.001):
            cancel_check()
        return {"valid": True}

    executor = FacilitySpatialExecutor(
        maximum_workers=1,
        maximum_pending_jobs=1,
        diagnose=blocked_diagnose,
    )
    try:
        job = executor.submit_diagnostics({}, {})
        assert started.wait(1)
        with pytest.raises(FacilityValidationError) as raised:
            executor.submit_diagnostics({}, {})
        assert raised.value.code == "spatial_execution_overloaded"
        release.set()
        assert job.result(timeout=1) == {"valid": True}
    finally:
        release.set()
        executor.close()


def test_spatial_executor_timeout_is_typed_and_cancels_the_job():
    def blocked_diagnose(*_args, cancel_check, **_kwargs):
        while True:
            cancel_check()
            time.sleep(0.001)

    executor = FacilitySpatialExecutor(
        maximum_workers=1,
        maximum_pending_jobs=1,
        timeout_seconds=0.01,
        diagnose=blocked_diagnose,
    )
    try:
        with pytest.raises(FacilityValidationError) as raised:
            executor.run_diagnostics({}, {})
        assert raised.value.code == "spatial_execution_timeout"
    finally:
        executor.close()
