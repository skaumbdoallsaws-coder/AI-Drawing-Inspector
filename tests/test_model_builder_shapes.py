"""Geometry contracts: bounds, local winding, closure, counts and transforms."""
from collections import Counter
import math

import numpy as np
import pytest

from tests.model_builder_test_support import module, recipe, shape

normalize = module("recipe").normalize_recipe
shapes = module("shapes")
scene = module("scene")
Error = module("errors").ModelBuildError


def meshes(entry):
    return shapes.make_shape(normalize(recipe(entry))["entries"][0])


def signed_volume(mesh):
    a, b, c = np.moveaxis(mesh.positions[mesh.indices], 1, 0)
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


def assert_manifold(mesh):
    """Weld split face vertices, then demand two opposite uses of every edge."""
    vertices = [tuple(np.round(p, 9)) for p in mesh.positions]
    edges = Counter()
    directed = Counter()
    for triangle in mesh.indices:
        points = [vertices[i] for i in triangle]
        assert len(set(points)) == 3
        for a, b in zip(points, points[1:] + points[:1]):
            edges[tuple(sorted((a, b)))] += 1
            directed[(a, b)] += 1
    assert set(edges.values()) == {2}
    assert all(count == directed[(b, a)] for (a, b), count in directed.items())
    assert signed_volume(mesh) > 0


CASES = [
    (shape(), [-.5, 0, -.5], [.5, 1, .5], 12),
    (shape("cylinder"), [-.5, 0, -.5], [.5, 1, .5], 96),
    (shape("cylinder", radiusTo=.25), [-.5, 0, -.5], [.5, 1, .5], 96),
    (shape("cylinder", radiusTo=0), [-.5, 0, -.5], [.5, 1, .5], 48),
    (shape("cylinder", hollow=.05), [-.5, 0, -.5], [.5, 1, .5], 192),
    (shape("tube"), [-.1, 0, -.1], [.1, 1, .1], 48),
    (shape("tube", path=[[0, 0, 0], [0, 1, 0], [1, 1, 0]], sides=8),
     [-.1, 0, -.1], [1, 1.1, .1], 48),
    (shape("lathe"), [-.5, 0, -.5], [.5, 1, .5], 128),
    (shape("lathe", profile=[[.5, 0], [.5, 1], [.3, 1], [.3, 0]]),
     [-.5, 0, -.5], [.5, 1, .5], 256),
    (shape("torus"), [-.6, -.1, -.6], [.6, .1, .6], 384),
    (shape("sphere"), [-1, -2, -3], [1, 2, 3], 528),
    (shape("sphere", part="upper"), [-1, 0, -3], [1, 2, 3], 288),
    (shape("sphere", part="lower"), [-1, -2, -3], [1, 0, 3], 288),
    (shape("extrude"), [0, 0, 0], [1, 1, .2], 12),
    (shape("extrude", plane="zy"), [0, 0, 0], [.2, 1, 1], 12),
    (shape("extrude", plane="xz"), [0, 0, 0], [1, .2, 1], 12),
    (shape("extrude", profile=[[0, 0], [1, 0], [1, .3], [.3, .3], [.3, 1], [0, 1]]),
     [0, 0, 0], [1, 1, .2], 20),
]


@pytest.mark.parametrize("entry,low,high,count", CASES, ids=[
    "box", "cylinder", "frustum", "cone", "pipe", "tube", "miter", "lathe", "hollow-lathe",
    "torus", "sphere", "upper-sphere", "lower-sphere", "extrude-xy", "extrude-zy", "extrude-xz", "concave-extrude"])
def test_shape_bounds_closed_winding_and_exact_triangle_estimate(entry, low, high, count):
    normalized = normalize(recipe(entry))["entries"][0]
    mesh, _ = shapes.make_shape(normalized)[0]
    assert mesh.positions.min(axis=0) == pytest.approx(low, abs=1e-10)
    assert mesh.positions.max(axis=0) == pytest.approx(high, abs=1e-10)
    assert mesh.closed
    assert len(mesh.indices) == module("budgets").triangles(normalized) == count
    assert_manifold(mesh)
    if entry["shape"] == "box":
        assert signed_volume(mesh) == pytest.approx(1)


@pytest.mark.parametrize("hollow", [False, True])
@pytest.mark.parametrize("caps,solid_count,hollow_count", [("none", 48, 96), ("start", 72, 144),
                                                         ("end", 72, 144), ("both", 96, 192)])
