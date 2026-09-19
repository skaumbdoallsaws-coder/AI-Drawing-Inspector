from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.planning_generation import (
    FACILITY_PLANNING_PROTOTYPE_TOOL,
    FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
    MMLE_FACILITY_PLANNING_PACKAGE_ID,
    FacilityPlanningGenerationError,
    canonicalize_facility_planning_generation_request,
    canonicalize_facility_program_resource_amendment_request,
    facility_program_resource_amendment_tool_spec,
    facility_planning_prototype_tool_spec,
    is_facility_planning_prototype_request,
    is_facility_program_resource_amendment_request,
)


ROOT = Path(__file__).resolve().parents[1]


def test_planning_prototype_contract_is_closed_and_explicit() -> None:
    request = canonicalize_facility_planning_generation_request(
        {
            "planning_package_id": MMLE_FACILITY_PLANNING_PACKAGE_ID,
            "execution_mode": "authorized_draft_run",
        }
    )
    assert request == {
        "planning_package_id": MMLE_FACILITY_PLANNING_PACKAGE_ID,
        "execution_mode": "authorized_draft_run",
    }
    assert facility_planning_prototype_tool_spec()["name"] == (
        FACILITY_PLANNING_PROTOTYPE_TOOL
    )
    assert is_facility_planning_prototype_request(
        "Build the trusted MMLE-50D factory prototype from its planning package."
    )
    assert not is_facility_planning_prototype_request(
        "Build a typical factory for a new product."
    )

    try:
        canonicalize_facility_planning_generation_request(
            {
                "planning_package_id": MMLE_FACILITY_PLANNING_PACKAGE_ID,
                "execution_mode": "authorized_draft_run",
                "coordinates": [10, 20],
            }
        )
    except FacilityPlanningGenerationError as exc:
        assert exc.code == "facility_planning_generation_request_invalid"
    else:  # pragma: no cover - explicit fail-closed assertion.
        raise AssertionError("Model-authored geometry was accepted.")


def test_resource_amendment_contract_is_coordinate_free_and_evidence_bound() -> None:
    request = canonicalize_facility_program_resource_amendment_request(
        {
            "resource_batch_id": "raw-material-racks",
            "quantity": 89,
            "placement_pattern": None,
            "semantic_orientation": "long_side_north_south",
            "authored_spacing_meters": 1.5,
            "execution_mode": "authorized_draft_run",
        }
    )
    assert request == {
        "resource_batch_id": "raw-material-racks",
        "patch": {
            "quantity": 89,
            "semantic_orientation": "long_side_north_south",
            "authored_spacing": {
                "value": 1.5,
                "unit": "m",
                "evidence_ref": "user-authored-facility-program-amendment",
            },
        },
        "execution_mode": "authorized_draft_run",
    }
    assert facility_program_resource_amendment_tool_spec()["name"] == (
        FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL
    )
    assert is_facility_program_resource_amendment_request(
        "Reduce the raw material rack count to 89."
    )
    assert not is_facility_program_resource_amendment_request(
        "Build the trusted MMLE-50D factory prototype."
    )
    assert not is_facility_program_resource_amendment_request(
        "Arrange Assembly using the shortest feasible of line, L, and U "
        "layouts with 1 m spacing."
    )
    assert not is_facility_program_resource_amendment_request(
        "Make this aisle safe for any forklift."
    )
    try:
        canonicalize_facility_program_resource_amendment_request(
            {
                "resource_batch_id": "raw-material-racks",
                "quantity": 89,
                "placement_pattern": None,
                "semantic_orientation": None,
                "authored_spacing_meters": None,
                "execution_mode": "authorized_draft_run",
                "coordinates": [10, 20],
            }
        )
    except FacilityPlanningGenerationError as exc:
        assert exc.code == "facility_program_local_amendment_invalid"
    else:  # pragma: no cover
        raise AssertionError("Model-authored amendment geometry was accepted.")


def test_planning_package_endpoint_resolves_server_side_program(
    tmp_path: Path,
    monkeypatch,
) -> None:
    host = LocalFacilityLayoutHost(
        tmp_path / "facility-planning-host",
        private_assets=True,
        private_asset_root=ROOT,
        facility_planning_root=ROOT / "generated" / "facility_planning",
    )
    captured = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {
            "runId": "fgr-planning-test",
            "status": "planning",
            "prototypeMode": True,
            "saved": False,
        }

    monkeypatch.setattr(
        host.generation_coordinator,
        "start_facility_program_run",
        fake_start,
    )
    app = FastAPI()
    app.include_router(host.create_router())
    client = TestClient(app)
    headers = {"X-InspectorPro-Session": "planning-package-test"}
    try:
        response = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/"
            "planning-package",
            headers=headers,
            json={
                "prototypeMode": True,
                "supersedeActiveDraft": True,
                "planningPackageId": MMLE_FACILITY_PLANNING_PACKAGE_ID,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["planningPackageId"] == MMLE_FACILITY_PLANNING_PACKAGE_ID
        assert body["planningAuthority"] == "illustrative_prototype"
        assert captured["prototype_mode"] is True
        authority = captured["facility_program"]["authority_and_mode"]
        assert authority["mode"] == "intent_driven_prototype"
        assert authority["evidence_status"] == "inferred"
        assert authority["review_status"] == "pending"
        assert authority["production_eligible"] is False
        assert authority["prototype_assumptions_allowed"] is True

        unavailable = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/"
            "planning-package",
            headers=headers,
            json={
                "prototypeMode": True,
                "planningPackageId": "unknown-package",
            },
        )
        assert unavailable.status_code == 422
        assert unavailable.json()["detail"]["error"]["code"] == (
            "facility_planning_package_unavailable"
        )
    finally:
        client.close()
