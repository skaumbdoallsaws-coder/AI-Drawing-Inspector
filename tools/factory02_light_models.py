"""Light fittings for the facility lighting plan (docs/facility-lighting-plan.md, L5 and L8).

Five authored models, built from primitives (the same bytes on every run):

- asset-factory02-stack-light: a three-lamp stack light (red, amber and green from the top) on a short pole with a
  40 mm mounting foot, for robot cells and machines. Its footprint is the foot, so it can sit on a fence rail.
- asset-factory02-rotating-beacon: an amber rotating beacon on a round base, for the top of a forklift guard.
- asset-factory02-rotating-beacon-wall: the same beacon on a steel wall bracket, for a wall beside a dock door.
- asset-factory02-pole-light (L8): an 8 m car park pole on a concrete base, with one LED head on top facing down.
- asset-factory02-wall-light (L8): an outdoor LED wall light whose lens faces down and 30 degrees out from the wall,
  for over a dock door.

Each lamp is its own part. The pole light's and wall light's LED lens, the beacons' lens and the stack light's green
lamp come lit: their material names a Lights finish (glTF material extras facilityDefaultFinish: Pole light LED, Wall
light LED, Beacon amber, Stack light green), which the 3D view shows, and the component inventory reports, unless the
placement gives that part a finish of its own. The stack light's amber and red lamps start unlit, in the plain color
of their Lights finish: a Lights finish on the part (set_component_materials with an appearanceId) lights it. Its
three lamps are one finish group (extras facilityFinishGroup "stack lamps"), since one lamp shows the cell's state: the
green lamp's default shows only while none of the three has a finish of its own, so a stack light set to amber or red
shows that lamp alone. Stack light green is steady; Beacon amber turns. An outdoor
Lights finish (pole light, wall light or dock light) gives an LED lens its beam angle, so in the evening scene it shows
a soft beam down to the ground and a pool where the beam lands. tools/light_factory02.py places them in Factory 02.
Illustrative only: not an electrical, lighting, signalling or machine-safety design.

The catalog descriptions still say to give the lens a Lights finish: a description is part of the asset's revision,
and a new revision would orphan the lights already placed.

    python tools/factory02_light_models.py [--root PROJECT_ROOT]

writes the models to generated/industrial_assets/factory02_lights/ and adds or updates their entries in the
private asset catalog (generated/industrial_assets/local_library/catalog.json). A second run changes nothing.
Restart the app afterwards: it reads the catalog when it starts.
"""
from pathlib import Path
import argparse
import json
import math
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))   # run as a script: the app's packages, for the private catalog's lock
FOLDER = "generated/industrial_assets/factory02_lights"
CATALOG = Path("generated/industrial_assets/local_library/catalog.json")
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
SEGMENTS = 32
STACK_LIGHT = "asset-factory02-stack-light"
BEACON = "asset-factory02-rotating-beacon"
WALL_BEACON = "asset-factory02-rotating-beacon-wall"
POLE_LIGHT = "asset-factory02-pole-light"
WALL_LIGHT = "asset-factory02-wall-light"
POLE_HEIGHT = 8.0            # metres, the top of the LED head; its lens faces down at 7.85 m
WALL_LIGHT_TILT = 30         # degrees: the wall light's lens faces down and this far out from the wall

# (sRGB color, metalness, roughness). The lamps' colors are the plain (unlit) colors of the Lights finishes they
# take (static/facility_library/appearances.json), so a lamp looks the same off as with its finish switched off.
BLACK = ("#1b1d20", 0.0, 0.6)
STEEL = ("#8a9097", 0.6, 0.45)
ALUMINIUM = ("#b8bec4", 0.7, 0.35)
GREEN_LAMP = ("#1d6b37", 0.0, 0.35)
AMBER_LAMP = ("#a96d06", 0.0, 0.35)
RED_LAMP = ("#7d1913", 0.0, 0.35)
BEACON_LENS = ("#b5740c", 0.0, 0.3)
CONCRETE = ("#9a9890", 0.0, 0.85)
POLE_STEEL = ("#6e757c", 0.5, 0.5)
HOUSING = ("#3a3f45", 0.3, 0.5)
LED_LENS = ("#dfe4e8", 0.0, 0.35)

