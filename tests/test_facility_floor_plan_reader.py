"""FP0 of the floor-plan import (docs/facility-floor-plan-import-plan.md, section 11): the DXF reader, the worker that
runs it inside limits, and the alignment math. Expected numbers are written by hand from the coordinates documented
in tests/floor_plan_dxf_fixtures.py, never read back from ezdxf."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

pytest.importorskip("ezdxf")

from ai_inspector.facility_layout import floor_plan_alignment as alignment
from ai_inspector.facility_layout import floor_plan_reader as reader
from ai_inspector.facility_layout import floor_plan_worker as worker
from tests import floor_plan_dxf_fixtures as fixtures

CASES = json.loads((Path(__file__).parent / "fixtures" / "facility_layout" / "floor_plan" / "alignment_cases.json")
                   .read_text(encoding="utf-8"))


def read(path, **options):
    return reader.read_dxf(str(path), **options)


def layer_name(geometry, layer_id):
    return next(layer["name"] for layer in geometry["layers"] if layer["layerId"] == layer_id)


def on_layer(geometry, name, kind=None):
    wanted = next(layer["layerId"] for layer in geometry["layers"] if layer["name"] == name)
    return [e for e in geometry["entities"] if e["layer"] == wanted and (kind is None or e["type"] == kind)]


def absolute(geometry, point):
    return (geometry["origin"][0] + point[0], geometry["origin"][1] + point[1])


def meters(geometry, point):
    scale = geometry["units"]["metersPerUnit"]
    u, v = absolute(geometry, point)
    return (u * scale, v * scale)


def near(a, b, tolerance=1e-6):
    return math.dist(a, b) <= tolerance


def same(points, expected, tolerance=1e-6):
    return len(points) == len(expected) and all(near(a, b, tolerance) for a, b in zip(points, expected))


def max_sagitta(points, radius):
    """The largest gap between a chord and the circle it cuts: a flattened circular curve's error."""
    worst = 0.0
    for a, b in zip(points, points[1:]):
        half = math.dist(a, b) / 2
        worst = max(worst, radius - math.sqrt(max(radius * radius - half * half, 0.0)))
    return worst


def on_circle(points, center, radius, tolerance=1e-6):
    return all(abs(math.dist(p, center) - radius) <= tolerance for p in points)


def warning_codes(geometry):
    return {warning["code"] for warning in geometry["warnings"]}


# -- fixture 1: the asymmetric factory ----------------------------------------------------------------------------

def test_factory_in_meters_comes_out_as_drawn(tmp_path):
    g = read(fixtures.factory(tmp_path))
    assert g["schema"] == reader.SCHEMA and g["parser"]["name"] == "ezdxf"
    assert {k: g["units"][k] for k in ("insunits", "name", "metersPerUnit", "status")} == {
        "insunits": 6, "name": "meters", "metersPerUnit": 1.0, "status": "declared"}
    assert g["curveTolerance"] == 0.002
    assert g["origin"] == [0.0, 0.0]
    assert g["extents"] == {"min": [0.0, 0.0], "max": [30.0, 20.0]}
    assert g["counts"]["keptEntities"] == 13 and g["counts"]["texts"] == 2 and g["unsupported"] == []
    assert g["warnings"] == []

    (outline,) = on_layer(g, "A-WALL-EXT")
    assert outline["type"] == "LWPOLYLINE" and outline["closed"] is True
    assert outline["points"] == [[0.0, 0.0], [30.0, 0.0], [30.0, 20.0], [0.0, 20.0]]
    walls = on_layer(g, "A-WALL", "LINE")
    assert [w["points"] for w in walls] == [[list(a), list(b)] for a, b in fixtures.FACTORY_FACES + fixtures.FACTORY_JAMBS]
    gap = walls[1]["points"][0][1] - walls[0]["points"][1][1]
    assert gap == pytest.approx(1.2)  # the door gap
    assert walls[2]["points"][0][0] - walls[0]["points"][0][0] == pytest.approx(0.2)  # the wall's thickness
    (room,) = on_layer(g, "A-AREA")
    xs, zs = [p[0] for p in room["points"]], [p[1] for p in room["points"]]
    area = 0.5 * abs(sum(xs[i] * zs[(i + 1) % 4] - xs[(i + 1) % 4] * zs[i] for i in range(4)))
    assert room["closed"] and area == pytest.approx(20.0)

    (column,) = on_layer(g, "S-COLS")
    (center, radius) = fixtures.FACTORY_COLUMN
    assert column["type"] == "CIRCLE" and column["closed"] and column["points"][0] != column["points"][-1]
    assert on_circle(column["points"], center, radius)
    assert max_sagitta(column["points"] + column["points"][:1], radius) <= 0.002 + 1e-9
    (swing,) = on_layer(g, "A-DOOR")
    assert swing["type"] == "ARC" and not swing["closed"]
    assert near(swing["points"][0], (11.4, 4.0)) and near(swing["points"][-1], (10.2, 5.2))
    assert on_circle(swing["points"], (10.2, 4.0), 1.2)

    text, mtext = on_layer(g, "A-TEXT")
    assert (text["type"], text["text"], text["at"], text["height"], text["rotation"], text["align"],
            text["mirrored"]) == ("TEXT", "Office", [21.0, 14.0], 0.3, 0.0, "LEFT", False)
    assert (mtext["type"], mtext["text"], mtext["at"], mtext["height"], mtext["align"]) == (
        "MTEXT", "Workshop\nBay 1", [3.0, 15.0], 0.5, "TOP_LEFT")
    layer = next(row for row in g["layers"] if row["name"] == "A-WALL")
    assert (layer["entities"], layer["vertices"], layer["color"]) == (7, 14, 2)
    assert layer["extents"] == {"min": [10.0, 0.0], "max": [10.2, 10.0]}


