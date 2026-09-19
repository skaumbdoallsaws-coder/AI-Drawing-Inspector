from __future__ import annotations

import math

import pytest

from ai_inspector.facility_layout.prototype_actor_profile import (
    FacilityActorProfileError,
    build_prototype_actor_profile,
)


REVISION = "a" * 64
FOOTPRINT = [
    {"x": -0.25, "z": -0.32},
    {"x": 0.25, "z": -0.32},
    {"x": 0.25, "z": 0.32},
    {"x": -0.25, "z": 0.32},
]


def test_profile_uses_exact_catalog_footprint_and_zero_added_clearance() -> None:
    placements = [{
        "placementId": "pl-operator-01",
        "assetId": "asset-operator",
        "transform": {"scale": 1},
    }]

    profile = build_prototype_actor_profile(
        asset_id="asset-operator",
        asset_definition_revision=REVISION,
        footprint_vertices=FOOTPRINT,
        placements=placements,
    )

    assert profile["footprintVertices"] == FOOTPRINT
    assert profile["navigationRadiusMeters"] == round(
        math.hypot(0.25, 0.32),
        6,
    )
    assert profile["additionalClearanceMeters"] == 0
    assert profile["envelopeAuthority"] == "catalog_footprint_geometry"
    assert profile["prototypeMode"] is True
    assert profile["productionEligible"] is False
    assert profile["placementScaleCheck"]["allUnitScale"] is True
    assert len(profile["profileRevision"]) == 64


def test_profile_refuses_ambiguous_or_scaled_geometry_sources() -> None:
    with pytest.raises(FacilityActorProfileError, match="exactly one"):
        build_prototype_actor_profile(
            asset_id="asset-operator",
            asset_definition_revision=REVISION,
            dimensions={"width": 0.5, "depth": 0.64},
            footprint_vertices=FOOTPRINT,
        )

    with pytest.raises(FacilityActorProfileError, match="Non-unit"):
        build_prototype_actor_profile(
            asset_id="asset-operator",
            asset_definition_revision=REVISION,
            footprint_vertices=FOOTPRINT,
            placements=[{
                "placementId": "pl-operator-01",
                "assetId": "asset-operator",
                "transform": {"scale": 1.2},
            }],
        )
