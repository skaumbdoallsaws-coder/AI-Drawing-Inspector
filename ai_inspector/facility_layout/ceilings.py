"""Zone ceilings: a layout says "this zone has a ceiling H m up", so lamps can hang from it (2026-11-02).

A zone may carry ``extensions.ceiling`` = ``{"heightMeters": H}`` (2 to 40 m above the zone's floorElevation), over
the zone's whole boundary. ``plan_settings.shell_with_plan_boundary`` adds each one to the shell the spatial checks
see, as a mounting surface of kind "ceiling" (featureId ``layout-ceiling-<zoneId>``); the shared shell authority is
not edited. ``set_zone_ceiling`` sets or clears it.

A placement hangs from a ceiling when its asset allows it (``coordinateFrame.allowedMountingSurfaces`` includes
"ceiling") and the placement asks for it (``metadata.mountingSurface`` ``{"surfaceKind": "ceiling"}``, implied when
"ceiling" is the asset's only mounting surface). ``spatial._mounting_checks`` then wants its footprint inside a zone
ceiling and its top (the highest point of its physical volume) at that ceiling's height. Collisions stay 3D, so a
lamp hung over a table collides with it only where their heights overlap.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

KEY = "ceiling"
PREFIX = "layout-ceiling-"
MIN_HEIGHT_METERS, MAX_HEIGHT_METERS = 2.0, 40.0


def normalize_ceiling(value: Any) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"heightMeters"}:
        raise ValueError("A zone ceiling is {heightMeters}")
    height = value["heightMeters"]
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) \
            or not MIN_HEIGHT_METERS <= height <= MAX_HEIGHT_METERS:
        raise ValueError(f"A zone ceiling's heightMeters must be between {MIN_HEIGHT_METERS:g} and "
                         f"{MAX_HEIGHT_METERS:g}")
    rounded = round(float(height), 3)
    return {"heightMeters": int(rounded) if rounded == int(rounded) else rounded}


def zone_ceiling(zone: Any) -> Mapping[str, Any] | None:
    extensions = zone.get("extensions") if isinstance(zone, Mapping) else None
    value = extensions.get(KEY) if isinstance(extensions, Mapping) else None
    return value if isinstance(value, Mapping) else None


def append_ceiling_features(shell: dict, layout: Mapping[str, Any]) -> None:
    """Each zone ceiling as a "ceiling" mounting surface at the zone's floor elevation plus its height."""
    features = shell.setdefault("features", [])
    for zone in layout.get("zones") or []:
        ceiling = zone_ceiling(zone)
        if ceiling is None:
            continue
        try:
            height = normalize_ceiling(ceiling)["heightMeters"]
            floor = float(zone.get("floorElevation", 0))
        except (TypeError, ValueError):
            continue  # validate_layout refuses it; the checks see no ceiling there
        features.append({
            "featureId": PREFIX + str(zone.get("zoneId")), "featureKind": "mounting_surface",
            "surfaceKind": "ceiling", "evidence": [],
            "geometry": {"boundary": deepcopy(zone.get("boundary")), "elevation": floor + height},
        })