# Part keys (p:<root node>/<part node>#<primitive>, names percent-encoded as in the component inventory).
STACK_LAMP_KEYS = {"green": "p:stack-light/green%20lamp#0", "amber": "p:stack-light/amber%20lamp#0",
                   "red": "p:stack-light/red%20lamp#0"}
BEACON_LENS_KEYS = {BEACON: "p:rotating-beacon/beacon%20lens#0", WALL_BEACON: "p:rotating-beacon-wall/beacon%20lens#0"}
LED_LENS_KEYS = {POLE_LIGHT: "p:pole-light/led%20lens#0", WALL_LIGHT: "p:wall-light/led%20lens#0"}


class Part:
    """One mesh: positions, normals and triangles wound counter-clockwise seen from outside."""

    def __init__(self):
        self.positions, self.normals, self.indices = [], [], []

    def vertex(self, position, normal):
        self.positions.append(tuple(float(v) for v in position))
        n = np.asarray(normal, dtype=float)
        self.normals.append(tuple(float(v) for v in n / np.linalg.norm(n)))
        return len(self.positions) - 1

    def triangle(self, a, b, c):
        p = np.array([self.positions[i] for i in (a, b, c)])
        outside = np.array([self.normals[i] for i in (a, b, c)]).sum(axis=0)
        if np.dot(np.cross(p[1] - p[0], p[2] - p[0]), outside) < 0:
            b, c = c, b
        self.indices += [a, b, c]


def _angles():
    return [2 * math.pi * i / SEGMENTS for i in range(SEGMENTS)]


def box(part, x0, x1, y0, y1, z0, z1, skip=()):
    """An axis-aligned box; SKIP lists faces to leave out as (axis, side), e.g. (1, 0) for the bottom."""
    bounds = ((x0, x1), (y0, y1), (z0, z1))
    for axis in range(3):
        u, v = [k for k in range(3) if k != axis]
        for side in (0, 1):
            if (axis, side) in skip:
                continue
            normal = [0, 0, 0]
            normal[axis] = 1 if side else -1
            corners = []
            for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                point = [0.0, 0.0, 0.0]
                point[axis], point[u], point[v] = bounds[axis][side], bounds[u][a], bounds[v][b]
                corners.append(part.vertex(point, normal))
            part.triangle(corners[0], corners[1], corners[2])
            part.triangle(corners[0], corners[2], corners[3])


def tube(part, radius, y0, y1, cz=0.0):
    """The side of an upright cylinder, smooth."""
    bottom, top = [], []
    for t in _angles():
        normal = (math.cos(t), 0, math.sin(t))
        bottom.append(part.vertex((radius * math.cos(t), y0, cz + radius * math.sin(t)), normal))
        top.append(part.vertex((radius * math.cos(t), y1, cz + radius * math.sin(t)), normal))
    for i in range(SEGMENTS):
        j = (i + 1) % SEGMENTS
        part.triangle(bottom[i], bottom[j], top[j])
        part.triangle(bottom[i], top[j], top[i])


def disc(part, radius, y, up, cz=0.0):
    normal = (0, 1 if up else -1, 0)
    centre = part.vertex((0, y, cz), normal)
    rim = [part.vertex((radius * math.cos(t), y, cz + radius * math.sin(t)), normal) for t in _angles()]
    for i in range(SEGMENTS):
        part.triangle(centre, rim[i], rim[(i + 1) % SEGMENTS])


