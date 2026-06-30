#!/usr/bin/env python3
"""
Estimate storage capacity from facility_layout_semantic.json.

The calculation intentionally stays transparent: it uses the rough rack envelope
and shelf-level estimates produced by facility_layout_semantics.py and reports
the assumptions with the result.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


UNIT_TO_METERS = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "mm": 0.001,
    "millimeter": 0.001,
    "millimeters": 0.001,
    "cm": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
}


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _normalize(text: str) -> str:
    return (text or "").strip().lower().replace("_", " ")


def _convert_to_meters(value: float, unit: str) -> float:
    key = unit.strip().lower()
    if key not in UNIT_TO_METERS:
        raise ValueError(f"Unsupported unit '{unit}'. Supported: {', '.join(sorted(UNIT_TO_METERS))}")
    return value * UNIT_TO_METERS[key]


def _box_dimensions(args: argparse.Namespace) -> Dict[str, Any]:
    unit = args.unit.strip().lower()
    length_m = _convert_to_meters(args.length, unit)
    depth_m = _convert_to_meters(args.depth, unit)
    height_m = _convert_to_meters(args.height, unit) if args.height is not None else None
    clearance_m = _convert_to_meters(args.clearance, unit)

    return {
        "input": {
            "lengthAlongRow": args.length,
            "depthCrossRow": args.depth,
            "height": args.height,
            "clearance": args.clearance,
            "unit": unit,
        },
        "meters": {
            "lengthAlongRow": length_m,
            "depthCrossRow": depth_m,
            "height": height_m,
            "clearance": clearance_m,
        },
    }


def _row_text(row: Dict[str, Any]) -> Iterable[str]:
    yield row.get("id") or ""
    yield row.get("displayName") or ""
    for alias in row.get("aliases", []):
        yield alias


def resolve_rows(semantic: Dict[str, Any], query: Optional[str]) -> Tuple[List[Dict[str, Any]], str]:
    rows = semantic.get("rackRows", [])
    if not query:
        return rows, "all_rows"

    normalized_query = _normalize(query)
    index = {
        _normalize(alias): row_id
        for alias, row_id in (semantic.get("semanticIndex") or {}).items()
    }
    if normalized_query in index:
        row_id = index[normalized_query]
        return [row for row in rows if row.get("id") == row_id], "exact_alias"

    substring_matches = [
        row
        for row in rows
        if any(normalized_query in _normalize(text) for text in _row_text(row))
    ]
    if substring_matches:
        return substring_matches, "substring"

    return [], "not_found"


def _shelf_pitch_meters(envelope: Dict[str, Any]) -> Optional[float]:
    levels = envelope.get("crossmemberLevelElevationsMeters") or []
    if len(levels) < 2:
        return None

    ordered = sorted(float(v) for v in levels)
    gaps = [ordered[i + 1] - ordered[i] for i in range(len(ordered) - 1)]
    return min(gaps) if gaps else None


def _estimate_instance_capacity(instance: Dict[str, Any], box_m: Dict[str, Optional[float]]) -> Dict[str, Any]:
    envelope = (instance.get("rackEnvelopeEstimate") or {})
    usable = envelope.get("estimatedUsableEnvelopeMeters") or {}

    along = usable.get("alongRow")
    depth = usable.get("crossRowDepth")
    shelf_levels = envelope.get("estimatedShelfLevels")
    clearance = box_m["clearance"] or 0.0

    effective_length = (box_m["lengthAlongRow"] or 0.0) + clearance
    effective_depth = (box_m["depthCrossRow"] or 0.0) + clearance

    if not along or not depth or not shelf_levels or effective_length <= 0 or effective_depth <= 0:
        return {
            "componentName": instance.get("componentName"),
            "capacityBoxes": 0,
            "status": "insufficient_envelope_data",
        }

    along_fit = math.floor(float(along) / effective_length)
    depth_fit = math.floor(float(depth) / effective_depth)
    per_shelf = max(0, along_fit) * max(0, depth_fit)
    footprint_capacity = per_shelf * int(shelf_levels)

    shelf_pitch = _shelf_pitch_meters(envelope)
    height_status = "not_checked"
    height_ok = None
    if box_m.get("height") is not None:
        if shelf_pitch is None:
            height_status = "unknown_shelf_pitch"
        else:
            height_ok = (box_m["height"] + clearance) <= shelf_pitch
            height_status = "passes_rough_pitch_check" if height_ok else "fails_rough_pitch_check"

    return {
        "componentName": instance.get("componentName"),
        "usableEnvelopeMeters": {
            "alongRow": _round(float(along)),
            "crossRowDepth": _round(float(depth)),
            "verticalSpan": _round(usable.get("verticalSpan")),
        },
        "estimatedShelfLevels": int(shelf_levels),
        "fitPerShelf": {
            "alongRowCount": along_fit,
            "crossRowDepthCount": depth_fit,
            "boxesPerShelf": per_shelf,
        },
        "capacityBoxes": footprint_capacity,
        "heightCheck": {
            "status": height_status,
            "passes": height_ok,
            "minShelfPitchMeters": _round(shelf_pitch),
        },
    }


def estimate_row_capacity(row: Dict[str, Any], box: Dict[str, Any]) -> Dict[str, Any]:
    instance_results = [
        _estimate_instance_capacity(instance, box["meters"])
        for instance in row.get("rackInstances", [])
    ]
    total = sum(result.get("capacityBoxes", 0) for result in instance_results)
    failed_height = [
        result["componentName"]
        for result in instance_results
        if (result.get("heightCheck") or {}).get("passes") is False
    ]

    return {
        "rowId": row.get("id"),
        "displayName": row.get("displayName"),
        "rackCount": row.get("rackCount"),
        "estimatedTotalBoxes": total,
        "instanceResults": instance_results,
        "heightWarnings": failed_height,
        "calculationBasis": {
            "source": "facility_layout_semantic rackEnvelopeEstimate",
            "method": "floor(usable_along / effective_box_length) * floor(usable_depth / effective_box_depth) * estimated_shelf_levels",
            "effectiveBoxIncludesClearance": True,
            "confidence": "rough",
        },
        "assumptions": [
            "Rack envelope is estimated from CAD child component centerline spans.",
            "Shelf levels are inferred from crossmember elevation groups.",
            "Plywood shelves and member thickness are not explicitly modeled.",
            "Capacity is a planning estimate until rack specs, clearance rules, and physical shelf details are confirmed.",
        ],
    }


def build_capacity_result(semantic: Dict[str, Any], query: Optional[str], box: Dict[str, Any]) -> Dict[str, Any]:
    rows, match_type = resolve_rows(semantic, query)
    row_results = [estimate_row_capacity(row, box) for row in rows]
    return {
        "schemaVersion": "facility-capacity-estimate-v0.1",
        "facilityId": (semantic.get("facility") or {}).get("id"),
        "rowQuery": query,
        "rowMatchType": match_type,
        "box": box,
        "rows": row_results,
        "estimatedTotalBoxes": sum(row.get("estimatedTotalBoxes", 0) for row in row_results),
        "warnings": [] if rows else [f"No rack row matched query '{query}'."],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate box capacity from facility semantic JSON.")
    parser.add_argument("--semantic", type=Path, default=Path("facility_layout_semantic.json"))
    parser.add_argument("--row", default=None, help="Rack row id or alias. Omit to calculate all rows.")
    parser.add_argument("--length", type=float, required=True, help="Box length along the rack row.")
    parser.add_argument("--depth", type=float, required=True, help="Box depth across the rack.")
    parser.add_argument("--height", type=float, default=None, help="Optional box height for rough shelf pitch check.")
    parser.add_argument("--clearance", type=float, default=0.0, help="Clearance added to each box dimension before fitting.")
    parser.add_argument("--unit", default="in", help="Input dimension unit: in, ft, mm, cm, or m.")
    parser.add_argument("--output", type=Path, default=None, help="Optional path for JSON result.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with args.semantic.open("r", encoding="utf-8") as handle:
        semantic = json.load(handle)

    result = build_capacity_result(semantic, args.row, _box_dimensions(args))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
        print(f"Wrote {args.output}")

    print(f"Facility: {result['facilityId']}")
    print(f"Rows matched: {len(result['rows'])} ({result['rowMatchType']})")
    print(f"Estimated total boxes: {result['estimatedTotalBoxes']}")
    for row in result["rows"]:
        print(f"- {row['rowId']}: {row['estimatedTotalBoxes']} boxes across {row['rackCount']} racks")
        if row["heightWarnings"]:
            print(f"  height warnings: {', '.join(row['heightWarnings'])}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
