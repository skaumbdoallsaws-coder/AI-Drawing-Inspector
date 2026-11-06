"""FP2 and FP3 of the floor-plan import (docs/facility-floor-plan-import-plan.md, sections 7, 8 and 11): walls, rooms,
the outline and doors converted from a drawing's layers. Expected numbers are worked out by hand from the fixtures' documented
coordinates (tests/floor_plan_dxf_fixtures.py), never from the converter itself."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import time

import pytest

from ai_inspector.facility_layout import floor_plan_conversion as conversion
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import default_plan_settings
from ai_inspector.facility_layout.perimeter_walls import compile_perimeter_walls
from ai_inspector.facility_layout.validate import validate_layout

IMPORT_ID = "fpi-" + "a" * 32
ROOT = Path(__file__).resolve().parents[1]


def layout():
    value = json.loads((ROOT / "tests/fixtures/facility_layout/empty_cell.json").read_text())
    value.setdefault("extensions", {})["facilityPlan"] = default_plan_settings()  # 40 m x 30 m
    return value


def reference(roles, *, translate=(5.0, 5.0), rotation=0.0, scale=1.0, origin=(0.0, 0.0)):
    return {"referenceId": "fp-main",
            "alignment": {"sourceOrigin": {"u": origin[0], "v": origin[1]}, "metersPerDrawingUnit": scale,
                          "rotationDegrees": rotation, "translationMeters": {"x": translate[0], "z": translate[1]}},
            "layers": [{"layerId": layer, "visible": True, "role": role} for layer, role in roles.items()]}


def drawing(*entities, layers=("L1", "L2", "L3", "L4")):
    return {"origin": [0.0, 0.0], "layers": [{"layerId": layer, "name": f"layer {layer}"} for layer in layers],
            "entities": list(entities)}


def line(entity, layer, a, b):
    return {"id": entity, "layer": layer, "type": "LINE", "closed": False, "points": [list(a), list(b)]}


def poly(entity, layer, points, closed=True, kind="LWPOLYLINE"):
    return {"id": entity, "layer": layer, "type": kind, "closed": closed, "points": [list(p) for p in points]}


def arc(entity, layer, center, radius, start, end, steps=8):
    """An arc as the reader stores it: points on the true curve from START to END degrees."""
    angles = [math.radians(start + (end - start) * index / steps) for index in range(steps + 1)]
    return {"id": entity, "layer": layer, "type": "ARC", "closed": False,
            "points": [[center[0] + radius * math.cos(t), center[1] + radius * math.sin(t)] for t in angles]}


def text(entity, layer, at, value):
    return {"id": entity, "layer": layer, "type": "TEXT", "at": list(at), "text": value, "height": 0.3,
            "rotation": 0.0, "mirrored": False}


WALLS = {"walls": {"heightMeters": 3}}


def convert(geometry, roles, settings=None, *, doc=None, **placement):
    return conversion.convert(geometry, reference(roles, **placement), doc if doc is not None else layout(),
                              conversion.normalize_settings(settings or {}), import_id=IMPORT_ID)


def xz(row, key):
    return (row[key]["x"], row[key]["z"])


def segments(result, state=None):
    return sorted((xz(row, "start"), xz(row, "end"), row["thicknessMeters"]) for row in result["walls"]
                  if state is None or row["state"] == state)


def near(a, b, tolerance=1e-9):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


# ---------------------------------------------------------------------------------------------------------------
# Settings.


def test_settings_are_closed_and_checked():
    assert conversion.normalize_settings(None) == {"walls": None, "rooms": None, "outline": None, "doors": None,
                                                   "columns": None, "excluded": []}
    assert conversion.normalize_settings({"columns": {"heightMeters": 6}})["columns"] == {"heightMeters": 6.0}
    assert conversion.normalize_settings({"columns": {}})["columns"] == {"heightMeters": None}
    assert conversion.normalize_settings({"excluded": ["col-fp-" + "4" * 16]})["excluded"] == ["col-fp-" + "4" * 16]
    assert conversion.normalize_settings({"doors": {"heightMeters": 2.1}})["doors"] == {"heightMeters": 2.1}
    assert conversion.normalize_settings({"doors": {}})["doors"] == {"heightMeters": None}
    assert conversion.normalize_settings({"excluded": ["dr-fp-" + "3" * 16]})["excluded"] == ["dr-fp-" + "3" * 16]
    value = conversion.normalize_settings({"walls": {"heightMeters": 3}, "outline": {"heightMeters": 6},
                                           "rooms": {"zoneType": "storage"}, "excluded": ["iw-fp-" + "1" * 16] * 2})
    assert value["walls"] == {"heightMeters": 3.0, "thicknessMeters": 0.2, "maxThicknessMeters": 0.6}
    assert value["outline"] == {"heightMeters": 6.0, "thicknessMeters": 0.3, "loop": None, "replace": False}
    assert value["rooms"] == {"zoneType": "storage", "types": {}}
    assert value["excluded"] == ["iw-fp-" + "1" * 16]
    # The heights may come later: the thicknesses and the outline chosen apply before them.
    early = conversion.normalize_settings({"walls": {"maxThicknessMeters": 1}, "outline": {"loop": "ol-fp-" + "2" * 16}})
    assert early["walls"] == {"heightMeters": None, "thicknessMeters": 0.2, "maxThicknessMeters": 1.0}
    assert early["outline"] == {"heightMeters": None, "thicknessMeters": 0.3, "loop": "ol-fp-" + "2" * 16,
                                "replace": False}
    for bad in ({"walls": {"heightMeters": 0.2}}, {"walls": {"heightMeters": 3, "color": "#fff"}},
                {"walls": {"heightMeters": True}}, {"walls": {"heightMeters": float("nan")}},
                {"walls": {"heightMeters": 3, "thicknessMeters": 2.5}}, {"rooms": {"zoneType": "room"}},
                {"rooms": {"types": {"zn-fp-" + "1" * 16: "office"}}}, {"rooms": {"types": {"zone-1": "storage"}}},
                {"outline": {"heightMeters": 6, "replace": "yes"}}, {"outline": {"heightMeters": 6, "loop": "x"}},
                {"excluded": ["pl-1"]}, {"excluded": "iw-fp-" + "1" * 16}, {"other": 1}, [],
                {"doors": {"heightMeters": 0.2}}, {"doors": {"widthMeters": 1}}, {"doors": 2.1},
                {"columns": {"heightMeters": 31}}, {"columns": {"color": "#fff"}}, {"excluded": ["col-1"]}):
        with pytest.raises(conversion.ConversionSettingsError):
            conversion.normalize_settings(bad)


def test_zone_types_are_the_layout_schema_s_own():
    schema = json.loads((ROOT / "static/contracts/facility-layout-schema-v1.json").read_text(encoding="utf-8"))
    assert list(conversion.ZONE_TYPES) == schema["$defs"]["zone"]["properties"]["zoneType"]["enum"]


# ---------------------------------------------------------------------------------------------------------------
# Fixture 1, the asymmetric factory, read from a real DXF.


@pytest.fixture(scope="module")
def factory_geometry(tmp_path_factory):
    pytest.importorskip("ezdxf")
    from ai_inspector.facility_layout import floor_plan_reader as reader
    from tests import floor_plan_dxf_fixtures as fixtures
    folder = tmp_path_factory.mktemp("fp2")
    out = {}
    for unit in ("meters", "millimeters", "feet"):
        out[unit] = reader.read_dxf(str(fixtures.factory(folder, unit=unit)))
    return out


def factory_roles(geometry):
    by_name = {layer["name"]: layer["layerId"] for layer in geometry["layers"]}
    roles = {"A-WALL-EXT": "perimeter", "A-WALL": "wall_faces", "A-AREA": "room_boundary", "S-COLS": "column",
             "A-DOOR": "door", "A-TEXT": "text"}
    return {by_name[name]: role for name, role in roles.items()}


FACTORY_SETTINGS = {"walls": {"heightMeters": 3}, "rooms": {"zoneType": "workcell"}, "outline": {"heightMeters": 6}}


def test_the_factory_converts_to_hand_worked_walls_room_and_outline(factory_geometry):
    geometry = factory_geometry["meters"]
    result = convert(geometry, factory_roles(geometry), FACTORY_SETTINGS)
    # The partition: faces at x = 10 and 10.2, moved by (5, 5). The door swing (hinged at the jamb (10.2, 4), 1.2 m,
    # shut against the jamb at y = 5.2) joins its two pieces into one wall with the door's opening, 4 to 5.2 m along.
    assert segments(result) == [((15.1, 5.0), (15.1, 15.0), 0.2)]
    (partition,) = result["walls"]
    assert (partition["state"], partition["label"], partition["from"], partition["lengthMeters"]) == (
        "new", "Drawing wall 1", "faces", 10.0)
    assert partition["openings"] == [{"startMeters": 4.0, "endMeters": 5.2}]
    (door,) = result["doors"]
    assert {key: door[key] for key in ("kind", "widthMeters", "at", "wall", "wallLabel", "state", "label")} == {
        "kind": "single", "widthMeters": 1.2, "at": {"x": 15.1, "z": 9.6}, "wall": partition["candidateId"],
        "wallLabel": "Drawing wall 1", "state": "new", "label": "Drawing door 1"}
    # The 4 m x 5 m room, named by the text inside it.
    (room,) = result["rooms"]
    assert room["boundary"] == [{"x": 25.0, "z": 17.0}, {"x": 29.0, "z": 17.0}, {"x": 29.0, "z": 22.0},
                                {"x": 25.0, "z": 22.0}]
    assert (room["areaSquareMeters"], room["label"], room["labelFrom"], room["zoneType"], room["state"]) == (
        20.0, "Office", "text", "workcell", "new")
    # The outline, a 30 m x 20 m loop.
    (outline,) = result["outlines"]
    assert outline["boundary"] == [{"x": 5.0, "z": 5.0}, {"x": 35.0, "z": 5.0}, {"x": 35.0, "z": 25.0},
                                   {"x": 5.0, "z": 25.0}]
    assert (outline["from"], outline["thicknessMeters"], outline["state"]) == ("line", 0.3, "new")
    # The jambs and the end line close the wall ends; the round column waits for its height.
    assert result["unconvertedCounts"] == {"wall_end": 3}
    (column,) = result["columns"]
    assert {key: column[key] for key in ("shape", "center", "diameterMeters", "state", "reason", "label")} == {
        "shape": "circle", "center": {"x": 22.5, "z": 11.5}, "diameterMeters": 0.5, "state": "waiting",
        "reason": "column_settings", "label": "Drawing column 1"}
    assert result["summary"]["columns"] == {"waiting": 1}
    assert [op["op"] for op in result["operations"]] == ["set_perimeter_walls", "upsert_interior_wall", "add_zone"]
    assert result["summary"]["blocked"] is None and result["summary"]["doors"] == {"new": 1}
    wall = result["operations"][1]["wall"]
    assert wall == {"wallId": partition["candidateId"], "label": "Drawing wall 1",
                    "start": {"x": 15.1, "z": 5.0}, "end": {"x": 15.1, "z": 15.0}, "heightMeters": 3.0,
                    "thicknessMeters": 0.2, "baseElevation": 0.0, "color": "#45484b",
                    "openings": [{"startMeters": 4.0, "endMeters": 5.2}]}


def test_applying_the_factory_keeps_everything_else_and_converting_again_adds_nothing(factory_geometry):
    geometry = factory_geometry["meters"]
    roles = factory_roles(geometry)
    before = layout()
    result = convert(geometry, roles, FACTORY_SETTINGS, doc=before)
    after = apply_facility_layout_operations(deepcopy(before), result["operations"])["document"]
    validate_layout(after)
    walls = after["extensions"]["facilityInteriorWalls"]["walls"]
    assert [wall["wallId"] for wall in walls] == [row["candidateId"] for row in result["walls"]]
    assert [zone["zoneId"] for zone in after["zones"]] == [result["rooms"][0]["candidateId"]]
    assert after["extensions"]["facilityPerimeterWalls"]["settings"]["boundarySource"] == "polygon"
    for key in ("placements", "routes", "utilityNetworks", "processBindings", "sourceShellRef", "coordinateFrame"):
        assert after[key] == before[key], key
    assert after["extensions"]["facilityPlan"] == before["extensions"]["facilityPlan"]
    again = convert(geometry, roles, FACTORY_SETTINGS, doc=after)
    assert [row["state"] for row in again["walls"] + again["rooms"] + again["outlines"] + again["doors"]] == [
        "there"] * 4
    assert again["operations"] == [] and again["summary"]["blocked"]["code"] == "nothing_to_add"


def test_converting_reads_the_drawing_and_never_changes_it(factory_geometry):
    # The server keeps the last drawings parsed and converts them again after every change of settings.
    geometry = factory_geometry["meters"]
    before = json.dumps(geometry, sort_keys=True)
    convert(geometry, factory_roles(geometry), FACTORY_SETTINGS)
    convert(geometry, factory_roles(geometry), FACTORY_SETTINGS, translate=(25.0, 0.0), rotation=90.0)
    assert json.dumps(geometry, sort_keys=True) == before


@pytest.mark.parametrize("unit, scale", [("millimeters", 0.001), ("feet", 0.3048)])
def test_the_same_drawing_in_other_units_converts_to_the_same_meters(factory_geometry, unit, scale):
    meters = convert(factory_geometry["meters"], factory_roles(factory_geometry["meters"]), FACTORY_SETTINGS)
    other = convert(factory_geometry[unit], factory_roles(factory_geometry[unit]), FACTORY_SETTINGS, scale=scale)
    for kind in ("walls", "rooms", "outlines", "doors"):
        assert [row["candidateId"] for row in other[kind]] == [row["candidateId"] for row in meters[kind]], kind
    assert other["operations"] == meters["operations"]


def test_a_turned_drawing_lands_where_its_corners_project(factory_geometry):
    geometry = factory_geometry["meters"]
    # 90 degrees: x = 25 - v, z = u (the drawing's x axis runs along the plan's z).
    result = convert(geometry, factory_roles(geometry), FACTORY_SETTINGS, translate=(25.0, 0.0), rotation=90.0)
    # The partition (u = 10.1, v 0..10, its door v 4..5.2) runs along x at z = 10.1, from x = 15 to 25; the door is
    # x = 21 down to 19.8, so 4.8 to 6 m along it.
    assert segments(result) == [((15.0, 10.1), (25.0, 10.1), 0.2)]
    assert result["walls"][0]["openings"] == [{"startMeters": 4.8, "endMeters": 6.0}]
    (room,) = result["rooms"]  # corners (20,12) (24,12) (24,17) (20,17), counter-clockwise from the lowest
    assert room["boundary"] == [{"x": 8.0, "z": 20.0}, {"x": 13.0, "z": 20.0}, {"x": 13.0, "z": 24.0},
                                {"x": 8.0, "z": 24.0}]
    (outline,) = result["outlines"]
    assert outline["boundary"] == [{"x": 5.0, "z": 0.0}, {"x": 25.0, "z": 0.0}, {"x": 25.0, "z": 30.0},
                                   {"x": 5.0, "z": 30.0}]
    assert result["summary"]["blocked"] is None


# ---------------------------------------------------------------------------------------------------------------
# Walls from faces and centerlines (synthetic drawings, moved by (5, 5)).


FACES = {"L1": "wall_faces"}
CENTER = {"L1": "wall_centerline"}


def test_an_l_drawn_with_faces_fills_its_corner():
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (0.2, 0.2), (10, 0.2)),
                       line("e3", "L1", (0, 0), (0, 8)), line("e4", "L1", (0.2, 0.2), (0.2, 8)))
    result = convert(geometry, FACES, WALLS)
    assert segments(result, "new") == [((5.0, 5.1), (15.0, 5.1), 0.2), ((5.1, 5.0), (5.1, 13.0), 0.2)]
    assert result["unconverted"] == []


def test_a_t_drawn_with_faces_runs_through_and_the_branch_reaches_its_centerline():
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (0, 0.2), (4.9, 0.2)),
                       line("e3", "L1", (5.1, 0.2), (10, 0.2)), line("e4", "L1", (4.9, 0.2), (4.9, 5)),
                       line("e5", "L1", (5.1, 0.2), (5.1, 5)))
    result = convert(geometry, FACES, WALLS)
    assert segments(result, "new") == [((5.0, 5.1), (15.0, 5.1), 0.2), ((10.0, 5.1), (10.0, 10.0), 0.2)]


def test_a_door_gap_stays_open_even_when_a_wall_ends_at_its_jamb():
    # Two pieces of one wall with a 1.2 m door; a cross wall ends at the door's edge.
    geometry = drawing(line("e1", "L1", (0, 0), (4, 0)), line("e2", "L1", (5.2, 0), (10, 0)),
                       line("e3", "L1", (4, 0), (4, 6)))
    result = convert(geometry, CENTER, WALLS)
    # The cross wall and the left piece close their corner (an L); the 1.2 m gap is not filled.
    assert segments(result, "new") == [((5.0, 5.0), (9.1, 5.0), 0.2), ((9.0, 4.9), (9.0, 11.0), 0.2),
                                       ((10.2, 5.0), (15.0, 5.0), 0.2)]


def test_three_parallel_lines_are_ambiguous_and_never_guessed():
    geometry = drawing(line("e1", "L1", (0, 0), (0, 5)), line("e2", "L1", (0.1, 0), (0.1, 5)),
                       line("e3", "L1", (0.2, 0), (0.2, 5)))
    result = convert(geometry, FACES, WALLS)
    assert {row["reason"] for row in result["walls"]} == {"ambiguous_faces"}
    assert result["operations"] == [] and result["summary"]["blocked"]["code"] == "nothing_to_add"


def box(prefix, x0, x1, z0=0.0, z1=0.2):
    """A box drawn as four lines: bottom, right, top, left."""
    corners = ((x0, z0), (x1, z0), (x1, z1), (x0, z1))
    return [line(f"{prefix}{side}", "L1", corners[side], corners[(side + 1) % 4]) for side in range(4)]


WIDE = {"walls": {"heightMeters": 3, "maxThicknessMeters": 1}}


def test_jamb_lines_across_a_doorway_never_pair_into_a_wall():
    # Faces 0.25 m apart, broken by a 0.9 m doorway with its jamb lines, and a door hinged at (4, 0.25). With walls up
    # to 1 m thick the two jambs are parallel lines close enough to pair: that wall would fill the doorway.
    geometry = drawing(line("f1", "L1", (0, 0), (4, 0)), line("f2", "L1", (4.9, 0), (10, 0)),
                       line("f3", "L1", (0, 0.25), (4, 0.25)), line("f4", "L1", (4.9, 0.25), (10, 0.25)),
                       line("j1", "L1", (4, 0), (4, 0.25)), line("j2", "L1", (4.9, 0), (4.9, 0.25)),
                       arc("d1", "L2", (4, 0.25), 0.9, 0, 90))
    result = convert(geometry, {"L1": "wall_faces", "L2": "door"}, WIDE)
    (wall,) = result["walls"]
    assert (xz(wall, "start"), xz(wall, "end"), wall["thicknessMeters"], wall["openings"], wall["state"]) == (
        (5.0, 5.125), (15.0, 5.125), 0.25, [{"startMeters": 4.0, "endMeters": 4.9}], "new")
    assert [(row["kind"], row["widthMeters"], row["state"]) for row in result["doors"]] == [("single", 0.9, "new")]
    assert result["unconvertedCounts"] == {"wall_end": 2}


def test_a_wall_s_end_line_never_pairs_with_a_wall_beyond_it():
    # A wall closed by an end line 0.5 m short of a cross wall: the end line and the cross wall's near face are close
    # enough to pair, and that face, pairing on both of its sides, would leave the cross wall ambiguous.
    geometry = drawing(line("e1", "L1", (0, 0), (5, 0)), line("e2", "L1", (0, 0.2), (5, 0.2)),
                       line("e3", "L1", (5, 0), (5, 0.2)),
                       line("e4", "L1", (5.5, -3), (5.5, 3)), line("e5", "L1", (5.7, -3), (5.7, 3)))
    result = convert(geometry, FACES, WALLS)
    assert segments(result) == [((5.0, 5.1), (10.0, 5.1), 0.2), ((10.6, 2.0), (10.6, 8.0), 0.2)]
    assert {row["state"] for row in result["walls"]} == {"new"}
    assert result["unconvertedCounts"] == {"wall_end": 1}


def test_a_short_box_is_one_wall_along_its_long_sides_and_the_gap_to_the_next_stays_open():
    # Two piers 0.6 m x 0.2 m drawn as boxes 0.3 m apart. With walls up to 1 m thick each box's ends pair across it,
    # and the facing ends of the two pair across the gap between them.
    result = convert(drawing(*box("a", 0, 0.6), *box("b", 0.9, 1.5)), FACES, WIDE)
    assert segments(result) == [((5.0, 5.1), (5.6, 5.1), 0.2), ((5.9, 5.1), (6.5, 5.1), 0.2)]
    assert {row["state"] for row in result["walls"]} == {"new"}
    assert result["unconvertedCounts"] == {"wall_end": 4}


def test_a_square_pier_drawn_with_four_faces_is_one_wall_whichever_way_round():
    # A 0.4 m square: each pair of its sides closes the other pair's ends, and neither is longer. One of them is the
    # wall, the one along x, in any order and either way along each line; the other two sides are its ends.
    sides = box("p", 0, 0.4, 0, 0.4)  # bottom, right, top, left
    flipped = [line(row["id"], "L1", row["points"][1], row["points"][0]) for row in sides]
    for order in (sides, sides[::-1], [sides[2], sides[0], sides[3], sides[1]], flipped):
        result = convert(drawing(*order), FACES, WALLS)
        assert segments(result) == [((5.0, 5.2), (5.4, 5.2), 0.4)], [row["id"] for row in order]
        assert [row["state"] for row in result["walls"]] == ["new"]
        assert result["unconvertedCounts"] == {"wall_end": 2}



def test_a_square_pier_turned_to_any_angle_is_one_wall_whichever_way_round():
    # Turned, its sides' lengths and gaps differ in their last digits: still one wall, the same in any order, along
    # the sides at the smaller angle from x (before, turned 5 degrees about (0, 0) or 95 about (0.2, 0.2), both pairs
    # were kept: two walls on one spot).
    for angle, (cx, cy) in ((5, (0, 0)), (95, (0.2, 0.2)), (30, (2, 3)), (45, (2, 3)), (80, (2, 3)), (135, (2, 3))):
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        corners = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in ((-0.2, -0.2), (0.2, -0.2), (0.2, 0.2),
                                                                         (-0.2, 0.2))]
        sides = [line(f"p{k}", "L1", corners[k], corners[(k + 1) % 4]) for k in range(4)]
        flipped = [line(row["id"], "L1", row["points"][1], row["points"][0]) for row in sides]
        results = [convert(drawing(*order), FACES, WALLS)
                   for order in (sides, sides[::-1], [sides[2], sides[0], sides[3], sides[1]], flipped)]
        assert all((result["walls"], result["operations"]) == (results[0]["walls"], results[0]["operations"])
                   for result in results), angle
        (wall,) = results[0]["walls"]
        assert (wall["state"], wall["thicknessMeters"], wall["lengthMeters"]) == ("new", 0.4, 0.4), angle
        assert results[0]["unconvertedCounts"] == {"wall_end": 2} and len(results[0]["operations"]) == 1
        (x1, z1), (x2, z2) = xz(wall, "start"), xz(wall, "end")
        along = math.degrees(math.atan2(z2 - z1, x2 - x1)) % 180
        expected = min(angle % 180, (angle + 90) % 180)
        assert min(abs(along - expected), 180 - abs(along - expected)) < 0.05, (angle, along)



def test_a_box_a_little_longer_than_wide_is_one_wall_along_its_longer_sides_turned_or_not():
    # Only rounding makes a turned pair "no longer than wide": a pier 0.400 m by 0.405 m, or a stub 0.203 m long and
    # 0.2 m thick, is one wall along its longer sides however it is turned and however it is drawn (with 5 mm of
    # slack, the pier turned 1 degree about (2, 3) lost both pairs and became no wall at all, and the stub turned 90
    # degrees came out 0.203 m thick and 0.2 m long).
    for size_x, size_y in ((0.4, 0.405), (0.405, 0.4), (0.2, 0.203), (0.203, 0.2)):
        wide, long = min(size_x, size_y), max(size_x, size_y)
        for angle in (0, 1, 5, 37, 89, 90, 135):
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            for cx, cy in ((2, 3), (0.2, 0.2)):
                corners = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in (
                    (-size_x / 2, -size_y / 2), (size_x / 2, -size_y / 2), (size_x / 2, size_y / 2),
                    (-size_x / 2, size_y / 2))]
                for form, entities, left in (
                        ("polyline", [poly("p1", "L1", corners)], {}),
                        ("lines", [line(f"b{k}", "L1", corners[k], corners[(k + 1) % 4]) for k in range(4)],
                         {"wall_end": 2})):
                    case = (size_x, size_y, angle, (cx, cy), form)
                    result = convert(drawing(*entities), FACES, WALLS)
                    assert len(result["walls"]) == 1, (case, result["unconvertedCounts"])
                    (wall,) = result["walls"]
                    assert (wall["state"], wall["thicknessMeters"], wall["lengthMeters"]) == ("new", wide, long), case
                    assert result["unconvertedCounts"] == left, case
                    (x1, z1), (x2, z2) = xz(wall, "start"), xz(wall, "end")
                    along = math.degrees(math.atan2(z2 - z1, x2 - x1)) % 180
                    expected = (angle + (0 if size_x > size_y else 90)) % 180
                    assert min(abs(along - expected), 180 - abs(along - expected)) < 0.05, (case, along)


def test_an_end_line_about_as_long_as_its_gap_to_a_cross_wall_beyond_is_not_a_wall():
    # A 0.2 m wall's end line, 0.196 to 0.202 m short of a cross wall's face, is that wall's end and nothing more: no
    # stub fills the gap (allowing only rounding there made a 0.198 m by 0.2 m wall of the end line and the face).
    for gap in (0.196, 0.198, 0.2, 0.202):
        for turned in (False, True):
            def at(u, v):
                return (v, u) if turned else (u, v)
            result = convert(drawing(
                line("w1", "L1", at(0, 0), at(5, 0)), line("w2", "L1", at(0, 0.2), at(5, 0.2)),
                line("cap", "L1", at(5, 0), at(5, 0.2)),
                line("x1", "L1", at(5 + gap, -2), at(5 + gap, 2)),
                line("x2", "L1", at(5 + gap + 0.2, -2), at(5 + gap + 0.2, 2))), FACES, WALLS)
            walls = sorted((row["state"], row["thicknessMeters"], row["lengthMeters"]) for row in result["walls"])
            assert walls == [("new", 0.2, 4.0), ("new", 0.2, 5.0)], (gap, turned, walls)
            assert result["unconvertedCounts"] == {"wall_end": 1}, (gap, turned)


def test_a_box_whose_short_sides_are_too_short_to_pair_is_still_a_box_at_a_wall_end():
    # A 0.102 m by 0.098 m box drawn closed at the end of a 0.102 m wall: its 0.098 m sides overlap too little to pair,
    # yet it is a box, so only rounding counts as "no longer than wide" and it is one wall along its longer sides; the
    # wall runs into it (to its far side) as it would into any wall it meets. Taken for an end line and a wall beyond
    # it (5 mm of slack), it was dropped and its lines left over.
    for angle in (0, 30, 90, 135):
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

        def at(x, y):
            return (2 + x * c - y * s, 3 + x * s + y * c)
        box = [at(0, 0), at(0.102, 0), at(0.102, 0.098), at(0, 0.098)]
        wall = [line("w1", "L1", at(0, -4), at(0, 0)), line("w2", "L1", at(0.102, -4), at(0.102, 0))]
        for form, entities, left in (
                ("polyline", [poly("box", "L1", box)], {}),
                ("lines", [line(f"b{k}", "L1", box[k], box[(k + 1) % 4]) for k in range(4)], {"wall_end": 2})):
            result = convert(drawing(*wall, *entities), FACES, WALLS)
            walls = sorted((row["state"], row["thicknessMeters"], row["lengthMeters"]) for row in result["walls"])
            assert walls == [("new", 0.098, 0.102), ("new", 0.102, 4.098)], (angle, form, walls)
            assert result["unconvertedCounts"] == left, (angle, form)


def test_lines_close_to_a_face_but_not_copies_of_it_pair_as_they_did():
    # Only the same line drawn again is folded into one. A line within 5 mm of a face but turned, or a few mm
    # shorter, is a line of its own: the wall and its id are the ones the converter gave before copies were folded.
    slanted = drawing(line("e1", "L1", (0, 0), (0.15, 0)), line("e2", "L1", (0, 0.2), (0.15, 0.2)),
                      line("e3", "L1", (0, -0.004), (0.15, 0.004)))
    result = convert(slanted, FACES, WALLS)
    assert segments(result) == [((5.0, 5.1), (5.15, 5.1), 0.2)]
    assert [row["candidateId"] for row in result["walls"]] == ["iw-fp-1fab0d508f7704a5"]
    assert result["unconvertedCounts"] == {"no_matching_face": 1}
    shorter = drawing(line("e1", "L1", (0, 0), (10.004, 0)), line("e2", "L1", (0, 0.2), (10.004, 0.2)),
                      line("e3", "L1", (0, 0), (10, 0)))
    result = convert(shorter, FACES, WALLS)
    assert segments(result) == [((5.0, 5.1), (15.004, 5.1), 0.2)]
    (wall,) = result["walls"]
    assert (wall["candidateId"], wall["sources"]) == ("iw-fp-b6d4e3280435910a", ["e1", "e2", "e3"])
    assert result["unconverted"] == []

def test_the_largest_thickness_applies_before_the_height_is_given():
    # Faces 0.9 m apart pair only when the largest thickness allows it; without a height the wall waits for one.
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (0, 0.9), (10, 0.9)))
    assert convert(geometry, FACES, {"walls": {}})["walls"] == []
    wide = convert(geometry, FACES, {"walls": {"maxThicknessMeters": 1}})
    assert [(row["thicknessMeters"], row["state"], row["reason"]) for row in wide["walls"]] == [
        (0.9, "waiting", "wall_settings")]
    assert wide["operations"] == []


def test_centerlines_close_an_l_and_duplicates_are_one_wall():
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (10, 0), (0, 0)),
                       line("e3", "L1", (0, 0), (0, 8)))
    result = convert(geometry, CENTER, WALLS)
    assert segments(result, "new") == [((4.9, 5.0), (15.0, 5.0), 0.2), ((5.0, 4.9), (5.0, 13.0), 0.2)]


def test_faces_given_the_centerline_role_are_refused_as_overlapping():
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (0, 0.15), (10, 0.15)))
    result = convert(geometry, CENTER, WALLS)
    assert {row["reason"] for row in result["walls"]} == {"overlapping_walls"}


def test_curves_on_a_wall_layer_stay_drawing():
    arc = [(5 + 3 * math.cos(math.radians(a)), 3 * math.sin(math.radians(a))) for a in range(0, 91, 3)]
    bend = [(0, 10), (5, 10), (10, 11)]  # a 11 degree kink: part of a curve, not two walls
    geometry = drawing(poly("e1", "L1", arc, closed=False), poly("e2", "L1", bend, closed=False),
                       {"id": "e3", "layer": "L1", "type": "ARC", "closed": False, "points": [[0, 0], [1, 1]]},
                       line("e4", "L1", (20, 0), (20, 5)))
    result = convert(geometry, CENTER, WALLS)
    assert result["unconvertedCounts"] == {"curve": 3}
    assert segments(result, "new") == [((25.0, 5.0), (25.0, 10.0), 0.2)]


def test_a_polyline_of_straight_runs_gives_one_wall_per_run():
    geometry = drawing(poly("e1", "L1", [(0, 0), (4, 0), (8, 0), (8, 6)], closed=False))
    result = convert(geometry, CENTER, WALLS)
    assert segments(result, "new") == [((5.0, 5.0), (13.1, 5.0), 0.2), ((13.0, 4.9), (13.0, 11.0), 0.2)]


def test_unpaired_lines_are_listed_with_their_reason():
    geometry = drawing(line("e1", "L1", (0, 0), (0, 5)), line("e2", "L1", (0.2, 0), (0.2, 5)),
                       line("e3", "L1", (0, 5), (0.2, 5)), line("e4", "L1", (10, 0), (12, 3)))
    result = convert(geometry, FACES, WALLS)
    assert sorted((row["entityId"], row["reason"]) for row in result["unconverted"]) == [
        ("e3", "wall_end"), ("e4", "no_matching_face")]


def test_walls_wait_for_their_height_and_never_land_on_a_wall_already_there():
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)))
    waiting = convert(geometry, CENTER)
    assert [(row["state"], row["reason"]) for row in waiting["walls"]] == [("waiting", "wall_settings")]
    assert waiting["summary"]["blocked"]["code"] == "nothing_to_add"
    doc = apply_facility_layout_operations(layout(), [{"op": "upsert_interior_wall", "wall": {
        "wallId": "iw-office", "label": "Office", "start": {"x": 7, "z": 5}, "end": {"x": 12, "z": 5},
        "heightMeters": 3, "thicknessMeters": 0.2, "baseElevation": 0, "color": "#45484b", "openings": []}}])["document"]
    result = convert(geometry, CENTER, WALLS, doc=doc)
    assert [(row["state"], row["reason"]) for row in result["walls"]] == [("refused", "wall_there")]


def test_a_wall_beside_one_already_there_is_there_while_they_overlap_and_new_once_they_only_touch():
    # Two 0.2 m walls side by side overlap while their center lines are less than 0.1 + 0.1 m apart; an overlap
    # within TOLERANCE (5 mm) is walls drawn touching.
    doc = apply_facility_layout_operations(layout(), [{"op": "upsert_interior_wall", "wall": {
        "wallId": "iw-office", "label": "Office", "start": {"x": 7, "z": 5}, "end": {"x": 12, "z": 5},
        "heightMeters": 3, "thicknessMeters": 0.2, "baseElevation": 0, "color": "#45484b", "openings": []}}])["document"]
    for apart, expected in ((0.15, ("refused", "wall_there")), (0.19, ("refused", "wall_there")),
                            (0.197, ("new", None)), (0.2, ("new", None))):
        result = convert(drawing(line("e1", "L1", (0, apart), (10, apart))), CENTER, WALLS, doc=doc)
        assert [(row["state"], row["reason"]) for row in result["walls"]] == [expected], apart


def test_walls_outside_the_plan_are_refused_and_excluded_ones_left_out():
    geometry = drawing(line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (0, 30), (10, 30)))
    result = convert(geometry, CENTER, WALLS)
    rows = {row["start"]["z"]: row for row in result["walls"]}
    assert (rows[35.0]["state"], rows[35.0]["reason"]) == ("refused", "outside_plan")
    excluded = convert(geometry, CENTER, dict(WALLS, excluded=[rows[5.0]["candidateId"]]))
    assert [row["state"] for row in excluded["walls"]] == ["excluded", "refused"]
    assert excluded["operations"] == []


def test_more_walls_than_a_plan_holds_block_the_whole_conversion():
    geometry = drawing(*[line(f"e{i}", "L1", (0.5 + i * 0.25, 0), (0.5 + i * 0.25, 4)) for i in range(129)])
    result = convert(geometry, CENTER, {"walls": {"heightMeters": 3, "thicknessMeters": 0.05}}, translate=(1, 1))
    assert result["summary"]["walls"] == {"new": 129}
    assert result["summary"]["blocked"]["code"] == "too_many_walls"
    assert result["operations"] == []


def test_changes_larger_than_a_review_holds_block_the_whole_conversion(factory_geometry, monkeypatch):
    from ai_inspector.facility_layout.floor_plan_proposals import PACKAGE_LIMITS
    assert PACKAGE_LIMITS == (conversion.MAX_OPERATIONS, conversion.MAX_PACKAGE_BYTES)
    geometry = factory_geometry["meters"]
    monkeypatch.setattr(conversion, "MAX_PACKAGE_BYTES", 500)
    result = convert(geometry, factory_roles(geometry), FACTORY_SETTINGS)
    assert result["summary"]["operations"] == 3
    assert result["summary"]["blocked"]["code"] == "changes_too_large"


def test_the_result_does_not_depend_on_the_drawing_s_entity_order():
    entities = [line("e1", "L1", (0, 0), (10, 0)), line("e2", "L1", (0, 0.2), (4.9, 0.2)),
                line("e3", "L1", (5.1, 0.2), (10, 0.2)), line("e4", "L1", (4.9, 0.2), (4.9, 5)),
                line("e5", "L1", (5.1, 0.2), (5.1, 5)), line("e6", "L1", (0, 0), (0, 5)),
                line("e7", "L1", (0.2, 0.2), (0.2, 5))]
    forward = convert(drawing(*entities), FACES, WALLS)
    backward = convert(drawing(*reversed(entities)), FACES, WALLS)
    assert forward["walls"] == backward["walls"] and forward["operations"] == backward["operations"]


def test_thousands_of_face_lines_convert_in_seconds():
    entities = []
    for row in range(30):
        for column in range(45):
            x, z = column * 0.8, row * 1.0
            entities += [line(f"a{row}-{column}", "L1", (x, z), (x + 0.6, z)),
                         line(f"b{row}-{column}", "L1", (x, z + 0.2), (x + 0.6, z + 0.2))]
    started = time.perf_counter()
    result = convert(drawing(*entities), FACES, WALLS, translate=(0.5, 0.5))
    assert time.perf_counter() - started < 20
    assert result["summary"]["walls"] == {"new": 1350}
    assert result["summary"]["blocked"]["code"] == "too_many_walls"


def test_copies_of_face_lines_pair_once_and_the_wall_keeps_every_copy_as_a_source():
    # 200 copies of each face, half of one face drawn the other way: one wall (before, 40,000 pairs, refused as too
    # large to convert).
    copies = []
    for k in range(200):
        a, b = ((0, 0), (10, 0)) if k % 2 else ((10, 0), (0, 0))
        copies += [line(f"a{k:03d}", "L1", a, b), line(f"b{k:03d}", "L1", (0, 0.2), (10, 0.2))]
    started = time.perf_counter()
    result = convert(drawing(*copies), FACES, WALLS)
    assert time.perf_counter() - started < 5
    assert segments(result) == [((5.0, 5.1), (15.0, 5.1), 0.2)]
    (wall,) = result["walls"]
    assert wall["state"] == "new"
    assert wall["sources"] == sorted(row["id"] for row in copies)[:conversion.MAX_SOURCES]
    assert result["unconverted"] == []
    # A copy of a line that pairs with nothing is listed for each entity drawn.
    lone = convert(drawing(line("c1", "L1", (0, 5), (4, 5)), line("c2", "L1", (4, 5), (0, 5))), FACES, WALLS)
    assert lone["walls"] == [] and [row["entityId"] for row in lone["unconverted"]] == ["c1", "c2"]
    assert lone["unconvertedCounts"] == {"no_matching_face": 2}


def test_a_line_kilometers_long_and_a_room_of_thousands_of_corners_convert_in_seconds():
    # The work follows a line's length, not the box around it, and a loop's straight points go in one pass.
    long_wall = (line("e1", "L1", (0, 0), (40000, 30000)), line("e2", "L1", (0.25, 0), (40000.25, 30000)))
    teeth = [(0.5 * k, 0.25 * (k % 2)) for k in range(4001)]  # 4000 corners along the bottom
    top = [(2000 - 0.5 * k, 10) for k in range(4001)]  # then 4000 points on one straight line along the top
    started = time.perf_counter()
    result = convert(drawing(*long_wall, poly("r1", "L2", teeth + top)), {"L1": "wall_faces", "L2": "room_boundary"},
                     {"walls": {"heightMeters": 3}, "rooms": {"zoneType": "storage"}})
    assert time.perf_counter() - started < 5
    assert [(row["thicknessMeters"], row["reason"]) for row in result["walls"]] == [(0.15, "outside_plan")]
    assert result["unconvertedCounts"] == {"too_many_vertices": 1}


def test_an_outline_with_too_many_corners_is_never_searched_for_doors():
    teeth = [(0.05 * k, 0.025 * (k % 2)) for k in range(3001)]  # 3000 corners along the bottom
    swings = [arc(f"d{k}", "L2", (1 + 0.05 * k, 20), 1.0, 0, 90) for k in range(1500)]  # hinged on the top edge
    started = time.perf_counter()
    result = convert(drawing(poly("o1", "L3", teeth + [(150, 20), (0, 20)]), *swings),
                     {"L3": "perimeter", "L2": "door"}, {"outline": {"heightMeters": 6}})
    assert time.perf_counter() - started < 5
    assert [(row["state"], row["reason"]) for row in result["outlines"]] == [("refused", "too_many_corners")]
    assert result["doors"] == [] and result["unconvertedCounts"] == {"door_unmatched": 1500}


def test_lines_closing_one_end_of_many_pairs_do_not_slow_the_box_check():
    # 30 lines a hair apart facing 30 more 0.2 m away, 200 lines a hair apart across their tops and a wall's two faces
    # meeting them: every line closing a pair's top end was tried against every other as a box's two short sides
    # (half a minute). A box needs one at each end.
    lines = [line(f"a{i}", "L1", (0.000005 * i, 0), (0.000005 * i, 0.203)) for i in range(30)]
    lines += [line(f"b{i}", "L1", (0.2 + 0.000005 * i, 0), (0.2 + 0.000005 * i, 0.203)) for i in range(30)]
    lines += [line(f"h{k}", "L1", (0, 0.203 + 0.000005 * k), (0.2, 0.203 + 0.000005 * k)) for k in range(200)]
    lines += [line("x1", "L1", (-2, 0), (0, 0)), line("x2", "L1", (-2, 0.203), (0, 0.203))]
    started = time.perf_counter()
    result = convert(drawing(*lines), FACES, WALLS)
    assert time.perf_counter() - started < 5
    assert [(row["state"], row["thicknessMeters"], row["lengthMeters"]) for row in result["walls"]] == [
        ("new", 0.203, 2.0)]
    assert result["unconvertedCounts"] == {"no_matching_face": 230, "wall_end": 30}


def test_each_try_at_a_box_is_charged_to_the_work_budget(monkeypatch):
    # A box 0.2 m wide and 0.203 m long with five lines closing each end: 25 tries at its two short sides.
    lines = [line("a", "L1", (0, 0), (0, 0.203)), line("b", "L1", (0.2, 0), (0.2, 0.203))]
    lines += [line(f"h{k}", "L1", (0, 0.203 + 0.0005 * k), (0.2, 0.203 + 0.0005 * k)) for k in range(5)]
    lines += [line(f"g{k}", "L1", (0, -0.0005 * k), (0.2, -0.0005 * k)) for k in range(5)]
    monkeypatch.setattr(conversion, "BOX_WORK", conversion.MAX_WORK)
    with pytest.raises(conversion.ConversionTooLargeError, match="too large"):
        convert(drawing(*lines), FACES, WALLS)
    monkeypatch.setattr(conversion, "BOX_WORK", 0)
    result = convert(drawing(*lines), FACES, WALLS)
    assert [(row["state"], row["thicknessMeters"], row["lengthMeters"]) for row in result["walls"]] == [
        ("new", 0.2, 0.203)]


def test_a_conversion_past_its_limits_is_refused_as_too_large(monkeypatch):
    hatched = drawing(*(line(f"e{k}", "L1", (0, 0.01 * k), (10, 0.01 * k)) for k in range(300)))  # 1 cm apart
    stacked = drawing(*(line(f"e{k}", "L1", (0, 0), (10, 0)) for k in range(300)))
    monkeypatch.setattr(conversion, "MAX_WORK", 50_000)
    with pytest.raises(conversion.ConversionTooLargeError, match="too large"):
        convert(hatched, FACES, WALLS)
    monkeypatch.setattr(conversion, "MAX_PIECES", 100)
    with pytest.raises(conversion.ConversionTooLargeError, match="100 straight pieces"):
        convert(stacked, FACES, WALLS)
    monkeypatch.setattr(conversion, "MAX_DOOR_SYMBOLS", 2)
    swings = drawing(*BROKEN_WALL, *(arc(f"d{k}", "L2", (4, 0), 1.0, 0, 90) for k in range(3)))
    with pytest.raises(conversion.ConversionTooLargeError, match="door"):
        convert(swings, DOORS, WALLS)


# ---------------------------------------------------------------------------------------------------------------
# Rooms.


ROOMS = {"L2": "room_boundary", "L3": "text"}


def square(entity, x, z, size, layer="L2", **options):
    return poly(entity, layer, [(x, z), (x + size, z), (x + size, z + size), (x, z + size)], **options)


def test_room_outlines_are_checked_and_named_by_one_text_inside():
    geometry = drawing(
        square("r1", 0, 0, 4), text("t1", "L3", (2, 2), "Office"),
        poly("r2", "L2", [(10, 0), (10, 4), (14, 4), (14, 0)]),  # clockwise
        text("t2", "L3", (11, 1), "Store"), text("t3", "L3", (13, 3), "Stores"),
        poly("r3", "L2", [(20, 0), (24, 0), (24, 4), (20, 4), (20, 0.004)], closed=False),  # a 4 mm gap closes
        poly("r4", "L2", [(0, 10), (4, 10), (0, 14), (4, 14)]),  # a bow tie
        poly("r5", "L2", [(10, 10), (14, 10), (14, 14)], closed=False),  # open
        square("r6", 20, 10, 0.5))  # 0.25 m2: too small
    result = convert(geometry, ROOMS, {"rooms": {"zoneType": "storage"}})
    rooms = {row["sources"][0]: row for row in result["rooms"]}
    assert (rooms["r1"]["label"], rooms["r1"]["labelFrom"]) == ("Office", "text")
    assert (rooms["r2"]["labelFrom"], rooms["r2"]["label"]) == ("several", "Drawing room 2")
    assert rooms["r2"]["boundary"][0] == {"x": 15.0, "z": 5.0} and rooms["r2"]["boundary"][1] == {"x": 19.0, "z": 5.0}
    assert rooms["r3"]["state"] == "new" and len(rooms["r3"]["boundary"]) == 4
    assert {row["entityId"]: row["reason"] for row in result["unconverted"]} == {
        "r4": "crosses_itself", "r5": "open_outline", "r6": "too_small"}
    assert all(row["zoneType"] == "storage" and row["state"] == "new" for row in result["rooms"])


def test_nested_and_repeated_rooms_are_resolved_explicitly():
    geometry = drawing(square("big", 0, 0, 10), square("inner", 2, 2, 3), square("copy", 2, 2, 3))
    result = convert(geometry, ROOMS, {"rooms": {"zoneType": "workcell"}})
    rows = {row["sources"][0]: row for row in result["rooms"]}
    assert (rows["big"]["state"], rows["big"]["reason"]) == ("refused", "holds_rooms")
    assert rows["inner"]["state"] == "new"
    assert (rows["copy"]["state"], rows["copy"]["reason"]) == ("refused", "duplicate")
    kept = convert(geometry, ROOMS, {"rooms": {"zoneType": "workcell"}, "excluded": [rows["inner"]["candidateId"]]})
    states = {row["sources"][0]: row["state"] for row in kept["rooms"]}
    assert states == {"big": "new", "inner": "excluded", "copy": "refused"}


def test_copies_of_a_room_are_searched_once_and_each_label_is_read_once(monkeypatch):
    # 100 copies of one room around 1,000 labels: the copies are duplicates before any search, and a label is read
    # once however many rooms hold it (before, every copy read every label: 100,000 reads).
    reads = []
    real = conversion._label
    monkeypatch.setattr(conversion, "_label", lambda value: reads.append(value) or real(value))
    labels = [text(f"t{k}", "L3", (1 + 0.008 * k, 5), f"Bay {k}") for k in range(1000)]
    started = time.perf_counter()
    result = convert(drawing(*(square(f"r{k}", 0, 0, 10) for k in range(100)), *labels), ROOMS,
                     {"rooms": {"zoneType": "storage"}})
    assert time.perf_counter() - started < 5
    states = [(row["state"], row["reason"]) for row in result["rooms"]]
    assert states.count(("refused", "duplicate")) == 99 and states.count(("new", None)) == 1
    assert len(reads) == 1000
    assert {row["labelFrom"] for row in result["rooms"]} == {"several"}


def test_room_searches_are_charged_to_the_conversion_s_work(monkeypatch):
    # 40 rooms one inside the next around 2,000 labels: each room's search meets every label, 80,000 in all. A
    # drawing like that is refused as too large once that passes the conversion's work, never searched for minutes.
    labels = [text(f"t{k}", "L3", (20 + 0.001 * k, 15), f"Bay {k}") for k in range(2000)]
    rooms = [square(f"r{k}", 21 - (1.5 + 0.1 * k), 15 - (1.5 + 0.1 * k), 2 * (1.5 + 0.1 * k)) for k in range(40)]
    geometry = drawing(*rooms, *labels)
    settings = {"rooms": {"zoneType": "storage"}}
    monkeypatch.setattr(conversion, "MAX_WORK", 60_000)
    with pytest.raises(conversion.ConversionTooLargeError, match="too large"):
        convert(geometry, ROOMS, settings, translate=(0, 0))
    monkeypatch.setattr(conversion, "MAX_WORK", 100_000)
    result = convert(geometry, ROOMS, settings, translate=(0, 0))
    states = [(row["state"], row["reason"]) for row in result["rooms"]]
    assert states.count(("new", None)) == 1 and states.count(("refused", "holds_rooms")) == 39


def test_only_rooms_that_can_still_be_added_hold_a_room_and_zones_already_there_say_so():
    geometry = drawing(square("big", 0, 0, 10), square("inner", 2, 2, 3))
    settings = {"rooms": {"zoneType": "workcell"}}
    first = convert(geometry, ROOMS, settings)
    # The inner room added: the outer one now holds a zone already on the plan, which no review can leave out.
    doc = apply_facility_layout_operations(layout(), first["operations"])["document"]
    again = convert(geometry, ROOMS, settings, doc=doc)
    assert {row["sources"][0]: (row["state"], row["reason"]) for row in again["rooms"]} == {
        "big": ("refused", "holds_zones"), "inner": ("there", None)}
    assert again["rooms"][0]["message"] == conversion.MESSAGES["holds_zones"]
    # A room inside that cannot be added either holds nothing: the outer one gets its own reason.
    outside = drawing(square("big", 30, 0, 10), square("inner", 33, 2, 3))  # past the plan's 40 m width
    assert {row["sources"][0]: (row["state"], row["reason"]) for row in convert(outside, ROOMS, settings)["rooms"]} \
        == {"big": ("refused", "outside_plan"), "inner": ("refused", "outside_plan")}
    # Three deep: each room waits on the ones inside it until they are left out.
    nested = drawing(square("a", 0, 0, 12), square("b", 1, 1, 8), square("c", 2, 2, 3))
    ids = {row["sources"][0]: row["candidateId"] for row in convert(nested, ROOMS, settings)["rooms"]}
    for excluded, expected in (([], {"a": "refused", "b": "refused", "c": "new"}),
                               (["c"], {"a": "refused", "b": "new", "c": "excluded"}),
                               (["b", "c"], {"a": "new", "b": "excluded", "c": "excluded"})):
        rows = convert(nested, ROOMS, dict(settings, excluded=[ids[name] for name in excluded]))["rooms"]
        assert {row["sources"][0]: row["state"] for row in rows} == expected, excluded


def test_rooms_wait_for_a_zone_type_and_a_zone_already_there_is_kept():
    geometry = drawing(square("r1", 0, 0, 4), square("r2", 10, 0, 4))
    waiting = convert(geometry, ROOMS)
    assert {(row["state"], row["reason"]) for row in waiting["rooms"]} == {("waiting", "zone_type")}
    first = waiting["rooms"][0]["candidateId"]
    typed = convert(geometry, ROOMS, {"rooms": {"types": {first: "inspection"}}})
    assert [(row["zoneType"], row["state"]) for row in typed["rooms"]] == [("inspection", "new"), (None, "waiting")]
    doc = apply_facility_layout_operations(layout(), [{"op": "add_zone", "zone": {
        "zoneId": "zn-hand", "zoneType": "storage", "label": "Hand drawn", "floorElevation": 0, "anchors": [],
        "evidence": [], "boundary": [{"x": 5.05, "z": 5}, {"x": 9, "z": 5}, {"x": 9, "z": 9}, {"x": 5.05, "z": 9}]}}])
    result = convert(geometry, ROOMS, {"rooms": {"zoneType": "storage"}}, doc=doc["document"])
    assert [(row["state"], row["reason"]) for row in result["rooms"]] == [("refused", "zone_there"), ("new", None)]


# ---------------------------------------------------------------------------------------------------------------
# The outline.


OUTLINE = {"L4": "perimeter"}


def test_two_nested_loops_one_distance_apart_are_the_outer_walls_faces():
    geometry = drawing(square("out", 0, 0, 20, layer="L4"), square("in", 0.3, 0.3, 19.4, layer="L4"))
    result = convert(geometry, OUTLINE, {"outline": {"heightMeters": 6}})
    (row,) = result["outlines"]
    assert (row["from"], row["thicknessMeters"], row["state"]) == ("faces", 0.3, "new")
    assert row["boundary"] == [{"x": 5.15, "z": 5.15}, {"x": 24.85, "z": 5.15}, {"x": 24.85, "z": 24.85},
                               {"x": 5.15, "z": 24.85}]
    assert result["operations"] == [{"op": "set_perimeter_walls", "wallSettings": {
        "boundarySource": "polygon", "boundary": row["boundary"], "heightMeters": 6.0, "thicknessMeters": 0.3,
        "openings": []}}]


def test_several_outlines_wait_for_the_user_to_choose_one():
    geometry = drawing(square("a", 0, 0, 10, layer="L4"), square("b", 15, 0, 5, layer="L4"))
    result = convert(geometry, OUTLINE, {"outline": {"heightMeters": 6}})
    assert {(row["state"], row["reason"]) for row in result["outlines"]} == {("waiting", "choose_outline")}
    chosen = result["outlines"][1]["candidateId"]
    picked = convert(geometry, OUTLINE, {"outline": {"heightMeters": 6, "loop": chosen}})
    assert sorted(row["state"] for row in picked["outlines"]) == ["new", "refused"]
    # Chosen before the height is given: the choice stands and the chosen one waits for the height.
    early = convert(geometry, OUTLINE, {"outline": {"loop": chosen}})
    assert {row["candidateId"]: (row["state"], row["reason"]) for row in early["outlines"]} == {
        chosen: ("waiting", "outline_settings"), result["outlines"][0]["candidateId"]: ("refused", "other_outline")}
    assert early["operations"] == []


def test_an_outline_choice_that_names_none_of_the_outlines_chooses_none():
    geometry = drawing(square("a", 0, 0, 10, layer="L4"), square("b", 15, 0, 5, layer="L4"))
    result = convert(geometry, OUTLINE, {"outline": {"heightMeters": 6, "loop": "ol-fp-" + "9" * 16}})
    assert {(row["state"], row["reason"]) for row in result["outlines"]} == {("waiting", "choose_outline")}


def test_outer_walls_already_there_are_replaced_only_when_asked_and_the_review_says_what_goes():
    doc = layout()
    doc["extensions"]["facilityPerimeterWalls"] = compile_perimeter_walls(
        {"boundarySource": "plan", "heightMeters": 6, "thicknessMeters": 0.3,
         "openings": [{"edge": 0, "startMeters": 2, "endMeters": 6}], "interiorColor": "#aabbcc"}, doc)
    geometry = drawing(square("out", 0, 0, 20, layer="L4"))
    result = convert(geometry, OUTLINE, {"outline": {"heightMeters": 6}}, doc=doc)
    (row,) = result["outlines"]
    assert (row["state"], row["reason"]) == ("waiting", "replace_needed")
    assert "its 1 opening" in row["message"]
    assert row["replaces"] == {"boundarySource": "plan", "openings": 1, "exteriorFinish": False}
    replaced = convert(geometry, OUTLINE, {"outline": {"heightMeters": 6, "replace": True}}, doc=doc)
    assert replaced["outlines"][0]["state"] == "new"
    assert replaced["operations"][0]["wallSettings"]["interiorColor"] == "#aabbcc"


def test_a_column_waits_for_its_height_and_a_stray_door_line_stays_drawing():
    geometry = drawing(square("c1", 0, 0, 0.4, layer="L1"), line("d1", "L2", (0, 0), (1, 0)))
    result = convert(geometry, {"L1": "column", "L2": "door"})
    assert result["unconvertedCounts"] == {"door_part": 1}
    assert [(row["state"], row["reason"]) for row in result["columns"]] == [("waiting", "column_settings")]
    assert result["layers"] == {"L1": {"name": "layer L1", "role": "column"},
                                "L2": {"name": "layer L2", "role": "door"}}


# ---------------------------------------------------------------------------------------------------------------
# Doors (FP3). Walls are centerlines on L1 and door symbols on L2, moved by (5, 5) into the 40 m x 30 m plan.


DOORS = {"L1": "wall_centerline", "L2": "door"}
BROKEN_WALL = (line("e1", "L1", (0, 0), (4, 0)), line("e2", "L1", (5, 0), (10, 0)))  # a 1 m break, x = 4 to 5


def test_a_swing_in_a_wall_break_joins_the_wall_with_a_door_opening():
    # Hinged at either jamb and opening to either side, it is the same door: one wall from (5, 5) to (15, 5) with
    # a full-height opening 4 to 5 m along it.
    ids = set()
    for hinge, start, end in (((4, 0), 0, 90), ((4, 0), -90, 0), ((5, 0), 90, 180), ((5, 0), 180, 270)):
        result = convert(drawing(*BROKEN_WALL, arc("d1", "L2", hinge, 1.0, start, end)), DOORS, WALLS)
        (wall,) = result["walls"]
        assert (xz(wall, "start"), xz(wall, "end"), wall["openings"], wall["state"]) == (
            (5.0, 5.0), (15.0, 5.0), [{"startMeters": 4.0, "endMeters": 5.0}], "new"), (hinge, start)
        assert wall["sources"] == ["e1", "e2"]
        (door,) = result["doors"]
        assert {key: door[key] for key in ("kind", "widthMeters", "at", "wall", "outline", "state", "sources")} == {
            "kind": "single", "widthMeters": 1.0, "at": {"x": 9.5, "z": 5.0}, "wall": wall["candidateId"],
            "outline": None, "state": "new", "sources": ["d1"]}
        assert result["unconverted"] == []
        (operation,) = result["operations"]
        assert operation["wall"]["openings"] == [{"startMeters": 4.0, "endMeters": 5.0}]
        ids.add(door["candidateId"])
    assert len(ids) == 1
    # Applied, the wall keeps its opening; converting again finds the wall and its door there.
    doc = layout()
    after = apply_facility_layout_operations(deepcopy(doc), result["operations"])["document"]
    validate_layout(after)
    assert after["extensions"]["facilityInteriorWalls"]["walls"][0]["openings"] == [
        {"startMeters": 4.0, "endMeters": 5.0}]
    again = convert(drawing(*BROKEN_WALL, arc("d1", "L2", (4, 0), 1.0, 0, 90)), DOORS, WALLS, doc=after)
    assert [row["state"] for row in again["walls"] + again["doors"]] == ["there", "there"]


def test_a_door_drawn_as_one_polyline_reads_like_a_line_and_an_arc():
    # The leaf from the hinge (4, 0) to (4, 1), then the swing down to the jamb (5, 0), in one polyline.
    swing = arc("x", "L2", (4, 0), 1.0, 90, 0)["points"]
    geometry = drawing(*BROKEN_WALL, poly("p1", "L2", [(4, 0)] + swing, closed=False))
    result = convert(geometry, DOORS, WALLS)
    assert [row["openings"] for row in result["walls"]] == [[{"startMeters": 4.0, "endMeters": 5.0}]]
    assert [(row["kind"], row["sources"]) for row in result["doors"]] == [("single", ["p1"])]
    assert result["unconverted"] == []


def test_a_swing_drawn_in_steps_of_under_a_degree_is_a_door_like_the_arc():
    # A quarter circle in 176 steps of half a degree (as a drawing in millimeters may store its curves) is one
    # straight run by the one-degree rule; its points still make it a swing, with its leaf or without.
    swing = arc("x", "L2", (4, 0), 1.0, 90, 0, steps=176)["points"]
    for door in (poly("p1", "L2", [(4, 0)] + swing, closed=False), poly("p2", "L2", swing, closed=False)):
        result = convert(drawing(*BROKEN_WALL, door), DOORS, WALLS)
        assert [row["openings"] for row in result["walls"]] == [[{"startMeters": 4.0, "endMeters": 5.0}]], door["id"]
        assert [(row["kind"], row["sources"]) for row in result["doors"]] == [("single", [door["id"]])]
        assert result["unconverted"] == []


def test_two_half_swings_from_both_jambs_are_a_double_door_and_one_swinging_both_ways_is_one_door():
    double = drawing(line("e1", "L1", (0, 0), (4, 0)), line("e2", "L1", (6, 0), (10, 0)),
                     arc("d1", "L2", (4, 0), 1.0, 0, 90), arc("d2", "L2", (6, 0), 1.0, 90, 180))
    result = convert(double, DOORS, WALLS)
    assert [row["openings"] for row in result["walls"]] == [[{"startMeters": 4.0, "endMeters": 6.0}]]
    assert [(row["kind"], row["widthMeters"], row["at"], row["sources"]) for row in result["doors"]] == [
        ("double", 2.0, {"x": 10.0, "z": 5.0}, ["d1", "d2"])]
    both_ways = drawing(*BROKEN_WALL, arc("d1", "L2", (4, 0), 1.0, 0, 90), arc("d2", "L2", (4, 0), 1.0, -90, 0))
    result = convert(both_ways, DOORS, WALLS)
    assert [row["openings"] for row in result["walls"]] == [[{"startMeters": 4.0, "endMeters": 5.0}]]
    assert [(row["kind"], row["sources"]) for row in result["doors"]] == [("single", ["d1", "d2"])]


def test_swings_that_disagree_or_fit_two_breaks_leave_the_door_unclear_and_the_break_open():
    # A full-width swing at one jamb and a half-width one at the other.
    mixed = drawing(*BROKEN_WALL, arc("d1", "L2", (4, 0), 1.0, 0, 90), arc("d2", "L2", (5, 0), 0.5, 90, 180))
    result = convert(mixed, DOORS, WALLS)
    assert segments(result) == [((5.0, 5.0), (9.0, 5.0), 0.2), ((10.0, 5.0), (15.0, 5.0), 0.2)]
    assert [(row["kind"], row["state"], row["reason"], row["sources"]) for row in result["doors"]] == [
        ("unclear", "refused", "door_ambiguous", ["d1", "d2"])]
    # Two walls 0.28 m apart broken at the same place: a swing hinged between them fits both breaks.
    twin = drawing(*BROKEN_WALL, line("e3", "L1", (0, 0.28), (4, 0.28)), line("e4", "L1", (5, 0.28), (10, 0.28)),
                   arc("d1", "L2", (4, 0.14), 1.0, 0, 90))
    result = convert(twin, DOORS, WALLS)
    assert len(result["walls"]) == 4 and all(row["openings"] == [] for row in result["walls"])
    assert [(row["kind"], row["reason"]) for row in result["doors"]] == [("unclear", "door_ambiguous")] * 2


def test_an_excluded_door_keeps_the_break():
    geometry = drawing(*BROKEN_WALL, arc("d1", "L2", (4, 0), 1.0, 0, 90))
    door = convert(geometry, DOORS, WALLS)["doors"][0]["candidateId"]
    result = convert(geometry, DOORS, {**WALLS, "excluded": [door]})
    assert segments(result, "new") == [((5.0, 5.0), (9.0, 5.0), 0.2), ((10.0, 5.0), (15.0, 5.0), 0.2)]
    assert [(row["candidateId"], row["state"]) for row in result["doors"]] == [(door, "excluded")]
    assert result["unconverted"] == []
    # The wall left out instead: the door goes with it.
    wall = convert(geometry, DOORS, WALLS)["walls"][0]["candidateId"]
    result = convert(geometry, DOORS, {**WALLS, "excluded": [wall]})
    assert [(row["state"], row["reason"]) for row in result["walls"] + result["doors"]] == [
        ("excluded", None), ("refused", "door_host_left_out")]


def test_what_is_no_door_stays_drawing_with_its_reason():
    geometry = drawing(
        *BROKEN_WALL,
        arc("d1", "L2", (4, 0), 1.5, 0, 90),  # wider than the break
        arc("d2", "L2", (20, 10), 1.0, 0, 90),  # no wall near it
        arc("d3", "L2", (30, 10), 1.0, 0, 180),  # half a circle is no swing
        arc("d4", "L2", (30, 20), 1.0, 0, 270, steps=12),  # nor three quarters (its ends are a right angle apart)
        line("d5", "L2", (30, 25), (31, 25)))
    result = convert(geometry, DOORS, WALLS)
    assert segments(result) == [((5.0, 5.0), (9.0, 5.0), 0.2), ((10.0, 5.0), (15.0, 5.0), 0.2)]
    assert result["doors"] == []
    assert result["unconvertedCounts"] == {"door_part": 3, "door_unmatched": 2}
    assert {row["entityId"]: row["reason"] for row in result["unconverted"]} == {
        "d1": "door_unmatched", "d2": "door_unmatched", "d3": "door_part", "d4": "door_part", "d5": "door_part"}


OUTER = {"L3": "perimeter", "L2": "door"}


def outer_doors():
    """A 20 m x 15 m outline (layout (5, 5) to (25, 20); edge 0 runs along z = 5 from x = 5, edge 1 up x = 25 from
    z = 5). Edge 0: a 1 m door hinged at x = 8 with its leaf. Edge 1: a double door, two 1 m leaves hinged at y = 5 and
    y = 7 and shut at y = 6. Edge 2: a swing without its leaf."""
    return drawing(
        poly("o1", "L3", [(0, 0), (20, 0), (20, 15), (0, 15)]),
        arc("dA", "L2", (8, 0), 1.0, -90, 0), line("lA", "L2", (8, 0), (8, -1)),
        arc("dB1", "L2", (20, 5), 1.0, 0, 90), line("lB1", "L2", (20, 5), (21, 5)),
        arc("dB2", "L2", (20, 7), 1.0, -90, 0), line("lB2", "L2", (20, 7), (21, 7)),
        arc("dC", "L2", (10, 15), 1.0, 0, 90))


def test_outer_doors_need_their_leaf_and_wait_for_their_height():
    waiting = convert(outer_doors(), OUTER, {"outline": {"heightMeters": 6}})
    (outline,) = waiting["outlines"]
    assert (outline["state"], outline["reason"]) == ("waiting", "door_settings")
    assert [(row["edge"], row["kind"], row["widthMeters"], row["at"], row["state"], row["sources"])
            for row in waiting["doors"]] == [
        (0, "single", 1.0, {"x": 13.5, "z": 5.0}, "waiting", ["dA", "lA"]),
        (1, "double", 2.0, {"x": 25.0, "z": 11.0}, "waiting", ["dB1", "dB2", "lB1", "lB2"])]
    assert all(row["outline"] == outline["candidateId"] and row["wall"] is None for row in waiting["doors"])
    assert waiting["unconvertedCounts"] == {"door_leaf_missing": 1}
    assert waiting["unconverted"][0]["entityId"] == "dC"
    assert waiting["operations"] == []
    result = convert(outer_doors(), OUTER, {"outline": {"heightMeters": 6}, "doors": {"heightMeters": 2.1}})
    assert [row["state"] for row in result["outlines"] + result["doors"]] == ["new"] * 3
    (operation,) = result["operations"]
    assert operation["wallSettings"]["openings"] == [
        {"edge": 0, "startMeters": 8.0, "endMeters": 9.0, "heightMeters": 2.1},
        {"edge": 1, "startMeters": 5.0, "endMeters": 7.0, "heightMeters": 2.1}]
    after = apply_facility_layout_operations(deepcopy(layout()), result["operations"])["document"]
    validate_layout(after)
    assert len(after["extensions"]["facilityPerimeterWalls"]["settings"]["openings"]) == 2
    again = convert(outer_doors(), OUTER, {"outline": {"heightMeters": 6}, "doors": {"heightMeters": 2.1}},
                    doc=after)
    assert [row["state"] for row in again["outlines"] + again["doors"]] == ["there"] * 3
    # Doors left out: the outer walls are added without them, and with none kept no door height is needed.
    first, second = (row["candidateId"] for row in result["doors"])
    one = convert(outer_doors(), OUTER, {"outline": {"heightMeters": 6}, "doors": {"heightMeters": 2.1},
                                         "excluded": [first]})
    assert [opening["edge"] for opening in one["operations"][0]["wallSettings"]["openings"]] == [1]
    assert [row["state"] for row in one["doors"]] == ["excluded", "new"]
    none = convert(outer_doors(), OUTER, {"outline": {"heightMeters": 6}, "excluded": [first, second]})
    assert none["outlines"][0]["state"] == "new"
    assert none["operations"][0]["wallSettings"]["openings"] == []
    without = convert(outer_doors(), OUTER, {"outline": {"heightMeters": 6}, "excluded": [outline["candidateId"]]})
    assert {(row["state"], row["reason"]) for row in without["doors"]} == {("refused", "door_host_left_out")}
    # The order the drawing lists its entities in changes nothing.
    backward = drawing(*reversed(outer_doors()["entities"]))
    assert convert(backward, OUTER, {"outline": {"heightMeters": 6}, "doors": {"heightMeters": 2.1}}) == result


def test_an_outer_door_at_a_corner_stays_within_its_edge_once_rounded():
    # Edge 0 is 19.99996 m long and the door shuts at its far corner: rounded to 0.1 mm its end would be 20 m, past
    # the edge, which the outer walls refuse; it stops at the corner instead.
    end = 19.99996
    geometry = drawing(poly("o1", "L3", [(0, 0), (end, 0), (end, 15), (0, 15)]),
                       arc("d1", "L2", (end - 1, 0), 1.0, -90, 0), line("l1", "L2", (end - 1, 0), (end - 1, -1)))
    result = convert(geometry, OUTER, {"outline": {"heightMeters": 6}, "doors": {"heightMeters": 2.1}})
    (operation,) = result["operations"]
    assert operation["wallSettings"]["openings"] == [
        {"edge": 0, "startMeters": 19.0, "endMeters": end, "heightMeters": 2.1}]
    validate_layout(apply_facility_layout_operations(deepcopy(layout()), result["operations"])["document"])


def test_an_outer_door_drawn_twice_or_swinging_both_ways_is_one_door():
    outline = poly("o1", "L3", [(0, 0), (20, 0), (20, 15), (0, 15)])
    leaf = line("lA", "L2", (8, 0), (8, -1))
    twice = drawing(outline, arc("dA", "L2", (8, 0), 1.0, -90, 0), arc("dA2", "L2", (8, 0), 1.0, -90, 0), leaf)
    both = drawing(outline, arc("dA", "L2", (8, 0), 1.0, -90, 0), leaf,
                   arc("dB", "L2", (8, 0), 1.0, 90, 0), line("lB", "L2", (8, 0), (8, 1)))
    settings = {"outline": {"heightMeters": 6}, "doors": {"heightMeters": 2.1}}
    for geometry, sources in ((twice, ["dA", "dA2", "lA"]), (both, ["dA", "dB", "lA", "lB"])):
        result = convert(geometry, OUTER, settings)
        assert [(row["kind"], row["widthMeters"], row["sources"], row["state"]) for row in result["doors"]] == [
            ("single", 1.0, sources, "new")]
        (operation,) = result["operations"]
        assert operation["wallSettings"]["openings"] == [
            {"edge": 0, "startMeters": 8.0, "endMeters": 9.0, "heightMeters": 2.1}]
        validate_layout(apply_facility_layout_operations(deepcopy(layout()), result["operations"])["document"])
        assert result["unconverted"] == []
    # Swings that overlap without matching disagree: the door is unclear and stays drawing; the outline has no door.
    unclear = drawing(outline, arc("dA", "L2", (8, 0), 1.0, -90, 0), leaf,
                      arc("dC", "L2", (8, 0), 1.5, -90, 0), line("lC", "L2", (8, 0), (8, -1.5)))
    result = convert(unclear, OUTER, settings)
    assert result["doors"] == [] and [row["state"] for row in result["outlines"]] == ["new"]
    assert result["operations"][0]["wallSettings"]["openings"] == []
    assert {row["entityId"]: row["reason"] for row in result["unconverted"]} == {
        "dA": "door_overlap", "dC": "door_overlap", "lA": "door_part", "lC": "door_part"}


def test_every_reason_keeps_a_listed_row_past_the_listing_limit():
    # More curves than are listed, then a stray line on a column layer: its reason still has a row and a message.
    arcs = [{"id": f"a{index}", "layer": "L1", "type": "ARC", "closed": False,
             "points": [[index, 0], [index + 0.5, 0.5]]} for index in range(conversion.MAX_LISTED + 5)]
    result = convert(drawing(*arcs, line("c1", "L2", (0, 20), (0.4, 20))), {"L1": "wall_centerline", "L2": "column"})
    assert result["unconvertedCounts"] == {"curve": conversion.MAX_LISTED + 5, "column_shape": 1}
    reasons = [row["reason"] for row in result["unconverted"]]
    assert reasons.count("curve") == conversion.MAX_LISTED and reasons.count("column_shape") == 1
    column = next(row for row in result["unconverted"] if row["reason"] == "column_shape")
    assert (column["entityId"], column["message"]) == ("c1", conversion.MESSAGES["column_shape"])


def test_the_origin_binds_the_source_alignment_layers_settings_and_converter():
    settings = conversion.normalize_settings(FACTORY_SETTINGS)
    ref = reference(FACES)
    record = {"importId": IMPORT_ID, "sourceSha256": "1" * 64, "geometrySha256": "2" * 64}
    first = conversion.origin_for("fpc-x", ref, record, settings)
    moved = deepcopy(ref)
    moved["alignment"]["translationMeters"]["x"] = 6.0
    retyped = deepcopy(ref)
    retyped["layers"][0]["role"] = "wall_centerline"
    for other in (conversion.origin_for("fpc-x", moved, record, settings),
                  conversion.origin_for("fpc-x", retyped, record, settings),
                  conversion.origin_for("fpc-x", ref, record, conversion.normalize_settings(WALLS))):
        assert other != first
    assert first["converterVersion"] == conversion.CONVERTER_VERSION
    ids = {conversion.conversion_id(IMPORT_ID, ref, "fl-main", "r" * 64, settings),
           conversion.conversion_id(IMPORT_ID, moved, "fl-main", "r" * 64, settings),
           conversion.conversion_id(IMPORT_ID, ref, "fl-main", "s" * 64, settings)}
    assert len(ids) == 3


# ---------------------------------------------------------------------------------------------------------------
# Columns: on L1, moved by (5, 5) into the 40 m x 30 m plan.


COLUMNS = {"L1": "column"}
HEIGHT = {"columns": {"heightMeters": 6}}


def turned_box(entity, center, width, depth, degrees, start=0, reverse=False, layer="L1", **options):
    """A WIDTH x DEPTH box drawn as a closed polyline, its width along DEGREES (counterclockwise from +x), from corner
    START, either way round."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    corners = [(center[0] + x * c - z * s, center[1] + x * s + z * c)
               for x, z in ((-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2),
                            (-width / 2, depth / 2))]
    corners = corners[start:] + corners[:start]
    return poly(entity, layer, corners[::-1] if reverse else corners, **options)


