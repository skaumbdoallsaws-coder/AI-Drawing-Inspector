"""Columns: native parametric structural columns, rectangular or round, standing on the floor.

A column is a record, not a catalog model: where it stands (its center on the plan), how it is turned (rectangles
only), its size, its height and its appearance, and, when it was converted from a floor plan, the drawing entity it
came from. Saved as ``extensions.facilityColumns``::

    {"version": 1, "columns": [
        {"columnId": "col-a1", "label": "Column A1", "shape": "rectangle", "center": {"x": 10.0, "z": 5.0},
         "widthMeters": 0.4, "depthMeters": 0.4, "rotationDegrees": 0.0,
         "heightMeters": 8.0, "baseElevation": 0.0, "appearance": {"color": "#8f969c"},
         "source": {"referenceId": "fp-main", "importId": "fpi-...", "entityId": "2F"},
         "footprint": [{"x": 9.8, "z": 4.8}, ...]},
        {"columnId": "col-b1", "label": "Column B1", "shape": "circle", "center": {"x": 20.0, "z": 5.0},
         "diameterMeters": 0.4, "heightMeters": 8.0, "baseElevation": 0.0,
         "appearance": {"appearanceId": "concrete-smooth"}, "footprint": [...]}]}

The width runs along x and the depth along z before the turn; ``rotationDegrees`` turns the column as a compass
heading turns, as a placement's yawDegrees does (90 lays the width north-south). ``appearance`` is a placement
appearance (appearance_library.normalize_appearance): a color, or a library or custom finish. ``source`` is
optional. ``footprint`` is derived (the outline on the floor: four corners, or CIRCLE_POINTS round a circle) and is
checked against the rest on every save, as interior walls' panels are.

A column is an obstacle on the floor: the shell gets a "structural_column" feature for it
(append_column_features), so collision, clearance and aisle checks see it as they see walls. Undo restores a saved
revision, so columns are undone with everything else. Catalog models may later stand in for its look; its geometry
stays these numbers.
"""
from collections.abc import Mapping
import math
import re

from .perimeter_walls import _number

KEY = "facilityColumns"
PREFIX = "layout-column-"
FEATURE_KIND = "structural_column"
MAX_COLUMNS = 1000
CIRCLE_POINTS = 32
COLUMN_ID = re.compile(r"col-[a-z0-9-]{1,76}")
REFERENCE_ID = re.compile(r"fp-[a-z0-9-]{1,60}")
IMPORT_ID = re.compile(r"fpi-[a-f0-9]{32}")
SHAPES = {"rectangle": frozenset({"widthMeters", "depthMeters", "rotationDegrees"}),
          "circle": frozenset({"diameterMeters"})}
COMMON = frozenset({"columnId", "label", "shape", "center", "heightMeters", "baseElevation", "appearance"})
SOURCE_FIELDS = frozenset({"referenceId", "importId", "entityId"})
MAX_ENTITY_ID = 400
DEFAULT_COLOR = "#8f969c"
MIN_SIZE, MAX_SIZE = 0.05, 5.0
MIN_HEIGHT, MAX_HEIGHT = 0.5, 60.0


def footprint(column: Mapping) -> list[tuple[float, float]]:
    """The column's outline on the floor, anticlockwise with +z up (north): four corners, or a circle's points."""
    cx, cz = column["center"]["x"], column["center"]["z"]
    if column["shape"] == "circle":
        radius = column["diameterMeters"] / 2
        return [(cx + radius * math.cos(2 * math.pi * k / CIRCLE_POINTS),
                 cz + radius * math.sin(2 * math.pi * k / CIRCLE_POINTS)) for k in range(CIRCLE_POINTS)]
    turn = math.radians(column["rotationDegrees"])
    c, s = math.cos(turn), math.sin(turn)
    half_w, half_d = column["widthMeters"] / 2, column["depthMeters"] / 2
    # A compass turn: x goes to (cos, -sin) and z to (sin, cos).
    return [(cx + x * c + z * s, cz - x * s + z * c)
            for x, z in ((-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d))]


def _source(value) -> dict:
    if not isinstance(value, Mapping) or set(value) != SOURCE_FIELDS:
        raise ValueError("A column's source needs referenceId, importId and entityId")
    if not isinstance(value["referenceId"], str) or not REFERENCE_ID.fullmatch(value["referenceId"]):
        raise ValueError("A column's source referenceId must be an underlay ID (fp-...)")
    if not isinstance(value["importId"], str) or not IMPORT_ID.fullmatch(value["importId"]):
        raise ValueError("A column's source importId must be an import ID (fpi-...)")
    entity = value["entityId"]
    if not isinstance(entity, str) or not entity or len(entity) > MAX_ENTITY_ID or not entity.isprintable():
        raise ValueError(f"A column's source entityId must be 1 to {MAX_ENTITY_ID} printable characters")
    return {"referenceId": value["referenceId"], "importId": value["importId"], "entityId": entity}


