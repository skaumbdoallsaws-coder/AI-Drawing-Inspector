from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.edit_schemas import operation_batch_schema
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.floor_paths import compile_floor_path
from ai_inspector.facility_layout.operations import apply_facility_layout_operations


def path(shape=None):
    return {"label": "Court circle", "color": "#FFFFFF", "lineWidth": .05, "elevation": .015,
            "shape": shape or {"kind": "arc", "center": {"x": 10, "z": 10},
                               "radius": 1.8, "startDegrees": 0, "sweepDegrees": 360}}


def test_arc_is_bounded_continuous_and_matches_existing_line_rotation():
    rows = compile_floor_path(path())
    assert len(rows) == 128
    endpoints = []
    for row in rows:
        angle = math.radians(row["transform"]["rotationDegrees"])
        p = row["transform"]["position"]
        dx, dz = math.cos(angle) * row["width"]/2, -math.sin(angle) * row["width"]/2
        endpoints.append(((p["x"]-dx, p["z"]-dz), (p["x"]+dx, p["z"]+dz)))
        for x, z in endpoints[-1]:
            assert math.hypot(x-10, z-10) == pytest.approx(1.8)
    for i in range(len(rows)):
        assert endpoints[i][1] == pytest.approx(endpoints[(i+1) % len(rows)][0])
    assert endpoints[0][0] == pytest.approx((11.8, 10))


def test_polyline_closure_and_negative_arc_sweep():
    shape = {"kind": "polyline", "points": [{"x": 1, "z": 1}, {"x": 4, "z": 1},
             {"x": 4, "z": 5}], "closed": True}
    assert [row["width"] for row in compile_floor_path(path(shape))] == pytest.approx([3, 4, 5])
    shape = path()["shape"]
    shape["sweepDegrees"] = -180
    rows = compile_floor_path(path(shape))
    assert len(rows) == 64 and rows[0]["transform"]["position"]["z"] < 10


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(lineWidth=0), lambda p: p.update(color="gold"),
    lambda p: p.update(elevation=float("nan")), lambda p: p["shape"].update(radius=float("inf")),
    lambda p: p["shape"].update(sweepDegrees=0), lambda p: p["shape"].update(sweepDegrees=361),
    lambda p: p.update(shell="no"), lambda p: p.update(shape={"kind": "polyline", "closed": False,
        "points": [{"x": 1, "z": 1}, {"x": 1, "z": 1}]}),
])
def test_invalid_paths_rejected_by_domain_not_only_mcp(mutate):
    value = path()
    mutate(value)
    with pytest.raises(FacilityValidationError):
        compile_floor_path(value)


def test_path_schema_and_deterministic_operation_preserve_original_document():
    document = json.loads((Path(__file__).parent / "fixtures/facility_layout/empty_cell.json").read_text())
    before = deepcopy(document)
    operations = [{"op": "add_floor_path", "path": path()}]
    Draft202012Validator(operation_batch_schema()).validate({"operations": operations})
    first = apply_facility_layout_operations(document, operations)
    second = apply_facility_layout_operations(document, operations)
    assert first == second and document == before
    assert len(first["createdIds"]) == 128
    assert len(set(first["createdIds"])) == 128
