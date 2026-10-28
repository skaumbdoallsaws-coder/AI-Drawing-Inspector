"""Model files are mirrored once across x = 0 on their way into a layout (2026-10-21)."""
import math

import pytest

from ai_inspector.facility_layout.asset_orientation import yaw_quaternion
from ai_inspector.facility_layout.model_axes import (
    mirror_catalog_record, mirror_heading, mirror_semantics, mirror_surface,
)
from ai_inspector.facility_layout.model_axes_migration import _yaw_degrees, migrate_layout
from ai_inspector.facility_layout.spatial import _rotate_vector


def _surface(heading=30.0):
    h = math.radians(heading)
    return {
        "surfaceId": "top", "label": "Top", "allowedSides": ["above"], "evidenceStatus": "derived",
        "localFrame": {"origin": {"x": 0.3, "y": 0.75, "z": -0.1},
                       "xAxis": {"x": math.cos(h), "y": 0.0, "z": -math.sin(h)},
                       "zAxis": {"x": math.sin(h), "y": 0.0, "z": math.cos(h)},
                       "normal": {"x": 0.0, "y": 1.0, "z": 0.0}},
        "bounds": {"minimumX": -0.2, "maximumX": 0.6, "minimumZ": -0.3, "maximumZ": 0.25},
    }


def _point(surface, u, v):
    frame = surface["localFrame"]
    return tuple(frame["origin"][a] + u * frame["xAxis"][a] + v * frame["zAxis"][a] for a in "xyz")


def test_a_mirrored_surface_is_the_mirror_image_and_keeps_a_proper_frame():
    surface = _surface()
    mirrored = mirror_surface(surface)
    frame = mirrored["localFrame"]
    x_axis, z_axis = frame["xAxis"], frame["zAxis"]
    # The validator's frame rules: horizontal, orthonormal, z cross x points up.
    assert math.isclose(z_axis["z"] * x_axis["x"] - z_axis["x"] * x_axis["z"], 1.0)
    assert abs(x_axis["x"] * z_axis["x"] + x_axis["z"] * z_axis["z"]) < 1e-12
    # attachTo's rule: xAxis = (cos h, -sin h) for the surface heading h.
    heading = math.atan2(z_axis["x"], z_axis["z"])
    assert math.isclose(x_axis["x"], math.cos(heading)) and math.isclose(x_axis["z"], -math.sin(heading))
    bounds = surface["bounds"]
    for u in (bounds["minimumX"], bounds["maximumX"]):
        for v in (bounds["minimumZ"], bounds["maximumZ"]):
            x, y, z = _point(surface, u, v)
            assert all(math.isclose(a, b, abs_tol=1e-12)
                       for a, b in zip(_point(mirrored, -u, v), (-x, y, z)))
    assert mirrored["bounds"]["minimumX"] == -0.6 and mirrored["bounds"]["maximumX"] == 0.2


def test_sides_trade_east_and_west_and_a_seat_moves_to_its_mirror_image():
    semantics = {"functionalSides": {"front": {"side": "east", "evidenceStatus": "inferred"},
                                     "rear": {"side": "west", "evidenceStatus": "inferred"},
                                     "operator": {"side": "north", "evidenceStatus": "inferred"}},
                 "workstationSeat": {"localPosition": {"x": 0.25, "z": 0.25}, "facingDegrees": 225}}
    mirrored = mirror_semantics(semantics)
    assert [mirrored["functionalSides"][r]["side"] for r in ("front", "rear", "operator")] == ["west", "east", "north"]
    assert mirrored["workstationSeat"] == {"localPosition": {"x": -0.25, "z": 0.25}, "facingDegrees": 135.0}
    assert semantics["functionalSides"]["front"]["side"] == "east"
    assert [mirror_heading(h) for h in (0, 90, 180, 270)] == [0.0, 270.0, 180.0, 90.0]


