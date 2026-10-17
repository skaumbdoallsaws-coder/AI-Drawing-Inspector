"""Geometry and preservation checks for the authored perimeter, not building approval."""
import math
import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb, inspect_glb
from tools.add_independent_factory_walls import asset_specs, wall_segments, require_base, build_operations, JOINT


def test_perimeter_fills_only_wall_strips_except_two_openings():
    segments = wall_segments(300, 200)
    polygons = [box(*row[2]) for row in segments]
    assert len(polygons) == 6
    ring = box(0, 0, 300, 200).difference(box(.25, .25, 299.75, 199.75))
    expected = ring.difference(box(-1, 91, 1, 106)).difference(box(299, 91, 301, 106))
    for x in (0, 299.75):
        expected = expected.difference(box(x, .25, x+.25, .25+JOINT))
        expected = expected.difference(box(x, 199.75-JOINT, x+.25, 199.75))
    assert unary_union(polygons).symmetric_difference(expected).area < 1e-9
    for i, p in enumerate(polygons):
        assert all(p.intersection(q).area == 0 for q in polygons[i+1:])


@pytest.mark.parametrize("width,depth,thickness,opening", [
    (0, 200, .25, (91, 106)), (300, 90, .25, (91, 106)),
    (300, 200, 0, (91, 106)), (300, 200, .25, (106, 91)),
    (math.inf, 200, .25, (91, 106)), (300, math.nan, .25, (91, 106)),
    (300, 200, .25, (.255, 106)), (300, 200, .25, (91, 199.745)),
])
def test_invalid_dimensions_fail(width, depth, thickness, opening):
    with pytest.raises(ValueError):
        wall_segments(width, depth, thickness, opening)


def test_three_shared_meshes_are_nonblank_and_match_dimensions():
    specs = asset_specs(wall_segments(300, 200))
    assert len(specs) == 3
    for spec in specs:
        d = spec["dimensions"]
        bounds = {"minimum": {"x": -d["width"]/2, "y": 0, "z": -d["depth"]/2},
                  "maximum": {"x": d["width"]/2, "y": 6, "z": d["depth"]/2}}
        result = inspect_glb(build_aabb_proxy_glb(bounds))
        assert result.scene_triangle_count == 12
        for side in bounds:
            for axis in bounds[side]:
                assert result.aabb[side][axis] == pytest.approx(bounds[side][axis])


def test_placements_locked_and_zone_membership_remains_geometric():
    segments = wall_segments(300, 200)
    catalog = {s["assetId"]: {**s, "assetDefinitionRevision": "r"} for s in asset_specs(segments)}
    ops = build_operations(segments, catalog)
    assert len(ops) == 12
    placements = [op["placement"] for op in ops if op["op"] == "place_asset"]
    assert len({p["placementId"] for p in placements}) == 6
    assert all(p["positionMode"] == "locked" and "zoneId" not in p for p in placements)


def test_original_layout_not_a_valid_target():
    with pytest.raises(ValueError, match="refusing"):
        require_base({"layoutId": "fl-reference-manual-20260812"})


def test_stale_revision_not_a_valid_target(monkeypatch):
    import tools.add_independent_factory_walls as tool
    monkeypatch.setattr(tool, "layout_revision", lambda d: "changed")
    with pytest.raises(ValueError, match="refusing"):
        require_base({"layoutId": tool.LAYOUT_ID})
