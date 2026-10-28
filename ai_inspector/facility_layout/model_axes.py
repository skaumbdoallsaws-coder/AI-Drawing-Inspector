"""How model files sit in a layout (the 2026-10-21 display fix).

Layout coordinates are +X east, +Y up, +Z north, drawn on the plan with north up
and east to the right. That frame is left-handed, while model files (glTF) and
the three.js renderer are right-handed. Until 2026-10-21 the 3D view drew layout
numbers directly, so every layout appeared as a mirror image of its plan.

The fix keeps every layout number as it is and mirrors the 3D display instead.
For a vendor's CAD model to look true under that mirror, the model is mirrored
once across its own x = 0 plane on its way into a layout: a point the model file
puts at +x sits at -x in the layout's model space, and a side the file calls
east (+x) is the layout's west side of the unrotated model.

Authored model-space data stays written in the model file's own axes: library
footprints, bounds, connectors and support surfaces, and the reviewed sides and
seats in asset_orientation.py. This module converts it into the layout's model
space when the catalog is built (host.py), for records drawn from a model file.
Built-in prototype boxes have no file to stay true to and are left as authored.
The renderer mirrors loaded model files the same way (mirrorModelFileGeometry in
static/facility_layout_three_adapter.js).
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

_SWAPPED_SIDES = {"east": "west", "west": "east"}


def mirror_side(side: Any) -> Any:
    """East and west trade places; every other side name is unchanged."""
    return _SWAPPED_SIDES.get(side, side) if isinstance(side, str) else side


def mirror_heading(degrees: float) -> float:
    """A heading clockwise from north (+Z) toward east (+X), mirrored across x = 0."""
    value = (360.0 - float(degrees)) % 360.0
    return 0.0 if abs(value) < 1e-12 or abs(value - 360.0) < 1e-12 else value


def mirror_point(point: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(point)
    if "x" in result:
        result["x"] = -float(result["x"]) + 0.0
    return result


def mirror_polygon(points: Any) -> Any:
    """Mirror a polygon and reverse its vertex order so it keeps its winding."""
    if not isinstance(points, list):
        return points
    return [mirror_point(point) if isinstance(point, Mapping) else point for point in reversed(points)]


def mirror_surface(surface: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror a support surface and keep its frame a proper (right-handed) one.

    A point on the surface is origin + u * xAxis + v * zAxis. Its mirror image is
    origin' + u' * xAxis' + v * zAxis' with xAxis' = -mirror(xAxis), u' = -u, so the
    u range flips sign and the frame stays horizontal and orthonormal.
    """
    result = deepcopy(dict(surface))
    frame = result.get("localFrame")
    if isinstance(frame, Mapping):
        frame = dict(frame)
        for name in ("origin", "zAxis", "normal"):
            if isinstance(frame.get(name), Mapping):
                frame[name] = mirror_point(frame[name])
        x_axis = frame.get("xAxis")
        if isinstance(x_axis, Mapping):
            frame["xAxis"] = {
                key: (float(value) if key == "x" else -float(value) + 0.0) if key in ("x", "y", "z") else value
                for key, value in x_axis.items()
            }
        result["localFrame"] = frame
    bounds = result.get("bounds")
    if isinstance(bounds, Mapping) and {"minimumX", "maximumX"} <= set(bounds):
        bounds = dict(bounds)
        bounds["minimumX"], bounds["maximumX"] = -float(bounds["maximumX"]) + 0.0, -float(bounds["minimumX"]) + 0.0
        result["bounds"] = bounds
    return result


def mirror_semantics(semantics: Mapping[str, Any]) -> dict[str, Any]:
    """Reviewed sides trade east and west; a registered seat moves to its mirror image."""
    result = deepcopy(dict(semantics))
    sides = result.get("functionalSides")
    if isinstance(sides, Mapping):
        result["functionalSides"] = {
            role: ({**entry, "side": mirror_side(entry.get("side"))} if isinstance(entry, Mapping) else entry)
            for role, entry in sides.items()
        }
    seat = result.get("workstationSeat")
    if isinstance(seat, Mapping):
        seat = dict(seat)
        if isinstance(seat.get("localPosition"), Mapping):
            seat["localPosition"] = mirror_point(seat["localPosition"])
        if isinstance(seat.get("facingDegrees"), (int, float)) and not isinstance(seat.get("facingDegrees"), bool):
            seat["facingDegrees"] = mirror_heading(seat["facingDegrees"])
        result["workstationSeat"] = seat
    return result


def has_model_file(record: Mapping[str, Any]) -> bool:
    """Only records drawn from a model file are mirrored; prototype boxes are authored in layout axes."""
    return bool(record.get("privateLocalVisual"))


def _mirror_connector(connector: Any) -> Any:
    if not isinstance(connector, Mapping):
        return connector
    result = dict(connector)
    for name in ("position", "facing"):
        if isinstance(result.get(name), Mapping):
            result[name] = mirror_point(result[name])
    return result


def mirror_catalog_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a catalog record with its model-space data in the layout's model space.

    Apply exactly once, where the catalog is built. The record keeps its
    assetDefinitionRevision: the revision names the authored definition, and the
    conversion is the same for every definition drawn from a model file.
    """
    result = deepcopy(dict(record))
    if not has_model_file(result):
        return result
    definition = result.get("definition")
    if isinstance(definition, Mapping):
        definition = dict(definition)
        geometry = definition.get("geometry")
        if isinstance(geometry, Mapping):
            geometry = dict(geometry)
            if isinstance(geometry.get("footprintPolygons"), list):
                geometry["footprintPolygons"] = [mirror_polygon(polygon) for polygon in geometry["footprintPolygons"]]
            aabb = geometry.get("aabb")
            if isinstance(aabb, Mapping) and isinstance(aabb.get("minimum"), Mapping) \
                    and isinstance(aabb.get("maximum"), Mapping):
                minimum, maximum = dict(aabb["minimum"]), dict(aabb["maximum"])
                minimum["x"], maximum["x"] = -float(aabb["maximum"]["x"]) + 0.0, -float(aabb["minimum"]["x"]) + 0.0
                geometry["aabb"] = {**aabb, "minimum": minimum, "maximum": maximum}
            definition["geometry"] = geometry
        if isinstance(definition.get("connectors"), list):
            definition["connectors"] = [_mirror_connector(item) for item in definition["connectors"]]
        if isinstance(definition.get("supportSurfaces"), list):
            definition["supportSurfaces"] = [
                mirror_surface(surface) if isinstance(surface, Mapping) else surface
                for surface in definition["supportSurfaces"]]
        if isinstance(definition.get("facilitySemantics"), Mapping):
            definition["facilitySemantics"] = mirror_semantics(definition["facilitySemantics"])
        result["definition"] = definition
    if isinstance(result.get("supportSurfaces"), list):
        result["supportSurfaces"] = [
            mirror_surface(surface) if isinstance(surface, Mapping) else surface
            for surface in result["supportSurfaces"]]
    if isinstance(result.get("facilitySemantics"), Mapping):
        result["facilitySemantics"] = mirror_semantics(result["facilitySemantics"])
    return result