def circle(entity, center, radius, steps=64, layer="L1", kind="CIRCLE"):
    return poly(entity, layer, [(center[0] + radius * math.cos(2 * math.pi * k / steps),
                                 center[1] + radius * math.sin(2 * math.pi * k / steps)) for k in range(steps)],
                kind=kind)


def test_circles_and_rectangles_on_a_column_layer_become_columns_that_keep_their_entity():
    geometry = drawing(circle("c1", (2, 3), 0.25), turned_box("c2", (10, 3), 0.6, 0.4, 0),
                       turned_box("c3", (20, 3), 0.6, 0.4, 30), circle("c4", (2, 10), 0.3, kind="LWPOLYLINE"))
    waiting = convert(geometry, COLUMNS)
    assert [(row["state"], row["reason"]) for row in waiting["columns"]] == [("waiting", "column_settings")] * 4
    assert waiting["operations"] == [] and waiting["summary"]["blocked"]["code"] == "nothing_to_add"
    result = convert(geometry, COLUMNS, HEIGHT)
    rows = {row["sources"][0]: row for row in result["columns"]}
    assert {key: rows["c1"][key] for key in ("shape", "center", "diameterMeters", "label", "entityId", "block")} == {
        "shape": "circle", "center": {"x": 7.0, "z": 8.0}, "diameterMeters": 0.5, "label": "Drawing column 1",
        "entityId": "c1", "block": None}
    assert {key: rows["c2"][key] for key in ("shape", "center", "widthMeters", "depthMeters", "rotationDegrees")} == {
        "shape": "rectangle", "center": {"x": 15.0, "z": 8.0}, "widthMeters": 0.6, "depthMeters": 0.4,
        "rotationDegrees": 0.0}
    # Turned 30 degrees counterclockwise (x right, z up) is a compass turn of 330: 60 after the swap that keeps
    # rotations under 90 (its 0.4 m side runs along 120 degrees counterclockwise).
    assert (rows["c3"]["widthMeters"], rows["c3"]["depthMeters"], rows["c3"]["rotationDegrees"]) == (0.4, 0.6, 60.0)
    assert (rows["c4"]["shape"], rows["c4"]["diameterMeters"]) == ("circle", 0.6)
    assert [row["state"] for row in result["columns"]] == ["new"] * 4 and result["summary"]["columns"] == {"new": 4}
    assert [op["op"] for op in result["operations"]] == ["upsert_column"] * 4
    record = result["operations"][0]["column"]
    assert record == {"columnId": result["columns"][0]["candidateId"], "label": "Drawing column 1", "shape": "circle",
                      "center": {"x": 7.0, "z": 8.0}, "diameterMeters": 0.5, "heightMeters": 6.0,
                      "baseElevation": 0.0, "appearance": {"color": "#8f969c"},
                      "source": {"referenceId": "fp-main", "importId": IMPORT_ID, "entityId": "c1"}}
    assert result["columns"][0]["candidateId"].startswith("col-fp-")
    # Applied, they are saved with their outlines, and converting again finds them there.
    doc = apply_facility_layout_operations(layout(), result["operations"])["document"]
    saved = doc["extensions"]["facilityColumns"]["columns"]
    assert [row["source"]["entityId"] for row in saved] == ["c1", "c2", "c3", "c4"]
    again = convert(geometry, COLUMNS, HEIGHT, doc=doc)
    assert [row["state"] for row in again["columns"]] == ["there"] * 4 and again["operations"] == []
    assert again["summary"]["columnsOnPlan"] == 4 and again["summary"]["columnLimit"] == 1000


