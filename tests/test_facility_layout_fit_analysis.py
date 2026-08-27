"""Read-only contracts for bounded Facility Layout fit analysis."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ai_inspector.facility_layout.fit_analysis import (
    analyze_facility_asset_fit,
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
MACHINE_REVISION = "a" * 64


def _golden() -> dict:
    return json.loads(SPATIAL_GOLDEN.read_text(encoding="ascii"))


def _catalog(golden: dict, *, with_clearance: bool = True) -> list[dict]:
    assets = deepcopy(golden["assetDefinitions"])
    machine = next(
        item for item in assets
        if item["assetId"] == "asset-machine-golden"
    )
    machine["assetDefinitionRevision"] = MACHINE_REVISION
    if not with_clearance:
        machine["clearances"] = []
    return assets


def _analyze(
    golden: dict,
    layout: dict,
    assets: list[dict],
    *,
    orientations: list[int] | None = None,
) -> dict:
    return analyze_facility_asset_fit(
        layout,
        assets,
        asset_id="asset-machine-golden",
        asset_definition_revision=MACHINE_REVISION,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        orientations_degrees=orientations,
        maximum_results=4,
    )


def test_bounded_fit_finds_validated_candidates_without_mutation() -> None:
    golden = _golden()
    layout = deepcopy(golden["baseLayout"])
    before = canonical_spatial_bytes(layout)

    result = _analyze(
        golden,
        layout,
        _catalog(golden),
        orientations=[0, 90],
    )

    assert canonical_spatial_bytes(layout) == before
    assert result["status"] == "complete"
    assert result["probeCount"] == 25
    assert result["engineEvaluatedCount"] == 50
    assert result["geometricFitFound"] is True
    assert result["clearanceValidatedFitFound"] is True
    assert result["fullyValidatedFitFound"] is True
    assert result["mutated"] is False
    assert result["evidenceClassification"] == {
        "assetAndZoneIdentity": "authored",
        "candidateGeometry": "derived",
        "fitSearchCompleteness": "bounded_not_exhaustive",
        "maximumAdditionalCapacity": "unknown",
        "productionCapacity": "unknown",
    }
    assert all(item["fullyValidated"] for item in result["candidates"])


def test_protected_route_blocks_every_candidate_without_mutation() -> None:
    golden = _golden()
    layout = deepcopy(golden["baseLayout"])
    layout["routes"] = [{
        "routeId": "rt-protected-entire-cell",
        "routeKind": "forklift",
        "corridorWidth": 20.0,
        "centerline": [
            {"x": 0.0, "z": 10.0},
            {"x": 20.0, "z": 10.0},
        ],
    }]
    before = canonical_spatial_bytes(layout)

    result = _analyze(
        golden,
        layout,
        _catalog(golden),
        orientations=[0],
    )

    assert canonical_spatial_bytes(layout) == before
    assert result["status"] == "complete"
    assert result["geometricFitFound"] is False
    assert result["clearanceValidatedFitFound"] is False
    assert result["fullyValidatedFitFound"] is False
    assert result["candidates"] == []
    assert result["rejectionCounts"]["protected_space_intrusion"] == 24
    assert result["mutated"] is False


def test_geometric_fit_does_not_upgrade_missing_clearance_evidence() -> None:
    golden = _golden()
    result = _analyze(
        golden,
        deepcopy(golden["baseLayout"]),
        _catalog(golden, with_clearance=False),
        orientations=[0],
    )

    assert result["geometricFitFound"] is True
    assert result["clearanceValidatedFitFound"] is False
    assert result["fullyValidatedFitFound"] is False
    assert result["candidates"]
    assert all(
        item["geometricValid"] is True
        and item["clearanceValidated"] is False
        and item["fullyValidated"] is False
        and item["safetyStatus"] == "unverified"
        for item in result["candidates"]
    )


def test_missing_exact_asset_revision_fails_closed() -> None:
    golden = _golden()
    result = analyze_facility_asset_fit(
        golden["baseLayout"],
        _catalog(golden),
        asset_id="asset-machine-golden",
        asset_definition_revision="f" * 64,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )

    assert result["status"] == "blocked"
    assert result["blockerCodes"] == ["exact_asset_revision_unavailable"]
    assert result["geometricFitFound"] is False
    assert result["candidates"] == []
