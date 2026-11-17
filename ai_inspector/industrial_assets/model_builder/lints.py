"""Cheap deterministic geometry diagnostics, before pieces merge into finishable parts."""
import re

import numpy as np

from .adapt import material_key

MAX_FINDINGS = 20  # per code
MAX_PAIRS = 100000


def _clip(subject, clip):
    def cross(a, b, p):
        return (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])
    result = list(subject)
    for a, b in zip(clip, np.roll(clip, -1, axis=0)):
        previous = result[-1] if result else None
        output = []
        for current in result:
            dp, dc = cross(a, b, previous), cross(a, b, current)
            if (dp >= 0) != (dc >= 0):
                output.append(previous + (current-previous) * dp/(dp-dc))
            if dc >= 0:
                output.append(current)
            previous = current
        result = output
    if len(result) < 3:
        return 0.
    p = np.asarray(result)
    return abs(float(np.sum(p[:,0]*np.roll(p[:,1], -1)-p[:,1]*np.roll(p[:,0], -1))))/2


def _planes(component):
    """Coalesce the two triangles of each box/plate face into a convex polygon."""
    if component.entry.get("shape") not in ("box", "panel"):
        return []
    points = component.mesh.positions
    groups = {}
    for face in component.mesh.indices:
        a, b, c = points[face]
        normal = np.cross(b-a, c-a)
        normal /= np.linalg.norm(normal)
        distance = float(normal @ a)
        key = tuple(np.round(normal, 7)) + (round(distance, 7),)
        groups.setdefault(key, set()).update(int(i) for i in face)
    result = []
    for plane, indices in groups.items():
        normal = np.array(plane[:3])
        drop = int(np.argmax(np.abs(normal)))
        polygon = np.delete(points[sorted(indices)], drop, axis=1)
        center = polygon.mean(axis=0)
        angles = np.arctan2(polygon[:,1]-center[1], polygon[:,0]-center[0])
        polygon = polygon[np.argsort(angles)]
        result.append((normal, plane[3], drop, polygon))
    return result


def lint_model(components, recipe, dimensions, shift, triangle_count):
    findings, counts, warnings = [], {}, []
    def add(code, pieces=(), **details):
        if counts.get(code, 0) >= MAX_FINDINGS:
            return
        counts[code] = counts.get(code, 0)+1
        findings.append({"code": code, "entryIds": sorted({c.entry["id"] for c in pieces}),
                         "instances": sorted({c.instance for c in pieces}), **details})

    mismatch = [k for k, v in dimensions.items() if abs(v-recipe["size"][k]) > max(.01, .02*recipe["size"][k])]
    if mismatch:
        add("size_mismatch", dimensions=mismatch)
    if abs(shift[1]) > .02 or max(abs(shift[0]), abs(shift[2])) > .05:
        add("floor_shift", shift=[float(x) for x in shift], baseHeight=recipe["hangHeight"])
    if triangle_count > 20000:
        add("heavy", triangles=triangle_count)
    if "fitsWithin" in recipe:
        # Already net of clearances, in the model's intended gap frame.
        occupied = dict(dimensions, height=dimensions["height"]+recipe["hangHeight"])
        excess = [k for k, v in occupied.items() if k in recipe["fitsWithin"] and v > recipe["fitsWithin"][k]+1e-7]
        if excess:
            add("fit_exceeded", dimensions=excess)
    checked_names = set()
    boxes = [c.bounds for c in components]
    connected = [low[1] <= recipe["hangHeight"]+.003 for low, _ in boxes]
    for i, c in enumerate(components):
        low, high = boxes[i]
        if bool(np.all(high-low < .002)):
            add("tiny_part", (c,))
        name = c.output_name or c.entry["name"]
        if name not in checked_names and re.fullmatch(r"(part|box|cylinder|mesh|object)[ _-]*\d*", name, re.I):
            add("generic_name", (c,))
        checked_names.add(name)
        if c.role == "print" and name in recipe["front"]:
            a, b, d = c.mesh.positions[c.mesh.indices[0]]
            normal = np.cross(b-a, d-a)
            normal /= np.linalg.norm(normal)
            if normal[2] < 1-1e-6:
                add("front_check", (c,), facing=np.round(normal, 6).tolist())
    planes, tested, incomplete = {}, 0, False
    order = sorted(range(len(components)), key=lambda i: (boxes[i][0][0], components[i].instance, components[i].role))
    for position, i in enumerate(order):
        low, high = boxes[i]
        for j in order[position+1:]:
            other_low, other_high = boxes[j]
            if other_low[0] > high[0]+.003:
                break
            tested += 1
            if tested > MAX_PAIRS:
                incomplete = True
                break
            gap = np.maximum(np.maximum(low-other_high, other_low-high), 0)
            if np.linalg.norm(gap) <= .003+1e-10:
                connected[i] = connected[j] = True
            if (counts.get("coplanar_overlap", 0) >= MAX_FINDINGS
                    or material_key(components[i]) == material_key(components[j])
                    or np.any(gap > .0003)):
                continue
            if i not in planes:
                planes[i] = _planes(components[i])
            if j not in planes:
                planes[j] = _planes(components[j])
            overlap = False
            for n, d, axis, polygon in planes[i]:
                for m, e, other_axis, other_polygon in planes[j]:
                    if axis == other_axis and n @ m > 1-1e-6 and abs(d-e) <= .0003:
                        if _clip(polygon, other_polygon) / abs(n[axis]) > .0001:
                            overlap = True
                            break
                if overlap:
                    break
            if overlap:
                add("coplanar_overlap", (components[i], components[j]))
        if incomplete:
            break
    if incomplete:
        warnings.append("Contact lint reached its 100000-pair limit; floating results are incomplete.")
    else:
        for c, contact in zip(components, connected):
            if not contact:
                add("floating_part", (c,))
    return findings, warnings