@pytest.mark.parametrize("degrees", [0, 1, 30, 45, 89, 90, 91, 135, 180, 270, 359])
def test_a_rectangle_is_one_column_whichever_corner_and_way_round_it_is_drawn_and_lands_on_its_drawing(degrees):
    from ai_inspector.facility_layout.columns import footprint
    ids, shapes = set(), set()
    for start in range(4):
        for reverse in (False, True):
            geometry = drawing(turned_box("c1", (10, 10), 0.8, 0.3, degrees, start, reverse))
            (row,) = convert(geometry, COLUMNS, HEIGHT)["columns"]
            ids.add(row["candidateId"])
            shapes.add((row["widthMeters"], row["depthMeters"], row["rotationDegrees"]))
            assert 0 <= row["rotationDegrees"] < 90
            # The saved outline is the drawn box, moved by (5, 5), whatever the turn.
            drawn = turned_box("c1", (15, 15), 0.8, 0.3, degrees)["points"]
            outline = footprint(row)
            assert all(min(math.dist(point, corner) for corner in outline) < 2e-4 for point in drawn), (
                degrees, start, reverse, outline)
    assert len(ids) == 1 and len(shapes) == 1, (ids, shapes)


def test_a_block_insert_is_one_column_that_keeps_the_insert_and_an_array_is_one_per_copy():
    blocks = {"blocks": ["COL400"]}
    geometry = drawing(
        dict(turned_box("i1/a", (4, 4), 0.4, 0.4, 0), **blocks), dict(line("i1/b", "L1", (3.8, 3.8), (4.2, 4.2)),
                                                                        **blocks),
        dict(turned_box("i1/c", (4, 4), 0.3, 0.3, 0), **blocks),  # an inner outline: part of the column
        dict(circle("g[0]/a", (10, 4), 0.2), blocks=["C300"]), dict(circle("g[1]/a", (14, 4), 0.2), blocks=["C300"]),
        dict(turned_box("r/k1/a", (20, 4), 0.4, 0.4, 0), blocks=["ROW", "COL"]),
        dict(turned_box("r/k2/a", (20, 10), 0.4, 0.4, 0), blocks=["ROW", "COL"]))
    result = convert(geometry, COLUMNS, HEIGHT)
    assert [(row["entityId"], row["block"], row["shape"], row["state"]) for row in result["columns"]] == [
        ("i1", "COL400", "rectangle", "new"), ("g[0]", "C300", "circle", "new"), ("g[1]", "C300", "circle", "new"),
        ("r/k1", "COL", "rectangle", "new"), ("r/k2", "COL", "rectangle", "new")]
    assert result["columns"][0]["sources"] == ["i1/a", "i1/b", "i1/c"]
    assert result["unconvertedCounts"] == {}
    assert result["operations"][0]["column"]["source"]["entityId"] == "i1"


