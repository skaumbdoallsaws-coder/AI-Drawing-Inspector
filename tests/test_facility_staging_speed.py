"""Factory 02 staging speed-ups (2026-11-01): each shortcut gives what the full work gives.

The reviews skip exact geometry tests that envelopes show are False, build each shape and the review map
once, and the operation kernel hands on canonical bytes it has worked out. Each test runs the same work
with the shortcuts on and off, on items that meet a zone only along an edge, at a corner or within
rounding, and on items far from every zone.
"""
from copy import deepcopy
import math

from ai_inspector.facility_layout import diff, observation, operations, parking_review, semantic_model
from ai_inspector.facility_layout.canonical import layout_revision
from tests.test_facility_layout_operations import _fixture
from tests.test_facility_layout_semantic_model import _state
from tests.test_facility_parking_review import bay, layout as parking_layout, route as parking_route

PLAN = [{"op": "set_plan_settings", "planSettings": {
    "widthMeters": 55.0, "depthMeters": 36.0, "gridSpacingMeters": 2.0, "majorGridSpacingMeters": 10.0}}]
STAMPS = (None, "2026-11-01T12:00:00Z")


def test_the_kernel_hands_on_the_bytes_it_would_work_out_again(monkeypatch):
    layout = _fixture("empty_cell.json")
    fast = [operations.apply_facility_layout_operations(layout, PLAN, updated_at=stamp) for stamp in STAMPS]
    monkeypatch.setattr(operations, "build_exact_layout_diff",
                        lambda before, after, known_bytes=None: diff.build_exact_layout_diff(before, after))
    monkeypatch.setattr(operations, "facility_layout_diff_hash",
                        lambda after_bytes=None, **fields: diff.facility_layout_diff_hash(**fields))
    slow = [operations.apply_facility_layout_operations(layout, PLAN, updated_at=stamp) for stamp in STAMPS]
    assert slow == fast
    for result in fast:
        assert result["changed"]
        assert result["canonicalDiff"]["beforeRevision"] == layout_revision(layout)
        assert result["canonicalDiff"]["afterRevision"] == layout_revision(result["document"])
    assert fast[0]["diffHash"] != fast[1]["diffHash"]  # the stamped document is a new document


def _square(x, z, size=1.0):
    return [{"x": x, "z": z}, {"x": x + size, "z": z}, {"x": x + size, "z": z + size}, {"x": x, "z": z + size}]


def _placement(placement_id, polygon, x, z, zone_ids=()):
    value = deepcopy(_state()["placements"][0])
    value.update(
        placementId=placement_id, displayName=placement_id, zoneIds=list(zone_ids),
        transform={"position": {"x": x, "y": 0, "z": z}, "scale": 1},
        physicalGeometry=[{"recordId": f"physical:{placement_id}", "polygon": polygon, "minimumY": 0,
                           "maximumY": 1, "authoritative": True}] if polygon else [])
    return value


def _marking(marking_id, x, z, rotation=0.0):
    return {"markingId": marking_id, "markingType": "crosswalk", "semanticRole": "pedestrian_lane",
            "label": marking_id, "width": 2, "depth": 2,
            "transform": {"position": {"x": x, "y": 0, "z": z}, "rotationDegrees": rotation}}


def _route(route_id, z, x1=0, x2=20):
    return {"routeId": route_id, "label": route_id, "routeKind": "material", "corridorWidth": 3,
            "centerline": [{"x": x1, "y": 0, "z": z}, {"x": x2, "y": 0, "z": z}]}


def _edge_state():
    """_state() (zones dept-machining 0-20 x 0-10, cell-a 2-8 x 2-8, dept-automation 20-40 x 0-10) with
    items that meet a zone only along an edge or at a corner, items far from every zone, and a placement
    with no footprint whose centre is on cell-a's west edge to within point_in_polygon's tolerance."""
    state = _state()
    state["placements"] += [
        _placement("pl-edge", _square(8, 3), 8.5, 3.5, ["dept-machining"]),
        _placement("pl-corner", _square(40, 10), 40.5, 10.5),
        _placement("pl-far", _square(60, 60), 60.5, 60.5),
        _placement("pl-bare", None, 2 - 1e-10, 5),  # point_in_polygon: on the edge
    ]
    state["routes"] += [_route("rt-edge", 11.5), _route("rt-far", 80)]
    state["floorMarkings"] += [_marking("fm-corner", 21, 11), _marking("fm-tilted", 9, 9, 45),
                               _marking("fm-far", 90, 90)]
    return state


def test_the_review_map_is_the_same_without_envelopes_or_caches(monkeypatch):
    state = _edge_state()
    fast = semantic_model.build_facility_semantic_map(deepcopy(state))
    shape, facts = semantic_model._cached_scope_shape, semantic_model._placement_scope_facts
    monkeypatch.setattr(semantic_model, "_bounds_may_meet", lambda left, right: True)
    monkeypatch.setattr(semantic_model, "_point_may_be_inside", lambda point, bounds: True)
    monkeypatch.setattr(semantic_model, "_cached_scope_shape",
                        lambda cache, kind, item, build: shape({}, kind, item, build))
    monkeypatch.setattr(semantic_model, "_placement_scope_facts", lambda record, cache: facts(record, {}))
    assert semantic_model.build_facility_semantic_map(deepcopy(state)) == fast


