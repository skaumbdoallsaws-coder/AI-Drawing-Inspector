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

A placement may hang under another placement instead, a raised structure such as a pergola roof (2026-11-05):
``metadata.mountingSurface`` ``{"surfaceKind": "ceiling", "placementId": <host>}`` (the kind may be left out). The
checks see the host's underside as a ceiling (featureId ``placement-underside-<host>``,
``spatial._placement_underside_surfaces``): its footprint at the lowest point of its physical volume, which must be at
least MIN_HEIGHT_METERS above the layout's floorElevation, so nothing hangs under a desk; a missing host is an error
too. The rules above then apply. An item whose top meets its host's underside touches it without colliding, and
collides as before with anything else it overlaps.

A ceiling may name a ``finish`` (``FINISHES``): "acoustic-tile" (a white suspended ceiling of 600 mm tiles) or
"open-deck" (exposed light grey steel joists whose underside is at the height, under a ribbed deck, 2026-11-03);
without one it is drawn matte charcoal (the 3D view only; the checks ignore it).

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


COVERS = ((KEY, "set_zone_ceiling"), (ROOF_KEY, "set_zone_roof"))


def kept_zone_covers(saved_zone: Any, sent_extensions: Mapping[str, Any]) -> dict:
    """A zone's ceiling and roof change only through set_zone_ceiling and set_zone_roof (2026-11-03). For extensions
    sent to replace a zone's (an edit_zone patch, or a zone in a whole-document save): each of the two left out keeps
    its saved value (None: none), and one sent must equal it. Returns {key: kept value or None}; raises ValueError
    naming the operation that owns a changed one."""
    extensions = saved_zone.get("extensions") if isinstance(saved_zone, Mapping) else None
    saved = extensions if isinstance(extensions, Mapping) else {}
    kept = {}
    for key, owner in COVERS:
        if key in sent_extensions and sent_extensions[key] != saved.get(key):
            raise ValueError(f"A zone's extensions.{key} stays as saved: leave it out or send it unchanged, and change "
                             f"it with {owner}.")
        kept[key] = deepcopy(saved.get(key))
    return kept


def put_back_zone_covers(zone: dict, kept: Mapping[str, Any]) -> None:
    """Set the zone's extensions.ceiling and extensions.roof to KEPT (kept_zone_covers), None meaning none."""
    extensions = zone.get("extensions")
    if not isinstance(extensions, dict):
        if all(value is None for value in kept.values()):
            return
        extensions = zone["extensions"] = {}
    for key, value in kept.items():
        if value is None:
            extensions.pop(key, None)
        else:
            extensions[key] = deepcopy(value)


def keep_layout_zone_covers(saved_layout: Mapping[str, Any], document: Mapping[str, Any]) -> dict:
    """A whole-document save (the HTTP PUT of a layout) under the same rule as edit_zone: a copy of DOCUMENT whose
    zones keep their saved ceilings and roofs where they leave out extensions or leave them out of extensions; a
    changed one (or one on a new zone) raises ValueError. What validation refuses is left as sent for it to refuse:
    a document that is not an object, zones that are not a list, a zone that is not an object or has no string
    zoneId, and extensions sent that are not an object (null included: only a zone without the field keeps them)."""
    if not isinstance(document, Mapping):
        return document
    result = deepcopy(dict(document))
    zones = result.get("zones")
    if not isinstance(zones, list):
        return result
    saved = {zone["zoneId"]: zone for zone in saved_layout.get("zones") or []
             if isinstance(zone, Mapping) and isinstance(zone.get("zoneId"), str)}
    for zone in zones:
        if not isinstance(zone, dict) or not isinstance(zone.get("zoneId"), str):
            continue
        if "extensions" in zone and not isinstance(zone["extensions"], Mapping):
            continue
        put_back_zone_covers(zone, kept_zone_covers(saved.get(zone["zoneId"]), zone.get("extensions") or {}))
    return result


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
