"""Canonical Facility Layout plan-boundary and grid settings."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping


PLAN_SETTINGS_EXTENSION_KEY = "facilityPlan"
DEFAULT_WIDTH_METERS = 40.0
DEFAULT_DEPTH_METERS = 30.0
DEFAULT_GRID_SPACING_METERS = 1.0
DEFAULT_MAJOR_GRID_SPACING_METERS = 5.0
MINIMUM_FACILITY_DIMENSION_METERS = 0.5
MAXIMUM_FACILITY_DIMENSION_METERS = 10_000.0
MINIMUM_GRID_SPACING_METERS = 0.05


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def normalize_plan_settings(value: Mapping[str, Any]) -> dict[str, float]:
    """Validate one persisted plan-setting value without applying defaults."""

    if not isinstance(value, Mapping):
        raise ValueError("planSettings must be an object")
    allowed = {
        "widthMeters",
        "depthMeters",
        "gridSpacingMeters",
        "majorGridSpacingMeters",
    }
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ValueError("planSettings contains unsupported fields: " + ", ".join(unknown))
    width = _finite_number(value.get("widthMeters"), "widthMeters")
    depth = _finite_number(value.get("depthMeters"), "depthMeters")
    grid = _finite_number(value.get("gridSpacingMeters"), "gridSpacingMeters")
    major = _finite_number(
        value.get("majorGridSpacingMeters"),
        "majorGridSpacingMeters",
    )
    for field, number in (("widthMeters", width), ("depthMeters", depth)):
        if not MINIMUM_FACILITY_DIMENSION_METERS <= number <= MAXIMUM_FACILITY_DIMENSION_METERS:
            raise ValueError(
                f"{field} must be between {MINIMUM_FACILITY_DIMENSION_METERS} "
                f"and {MAXIMUM_FACILITY_DIMENSION_METERS} meters"
            )
    maximum_grid = max(width, depth)
    if not MINIMUM_GRID_SPACING_METERS <= grid <= maximum_grid:
        raise ValueError(
            f"gridSpacingMeters must be between {MINIMUM_GRID_SPACING_METERS} "
            f"and {maximum_grid} meters"
        )
    if not grid <= major <= maximum_grid:
        raise ValueError(
            "majorGridSpacingMeters must be at least the grid spacing and no "
            "larger than the facility"
        )
    multiple = major / grid
    if abs(multiple - round(multiple)) > 1e-9:
        raise ValueError("majorGridSpacingMeters must be a whole multiple of gridSpacingMeters")
    return {
        "widthMeters": width,
        "depthMeters": depth,
        "gridSpacingMeters": grid,
        "majorGridSpacingMeters": major,
    }


def plan_settings_from_layout(layout: Mapping[str, Any]) -> dict[str, float] | None:
    extensions = layout.get("extensions") if isinstance(layout, Mapping) else None
    if not isinstance(extensions, Mapping):
        return None
    value = extensions.get(PLAN_SETTINGS_EXTENSION_KEY)
    if not isinstance(value, Mapping):
        return None
    return normalize_plan_settings(value)


def default_plan_settings(
    *,
    width_meters: float = DEFAULT_WIDTH_METERS,
    depth_meters: float = DEFAULT_DEPTH_METERS,
    grid_spacing_meters: float = DEFAULT_GRID_SPACING_METERS,
    major_grid_spacing_meters: float = DEFAULT_MAJOR_GRID_SPACING_METERS,
) -> dict[str, float]:
    return normalize_plan_settings({
        "widthMeters": width_meters,
        "depthMeters": depth_meters,
        "gridSpacingMeters": grid_spacing_meters,
        "majorGridSpacingMeters": major_grid_spacing_meters,
    })


def plan_world_bounds(
    settings: Mapping[str, Any],
    *,
    minimum_x: float = 0.0,
    minimum_z: float = 0.0,
    floor_y: float = 0.0,
) -> dict[str, float]:
    normalized = normalize_plan_settings(settings)
    return {
        "minX": float(minimum_x),
        "minZ": float(minimum_z),
        "maxX": float(minimum_x) + normalized["widthMeters"],
        "maxZ": float(minimum_z) + normalized["depthMeters"],
        "floorY": float(floor_y),
    }


def shell_with_plan_boundary(
    shell: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the shell with its floor boundary replaced by authored plan bounds."""

    result = deepcopy(dict(shell))
    from .perimeter_walls import append_wall_features
    append_wall_features(result, layout)
    from .interior_walls import append_interior_features
    append_interior_features(result, layout)
    # Zone ceilings: "ceiling" mounting surfaces that lamps hang from (ceilings.py).
    from .ceilings import append_ceiling_features
    append_ceiling_features(result, layout)
    from .ground import KEY as GROUND_KEY, apply_ground_to_shell
    if GROUND_KEY in layout.get("extensions", {}):
        apply_ground_to_shell(result, layout)
        return result
    settings = plan_settings_from_layout(layout)
    if settings is None:
        return result
    floor_y = float(
        (result.get("coordinateFrame") or {}).get("floorElevation", 0.0)
    )
    boundary = [
        {"x": 0.0, "z": 0.0},
        {"x": settings["widthMeters"], "z": 0.0},
        {"x": settings["widthMeters"], "z": settings["depthMeters"]},
        {"x": 0.0, "z": settings["depthMeters"]},
    ]
    features = result.get("features")
    if not isinstance(features, list):
        features = []
        result["features"] = features
    floor = next(
        (
            feature
            for feature in features
            if isinstance(feature, dict)
            and feature.get("featureKind") in {"floor", "floor_surface"}
        ),
        None,
    )
    if floor is None:
        floor = {
            "featureId": "floor-layout-plan",
            "featureKind": "floor_surface",
            "geometry": {},
            "evidence": [],
        }
        features.append(floor)
    geometry = floor.get("geometry")
    if not isinstance(geometry, dict):
        geometry = {}
        floor["geometry"] = geometry
    geometry["boundary"] = boundary
    geometry["elevation"] = floor_y
    return result
