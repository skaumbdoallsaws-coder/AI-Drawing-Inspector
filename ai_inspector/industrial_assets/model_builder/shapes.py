"""Small deterministic indexed meshes. Profiles are simple polygons, without holes."""
from dataclasses import dataclass
import math

import numpy as np

from .errors import require
from .recipe import lathe_profile, polygon_area


@dataclass
class Mesh:
    positions: np.ndarray
    indices: np.ndarray
    uv: np.ndarray | None = None
    closed: bool = True

    def transformed(self, matrix, offset):
        positions = self.positions @ matrix.T + offset
        indices = self.indices.copy()
        uv = None if self.uv is None else self.uv.copy()
        if np.linalg.det(matrix) < 0:
            indices[:, [1, 2]] = indices[:, [2, 1]]
            if uv is not None:
                uv[:, 0] = 1 - uv[:, 0]  # Printed fronts retain readable handedness.
        return Mesh(positions, indices, uv, self.closed)


class Builder:
    def __init__(self):
        self.points, self.faces = [], []

    def point(self, value):
        self.points.append(tuple(value))
        return len(self.points) - 1

    def face(self, indices, normal=None):
        cleaned = []
        for i in indices:
            if not cleaned or i != cleaned[-1]:
                cleaned.append(i)
        if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
            cleaned.pop()
        if len(cleaned) < 3:
            return
        if normal is not None:
            a, b, c = np.asarray([self.points[i] for i in cleaned[:3]])
            if np.dot(np.cross(b-a, c-a), normal) < 0:
                cleaned.reverse()
        for j in range(1, len(cleaned)-1):
            self.faces.append((cleaned[0], cleaned[j], cleaned[j+1]))

    def mesh(self, closed=True):
        return Mesh(np.asarray(self.points, dtype=float), np.asarray(self.faces, dtype=np.uint32), closed=closed)


def basis(axis):
    """Map local +Y onto an arbitrary axis using a proper orthonormal frame."""
    y = np.asarray(axis, dtype=float)
    y /= np.linalg.norm(y)
    seed = np.array([1., 0, 0]) if abs(y[0]) < .9 else np.array([0., 0, 1])
    x = seed - y * np.dot(seed, y)
    x /= np.linalg.norm(x)
    return np.column_stack((x, y, np.cross(x, y)))


