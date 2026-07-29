"""P10 warehouse and manufacturing-cell workflow package tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.observation import TrustedFacilityContext
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.planner import (
    generate_layout_proposals,
    validate_layout_request,
)
from ai_inspector.facility_layout.semantic_plan import (
    compile_semantic_facility_plan,
)
from ai_inspector.facility_layout.workflows import (
    FacilityWorkflowPackageError,
    cell_template_revision,
    compile_manufacturing_cell_package,
    compile_warehouse_lane_package,
)


FIXTURE_ROOT = (
    Path(__file__).parent
    / "fixtures"
    / "facility_layout"
    / "workflows"
)


def _fixture(name: str) -> dict:
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="ascii")
    )


def _contexts(fixture: dict):
    return (
        TrustedFacilityContext(
            "facility_layout.state",
            fixture["trustedState"],
        ),
        TrustedFacilityContext(
            "facility_layout.evidence",
            fixture["trustedEvidence"],
        ),
    )


def _without_request_id(request: dict) -> dict:
    result = deepcopy(request)
    result.pop("requestId", None)
    return result


def _contains_raw_geometry(value) -> bool:
    forbidden = {
        "camera",
        "centerline",
        "coordinate",
        "coordinates",
        "matrix",
        "pixels",
        "position",
        "quaternion",
        "routepoints",
        "screen",
        "transform",
        "viewport",
        "waypoints",
        "x",
        "y",
        "z",
    }
    if isinstance(value, dict):
        return any(
            (
                "".join(
                    character
                    for character in str(key).lower()
                    if character.isalnum()
                )
                in forbidden
            )
            or _contains_raw_geometry(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_raw_geometry(item) for item in value)
    return False


def _zone(
    zone_id: str,
    zone_type: str,
    boundary: list[tuple[float, float]],
    *,
    anchors: list[dict] | None = None,
) -> dict:
    return {
        "zoneId": zone_id,
        "zoneType": zone_type,
        "label": zone_id.replace("-", " ").title(),
        "boundary": [
            {"x": float(x), "z": float(z)} for x, z in boundary
        ],
        "floorElevation": 0.0,
        "allowedAssetCategories": [],
        "gridSpacing": 0.5,
        "anchors": deepcopy(anchors or []),
        "evidence": [],
    }


def _asset_definition(asset: dict, index: int) -> dict:
    connectors = []
    for connector_index, connector in enumerate(
        asset.get("connectors", [])
    ):
        allowed = list(connector.get("allowedRouteKinds", []))
        connectors.append(
            {
                "connectorId": connector["connectorId"],
                "connectorKind": (
                    allowed[0] if allowed else "compressed_air"
                ),
                "position": {
                    "x": 0.4 if connector_index % 2 else -0.4,
                    "y": 0.5,
                    "z": 0.0,
                },
                "facing": {
                    "x": 1.0 if connector_index % 2 else -1.0,
                    "y": 0.0,
                    "z": 0.0,
                },
                "role": "bidirectional",
                "allowedRouteKinds": allowed,
                "interface": {},
                "evidenceStatus": "authored",
                "evidence": [],
            }
        )
    half_x = 0.35 + (index % 3) * 0.05
    half_z = 0.3 + (index % 2) * 0.05
    return {
        "revision": asset["assetDefinitionRevision"],
        "document": {
            "documentKind": "industrial_asset_definition",
            "assetId": asset["assetId"],
            "category": asset["category"],
            "coordinateFrame": {
                "allowedMountingSurfaces": ["floor"],
                "floorAnchor": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            "geometry": {
                "footprintPolygons": [
                    [
                        {"x": -half_x, "z": -half_z},
                        {"x": half_x, "z": -half_z},
                        {"x": half_x, "z": half_z},
                        {"x": -half_x, "z": half_z},
                    ]
                ],
                "heightInterval": {
                    "minimumY": 0.0,
                    "maximumY": 1.5,
                },
            },
            "collision": {
                "geometry": {"footprintIndex": 0},
                "verticalInterval": {
                    "minimumY": 0.0,
                    "maximumY": 1.5,
                },
            },
            "connectors": connectors,
        },
    }


def _planner_context(
    fixture: dict,
    *,
    warehouse: bool,
) -> tuple[dict, dict, dict]:
    state = fixture["trustedState"]
    scope = fixture["spec"]["scope"]
    sources = fixture["spec"]["sourceRevisions"]
    layout = create_layout_document(
        layout_id=scope["layoutId"],
        display_name=scope["label"],
        association={"siteId": scope["siteId"], "areaId": "area-p10"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "datum-p10",
            "floorElevation": 0.0,
        },
        source_shell_ref={
            "shellId": state["dependencyRevisions"]["shellId"],
            "shellRevision": sources["shell"],
            "coordinateFrameFingerprint": "8" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-p10",
            "policySetRevision": sources["policy"],
        },
        catalog_snapshot_revision=sources["catalog"],
        created_at="2026-07-29T00:00:00Z",
    )
    if warehouse:
        zones = [
            _zone(
                "zn-warehouse-storage",
                "storage",
                [(0, 0), (18, 0), (18, 10), (0, 10)],
            ),
            _zone(
                "zn-warehouse-staging",
                "staging",
                [(18, 0), (26, 0), (26, 5), (18, 5)],
            ),
            _zone(
                "zn-warehouse-dock",
                "dock",
                [(18, 5), (26, 5), (26, 10), (18, 10)],
            ),
            _zone(
                "zn-warehouse-charging",
                "charging",
                [(18, 10), (26, 10), (26, 14), (18, 14)],
            ),
            _zone(
                "zn-warehouse-aisle",
                "aisle",
                [(0, 14), (28, 14), (28, 18), (0, 18)],
                anchors=[
                    {
                        "anchorId": "za-warehouse-in",
                        "anchorKind": "forklift",
                        "position": {"x": 2.0, "y": 0.0, "z": 16.0},
                        "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "allowedRouteKinds": ["forklift"],
                        "evidence": [],
                    },
                    {
                        "anchorId": "za-warehouse-out",
                        "anchorKind": "forklift",
                        "position": {
                            "x": 26.0,
                            "y": 0.0,
                            "z": 16.0,
                        },
                        "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "allowedRouteKinds": ["forklift"],
                        "evidence": [],
                    },
                ],
            ),
        ]
    else:
        zones = [
            _zone(
                "zn-cell-work",
                "workcell",
                [(0, 0), (30, 0), (30, 20), (0, 20)],
            ),
            _zone(
                "zn-cell-operator",
                "operator",
                [(32, 0), (42, 0), (42, 8), (32, 8)],
            ),
            _zone(
                "zn-cell-maintenance",
                "service",
                [(32, 10), (45, 10), (45, 20), (32, 20)],
            ),
            _zone(
                "zn-cell-safety",
                "safety",
                [(0, 22), (30, 22), (30, 28), (0, 28)],
            ),
        ]
    result = apply_facility_layout_operations(
        layout,
        [{"op": "add_zone", "zone": zone} for zone in zones],
    )
    assets = {
        item["assetId"]: _asset_definition(item, index)
        for index, item in enumerate(state["assets"])
    }
    vehicles = {
        "vehicle-warehouse-forklift": {
            "vehicleProfileId": "vehicle-warehouse-forklift",
            "vehicleProfileRevision": "e" * 64,
            "displayName": "Warehouse test forklift",
            "overallDimensions": {
                "length": 1.2,
                "width": 0.8,
                "height": 1.8,
            },
            "footprint": [
                {"x": -0.6, "z": -0.4},
                {"x": 0.6, "z": -0.4},
                {"x": 0.6, "z": 0.4},
                {"x": -0.6, "z": 0.4},
            ],
            "wheelbase": 0.8,
            "steeringLimits": {"minimumTurningRadiusMeters": 1.0},
            "speedLimits": {"maximumMetersPerSecond": 2.0},
            "loadLimits": {"maximumKilograms": 1000},
            "gradeLimits": {"maximumPercent": 8},
            "reversePolicy": "allowed",
        }
    }
    return result["document"], assets, vehicles


def test_warehouse_lane_compiles_deterministically_with_capacity() -> None:
    fixture = _fixture("warehouse-lane.json")
    original = deepcopy(fixture["spec"])

    first = compile_warehouse_lane_package(fixture["spec"])
    second = compile_warehouse_lane_package(deepcopy(fixture["spec"]))

    assert first == second
    assert fixture["spec"] == original
    assert first["specFingerprint"] == (
        "892ff567a07527f7c50bda03c8e55716a22fdb3ebd670cd163dc727e41b7f9e9"
    )
    lane = first["domainModel"]["warehouseLane"]
    assert lane["counts"] == {
        "rows": 2,
        "bays": 6,
        "levels": 12,
        "slots": 24,
        "nominalPalletPositions": 24,
    }
    assert len(lane["rows"]) == 2
    assert len(lane["rows"][0]["bays"]) == 3
    assert len(lane["rows"][0]["bays"][0]["slots"]) == 4
    assert len(lane["pallets"]) == 2
    assert first["estimates"]["capacity"] == {
        "estimateType": "planning_estimate",
        "nominalPalletPositions": 24,
        "planningUtilizationPercent": 85.0,
        "usablePalletPositions": 20,
        "occupiedPalletPositions": 2,
        "availablePalletPositions": 18,
        "basis": {
            "knowledgeStatus": "inferred",
            "evidenceIds": [],
            "assumptionIds": [
                "assumption-warehouse-utilization"
            ],
        },
        "sourceRevisions": fixture["spec"]["sourceRevisions"],
    }


def test_warehouse_manual_and_sage_paths_compile_to_same_intent() -> None:
    fixture = _fixture("warehouse-lane.json")
    result = compile_warehouse_lane_package(fixture["spec"])
    state, evidence = _contexts(fixture)
    sage = compile_semantic_facility_plan(
        result["semanticPlan"],
        state=state,
        evidence=evidence,
    )

    assert validate_layout_request(
        result["manualPlannerRequest"]
    ) == result["manualPlannerRequest"]
    assert _without_request_id(
        result["manualPlannerRequest"]
    ) == _without_request_id(sage["plannerRequest"])
    assert sage["semanticSummary"] == {
        "selectedAssetItemCount": 5,
        "requestedPlacementCount": 9,
        "requiredCapabilityCount": 1,
        "zoneRequestCount": 4,
        "flowCount": 1,
        "processBindingCount": 0,
        "assumptionCount": 1,
        "unresolvedCount": 0,
    }
    assert (
        result["estimates"]["forkliftTravel"][0]["estimateStatus"]
        == "computed_by_deterministic_router_on_preview"
    )
    assert not _contains_raw_geometry(result["semanticPlan"])


def test_warehouse_rejects_slot_overfill_and_raw_geometry() -> None:
    fixture = _fixture("warehouse-lane.json")
    overfilled = deepcopy(fixture["spec"])
    duplicate = deepcopy(overfilled["pallets"][0])
    duplicate["palletId"] = "pallet-alpha-003"
    overfilled["pallets"].append(duplicate)
    with pytest.raises(
        FacilityWorkflowPackageError,
        match="exceeds its declared pallet positions",
    ) as caught:
        compile_warehouse_lane_package(overfilled)
    assert caught.value.code == "warehouse_slot_capacity_exceeded"

    forged = deepcopy(fixture["spec"])
    forged["rackSystem"]["position"] = {"east": 12}
    with pytest.raises(FacilityWorkflowPackageError) as caught:
        compile_warehouse_lane_package(forged)
    assert caught.value.code == "workflow_raw_geometry_forbidden"


def test_cnc_cell_compiles_complete_role_template_and_provenance() -> None:
    fixture = _fixture("cnc-tending-cell.json")
    original = deepcopy(fixture["spec"])

    first = compile_manufacturing_cell_package(fixture["spec"])
    second = compile_manufacturing_cell_package(
        deepcopy(fixture["spec"])
    )

    assert first == second
    assert fixture["spec"] == original
    assert first["specFingerprint"] == (
        "64d2f3bae60a12268516bdb17189844773f79a5a3f85eb6730d407b507bc66eb"
    )
    cell = first["domainModel"]["manufacturingCell"]
    assert cell["templateRevision"] == (
        "7f5653fea6ce8634d2ea73c60822a33ec7a769d1bcc965af1ca53331cc9b74d9"
    )
    assert cell_template_revision(
        fixture["spec"]["template"]
    ) == cell["templateRevision"]
    assert {
        item["cellRole"] for item in cell["roles"]
    } == {
        "machine",
        "robot",
        "fixture",
        "guard",
        "workstation",
        "conveyor",
        "material_input",
        "material_output",
    }
    assert cell["operatorZoneIds"] == ["zone-cell-operator"]
    assert cell["maintenanceZoneIds"] == [
        "zone-cell-maintenance"
    ]
    assert cell["safetyZoneIds"] == ["zone-cell-safety"]
    assert cell["processBindingIntentIds"] == [
        "binding-cell-cnc-tending"
    ]
    assert first["estimates"]["resourceSummary"][
        "requestedPlacementCount"
    ] == 8
    assert first["estimates"]["processCoverage"][
        "operationNodeCount"
    ] == 3


def test_cnc_cell_manual_and_sage_paths_compile_to_same_intent() -> None:
    fixture = _fixture("cnc-tending-cell.json")
    result = compile_manufacturing_cell_package(fixture["spec"])
    state, evidence = _contexts(fixture)
    sage = compile_semantic_facility_plan(
        result["semanticPlan"],
        state=state,
        evidence=evidence,
    )

    assert validate_layout_request(
        result["manualPlannerRequest"]
    ) == result["manualPlannerRequest"]
    assert _without_request_id(
        result["manualPlannerRequest"]
    ) == _without_request_id(sage["plannerRequest"])
    assert sage["semanticSummary"] == {
        "selectedAssetItemCount": 8,
        "requestedPlacementCount": 8,
        "requiredCapabilityCount": 3,
        "zoneRequestCount": 1,
        "flowCount": 5,
        "processBindingCount": 1,
        "assumptionCount": 1,
        "unresolvedCount": 13,
    }
    codes = {
        item["code"] for item in sage["unresolvedItems"]
    }
    assert "utility_network_planning_deferred" in codes
    assert "process_binding_application_deferred" in codes
    assert "route_mutation_not_supported" in codes
    assert "operational_overlay_zone_pending" in codes
    assert not _contains_raw_geometry(result["semanticPlan"])


def test_cell_template_is_reusable_across_layout_identity() -> None:
    fixture = _fixture("cnc-tending-cell.json")
    first = compile_manufacturing_cell_package(fixture["spec"])
    reused = deepcopy(fixture["spec"])
    reused["packageId"] = "cnc-tending-cell-beta"
    reused["scope"] = {
        "siteId": "site-cell-beta",
        "layoutId": "fl-cell-beta",
        "label": "CNC tending cell beta",
    }
    reused["sourceRevisions"]["layout"] = "9" * 64
    second = compile_manufacturing_cell_package(reused)

    assert (
        first["domainModel"]["reusableTemplate"]
        == second["domainModel"]["reusableTemplate"]
    )
    assert (
        first["domainModel"]["manufacturingCell"][
            "templateFingerprint"
        ]
        == second["domainModel"]["manufacturingCell"][
            "templateFingerprint"
        ]
    )
    assert first["specFingerprint"] != second["specFingerprint"]
    assert first["semanticPlan"]["planId"] != second["semanticPlan"]["planId"]


def test_cell_rejects_missing_role_and_stale_template_revision() -> None:
    fixture = _fixture("cnc-tending-cell.json")
    missing = deepcopy(fixture["spec"])
    missing["assetAssignments"].pop()
    with pytest.raises(FacilityWorkflowPackageError) as caught:
        compile_manufacturing_cell_package(missing)
    assert caught.value.code == "cell_role_assignments_incomplete"

    stale = deepcopy(fixture["spec"])
    stale["template"]["label"] = "Changed without revision"
    with pytest.raises(FacilityWorkflowPackageError) as caught:
        compile_manufacturing_cell_package(stale)
    assert caught.value.code == "cell_template_revision_mismatch"


def test_workflow_packages_have_no_product_fixture_dependency() -> None:
    package_root = (
        Path(__file__).parents[1]
        / "ai_inspector"
        / "facility_layout"
        / "workflows"
    )
    source = "\n".join(
        path.read_text(encoding="ascii")
        for path in sorted(package_root.glob("*.py"))
    ).lower()
    assert "assem3" not in source
    assert "tricycle" not in source


@pytest.mark.parametrize(
    ("fixture_name", "compiler", "warehouse", "expected_instances"),
    [
        (
            "warehouse-lane.json",
            compile_warehouse_lane_package,
            True,
            9,
        ),
        (
            "cnc-tending-cell.json",
            compile_manufacturing_cell_package,
            False,
            8,
        ),
    ],
)
def test_manual_and_sage_requests_build_real_p8_ghost_alternatives(
    fixture_name,
    compiler,
    warehouse,
    expected_instances,
) -> None:
    fixture = _fixture(fixture_name)
    package = compiler(fixture["spec"])
    state, evidence = _contexts(fixture)
    sage = compile_semantic_facility_plan(
        package["semanticPlan"],
        state=state,
        evidence=evidence,
    )
    layout, assets, vehicles = _planner_context(
        fixture,
        warehouse=warehouse,
    )

    manual_preview = generate_layout_proposals(
        layout,
        package["manualPlannerRequest"],
        assets,
        vehicle_profiles=vehicles,
    )
    sage_preview = generate_layout_proposals(
        layout,
        sage["plannerRequest"],
        assets,
        vehicle_profiles=vehicles,
    )

    for preview in (manual_preview, sage_preview):
        assert preview["previewPure"] is True
        assert preview["alternatives"]
        selected = preview["alternatives"][0]
        assert selected["metrics"]["completeAssetSet"] is True
        assert (
            selected["metrics"]["requestedInstanceCount"]
            == expected_instances
        )
        assert (
            selected["metrics"]["resolvedInstanceCount"]
            == expected_instances
        )
        assert selected["metrics"]["spatialErrorCount"] == 0
        assert any(
            operation["op"] == "place_asset"
            for operation in selected["operations"]
        )
        replay = apply_facility_layout_operations(
            layout,
            selected["operations"],
            base_revision=preview["layoutRevision"],
        )
        assert replay["diffHash"] == selected["operationReceipt"][
            "diffHash"
        ]
