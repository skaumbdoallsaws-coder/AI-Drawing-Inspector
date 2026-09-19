"""Reviewed reference-only Finished Goods vehicle-cycle derivation.

The user owns the semantic sequence and selected rack aisle. Exact transient
waypoints are derived from stable layout and catalog identities; they are never
written into the saved Facility Layout document.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .spatial import placement_spatial_records


REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET = (
    "reference_finished_goods_putaway"
)
REFERENCE_FINISHED_GOODS_DISPATCH_PRESET = (
    "reference_finished_goods_dispatch"
)
REFERENCE_FINISHED_GOODS_PRESETS = {
    REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
    REFERENCE_FINISHED_GOODS_DISPATCH_PRESET,
}
REFERENCE_FINISHED_GOODS_ZONE_LABEL = "Finished Goods"
REFERENCE_FINISHED_GOODS_ROW_THREE_LABEL = "Finished Goods Rack Row R03"
REFERENCE_FINISHED_GOODS_ROW_FOUR_LABEL = "Finished Goods Rack Row R04"
REFERENCE_FINISHED_GOODS_TARGET_BAY_FROM_NORTH = 10
REFERENCE_FINISHED_GOODS_SCHEMA_VERSION = (
    "facility-reference-finished-goods-cycle-v1"
)


def _bounds(points: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    if len(points) < 3:
        raise ValueError("Finished Goods geometry requires a polygon boundary.")
    return (
        min(float(point["x"]) for point in points),
        min(float(point["z"]) for point in points),
        max(float(point["x"]) for point in points),
        max(float(point["z"]) for point in points),
    )


def _contains(position: Mapping[str, Any], boundary: Sequence[Mapping[str, Any]]) -> bool:
    minimum_x, minimum_z, maximum_x, maximum_z = _bounds(boundary)
    return (
        minimum_x - 1.0e-9 <= float(position["x"]) <= maximum_x + 1.0e-9
        and minimum_z - 1.0e-9 <= float(position["z"]) <= maximum_z + 1.0e-9
    )


def _placement_bounds(
    placement: Mapping[str, Any],
    asset_definitions: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[float, float, float, float]:
    key = (
        str(placement.get("assetId") or ""),
        str(placement.get("assetDefinitionRevision") or ""),
    )
    definition = asset_definitions.get(key)
    if not isinstance(definition, Mapping):
        raise ValueError(
            "Finished Goods cycle requires every referenced exact catalog revision."
        )
    points = [
        point
        for record in placement_spatial_records(placement, definition)
        for point in record.polygon
    ]
    if not points:
        raise ValueError("Finished Goods cycle placement geometry is unavailable.")
    return (
        min(float(point[0]) for point in points),
        min(float(point[1]) for point in points),
        max(float(point[0]) for point in points),
        max(float(point[1]) for point in points),
    )


def _point(x: float, z: float) -> dict[str, float]:
    return {"x": round(float(x), 6), "z": round(float(z), 6)}


def _segment(
    segment_id: str,
    phase: str,
    start: Mapping[str, float],
    goal: Mapping[str, float],
    start_heading: float,
    goal_heading: float,
    *,
    display_offset_meters: float,
) -> dict[str, Any]:
    return {
        "segmentId": segment_id,
        "phase": phase,
        "start": dict(start),
        "goal": dict(goal),
        "startHeading": round(float(start_heading), 9),
        "goalHeading": round(float(goal_heading), 9),
        "displayOffsetMeters": float(display_offset_meters),
    }


def _stable_route_id(seed: Mapping[str, Any]) -> str:
    payload = json.dumps(
        seed,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return f"rt-fg-{hashlib.sha256(payload).hexdigest()[:24]}"


def derive_reference_finished_goods_cycle(
    layout: Mapping[str, Any],
    asset_definitions: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    preset: str,
    planner_vehicle_length_meters: float,
) -> dict[str, Any]:
    """Derive the reviewed put-away or reverse-dispatch cycle.

    The tenth R04 rack bay is the example destination reviewed in the supplied
    concept. Loaded and empty paths share one physical aisle; the tiny offsets
    are renderer-only and never enter the planner geometry.
    """

    if preset not in REFERENCE_FINISHED_GOODS_PRESETS:
        raise ValueError("Finished Goods activity preset is unsupported.")
    length = float(planner_vehicle_length_meters)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Finished Goods activity requires a positive vehicle length.")

    zones = {
        str(zone.get("label") or ""): zone
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping)
    }
    required_labels = (
        REFERENCE_FINISHED_GOODS_ZONE_LABEL,
        REFERENCE_FINISHED_GOODS_ROW_THREE_LABEL,
        REFERENCE_FINISHED_GOODS_ROW_FOUR_LABEL,
    )
    if any(label not in zones for label in required_labels):
        raise ValueError("The reviewed Finished Goods rack-row geometry is unavailable.")
    finished = zones[REFERENCE_FINISHED_GOODS_ZONE_LABEL]
    row_three = zones[REFERENCE_FINISHED_GOODS_ROW_THREE_LABEL]
    row_four = zones[REFERENCE_FINISHED_GOODS_ROW_FOUR_LABEL]
    finished_boundary = list(finished.get("boundary") or [])
    placements = [
        placement
        for placement in layout.get("placements", [])
        if isinstance(placement, Mapping)
        and isinstance((placement.get("transform") or {}).get("position"), Mapping)
        and _contains(placement["transform"]["position"], finished_boundary)
    ]

    def exact_asset(asset_id: str) -> list[Mapping[str, Any]]:
        return sorted(
            (
                placement
                for placement in placements
                if str(placement.get("assetId") or "") == asset_id
            ),
            key=lambda item: str(item.get("placementId") or ""),
        )

    forklifts = exact_asset("asset-forklift")
    pallet_trucks = exact_asset("asset-pallet-truck-simple")
    pallets = exact_asset("asset-pallet-1200x1000")
    if len(forklifts) != 1 or len(pallet_trucks) != 1 or len(pallets) != 10:
        raise ValueError(
            "The frozen Finished Goods actor or staging inventory changed."
        )
    vehicle = forklifts[0]
    parked = pallet_trucks[0]
    staged = max(
        pallets,
        key=lambda item: (
            float(item["transform"]["position"]["z"]),
            float(item["transform"]["position"]["x"]),
            str(item["placementId"]),
        ),
    )
    row_four_racks = sorted(
        (
            placement
            for placement in placements
            if str(placement.get("assetId") or "") == "asset-pallet-rack"
            and _contains(
                placement["transform"]["position"],
                list(row_four.get("boundary") or []),
            )
        ),
        key=lambda item: (
            float(item["transform"]["position"]["z"]),
            str(item["placementId"]),
        ),
    )
    if len(row_four_racks) != 12:
        raise ValueError("The frozen R04 rack-bay inventory changed.")
    target_rack = row_four_racks[
        REFERENCE_FINISHED_GOODS_TARGET_BAY_FROM_NORTH - 1
    ]

    row_three_bounds = _bounds(list(row_three.get("boundary") or []))
    row_four_bounds = _bounds(list(row_four.get("boundary") or []))
    finished_bounds = _bounds(finished_boundary)
    staged_bounds = _placement_bounds(staged, asset_definitions)
    pallet_bounds = [
        _placement_bounds(pallet, asset_definitions) for pallet in pallets
    ]
    aisle_x = (row_three_bounds[2] + row_four_bounds[0]) / 2.0
    staging_south = max(item[3] for item in pallet_bounds)
    cross_z = (staging_south + row_four_bounds[1]) / 2.0
    vehicle_position = vehicle["transform"]["position"]
    target_position = target_rack["transform"]["position"]
    home = _point(vehicle_position["x"], vehicle_position["z"])
    pickup = _point(staged_bounds[2] + length / 2.0, (
        staged_bounds[1] + staged_bounds[3]
    ) / 2.0)
    entrance = _point(aisle_x, cross_z)
    shelf_pre_align = _point(aisle_x, target_position["z"])
    shelf = _point(
        row_four_bounds[0] - length / 2.0,
        target_position["z"],
    )
    cross_min_z = min(home["z"], pickup["z"]) - length
    cross_boundary = [
        _point(row_three_bounds[2], cross_min_z),
        _point(finished_bounds[2], cross_min_z),
        _point(finished_bounds[2], row_four_bounds[1]),
        _point(row_three_bounds[2], row_four_bounds[1]),
    ]
    aisle_boundary = [
        _point(row_three_bounds[2], cross_min_z),
        _point(row_four_bounds[0], cross_min_z),
        _point(row_four_bounds[0], row_four_bounds[3]),
        _point(row_three_bounds[2], row_four_bounds[3]),
    ]

    north = -math.pi / 2.0
    south = math.pi / 2.0
    east = 0.0
    west = math.pi
    if preset == REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET:
        segments = [
            _segment("pick-staged-pallet", "finished_goods_pick", home, pickup, west, west, display_offset_meters=0.0),
            _segment("loaded-cross-aisle", "loaded_putaway", pickup, entrance, west, south, display_offset_meters=0.12),
            _segment("loaded-rack-aisle", "loaded_putaway", entrance, shelf_pre_align, south, south, display_offset_meters=0.12),
            _segment("loaded-shelf-align", "loaded_putaway", shelf_pre_align, shelf, south, east, display_offset_meters=0.12),
            _segment("empty-shelf-withdraw", "return_empty", shelf, shelf_pre_align, west, north, display_offset_meters=-0.12),
            _segment("empty-rack-aisle", "return_empty", shelf_pre_align, entrance, north, north, display_offset_meters=-0.12),
            _segment("empty-cross-aisle", "return_empty", entrance, home, north, west, display_offset_meters=-0.12),
        ]
        reviewed_actions = [
            {"stop": "1", "placementId": staged["placementId"], "actions": ["pick"]},
            {"stop": "2", "zoneIds": [row_three["zoneId"], row_four["zoneId"]], "actions": ["travel_loaded"]},
            {"stop": "3", "placementId": target_rack["placementId"], "actions": ["align", "place"]},
            {"stop": "4", "placementId": vehicle["placementId"], "actions": ["withdraw", "return_empty"]},
        ]
        cycle_kind = "finished_goods_putaway"
    else:
        segments = [
            _segment("empty-cross-to-rack", "empty_to_rack", home, entrance, west, south, display_offset_meters=-0.12),
            _segment("empty-rack-aisle", "empty_to_rack", entrance, shelf_pre_align, south, south, display_offset_meters=-0.12),
            _segment("empty-shelf-align", "empty_to_rack", shelf_pre_align, shelf, south, east, display_offset_meters=-0.12),
            _segment("loaded-shelf-withdraw", "loaded_dispatch", shelf, shelf_pre_align, west, north, display_offset_meters=0.12),
            _segment("loaded-rack-aisle", "loaded_dispatch", shelf_pre_align, entrance, north, north, display_offset_meters=0.12),
            _segment("loaded-cross-to-staging", "loaded_dispatch", entrance, home, north, west, display_offset_meters=0.12),
        ]
        reviewed_actions = [
            {"stop": "1", "placementId": target_rack["placementId"], "actions": ["align", "retrieve"]},
            {"stop": "2", "placementId": staged["placementId"], "actions": ["deliver_to_staging"]},
            {"stop": "3", "placementId": target_rack["placementId"], "actions": ["return_empty"]},
        ]
        cycle_kind = "finished_goods_dispatch"

    route_seed = {
        "schemaVersion": REFERENCE_FINISHED_GOODS_SCHEMA_VERSION,
        "preset": preset,
        "vehiclePlacementId": vehicle["placementId"],
        "stagedPalletPlacementId": staged["placementId"],
        "targetRackPlacementId": target_rack["placementId"],
        "rowZoneIds": [row_three["zoneId"], row_four["zoneId"]],
    }
    return {
        "schemaVersion": REFERENCE_FINISHED_GOODS_SCHEMA_VERSION,
        "preset": preset,
        "cycleKind": cycle_kind,
        "routeId": _stable_route_id(route_seed),
        "zoneId": str(finished["zoneId"]),
        "rowZoneIds": [str(row_three["zoneId"]), str(row_four["zoneId"])],
        "vehiclePlacementId": str(vehicle["placementId"]),
        "parkedVehiclePlacementIds": [str(parked["placementId"])],
        "stagedPalletPlacementId": str(staged["placementId"]),
        "targetRackPlacementId": str(target_rack["placementId"]),
        "targetRackBayFromNorth": REFERENCE_FINISHED_GOODS_TARGET_BAY_FROM_NORTH,
        "scopePlacementIds": sorted(str(item["placementId"]) for item in placements),
        "excludedObstaclePlacementIds": sorted([
            str(vehicle["placementId"]),
            str(staged["placementId"]),
        ]),
        "points": {
            "home": home,
            "pickup": pickup,
            "aisleEntrance": entrance,
            "shelfPreAlign": shelf_pre_align,
            "shelfService": shelf,
        },
        "traversablePolygons": [cross_boundary, aisle_boundary],
        "segments": segments,
        "reviewedStopActions": reviewed_actions,
        "geometryAuthority": (
            "derived_from_exact_reference_zone_placement_and_catalog_geometry"
        ),
        "loadValidationStatus": "not_evaluated",
        "productionEligible": False,
    }


__all__ = [
    "REFERENCE_FINISHED_GOODS_DISPATCH_PRESET",
    "REFERENCE_FINISHED_GOODS_PRESETS",
    "REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET",
    "REFERENCE_FINISHED_GOODS_SCHEMA_VERSION",
    "REFERENCE_FINISHED_GOODS_ZONE_LABEL",
    "derive_reference_finished_goods_cycle",
]
