"""FP2 of the floor-plan import (docs/facility-floor-plan-import-plan.md, sections 7, 8 and 11): walls, rooms and the
outline converted from a drawing's layers. Expected numbers are worked out by hand from the fixtures' documented
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
    assert conversion.normalize_settings(None) == {"walls": None, "rooms": None, "outline": None, "excluded": []}
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
                {"excluded": ["pl-1"]}, {"excluded": "iw-fp-" + "1" * 16}, {"other": 1}, []):
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
    # The partition: faces at x = 10 and 10.2, broken by the door from y = 4 to 5.2; moved by (5, 5).
    assert segments(result) == [((15.1, 5.0), (15.1, 9.0), 0.2), ((15.1, 10.2), (15.1, 15.0), 0.2)]
    assert [row["state"] for row in result["walls"]] == ["new", "new"]
    assert [row["label"] for row in result["walls"]] == ["Drawing wall 1", "Drawing wall 2"]
    assert all(row["from"] == "faces" and row["lengthMeters"] in (4.0, 4.8) for row in result["walls"])
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
    # The jambs and the end line close the wall ends; the column and the door wait for FP3.
    assert result["unconvertedCounts"] == {"later_phase": 2, "wall_end": 3}
    assert [op["op"] for op in result["operations"]] == ["set_perimeter_walls", "upsert_interior_wall",
                                                         "upsert_interior_wall", "add_zone"]
    assert result["summary"]["blocked"] is None
    wall = result["operations"][1]["wall"]
    assert wall == {"wallId": result["walls"][0]["candidateId"], "label": "Drawing wall 1",
                    "start": {"x": 15.1, "z": 5.0}, "end": {"x": 15.1, "z": 9.0}, "heightMeters": 3.0,
                    "thicknessMeters": 0.2, "baseElevation": 0.0, "color": "#45484b", "openings": []}


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
    assert [row["state"] for row in again["walls"] + again["rooms"] + again["outlines"]] == ["there"] * 4
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
    for kind in ("walls", "rooms", "outlines"):
        assert [row["candidateId"] for row in other[kind]] == [row["candidateId"] for row in meters[kind]], kind
    assert other["operations"] == meters["operations"]


def test_a_turned_drawing_lands_where_its_corners_project(factory_geometry):
    geometry = factory_geometry["meters"]
    # 90 degrees: x = 25 - v, z = u (the drawing's x axis runs along the plan's z).
    result = convert(geometry, factory_roles(geometry), FACTORY_SETTINGS, translate=(25.0, 0.0), rotation=90.0)
    # The partition (u = 10.1, v 0..4 and 5.2..10) runs along x at z = 10.1.
    assert segments(result) == [((15.0, 10.1), (19.8, 10.1), 0.2), ((21.0, 10.1), (25.0, 10.1), 0.2)]
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


def test_columns_and_doors_are_listed_for_a_later_step():
    geometry = drawing(square("c1", 0, 0, 0.4, layer="L1"), line("d1", "L2", (0, 0), (1, 0)))
    result = convert(geometry, {"L1": "column", "L2": "door"})
    assert result["unconvertedCounts"] == {"later_phase": 2}
    assert result["layers"] == {"L1": {"name": "layer L1", "role": "column"},
                                "L2": {"name": "layer L2", "role": "door"}}


def test_every_reason_keeps_a_listed_row_past_the_listing_limit():
    # More curves than are listed, then a column: the column's reason still has a row, and so its message.
    arcs = [{"id": f"a{index}", "layer": "L1", "type": "ARC", "closed": False,
             "points": [[index, 0], [index + 0.5, 0.5]]} for index in range(conversion.MAX_LISTED + 5)]
    result = convert(drawing(*arcs, square("c1", 0, 20, 0.4, layer="L2")), {"L1": "wall_centerline", "L2": "column"})
    assert result["unconvertedCounts"] == {"curve": conversion.MAX_LISTED + 5, "later_phase": 1}
    reasons = [row["reason"] for row in result["unconverted"]]
    assert reasons.count("curve") == conversion.MAX_LISTED and reasons.count("later_phase") == 1
    column = next(row for row in result["unconverted"] if row["reason"] == "later_phase")
    assert (column["entityId"], column["message"]) == ("c1", conversion.MESSAGES["later_phase"])


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