# -- fixture 2: the same factory in other units -------------------------------------------------------------------

@pytest.mark.parametrize("unit", ["millimeters", "inches", "feet"])
def test_equivalent_unit_drawings_give_the_same_meters(tmp_path, unit):
    base = read(fixtures.factory(tmp_path))
    other = read(fixtures.factory(tmp_path, unit=unit))
    scale = other["units"]["metersPerUnit"]
    assert other["units"]["status"] == "declared" and other["units"]["name"] == unit
    assert scale == pytest.approx(1 / fixtures.UNIT_PER_METER[unit], rel=1e-12)
    assert other["curveTolerance"] * scale == pytest.approx(0.002)
    assert len(other["entities"]) == len(base["entities"])
    curves = {"CIRCLE": fixtures.FACTORY_COLUMN, "ARC": (fixtures.FACTORY_DOOR_ARC[0], fixtures.FACTORY_DOOR_ARC[1])}
    for mine, theirs in zip(base["entities"], other["entities"]):
        assert (theirs["type"], layer_name(other, theirs["layer"])) == (mine["type"], layer_name(base, mine["layer"]))
        if "points" not in mine:
            assert theirs["text"] == mine["text"] and theirs["align"] == mine["align"]
            assert near(meters(other, theirs["at"]), meters(base, mine["at"]))
            assert theirs["height"] * scale == pytest.approx(mine["height"], abs=1e-6)
            continue
        assert theirs["closed"] == mine["closed"]
        mine_m = [meters(base, p) for p in mine["points"]]
        theirs_m = [meters(other, p) for p in theirs["points"]]
        if mine["type"] in curves:  # flattened anew in each unit: same circle, same ends, same error bound
            center, radius = curves[mine["type"]]
            assert on_circle(theirs_m, center, radius)
            assert near(theirs_m[0], mine_m[0]) and near(theirs_m[-1], mine_m[-1])
            closing = theirs_m[:1] if theirs["closed"] else []
            assert max_sagitta(theirs_m + closing, radius) <= 0.002 + 1e-9
        else:
            assert len(theirs_m) == len(mine_m)
            assert all(near(a, b) for a, b in zip(theirs_m, mine_m))


# -- fixture 3: unitless and misleading units ----------------------------------------------------------------------

def test_unitless_drawing_needs_calibration_and_10000_units_to_10_m_is_a_millimeter(tmp_path):
    g = read(fixtures.unitless_segment(tmp_path))
    assert g["units"]["status"] == "unresolved" and g["units"]["metersPerUnit"] is None
    assert g["units"]["name"] == "unitless" and "units_unresolved" in warning_codes(g)
    (segment,) = g["entities"]
    a, b = (absolute(g, p) for p in segment["points"])
    assert same([a, b], [(0.0, 0.0), (10000.0, 0.0)])
    assert alignment.scale_for_distance(a, b, 10.0) == 0.001
    fitted = alignment.fit([(a, (0.0, 0.0)), (b, (10.0, 0.0))])
    assert fitted["metersPerDrawingUnit"] == pytest.approx(0.001, rel=1e-12)
    assert fitted["rotationDegrees"] == pytest.approx(0.0, abs=1e-9)
    assert fitted["maxResidualMeters"] < 1e-9