def test_cylinder_caps_and_open_boundaries(hollow, caps, solid_count, hollow_count):
    entry = shape("cylinder", caps=caps, **({"hollow": .05} if hollow else {}))
    mesh, _ = meshes(entry)[0]
    assert len(mesh.indices) == (hollow_count if hollow else solid_count)
    assert mesh.closed == (caps == "both")
    # Even the open skin must have consistent outward radial winding.
    for triangle in mesh.indices:
        a, b, c = mesh.positions[triangle]
        normal = np.cross(b-a, c-a)
        centroid = (a+b+c)/3
        if abs(normal[1]) < 1e-9:
            radial = normal @ np.array([centroid[0], 0, centroid[2]])
            radii = np.linalg.norm(mesh.positions[triangle][:, [0, 2]], axis=1)
            assert radial < 0 if hollow and max(radii) < .49 else radial > 0


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_axis_mapping_is_proper_and_closed(axis):
    for entry in (shape("torus", axis=axis), shape("lathe", axis=axis)):
        mesh, _ = meshes(entry)[0]
        assert_manifold(mesh)
    assert np.linalg.det(shapes.axis_matrix(axis)) == pytest.approx(1)


def test_diagonal_cylinder_exact_axis_and_volume():
    a, b = np.array([1., 2, 3]), np.array([2., 4, 5])
    entry = shape("cylinder", **{"from": a.tolist(), "to": b.tolist()}, radius=.2)
    mesh, _ = meshes(entry)[0]
    axis = (b-a) / np.linalg.norm(b-a)
    distance = (mesh.positions-a) @ axis
    assert min(distance) == pytest.approx(0, abs=1e-10)
    assert max(distance) == pytest.approx(3)
    assert_manifold(mesh)
    assert signed_volume(mesh) == pytest.approx(24/2 * math.sin(math.tau/24) * .2**2 * 3)


def test_closed_tube_is_manifold_and_reversing_path_is_refused():
    mesh, _ = meshes(shape("tube", path=[[0,0,0], [0,1,0], [1,1,0], [1,0,0]],
                           closed=True, sides=8))[0]
    assert_manifold(mesh)
    assert len(mesh.indices) == 64
    with pytest.raises(Error) as caught:
        scene.expand(normalize(recipe(shape("tube", path=[[0,0,0], [0,1,0], [0,0,0]]))))
    assert caught.value.code == "geometry_invalid"
    assert caught.value.path == "$.entries[0].path"


@pytest.mark.parametrize("facing,normal", [("+z", [0,0,1]), ("-z", [0,0,-1]), ("+x", [1,0,0]),
                                         ("-x", [-1,0,0]), ("+y", [0,1,0])])
def test_panel_plate_thickness_face_gap_and_uv(facing, normal):
    entry = shape("panel", center=[0, 0, 0], size=[.36, .2], facing=facing)
    (back, role), (front, print_role) = meshes(entry)
    assert role == "back" and print_role == "print"
    assert_manifold(back)
    assert len(back.indices) == 12 and len(front.indices) == 2
    assert front.closed is False
    assert (back.positions @ normal).min() == pytest.approx(-.0025)
    assert (back.positions @ normal).max() == pytest.approx(-.0005)
    assert front.positions @ normal == pytest.approx([0]*4)
    assert set(map(tuple, front.uv)) == {(0, 0), (0, 1), (1, 0), (1, 1)}
    a, b, c = front.positions[front.indices[0]]
    assert np.cross(b-a, c-a) @ normal > 0


def test_nested_transform_order_shape_pivot_then_group_then_parent_pattern():
    # The 2 x 1 x .5 box rotates around its own centre (1, .5, 0).
    entry = shape(min=[0,0,-.25], max=[2,1,.25], rotate={"z": 90})
    inner = {"id": "inner", "group": [entry], "position": [1, 0, 0], "rotate": {"y": 90}}
    outer = {"id": "outer", "group": [inner], "position": [0, 2, 0], "rotate": {"x": 90},
             "repeat": {"count": 2, "step": [3, 0, 0]}}
    pieces = scene.expand(normalize(recipe(outer)))
    assert len(pieces) == 2
    low, high = pieces[0].bounds
    assert low == pytest.approx([.75, 2.5, -.5])
    assert high == pytest.approx([1.25, 3.5, 1.5])
    assert pieces[1].bounds[0] == pytest.approx(low + [3, 0, 0])
    assert pieces[0].instance == "outer[0]/inner[0]/body[0]"
    for piece in pieces:
        assert_manifold(piece.mesh)