def compile_columns(value, layout) -> dict:
    """VALUE (version 1 and its columns, without footprints) checked against LAYOUT and given its footprints."""
    from shapely.geometry import Polygon, box
    from .appearance_library import normalize_appearance
    from .ground import normalize_ground, supports_footprint
    from .plan_settings import plan_settings_from_layout
    if not isinstance(value, Mapping) or set(value) != {"version", "columns"} or type(value["version"]) is not int \
            or value["version"] != 1:
        raise ValueError("Columns require version 1 and columns")
    if not isinstance(value["columns"], list) or len(value["columns"]) > MAX_COLUMNS:
        raise ValueError(f"At most {MAX_COLUMNS} columns are supported")
    plan = plan_settings_from_layout(layout)
    if value["columns"] and not plan:
        raise ValueError("Set plan dimensions before adding columns")
    ground = (layout.get("extensions") or {}).get("facilityGround")
    if ground:
        ground = normalize_ground(ground)
    floor = float((layout.get("coordinateFrame") or {}).get("floorElevation", 0))
    result, ids = [], set()
    for column in value["columns"]:
        if not isinstance(column, Mapping) or not isinstance(column.get("shape"), str) or column["shape"] not in SHAPES:
            raise ValueError("A column's shape must be rectangle or circle")
        fields = COMMON | SHAPES[column["shape"]]
        if set(column) - {"source"} != fields:
            raise ValueError(f"A {column['shape']} column has exactly: " + ", ".join(sorted(fields))
                             + " (and may have source)")
        column_id = column["columnId"]
        if not isinstance(column_id, str) or not COLUMN_ID.fullmatch(column_id) or column_id in ids:
            raise ValueError("Columns need unique stable IDs (col-...)")
        ids.add(column_id)
        label = column["label"]
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("A column's name must contain 1 to 120 characters")
        center = column["center"]
        if not isinstance(center, Mapping) or set(center) != {"x", "z"}:
            raise ValueError("A column's center requires x and z")
        row = {"columnId": column_id, "label": label.strip(), "shape": column["shape"],
               "center": {key: _number(center[key], "center." + key, -10000, 10000) for key in ("x", "z")}}
        if column["shape"] == "rectangle":
            row["widthMeters"] = _number(column["widthMeters"], "Column width", MIN_SIZE, MAX_SIZE)
            row["depthMeters"] = _number(column["depthMeters"], "Column depth", MIN_SIZE, MAX_SIZE)
            row["rotationDegrees"] = _number(column["rotationDegrees"], "Column rotation", -360, 360)
        else:
            row["diameterMeters"] = _number(column["diameterMeters"], "Column diameter", MIN_SIZE, MAX_SIZE)
        row["heightMeters"] = _number(column["heightMeters"], "Column height", MIN_HEIGHT, MAX_HEIGHT)
        row["baseElevation"] = _number(column["baseElevation"], "Column elevation", -1000, 1000)
        try:
            row["appearance"] = normalize_appearance(column["appearance"], layout)
        except ValueError as exc:
            raise ValueError(f"Column appearance: {exc}") from None
        if "source" in column:
            row["source"] = _source(column["source"])
        outline = footprint(row)
        shape = Polygon(outline)
        if not box(0, 0, plan["widthMeters"], plan["depthMeters"]).buffer(1e-8).covers(shape):
            raise ValueError(f"Column '{row['label']}' extends outside the facility plan")
        if ground and not supports_footprint(ground, outline, row["baseElevation"]):
            raise ValueError(f"Column '{row['label']}' must stand on a flat ground surface at its base elevation")
        if not ground and abs(row["baseElevation"] - floor) > 1e-6:
            raise ValueError(f"Column '{row['label']}' base must match the floor elevation")
        row["footprint"] = [{"x": round(x, 9), "z": round(z, 9)} for x, z in outline]
        result.append(row)
    return {"version": 1, "columns": result}


def authored(value) -> dict:
    """VALUE without its derived footprints: what the setters take back."""
    rows = value.get("columns") if isinstance(value, Mapping) else None
    return dict(value, columns=[{k: v for k, v in row.items() if k != "footprint"}
                                for row in (rows if isinstance(rows, list) else []) if isinstance(row, Mapping)])


def validate_columns(layout) -> None:
    extensions = layout.get("extensions") or {}
    if not isinstance(extensions, Mapping) or KEY not in extensions:  # no columns; a stored null is refused below
        return
    value = extensions[KEY]
    if not isinstance(value, Mapping) or not isinstance(value.get("columns"), list):
        raise ValueError("Invalid columns")
    if compile_columns(authored(value), layout) != value:
        raise ValueError("Column geometry does not match its settings")


def append_column_features(shell, layout) -> None:
    """The layout's columns as shell obstacles ("structural_column"), so the spatial checks see them."""
    validate_columns(layout)
    features = shell.setdefault("features", [])
    if any(str(f.get("featureId", "")).startswith(PREFIX) for f in features):
        raise ValueError("Shell uses a reserved column identity")
    for column in ((layout.get("extensions") or {}).get(KEY) or {}).get("columns", []):
        features.append({"featureId": PREFIX + column["columnId"], "featureKind": FEATURE_KIND, "evidence": [],
                         "geometry": {"boundary": column["footprint"], "elevation": column["baseElevation"],
                                      "height": column["heightMeters"]}})