def test_a_known_distance_exposes_a_misleading_unit_header(tmp_path):
    g = read(fixtures.unitless_segment(tmp_path, insunits=6, name="says-meters.dxf"))
    assert g["units"]["status"] == "declared" and g["units"]["metersPerUnit"] == 1.0
    (segment,) = g["entities"]
    a, b = (absolute(g, p) for p in segment["points"])
    rigid = alignment.fit([(a, (0.0, 0.0)), (b, (10.0, 0.0))], meters_per_unit=g["units"]["metersPerUnit"])
    assert rigid["metersPerDrawingUnit"] == 1.0  # held, as declared
    assert rigid["scaleRatio"] == pytest.approx(0.001)  # the picks say millimeters
    assert rigid["maxResidualMeters"] == pytest.approx(4995.0)


def test_other_unit_codes_stay_unresolved(tmp_path):
    g = read(fixtures.unitless_segment(tmp_path, insunits=7, name="kilometers.dxf"))
    assert (g["units"]["name"], g["units"]["status"], g["units"]["metersPerUnit"]) == ("kilometers", "unresolved",
                                                                                        None)


# -- fixture 4: survey-sized coordinates ---------------------------------------------------------------------------

def test_survey_sized_coordinates_keep_their_local_precision(tmp_path):
    local = read(fixtures.factory(tmp_path))
    far = read(fixtures.factory(tmp_path, offset=(512345.678, 4012345.678), name="survey.dxf"))
    assert far["origin"] == [512345.678, 4012345.678]
    assert far["extents"] == {"min": [0.0, 0.0], "max": [30.0, 20.0]}
    assert on_layer(far, "A-WALL-EXT")[0]["points"] == [[0.0, 0.0], [30.0, 0.0], [30.0, 20.0], [0.0, 20.0]]
    assert len(far["entities"]) == len(local["entities"])
    for a, b in zip(local["entities"], far["entities"]):
        if "points" in a:
            assert len(b["points"]) == len(a["points"])
            assert all(near(p, q) for p, q in zip(a["points"], b["points"]))
        else:
            assert near(a["at"], b["at"])


# -- fixture 5: blocks ---------------------------------------------------------------------------------------------

def boxes(geometry, name):
    """(center x, center y, width, height) of each closed polyline on layer NAME, absolute drawing units."""
    out = []
    for entity in on_layer(geometry, name, "LWPOLYLINE"):
        points = [absolute(geometry, p) for p in entity["points"]]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        out.append(tuple(round(v, 6) for v in ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                                               max(xs) - min(xs), max(ys) - min(ys))))
    return out


def test_blocks_expand_nested_rotated_mirrored_scaled_arrayed_and_inherit_layer_zero(tmp_path):
    g = read(fixtures.blocks(tmp_path))
    # ROW at (2, 3) turned 90 degrees, each COL square on layer 0 inside, so on S-COLS; then COL scaled 2 x 0.5.
    assert boxes(g, "S-COLS") == [(2.0, 3.0, 0.4, 0.4), (2.0, 9.0, 0.4, 0.4), (2.0, 15.0, 0.4, 0.4),
                                  (20.0, 20.0, 0.8, 0.2)]
    # The MINSERT grid: 3 columns 5 m apart, 2 rows 4 m apart.
    assert sorted(boxes(g, "S-GRID")) == sorted((x, y, 0.4, 0.4) for x in (30.0, 35.0, 40.0) for y in (0.0, 4.0))
    labels = on_layer(g, "S-TEXT")  # not on layer 0: they keep their own layer
    assert len(labels) == 10 and {label["text"] for label in labels} == {"C"}
    turned = [label for label in labels if label["rotation"] == 90.0]
    assert same([absolute(g, label["at"]) for label in turned], [(2.0, 3.0), (2.0, 9.0), (2.0, 15.0)])
    squashed = next(label for label in labels if near(absolute(g, label["at"]), (20.0, 20.0)))
    assert squashed["height"] == pytest.approx(0.05) and squashed["rotation"] == 0.0

    line, arc = sorted(on_layer(g, "A-DOOR"), key=lambda e: e["type"] != "LINE")
    assert same([absolute(g, p) for p in line["points"]], [(5.0, 5.0), (4.0, 5.0)])  # mirrored: runs to -x
    swing = [absolute(g, p) for p in arc["points"]]
    assert near(swing[0], (4.0, 5.0)) and near(swing[-1], (5.0, 6.0))
    assert on_circle(swing, (5.0, 5.0), 1.0) and all(p[0] <= 5.0 + 1e-9 for p in swing)

    part, based = on_layer(g, "A-PART")
    assert same([absolute(g, p) for p in part["points"]], [(0.0, 30.0), (1.0, 30.0)])  # millimeter block, scaled once
    assert same([absolute(g, p) for p in based["points"]], [(50.0, 50.0), (60.0, 50.0)])  # base point honored
    assert g["blockUnits"] == [{"block": "MM-PART", "units": "millimeters"}]
    assert "block_units" in warning_codes(g)

    ids = [entity["id"] for entity in g["entities"]]
    assert len(ids) == len(set(ids))
    nested = on_layer(g, "S-COLS", "LWPOLYLINE")[0]
    assert nested["id"].count("/") == 2 and nested["blocks"] == ["ROW", "COL"]
    grid_ids = sorted(e["id"].split("/")[0] for e in on_layer(g, "S-GRID"))
    assert [i[-3:] for i in grid_ids] == [f"[{n}]" for n in range(6)]


