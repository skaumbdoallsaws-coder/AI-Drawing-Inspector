"""Entry/group expansion after preflight. Transform order is T * Rz * Ry * Rx."""
from dataclasses import dataclass, replace
import hashlib
import math

import numpy as np

from .errors import ModelBuildError, require
from .schema import PATTERNS
from .shapes import Mesh, make_shape


def rotation(value):
    x, y, z = (math.radians(value.get(a, 0)) for a in "xyz")
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return (np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]]) @ np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
            @ np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]]))


@dataclass
class Component:
    mesh: Mesh
    entry: dict
    role: str
    instance: str
    ancestors: tuple[str, ...]
    path: str = "$"
    output_name: str | None = None
    include_key: str | None = None
    include_material_key: str | None = None
    include_material: dict | None = None
    include_frame: np.ndarray | None = None
    anchorable: bool = False

    @property
    def bounds(self):
        return self.mesh.positions.min(axis=0), self.mesh.positions.max(axis=0)

    def transformed(self, matrix, offset):
        frame = self.include_frame
        if frame is not None:
            transform = np.eye(4)
            transform[:3, :3], transform[:3, 3] = matrix, offset
            frame = transform @ frame
        return replace(self, mesh=self.mesh.transformed(matrix, offset), include_frame=frame)


def bounds(components):
    return (np.min([c.bounds[0] for c in components], axis=0),
            np.max([c.bounds[1] for c in components], axis=0))


class Random:
    """Versioned SHA-256 counter stream: stable across processes and numpy releases."""
    def __init__(self, seed):
        self.seed, self.counter = seed, 0

    def uniform(self, low=0., high=1.):
        data = f"model-builder-1:{self.seed}:{self.counter}".encode("ascii")
        self.counter += 1
        unit = int.from_bytes(hashlib.sha256(data).digest()[:8], "big") / 18446744073709551616
        return low + (high-low)*unit


def _pattern(entry, components, path):
    key = next((key for key in PATTERNS if key in entry), None)
    if key is None:
        return [components]
    p, batches = entry[key], []
    low, high = bounds(components)
    center = (low+high)/2
    if key == "repeat":
        matrices = [(np.eye(3), np.asarray(p["step"])*i) for i in range(p["count"])]
    elif key == "grid":
        matrices = [(np.eye(3), np.asarray(p["step1"])*i + np.asarray(p["step2"])*j)
                    for i in range(p["count"][0]) for j in range(p["count"][1])]
    elif key == "around":
        step = p["degrees"] / (p["count"] if p["degrees"] == 360 else p["count"]-1)
        origin = np.asarray(p["center"])
        matrices = []
        for i in range(p["count"]):
            matrix = rotation({p["axis"]: i*step})
            matrices.append((matrix, origin-matrix @ origin))
    elif key == "mirror":
        matrix = np.eye(3)
        matrix["xyz".index(p["plane"]), "xyz".index(p["plane"])] = -1
        matrices = [(np.eye(3), np.zeros(3)), (matrix, np.zeros(3))]
    else:
        random = Random(p["seed"])
        minimum, maximum = np.asarray(p["within"]["min"]), np.asarray(p["within"]["max"])
        for _ in range(p["count"]):
            scale = np.array([1+random.uniform(-1, 1)*j for j in p["sizeJitter"]])
            matrix = rotation({axis: random.uniform(*p[field]) for axis, field in
                               (("y", "turnY"), ("x", "tiltX"), ("z", "tiltZ"))}) @ np.diag(scale)
            copy = [c.transformed(matrix, -matrix @ center) for c in components]
            lo, hi = bounds(copy)
            start, end = minimum-lo, maximum-hi
            require(bool(np.all(start <= end + 1e-10)), path + ".scatter.within",
                    "The rotated and jittered copy is larger than its container", "scatter_bounds_too_small")
            offset = np.array([random.uniform(a, max(a, b)) for a, b in zip(start, end)])
            batches.append([c.transformed(np.eye(3), offset) for c in copy])
        return batches
    return [[c.transformed(matrix, offset) for c in components] for matrix, offset in matrices]


def expand(recipe, includes=None):
    def visit(entry, ancestors, path):
        if "include" in entry:
            from .composition import components_for
            components = components_for(entry, ancestors, path, includes or {})
            matrix, offset = rotation({"y": entry["rotateY"]}), np.asarray(entry["position"])
        elif "group" in entry:
            components = [c for i, child in enumerate(entry["group"])
                          for c in visit(child, ancestors + (entry["id"],), f"{path}.group[{i}]")]
            matrix, offset = rotation(entry["rotate"]), np.asarray(entry["position"])
        else:
            try:
                components = [Component(mesh, entry, role, "", ancestors, path) for mesh, role in make_shape(entry)]
            except ModelBuildError as error:
                raise ModelBuildError(error.code, path + error.path[1:], error.problem) from error
            low, high = bounds(components)
            pivot = (low+high)/2
            matrix = rotation(entry["rotate"])
            offset = pivot - matrix @ pivot
        components = [c.transformed(matrix, offset) for c in components]
        result = []
        for i, batch in enumerate(_pattern(entry, components, path)):
            for component in batch:
                instance = f"{entry['id']}[{i}]" + ("/" + component.instance if component.instance else "")
                result.append(replace(component, instance=instance))
        return result

    components = [c for i, entry in enumerate(recipe["entries"]) for c in visit(entry, (), f"$.entries[{i}]")]
    for component in components:
        low, high = component.bounds
        require(bool(np.isfinite(component.mesh.positions).all()) and bool(np.all(low >= -15-1e-9))
                and bool(np.all(high <= 15+1e-9)), component.path,
                "Expanded coordinates must remain within +/-15 m", "geometry_invalid")
        points = component.mesh.positions[component.mesh.indices]
        areas = np.linalg.norm(np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0]), axis=1)
        require(bool(np.all(areas > 1e-15)), component.path,
                "Shape contains a degenerate triangle", "geometry_invalid")
    return components
