"""Small geometry kit for the kitchen models: boxes, lathed pots, spheres, swept tubes and textured quads as
glbsrc Parts (metres, Y up). Parts with the same role are merged before writing."""
import math
import sys
from pathlib import Path

import numpy as np

OLD = Path(r"C:\Users\might\AppData\Local\Temp\claude\C--Users-might-OneDrive-Desktop-InspectorPro"
           r"\92fab758-6b88-4741-8a85-402de6eda6c9\scratchpad")
sys.path.insert(0, str(OLD))
import glbsrc as S  # noqa: E402


def linear(hex_color):
    h = hex_color.lstrip("#")
    out = []
    for k in range(3):
        c = int(h[2 * k:2 * k + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out + [1.0]


def material(name, color="#cccccc", roughness=0.6, metallic=0.0, image=None, emissive=None, blend=False):
    m = S.Material(name, color=linear(color) if isinstance(color, str) else list(color), roughness=roughness,
                   metallic=metallic, image=image, emissive=emissive, blend=blend)
    return m


class Builder:
    """Collects triangles per role; parts() gives one Part per role (flat normals unless given)."""

    def __init__(self):
        self.roles = {}   # role -> dict(P=[], N=[], U=[], I=[], material=...)

    def _role(self, role, mat):
        if role not in self.roles:
            self.roles[role] = {"P": [], "N": [], "U": [], "I": [], "n": 0, "material": mat, "uv": True}
        return self.roles[role]

    def add(self, role, mat, P, I, N=None, U=None):
        r = self._role(role, mat)
        P = np.asarray(P, float)
        r["I"].append(np.asarray(I, np.int64).ravel() + r["n"])
        r["P"].append(P)
        r["N"].append(None if N is None else np.asarray(N, float))
        if U is None:
            r["uv"] = False
        r["U"].append(None if U is None else np.asarray(U, float))
        r["n"] += len(P)

    def box(self, role, mat, lo, hi, faces="all"):
        (x0, y0, z0), (x1, y1, z1) = lo, hi
        quads = {
            "+x": ([(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)], (1, 0, 0)),
            "-x": ([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], (-1, 0, 0)),
            "+y": ([(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)], (0, 1, 0)),
            "-y": ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], (0, -1, 0)),
            "+z": ([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], (0, 0, 1)),
            "-z": ([(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)], (0, 0, -1)),
        }
        for key, (corners, n) in quads.items():
            if faces != "all" and key not in faces:
                continue
            P = np.array(corners, float)
            U = np.array([(0, 1), (1, 1), (1, 0), (0, 0)], float)
            self.add(role, mat, P, [0, 1, 2, 0, 2, 3], N=[n] * 4, U=U)

    def quad(self, role, mat, corners, normal, uv=((0, 1), (1, 1), (1, 0), (0, 0))):
        self.add(role, mat, corners, [0, 1, 2, 0, 2, 3], N=[normal] * 4, U=uv)

    def lathe(self, role, mat, profile, centre=(0, 0, 0), segments=40, cap_top=False, cap_bottom=True):
        """Revolve [(radius, y), ...] (bottom to top, outside then inside if a wall) round Y at CENTRE."""
        cx, cy, cz = centre
        prof = np.asarray(profile, float)
        rings = len(prof)
        P, U = [], []
        for i in range(segments + 1):
            a = 2 * math.pi * i / segments
            ca, sa = math.cos(a), math.sin(a)
            for j, (r, y) in enumerate(prof):
                P.append((cx + r * ca, cy + y, cz + r * sa))
                U.append((i / segments, j / max(1, rings - 1)))
        I = []
        for i in range(segments):
            for j in range(rings - 1):
                a = i * rings + j
                b = (i + 1) * rings + j
                I += [a, a + 1, b, b, a + 1, b + 1]
        self.add(role, mat, P, I, U=U)
        if cap_bottom and prof[0][0] > 1e-6:
            self.disc(role, mat, (cx, cy + prof[0][1], cz), prof[0][0], down=True, segments=segments)
        if cap_top and prof[-1][0] > 1e-6:
            self.disc(role, mat, (cx, cy + prof[-1][1], cz), prof[-1][0], down=False, segments=segments)

    def disc(self, role, mat, centre, radius, down=False, segments=40):
        cx, cy, cz = centre
        P = [(cx, cy, cz)] + [(cx + radius * math.cos(2 * math.pi * i / segments), cy,
                               cz + radius * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
        I = []
        for i in range(segments):
            a, b = 1 + i, 1 + (i + 1) % segments
            I += [0, a, b] if down else [0, b, a]
        U = [(0.5, 0.5)] + [(0.5 + 0.5 * math.cos(2 * math.pi * i / segments),
                             0.5 + 0.5 * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
        self.add(role, mat, P, I, N=[(0, -1 if down else 1, 0)] * len(P), U=U)

    def ellipsoid(self, role, mat, centre, radii, rings=14, segments=20, squash=None):
        cx, cy, cz = centre
        rx, ry, rz = radii
        P, N, I = [], [], []
        for j in range(rings + 1):
            v = math.pi * j / rings
            for i in range(segments + 1):
                u = 2 * math.pi * i / segments
                n = (math.sin(v) * math.cos(u), -math.cos(v), math.sin(v) * math.sin(u))
                k = 1.0 if squash is None else squash(n)
                P.append((cx + rx * n[0] * k, cy + ry * n[1] * k, cz + rz * n[2] * k))
                N.append(n)
        for j in range(rings):
            for i in range(segments):
                a = j * (segments + 1) + i
                b = a + segments + 1
                I += [a, b, a + 1, a + 1, b, b + 1]
        self.add(role, mat, P, I, N=N)

    def tube(self, role, mat, path, radius, sides=12, caps=True):
        """A round tube along PATH (list of 3D points)."""
        path = np.asarray(path, float)
        P, I = [], []
        up = np.array([0.0, 1.0, 0.0])
        frames = []
        for k in range(len(path)):
            t = path[min(k + 1, len(path) - 1)] - path[max(k - 1, 0)]
            t /= np.linalg.norm(t)
            ref = up if abs(t @ up) < 0.9 else np.array([1.0, 0, 0])
            n = np.cross(t, ref)
            n /= np.linalg.norm(n)
            b = np.cross(t, n)
            frames.append((n, b))
        for k, c in enumerate(path):
            n, b = frames[k]
            for s in range(sides):
                a = 2 * math.pi * s / sides
                P.append(c + radius * (math.cos(a) * n + math.sin(a) * b))
        for k in range(len(path) - 1):
            for s in range(sides):
                a, b2 = k * sides + s, k * sides + (s + 1) % sides
                c, d = a + sides, b2 + sides
                I += [a, c, b2, b2, c, d]
        self.add(role, mat, P, I)

    def cylinder(self, role, mat, centre, radius, y0, y1, segments=24):
        self.lathe(role, mat, [(radius, y0), (radius, y1)], centre=(centre[0], 0, centre[1]), segments=segments,
                   cap_top=True, cap_bottom=True)

    def parts(self):
        out = []
        for role, r in self.roles.items():
            P = np.vstack(r["P"])
            I = np.concatenate(r["I"])
            if all(n is not None for n in r["N"]):
                N = np.vstack(r["N"])
            else:
                N = None
            U = np.vstack(r["U"]) if r["uv"] else None
            if N is None:
                N = flat_or_smooth(P, I)
            out.append(S.Part(role, P, N, U, I, r["material"]))
        return out


def flat_or_smooth(P, I):
    """Vertex normals from the triangles touching each vertex (lathe/tube vertices are shared: smooth)."""
    N = np.zeros_like(P)
    tri = I.reshape(-1, 3)
    fn = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
    for k in range(3):
        np.add.at(N, tri[:, k], fn)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def write_glb(stem, parts, generator, finishes=None, mask_roles=(), max_texture=1024):
    """GLB bytes. FINISHES maps a role to a facilityDefaultFinish (the part comes lit); MASK_ROLES get alphaMode MASK."""
    w = S.Writer(stem)
    w.g["asset"]["generator"] = generator
    for p in parts:
        w.add(p, p.name, max_texture=max_texture)
        mat = w.g["materials"][-1]
        if finishes and p.name in finishes:
            mat["extras"]["facilityDefaultFinish"] = finishes[p.name]
        if p.name in mask_roles:
            mat["alphaMode"] = "MASK"
            mat["alphaCutoff"] = 0.5
            mat["pbrMetallicRoughness"]["baseColorFactor"][3] = 1.0
    return w.bytes()


def centred(parts):
    """Moves parts so the bounds are centred on X/Z with the base at y = 0; returns the offset applied."""
    lo = np.min([p.P.min(0) for p in parts], axis=0)
    hi = np.max([p.P.max(0) for p in parts], axis=0)
    off = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    for p in parts:
        p.P = p.P + off
    return off
