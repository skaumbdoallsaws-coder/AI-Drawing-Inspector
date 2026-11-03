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

A ceiling may name a ``finish`` (``FINISHES``): "acoustic-tile" (a white suspended ceiling of 600 mm tiles) or
"open-deck" (matte charcoal); without one it is drawn matte charcoal (the 3D view only; the checks ignore it).

Zone roofs (2026-11-02): ``extensions.roof`` = ``{"heightMeters": H}`` draws a flat roof over the zone whose underside
is H m above its floor (the wall tops), in the 3D view only, on the roof sheeting layer. ``set_zone_roof`` sets or
clears it. Nothing else reads it.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

KEY = "ceiling"
ROOF_KEY = "roof"
PREFIX = "layout-ceiling-"
MIN_HEIGHT_METERS, MAX_HEIGHT_METERS = 2.0, 40.0
FINISHES = ("acoustic-tile", "open-deck")


def _height(value: Any, what: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not MIN_HEIGHT_METERS <= value <= MAX_HEIGHT_METERS:
        raise ValueError(f"A zone {what}'s heightMeters must be between {MIN_HEIGHT_METERS:g} and "
                         f"{MAX_HEIGHT_METERS:g}")
    rounded = round(float(value), 3)
    return int(rounded) if rounded == int(rounded) else rounded


def normalize_ceiling(value: Any) -> dict:
    if not isinstance(value, Mapping) or "heightMeters" not in value or not set(value) <= {"heightMeters", "finish"}:
        raise ValueError("A zone ceiling is {heightMeters} with an optional finish")
    result = {"heightMeters": _height(value["heightMeters"], "ceiling")}
    if "finish" in value:
        if value["finish"] not in FINISHES:
            raise ValueError("A zone ceiling's finish is one of: " + ", ".join(FINISHES))
        result["finish"] = value["finish"]
    return result


def normalize_roof(value: Any) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"heightMeters"}:
        raise ValueError("A zone roof is {heightMeters}")
    return {"heightMeters": _height(value["heightMeters"], "roof")}


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
