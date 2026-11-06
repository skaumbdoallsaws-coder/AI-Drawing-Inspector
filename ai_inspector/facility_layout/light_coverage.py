"""Lighting coverage (docs/facility-lighting-plan.md, CC): estimated brightness on the floor from the layout's lamps,
and the dark spots between them. Always an estimate, not a lighting design, with no code-compliance claims.

Lamps (CC1). A lamp is found as the 3D view finds the lamps that throw floor pools (lampPartsOf in
static/facility_layout_light_pools.js): in a model part that shows a Lights finish, each connected piece whose
downward-facing patches make up at least a fifth of its surface; its centre is their area-weighted centre and its aim
their area-weighted normal, worked out in the part's own frame and carried into the layout as the view draws it
(placement, the model file's x mirror, sourceToCanonical, the node chain). The part's finish is the placement's own
part finish, else the finish its model names (a light's lens that comes lit), else the placement's finish. Only a
steady finish with `estimate` data in the appearance library counts (a typical output and beam angle: general and
outdoor lights); signal lights (beacons, stack lights, exit signs) light nothing here. A lamp tipped so that it no
longer faces down, or less than MIN_HEIGHT above the ground below it, counts as none, as for the pools. The saved
scene's switch (adjustments.lights false) turns every lamp off; its areas (adjustments.lightAreas, L7) turn lamps
off by where their centre is, as the view does (static/facility_layout_light_areas.js).

Low lights and uplights (2026-11-05, the gym's garden). A low outdoor light (emission.low: a bollard, a path light, a
lantern) counts from LOW_MIN_HEIGHT above the ground, and every glowing piece of it with a patch facing down is a lamp
(share 0, as the view's bulbsOf: a lantern's glass faces down only at its foot). The lamps of one lit part share the
finish's output, as the view's pools of one mesh share its light: a festoon string's eight bulbs give 400 lm between
them, not each. Each lit part is one light, as in the view. An uplight
(emission.uplight) lights what it faces, not the ground: it counts as none, and the summary lists it
(uplightsNotCounted).

Brightness (CC2). On a CELL grid over the chosen area (a floor area, a zone, a rectangle or the whole lot), each lamp
is a point source whose light fades away from its aim: I = I0 cos^m(theta) at theta off the aim, with m set so that it
is half the peak at the edge of the beam angle (as makers give a beam angle) and the whole output in the lamp's front
half, I0 = lumens (m + 1) / (2 pi). Then the inverse square law and the cosine of the angle onto level ground:
E = I h / d^3 for a cell h below the lamp and d from it, out to MAX_REACH. (Until 2026-11-01 the beam was even inside
its angle and dark outside it; that hard edge left pockets at 0 lux between car park poles.) Walls stop light (below);
nothing else casts a shadow, and there are no reflections, light loss or daylight. A lamp lights the area when it adds
at least LIGHTING_LUX somewhere in it. Dark spots are connected cells (sides touching) below a level: half the area's
mean unless one is given. A cell's value is the light at its centre, except near a lamp below SMOOTH_BELOW (a bollard,
a lantern: 2026-11-05 review): there the light changes a lot across one cell, so a centre alone swung with where the
lamp stood over it (a 0.3 m bollard over a cell's centre read 1605 lux there and 0.7 m away 59), and those cells take
the mean of a grid of points across each (_cell_means).

Walls (2026-11-01, the user's go). Until then the hall's light rows lit the truck yard through the dock wall. A lamp
lights a cell only if the line from the lamp to the cell clears every wall: where it crosses a wall's line in plan it
passes above the wall's top. A wall counts down to the ground, whatever its bottom: walls stand on a floor, and
ground lower than that floor behind one (Factory 02's truck yard is 1.35 m below the hall) gets no light under it. A
wall wholly above the lamp stops none of its light. The walls (blocking_walls) are each upright placement whose
catalog record is tagged "wall" (its centre line, from its catalog box as placed) and each "wall" feature of the
layout's shell as the spatial checks see it (the shell's own walls and the layout's perimeter and interior walls: the
outline of each, those of one height merged first). Mesh guards, fences, doors and racks are not walls: light passes
them, and a gap between walls (an open dock door's) in full. A dark spot's nearest lamps are the nearest that no wall
hides from its centre.

The lot (2026-11-01, a CC bug found on Factory 02): the car parks and truck yards are outdoor ground. Zones named
parking, car park, yard or lot, and zones holding parking bays out of doors, less the building and the floor areas.
The building (building_footprint) is what each placement tagged "roof" and "building" covers and the outline the
layout's perimeter walls follow. Until then Factory 02's lot took in the hall's Equipment Service + Utilities zone
(its equipment bays are parking bays): 1,968 sq m of hall floor at about 264 lux.
"""
from collections import Counter
import math
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import numpy as np
import shapely
from shapely.geometry import MultiPoint, Polygon, box
from shapely.ops import unary_union

NAME = "check_lighting_coverage"
CAPTION = "Estimate, not a lighting design. No code-compliance claims."
CELL = 1.0                  # m: the grid
MAX_CELLS = 600_000         # cells in one check (Factory 02's whole lot is about 92,000)
MAX_REACH = 60.0            # m from a lamp (plan distance): its light is cut here; a 20000 lm row lamp 9 m up adds
                            # about 0.04 lux this far out
LIGHTING_LUX = 0.5          # a lamp lights an area when it adds at least this somewhere in it
FACING_DOWN = -0.7          # as static/facility_layout_light_pools.js
MIN_LAMP_AREA = 0.0005      # square metres; a smaller downward patch is a sliver, not a lamp
MIN_LAMP_SHARE = 0.2        # a lamp's downward patches make up at least this share of its piece's surface
MIN_HEIGHT = 3.0            # m above the ground below it; lower glows throw no pool and count as no lamp
LOW_MIN_HEIGHT = 0.1        # m: a low outdoor light (emission.low: a bollard, a lantern) counts from here
SMOOTH_BELOW = 2.0          # m: near a lamp this low, cells take the mean over points across each (_cell_means) ...
SMOOTH_REACH = 3.0          # ... within this many times its height of it, and at least 2 m, plus a cell
DARK_SHARE = 0.5            # default dark level: this share of the area's mean
LISTED_SPOTS = 20
NEAREST_LAMPS = 3
OUTSIDE_VALUE = 65535       # the view's grid (CC3): a cell outside the area
EDGE = 1e-6                 # m: a lamp this close to an area's edge is inside it (L7)
MIRROR = np.diag([-1.0, 1.0, 1.0, 1.0])
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
LIMITATIONS = [
    "Lamp outputs and beam angles are typical values for each Lights finish, not the real fittings' data.",
    "Each lamp is a point whose light fades away from its aim, to half at the edge of its beam angle and less past "
    "it. Walls stop it (wall placements and the building's own walls, up to their top); doors, racks, machines and "
    "other items cast no shadows. No reflections, no light loss over time and no daylight.",
    "Brightness is on the floor or ground (horizontal), on a 1 m grid.",
    "Only lamps with a general or outdoor Lights finish count, hung at least 3 m up (low outdoor lights such as "
    "bollards and lanterns from any height); signal lights and uplights do not.",
]
_GEOMETRY_CACHE = {}
_VISUAL_PATHS = {}