def test_access_is_the_same_with_the_review_map_handed_in():
    state = _edge_state()
    state["assets"][0]["facilitySemantics"] = {"functionalSides": {
        "operator": {"side": "east", "evidenceStatus": "authored"},
        "front": {"side": "north", "evidenceStatus": "authored"}}}
    semantic = semantic_model.build_facility_semantic_map(state)
    kept = deepcopy(semantic)
    for role in ("operator", "front"):
        assert (semantic_model.analyze_facility_asset_access(state, interface_role=role, semantic=semantic)
                == semantic_model.analyze_facility_asset_access(state, interface_role=role))
    assert semantic == kept  # read only


def test_the_zone_index_finds_the_zones_the_scan_finds():
    zones = [
        {"zoneId": "zn-square", "boundary": _square(0, 0, 10)},
        {"zoneId": "zn-ell", "boundary": [{"x": 0, "z": 0}, {"x": 6, "z": 0}, {"x": 6, "z": 2}, {"x": 2, "z": 2},
                                          {"x": 2, "z": 6}, {"x": 0, "z": 6}]},
        {"zoneId": "zn-triangle", "boundary": [{"x": 4, "z": 4}, {"x": 10, "z": 4}, {"x": 4, "z": 10}]},
        {"zoneId": "zn-tilted", "boundary": [{"x": 5, "z": 0}, {"x": 10, "z": 5}, {"x": 5, "z": 10},
                                             {"x": 0, "z": 5}]},
        {"zoneId": "zn-line", "boundary": [{"x": 0, "z": 0}, {"x": 10, "z": 10}]},
        {"zoneId": "zn-partly-read", "boundary": [{"x": 1, "z": 1}, {"x": True, "z": 3}, {"x": 9, "z": 1},
                                                  {"x": 9, "z": 9}, "not a point"]},
        {"zoneId": "zn-empty"},
    ]
    index = observation._zone_point_index(zones)
    assert [zone_id for zone_id, _, _ in index] == [
        "zn-square", "zn-ell", "zn-triangle", "zn-tilted", "zn-partly-read"]
    values = (-3, 0, 1, 2, 3, 4, 5, 6, 7.5, 9, 10, 12)
    probes = sorted({value + step for value in values for step in (-1e-6, -1e-9, 0.0, 1e-9, 1e-6)})
    probes += [math.nan, math.inf, -math.inf]
    for x in probes:
        for z in probes:
            assert observation._zones_at(x, z, zones, index) == observation._zones_at(x, z, zones, None), (x, z)
    for unreadable in ("not a zone", {"boundary": _square(0, 0)}, {"zoneId": "zn-text", "boundary": "0,0 1,1"},
                       {"zoneId": "zn-huge", "boundary": [{"x": 10 ** 400, "z": 0}, *_square(0, 0)]}):
        assert observation._zone_point_index([*zones, unreadable]) is None


def _parked(placement_id, x, z):
    return {"placementId": placement_id, "assetId": "asset-car", "assetDefinitionRevision": "3" * 64,
            "transform": {"position": {"x": x, "y": 0, "z": z}, "rotationDegrees": 0}}


def test_the_parking_review_is_the_same_without_envelopes_or_caches(monkeypatch):
    before = parking_layout()  # zone 0-30 x 0-20, ten bays along its south edge
    marked = deepcopy(before)
    marked["floorMarkings"] += [
        dict(bay(20), transform={"position": {"x": 31.25, "y": 0, "z": 2.5}, "rotationDegrees": 0}),
        dict(bay(21), transform={"position": {"x": 30.0, "y": 0, "z": 10.0}, "rotationDegrees": 90}),
        dict(bay(22), transform={"position": {"x": 100.0, "y": 0, "z": 100.0}, "rotationDegrees": 0}),
    ]
    marked["routes"] = [parking_route(), dict(parking_route(z=23), routeId="rt-edge"),
                        dict(parking_route(z=80), routeId="rt-far")]
    marked["placements"] = [_parked("pl-in", 15, 10), _parked("pl-far", 100, 100)]
    on_edge, beside = deepcopy(before), deepcopy(before)  # each changes only by one car
    on_edge["placements"] = [_parked("pl-on-edge", 30, 10)]
    beside["placements"] = [_parked("pl-beside", 30 + 1e-9, 10)]
    changes = [(before, marked), (before, on_edge), (before, beside), (marked, on_edge)]

    def reviews():
        return ([parking_review.review_changed_parking(old, new) for old, new in changes],
                [parking_review._scope_snapshot(document, before["zones"][0]) for document in (marked, on_edge)])
    fast = reviews()
    assert fast[0][1] is not None and fast[0][2] is None  # a car on the zone's edge is in it; one beside it is not
    monkeypatch.setattr(parking_review, "_apart", lambda left, right: False)
    monkeypatch.setattr(parking_review, "_may_cover", lambda bounds, x, z: True)
    monkeypatch.setattr(parking_review, "_once", lambda cache, kind, item, build: build(item))
    assert reviews() == fast
