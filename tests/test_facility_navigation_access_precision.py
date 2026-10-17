"""Canonical access points must preserve both service side and clearance."""
import math
from types import SimpleNamespace

import pytest
from shapely.geometry import Point, box

from ai_inspector.facility_layout import navigation_compiler as compiler


@pytest.mark.parametrize("side", ["north", "south", "east", "west"])
def test_access_point_rounds_outward_before_free_space_check(monkeypatch, side):
    equipment = box(218.168225, 18.168225, 219.831775, 19.831775)
    monkeypatch.setattr(compiler, "placement_spatial_records", lambda *_: [
        SimpleNamespace(polygon=list(equipment.exterior.coords))])
    radius = .40360272
    low_x, low_z, high_x, high_z = equipment.bounds
    expanded = box(math.floor((low_x-radius)*1e6)/1e6,
                   math.floor((low_z-radius)*1e6)/1e6,
                   math.ceil((high_x+radius)*1e6)/1e6,
                   math.ceil((high_z+radius)*1e6)/1e6)
    free = box(202, 8, 225, 24).difference(expanded)
    points = compiler._placement_access_candidates({}, {}, free, radius, [side])
    assert len(points) == 1
    p = points[0]
    assert free.covers(Point(p["x"], p["z"]))
    assert equipment.distance(Point(p["x"], p["z"])) >= radius
    assert all(v == round(v, 6) for v in p.values())
    # A genuinely obstructed requested side cannot fall back to another side.
    blocked = free.difference(Point(p["x"], p["z"]).buffer(.01))
    assert compiler._placement_access_candidates({}, {}, blocked, radius, [side]) == []