def test_only_records_drawn_from_a_model_file_are_mirrored():
    record = {"assetId": "a", "assetDefinitionRevision": "r1", "privateLocalVisual": {"url": "x.glb"},
              "definition": {"geometry": {"footprintPolygons": [[{"x": 0.1, "z": 0}, {"x": 0.5, "z": 0}, {"x": 0.5, "z": 1}]],
                                          "aabb": {"minimum": {"x": -0.2, "y": 0, "z": -1}, "maximum": {"x": 0.6, "y": 1, "z": 1}}},
                             "connectors": [{"connectorId": "out", "position": {"x": 0.4, "y": 0, "z": 0},
                                             "facing": {"x": 1.0, "y": 0, "z": 0}}],
                             "supportSurfaces": [_surface()]},
              "supportSurfaces": [_surface()],
              "facilitySemantics": {"functionalSides": {"front": {"side": "east"}}}}
    mirrored = mirror_catalog_record(record)
    assert mirrored["assetDefinitionRevision"] == "r1"
    assert mirrored["definition"]["geometry"]["footprintPolygons"] == [[{"x": -0.5, "z": 1}, {"x": -0.5, "z": 0}, {"x": -0.1, "z": 0}]]
    assert mirrored["definition"]["geometry"]["aabb"]["minimum"]["x"] == -0.6
    assert mirrored["definition"]["connectors"][0]["facing"]["x"] == -1.0
    assert mirrored["supportSurfaces"][0]["bounds"]["minimumX"] == -0.6
    assert mirrored["facilitySemantics"]["functionalSides"]["front"]["side"] == "west"
    prototype = {key: value for key, value in record.items() if key != "privateLocalVisual"}
    assert mirror_catalog_record(prototype) == prototype


REGISTRY = {
    "rack": ("rev-rack", {"functionalSides": {"front": {"side": "east"}}}),
    "cubicle": ("rev-cub", {"functionalSides": {"front": {"side": "north"}},
                            "workstationSeat": {"localPosition": {"x": 0.25, "z": 0.25}, "facingDegrees": 225}}),
    "chair": ("rev-chair", {"functionalSides": {"front": {"side": "north"}}}),
}


def _place(pid, asset, x, z, yaw, **extra):
    return {"placementId": pid, "assetId": asset, "assetDefinitionRevision": REGISTRY[asset][0] if asset in REGISTRY else "r",
            "transform": {"position": {"x": x, "y": 0.0, "z": z}, "quaternion": yaw_quaternion(yaw), "scale": 1}, **extra}