def test_block_nesting_limit_reports_the_inserts_it_skips(tmp_path):
    g = read(fixtures.blocks(tmp_path), limits={"maxBlockDepth": 1})
    assert boxes(g, "S-COLS") == [(20.0, 20.0, 0.8, 0.2)]  # the ROW's columns sit one level too deep
    rows = [row for row in g["unsupported"] if row["reason"] == "block_nesting"]
    assert [(row["type"], layer_name(g, row["layer"]), row["count"]) for row in rows] == [("INSERT", "S-COLS", 3)]


# -- fixture 6: curves ---------------------------------------------------------------------------------------------

def test_curves_follow_their_true_shape_within_the_tolerance(tmp_path):
    g = read(fixtures.curves(tmp_path))
    tolerance = g["curveTolerance"]
    bulged, arc, circle = g["entities"]
    points = [absolute(g, p) for p in bulged["points"]]
    assert near(points[0], (0.0, 0.0)) and near(points[-2], (10.0, 0.0)) and near(points[-1], (10.0, -5.0))
    half = points[:-1]  # a positive bulge from (0,0) to (10,0) turns counter-clockwise: through (5,-5)
    assert min(p[1] for p in half) == pytest.approx(-5.0, abs=tolerance)
    assert on_circle(half, (5.0, 0.0), 5.0) and all(p[1] <= 1e-9 for p in half)
    assert max_sagitta(half, 5.0) <= tolerance + 1e-9

    points = [absolute(g, p) for p in arc["points"]]  # extrusion (0,0,-1): OCS x runs along world -x
    assert near(points[0], (-22.0, 0.0)) and near(points[-1], (-20.0, 2.0))
    assert on_circle(points, (-20.0, 0.0), 2.0)
    assert all(p[0] <= -20.0 + 1e-9 and p[1] >= -1e-9 for p in points)
    assert max_sagitta(points, 2.0) <= tolerance + 1e-9

    points = [absolute(g, p) for p in circle["points"]]
    assert circle["closed"] and points[0] != points[-1]
    assert on_circle(points, (40.0, 0.0), 3.0) and max_sagitta(points + points[:1], 3.0) <= tolerance + 1e-9


def test_too_detailed_curves_are_drawn_coarser_or_reported(tmp_path):
    g = read(fixtures.curves(tmp_path), limits={"maxEntityVertices": 40})
    by_type = {entity["type"]: entity for entity in g["entities"]}
    assert all(len(entity["points"]) <= 40 for entity in g["entities"])
    assert "tolerance" not in by_type["ARC"]  # 19 points fit at 2 mm
    assert by_type["CIRCLE"]["tolerance"] in (pytest.approx(0.02), pytest.approx(0.2))
    assert by_type["LWPOLYLINE"]["tolerance"] in (pytest.approx(0.02), pytest.approx(0.2))
    g = read(fixtures.curves(tmp_path), limits={"maxEntityVertices": 3})
    reasons = {(row["type"], row["reason"]): row["count"] for row in g["unsupported"]}
    assert reasons[("CIRCLE", "too_many_vertices")] == 1


