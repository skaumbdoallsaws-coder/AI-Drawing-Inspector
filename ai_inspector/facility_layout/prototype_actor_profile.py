"""Prototype, geometry-only navigation profiles for placed actors.

The navigation radius is *computed* from the exact revision-bound catalog
footprint - the maximum distance of any footprint vertex from the placement
origin - never supplied as unexplained policy. That makes it rotation
invariant: the disc encloses the rendered footprint at any heading.

This envelope is rendered footprint geometry and nothing else. It does not
establish human clearance, body sway, ergonomics, accessibility, safe
separation, collision safety, or regulatory compliance. ``additionalClearance``
is fixed at zero so no safety margin can be smuggled in through this path.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

PROTOTYPE_ACTOR_PROFILE_SCHEMA_VERSION = "facility-prototype-actor-profile-v1"

#: The compiler normalizes geometry to six decimals; match it exactly so a
#: recomputed radius never disagrees with the one bound into a snapshot.
GEOMETRY_DECIMALS = 6

ENVELOPE_QUALIFICATION = (
    "Rendered footprint geometry only. This envelope circumscribes the exact "
    "catalog footprint so it remains valid at any heading. It establishes no "
    "human clearance, body sway, ergonomics, accessibility, safe separation, "
    "collision safety, or regulatory compliance, and carries no additional "
    "clearance."
)


class FacilityActorProfileError(ValueError):
    """Raised when a prototype actor profile cannot be derived."""


def footprint_vertices_from_dimensions(
    dimensions: Mapping[str, Any],
) -> list[dict[str, float]]:
    """Return the four half-extent corners of a catalog bounding footprint."""

    try:
        width = float(dimensions["width"])
        depth = float(dimensions["depth"])
    except (KeyError, TypeError, ValueError) as error:
        raise FacilityActorProfileError(
            "Catalog dimensions must supply numeric width and depth."
        ) from error
    if not (math.isfinite(width) and math.isfinite(depth)) or width <= 0 or depth <= 0:
        raise FacilityActorProfileError("Catalog footprint must be positive and finite.")
    half_x = width / 2.0
    half_z = depth / 2.0
    return [
        {"x": -half_x, "z": -half_z},
        {"x": half_x, "z": -half_z},
        {"x": half_x, "z": half_z},
        {"x": -half_x, "z": half_z},
    ]


def rotation_invariant_radius(vertices: Sequence[Mapping[str, Any]]) -> float:
    """Maximum distance of any footprint vertex from the placement origin."""

    if not vertices:
        raise FacilityActorProfileError("Footprint must contain at least one vertex.")
    best = 0.0
    for vertex in vertices:
        x = float(vertex["x"])
        z = float(vertex["z"])
        if not (math.isfinite(x) and math.isfinite(z)):
            raise FacilityActorProfileError("Footprint vertices must be finite.")
        best = max(best, math.hypot(x, z))
    if best <= 0.0:
        raise FacilityActorProfileError("Footprint radius must be positive.")
    return best


def validate_placement_scales(
    placements: Sequence[Mapping[str, Any]],
    asset_id: str,
) -> dict[str, Any]:
    """Confirm every placement of an asset renders at unit scale.

    A scaled placement would render a footprint the derived radius does not
    enclose, so this is checked rather than assumed.
    """

    scales: dict[str, float] = {}
    for placement in placements:
        if placement.get("assetId") != asset_id:
            continue
        raw = (placement.get("transform") or {}).get("scale", 1)
        if isinstance(raw, Mapping):
            components = [float(raw.get(axis, 1)) for axis in ("x", "y", "z")]
            scale = max(components)
        else:
            scale = float(raw)
        scales[placement["placementId"]] = scale
    non_unit = sorted(
        placement_id
        for placement_id, scale in scales.items()
        if abs(scale - 1.0) > 1e-9
    )
    return {
        "assetId": asset_id,
        "placementCount": len(scales),
        "nonUnitScalePlacementIds": non_unit,
        "allUnitScale": not non_unit,
    }


def build_prototype_actor_profile(
    *,
    asset_id: str,
    asset_definition_revision: str,
    dimensions: Mapping[str, Any] | None = None,
    footprint_vertices: Sequence[Mapping[str, Any]] | None = None,
    actor_class: str = "pedestrian",
    placements: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Derive a content-hashed, geometry-only navigation profile."""

    if actor_class not in {"pedestrian", "vehicle"}:
        raise FacilityActorProfileError("Actor class must be pedestrian or vehicle.")
    if len(str(asset_definition_revision)) != 64:
        raise FacilityActorProfileError(
            "Profile must bind a 64-character asset definition revision."
        )

    if (dimensions is None) == (footprint_vertices is None):
        raise FacilityActorProfileError(
            "Supply exactly one catalog footprint source."
        )
    vertices = (
        footprint_vertices_from_dimensions(dimensions)
        if dimensions is not None
        else [
            {"x": float(vertex["x"]), "z": float(vertex["z"])}
            for vertex in footprint_vertices or ()
        ]
    )
    exact_radius = rotation_invariant_radius(vertices)
    radius = round(exact_radius, GEOMETRY_DECIMALS)

    scale_check = validate_placement_scales(placements, asset_id)
    if placements and not scale_check["allUnitScale"]:
        raise FacilityActorProfileError(
            "Non-unit placement scale would render a footprint this radius does "
            f"not enclose: {scale_check['nonUnitScalePlacementIds']}"
        )

    profile = {
        "schemaVersion": PROTOTYPE_ACTOR_PROFILE_SCHEMA_VERSION,
        "profileKind": actor_class,
        "profileId": f"prototype-{asset_id}-geometry-v1",
        "assetId": asset_id,
        "assetDefinitionRevision": str(asset_definition_revision),
        "footprintVertices": [
            {
                "x": round(vertex["x"], GEOMETRY_DECIMALS),
                "z": round(vertex["z"], GEOMETRY_DECIMALS),
            }
            for vertex in vertices
        ],
        "navigationRadiusMeters": radius,
        "additionalClearanceMeters": 0,
        "envelopeAuthority": "catalog_footprint_geometry",
        "evidenceStatus": "derived",
        "reviewStatus": "pending",
        "prototypeMode": True,
        "productionEligible": False,
        "placementScaleCheck": scale_check,
        "qualification": ENVELOPE_QUALIFICATION,
    }
    payload = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    profile["profileRevision"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return profile