def test_migration_turns_east_west_fronts_and_reseats_chairs_and_moves_attachments():
    desk_yaw = 30.0
    seat = _rotate_vector((0.25, 0.0, 0.25), tuple(yaw_quaternion(desk_yaw)[k] for k in "xyzw"))
    layout = {"placements": [
        _place("p-rack", "rack", 5, 5, 90),
        _place("p-desk", "cubicle", 10, 10, desk_yaw),
        _place("p-chair", "chair", 10 + seat[0], 10 + seat[2], desk_yaw + 225),
        _place("p-loose-chair", "chair", 2, 2, 0),
        _place("p-monitor", "monitor", 0, 0, 0, snapRelationship={
            "family": "surface_attachment", "supportPlacementId": "p-desk", "surfaceId": "top",
            "surfaceSource": "asset_definition", "localPosition": {"x": 0.3, "z": -0.1},
            "localRotationDegrees": 30.0}),
        _place("p-box", "monitor", 4.6, 4.8, 90, snapRelationship={
            "family": "surface_attachment", "supportPlacementId": "p-rack", "surfaceId": "derived-top",
            "surfaceSource": "derived_aabb", "localPosition": {"x": 0.2, "z": -0.4},
            "localRotationDegrees": 0.0}),
    ], "extensions": {"facilityEquipmentDecals": {"version": 1, "decals": [{
        "decalId": "edecal-1", "placementId": "p-rack", "anchor": {
            "position": {"x": 0.4, "y": 1.0, "z": 0.1}, "normal": {"x": 1.0, "y": 0, "z": 0}, "rotationDegrees": 15}}]}}}
    migrated, report = migrate_layout(layout, REGISTRY)
    by_id = {p["placementId"]: p for p in migrated["placements"]}
    assert report == {"turned": 1, "seated": 1, "attachments": 1, "derivedAttachments": 1, "equipmentDecals": 1}
    # The rack turns in place: same spot, front still where it faced.
    assert by_id["p-rack"]["transform"]["position"] == {"x": 5, "y": 0.0, "z": 5}
    assert math.isclose(_yaw_degrees(by_id["p-rack"]["transform"]["quaternion"]) % 360, 270.0)
    # The seated chair moves to the mirrored seat; the loose chair stays put.
    q = tuple(yaw_quaternion(desk_yaw)[k] for k in "xyzw")
    mirrored_seat = _rotate_vector((-0.25, 0.0, 0.25), q)
    chair = by_id["p-chair"]["transform"]
    assert math.isclose(chair["position"]["x"], 10 + mirrored_seat[0]) and math.isclose(chair["position"]["z"], 10 + mirrored_seat[2])
    assert math.isclose(_yaw_degrees(chair["quaternion"]) % 360, (desk_yaw + 135) % 360)
    assert by_id["p-loose-chair"]["transform"] == layout["placements"][3]["transform"]
    # The attachment sits where the validator expects it on the mirrored surface.
    monitor = by_id["p-monitor"]
    relationship = monitor["snapRelationship"]
    assert relationship["localPosition"] == {"x": -0.3, "z": -0.1} and relationship["localRotationDegrees"] == -30.0
    offset = _rotate_vector((-0.3, 0.0, -0.1), q)
    assert math.isclose(monitor["transform"]["position"]["x"], 10 + offset[0])
    assert math.isclose(monitor["transform"]["position"]["z"], 10 + offset[2])
    assert math.isclose(_yaw_degrees(monitor["transform"]["quaternion"]), desk_yaw - 30.0)
    # The item on the turned rack's derived top keeps its place and stays consistent with the rack.
    box = by_id["p-box"]
    assert box["transform"]["position"] == {"x": 4.6, "y": 0.0, "z": 4.8}
    rack_q = tuple(by_id["p-rack"]["transform"]["quaternion"][k] for k in "xyzw")
    local = box["snapRelationship"]["localPosition"]
    world = _rotate_vector((local["x"], 0.0, local["z"]), rack_q)
    assert math.isclose(5 + world[0], 4.6, abs_tol=1e-9) and math.isclose(5 + world[2], 4.8, abs_tol=1e-9)
    yaw_delta = (_yaw_degrees(box["transform"]["quaternion"]) - _yaw_degrees(by_id["p-rack"]["transform"]["quaternion"])
                 - box["snapRelationship"]["localRotationDegrees"])
    assert abs((yaw_delta + 180) % 360 - 180) < 1e-9
    # Decals move to the mirrored spot.
    anchor = migrated["extensions"]["facilityEquipmentDecals"]["decals"][0]["anchor"]
    assert anchor == {"position": {"x": -0.4, "y": 1.0, "z": 0.1}, "normal": {"x": -1.0, "y": 0, "z": 0}, "rotationDegrees": -15.0}
    # The input is untouched.
    assert layout["placements"][0]["transform"]["quaternion"] == yaw_quaternion(90)


def test_migration_refuses_placement_face_artworks():
    layout = {"placements": [], "extensions": {"facilityDecals": {"version": 1, "artworks": [
        {"artworkId": "a", "target": {"placementId": "p", "face": "positive_x"}}]}}}
    with pytest.raises(ValueError, match="Placement-face artworks"):
        migrate_layout(layout, REGISTRY)