# -- fixture 10: hostile drawings ----------------------------------------------------------------------------------

def test_hostile_drawing_is_reported_and_never_trusted(tmp_path):
    g = read(fixtures.hostile(tmp_path)["mixed"])
    reasons = {(row["type"], layer_name(g, row["layer"]), row["reason"]): row["count"] for row in g["unsupported"]}
    assert reasons == {("INSERT", "A-LOOP", "recursive_block"): 1, ("INSERT", "A-XREF", "external_reference"): 1,
                       ("HATCH", "A-HATCH", "hatch"): 1, ("DIMENSION", "A-DIMS", "dimension"): 1}
    assert same([absolute(g, p) for p in on_layer(g, "A-LOOP")[0]["points"]], [(0.0, 0.0), (1.0, 0.0)])
    assert g["externalReferences"] == [{"name": "BASE-XREF", "file": "base-building.dxf"}]
    assert "private" not in json.dumps(g)  # the reference's folder never leaves the reader
    assert g["paperSpace"] == [{"name": "Layout1", "entities": 1}]
    assert warning_codes(g) == {"external_references", "paper_space", "long_text"}
    long_text, script = on_layer(g, "A-TEXT")
    assert long_text["text"] == "x" * 4096
    assert script["text"] == "<script>alert(1)</script>"  # kept as text, the right-to-left override dropped


def test_a_coordinate_that_is_not_a_number_drops_only_its_entity(tmp_path):
    g = read(fixtures.hostile(tmp_path)["nan"])
    assert [(row["type"], row["reason"]) for row in g["unsupported"]] == [("LINE", "coordinates_out_of_range")]
    (kept,) = g["entities"]
    assert same([absolute(g, p) for p in kept["points"]], [(0.0, 1.0), (2.0, 1.0)])


@pytest.mark.parametrize("name, code", [("truncated", "truncated"), ("binary", "binary_dxf"), ("dwg", "dwg_file"),
                                        ("zip", "not_dxf"), ("text", "not_dxf")])
def test_files_that_are_not_complete_ascii_dxf_are_refused(tmp_path, name, code):
    with pytest.raises(reader.FloorPlanReadError) as caught:
        read(fixtures.hostile(tmp_path)[name])
    assert caught.value.code == code and caught.value.message


def test_an_empty_file_is_refused(tmp_path):
    empty = tmp_path / "empty.dxf"
    empty.write_bytes(b"")
    with pytest.raises(reader.FloorPlanReadError) as caught:
        read(empty)
    assert caught.value.code == "not_dxf"


# -- fixture 11: limits --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("limits, code", [
    ({"maxSourceEntities": 49}, "too_many_entities"),
    ({"maxVertices": 99}, "too_many_vertices"),
    ({"maxLayers": 21}, "too_many_layers"),  # the table's "0" and "Defpoints", then L-0 ... L-19
    ({"maxFileBytes": 1000}, "too_large"),
])
def test_limits_refuse_a_drawing_just_past_them(tmp_path, limits, code):
    path = fixtures.many_lines(tmp_path, 50, layers=20)
    with pytest.raises(reader.FloorPlanReadError) as caught:
        read(path, limits=limits)
    assert caught.value.code == code


def test_limits_accept_a_drawing_exactly_at_them(tmp_path):
    path = fixtures.many_lines(tmp_path, 50, layers=20)
    g = read(path, limits={"maxSourceEntities": 50, "maxVertices": 100, "maxLayers": 22})
    assert g["counts"]["keptEntities"] == 50 and g["counts"]["vertices"] == 100 and len(g["layers"]) == 22


def _segment_distance(point, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / length))
    return math.dist(point, (ax + t * dx, ay + t * dy))