def dome(part, radius, y0, height, cz=0.0, rings=8):
    """A half ellipsoid standing on the circle of RADIUS at Y0, HEIGHT tall."""
    rows = []
    for k in range(rings):
        phi = math.pi / 2 * k / rings
        row = []
        for t in _angles():
            normal = (math.cos(phi) * math.cos(t) / radius, math.sin(phi) / height, math.cos(phi) * math.sin(t) / radius)
            row.append(part.vertex((radius * math.cos(phi) * math.cos(t), y0 + height * math.sin(phi),
                                    cz + radius * math.cos(phi) * math.sin(t)), normal))
        rows.append(row)
    top = part.vertex((0, y0 + height, cz), (0, 1, 0))
    for lower, upper in zip(rows, rows[1:]):
        for i in range(SEGMENTS):
            j = (i + 1) % SEGMENTS
            part.triangle(lower[i], lower[j], upper[j])
            part.triangle(lower[i], upper[j], upper[i])
    for i in range(SEGMENTS):
        part.triangle(rows[-1][i], rows[-1][(i + 1) % SEGMENTS], top)


def solid_cylinder(part, radius, y0, y1, cz=0.0, bottom=True):
    tube(part, radius, y0, y1, cz)
    disc(part, radius, y1, True, cz)
    if bottom:
        disc(part, radius, y0, False, cz)


def beacon_parts(y0, cz=0.0):
    """Base and lens of the rotating beacon, standing at Y0. The lens has no underside (the base closes it), so
    it never counts as a downward lamp that throws a floor pool."""
    base, lens = Part(), Part()
    solid_cylinder(base, 0.075, y0, y0 + 0.035, cz)
    tube(lens, 0.065, y0 + 0.035, y0 + 0.125, cz)
    dome(lens, 0.065, y0 + 0.125, 0.055, cz)
    return [("base", base, BLACK), ("beacon lens", lens, BEACON_LENS)]


def stack_light_parts():
    mount, pole, base, cap = Part(), Part(), Part(), Part()
    box(mount, -0.02, 0.02, 0.0, 0.006, -0.02, 0.02)
    solid_cylinder(pole, 0.011, 0.006, 0.156, bottom=False)
    solid_cylinder(base, 0.03, 0.156, 0.186)
    lamps = []
    for name, color, y in (("green lamp", GREEN_LAMP, 0.186), ("amber lamp", AMBER_LAMP, 0.246),
                           ("red lamp", RED_LAMP, 0.306)):
        lamp = Part()
        tube(lamp, 0.03, y, y + 0.06)   # the side only: the base, the next lamp or the cap closes each end
        lamps.append((name, lamp, color))
    solid_cylinder(cap, 0.03, 0.366, 0.381, bottom=False)
    return [("mount", mount, STEEL), ("pole", pole, ALUMINIUM), ("base", base, BLACK), *lamps, ("cap", cap, BLACK)]


def wall_beacon_parts():
    bracket = Part()
    box(bracket, -0.06, 0.06, 0.0, 0.008, -0.11, 0.11)       # shelf
    box(bracket, -0.06, 0.06, 0.008, 0.17, -0.11, -0.104)    # back plate, against the wall
    return [("bracket", bracket, STEEL), *beacon_parts(0.008, cz=0.035)]


def flat(part, corners, normal):
    """A flat polygon (convex, corners in order), facing NORMAL."""
    ids = [part.vertex(corner, normal) for corner in corners]
    for i in range(1, len(ids) - 1):
        part.triangle(ids[0], ids[i], ids[i + 1])


def pole_light_parts():
    """An 8 m pole on a concrete base with one LED head on top. The head is open underneath and the lens closes it,
    facing straight down, so it is a lamp (docs/facility-lighting-plan.md, L3) and its aim is down."""
    base, pole, head, lens = Part(), Part(), Part(), Part()
    solid_cylinder(base, 0.25, 0.0, 0.5, bottom=False)
    tube(pole, 0.07, 0.5, 7.85)
    box(head, -0.36, 0.36, 7.85, POLE_HEIGHT, -0.18, 0.18, skip=((1, 0),))
    flat(lens, [(-0.36, 7.85, -0.18), (0.36, 7.85, -0.18), (0.36, 7.85, 0.18), (-0.36, 7.85, 0.18)], (0, -1, 0))
    return [("base", base, CONCRETE), ("pole", pole, POLE_STEEL), ("led head", head, HOUSING), ("led lens", lens, LED_LENS)]