def test_what_is_not_a_column_stays_drawing_with_the_reason():
    octagon = [(30 + 0.3 * math.cos(2 * math.pi * k / 8), 4 + 0.3 * math.sin(2 * math.pi * k / 8)) for k in range(8)]
    geometry = drawing(
        poly("oct", "L1", octagon),  # too few corners for a circle
        poly("ell", "L1", [(0, 0), (1, 0), (1, 0.4), (0.4, 0.4), (0.4, 1), (0, 1)]),  # an L
        line("stray", "L1", (5, 5), (6, 5)),
        turned_box("outer", (10, 10), 1.0, 1.0, 0), turned_box("inner", (10, 10), 0.4, 0.4, 0),  # one inside another
        *(line(f"loose{k}", "L1", a, b) for k, (a, b) in enumerate(  # a box drawn as four lines
            [((20, 20), (20.4, 20)), ((20.4, 20), (20.4, 20.4)), ((20.4, 20.4), (20, 20.4)), ((20, 20.4), (20, 20))])),
        dict(line("blk/x", "L1", (25, 25), (25.4, 25.4)), blocks=["MARK"]))  # a block with no outline
    result = convert(geometry, COLUMNS, HEIGHT)
    assert [row["sources"] for row in result["columns"]] == [["outer"]]
    assert {row["entityId"]: row["reason"] for row in result["unconverted"]} == {
        "oct": "column_shape", "ell": "column_shape", "stray": "column_shape", "inner": "column_inside",
        "loose0": "column_shape", "loose1": "column_shape", "loose2": "column_shape", "loose3": "column_shape",
        "blk/x": "column_shape"}