def test_a_curve_tilted_by_its_ocs_and_its_insert_stays_within_the_tolerance(tmp_path):
    # Codex review of FP0, finding 1: the plan stretch must include what block Z adds to plan X/Y.
    import ezdxf
    from ezdxf.math import OCS

    doc = ezdxf.new("R2010", units=6)
    doc.blocks.new("TILT").add_circle((0, 0), 1, dxfattribs={"extrusion": (0, 1, 2)})
    insert = doc.modelspace().add_blockref("TILT", (5, 5), dxfattribs={
        "extrusion": (0, 1, 1), "xscale": 1, "yscale": 1, "zscale": 2})
    path = tmp_path / "tilted.dxf"
    doc.saveas(path)
    g = read(path)
    (circle,) = [e for e in g["entities"] if e["type"] == "CIRCLE"]
    tolerance = circle.get("tolerance", g["curveTolerance"])
    points = [absolute(g, p) for p in circle["points"]]
    if circle["closed"]:
        points.append(points[0])
    ocs, matrix = OCS((0, 1, 2)), insert.matrix44()
    true = [matrix.transform(ocs.to_wcs((math.cos(t), math.sin(t), 0)))
            for t in (2 * math.pi * k / 4000 for k in range(4000))]
    assert max(abs(p.z - true[0].z) for p in true) < 1e-9  # the case only counts if the circle lies flat
    worst = max(min(_segment_distance((p.x, p.y), a, b) for a, b in zip(points, points[1:])) for p in true)
    assert worst <= tolerance + 1e-9


def test_attributes_count_as_entities_and_layer_zero_ones_take_the_insert_layer(tmp_path):
    # Codex review of FP0, findings 2 and 3.
    import ezdxf

    doc = ezdxf.new("R2010", units=6)
    doc.layers.add("LABELS")
    doc.blocks.new("TAG").add_line((0, 0), (1, 0))
    insert = doc.modelspace().add_blockref("TAG", (2, 2), dxfattribs={"layer": "LABELS"})
    for tag, x in (("ROOM", 0.0), ("AREA", 1.0)):
        insert.add_attrib(tag, tag.lower(), (2 + x, 3), dxfattribs={"layer": "0", "height": 0.25})
    path = tmp_path / "tagged.dxf"
    doc.saveas(path)
    g = read(path)
    assert g["counts"]["expandedEntities"] == 4  # the insert, its line and both attributes
    labels = [e for e in g["entities"] if e["type"] == "ATTRIB"]
    assert sorted(e["text"] for e in labels) == ["area", "room"]
    assert {layer_name(g, e["layer"]) for e in labels} == {"LABELS"}
    assert read(path, limits={"maxExpandedEntities": 4})["counts"]["expandedEntities"] == 4
    with pytest.raises(reader.FloorPlanReadError) as caught:
        read(path, limits={"maxExpandedEntities": 3})
    assert caught.value.code == "too_many_entities"


def test_a_label_too_tall_to_measure_is_reported_not_written(tmp_path):
    # Codex review of FP0, finding 4: finite parts, infinite height.
    import ezdxf

    doc = ezdxf.new("R2010", units=6)
    doc.blocks.new("HUGE").add_text("big", dxfattribs={"height": 1.7e308, "rotation": 45})
    doc.modelspace().add_blockref("HUGE", (0, 0), dxfattribs={"xscale": 1.1, "yscale": 1.1})
    doc.modelspace().add_line((0, 0), (1, 1))
    path = tmp_path / "huge.dxf"
    doc.saveas(path)
    g = read(path)
    assert not [e for e in g["entities"] if e["type"] == "TEXT"]
    assert any(row["type"] == "TEXT" and row["reason"] == "coordinates_out_of_range" for row in g["unsupported"])
    json.dumps(g, allow_nan=False)


def test_expanded_entity_limit_counts_block_contents(tmp_path):
    path = fixtures.blocks(tmp_path)
    assert read(path, limits={"maxExpandedEntities": 38})["counts"]["expandedEntities"] == 38
    with pytest.raises(reader.FloorPlanReadError) as caught:
        read(path, limits={"maxExpandedEntities": 37})
    assert caught.value.code == "too_many_entities"


# -- determinism and label text ------------------------------------------------------------------------------------

def test_reading_twice_gives_the_same_bytes(tmp_path):
    path = fixtures.blocks(tmp_path)
    assert json.dumps(read(path)) == json.dumps(read(path))


def test_label_text_is_cleaned_and_bounded():
    assert reader.clean_text("a\u202eb\u200bc\x07d", 100) == ("abcd", False)
    assert reader.clean_text("  line one \r\n line two ", 100) == ("line one\nline two", False)
    assert reader.clean_text("a\tb", 100) == ("a b", False)
    # Codex review of FP0, finding 5: every format character goes, not just a list of them.
    assert reader.clean_text("a\u061cb\u206ac\u206fd\U000e0041e\u00adf", 100) == ("abcdef", False)
    assert reader.clean_text("one\u2028two", 100) == ("one\ntwo", False)
    assert reader.clean_text("e\u0301", 100) == ("\u00e9", False)
    assert reader.clean_text("\u00e9" * 3000, 4096) == ("\u00e9" * 2048, True)  # whole characters only


