"""Columns (columns.py): native parametric structural columns, rectangular or round."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from ai_inspector.facility_layout.columns import (KEY, PREFIX, append_column_features, compile_columns,
                                                  validate_columns)
from ai_inspector.facility_layout.operations import FacilityLayoutOperationError, apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import default_plan_settings, shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from ai_inspector.facility_layout.validate import FacilityValidationError, validate_layout

SOURCE = {"referenceId": "fp-main", "importId": "fpi-" + "a" * 32, "entityId": "2F/1A"}


def layout():
    value = json.loads((Path(__file__).parent / "fixtures/facility_layout/empty_cell.json").read_text())
    value.setdefault("extensions", {})["facilityPlan"] = default_plan_settings()  # 40 m x 30 m
    return value


def square(**patch):
    return dict(dict(columnId="col-a1", label=" Column A1 ", shape="rectangle", center={"x": 10, "z": 5},
                     widthMeters=0.6, depthMeters=0.4, rotationDegrees=0, heightMeters=8, baseElevation=0,
                     appearance={"color": "#8F969C"}), **patch)


def round_(**patch):
    return dict(dict(columnId="col-b1", label="Column B1", shape="circle", center={"x": 20, "z": 5},
                     diameterMeters=0.5, heightMeters=8, baseElevation=0, appearance={"appearanceId": "concrete-smooth"},
                     source=SOURCE), **patch)


def apply(doc, *operations):
    return apply_facility_layout_operations(doc, list(operations))["document"]


def corners(column):
    return [(round(p["x"], 6), round(p["z"], 6)) for p in column["footprint"]]


def test_a_rectangle_and_a_circle_get_their_outlines_and_keep_what_was_given():
    doc = apply(layout(), {"op": "set_columns", "columns": {"version": 1, "columns": [square(), round_()]}})
    rect, circle = doc["extensions"][KEY]["columns"]
    assert rect["label"] == "Column A1" and rect["appearance"] == {"color": "#8f969c"} and "source" not in rect
    assert corners(rect) == [(9.7, 4.8), (10.3, 4.8), (10.3, 5.2), (9.7, 5.2)]  # width along x, depth along z
    assert circle["source"] == SOURCE and circle["appearance"] == {"appearanceId": "concrete-smooth"}
    assert len(circle["footprint"]) == 32
    assert all(abs(math.dist((p["x"], p["z"]), (20, 5)) - 0.25) < 1e-9 for p in circle["footprint"])
    validate_columns(doc)
    validate_layout(doc)


def test_rotation_turns_a_column_as_a_compass_heading_turns():
    # 90 lays the width (along x, east) north-south, as yawDegrees turns a placement's east side south.
    turned = compile_columns({"version": 1, "columns": [square(rotationDegrees=90)]}, layout())["columns"][0]
    xs = [p["x"] for p in turned["footprint"]]
    zs = [p["z"] for p in turned["footprint"]]
    assert (round(max(xs) - min(xs), 9), round(max(zs) - min(zs), 9)) == (0.4, 0.6)
    # The width's +x end goes to -z (south), as yawDegrees 90 turns x to (cos, -sin).
    first, second = turned["footprint"][0], turned["footprint"][1]  # (-w/2, -d/2) -> (+w/2, -d/2) along the width
    assert round(second["z"] - first["z"], 9) == -0.6 and round(second["x"] - first["x"], 9) == 0


@pytest.mark.parametrize("patch", [
    {"shape": "hexagon"}, {"widthMeters": 0.01}, {"depthMeters": 6}, {"heightMeters": 0.2}, {"heightMeters": True},
    {"center": {"x": 0.1, "z": 5}}, {"center": {"x": 10}}, {"baseElevation": 2}, {"label": "  "},
    {"columnId": "c-1"}, {"appearance": {"color": "gold"}}, {"appearance": {"appearanceId": "no-such-finish"}},
    {"diameterMeters": 0.4}, {"footprint": []}, {"source": {"referenceId": "fp-main"}},
    {"source": dict(SOURCE, importId="fpi-1")}, {"source": dict(SOURCE, entityId="")},
])
def test_a_bad_column_is_refused(patch):
    with pytest.raises(ValueError):
        compile_columns({"version": 1, "columns": [square(**patch)]}, layout())


def test_ids_are_unique_and_the_limit_holds():
    with pytest.raises(ValueError, match="unique"):
        compile_columns({"version": 1, "columns": [square(), square(center={"x": 12, "z": 5})]}, layout())
    with pytest.raises(ValueError, match="At most"):
        compile_columns({"version": 1, "columns": [square(columnId=f"col-{k}") for k in range(1001)]}, layout())


def test_upsert_and_delete_change_one_column_and_keep_the_rest():
    doc = apply(layout(), {"op": "upsert_column", "column": square()}, {"op": "upsert_column", "column": round_()})
    moved = apply(doc, {"op": "upsert_column", "column": square(center={"x": 11, "z": 6}, heightMeters=6)})
    rows = {row["columnId"]: row for row in moved["extensions"][KEY]["columns"]}
    assert rows["col-a1"]["center"] == {"x": 11.0, "z": 6.0} and rows["col-a1"]["heightMeters"] == 6
    assert rows["col-b1"] == doc["extensions"][KEY]["columns"][1]
    left = apply(moved, {"op": "delete_column", "columnId": "col-b1"})
    assert [row["columnId"] for row in left["extensions"][KEY]["columns"]] == ["col-a1"]
    gone = apply(left, {"op": "delete_column", "columnId": "col-a1"})
    assert KEY not in gone["extensions"]  # the last one leaves no empty record behind
    with pytest.raises(FacilityLayoutOperationError, match="was not found"):
        apply(gone, {"op": "delete_column", "columnId": "col-a1"})
    with pytest.raises(FacilityLayoutOperationError):  # the outline is derived, never given
        apply(doc, {"op": "upsert_column", "column": dict(square(), footprint=[])})


def test_a_saved_outline_that_does_not_match_is_refused():
    doc = apply(layout(), {"op": "upsert_column", "column": square()})
    doc["extensions"][KEY]["columns"][0]["footprint"][0]["x"] = 9.0
    with pytest.raises(ValueError, match="does not match"):
        validate_columns(doc)
    with pytest.raises(FacilityValidationError):
        validate_layout(doc)


def test_columns_are_structural_obstacles_in_the_shell():
    doc = apply(layout(), {"op": "upsert_column", "column": square()}, {"op": "upsert_column", "column": round_()})
    shell = {}
    append_column_features(shell, doc)
    assert [(f["featureId"], f["featureKind"], f["geometry"]["height"]) for f in shell["features"]] == [
        (PREFIX + "col-a1", "structural_column", 8.0), (PREFIX + "col-b1", "structural_column", 8.0)]
    kinds = {f["featureId"]: f["featureKind"] for f in shell_with_plan_boundary({"features": []}, doc)["features"]}
    assert kinds[PREFIX + "col-a1"] == "structural_column"


def test_a_placement_on_a_column_collides_and_an_aisle_through_it_is_obstructed():
    doc = layout()
    doc["zones"] = []
    doc["placements"] = [{"placementId": "pl-test", "assetId": "asset-test", "assetDefinitionRevision": "a" * 64,
                          "positionMode": "manual", "metadata": {}, "snapRelationship": None,
                          "transform": {"position": {"x": 10, "y": 0, "z": 5},
                                        "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1}}]
    doc["routes"] = [{"routeId": "rt-test", "label": "Past the column", "corridorWidth": 1,
                      "centerline": [{"x": 20, "y": 0, "z": 2}, {"x": 20, "y": 0, "z": 8}],
                      "extensions": {"facilityAisle": {"aisleKind": "pedestrian"}}}]
    asset = {"assetId": "asset-test", "geometry": {
        "footprintPolygons": [[{"x": -.2, "z": -.2}, {"x": .2, "z": -.2}, {"x": .2, "z": .2}, {"x": -.2, "z": .2}]],
        "heightInterval": {"minimumY": 0, "maximumY": 1}}, "clearances": []}

    def findings(columns):  # the stub route is enough for the checks, not for a save: compile as the setter does
        value = deepcopy(doc)
        value["extensions"][KEY] = compile_columns({"version": 1, "columns": columns}, value)
        result = diagnose_layout(value, [asset], shell=shell_with_plan_boundary({"features": []}, value))
        return {(f["code"], tuple(sorted(f.get("subjectRefs") or []))) for f in result["findings"]}

    codes = {code for code, _subjects in findings([square(), round_()])}
    assert {"shell_obstacle_collision", "aisle_shell_obstructed"} <= codes
    moved = findings([square(center={"x": 30, "z": 20}), round_(center={"x": 30, "z": 25})])
    assert not {"shell_obstacle_collision", "aisle_shell_obstructed"} & {code for code, _subjects in moved}


def test_undo_of_a_column_change_is_the_saved_revision_before_it():
    # Undo restores the revision a receipt was made on (operation_proposals.prepare_undo): nothing column-specific.
    before = apply(layout(), {"op": "upsert_column", "column": square()})
    after = apply(deepcopy(before), {"op": "delete_column", "columnId": "col-a1"})
    assert before["extensions"][KEY]["columns"][0]["columnId"] == "col-a1" and KEY not in after["extensions"]
    validate_layout(before)
    validate_layout(after)


def test_sage_can_write_every_column_the_kernel_takes_and_nothing_else():
    from jsonschema import Draft202012Validator
    from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
    validator = Draft202012Validator(operation_batch_schema())

    def errors(*operations):
        return list(validator.iter_errors({"operations": list(operations)}))

    good = [{"op": "upsert_column", "column": square()}, {"op": "upsert_column", "column": round_()},
            {"op": "set_columns", "columns": {"version": 1, "columns": [square(), round_()]}},
            {"op": "set_columns", "columns": {"version": 1, "columns": []}},
            {"op": "delete_column", "columnId": "col-a1"}]
    for operation in good:
        assert not errors(operation), operation
    apply(layout(), *good[:3])  # and the kernel takes them
    bad = [{"op": "upsert_column", "column": square(appearance={"color": "#8F969C", "roughness": 1})},
           {"op": "upsert_column", "column": round_(widthMeters=1)},
           {"op": "upsert_column", "column": dict(square(), footprint=[])},
           {"op": "upsert_column", "column": square(columnId="pl-a1")},
           {"op": "set_columns", "columns": [square()]},
           {"op": "delete_column", "columnId": "iw-a1"}]
    for operation in bad:
        assert errors(operation), operation