def wall_light_parts():
    """A wall pack: a back plate against the wall (its -Z face) and a housing whose underside, the lens, slopes up
    toward the front, so the lens faces down and WALL_LIGHT_TILT degrees out from the wall (+Z)."""
    plate, housing, lens = Part(), Part(), Part()
    back, front, low, top = -0.115, 0.125, 0.04, 0.32
    high = low + (front - back) * math.tan(math.radians(WALL_LIGHT_TILT))
    box(plate, -0.2, 0.2, 0.0, top, -0.125, back)
    flat(housing, [(-0.2, top, back), (0.2, top, back), (0.2, top, front), (-0.2, top, front)], (0, 1, 0))
    flat(housing, [(-0.2, high, front), (0.2, high, front), (0.2, top, front), (-0.2, top, front)], (0, 0, 1))
    for x, normal in ((-0.2, (-1, 0, 0)), (0.2, (1, 0, 0))):
        flat(housing, [(x, low, back), (x, high, front), (x, top, front), (x, top, back)], normal)
    tilt = math.radians(WALL_LIGHT_TILT)
    flat(lens, [(-0.2, low, back), (0.2, low, back), (0.2, high, front), (-0.2, high, front)],
         (0, -math.cos(tilt), math.sin(tilt)))
    return [("back plate", plate, STEEL), ("housing", housing, HOUSING), ("led lens", lens, LED_LENS)]


def _linear(color):
    def channel(value):
        value = int(value, 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return [round(channel(color[i:i + 2]), 5) for i in (1, 3, 5)]


def pack(doc, data):
    encoded = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("ascii")
    encoded += b" " * (-len(encoded) % 4)
    data = bytes(data) + b"\0" * (-len(data) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(data))
            + struct.pack("<I4s", len(encoded), b"JSON") + encoded + struct.pack("<I4s", len(data), b"BIN\0") + data)


def glb(root_name, parts, default_finishes=None, finish_groups=None):
    """The GLB bytes. DEFAULT_FINISHES maps a part name to the Lights finish its material names (it comes lit);
    FINISH_GROUPS maps a part name to its finish group (a default in a group shows only while no part of the group has
    a finish of its own)."""
    default_finishes, finish_groups = default_finishes or {}, finish_groups or {}
    doc = {"asset": {"version": "2.0", "generator": "InspectorPro tools/factory02_light_models.py"},
           "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"name": root_name, "children": list(range(1, len(parts) + 1))}],
           "meshes": [], "materials": [], "accessors": [], "bufferViews": []}
    data = bytearray()

    def view(payload, target):
        data.extend(b"\0" * (-len(data) % 4))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(data), "byteLength": len(payload), "target": target})
        data.extend(payload)
        return len(doc["bufferViews"]) - 1

    def accessor(array, kind, target, component, bounds=False):
        value = {"bufferView": view(array.tobytes(), target), "componentType": component, "count": len(array),
                 "type": kind}
        if bounds:
            value["min"] = [float(v) for v in array.min(axis=0)]
            value["max"] = [float(v) for v in array.max(axis=0)]
        doc["accessors"].append(value)
        return len(doc["accessors"]) - 1

    for index, (name, part, (color, metalness, roughness)) in enumerate(parts):
        positions = np.round(np.asarray(part.positions), 6).astype("<f4")
        normals = np.asarray(part.normals).astype("<f4")
        indices = np.asarray(part.indices, dtype="<u2")
        primitive = {"attributes": {"POSITION": accessor(positions, "VEC3", 34962, 5126, bounds=True),
                                    "NORMAL": accessor(normals, "VEC3", 34962, 5126)},
                     "indices": accessor(indices, "SCALAR", 34963, 5123), "material": index}
        extras = {"facilityAuthoredFinish": True, "facilityMaterialRole": name}
        if name in default_finishes:
            extras["facilityDefaultFinish"] = default_finishes[name]
        if name in finish_groups:
            extras["facilityFinishGroup"] = finish_groups[name]
        doc["materials"].append({"name": name, "extras": extras,
                                 "pbrMetallicRoughness": {"baseColorFactor": _linear(color) + [1.0],
                                                          "metallicFactor": metalness, "roughnessFactor": roughness}})
        doc["meshes"].append({"name": name, "primitives": [primitive]})
        doc["nodes"].append({"name": name, "mesh": index})
    doc["buffers"] = [{"byteLength": len(data) + (-len(data) % 4)}]
    return pack(doc, data)