def axis_matrix(axis):
    return basis({"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[axis])


def box(low, high):
    b = Builder()
    for x, y, z in ((0,0,0), (1,0,0), (1,1,0), (0,1,0),
                    (0,0,1), (1,0,1), (1,1,1), (0,1,1)):
        b.point([high[i] if bit else low[i] for i, bit in enumerate((x, y, z))])
    for ids, normal in (((0,1,2,3), (0,0,-1)), ((4,5,6,7), (0,0,1)),
                        ((0,4,7,3), (-1,0,0)), ((1,5,6,2), (1,0,0)),
                        ((0,1,5,4), (0,-1,0)), ((3,2,6,7), (0,1,0))):
        b.face(ids, normal)
    return b.mesh()


def _ring(b, radius, height, segments):
    if radius == 0:
        return [b.point((0, height, 0))] * segments
    return [b.point((radius * math.cos(2*math.pi*i/segments), height,
                     radius * math.sin(2*math.pi*i/segments))) for i in range(segments)]


def revolve(profile, segments):
    # A positive (r,y) profile encloses the solid on its left.
    profile = profile if polygon_area(profile) > 0 else list(reversed(profile))
    b = Builder()
    rings = [_ring(b, r, y, segments) for r, y in profile]
    for left, right in zip(rings, rings[1:] + rings[:1]):
        for i in range(segments):
            j = (i+1) % segments
            b.face([left[i], right[i], right[j], left[j]])
    return b.mesh()


def cylinder(e):
    b = Builder()
    n, start, end = e["segments"], np.array(e["from"]), np.array(e["to"])
    height = np.linalg.norm(end-start)
    outer = [_ring(b, e["radius"], 0, n), _ring(b, e["radiusTo"], height, n)]
    inner = ([_ring(b, e["radius"]-e["hollow"], 0, n),
              _ring(b, e["radiusTo"]-e["hollow"], height, n)] if "hollow" in e else None)
    for i in range(n):
        j = (i+1) % n
        b.face([outer[0][i], outer[1][i], outer[1][j], outer[0][j]])
        if inner:
            b.face([inner[0][j], inner[1][j], inner[1][i], inner[0][i]])
    for k, cap in enumerate(("start", "end")):
        if e["caps"] not in ("both", cap) or (k == 1 and e["radiusTo"] == 0):
            continue
        center = b.point((0, k*height, 0)) if inner is None else None
        for i in range(n):
            j = (i+1) % n
            b.face([outer[k][i], outer[k][j], inner[k][j], inner[k][i]] if inner
                   else [center, outer[k][i], outer[k][j]], (0, 1 if k else -1, 0))
    closed = e["caps"] == "both" or (e["radiusTo"] == 0 and e["caps"] == "start")
    return b.mesh(closed).transformed(basis(end-start), start)


def tube(e):
    points = np.asarray(e["path"], dtype=float)
    count, n, closed = len(points), e["sides"], e["closed"]
    segments = np.diff(np.vstack([points, points[:1]]) if closed else points, axis=0)
    segments /= np.linalg.norm(segments, axis=1)[:, None]
    b, rings = Builder(), []
    previous_u = None
    for k, point in enumerate(points):
        incoming = segments[k-1] if k or closed else segments[0]
        outgoing = segments[k % len(segments)] if k < count-1 or closed else incoming
        tangent = incoming + outgoing
        require(np.linalg.norm(tangent) > .1, "$.path",
                "Tube cannot reverse at a joint", "geometry_invalid")
        tangent /= np.linalg.norm(tangent)
        if previous_u is None:
            previous_u = basis(incoming)[:, 0]
        u = previous_u - incoming * np.dot(previous_u, incoming)
        if np.linalg.norm(u) < 1e-6:
            u = basis(incoming)[:, 0]
        u /= np.linalg.norm(u)
        v = np.cross(incoming, u)
        ring = []
        for i in range(n):
            angle = 2*math.pi*i/n
            radial = e["radius"] * (math.cos(angle)*u + math.sin(angle)*v)
            # Intersect each incoming tube generator with the joint's bisector plane.
            radial -= incoming * (np.dot(radial, tangent) / np.dot(incoming, tangent))
            ring.append(b.point(point + radial))
        rings.append(ring)
        previous_u = u
    for k in range(count if closed else count-1):
        left, right = rings[k], rings[(k+1) % count]
        for i in range(n):
            j = (i+1) % n
            # Ring frame u,v has u cross v = incoming.
            b.face([left[i], left[j], right[j], right[i]])
    if not closed:
        for k, normal in ((0, -segments[0]), (count-1, segments[-1])):
            center = b.point(points[k])
            for i in range(n):
                b.face([center, rings[k][i], rings[k][(i+1) % n]], normal)
    return b.mesh()


def torus(e):
    b = Builder()
    n, sides, radius, small = e["segments"], 8, e["radius"], e["tubeRadius"]
    for i in range(n):
        a = 2*math.pi*i/n
        for j in range(sides):
            c = 2*math.pi*j/sides
            r = radius + small*math.cos(c)
            b.point((r*math.cos(a), small*math.sin(c), r*math.sin(a)))
    for i in range(n):
        for j in range(sides):
            ids = [i*sides+j, i*sides+(j+1)%sides, ((i+1)%n)*sides+(j+1)%sides, ((i+1)%n)*sides+j]
            a, c = 2*math.pi*(i+.5)/n, 2*math.pi*(j+.5)/sides
            b.face(ids, (math.cos(a)*math.cos(c), math.sin(c), math.sin(a)*math.cos(c)))
    return b.mesh().transformed(axis_matrix(e["axis"]), np.asarray(e["center"]))


def sphere(e):
    first, last = {"whole": (0, 12), "upper": (6, 12), "lower": (0, 6)}[e["part"]]
    profile = [[0 if j in (0, 12) else math.sin(math.pi*j/12), -math.cos(math.pi*j/12)]
               for j in range(first, last+1)]
    if first == 6:
        profile.insert(0, [0, 0])
    if last == 6:
        profile.append([0, 0])
    return revolve(profile, 24).transformed(np.diag(e["radii"]), np.asarray(e["center"]))


def triangulate(profile):
    """Deterministic ear clipping of a validated simple CCW polygon."""
    points = np.asarray(profile)
    indices = list(range(len(points)))
    faces = []
    def cross(a, b, c):
        x, y = b-a, c-a
        return x[0]*y[1] - x[1]*y[0]
    while len(indices) > 3:
        found = False
        for k, current in enumerate(indices):
            a, c = indices[k-1], indices[(k+1) % len(indices)]
            if cross(points[a], points[current], points[c]) <= 1e-12:
                continue
            if any(all(v >= -1e-12 for v in (
                cross(points[a], points[current], points[q]),
                cross(points[current], points[c], points[q]),
                cross(points[c], points[a], points[q]))) for q in indices if q not in (a, current, c)):
                continue
            faces.append((a, current, c))
            indices.pop(k)
            found = True
            break
        require(found, "$.profile", "Profile cannot be triangulated", "geometry_invalid")
    faces.append(tuple(indices))
    return faces


def extrude(e):
    profile = e["profile"]
    if polygon_area(profile) < 0:
        profile = list(reversed(profile))
    b, n = Builder(), len(profile)
    for z in (e["at"], e["at"] + e["depth"]):
        for u, v in profile:
            b.point((u, v, z))
    for ids in triangulate(profile):
        b.face(ids, (0,0,-1))
        b.face([i+n for i in ids], (0,0,1))
    for i in range(n):
        j = (i+1) % n
        b.face([i, j, j+n, i+n])
    matrix = {"xy": np.eye(3), "zy": np.array([[0,0,1],[0,1,0],[1,0,0]]),
              "xz": np.array([[1,0,0],[0,0,1],[0,1,0]])}[e["plane"]]
    return b.mesh().transformed(matrix, np.zeros(3))


def panel_frame(facing):
    u, v, n = {
        "+z": ((1,0,0), (0,1,0), (0,0,1)), "-z": ((-1,0,0), (0,1,0), (0,0,-1)),
        "+x": ((0,0,-1), (0,1,0), (1,0,0)), "-x": ((0,0,1), (0,1,0), (-1,0,0)),
        "+y": ((1,0,0), (0,0,-1), (0,1,0)),
    }[facing]
    return np.column_stack((u, v, n))


def make_shape(e):
    """Return (mesh, role) pairs; a panel's print and backing are independently finishable."""
    shape = e["shape"]
    if shape == "panel":
        w, h = np.asarray(e["size"]) / 2
        plate = box((-w, -h, -.0025), (w, h, -.0005))
        face = Mesh(np.array([[-w,-h,0], [w,-h,0], [w,h,0], [-w,h,0]]),
                    np.array([[0,1,2], [0,2,3]], dtype=np.uint32),
                    np.array([[0,1], [1,1], [1,0], [0,0]], dtype=float), False)
        matrix, offset = panel_frame(e["facing"]), np.asarray(e["center"])
        return [(plate.transformed(matrix, offset), "back"), (face.transformed(matrix, offset), "print")]
    if shape == "box":
        low = np.asarray(e["min"]) if "min" in e else np.asarray(e["center"]) - np.asarray(e["size"])/2
        high = np.asarray(e["max"]) if "max" in e else np.asarray(e["center"]) + np.asarray(e["size"])/2
        mesh = box(low, high)
    elif shape == "lathe":
        mesh = revolve(lathe_profile(e["profile"]), e["segments"])
        mesh = mesh.transformed(axis_matrix(e["axis"]), np.asarray(e["center"]))
    else:
        mesh = {"cylinder": cylinder, "tube": tube, "torus": torus, "sphere": sphere, "extrude": extrude}[shape](e)
    return [(mesh, "body")]