def test_columns_on_the_plan_overlaps_and_odd_sizes_are_refused_and_left_out_ones_stay_out():
    hand_made = {"columnId": "col-hand", "label": "Hand", "shape": "circle", "center": {"x": 25.0, "z": 25.0},
                 "diameterMeters": 1.0, "heightMeters": 6, "baseElevation": 0, "appearance": {"color": "#8f969c"}}
    doc = apply_facility_layout_operations(layout(), [{"op": "upsert_column", "column": hand_made}])["document"]
    geometry = drawing(
        circle("on-hand", (20, 20), 0.3),  # lands on the hand-made column at (25, 25)
        turned_box("first", (2, 2), 0.4, 0.4, 0), turned_box("overlap", (2.2, 2), 0.4, 0.4, 0),
        turned_box("copy", (8, 2), 0.4, 0.4, 0), turned_box("copy2", (8, 2), 0.4, 0.4, 0),
        turned_box("tiny", (12, 2), 0.03, 0.4, 0), circle("huge", (16, 8), 2.6),
        turned_box("away", (14, 2), 0.4, 0.4, 0), turned_box("outside", (60, 2), 0.4, 0.4, 0))
    first = convert(geometry, COLUMNS, HEIGHT, doc=doc)
    states = {row["sources"][0]: (row["state"], row["reason"]) for row in first["columns"]}
    away = next(row["candidateId"] for row in first["columns"] if row["sources"] == ["away"])
    assert states == {"on-hand": ("refused", "column_there"), "first": ("new", None),
                      "overlap": ("refused", "overlapping_columns"), "copy": ("new", None),
                      "copy2": ("refused", "duplicate"), "tiny": ("refused", "column_size"),
                      "huge": ("refused", "column_size"), "away": ("new", None),
                      "outside": ("refused", "outside_plan")}
    left_out = convert(geometry, COLUMNS, dict(HEIGHT, excluded=[away]), doc=doc)
    assert [row["state"] for row in left_out["columns"] if row["candidateId"] == away] == ["excluded"]
    assert len(left_out["operations"]) == len(first["operations"]) - 1