# -- the worker ----------------------------------------------------------------------------------------------------

def job_folder(tmp_path, name="job"):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def test_worker_output_matches_the_in_process_reader(tmp_path):
    path = fixtures.factory(tmp_path)
    folder = job_folder(tmp_path)
    result = worker.parse_dxf(path, folder, source_sha256="ab" * 32)
    geometry = json.loads(Path(result["geometryPath"]).read_text(encoding="utf-8"))
    assert geometry == json.loads(json.dumps(read(path, source_sha256="ab" * 32)))
    assert result["manifest"] == reader.manifest_of(geometry) and "entities" not in result["manifest"]
    assert result["peakMemoryBytes"] is None or result["peakMemoryBytes"] < worker.DEFAULT_MEMORY_MB * 1024 * 1024
    assert sorted(p.name for p in folder.iterdir()) == ["geometry.json", "manifest.json", "worker-stderr.txt"]


def test_worker_passes_on_the_reader_refusals_and_limits(tmp_path):
    archive = tmp_path / "plan.dxf"
    archive.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    with pytest.raises(worker.FloorPlanParseError) as caught:
        worker.parse_dxf(archive, job_folder(tmp_path, "a"))
    assert (caught.value.code, caught.value.status_code) == ("not_dxf", 422)
    with pytest.raises(worker.FloorPlanParseError) as caught:
        worker.parse_dxf(fixtures.factory(tmp_path), job_folder(tmp_path, "b"), reader_limits={"maxSourceEntities": 5})
    assert (caught.value.code, caught.value.status_code) == ("too_many_entities", 413)


def test_worker_past_its_time_limit_is_stopped(tmp_path):
    folder = job_folder(tmp_path)
    with pytest.raises(worker.FloorPlanParseError) as caught:
        worker.parse_dxf(fixtures.factory(tmp_path), folder, timeout_seconds=0.05)
    assert caught.value.code == "parse_timeout"
    assert not (folder / "geometry.json").exists() and not (folder / "manifest.json").exists()


def test_worker_that_needs_more_memory_than_allowed_is_refused(tmp_path):
    big = fixtures.many_lines(tmp_path, 60_000, name="dense.dxf", layers=40)
    folder = job_folder(tmp_path)
    with pytest.raises(worker.FloorPlanParseError) as caught:
        worker.parse_dxf(big, folder, memory_mb=120)
    assert (caught.value.code, caught.value.status_code) == ("too_large", 413)
    assert not (folder / "geometry.json").exists()


def test_worker_that_cannot_start_says_so(tmp_path):
    with pytest.raises(worker.FloorPlanParseError) as caught:
        worker.parse_dxf(fixtures.factory(tmp_path), job_folder(tmp_path), python=str(tmp_path / "no-python.exe"))
    assert (caught.value.code, caught.value.status_code) == ("parse_unavailable", 503)


# -- alignment -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", CASES["cases"], ids=lambda case: case["name"])
def test_alignment_cases_map_both_ways(case):
    for point in case["points"]:
        x, z = alignment.to_layout(case["alignment"], *point["drawing"])
        assert x == pytest.approx(point["layout"][0], abs=CASES["tolerance"])
        assert z == pytest.approx(point["layout"][1], abs=CASES["tolerance"])
        u, v = alignment.to_drawing(case["alignment"], *point["layout"])
        assert (u, v) == (pytest.approx(point["drawing"][0], abs=1e-6), pytest.approx(point["drawing"][1], abs=1e-6))


def test_fit_recovers_a_turned_scaled_moved_drawing():
    truth = {"sourceOrigin": {"u": 1000.0, "v": 2000.0}, "metersPerDrawingUnit": 0.001, "rotationDegrees": 37.5,
             "translationMeters": {"x": 12.0, "z": -3.0}}
    drawing = [(1000.0, 2000.0), (31000.0, 2000.0), (31000.0, 22000.0), (5000.0, 17000.0)]
    result = alignment.fit([(p, alignment.to_layout(truth, *p)) for p in drawing], source_origin=(1000.0, 2000.0))
    assert result["metersPerDrawingUnit"] == pytest.approx(0.001, rel=1e-12)
    assert result["rotationDegrees"] == pytest.approx(37.5, abs=1e-9)
    assert result["translationMeters"] == {"x": pytest.approx(12.0, abs=1e-9), "z": pytest.approx(-3.0, abs=1e-9)}
    assert result["maxResidualMeters"] < 1e-9 and result["scaleRatio"] == pytest.approx(1.0)
    two = alignment.fit([(drawing[0], alignment.to_layout(truth, *drawing[0])),
                         (drawing[2], alignment.to_layout(truth, *drawing[2]))], source_origin=(1000.0, 2000.0))
    assert two["rotationDegrees"] == pytest.approx(37.5, abs=1e-9) and two["maxResidualMeters"] < 1e-9


