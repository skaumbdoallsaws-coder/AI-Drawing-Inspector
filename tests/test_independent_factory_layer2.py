"""Focused checks for the one-layout authoring audit, not Sage qualification."""
import pytest

from tools.audit_independent_factory_layer2 import (
    aisle_kind, box_purpose, build_corrections, expected_crossings, facing_quaternion,
    heading_error, marking_polygon, require_base,
)


@pytest.mark.parametrize("x,z", [(0, 3), (0, -3), (4, 0), (-4, 0), (2, 5)])
def test_heading_uses_standing_avatar_positive_z(x, z):
    origin = {"x": 0, "y": 0, "z": 0}
    target = {"x": x, "y": 0, "z": z}
    p = {"transform": {"position": origin, "quaternion": facing_quaternion(origin, target)}}
    assert heading_error(p, target) == pytest.approx(0, abs=1e-6)


def test_reversed_heading_is_not_a_pass():
    p = {"transform": {"position": {"x": 0, "z": 0}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}}}
    assert heading_error(p, {"x": 0, "z": -3}) == 180


def test_coincident_target_rejected():
    with pytest.raises(ValueError, match="coincident"):
        facing_quaternion({"x": 0, "z": 0}, {"x": 0, "z": 0})


@pytest.mark.parametrize("name,asset,expected", [
    ("R01 input", "asset-pallet-1200x1000", ("INPUT", "staging")),
    ("R01 output", "asset-pallet-1200x1000", ("OUTPUT", "staging")),
    ("Machining WIP 1", "asset-pallet-1200x1000", ("WIP", "staging")),
    ("Receiving forklift", "asset-forklift", ("FORKLIFT", "parking")),
    ("Service tooling-shelves", "asset-tooling-shelves", ("TOOLS", "staging")),
    ("Service crane-2-ton", "asset-crane-2-ton", ("CRANE", "parking")),
])
def test_floor_box_purpose_does_not_default_to_parking(name, asset, expected):
    assert box_purpose({"metadata": {"instanceLabel": name}, "assetId": asset}) == expected


def route(kind, a, b):
    return {"routeId": kind, "routeKind": "operator" if kind == "pedestrian" else "forklift",
            "extensions": {"facilityAisle": {"aisleKind": kind}}, "corridorWidth": 2 if kind == "pedestrian" else 6,
            "centerline": [{"x": a[0], "z": a[1]}, {"x": b[0], "z": b[1]}]}


def test_canonical_operator_route_is_a_pedestrian_aisle():
    walk = route("pedestrian", (5, 0), (5, 10))
    assert aisle_kind(walk) == "pedestrian"
    crossings = expected_crossings({"routes": [walk, route("forklift", (0, 5), (10, 5))]})
    assert crossings == [{"pedestrianRouteId": "pedestrian", "vehicleRouteId": "forklift", "x": 5, "z": 5,
                          "width": 2, "depth": 8, "angle": 0}]


def test_horizontal_crosswalk_rotates_along_pedestrian_travel():
    c = expected_crossings({"routes": [route("pedestrian", (0, 5), (10, 5)), route("forklift", (5, 0), (5, 10))]})[0]
    assert c["angle"] == 90
    m = {"width": c["width"], "depth": c["depth"], "transform": {"position": {"x": c["x"], "z": c["z"]}, "rotationDegrees": c["angle"]}}
    assert marking_polygon(m).bounds == pytest.approx((1, 4, 9, 6))


def test_missing_pedestrian_network_cannot_pass_vacuously():
    with pytest.raises(ValueError, match="both be present"):
        expected_crossings({"routes": [route("forklift", (0, 0), (10, 0))]})


def test_unreviewed_crossing_geometry_fails_closed():
    with pytest.raises(ValueError, match="perpendicular"):
        expected_crossings({"routes": [route("pedestrian", (0, 0), (10, 10)), route("forklift", (0, 5), (10, 5))]})


def test_wrong_layout_never_passes_save_guard():
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        require_base({"layoutId": "original-manual"})


def test_exact_revision_guard_rejects_edited_document(monkeypatch):
    import tools.audit_independent_factory_layer2 as audit
    monkeypatch.setattr(audit, "layout_revision", lambda _doc: "new-revision")
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        require_base({"layoutId": audit.LAYOUT_ID})


@pytest.mark.parametrize("name,target_name,expected_z", [
    ("Q1 inspector", "Q1 workstation", 6.9),
    ("A01 operator", "A01 assembly bench", 3.1),
])
def test_reviewed_workstation_side_is_preserved(name, target_name, expected_z):
    def asset(half_depth):
        return {"definition": {"geometry": {
            "heightInterval": {"minimumY": 0, "maximumY": 2},
            "footprintPolygons": [[{"x": -0.5, "z": -half_depth}, {"x": 0.5, "z": -half_depth},
                                   {"x": 0.5, "z": half_depth}, {"x": -0.5, "z": half_depth}]],
        }}}
    def placement(pid, aid, text, z):
        return {"placementId": pid, "assetId": aid, "assetDefinitionRevision": "rev",
                "metadata": {"instanceLabel": text}, "transform": {"scale": 1,
                    "position": {"x": 5, "y": 0, "z": z},
                    "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}}}
    doc = {"placements": [placement("person", "asset-operator", name, 0),
                          placement("bench", "asset-bench", target_name, 5)],
           "floorMarkings": [], "routes": [route("pedestrian", (0, 0), (0, 10)), route("forklift", (-5, 5), (5, 5))]}
    ops = build_corrections(doc, {("asset-operator", "rev"): asset(0.5), ("asset-bench", "rev"): asset(1)})
    move = next(o for o in ops if o["op"] == "move_placement")
    assert move["position"]["z"] == pytest.approx(expected_z)
