"""Basic shapes for authored assets (docs/sage-basic-shapes-plan.md, BS0).

Meshes made of flat faces (boxes, prisms, bars) and the self-contained GLB 2.0 that carries them, moved here from
the hand-built Factory 02 generators of 2026-10-30 (barriers, columns, roof frame, roof services). Their rules hold
for every model built with this module:
- a face winds counter-clockwise seen from outside, the side its normal points to (`Mesh.face` makes sure of it);
- a model is centred on x and z with its base at y = 0 and its length along x, so placements stay yaw-only
  (`on_floor` moves it there);
- thin bars get 4 sides and no caps, which keeps triangle counts low;
- every material carries extras.facilityAuthoredFinish, without which the facility 3D view paints it neutral gray.
`verify` checks a finished GLB against all of that and against its declared size.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import struct
from typing import Any, Iterable, Sequence

GENERATOR = "InspectorPro ai_inspector/industrial_assets/primitives.py"
SIZE_TOLERANCE = 2e-4   # metres: float32 positions in a model up to 400 m long
FACES = ("+x", "-x", "+y", "-y", "+z", "-z")
_AXES = {"x": 0, "y": 1, "z": 2}


def linear(color: str) -> list[float]:
    """'#rrggbb' (sRGB) as the linear channels glTF stores a base colour in."""
    if not (isinstance(color, str) and len(color) == 7 and color[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
        raise ValueError(f"A colour is '#rrggbb', not {color!r}")

    def channel(text):
        value = int(text, 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return [round(channel(color[i:i + 2]), 5) for i in (1, 3, 5)]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(vector):
    length = math.sqrt(_dot(vector, vector))
    if not length or not math.isfinite(length):
        raise ValueError(f"No direction in {vector!r}")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _newell(points):
    """Twice the area vector of a polygon, pointing to the side it winds counter-clockwise around."""
    nx = ny = nz = 0.0
    for index, (x0, y0, z0) in enumerate(points):
        x1, y1, z1 = points[(index + 1) % len(points)]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return (nx, ny, nz)


def _f32(value: float) -> float:
    """The value as float32 stores it, so accessor bounds match the packed positions exactly."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


