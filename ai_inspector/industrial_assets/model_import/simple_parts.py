"""Small plain-colour solids, including open vessels with a real bottom thickness."""
import math

import numpy as np

from .materials import default_material
from .model import Part
from .transforms import linear_color, rotation


def added_part(spec: dict, ordinal: int):
    vertices, normals, indices = [], [], []
    def face(points, outward):
        points = np.asarray(points, dtype=float)
        cross = np.cross(points[1] - points[0], points[2] - points[0])
        if np.dot(cross, outward) < 0:
            points = points[::-1]
            cross = -cross
        normal = cross / np.linalg.norm(cross)
        first = len(vertices)
        vertices.extend(points)
        normals.extend([normal] * len(points))
        indices.extend((first, first + k, first + k + 1) for k in range(1, len(points) - 1))
    if spec["shape"] == "box":
        w, h, d = spec["size"]
        for axis, extent in ((0, w), (1, h), (2, d)):
            others = [i for i in range(3) if i != axis]
            for sign in (-1, 1):
                points = []
                for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    point = np.zeros(3)
                    point[axis] = sign * extent / 2
                    point[others[0]] = a * spec["size"][others[0]] / 2
                    point[others[1]] = b * spec["size"][others[1]] / 2
                    point[1] += h / 2
                    points.append(point)
                outward = np.zeros(3)
                outward[axis] = sign
                face(points, outward)
    else:
        h = spec["height"]
        rb, rt = (spec["radius"], spec["radius"]) if spec["shape"] == "cylinder" else (
            spec["radiusBottom"], spec["radiusTop"])
        wall = spec.get("hollow")
        def ring(r, y, angle):
            return [r * math.cos(angle), y, r * math.sin(angle)]
        for k in range(32):
            a, b = k * math.tau / 32, (k + 1) * math.tau / 32
            radial = [math.cos((a + b) / 2), 0, math.sin((a + b) / 2)]
            face([ring(rb, 0, a), ring(rb, 0, b), ring(rt, h, b), ring(rt, h, a)], radial)
            face([[0, 0, 0], ring(rb, 0, a), ring(rb, 0, b)], [0, -1, 0])
            if wall is None:
                face([[0, h, 0], ring(rt, h, a), ring(rt, h, b)], [0, 1, 0])
            else:
                inner_bottom = rb + (rt - rb) * wall / h - wall
                inner_top = rt - wall
                face([ring(inner_bottom, wall, a), ring(inner_bottom, wall, b),
                      ring(inner_top, h, b), ring(inner_top, h, a)], -np.array(radial))
                face([ring(rt, h, a), ring(rt, h, b), ring(inner_top, h, b), ring(inner_top, h, a)], [0, 1, 0])
                face([[0, wall, 0], ring(inner_bottom, wall, a), ring(inner_bottom, wall, b)], [0, 1, 0])
    matrix = rotation(y=spec["turnDegrees"])
    part = Part(f"add{ordinal}", spec["name"], spec["name"], spec["name"], 0,
                np.array(vertices) @ matrix.T + np.array(spec["position"]),
                np.array(normals) @ matrix.T, None, np.array(indices, dtype=np.uint32))
    material = default_material()
    material.update(name=spec["name"], baseColor=linear_color(spec["color"]) + [1],
                    roughness=spec["roughness"], metalness=spec["metalness"])
    return part, material