def tool_spec():
    return {"name": NAME, "description":
        "Estimate how well the saved layout's lights cover a floor area, a zone, a rectangle or the whole lot, and "
        "list the dark spots between lamps. Give exactly one of floorAreaId (inspect_facility_authoring "
        "floor_surfaces), zoneId (e.g. a car park or the truck yard), rectangle {minX, minZ, maxX, maxZ} in plan "
        "metres, or lot: true. Optional darkBelowLux sets the dark level (default: half the area's mean). Lamps are "
        "the layout's general and outdoor lights (Lights finishes; low ones such as bollards and lanterns count from "
        "any height, uplights not at all) with typical outputs; the saved scene's lights "
        "switch and light areas apply; walls stop light, nothing else casts shadows. Returns estimated lux (minimum, "
        "mean, maximum) and the dark spots with their "
        "centres, sizes and nearest lamps. It is an estimate, not a lighting design: always say so ("
        + CAPTION + ") and never claim it meets or fails a code or standard. Read-only.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "floorAreaId": {"type": "string", "minLength": 1, "maxLength": 120},
            "zoneId": {"type": "string", "minLength": 1, "maxLength": 128},
            "rectangle": {"type": "object", "additionalProperties": False,
                          "required": ["minX", "minZ", "maxX", "maxZ"],
                          "properties": {key: {"type": "number"} for key in ("minX", "minZ", "maxX", "maxZ")}},
            "lot": {"type": "boolean"},
            "darkBelowLux": {"type": "number", "minimum": 0, "maximum": 100000}}}}


# Lamps (CC1) -------------------------------------------------------------------------------------------------------

def lamp_data(library):
    """{appearanceId: {"lumens", "beamAngleDegrees"}} for the steady Lights finishes with estimate data."""
    result = {}
    for appearance_id, row in library["appearances"].items():
        estimate, emission = row.get("estimate"), row.get("emission")
        if (isinstance(estimate, dict) and emission and emission.get("pattern", "steady") == "steady"
                and not emission.get("uplight")):   # an uplight lights what it faces, not the ground
            result[appearance_id] = {"label": row.get("label", appearance_id), "lumens": float(estimate["lumens"]),
                                     "beamAngleDegrees": float(estimate["beamAngleDegrees"])}
    return result


def _matrix(values):
    values = [float(value) for value in values]
    if len(values) != 16 or not all(math.isfinite(value) for value in values):
        raise ValueError("A matrix needs 16 finite numbers")
    return np.array(values, dtype=np.float64).reshape((4, 4), order="F")   # column-major, as three.js


def placement_matrix(transform):
    """The placement's layout transform: position, then quaternion, then uniform scale."""
    p, q = transform["position"], transform.get("quaternion") or {"x": 0, "y": 0, "z": 0, "w": 1}
    x, y, z, w = (float(q[key]) for key in ("x", "y", "z", "w"))
    norm = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    scale = float(transform.get("scale", 1) or 1)
    result = np.eye(4)
    result[:3, :3] = scale * np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    result[:3, 3] = [float(p["x"]), float(p["y"]), float(p["z"])]
    return result


def _components(count, triangles, mask):
    """Connected corner groups, joining the corners of each triangle in MASK."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    rows = np.concatenate([triangles[mask, 0], triangles[mask, 1]])
    cols = np.concatenate([triangles[mask, 1], triangles[mask, 2]])
    graph = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(count, count))
    return connected_components(graph, directed=False)[1]


def lamp_parts(positions, triangles, share=MIN_LAMP_SHARE):
    """The lamps in one triangle geometry, as lampPartsOf in static/facility_layout_light_pools.js: a list of
    (centre, aim, area) in the geometry's own coordinates. SHARE 0 takes every piece with a downward patch, as the
    view's bulbsOf does (a low outdoor light's lamps)."""
    positions = np.asarray(positions, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if not len(triangles):
        return []
    keys = np.floor(positions * 1e4 + 0.5).astype(np.int64)    # Math.round, joined by position as the view does
    _, corner = np.unique(keys, axis=0, return_inverse=True)
    corners = np.asarray(corner).reshape(-1)[triangles]
    points = positions[triangles]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    length = np.linalg.norm(normals, axis=1)
    areas = length / 2
    count = int(corners.max()) + 1
    piece = _components(count, corners, np.ones(len(corners), dtype=bool))[corners[:, 0]]
    surface = np.bincount(piece, weights=areas)
    down = (length > 1e-12) & (normals[:, 1] < FACING_DOWN * np.where(length > 0, length, 1))
    if not down.any():
        return []
    patch = _components(count, corners, down)[corners[down, 0]]
    weights = areas[down]
    centres = points[down].mean(axis=1)
    halves = normals[down] / 2
    patch_ids, first = np.unique(patch, return_index=True)
    lookup = np.searchsorted(patch_ids, patch)
    patch_area = np.bincount(lookup, weights=weights)
    keep = patch_area >= MIN_LAMP_AREA
    sums = {name: np.bincount(lookup, weights=values) for name, values in
            (("x", centres[:, 0] * weights), ("y", centres[:, 1] * weights), ("z", centres[:, 2] * weights),
             ("nx", halves[:, 0]), ("ny", halves[:, 1]), ("nz", halves[:, 2]))}
    owner = piece[np.flatnonzero(down)[first]]
    lamps = []
    for owner_piece in np.unique(owner[keep]):
        rows = keep & (owner == owner_piece)
        area = patch_area[rows].sum()
        if area <= 0 or area < share * surface[owner_piece]:
            continue
        centre = np.array([sums[key][rows].sum() for key in ("x", "y", "z")]) / area
        aim = np.array([sums[key][rows].sum() for key in ("nx", "ny", "nz")])
        norm = np.linalg.norm(aim)
        lamps.append((centre, aim / norm if norm > 0 else aim, float(area)))
    return lamps


def _visual_path(value, root):
    """A catalog visual's GLB under ROOT/generated, or None (anything else is not read). Resolved once per path."""
    if not isinstance(value, str):
        return None
    key = (value, str(root))
    if key not in _VISUAL_PATHS:
        if len(_VISUAL_PATHS) > 4096:
            _VISUAL_PATHS.clear()
        _VISUAL_PATHS[key] = _resolve_visual(value, root)
    path = _VISUAL_PATHS[key]
    return path if path is not None and path.is_file() else None