class Mesh:
    """One part's positions, normals and triangles, in model metres with y up."""

    def __init__(self) -> None:
        self.positions: list[tuple[float, float, float]] = []
        self.normals: list[tuple[float, float, float]] = []
        self.indices: list[int] = []

    @property
    def triangles(self) -> int:
        return len(self.indices) // 3

    def face(self, corners: Sequence[Sequence[float]], normal: Sequence[float], *,
             vertex_normals: Sequence[Sequence[float]] | None = None) -> None:
        """A flat convex polygon facing `normal`, as a triangle fan. Its corners may come in either order: they are
        turned to wind counter-clockwise seen from the side `normal` points to. `vertex_normals` (one per corner)
        shade it smooth instead of flat. A face with no area is left out."""
        corners = [(float(c[0]), float(c[1]), float(c[2])) for c in corners]
        if len(corners) < 3:
            raise ValueError("A face needs at least 3 corners")
        facing = _unit(normal)
        area = _newell(corners)
        if math.sqrt(_dot(area, area)) < 1e-12:
            return
        normals = [_unit(n) for n in vertex_normals] if vertex_normals is not None else [facing] * len(corners)
        if len(normals) != len(corners):
            raise ValueError("One vertex normal per corner")
        if _dot(area, facing) < 0:
            corners, normals = corners[::-1], normals[::-1]
        start = len(self.positions)
        self.positions += corners
        self.normals += normals
        for k in range(1, len(corners) - 1):
            self.indices += [start, start + k, start + k + 1]

    def box(self, lo: Sequence[float], hi: Sequence[float], *, skip: Iterable[str] = ()) -> None:
        """An axis-aligned box from corner `lo` to corner `hi`. `skip` leaves out faces by name ('+x', '-x', '+y',
        '-y', '+z', '-z'), for faces that sit against another part and can never be seen."""
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        if not (x0 < x1 and y0 < y1 and z0 < z1):
            raise ValueError(f"A box needs lo < hi on every axis, not {lo!r} to {hi!r}")
        skip = set(skip)
        if skip - set(FACES):
            raise ValueError(f"Unknown box faces {sorted(skip - set(FACES))}")
        faces = {"+x": ([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], (1, 0, 0)),
                 "-x": ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1, 0, 0)),
                 "+y": ([(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)], (0, 1, 0)),
                 "-y": ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
                 "+z": ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
                 "-z": ([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], (0, 0, -1))}
        for name, (corners, normal) in faces.items():
            if name not in skip:
                self.face(corners, normal)

    def prism(self, axis: str, centre: Sequence[float], radius: float, start: float, end: float, *,
              sides: int = 8, caps: bool = True, smooth: bool = False) -> None:
        """A regular bar with `sides` flat sides along `axis` ('x', 'y' or 'z'), from `start` to `end` on it.

        `centre` places it on the other two axes, in x, y, z order (for 'y' it is (x, z)). `radius` is the distance
        from the axis to each flat: with `sides` a multiple of 4 the flats face the other two axes, so the bar is
        exactly 2 * radius across them. `smooth` shades the sides round (normals straight out from the axis), for
        tanks and pipes; `caps` closes the ends.
        """
        if axis not in _AXES or sides < 3 or not radius > 0 or not start < end:
            raise ValueError(f"A prism needs an axis x, y or z, 3 or more sides, a radius and start < end")
        along = _AXES[axis]
        u_axis, v_axis = [k for k in range(3) if k != along]
        corner = radius / math.cos(math.pi / sides)
        ring = [(corner * math.cos(math.pi * (2 * k + 1) / sides), corner * math.sin(math.pi * (2 * k + 1) / sides))
                for k in range(sides)]

        def point(u, v, t):
            p = [0.0, 0.0, 0.0]
            p[along], p[u_axis], p[v_axis] = t, centre[0] + u, centre[1] + v
            return tuple(p)

        def direction(u, v):
            d = [0.0, 0.0, 0.0]
            d[u_axis], d[v_axis] = u, v
            return tuple(d)
        for k in range(sides):
            (u0, v0), (u1, v1) = ring[k], ring[(k + 1) % sides]
            shading = [direction(u0, v0), direction(u1, v1), direction(u1, v1), direction(u0, v0)] if smooth else None
            self.face([point(u0, v0, start), point(u1, v1, start), point(u1, v1, end), point(u0, v0, end)],
                      direction((u0 + u1) / 2, (v0 + v1) / 2), vertex_normals=shading)
        if caps:
            out = [0.0, 0.0, 0.0]
            out[along] = 1.0
            self.face([point(u, v, end) for u, v in ring], tuple(out))
            self.face([point(u, v, start) for u, v in ring], tuple(-c for c in out))

    def bar(self, start: Sequence[float], end: Sequence[float], width: float, height: float | None = None, *,
            caps: bool = False) -> None:
        """A straight bar of rectangular section between two points: its 4 sides, and its ends only with `caps`.

        `width` is measured across the bar horizontally and `height` (default: `width`, a square bar) in the
        upright plane through it; for an upright bar `width` runs along x and `height` along z.
        """
        start = tuple(float(c) for c in start)
        end = tuple(float(c) for c in end)
        if not width > 0 or not (height is None or height > 0):
            raise ValueError("A bar needs a positive width and height")
        d = _unit(_sub(end, start))
        u = _unit(_cross(d, (0.0, 0.0, 1.0) if abs(d[1]) > 0.99 else (0.0, 1.0, 0.0)))
        v = _cross(u, d)
        hw, hh = width / 2, (height if height is not None else width) / 2

        def p(base, a, b):
            return tuple(base[k] + a * u[k] + b * v[k] for k in range(3))
        for corners, normal in (
                ([p(start, hw, -hh), p(end, hw, -hh), p(end, hw, hh), p(start, hw, hh)], u),
                ([p(start, -hw, -hh), p(end, -hw, -hh), p(end, -hw, hh), p(start, -hw, hh)], tuple(-c for c in u)),
                ([p(start, -hw, hh), p(end, -hw, hh), p(end, hw, hh), p(start, hw, hh)], v),
                ([p(start, -hw, -hh), p(end, -hw, -hh), p(end, hw, -hh), p(start, hw, -hh)], tuple(-c for c in v))):
            self.face(corners, normal)
        if caps:
            for base, normal in ((end, d), (start, tuple(-c for c in d))):
                self.face([p(base, -hw, -hh), p(base, hw, -hh), p(base, hw, hh), p(base, -hw, hh)], normal)

    def move(self, dx: float, dy: float, dz: float) -> None:
        self.positions = [(x + dx, y + dy, z + dz) for x, y, z in self.positions]