def test_rotation_order_xyz_is_not_commuted():
    matrix = scene.rotation({"x": 90, "y": 90, "z": 90})
    assert matrix @ np.array([1,2,3]) == pytest.approx([3,2,-1])


@pytest.mark.parametrize("degrees,expected", [
    (360, [[1,0,0], [0,0,-1], [-1,0,0], [0,0,1]]),
    (180, [[1,0,0], [.5,0,-math.sqrt(3)/2], [-.5,0,-math.sqrt(3)/2], [-1,0,0]])])
def test_around_spacing_copy_zero_and_no_duplicate_full_turn(degrees, expected):
    entry = {"id": "peg", "name": "peg", "shape": "box", "material": "paint",
             "center": [1,0,0], "size": [.1,.1,.1],
             "around": {"count": 4, "axis": "y", "center": [0,0,0], "degrees": degrees}}
    pieces = scene.expand(normalize(recipe(entry)))
    centers = [(c.bounds[0]+c.bounds[1])/2 for c in pieces]
    assert np.asarray(centers) == pytest.approx(np.asarray(expected), abs=1e-10)


def test_grid_copy_order_and_positions():
    entry = shape(grid={"count": [2,3], "step1": [2,0,0], "step2": [0,0,2]})
    pieces = scene.expand(normalize(recipe(entry)))
    centers = [(c.bounds[0]+c.bounds[1])/2 for c in pieces]
    assert np.asarray(centers) == pytest.approx(np.array([[0,.5,0], [0,.5,2], [0,.5,4],
                                                       [2,.5,0], [2,.5,2], [2,.5,4]]))


@pytest.mark.parametrize("plane,facing", [("x", [0,0,1]), ("z", [0,0,-1])])
def test_mirror_winding_and_unmirrored_print_handedness(plane, facing):
    entry = shape("panel", center=[1,.5,1], mirror={"plane": plane}, print={
        "background": "#000000", "items": [{"text": "F1", "box": [0,0,1,1], "color": "#ffffff"}]})
    pieces = scene.expand(normalize(recipe(entry)))
    assert len(pieces) == 4
    for c in pieces:
        if c.role == "back":
            assert_manifold(c.mesh)
    original, mirrored = [c.mesh for c in pieces if c.role == "print"]
    a, b, c = mirrored.positions[mirrored.indices[0]]
    normal = np.cross(b-a, c-a)
    normal /= np.linalg.norm(normal)
    assert normal == pytest.approx(facing)
    for mesh in (original, mirrored):
        tri = mesh.indices[0]
        # Texture-space handedness relative to the visible front stays identical.
        q = mesh.uv[tri]
        assert np.linalg.det(np.array([q[1]-q[0], q[2]-q[0]])) < 0


def test_scatter_deterministic_jitter_and_all_corners_within():
    entry = shape(scatter={"count": 30, "seed": 42, "within": {"min": [-2,0,-2], "max": [2,4,2]},
                           "sizeJitter": [.3,.2,.1], "turnY": [-60,60], "tiltX": [-10,10], "tiltZ": [-10,10]})
    normalized = normalize(recipe(entry))
    first, second = scene.expand(normalized), scene.expand(normalized)
    assert len(first) == 30
    for a, b in zip(first, second):
        assert np.array_equal(a.mesh.positions, b.mesh.positions)
        assert np.all(a.bounds[0] >= [-2,0,-2]) and np.all(a.bounds[1] <= [2,4,2])
        assert_manifold(a.mesh)
    entry["scatter"]["seed"] = 43
    assert not np.array_equal(first[0].mesh.positions, scene.expand(normalize(recipe(entry)))[0].mesh.positions)
    entry["scatter"]["turnY"] = entry["scatter"]["tiltX"] = entry["scatter"]["tiltZ"] = [0,0]
    widths = np.array([c.bounds[1]-c.bounds[0] for c in scene.expand(normalize(recipe(entry)))])
    assert np.all(widths >= [.7,.8,.9]) and np.all(widths <= [1.3,1.2,1.1])
    assert np.ptp(widths, axis=0).min() > .1
    entry["scatter"]["within"] = {"min": [0,0,0], "max": [.1,.1,.1]}
    with pytest.raises(Error) as caught:
        scene.expand(normalize(recipe(entry)))
    assert caught.value.code == "scatter_bounds_too_small"
    assert caught.value.path == "$.entries[0].scatter.within"