def _resolve_visual(value, root):
    parsed = urlsplit(value)
    relative = Path(unquote(parsed.path).lstrip("/"))
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or relative.is_absolute()
            or ".." in relative.parts or "\\" in parsed.path or ":" in str(relative)):
        return None
    root = Path(root).resolve()
    path = root / relative
    if path.suffix.lower() != ".glb" or not path.resolve().is_relative_to((root / "generated").resolve()):
        return None
    return path


def _read_json_chunk(path):
    """A GLB's JSON chunk alone (the geometry is read only for light parts)."""
    import json
    import struct
    with path.open("rb") as stream:
        head = stream.read(20)
        if len(head) < 20:
            raise ValueError("GLB is truncated")
        magic, version, _ = struct.unpack_from("<4sII", head, 0)
        length, kind = struct.unpack_from("<I4s", head, 12)
        if magic != b"glTF" or version != 2 or kind != b"JSON" or length > 64 * 1024 * 1024:
            raise ValueError("Not a GLB 2.0 file")
        return json.loads(stream.read(length).rstrip(b" \t\r\n\x00").decode("utf-8"))


def _model(path):
    """A GLB's triangle parts: part keys, default finishes and node matrices (geometry later). Cached by file."""
    from ai_inspector.assembly_knowledge.glb_masks import _node_matrix
    from ai_inspector.codex_runtime.component_inventory import _slot_origins, material_slots
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key in _GEOMETRY_CACHE:
        return _GEOMETRY_CACHE[key]
    document = _read_json_chunk(path)
    nodes = document.get("nodes", [])
    world = {}

    def visit(index, parent):
        if index in world:
            return
        world[index] = parent @ _node_matrix(nodes[index])
        for child in nodes[index].get("children", []):
            visit(child, world[index])
    for index in document["scenes"][document.get("scene", 0)].get("nodes", []):
        visit(index, np.eye(4))
    parts = []
    for slot, (node_index, primitive_index) in zip(material_slots(document), _slot_origins(document)):
        primitive = document["meshes"][nodes[node_index]["mesh"]]["primitives"][primitive_index]
        if primitive.get("mode", 4) == 4:   # strips and fans are not lenses
            parts.append({"key": slot["key"], "legacyKey": slot["legacyKey"], "defaultFinish": slot.get("defaultFinish"),
                          "node": world[node_index], "primitive": primitive})
    if len(_GEOMETRY_CACHE) > 512:
        _GEOMETRY_CACHE.clear()
    _GEOMETRY_CACHE[key] = model = {"path": path, "document": document, "parts": parts}
    return model


