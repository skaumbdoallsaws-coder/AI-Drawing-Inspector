"""KF3 contracts for revision-bound asset and zone planning semantics."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout import planning_readiness as readiness_module
from ai_inspector.facility_layout.planning_readiness import (
    FACILITY_DIRECTIONAL_INTERFACE_ROLES,
    analyze_planning_ready_asset_fit,
    compile_asset_catalog_planning_readiness,
    compile_asset_planning_readiness,
    compile_zone_semantic_readiness,
)
from ai_inspector.facility_layout.spatial import canonical_spatial_bytes


ROOT = Path(__file__).resolve().parents[1]
SPATIAL_GOLDEN = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "spatial"
    / "golden_scenarios.json"
)


def _asset(
    *,
    revision: str | None = "a" * 64,
    side_status: str = "authored",
    clearance_status: str = "authored",
    planning_ready: bool = True,
) -> dict:
    definition = {
        "assetId": "asset-kf3-machine",
        "displayName": "KF3 Machine",
        "category": "Machines",
        "geometry": {
            "footprintPolygons": [[
                {"x": -1.0, "z": -0.5},
                {"x": 1.0, "z": -0.5},
                {"x": 1.0, "z": 0.5},
                {"x": -1.0, "z": 0.5},
            ]],
            "heightInterval": {"minimumY": 0.0, "maximumY": 2.0},
        },
        "coordinateFrame": {
            "allowedMountingSurfaces": ["floor"],
        },
        "facilitySemantics": {
            "semanticType": "machining_center",
            "operationalRoles": ["machining"],
            "functionalSides": {
                "operator": {
                    "side": "south",
                    "evidenceStatus": side_status,
                },
                "material_input": {
                    "side": "west",
                    "evidenceStatus": "derived",
                },
            },
            "evidenceStatus": "authored",
        },
        "mobility": {
            "classification": "fixed",
            "evidenceStatus": "authored",
        },
        "clearances": [{
            "clearanceId": "clr-service",
            "clearanceKind": "maintenance",
            "enforcement": "hard",
            "evidenceStatus": clearance_status,
            "evidence": ["ev-clearance"],
            "geometry": {
                "shape": "rectangle",
                "minimum": {"x": -1.5, "z": -1.0},
                "maximum": {"x": 1.5, "z": 1.0},
            },
        }],
        "capabilities": {"processTypes": ["milling"]},
        "utilities": {
            "electrical": {"evidenceStatus": "authored"},
        },
        "readiness": {
            "visualReady": {"value": True, "blockers": []},
            "placementReady": {"value": True, "blockers": []},
            "planningReady": {
                "value": planning_ready,
                "blockers": [] if planning_ready else ["review_required"],
            },
        },
    }
    result = {
        "assetId": definition["assetId"],
        "definition": definition,
    }
    if revision is not None:
        result["assetDefinitionRevision"] = revision
    return result


def test_revision_bound_asset_compiles_as_controlled_planning_ready() -> None:
    result = compile_asset_planning_readiness(_asset())

    assert result["revisionBound"] is True
    assert result["physicalEnvelope"]["footprint"] == {
        "available": True,
        "method": "revision_bound_footprint_polygons",
        "polygonCount": 1,
        "pointCount": 4,
        "evidenceStatus": "derived",
        "hardRuleEligible": True,
    }
    assert result["physicalEnvelope"]["height"]["heightMeters"] == 2.0
    assert result["readiness"]["level"] == "controlled_planning_ready"
    assert result["readiness"]["controlledPlanningReady"] is True
    assert result["clearances"]["accessEnvelopeCount"] == 1
    assert result["zoneAndProcessSemantics"]["processCapabilities"] == [
        "milling"
    ]


def test_asset_without_exact_revision_is_reported_unavailable() -> None:
    result = compile_asset_planning_readiness(_asset(revision=None))

    assert result["revisionBound"] is False
    assert result["readiness"]["level"] == "unavailable"
    assert result["readiness"]["geometricPlanningReady"] is False
    assert "exact_asset_revision_unavailable" in result["readiness"][
        "blockerCodes"
    ]


def test_catalog_never_drops_an_unavailable_asset() -> None:
    missing_geometry = _asset(revision="b" * 64)
    missing_geometry["assetId"] = "asset-kf3-unavailable"
    missing_geometry["definition"]["assetId"] = "asset-kf3-unavailable"
    missing_geometry["definition"]["geometry"] = {}
    result = compile_asset_catalog_planning_readiness(
        [_asset(), missing_geometry]
    )

    assert result["assetCount"] == 2
    assert result["revisionBoundFootprintCount"] == 1
    assert result["unavailableCount"] == 1
    assert {item["assetId"] for item in result["assets"]} == {
        "asset-kf3-machine",
        "asset-kf3-unavailable",
    }


def test_every_direction_reports_evidence_and_inference_cannot_bind() -> None:
    result = compile_asset_planning_readiness(
        _asset(side_status="inferred")
    )
    roles = result["directionalInterfaces"]["requiredRoles"]

    assert tuple(roles) == FACILITY_DIRECTIONAL_INTERFACE_ROLES
    assert roles["operator"] == {
        "side": "south",
        "evidenceStatus": "inferred",
        "hardRuleEligible": False,
        "sourceRole": "operator",
    }
    assert roles["input"]["side"] == "west"
    assert roles["input"]["evidenceStatus"] == "derived"
    assert roles["input"]["hardRuleEligible"] is True
    assert roles["service"]["evidenceStatus"] == "unknown"
    assert roles["service"]["hardRuleEligible"] is False


def test_inferred_clearance_never_satisfies_controlled_readiness() -> None:
    result = compile_asset_planning_readiness(
        _asset(clearance_status="inferred")
    )

    clearance = result["clearances"]["records"][0]
    assert clearance["geometryAvailable"] is True
    assert clearance["evidenceStatus"] == "inferred"
    assert clearance["hardRuleEligible"] is False
    assert result["clearances"]["evidenceComplete"] is False
    assert result["readiness"]["geometricPlanningReady"] is True
    assert result["readiness"]["controlledPlanningReady"] is False


def test_zone_label_is_preserved_while_inferred_role_stays_advisory() -> None:
    zone = {
        "zoneId": "zn-user-machining",
        "label": "  My Machining Department / Night Shift  ",
        "zoneType": "department",
        "boundary": [
            {"x": 0.0, "z": 0.0},
            {"x": 10.0, "z": 0.0},
            {"x": 10.0, "z": 5.0},
            {"x": 0.0, "z": 5.0},
        ],
    }
    result = compile_zone_semantic_readiness(
        zone,
        layout_revision="c" * 64,
    )

    assert result["label"] == {
        "value": "  My Machining Department / Night Shift  ",
        "evidenceStatus": "authored",
        "source": "user_authored_zone_label",
    }
    assert result["semanticRole"]["semanticType"] == "machining"
    assert result["semanticRole"]["evidenceStatus"] == "inferred"
    assert result["semanticRole"]["hardRuleEligible"] is False


def test_authored_zone_role_can_bind_without_rewriting_label() -> None:
    result = compile_zone_semantic_readiness({
        "zoneId": "zn-quality",
        "label": "QA Lab West",
        "semanticType": "inspection_quality",
        "operationalRoles": ["inspection"],
    })

    assert result["label"]["value"] == "QA Lab West"
    assert result["semanticRole"]["semanticType"] == "inspection_quality"
    assert result["semanticRole"]["evidenceStatus"] == "authored"
    assert result["semanticRole"]["hardRuleEligible"] is True


def test_fit_adapter_delegates_to_existing_analyzer(monkeypatch) -> None:
    layout = {
        "zones": [{
            "zoneId": "zn-fit",
            "label": "Fit Zone",
            "semanticType": "workcell",
        }]
    }
    before = canonical_spatial_bytes(layout)
    calls = []

    def fake_fit(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "complete",
            "fullyValidatedFitFound": True,
            "mutated": False,
        }

    monkeypatch.setattr(readiness_module, "analyze_facility_asset_fit", fake_fit)
    result = analyze_planning_ready_asset_fit(
        layout,
        [_asset()],
        asset_id="asset-kf3-machine",
        asset_definition_revision="a" * 64,
        zone_id="zn-fit",
        maximum_results=3,
    )

    assert len(calls) == 1
    assert calls[0][1]["maximum_results"] == 3
    assert result["analysisOwner"] == (
        "ai_inspector.facility_layout.fit_analysis"
    )
    assert result["controlledPlacementSupported"] is True
    assert canonical_spatial_bytes(layout) == before


def test_real_fit_remains_bounded_revisioned_and_read_only() -> None:
    golden = json.loads(SPATIAL_GOLDEN.read_text(encoding="ascii"))
    assets = deepcopy(golden["assetDefinitions"])
    machine = next(
        item for item in assets if item["assetId"] == "asset-machine-golden"
    )
    machine["assetDefinitionRevision"] = "d" * 64
    layout = deepcopy(golden["baseLayout"])
    before = canonical_spatial_bytes(layout)

    result = analyze_planning_ready_asset_fit(
        layout,
        assets,
        asset_id="asset-machine-golden",
        asset_definition_revision="d" * 64,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        orientations_degrees=[0],
        maximum_results=2,
    )

    assert result["fit"]["analysisMode"] == (
        "read_only_bounded_single_asset_fit"
    )
    assert result["fit"]["returnedCandidateCount"] <= 2
    assert result["fit"]["geometricFitFound"] is True
    assert result["mutated"] is False
    assert canonical_spatial_bytes(layout) == before


@pytest.mark.parametrize("status", ["inferred", "unknown", "unverified"])
def test_non_authoritative_clearance_status_never_promotes(status: str) -> None:
    result = compile_asset_planning_readiness(
        _asset(clearance_status=status)
    )
    assert result["clearances"]["records"][0]["hardRuleEligible"] is False
    assert result["readiness"]["controlledPlanningReady"] is False