def test_fit_and_distance_refuse_points_that_fix_nothing():
    with pytest.raises(ValueError):
        alignment.fit([((0, 0), (0, 0))])
    with pytest.raises(ValueError):
        alignment.fit([((5, 5), (0, 0)), ((5, 5), (10, 0))])  # one drawing point picked twice
    with pytest.raises(ValueError):
        alignment.fit([((0, 0), (0, 0)), ((100, 0), (0.05, 0))])  # layout picks 5 cm apart
    with pytest.raises(ValueError):
        alignment.fit([((0, 0), (0, 0)), ((float("nan"), 0), (1, 0))])
    with pytest.raises(ValueError):
        alignment.scale_for_distance((1, 1), (1, 1), 10.0)
    with pytest.raises(ValueError):
        alignment.scale_for_distance((0, 0), (1, 0), 0.05)


def test_alignment_is_stored_as_a_closed_idempotent_record():
    value = {"sourceOrigin": {"u": 1000.12345678, "v": -5}, "metersPerDrawingUnit": 0.001, "rotationDegrees": 450.0,
             "translationMeters": {"x": 1.23456789, "z": 0}, "unitSource": "header", "confirmed": True,
             "controlPoints": [{"source": {"u": 0, "v": 0}, "target": {"x": 0, "z": 0}}]}
    once = alignment.normalize_alignment(value)
    assert once["rotationDegrees"] == 90.0 and once["sourceOrigin"] == {"u": 1000.123457, "v": -5.0}
    assert once["translationMeters"] == {"x": 1.234568, "z": 0.0}
    assert alignment.normalize_alignment(once) == once
    broken = [dict(value, extra=1), dict(value, metersPerDrawingUnit=0), dict(value, metersPerDrawingUnit=float("nan")),
              dict(value, unitSource="guess"), dict(value, confirmed="yes"), dict(value, rotationDegrees=True),
              dict(value, controlPoints=[{"source": {"u": 0}, "target": {"x": 0, "z": 0}}]),
              dict(value, controlPoints=[{"source": {"u": 0, "v": 0}, "target": {"x": 2e6, "z": 0}}])]
    for record in broken:
        with pytest.raises(ValueError):
            alignment.normalize_alignment(record)


def test_rotation_rounded_onto_the_boundary_is_stored_once():
    # Codex review of FP0, finding 6.
    value = {"sourceOrigin": {"u": 0, "v": 0}, "metersPerDrawingUnit": 1, "rotationDegrees": -179.9999999996,
             "translationMeters": {"x": 0, "z": 0}, "unitSource": "header", "confirmed": True, "controlPoints": []}
    once = alignment.normalize_alignment(value)
    assert once["rotationDegrees"] == 180.0
    assert alignment.normalize_alignment(once) == once


def test_fit_checks_its_origin_and_a_held_scale_of_zero():
    # Codex review of FP0, finding 7.
    pairs = [((0, 0), (0, 0)), ((1, 0), (2, 0))]
    with pytest.raises(ValueError):
        alignment.fit(pairs, meters_per_unit=0)
    with pytest.raises(ValueError):
        alignment.fit(pairs, meters_per_unit=float("nan"))
    with pytest.raises(ValueError):
        alignment.fit(pairs, source_origin=(float("nan"), 0), meters_per_unit=1)
    with pytest.raises(ValueError):
        alignment.fit(pairs, source_origin=None)
    assert alignment.fit(pairs)["metersPerDrawingUnit"] == pytest.approx(2)
    assert alignment.fit(pairs, meters_per_unit=1)["metersPerDrawingUnit"] == 1


def test_rotation_is_kept_in_the_half_open_turn():
    assert [alignment.normalize_rotation(d) for d in (-180, 180, 540, -190, 359.5, 0)] == [180, 180, 180, 170, -0.5, 0]