MODELS = (
    {"assetId": STACK_LIGHT, "file": "stack-light.glb", "root": "stack-light", "parts": stack_light_parts,
     "displayName": "Stack light - 3 lamps", "category": "Automation",
     "dimensions": {"width": 0.06, "depth": 0.06, "height": 0.381},
     "footprint": [(-0.02, -0.02), (0.02, -0.02), (0.02, 0.02), (-0.02, 0.02)],
     "description": "Three-lamp stack light (red, amber and green from the top, 60 mm) on a short pole with a 40 mm "
                    "mounting foot, for robot cells and machines. Each lamp is its own part: give one a Lights "
                    "finish (Stack light green, amber or red) to light it. The footprint is the mounting foot. "
                    "Illustrative only; not an electrical or machine-safety design.",
     "tags": ["lighting", "stack-light", "andon", "signal", "robot cell", "authored", "factory02"],
     "defaultFinishes": {"green lamp": "light-stack-green"},
     "finishGroups": {"green lamp": "stack lamps", "amber lamp": "stack lamps", "red lamp": "stack lamps"}},
    {"assetId": BEACON, "file": "rotating-beacon.glb", "root": "rotating-beacon", "parts": lambda: beacon_parts(0.0),
     "displayName": "Rotating beacon", "category": "Safety Equipment",
     "dimensions": {"width": 0.15, "depth": 0.15, "height": 0.18},
     "description": "Amber rotating beacon on a round base, for the top of a forklift guard or a machine. Give the "
                    "beacon lens the Beacon amber finish to make it turn. Illustrative only; not a safety or "
                    "electrical design.",
     "tags": ["lighting", "beacon", "warning light", "forklift", "authored", "factory02"],
     "defaultFinishes": {"beacon lens": "light-beacon-amber"}},
    {"assetId": WALL_BEACON, "file": "rotating-beacon-wall.glb", "root": "rotating-beacon-wall",
     "parts": wall_beacon_parts, "displayName": "Rotating beacon on wall bracket", "category": "Safety Equipment",
     "dimensions": {"width": 0.15, "depth": 0.22, "height": 0.188},
     "description": "Amber rotating beacon on a steel wall bracket, for a wall beside a dock door. The bracket's back "
                    "plate is its -Z face. Give the beacon lens the Beacon amber finish to make it turn. Illustrative "
                    "only; not a safety or electrical design.",
     "tags": ["lighting", "beacon", "warning light", "dock", "wall-mounted", "authored", "factory02"],
     "defaultFinishes": {"beacon lens": "light-beacon-amber"}},
    {"assetId": POLE_LIGHT, "file": "pole-light.glb", "root": "pole-light", "parts": pole_light_parts,
     "displayName": "Pole light - 8 m, LED", "category": "Facilities",
     "dimensions": {"width": 0.72, "depth": 0.5, "height": POLE_HEIGHT},
     "footprint": [(-0.25, -0.25), (0.25, -0.25), (0.25, 0.25), (-0.25, 0.25)],
     "description": "Car park or yard pole light: an 8 m steel pole on a 0.5 m concrete base with one LED head on top, "
                    "its lens facing down at 7.85 m. Give the LED lens a Lights finish (Pole light LED) to light it; in "
                    "the evening scene it then shows a soft beam and a pool of light on the ground. The footprint is "
                    "the base. Illustrative only; not a lighting design.",
     "tags": ["lighting", "pole light", "street light", "car park", "parking", "outdoor", "yard", "authored",
              "factory02"],
     "defaultFinishes": {"led lens": "light-pole-led"}},
    {"assetId": WALL_LIGHT, "file": "wall-light.glb", "root": "wall-light", "parts": wall_light_parts,
     "displayName": "Wall light - outdoor LED", "category": "Facilities",
     "dimensions": {"width": 0.4, "depth": 0.25, "height": 0.32},
     "description": "Outdoor LED wall light (wall pack) for over a dock door or along a wall. The back plate is its -Z "
                    "face; the lens faces down and 30 degrees out from the wall. Give the LED lens a Lights finish "
                    "(Dock light LED or Wall light LED) to light it; in the evening scene it then shows a soft beam and "
                    "a pool of light where the beam lands. Illustrative only; not a lighting design.",
     "tags": ["lighting", "wall light", "wall pack", "dock light", "outdoor", "wall-mounted", "authored",
              "factory02"],
     "defaultFinishes": {"led lens": "light-wall-led"}},
)