def test_more_columns_than_a_plan_holds_block_the_conversion(monkeypatch):
    monkeypatch.setattr(conversion, "MAX_COLUMNS", 1)
    result = convert(drawing(circle("a", (2, 2), 0.2), circle("b", (6, 2), 0.2)), COLUMNS, HEIGHT)
    assert result["summary"]["blocked"]["code"] == "too_many_columns" and result["operations"] == []


@pytest.mark.parametrize("turn", [0.0, 0.2, 30.0, 89.8])
def test_a_box_a_little_off_square_is_one_column_whichever_corner_and_way_round_it_is_drawn(turn):
    # Codex review (columns, round 1): a box within the right-angle and equal-sides tolerances took its turn from the
    # side it started on, so its rotation (0 or 0.43 degrees) and its id depended on the corner it was drawn from.
    c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    corners = [(10 + x * c - z * s, 10 + x * s + z * c) for x, z in ((0, 0), (0.6, 0), (0.603, 0.4), (0.003, 0.4))]
    found = set()
    for start in range(4):
        for reverse in (False, True):
            ring = corners[start:] + corners[:start]
            (row,) = convert(drawing(poly("c1", "L1", ring[::-1] if reverse else ring)), COLUMNS, HEIGHT)["columns"]
            assert row["state"] == "new" and 0 <= row["rotationDegrees"] < 90
            found.add((row["candidateId"], row["widthMeters"], row["depthMeters"], row["rotationDegrees"]))
    assert len(found) == 1, found


def test_one_insert_of_many_columns_lists_its_entities_once_not_once_per_column():
    # Codex review (columns, round 1): each column of an insert listed and sorted all of the insert's entities again,
    # so one insert of N outlines cost N * N lookups before any limit could refuse it.
    lookups = [0]

    class Counted(dict):
        def get(self, key, default=None):
            lookups[0] += 1
            return super().get(key, default)

    count = 400
    entities = [Counted(dict(turned_box(f"row/e{k:03d}", (1 + (k % 20) * 1.5, 1 + (k // 20) * 1.2), 0.4, 0.4, 0),
                             blocks=["ROW"])) for k in range(count)]
    result = convert(drawing(*entities), COLUMNS, HEIGHT)
    assert [row["state"] for row in result["columns"]] == ["new"] * count
    sources = [f"row/e{k:03d}" for k in range(conversion.MAX_SOURCES)]
    assert all(row["entityId"] == "row" and row["block"] == "ROW" and row["sources"] == sources
               and row["layers"] == ["L1"] for row in result["columns"])
    assert lookups[0] < 30 * count, lookups  # listed per column, it would be over 2 * count * count
