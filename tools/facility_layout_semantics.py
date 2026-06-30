#!/usr/bin/env python3
"""
Build a facility semantic JSON layer from a SolidWorksExtractor assembly JSON.

This turns raw CAD component occurrences into business-level facility concepts:
rack rows, material-handling assets, inferred aisles, and capacity assumptions.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


Point3 = Tuple[float, float, float]


def _component_position(component: Dict[str, Any]) -> Optional[Point3]:
    transform = component.get("transform") or {}
    raw = transform.get("translation")
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    try:
        return float(raw[0]), float(raw[1]), float(raw[2])
    except (TypeError, ValueError):
        return None


def _round_float(value: Optional[float], digits: int = 6) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _round_point(point: Optional[Point3]) -> Optional[Dict[str, float]]:
    if point is None:
        return None
    return {
        "x": _round_float(point[0]),
        "y": _round_float(point[1]),
        "z": _round_float(point[2]),
    }


def _bounds(points: Iterable[Point3]) -> Optional[Dict[str, Dict[str, float]]]:
    pts = list(points)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return {
        "min": {"x": _round_float(min(xs)), "y": _round_float(min(ys)), "z": _round_float(min(zs))},
        "max": {"x": _round_float(max(xs)), "y": _round_float(max(ys)), "z": _round_float(max(zs))},
        "center": {
            "x": _round_float((min(xs) + max(xs)) / 2.0),
            "y": _round_float((min(ys) + max(ys)) / 2.0),
            "z": _round_float((min(zs) + max(zs)) / 2.0),
        },
    }


def _axis_span(points: List[Point3], axis: int) -> float:
    if not points:
        return 0.0
    values = [p[axis] for p in points]
    return max(values) - min(values)


def _axis_stats(points: List[Point3], axis: int) -> Dict[str, Any]:
    values = sorted(p[axis] for p in points)
    if len(values) < 2:
        return {
            "count": len(values),
            "minSpacingMeters": None,
            "averageSpacingMeters": None,
            "maxSpacingMeters": None,
        }

    gaps = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    return {
        "count": len(values),
        "minSpacingMeters": _round_float(min(gaps)),
        "averageSpacingMeters": _round_float(sum(gaps) / len(gaps)),
        "maxSpacingMeters": _round_float(max(gaps)),
    }


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _span_dict(points: List[Point3]) -> Dict[str, Optional[float]]:
    if not points:
        return {"x": None, "y": None, "z": None}
    return {
        "x": _round_float(_axis_span(points, 0)),
        "y": _round_float(_axis_span(points, 1)),
        "z": _round_float(_axis_span(points, 2)),
    }


def _cluster_values(values: List[float], tolerance: float = 0.025) -> List[float]:
    if not values:
        return []

    clusters: List[List[float]] = []
    for value in sorted(values):
        if not clusters or abs(value - clusters[-1][-1]) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)

    return [sum(cluster) / len(cluster) for cluster in clusters]


def _display_name(group: str) -> str:
    text = re.sub(r"^(Rack_Row_|Forklift_)", "", group or "")
    text = text.replace("_", " ").strip()
    return text or group


def _aliases(group: str, kind: str) -> List[str]:
    display = _display_name(group)
    aliases = {
        group,
        display,
        display.lower(),
        group.replace("_", " "),
        group.replace("_", " ").lower(),
    }

    if kind == "rack_row":
        aliases.add("rack " + display.lower())
        aliases.add("row " + display.lower())
        aliases.add("rack row " + display.lower())

        match = re.search(r"Rack_Row_([A-Z])_", group or "")
        if match:
            letter = match.group(1)
            aliases.add(f"row {letter}")
            aliases.add(f"rack row {letter}")

    if kind == "forklift":
        aliases.add("forklift " + display.lower())
        aisle = re.sub(r"^\d+\s+", "", display).strip()
        if aisle:
            aliases.add(aisle)
            aliases.add(aisle.lower())

    return sorted(a for a in aliases if a)


def _is_rack_component(component: Dict[str, Any]) -> bool:
    group = component.get("semanticGroup") or ""
    filename = (component.get("referencedFileName") or "").lower()
    return group.startswith("Rack_Row_") and filename.endswith(".sldasm")


def _is_forklift_component(component: Dict[str, Any]) -> bool:
    group = component.get("semanticGroup") or ""
    filename = (component.get("referencedFileName") or "").lower()
    return group.startswith("Forklift_") and filename.endswith(".sldprt")


def _top_level_components(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in data.get("components", []) if c.get("level") == 1]


def _children_by_parent(components: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    children: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for component in components:
        parent = component.get("parentName")
        if parent:
            children[parent].append(component)
    return children


def _estimate_rack_envelope(
    rack_component: Dict[str, Any],
    child_map: Dict[str, List[Dict[str, Any]]],
    row_primary_axis: str,
) -> Dict[str, Any]:
    children = child_map.get(rack_component.get("name") or "", [])
    child_points = [p for p in (_component_position(child) for child in children) if p]
    crossmembers = [
        child for child in children
        if "crossmember" in (child.get("referencedFileName") or "").lower()
    ]
    crossmember_points = [p for p in (_component_position(child) for child in crossmembers) if p]
    legs = [
        child for child in children
        if "leg" in (child.get("referencedFileName") or "").lower()
    ]

    crossmember_levels = _cluster_values([p[1] for p in crossmember_points])
    shelf_level_count = len(crossmember_levels) if crossmember_levels else None
    spans = _span_dict(child_points)

    along_axis = "x" if row_primary_axis == "x" else "z"
    cross_axis = "z" if row_primary_axis == "x" else "x"

    return {
        "basis": "child component centerline transforms",
        "confidence": "rough",
        "componentCountUsed": len(child_points),
        "legComponentCount": len(legs),
        "crossmemberComponentCount": len(crossmembers),
        "centerlineBoundsMeters": _bounds(child_points),
        "centerlineSpanMeters": spans,
        "estimatedUsableEnvelopeMeters": {
            "basis": "upper-bound estimate from leg/crossmember centerline spans; physical member thickness and clearance are not subtracted",
            "alongRow": spans[along_axis],
            "crossRowDepth": spans[cross_axis],
            "verticalSpan": spans["y"],
        },
        "estimatedShelfLevels": shelf_level_count,
        "crossmemberLevelElevationsMeters": [_round_float(v) for v in crossmember_levels],
        "assumptions": [
            "Crossmember elevation groups are treated as shelf/support levels.",
            "Plywood shelves are inferred from crossmember levels because shelf panels are not modeled.",
            "Usable envelope is a rough centerline estimate until rack member dimensions or manual rack specs are available.",
        ],
    }


def _aggregate_rack_envelopes(envelopes: List[Dict[str, Any]]) -> Dict[str, Any]:
    usable = [e.get("estimatedUsableEnvelopeMeters") or {} for e in envelopes]
    shelf_levels = [
        int(e["estimatedShelfLevels"])
        for e in envelopes
        if isinstance(e.get("estimatedShelfLevels"), int)
    ]

    return {
        "basis": "median of rack instance envelope estimates in this row",
        "confidence": "rough",
        "typicalRackUsableEnvelopeMeters": {
            "alongRow": _round_float(_median([u["alongRow"] for u in usable if isinstance(u.get("alongRow"), (int, float))])),
            "crossRowDepth": _round_float(_median([u["crossRowDepth"] for u in usable if isinstance(u.get("crossRowDepth"), (int, float))])),
            "verticalSpan": _round_float(_median([u["verticalSpan"] for u in usable if isinstance(u.get("verticalSpan"), (int, float))])),
        },
        "estimatedShelfLevelsTypical": _round_float(_median([float(v) for v in shelf_levels])),
        "estimatedShelfLevelsTotal": sum(shelf_levels) if shelf_levels else None,
        "estimatedShelfLevelDistribution": dict(sorted(Counter(shelf_levels).items())),
    }


def _build_rack_rows(top_components: List[Dict[str, Any]], all_components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    child_map = _children_by_parent(all_components)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for component in top_components:
        if _is_rack_component(component):
            grouped[component["semanticGroup"]].append(component)

    rows: List[Dict[str, Any]] = []
    for group, components in sorted(grouped.items()):
        instances = []
        positions: List[Point3] = []
        for component in sorted(components, key=lambda c: c.get("name") or ""):
            position = _component_position(component)
            if position:
                positions.append(position)
            instances.append(
                {
                    "componentName": component.get("name"),
                    "referencedFileName": component.get("referencedFileName"),
                    "activeConfiguration": component.get("activeConfiguration"),
                    "positionMeters": _round_point(position),
                }
            )

        span_x = _axis_span(positions, 0)
        span_z = _axis_span(positions, 2)
        primary_axis = "x" if span_x >= span_z else "z"
        axis_index = 0 if primary_axis == "x" else 2
        orientation = "east-west" if primary_axis == "x" else "north-south"

        rack_envelopes = {
            component.get("name"): _estimate_rack_envelope(component, child_map, primary_axis)
            for component in components
        }
        aggregate_envelope = _aggregate_rack_envelopes(list(rack_envelopes.values()))

        for instance in instances:
            instance["rackEnvelopeEstimate"] = rack_envelopes.get(instance["componentName"])

        row = {
            "id": group,
            "displayName": _display_name(group),
            "kind": "rack_row",
            "aliases": _aliases(group, "rack_row"),
            "rackCount": len(components),
            "rackInstances": instances,
            "orientation": orientation,
            "primaryAxis": primary_axis,
            "centerlineBoundsMeters": _bounds(positions),
            "centerlineSpanMeters": _round_float(max(span_x, span_z)),
            "centerlineRackSpacing": _axis_stats(positions, axis_index),
            "rackEnvelopeEstimate": aggregate_envelope,
            "capacityModel": {
                "status": "rough_envelope_available_needs_box_dimensions",
                "knownInputs": {
                    "rackCount": len(components),
                    "rackCenterPositionsMeters": len(positions),
                    "typicalRackUsableEnvelopeMeters": aggregate_envelope["typicalRackUsableEnvelopeMeters"],
                    "estimatedShelfLevelsTypical": aggregate_envelope["estimatedShelfLevelsTypical"],
                    "estimatedShelfLevelsTotal": aggregate_envelope["estimatedShelfLevelsTotal"],
                    "estimatedShelfLevelDistribution": aggregate_envelope["estimatedShelfLevelDistribution"],
                },
                "inputsNeeded": [
                    "box dimensions",
                    "clearance rules",
                    "confirmation of rack usable envelope",
                ],
                "assumptions": [
                    "Rack row grouping comes from SolidWorks FeatureManager folders.",
                    "Rack usable envelope is estimated from child component centerline spans.",
                    "Plywood shelves are not explicitly modeled; shelf levels are inferred from crossmember elevations.",
                    "Any capacity result should be labeled as an estimate until rack specs or physical member bounding boxes are available.",
                ],
                "formula": "sum(floor(usable_along_row / box_along_row) * floor(usable_cross_row_depth / box_depth) * shelf_levels) across racks",
            },
        }
        rows.append(row)

    return rows


def _distance_to_row(point: Point3, row: Dict[str, Any]) -> Optional[float]:
    bounds = row.get("centerlineBoundsMeters") or {}
    center = bounds.get("center") or {}
    if row.get("primaryAxis") == "x":
        z = center.get("z")
        return abs(point[2] - z) if z is not None else None
    x = center.get("x")
    return abs(point[0] - x) if x is not None else None


def _build_forklifts(top_components: List[Dict[str, Any]], rack_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    forklifts = []
    for component in sorted([c for c in top_components if _is_forklift_component(c)], key=lambda c: c.get("semanticGroup") or ""):
        position = _component_position(component)
        nearest_rows = []
        if position:
            distances = []
            for row in rack_rows:
                distance = _distance_to_row(position, row)
                if distance is not None:
                    distances.append((distance, row["id"]))
            for distance, row_id in sorted(distances)[:3]:
                nearest_rows.append({"rowId": row_id, "centerlineDistanceMeters": _round_float(distance)})

        group = component.get("semanticGroup")
        forklifts.append(
            {
                "id": group,
                "displayName": _display_name(group),
                "kind": "forklift",
                "aliases": _aliases(group, "forklift"),
                "componentName": component.get("name"),
                "referencedFileName": component.get("referencedFileName"),
                "positionMeters": _round_point(position),
                "nearestRackRows": nearest_rows,
            }
        )

    return forklifts


def _row_center(row: Dict[str, Any]) -> Optional[Point3]:
    center = ((row.get("centerlineBoundsMeters") or {}).get("center") or {})
    if not {"x", "y", "z"}.issubset(center):
        return None
    return float(center["x"]), float(center["y"]), float(center["z"])


def _build_aisles(rack_rows: List[Dict[str, Any]], forklifts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    aisles = []
    parallel_rows = [row for row in rack_rows if row.get("orientation") == "east-west"]
    parallel_rows.sort(key=lambda row: (_row_center(row) or (0, 0, 0))[2])

    forklift_positions = []
    for forklift in forklifts:
        pos = forklift.get("positionMeters")
        if pos:
            forklift_positions.append((forklift["id"], (pos["x"], pos["y"], pos["z"])))

    for index in range(len(parallel_rows) - 1):
        row_a = parallel_rows[index]
        row_b = parallel_rows[index + 1]
        center_a = _row_center(row_a)
        center_b = _row_center(row_b)
        if not center_a or not center_b:
            continue

        z_min = min(center_a[2], center_b[2])
        z_max = max(center_a[2], center_b[2])
        forklifts_in_band = [
            forklift_id
            for forklift_id, pos in forklift_positions
            if z_min <= pos[2] <= z_max
        ]

        aisles.append(
            {
                "id": f"Aisle_Between_{row_a['id']}_and_{row_b['id']}",
                "kind": "inferred_row_to_row_aisle",
                "betweenRows": [row_a["id"], row_b["id"]],
                "centerlineSpacingMeters": _round_float(abs(center_b[2] - center_a[2])),
                "approxCenterlineMeters": {
                    "x": _round_float((center_a[0] + center_b[0]) / 2.0),
                    "y": _round_float((center_a[1] + center_b[1]) / 2.0),
                    "z": _round_float((center_a[2] + center_b[2]) / 2.0),
                },
                "forkliftsCurrentlyInBand": forklifts_in_band,
                "assumptions": [
                    "Aisle is inferred between adjacent parallel rack-row centerlines.",
                    "Spacing is centerline-to-centerline, not clear driveable aisle width.",
                ],
            }
        )

    return aisles


def _build_semantic_index(rack_rows: List[Dict[str, Any]], forklifts: List[Dict[str, Any]]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for item in [*rack_rows, *forklifts]:
        for alias in item.get("aliases", []):
            key = alias.lower()
            if key not in index:
                index[key] = item["id"]
    return index


def build_facility_semantics(data: Dict[str, Any], source_path: Path) -> Dict[str, Any]:
    top_components = _top_level_components(data)
    rack_rows = _build_rack_rows(top_components, data.get("components", []))
    forklifts = _build_forklifts(top_components, rack_rows)
    aisles = _build_aisles(rack_rows, forklifts)

    component_groups = Counter(c.get("semanticGroup") for c in data.get("components", []) if c.get("semanticGroup"))
    top_component_groups = Counter(c.get("semanticGroup") for c in top_components if c.get("semanticGroup"))

    return {
        "schemaVersion": "facility-layout-semantic-v0.1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "extractorJson": str(source_path),
            "solidWorksFileName": data.get("fileName"),
            "solidWorksFilePath": data.get("filePath"),
            "extractionTime": data.get("extractionTime"),
            "units": "meters",
        },
        "facility": {
            "id": Path(data.get("fileName") or "facility_layout").stem,
            "displayName": Path(data.get("fileName") or "facility_layout").stem,
            "statistics": data.get("statistics") or {},
            "topLevelComponentCount": len(top_components),
            "semanticTopLevelGroupCounts": dict(sorted(top_component_groups.items())),
            "semanticComponentGroupCounts": dict(sorted(component_groups.items())),
        },
        "rackRows": rack_rows,
        "materialHandlingAssets": forklifts,
        "aisles": aisles,
        "semanticIndex": _build_semantic_index(rack_rows, forklifts),
        "globalAssumptions": [
            "Coordinates are taken from SolidWorks assembly component transforms and are expressed in meters.",
            "Rack rows and forklift identities come from FeatureManager folder names exported by the standalone extractor.",
            "Capacity answers should not be treated as final until rack usable envelopes and shelf-level assumptions are supplied or extracted.",
        ],
        "nextDataNeeded": [
            "rack usable bay envelope",
            "rack shelf level count",
            "clearance rules around boxes and aisles",
            "optional floor/zone boundaries from the warehouse layout component",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build facility semantic JSON from SolidWorksExtractor assembly JSON.")
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to SolidWorksExtractor assembly JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output semantic JSON path. Defaults to facility_layout_semantic.json next to the input.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path: Path = args.input
    output_path: Path = args.output or input_path.with_name("facility_layout_semantic.json")

    with input_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    semantic = build_facility_semantics(data, input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(semantic, handle, indent=2)
        handle.write("\n")

    print(f"Wrote {output_path}")
    print(f"Rack rows: {len(semantic['rackRows'])}")
    print(f"Forklifts: {len(semantic['materialHandlingAssets'])}")
    print(f"Inferred aisles: {len(semantic['aisles'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