def build(model):
    """The model's GLB bytes; checks they fill exactly its catalog dimensions, centred on X/Z with the base at 0."""
    raw = glb(model["root"], model["parts"](), model.get("defaultFinishes"), model.get("finishGroups"))
    length = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + length])
    lows = np.min([doc["accessors"][m["primitives"][0]["attributes"]["POSITION"]]["min"] for m in doc["meshes"]], axis=0)
    highs = np.max([doc["accessors"][m["primitives"][0]["attributes"]["POSITION"]]["max"] for m in doc["meshes"]], axis=0)
    size = model["dimensions"]
    expected = np.array([[-size["width"] / 2, 0, -size["depth"] / 2], [size["width"] / 2, size["height"], size["depth"] / 2]])
    if not np.allclose([lows, highs], expected, atol=1e-6, rtol=0):
        raise AssertionError(f"{model['assetId']} bounds {lows} {highs} do not match its dimensions")
    return raw


def catalog_entry(model):
    entry = {"artifact": FOLDER + "/" + model["file"], "assetId": model["assetId"], "category": model["category"],
             "description": model["description"], "dimensions": dict(model["dimensions"]),
             "displayName": model["displayName"],
             "source": {"evidenceStatus": "authored", "generator": "factory02_light_models.py", "kind": "authored-primitive"},
             "sourceToCanonical": list(IDENTITY), "tags": list(model["tags"])}
    if model.get("footprint"):
        entry["footprintPolygons"] = [[{"x": x, "z": z} for x, z in model["footprint"]]]
    return entry


def _dump_like(original, value):
    """The catalog in the layout it already has (compact or indented), so only the light entries change."""
    styles = ({"separators": (",", ":"), "sort_keys": True}, {"indent": 2, "sort_keys": True}, {"indent": 2},
              {"separators": (",", ":")})
    parsed = json.loads(original)
    for style in styles:
        for ending in (b"", b"\n"):
            if json.dumps(parsed, **style).encode("ascii") + ending == original:
                return json.dumps(value, **style).encode("ascii") + ending
    return json.dumps(value, **styles[0]).encode("ascii")


def install(root=ROOT):
    """Write the models and their catalog entries under ROOT; returns what changed."""
    root = Path(root)
    folder = root / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for model in MODELS:
        raw = build(model)
        path = folder / model["file"]
        if not path.is_file() or path.read_bytes() != raw:
            path.write_bytes(raw)
            written.append(FOLDER + "/" + model["file"])
    from ai_inspector.industrial_assets.authored_library import CatalogLock, replace_file
    catalog_path = root / CATALOG
    with CatalogLock(catalog_path):   # the app adds authored shapes to the same catalog: one writer at a time
        original = catalog_path.read_bytes()
        library = json.loads(original)
        positions = {asset["assetId"]: index for index, asset in enumerate(library["assets"])}
        for model in MODELS:
            entry = catalog_entry(model)
            if model["assetId"] in positions:
                library["assets"][positions[model["assetId"]]] = entry
            else:
                library["assets"].append(entry)
        if isinstance(library.get("summary"), dict):
            library["summary"]["total"] = len(library["assets"])
        updated = _dump_like(original, library)
        if updated != original:
            replace_file(catalog_path, updated, unchanged=original)
    return {"modelsWritten": written, "catalogChanged": updated != original,
            "assetIds": [model["assetId"] for model in MODELS]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="project root holding generated/ (default: this one)")
    print(json.dumps(install(parser.parse_args().root)))


if __name__ == "__main__":
    main()