def _geometry(model, part):
    """A part's positions and triangles, read from the GLB the first time a light part needs them."""
    if "positions" not in part:
        from ai_inspector.assembly_knowledge.glb_masks import _accessor, _read_glb
        if "binary" not in model:
            model["binary"] = _read_glb(model["path"])[1]
        document, binary, primitive = model["document"], model["binary"], part["primitive"]
        positions = _accessor(document, binary, primitive["attributes"]["POSITION"]).astype(np.float64)
        indices = (_accessor(document, binary, primitive["indices"]).reshape(-1) if "indices" in primitive
                   else np.arange(len(positions)))
        part["positions"] = positions
        part["triangles"] = indices.astype(np.int64)[: len(indices) // 3 * 3].reshape(-1, 3)
    return part


def _model_lamps(model, primitive, source_to_canonical, share=MIN_LAMP_SHARE):
    """A part's lamps in its own frame as the view holds it (mirrored across the model's x = 0 with the winding
    restored), and the part's matrix in the placed model (sourceToCanonical, then the node chain). SHARE as
    lamp_parts."""
    cache = primitive.setdefault("lamps", {})
    _geometry(model, primitive)
    key = (tuple(np.round(source_to_canonical.reshape(-1), 9)), share)
    if key not in cache:
        local = source_to_canonical @ primitive["node"]
        reflect = np.linalg.inv(local) @ MIRROR @ local
        points = np.c_[primitive["positions"], np.ones(len(primitive["positions"]))] @ reflect.T
        cache[key] = (local, lamp_parts(points[:, :3], primitive["triangles"][:, [0, 2, 1]], share))
    return cache[key]


def _part_finishes(placement, primitive, representation):
    """The finish a part shows: its own part finish, else the model's default, else the placement's finish."""
    materials = placement.get("componentMaterials") or {}
    same = materials.get("representation") == representation
    own = {row.get("key"): row for row in materials.get("overrides", []) if isinstance(row, dict)}
    row = own.get(primitive["key"]) or (own.get(primitive["legacyKey"]) if same else None)
    if row is not None:
        return row.get("appearanceId"), row.get("pattern")
    if primitive.get("defaultFinish"):
        return primitive["defaultFinish"], None
    appearance = placement.get("appearance")
    if isinstance(appearance, dict):
        return appearance.get("appearanceId"), appearance.get("pattern")
    return None, None


def _ground_rows(layout):
    ground = (layout.get("extensions") or {}).get("facilityGround") or {}
    return [row for row in ground.get("surfaces", []) if isinstance(row, dict)]


def ground_heights(layout, xs, zs):
    """The ground's height under plan points, as static/facility_layout_ground.js (floorElevation off the ground)."""
    xs, zs = np.asarray(xs, dtype=np.float64), np.asarray(zs, dtype=np.float64)
    floor = float((layout.get("coordinateFrame") or {}).get("floorElevation") or 0.0)
    heights = np.full(xs.shape, floor)
    found = np.zeros(xs.shape, dtype=bool)
    for row in _ground_rows(layout):
        inside = (~found & (xs >= row["minX"] - 1e-8) & (xs <= row["maxX"] + 1e-8)
                  & (zs >= row["minZ"] - 1e-8) & (zs <= row["maxZ"] + 1e-8))
        if not inside.any():
            continue
        if row["slopeAxis"] == "x":
            t = (xs[inside] - row["minX"]) / (row["maxX"] - row["minX"])
        else:
            t = (zs[inside] - row["minZ"]) / (row["maxZ"] - row["minZ"])
        heights[inside] = row["startElevation"] + np.clip(t, 0, 1) * (row["endElevation"] - row["startElevation"])
        found |= inside
    return heights


def _floor_shapes(layout):
    rows = ((layout.get("extensions") or {}).get("facilityFloorSurfaces") or {}).get("surfaces") or []
    return {row["surfaceId"]: row for row in rows if isinstance(row, dict) and row.get("surfaceId")}


def _polygon(points):
    points = [(float(p["x"]), float(p["z"])) for p in points or [] if isinstance(p, dict)]
    if len(points) < 3:
        return None
    shape = Polygon(points)
    return shape if shape.is_valid else shape.buffer(0)


def scene_switches(layout):
    """The saved scene's lights switch and its L7 areas: (switch on, [area shapes] or None, mode, missing ids)."""
    scene = (layout.get("extensions") or {}).get("facilityScene") or {}
    adjustments = scene.get("adjustments") or {}
    on = adjustments.get("lights") is not False
    value = adjustments.get("lightAreas")
    if not isinstance(value, dict) or value.get("mode") not in ("only", "except") or not isinstance(
            value.get("areas"), list):
        return on, None, None, []
    floors, shapes, missing = _floor_shapes(layout), [], []
    for area in value["areas"][:64]:
        if isinstance(area, dict) and isinstance(area.get("surfaceId"), str):
            shape = _polygon((floors.get(area["surfaceId"]) or {}).get("boundary"))
            if shape is None:
                missing.append(area["surfaceId"])
            else:
                shapes.append(shape)
            continue
        rect = (area or {}).get("rectangle") if isinstance(area, dict) else None
        if isinstance(rect, dict) and all(isinstance(rect.get(k), (int, float)) for k in ("minX", "minZ", "maxX", "maxZ")) \
                and rect["maxX"] > rect["minX"] and rect["maxZ"] > rect["minZ"]:
            shapes.append(box(rect["minX"], rect["minZ"], rect["maxX"], rect["maxZ"]))
    return on, shapes, value["mode"], missing


def _area_lit(shapes, mode, x, z):
    if shapes is None:
        return True
    inside = any(shape.distance(shapely.Point(x, z)) <= EDGE for shape in shapes)
    return inside if mode == "only" else not inside


def find_lamps(layout, catalog, library, project_root):
    """Every lamp of a general or outdoor Lights finish in the layout, with whether the saved scene has it on."""
    data = lamp_data(library)
    emissions = {key: row.get("emission") or {} for key, row in library["appearances"].items()}
    low = {key for key, emission in emissions.items() if emission.get("low") is True}
    uplights = {key for key, emission in emissions.items() if emission.get("uplight") is True}
    switch_on, shapes, mode, _ = scene_switches(layout)
    lamps, unread, signals, upward, models = [], set(), Counter(), Counter(), {}
    for placement in layout.get("placements", []):
        record = catalog.get((placement.get("assetId"), placement.get("assetDefinitionRevision")))
        if record is None:
            continue
        representation = (placement.get("componentMaterials") or {}).get("representation") or "overview"
        visuals = record.get("representations") or {}
        visual = next((v for v in (record.get(representation), visuals.get(representation), record.get("overview"),
                                   visuals.get("overview"), record.get("detail"), visuals.get("detail"))
                       if isinstance(v, dict)), None)
        path = _visual_path((visual or {}).get("path"), project_root)
        if path is None:
            continue
        try:
            model = models[path] if path in models else models.setdefault(path, _model(path))
        except Exception:  # noqa: BLE001 -- a model that cannot be read lights nothing here, and is reported
            unread.add(placement["assetId"])
            continue
        matrix = None
        for part, primitive in enumerate(model["parts"]):
            finish, pattern = _part_finishes(placement, primitive, representation)
            row = library["appearances"].get(finish) if finish else None
            if not row or not row.get("emission"):
                continue
            if finish in uplights:    # it lights the palm, plant or wall it faces, not the ground
                upward[row.get("label", finish)] += 1
                continue
            if finish not in data or (pattern and pattern != "steady"):
                signals[row.get("label", finish)] += 1
                continue
            if matrix is None:
                frame = (visual or {}).get("sourceToCanonical") or (
                    ((record.get("definition") or {}).get("coordinateFrame") or {}).get("sourceToCanonical")) or IDENTITY
                matrix = placement_matrix(placement["transform"]), _matrix(frame)
            place, frame = matrix
            try:
                local, parts = _model_lamps(model, primitive, frame, 0.0 if finish in low else MIN_LAMP_SHARE)
            except Exception:  # noqa: BLE001 -- as above
                unread.add(placement["assetId"])
                continue
            whole = place @ local
            down = whole[:3, :3] @ np.array([0.0, -1.0, 0.0])
            if not parts or down[1] / (np.linalg.norm(down) or 1) > FACING_DOWN:
                continue    # tipped over: its lamps no longer face the floor
            for centre, aim, _area in parts:
                point = whole @ np.append(centre, 1.0)
                direction = whole[:3, :3] @ aim
                direction = direction / (np.linalg.norm(direction) or 1)
                if direction[1] > FACING_DOWN:
                    continue
                lamps.append({"placementId": placement["placementId"],
                              "label": (placement.get("metadata") or {}).get("instanceLabel") or placement["assetId"],
                              "finish": finish, "x": float(point[0]), "y": float(point[1]), "z": float(point[2]),
                              "aim": [float(v) for v in direction],
                              "lumens": data[finish]["lumens"], "beamAngleDegrees": data[finish]["beamAngleDegrees"],
                              "_part": part})
    below = ground_heights(layout, [lamp["x"] for lamp in lamps], [lamp["z"] for lamp in lamps]) if lamps else []
    kept = []
    for lamp, ground in zip(lamps, below):
        height = lamp["y"] - float(ground)
        if height < (LOW_MIN_HEIGHT if lamp["finish"] in low else MIN_HEIGHT):
            continue    # as for the pools: a glow this low is no lamp (a low outdoor light's, from LOW_MIN_HEIGHT)
        on = switch_on and _area_lit(shapes, mode, lamp["x"], lamp["z"])
        kept.append(dict(lamp, heightMeters=round(height, 2), on=bool(on),
                         off=None if on else ("switch" if not switch_on else "area")))
    # A low part's lamps (a festoon string's bulbs) share its output, as the view's pools of one mesh share its light:
    # each lit part is one light, in the view and here alike.
    shared = Counter((lamp["placementId"], lamp["finish"], lamp["_part"]) for lamp in kept if lamp["finish"] in low)
    for lamp in kept:
        count = shared.get((lamp["placementId"], lamp["finish"], lamp.pop("_part")), 0)
        if count > 1:
            lamp["lumens"] = lamp["lumens"] / count
    return kept, {"unreadModels": sorted(unread), "signalLightParts": dict(signals), "uplightParts": dict(upward)}


# Brightness (CC2) --------------------------------------------------------------------------------------------------

def area_of(layout, arguments, catalog=None):
    """The area to check: (shape, {kind, id, label}). CATALOG (as blocking_walls takes it) finds the building's roof,
    which the lot leaves out (building_footprint)."""
    given = [key for key in ("floorAreaId", "zoneId", "rectangle", "lot")
             if arguments.get(key) not in (None, False)]
    if len(given) != 1:
        raise ValueError("Give exactly one of floorAreaId, zoneId, rectangle or lot.")
    kind = given[0]
    if kind == "floorAreaId":
        row = _floor_shapes(layout).get(arguments["floorAreaId"])
        shape = _polygon((row or {}).get("boundary"))
        if shape is None:
            raise ValueError("That floor area is not in the saved layout (inspect_facility_authoring floor_surfaces).")
        return shape, {"kind": "floor_area", "id": row["surfaceId"], "label": row.get("label") or row["surfaceId"]}
    if kind == "zoneId":
        row = next((z for z in layout.get("zones", []) if z.get("zoneId") == arguments["zoneId"]), None)
        shape = _polygon((row or {}).get("boundary"))
        if shape is None:
            raise ValueError("That zone is not in the saved layout.")
        return shape, {"kind": "zone", "id": row["zoneId"], "label": row.get("label") or row["zoneId"]}
    if kind == "rectangle":
        rect = arguments["rectangle"]
        if not all(isinstance(rect.get(k), (int, float)) and math.isfinite(rect[k])
                   for k in ("minX", "minZ", "maxX", "maxZ")) or rect["maxX"] - rect["minX"] < CELL \
                or rect["maxZ"] - rect["minZ"] < CELL:
            raise ValueError("A rectangle needs minX < maxX and minZ < maxZ, at least 1 m each way.")
        return box(rect["minX"], rect["minZ"], rect["maxX"], rect["maxZ"]), {
            "kind": "rectangle", "id": None,
            "label": f"x {rect['minX']:g} to {rect['maxX']:g}, z {rect['minZ']:g} to {rect['maxZ']:g}"}
    indoors = [shape for shape in (_polygon(row.get("boundary")) for row in _floor_shapes(layout).values()) if shape]
    building = building_footprint(layout, catalog)
    indoor = unary_union(indoors + ([building] if building is not None else []))
    lots = [(zone, shape) for zone, shape in ((z, _polygon(z.get("boundary"))) for z in layout.get("zones", []))
            if shape is not None and _is_lot(layout, zone, shape, indoor)
            and shape.difference(indoor).area >= CELL * CELL]
    lot = unary_union([shape for _, shape in lots]).difference(indoor) if lots else None
    if lot is None or lot.area < CELL * CELL:
        raise ValueError("This layout has no car park or truck yard zone; check one zone, floor area or rectangle instead.")
    return lot, {"kind": "lot", "id": None, "label": "the car parks and truck yards",
                 "zoneIds": [zone["zoneId"] for zone, _ in lots]}


def _is_lot(layout, zone, shape, indoor=None):
    """A car park or truck yard: a zone named so, or one holding parking bays (as the parking review finds them) out
    of doors. A bay in the building or a floor area (INDOOR) is a forklift's or a machine's (Factory 02's Equipment
    Service + Utilities zone has 12)."""
    if re.search(r"\bparking\b|\bcar\s*park\b|\byard\b|\blot\b", str(zone.get("label") or ""), re.I):
        return True
    for mark in layout.get("floorMarkings", []):
        if mark.get("markingType") == "parking_box" and mark.get("semanticRole") != "staging":
            p = (mark.get("transform") or {}).get("position") or {}
            point = shapely.Point(float(p.get("x", 0)), float(p.get("z", 0)))
            if shape.covers(point) and (indoor is None or not indoor.covers(point)):
                return True
    return False


def building_footprint(layout, catalog=None):
    """The building in plan, which the lot leaves out: what each placement tagged "roof" and "building" covers (its
    catalog box as placed; Factory 02's roof deck over the hall) and the outline the layout's perimeter walls follow
    (facilityPerimeterWalls: the plan's edges or their own polygon). CATALOG maps (assetId, revision) or assetId to a
    record, as light_positions reads it. None when the layout shows no building."""
    from .light_positions import _aabb, _record_for, _tags
    from .spatial import _quaternion, _rotate_vector
    extensions = layout.get("extensions") or {}
    shapes = []
    settings = (extensions.get("facilityPerimeterWalls") or {}).get("settings") or {}
    if settings.get("boundarySource") == "polygon":
        shapes.append(_polygon(settings.get("boundary")))
    elif settings.get("boundarySource") == "plan":
        plan = extensions.get("facilityPlan") or {}
        try:
            shapes.append(box(0.0, 0.0, float(plan["widthMeters"]), float(plan["depthMeters"])))
        except (KeyError, TypeError, ValueError):
            pass
    for placement in layout.get("placements", []) if catalog else []:
        record = _record_for(catalog, placement)
        if record is None or not {"roof", "building"} <= _tags(record):
            continue
        transform = placement.get("transform") or {}
        try:
            q = _quaternion(transform.get("quaternion"))
            position = transform["position"]
            scale = float(transform.get("scale", 1))
            low, high = _aabb(record)
            corners = [_rotate_vector((x * scale, y * scale, z * scale), q) for x in (low["x"], high["x"])
                       for y in (low["y"], high["y"]) for z in (low["z"], high["z"])]
            shapes.append(MultiPoint([(float(position["x"]) + c[0], float(position["z"]) + c[2])
                                      for c in corners]).convex_hull)
        except (KeyError, TypeError, ValueError):
            continue
    shapes = [shape for shape in shapes if shape is not None and shape.area > 0]
    return unary_union(shapes) if shapes else None


# Walls ---------------------------------------------------------------------------------------------------------------

def blocking_walls(layout, catalog, shell=None):
    """The walls that stop light, each (ax, az, bx, bz, bottom, top): a line in plan and the heights it spans.
    - An upright placement whose catalog record is tagged "wall": its centre line, from its catalog box turned, scaled
      and moved as placed. CATALOG maps (assetId, revision) or assetId to a record, as light_positions reads it.
    - A "wall" feature of SHELL, the layout's shell as the spatial checks see it (the service's effective_shell: its
      own walls and the layout's perimeter and interior walls): the edges of its outline, the features of one height
      merged first (perimeter walls come as up to 1024 triangles).
    Mesh guards, fences, doors and racks are not walls: light passes them."""
    from .light_positions import _aabb, _axes, _record_for, _tags
    from .spatial import _quaternion, _rotate_vector, _shell_feature_interval, _shell_feature_polygon
    walls = []
    for placement in layout.get("placements", []):
        record = _record_for(catalog, placement)
        if record is None or "wall" not in _tags(record):
            continue
        transform = placement.get("transform") or {}
        try:
            q = _quaternion(transform.get("quaternion"))
            position = transform["position"]
            scale = float(transform.get("scale", 1))
        except (KeyError, TypeError, ValueError):
            continue
        low, high = _aabb(record)
        if not low or not high or abs(_rotate_vector((0.0, 1.0, 0.0), q)[1] - 1) > 1e-6:
            continue                                # a wall on its side or tipped over is not one here
        corners = [_rotate_vector((x * scale, 0.0, z * scale), q) for x in (low["x"], high["x"])
                   for z in (low["z"], high["z"])]
        outline = Polygon([(position["x"] + c[0], position["z"] + c[2]) for c in corners]).convex_hull
        (cx, cz), axis, half, _ = _axes(outline)
        if half <= 0:
            continue
        walls.append((cx - axis[0] * half, cz - axis[1] * half, cx + axis[0] * half, cz + axis[1] * half,
                      float(position["y"]) + scale * float(low["y"]), float(position["y"]) + scale * float(high["y"])))
    by_height = {}
    for feature in (shell or {}).get("features", []) or []:
        if not isinstance(feature, dict) or feature.get("featureKind") != "wall":
            continue
        try:
            points, interval = _shell_feature_polygon(feature), _shell_feature_interval(feature)
        except (TypeError, ValueError):
            continue
        if points is not None:
            by_height.setdefault(interval, []).append(Polygon(points).buffer(0))
    for (bottom, top), outlines in sorted(by_height.items()):
        merged = unary_union(outlines).simplify(1e-9)
        boundary = merged.boundary
        for line in getattr(boundary, "geoms", [boundary]):
            coords = list(line.coords)
            walls.extend((ax, az, bx, bz, float(bottom), float(top)) for (ax, az), (bx, bz) in zip(coords, coords[1:]))
    return walls


def _crosses(lx, ly, lz, cx, cz, ground, ax, az, bx, bz, top):
    """Whether the line from the lamp at (lx, ly, lz) to the ground point (cx, ground, cz) crosses the wall line
    (ax, az)-(bx, bz) in plan, between the two, below the wall's top (numpy broadcasting). The wall counts down to the
    ground (the module's note on walls)."""
    dx, dz, ex, ez, wx, wz = cx - lx, cz - lz, bx - ax, bz - az, ax - lx, az - lz
    across = dx * ez - dz * ex
    safe = np.where(across != 0, across, 1.0)
    t = (wx * ez - wz * ex) / safe          # along the line, from the lamp (0) to the point (1)
    u = (wx * dz - wz * dx) / safe          # along the wall, from one end (0) to the other (1)
    return (across != 0) & (t > 0) & (t < 1) & (u >= 0) & (u <= 1) & (ly + t * (ground - ly) < top)


def _shadowed(lamp, walls, xs, zs, ground, wanted):
    """Which of the WANTED cells (a window of the grid: centres XS, ZS, ground heights GROUND) the WALLS hide from
    LAMP. Only the walls within reach, not wholly above the lamp and topping the lowest ground; for each, only the
    cells not yet hidden in the box round the plan region it can hide: past it, within the angle it spans from the
    lamp, out to where a line to the lowest ground clears its top (to the window's edge when its top is at or above
    the lamp)."""
    hidden = np.zeros(xs.shape, dtype=bool)
    if not wanted.any():
        return hidden
    lx, ly, lz = lamp["x"], lamp["y"], lamp["z"]
    ax, az, bx, bz, bottom, top = walls.T
    ex, ez = bx - ax, bz - az
    along = np.clip(((lx - ax) * ex + (lz - az) * ez) / np.maximum(ex * ex + ez * ez, 1e-12), 0.0, 1.0)
    reach = np.hypot(ax + along * ex - lx, az + along * ez - lz) <= MAX_REACH
    low = float(ground[wanted].min())
    first_x, first_z, rows, cols = float(xs[0, 0]), float(zs[0, 0]), xs.shape[0], xs.shape[1]
    for i in np.flatnonzero(reach & (top > low) & (bottom < ly)):
        k = (ly - low) / (ly - top[i]) if top[i] < ly else 1e6
        px = (ax[i], bx[i], lx + k * (ax[i] - lx), lx + k * (bx[i] - lx))
        pz = (az[i], bz[i], lz + k * (az[i] - lz), lz + k * (bz[i] - lz))
        c0 = max(0, math.floor((min(px) - first_x) / CELL))
        c1 = min(cols, math.ceil((max(px) - first_x) / CELL) + 1)
        r0 = max(0, math.floor((min(pz) - first_z) / CELL))
        r1 = min(rows, math.ceil((max(pz) - first_z) / CELL) + 1)
        if c0 >= c1 or r0 >= r1:
            continue
        open_rows, open_cols = np.nonzero(wanted[r0:r1, c0:c1] & ~hidden[r0:r1, c0:c1])
        if len(open_rows):
            open_rows, open_cols = open_rows + r0, open_cols + c0
            behind = _crosses(lx, ly, lz, xs[open_rows, open_cols], zs[open_rows, open_cols],
                              ground[open_rows, open_cols], ax[i], az[i], bx[i], bz[i], top[i])
            hidden[open_rows[behind], open_cols[behind]] = True
    return hidden


def _hidden_from(lamps, walls, x, z, ground):
    """Which of LAMPS one of WALLS hides the ground point (x, ground, z) from."""
    if walls is None or not len(walls) or not lamps:
        return np.zeros(len(lamps), dtype=bool)
    lx, ly, lz = (np.array([[lamp[key]] for lamp in lamps], dtype=float) for key in "xyz")
    ax, az, bx, bz, bottom, top = walls.T
    return (_crosses(lx, ly, lz, x, z, ground, ax, az, bx, bz, top) & (bottom < ly)).any(axis=1)


def estimate(layout, lamps, shape, dark_below=None, walls=()):
    """Estimated lux on a CELL grid over SHAPE from the lamps that are on: the grid, totals and dark spots. Only the
    cells inside SHAPE are worked out; the others in its bounding grid are not read. WALLS (blocking_walls) stop
    light."""
    walls = np.asarray(walls, dtype=float).reshape(-1, 6)
    min_x, min_z, max_x, max_z = shape.bounds
    x0, z0 = math.floor(min_x / CELL) * CELL, math.floor(min_z / CELL) * CELL
    cols, rows = max(1, math.ceil((max_x - x0) / CELL)), max(1, math.ceil((max_z - z0) / CELL))
    if cols * rows > MAX_CELLS:
        raise ValueError(f"That area is too large to check at once ({cols} x {rows} m); choose a smaller one.")
    xs = x0 + CELL * (np.arange(cols) + 0.5)
    zs = z0 + CELL * (np.arange(rows) + 0.5)
    grid_x, grid_z = np.meshgrid(xs, zs)
    shapely.prepare(shape)
    inside = shapely.intersects_xy(shape, grid_x, grid_z)
    if not inside.any():
        raise ValueError("That area is smaller than one 1 m cell.")
    ground = ground_heights(layout, grid_x, grid_z)
    lux = np.zeros((rows, cols))
    lit = [lamp for lamp in lamps if lamp["on"]]
    reaching = 0
    for lamp in lit:
        # Half the peak at the beam angle's edge: cos(half the beam)^m = 1/2. The whole output over the front half:
        # the integral of I0 cos^m over it is 2 pi I0 / (m + 1).
        power = math.log(0.5) / math.log(math.cos(math.radians(lamp["beamAngleDegrees"]) / 2))
        peak = lamp["lumens"] * (power + 1) / (2 * math.pi)
        aim = np.asarray(lamp["aim"])
        c0 = max(0, math.floor((lamp["x"] - MAX_REACH - x0) / CELL))
        c1 = min(cols, math.ceil((lamp["x"] + MAX_REACH - x0) / CELL))
        r0 = max(0, math.floor((lamp["z"] - MAX_REACH - z0) / CELL))
        r1 = min(rows, math.ceil((lamp["z"] + MAX_REACH - z0) / CELL))
        if c0 >= c1 or r0 >= r1:
            continue
        window = inside[r0:r1, c0:c1]          # only the area's cells are read: trim to them
        rows_in, cols_in = np.flatnonzero(window.any(axis=1)), np.flatnonzero(window.any(axis=0))
        if not len(rows_in):
            continue
        r0, r1, c0, c1 = r0 + rows_in[0], r0 + rows_in[-1] + 1, c0 + cols_in[0], c0 + cols_in[-1] + 1
        dx = grid_x[r0:r1, c0:c1] - lamp["x"]
        dz = grid_z[r0:r1, c0:c1] - lamp["z"]
        drop = lamp["y"] - ground[r0:r1, c0:c1]
        distance = np.sqrt(dx * dx + dz * dz + drop * drop)
        safe = np.where(distance > 1e-9, distance, 1.0)
        facing = (dx * aim[0] - drop * aim[1] + dz * aim[2]) / safe     # the cosine of the angle off the aim
        lit_here = (drop > 0) & (facing > 0) & (dx * dx + dz * dz <= MAX_REACH * MAX_REACH)
        add = np.where(lit_here, peak * np.clip(facing, 0.0, 1.0) ** power * drop / safe ** 3, 0.0)
        height = lamp.get("heightMeters")
        if height is None:
            ci = min(max(int((lamp["x"] - x0) // CELL) - c0, 0), c1 - c0 - 1)
            ri = min(max(int((lamp["z"] - z0) // CELL) - r0, 0), r1 - r0 - 1)
            height = float(drop[ri, ci])
        if 0 < height < SMOOTH_BELOW:
            add = _cell_means(add, aim, peak, power, dx, dz, drop, height)
        if len(walls):
            add = np.where(_shadowed(lamp, walls, grid_x[r0:r1, c0:c1], grid_z[r0:r1, c0:c1], ground[r0:r1, c0:c1],
                                     lit_here & inside[r0:r1, c0:c1]), 0.0, add)
        if np.where(inside[r0:r1, c0:c1], add, 0.0).max() >= LIGHTING_LUX:
            reaching += 1
        lux[r0:r1, c0:c1] += add
    values = lux[inside]
    totals = {"minimum": round(float(values.min()), 1), "mean": round(float(values.mean()), 1),
              "maximum": round(float(values.max()), 1)}
    level = float(dark_below) if dark_below is not None else DARK_SHARE * float(values.mean())
    spots = _dark_spots(lux, inside, level, x0, z0, lit, walls, ground) if values.max() > 0 else []
    return {"grid": {"originX": x0, "originZ": z0, "cellMeters": CELL, "cols": cols, "rows": rows,
                     "inside": inside, "lux": lux},
            "cells": int(inside.sum()), "lampsReaching": reaching, "totals": totals,
            "darkLevel": round(level, 1), "darkSpots": spots}


def _cell_means(add, aim, peak, power, dx, dz, drop, height):
    """ADD (a lamp's light at the cell centres, DX, DZ and DROP from the lamp to each) with the cells near a lamp
    HEIGHT up replaced by the mean over n x n points across each, n = 2 cells over the height (4 to 16): the light under
    a low lamp changes a lot across one cell. A cell keeps its centre's walls (the caller's shadow test)."""
    reach = max(2.0, SMOOTH_REACH * height) + CELL
    near = dx * dx + dz * dz <= reach * reach
    if not near.any():
        return add
    rows, cols = np.nonzero(near)
    r0, r1, c0, c1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    sdx, sdz, sdrop = dx[r0:r1, c0:c1], dz[r0:r1, c0:c1], drop[r0:r1, c0:c1]
    count = min(16, max(4, math.ceil(2 * CELL / height)))
    steps = ((np.arange(count) + 0.5) / count - 0.5) * CELL
    total = np.zeros_like(sdx)
    for ox in steps:
        for oz in steps:
            px, pz = sdx + ox, sdz + oz
            distance = np.sqrt(px * px + pz * pz + sdrop * sdrop)
            safe = np.where(distance > 1e-9, distance, 1.0)
            facing = (px * aim[0] - sdrop * aim[1] + pz * aim[2]) / safe
            total += np.where((sdrop > 0) & (facing > 0),
                              peak * np.clip(facing, 0.0, 1.0) ** power * sdrop / safe ** 3, 0.0)
    result = add.copy()
    result[r0:r1, c0:c1] = np.where(near[r0:r1, c0:c1], total / count ** 2, add[r0:r1, c0:c1])
    return result


def _dark_spots(lux, inside, level, x0, z0, lamps, walls=None, ground=None):
    """Connected cells (sides touching) below LEVEL, largest first. A spot's centre is its cell deepest inside it
    (farthest from light or the area's edge), so a ring of dark around a lamp's pool has its centre in the dark. Its
    nearest lamps are the nearest that none of WALLS hides from its centre (GROUND: the grid's ground heights)."""
    from scipy import ndimage
    dark = inside & (lux < level)
    labels, count = ndimage.label(dark)
    if not count:
        return []
    depth = ndimage.distance_transform_edt(np.pad(dark, 1))[1:-1, 1:-1]
    ids = np.arange(1, count + 1)
    sizes = ndimage.sum(np.ones_like(lux), labels, ids)
    boxes = ndimage.find_objects(labels)
    spots = []
    for spot_id in ids[np.argsort(-sizes, kind="stable")]:
        window = boxes[spot_id - 1]
        local_rows, local_cols = np.nonzero(labels[window] == spot_id)
        rows, cols = local_rows + window[0].start, local_cols + window[1].start
        depths = depth[rows, cols]
        middle = np.hypot(rows - rows.mean(), cols - cols.mean())
        deepest = int(np.argmin(np.where(depths >= depths.max() - 0.5, middle, np.inf)))   # among equals, the middle
        x = x0 + CELL * (cols[deepest] + 0.5)
        z = z0 + CELL * (rows[deepest] + 0.5)
        near = sorted(lamps, key=lambda lamp: math.hypot(lamp["x"] - x, lamp["z"] - z))
        nearest, seen = [], set()
        below = float(ground[rows[deepest], cols[deepest]]) if ground is not None else 0.0
        start, batch = 0, 8                     # nearest first, in growing batches: usually the first one does
        while start < len(near) and len(nearest) < NEAREST_LAMPS:
            some = near[start:start + batch]
            for lamp, hidden in zip(some, _hidden_from(some, walls, x, z, below)):
                if hidden or lamp["placementId"] in seen:
                    continue
                seen.add(lamp["placementId"])
                nearest.append({"placementId": lamp["placementId"], "label": lamp["label"],
                                "distanceMeters": round(math.hypot(lamp["x"] - x, lamp["z"] - z), 1)})
                if len(nearest) == NEAREST_LAMPS:
                    break
            start, batch = start + batch, batch * 4
        values = lux[rows, cols]
        spots.append({"centre": {"x": round(float(x), 1), "z": round(float(z), 1)}, "sizeSquareMeters": round(len(rows) * CELL * CELL, 1),
                      "extentMeters": {"x": round(CELL * (cols.max() - cols.min() + 1), 1),
                                       "z": round(CELL * (rows.max() - rows.min() + 1), 1)},
                      "minimumLux": round(float(values.min()), 1), "meanLux": round(float(values.mean()), 1),
                      "nearestLamps": nearest, "cells": (rows, cols)})
    return spots


def view_payload(summary, result):
    """What the view draws (CC3): the summary; the grid's lux as base64 little-endian uint16 in tenths of a lux
    (65535 = outside the area), row by row from the south-west cell; and each listed dark spot, numbered, with its
    outline (rings of x, z pairs along the cell edges)."""
    import base64
    grid = result["grid"]
    tenths = np.clip(np.rint(grid["lux"] * 10), 0, OUTSIDE_VALUE - 1).astype("<u2")
    tenths[~grid["inside"]] = OUTSIDE_VALUE
    spots = [dict(listed, number=number, outline=_outline(spot["cells"], grid["originX"], grid["originZ"]))
             for number, (spot, listed) in enumerate(zip(result["darkSpots"], summary["darkSpots"]["listed"]), 1)]
    return {"summary": summary,
            "grid": {"originX": grid["originX"], "originZ": grid["originZ"], "cellMeters": grid["cellMeters"],
                     "cols": grid["cols"], "rows": grid["rows"], "encoding": "uint16le-tenths",
                     "values": base64.b64encode(tenths.tobytes()).decode("ascii")},
            "spots": spots}


def _outline(cells, x0, z0):
    """A dark spot's outline: the rings (outer edge and any holes) of the union of its cells, in plan metres."""
    rows, cols = cells
    order = np.lexsort((cols, rows))
    rows, cols = rows[order], cols[order]
    breaks = np.nonzero((np.diff(rows) != 0) | (np.diff(cols) != 1))[0] + 1      # runs of cells along a row
    starts, ends = np.concatenate([[0], breaks]), np.concatenate([breaks, [len(rows)]])
    shape = shapely.simplify(unary_union([box(x0 + CELL * cols[s], z0 + CELL * rows[s], x0 + CELL * (cols[e - 1] + 1),
                                              z0 + CELL * (rows[s] + 1)) for s, e in zip(starts, ends)]), 0)
    rings = []
    for polygon in getattr(shape, "geoms", [shape]):
        for ring in (polygon.exterior, *polygon.interiors):
            rings.append([round(float(value), 2) for point in list(ring.coords)[:-1] for value in point])
    return rings


def check_lighting_coverage(layout, catalog, library, arguments, project_root=None, shell=None):
    """Sage's read (CC4) and the view's numbers (CC3) for one area: the summary, and the estimate with its cells.
    SHELL: the layout's shell as the spatial checks see it (the service's effective_shell), for its walls."""
    project_root = project_root or Path(__file__).resolve().parents[2]
    by_revision = {(record["assetId"], record["assetDefinitionRevision"]): record for record in catalog}
    shape, area = area_of(layout, arguments, by_revision)
    dark_below = arguments.get("darkBelowLux")
    if dark_below is not None and (isinstance(dark_below, bool) or not isinstance(dark_below, (int, float))
                                   or not 0 <= dark_below <= 100000):
        raise ValueError("darkBelowLux must be a number from 0 to 100000.")
    lamps, notes = find_lamps(layout, by_revision, library, project_root)
    walls = blocking_walls(layout, by_revision, shell)
    result = estimate(layout, lamps, shape, dark_below, walls)
    switch_on, shapes, mode, missing = scene_switches(layout)
    scene = (layout.get("extensions") or {}).get("facilityScene") or {}
    spots = result["darkSpots"]
    summary = {
        "label": CAPTION,
        "area": dict(area, sizeSquareMeters=round(shape.area, 1), cells=result["cells"]),
        "scene": {"sceneId": scene.get("sceneId"), "lightsSwitch": "on" if switch_on else "off",
                  "lightAreas": None if shapes is None else {"mode": mode, "areas": len(shapes) + len(missing),
                                                             "missingFloorAreas": missing}},
        "lamps": {"inLayout": len(lamps), "on": sum(lamp["on"] for lamp in lamps),
                  "offBySwitch": sum(lamp["off"] == "switch" for lamp in lamps),
                  "offByArea": sum(lamp["off"] == "area" for lamp in lamps),
                  "lightingThisArea": result["lampsReaching"],
                  "byFinish": dict(Counter(lamp["finish"] for lamp in lamps if lamp["on"]))},
        "estimatedLux": result["totals"],
        "wallLines": len(walls),
        "darkSpots": {"belowLux": result["darkLevel"],
                      "basis": "the level asked for" if dark_below is not None else "half the area's mean",
                      "count": len(spots), "listed": [{k: v for k, v in spot.items() if k != "cells"}
                                                      for spot in spots[:LISTED_SPOTS]]},
        "lampData": {finish: dict(value, basis="typical, for estimates") for finish, value in lamp_data(library).items()
                     if any(lamp["finish"] == finish for lamp in lamps)},
        "limitations": LIMITATIONS,
    }
    if notes["unreadModels"]:
        summary["lamps"]["unreadModels"] = notes["unreadModels"]
    if notes["signalLightParts"]:
        summary["lamps"]["signalLightsNotCounted"] = notes["signalLightParts"]
    if notes["uplightParts"]:
        summary["lamps"]["uplightsNotCounted"] = notes["uplightParts"]
    if result["totals"]["maximum"] <= 0:
        summary["darkSpots"]["note"] = ("No lamp that is on lights this area: it is dark everywhere." if lamps else
                                        "This layout has no general or outdoor lights.")
    return summary, result