@dataclass(frozen=True)
class Finish:
    """A part's material: base colour ('#rrggbb'), metalness and roughness, plus any other glTF material fields
    (an emissiveFactor for a lamp lens) and extras (facilityDefaultFinish, ...)."""
    color: str
    metalness: float = 0.0
    roughness: float = 0.55
    fields: dict = field(default_factory=dict, hash=False)
    extras: dict = field(default_factory=dict, hash=False)


Part = tuple  # (name, Mesh, Finish or '#rrggbb'): the name becomes the material's role


def bounds(parts: Sequence[Part]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    points = [p for _, mesh, _ in parts for p in mesh.positions]
    if not points:
        raise ValueError("The model has no geometry")
    return (tuple(min(p[k] for p in points) for k in range(3)), tuple(max(p[k] for p in points) for k in range(3)))


def size_of(parts: Sequence[Part]) -> dict[str, float]:
    """The model's width (x), height (y) and depth (z) in metres, as a catalog entry's dimensions."""
    lo, hi = bounds(parts)
    return {"width": hi[0] - lo[0], "height": hi[1] - lo[1], "depth": hi[2] - lo[2]}


def on_floor(parts: Sequence[Part]) -> list[Part]:
    """Moves every part together so the model is centred on x and z with its lowest point at y = 0."""
    lo, hi = bounds(parts)
    shift = (-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2)
    for _, mesh, _ in parts:
        mesh.move(*shift)
    return list(parts)


def glb(parts: Sequence[Part], root: str, *, generator: str = GENERATOR) -> bytes:
    """The GLB 2.0 bytes: one node per part under a root node, one material per part named after it and marked as
    an authored finish. The same parts always give the same bytes."""
    kept = [(name, mesh, finish if isinstance(finish, Finish) else Finish(finish))
            for name, mesh, finish in parts if mesh.triangles]
    if not kept:
        raise ValueError("A model needs at least one triangle")
    names = [name for name, _, _ in kept]
    if len(set(names)) != len(names) or not all(isinstance(name, str) and name for name in names):
        raise ValueError(f"Each part needs its own name, not {names!r}")
    doc: dict[str, Any] = {
        "asset": {"generator": generator, "version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"children": [], "name": root}], "meshes": [], "materials": [], "accessors": [], "bufferViews": []}
    blob = bytearray()

    def view(data: bytes, target: int) -> int:
        blob.extend(b"\0" * (-len(blob) % 4))
        doc["bufferViews"].append({"buffer": 0, "byteLength": len(data), "byteOffset": len(blob), "target": target})
        blob.extend(data)
        return len(doc["bufferViews"]) - 1

    for name, mesh, finish in kept:
        positions = [_f32(round(c, 6) + 0.0) for p in mesh.positions for c in p]
        normals = [round(c, 6) + 0.0 for n in mesh.normals for c in n]
        count = len(mesh.positions)
        wide = count > 65535
        first = len(doc["accessors"])
        doc["accessors"] += [
            {"bufferView": view(struct.pack(f"<{len(positions)}f", *positions), 34962), "componentType": 5126,
             "count": count, "type": "VEC3",
             "max": [max(positions[k::3]) for k in range(3)], "min": [min(positions[k::3]) for k in range(3)]},
            {"bufferView": view(struct.pack(f"<{len(normals)}f", *normals), 34962), "componentType": 5126,
             "count": count, "type": "VEC3"},
            {"bufferView": view(struct.pack(f"<{len(mesh.indices)}{'I' if wide else 'H'}", *mesh.indices), 34963),
             "componentType": 5125 if wide else 5123, "count": len(mesh.indices), "type": "SCALAR"}]
        doc["materials"].append({
            **finish.fields, "name": name,
            "extras": {**finish.extras, "facilityAuthoredFinish": True, "facilityMaterialRole": name},
            "pbrMetallicRoughness": {"baseColorFactor": linear(finish.color) + [1.0],
                                     "metallicFactor": finish.metalness, "roughnessFactor": finish.roughness}})
        doc["meshes"].append({"name": name, "primitives": [{
            "attributes": {"NORMAL": first + 1, "POSITION": first}, "indices": first + 2,
            "material": len(doc["materials"]) - 1, "mode": 4}]})
        doc["nodes"].append({"mesh": len(doc["meshes"]) - 1, "name": name})
        doc["nodes"][0]["children"].append(len(doc["nodes"]) - 1)
    blob.extend(b"\0" * (-len(blob) % 4))
    doc["buffers"] = [{"byteLength": len(blob)}]
    text = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("ascii")
    text += b" " * (-len(text) % 4)
    body = struct.pack("<I4s", len(text), b"JSON") + text + struct.pack("<I4s", len(blob), b"BIN\0") + bytes(blob)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def gltf_json(payload: bytes) -> dict:
    """The JSON chunk of GLB bytes."""
    length = struct.unpack_from("<I", payload, 12)[0]
    return json.loads(payload[20:20 + length])


def verify(payload: bytes, dimensions: dict | None = None) -> dict:
    """The checks a model passes before it is published, as the Factory 02 generators ran them.

    A valid static GLB 2.0 (the catalog's own inspector), centred on x and z with its base at y = 0, the declared
    size when given (width along x, height y, depth z), and every material marked as an authored finish. Returns
    {'dimensions', 'triangles', 'bytes'}; raises ValueError.
    """
    from .artifacts import ArtifactValidationError, inspect_glb
    try:
        info = inspect_glb(bytes(payload))
    except ArtifactValidationError as exc:
        raise ValueError(f"Not a valid GLB: {exc}") from None
    lo, hi = info.aabb["minimum"], info.aabb["maximum"]
    size = {"width": hi["x"] - lo["x"], "height": hi["y"] - lo["y"], "depth": hi["z"] - lo["z"]}
    if abs(lo["y"]) > SIZE_TOLERANCE:
        raise ValueError(f"The model's base is at y = {lo['y']:.4f}, not 0")
    if abs(lo["x"] + hi["x"]) > SIZE_TOLERANCE or abs(lo["z"] + hi["z"]) > SIZE_TOLERANCE:
        raise ValueError("The model is not centred on x and z")
    for key, value in (dimensions or {}).items():
        if abs(size[key] - float(value)) > SIZE_TOLERANCE:
            raise ValueError(f"The model's {key} is {size[key]:.4f} m, not the declared {float(value):.4f} m")
    unmarked = [m.get("name") for m in gltf_json(payload).get("materials", [])
                if not (m.get("extras") or {}).get("facilityAuthoredFinish")]
    if unmarked:
        raise ValueError(f"Materials without extras.facilityAuthoredFinish (the 3D view paints them gray): {unmarked}")
    return {"dimensions": {key: round(value, 4) for key, value in size.items()},
            "triangles": info.scene_triangle_count, "bytes": len(payload)}
