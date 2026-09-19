"""Reviewed reference-only Receiving pallet-to-rack cycle derivation.

The supplied review defines two example journeys in the frozen manual layout:
upper staging to the middle rack block, and lower staging to the lower rack
block. Exact transient waypoints come from stable layout and catalog identities
and never enter the saved Facility Layout document.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .spatial import placement_spatial_records


REFERENCE_RECEIVING_PUTAWAY_PRESET = "reference_receiving_putaway"
REFERENCE_RECEIVING_ZONE_LABEL = "Receiving + Raw Material"
REFERENCE_RECEIVING_SCHEMA_VERSION = (
    "facility-reference-receiving-cycle-v1"
)
REFERENCE_RECEIVING_PLANNER_GRID_METERS = 1.0
# This only prevents corridor-rounding from excluding exact obstacle tangency;
# the rack obstacle remains authoritative and this is not engineering clearance.
_CORRIDOR_NUMERIC_TOLERANCE_METERS = 0.01


def _bounds(points: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float]:
    if len(points) < 3:
        raise ValueError("Receiving geometry requires a polygon boundary.")
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
            "Receiving cycle requires every referenced exact catalog revision."
        )
    points = [
        point
        for record in placement_spatial_records(placement, definition)
        for point in record.polygon
    ]
    if not points:
        raise ValueError("Receiving cycle placement geometry is unavailable.")
    return (
        min(float(point[0]) for point in points),
        min(float(point[1]) for point in points),
        max(float(point[0]) for point in points),
        max(float(point[1]) for point in points),
    )


def _point(x: float, z: float) -> dict[str, float]:
    return {"x": round(float(x), 6), "z": round(float(z), 6)}


def _rectangle(
    minimum_x: float,
    minimum_z: float,
    maximum_x: float,
    maximum_z: float,
) -> list[dict[str, float]]:
    return [
        _point(minimum_x, minimum_z),
        _point(maximum_x, minimum_z),
        _point(maximum_x, maximum_z),
        _point(minimum_x, maximum_z),
    ]


def _heading(start: Mapping[str, float], goal: Mapping[str, float]) -> float:
    delta_x = float(goal["x"]) - float(start["x"])
    delta_z = float(goal["z"]) - float(start["z"])
    if abs(delta_x) >= abs(delta_z):
        return 0.0 if delta_x >= 0 else math.pi
    return math.pi / 2.0 if delta_z >= 0 else -math.pi / 2.0


def _segment(
    segment_id: str,
    phase: str,
    start: Mapping[str, float],
    goal: Mapping[str, float],
    *,
    display_offset_meters: float,
    goal_heading: float | None = None,
    traversable_polygons: Sequence[Sequence[Mapping[str, float]]],
) -> dict[str, Any]:
    travel_heading = _heading(start, goal)
    return {
        "segmentId": segment_id,
        "phase": phase,
        "start": dict(start),
        "goal": dict(goal),
        "startHeading": round(float(travel_heading), 9),
        "goalHeading": round(float(
            travel_heading if goal_heading is None else goal_heading
        ), 9),
        "displayOffsetMeters": float(display_offset_meters),
        "traversablePolygons": [
            [dict(point) for point in polygon]
            for polygon in traversable_polygons
        ],
    }


def _stable_id(prefix: str, seed: Mapping[str, Any]) -> str:
    payload = json.dumps(
        seed,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _coordinate_groups(
    placements: Sequence[Mapping[str, Any]],
    coordinate: str,
) -> list[list[Mapping[str, Any]]]:
    ordered = sorted(
        placements,
        key=lambda item: (
            float(item["transform"]["position"][coordinate]),
            str(item["placementId"]),
        ),
    )
    values = sorted({
        round(float(item["transform"]["position"][coordinate]), 6)
        for item in ordered
    })
    buckets = {
        value: [
            item
            for item in ordered
            if math.isclose(
                float(item["transform"]["position"][coordinate]),
                value,
                abs_tol=1.0e-6,
            )
        ]
        for value in values
    }
    if len(values) < 2:
        return [ordered]
    if len(values) == 2:
        return [buckets[value] for value in values]
    positive_steps = [
        right - left
        for left, right in zip(values, values[1:])
        if right - left > 1.0e-6
    ]
    nominal_step = min(positive_steps)
    split_after = {
        left
        for left, right in zip(values, values[1:])
        if right - left > nominal_step * 1.5
    }
    groups: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for value in values:
        current.extend(buckets[value])
        if value in split_after:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def derive_reference_receiving_cycles(
    layout: Mapping[str, Any],
    asset_definitions: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    preset: str,
    planner_vehicle_length_meters: float,
) -> dict[str, Any]:
    """Derive the two reviewed Receiving put-away cycles."""

    if preset != REFERENCE_RECEIVING_PUTAWAY_PRESET:
        raise ValueError("Receiving activity preset is unsupported.")
    length = float(planner_vehicle_length_meters)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("Receiving activity requires a positive vehicle length.")

    zone = next(
        (
            item
            for item in layout.get("zones", [])
            if isinstance(item, Mapping)
            and item.get("label") == REFERENCE_RECEIVING_ZONE_LABEL
        ),
        None,
    )
    if not isinstance(zone, Mapping):
        raise ValueError("The reviewed Receiving geometry is unavailable.")
    boundary = list(zone.get("boundary") or [])
    placements = [
        placement
        for placement in layout.get("placements", [])
        if isinstance(placement, Mapping)
        and isinstance((placement.get("transform") or {}).get("position"), Mapping)
        and _contains(placement["transform"]["position"], boundary)
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

    forklifts = exact_asset(
        "asset-forklift-2610x2264x986-minimum-height-green"
    )
    pallet_trucks = exact_asset("asset-pallet-truck-simple")
    pallets = exact_asset("asset-pallet-1200x1000")
    racks = exact_asset("asset-pallet-rack")
    if (
        len(forklifts) != 4
        or len(pallet_trucks) != 4
        or len(pallets) != 16
        or len(racks) != 90
    ):
        raise ValueError("The frozen Receiving actor or storage inventory changed.")

    forklift_groups = _coordinate_groups(forklifts, "z")
    pallet_groups = _coordinate_groups(pallets, "z")
    rack_blocks = _coordinate_groups(racks, "z")
    if (
        [len(group) for group in forklift_groups] != [2, 2]
        or [len(group) for group in pallet_groups] != [8, 8]
        or [len(group) for group in rack_blocks] != [30, 30, 30]
    ):
        raise ValueError("The frozen Receiving banks or rack blocks changed.")

    rack_columns = sorted({
        round(float(item["transform"]["position"]["x"]), 6)
        for item in racks
    })
    if len(rack_columns) != 5:
        raise ValueError("The frozen Receiving rack columns changed.")
    target_column_x = rack_columns[2]
    east_neighbor_x = rack_columns[3]

    moving_lower = max(
        forklift_groups[0],
        key=lambda item: (
            float(item["transform"]["position"]["x"]),
            str(item["placementId"]),
        ),
    )
    moving_upper = max(
        forklift_groups[1],
        key=lambda item: (
            float(item["transform"]["position"]["x"]),
            str(item["placementId"]),
        ),
    )
    selected_lower_pallet = max(
        pallet_groups[0],
        key=lambda item: (
            float(item["transform"]["position"]["z"]),
            float(item["transform"]["position"]["x"]),
            str(item["placementId"]),
        ),
    )
    selected_upper_pallet = min(
        pallet_groups[1],
        key=lambda item: (
            float(item["transform"]["position"]["z"]),
            -float(item["transform"]["position"]["x"]),
            str(item["placementId"]),
        ),
    )

    def target_rack(block: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        candidates = [
            item
            for item in block
            if math.isclose(
                float(item["transform"]["position"]["x"]),
                target_column_x,
                abs_tol=1.0e-6,
            )
        ]
        return max(
            candidates,
            key=lambda item: (
                float(item["transform"]["position"]["z"]),
                str(item["placementId"]),
            ),
        )

    lower_target = target_rack(rack_blocks[0])
    upper_target = target_rack(rack_blocks[1])
    rack_bounds = {
        str(item["placementId"]): _placement_bounds(item, asset_definitions)
        for item in racks
    }
    pallet_bounds = {
        str(item["placementId"]): _placement_bounds(item, asset_definitions)
        for item in pallets
    }
    staging_east = max(item[2] for item in pallet_bounds.values())
    rack_west = min(item[0] for item in rack_bounds.values())
    access_x = (staging_east + rack_west) / 2.0
    target_column_east = max(
        rack_bounds[str(item["placementId"])][2]
        for item in racks
        if math.isclose(
            float(item["transform"]["position"]["x"]),
            target_column_x,
            abs_tol=1.0e-6,
        )
    )
    east_neighbor_west = min(
        rack_bounds[str(item["placementId"])][0]
        for item in racks
        if math.isclose(
            float(item["transform"]["position"]["x"]),
            east_neighbor_x,
            abs_tol=1.0e-6,
        )
    )
    rack_aisle_x = (target_column_east + east_neighbor_west) / 2.0

    def block_bounds(block: Sequence[Mapping[str, Any]]) -> tuple[float, float, float, float]:
        values = [rack_bounds[str(item["placementId"])] for item in block]
        return (
            min(item[0] for item in values),
            min(item[1] for item in values),
            max(item[2] for item in values),
            max(item[3] for item in values),
        )

    lower_bounds = block_bounds(rack_blocks[0])
    middle_bounds = block_bounds(rack_blocks[1])
    upper_bounds = block_bounds(rack_blocks[2])
    lower_cross_z = (lower_bounds[3] + middle_bounds[1]) / 2.0
    upper_cross_z = (middle_bounds[3] + upper_bounds[1]) / 2.0
    zone_bounds = _bounds(boundary)
    lower_corridors = {
        "bank": _rectangle(
            zone_bounds[0], zone_bounds[1], rack_west, middle_bounds[1]
        ),
        "access": _rectangle(
            staging_east, zone_bounds[1], rack_west, middle_bounds[1]
        ),
        "cross": _rectangle(
            staging_east,
            lower_bounds[3],
            east_neighbor_west,
            middle_bounds[1],
        ),
        "rackAisle": _rectangle(
            target_column_east - _CORRIDOR_NUMERIC_TOLERANCE_METERS,
            lower_bounds[1],
            east_neighbor_west + _CORRIDOR_NUMERIC_TOLERANCE_METERS,
            middle_bounds[1],
        ),
    }
    upper_corridors = {
        "bank": _rectangle(
            zone_bounds[0], middle_bounds[3], rack_west, zone_bounds[3]
        ),
        "access": _rectangle(
            staging_east, middle_bounds[3], rack_west, zone_bounds[3]
        ),
        "cross": _rectangle(
            staging_east,
            middle_bounds[3],
            east_neighbor_west,
            upper_bounds[1],
        ),
        "rackAisle": _rectangle(
            target_column_east - _CORRIDOR_NUMERIC_TOLERANCE_METERS,
            middle_bounds[1],
            east_neighbor_west + _CORRIDOR_NUMERIC_TOLERANCE_METERS,
            upper_bounds[1],
        ),
    }

    def build_cycle(
        *,
        cycle_key: str,
        cycle_label: str,
        vehicle: Mapping[str, Any],
        staged: Mapping[str, Any],
        target: Mapping[str, Any],
        cross_z: float,
        corridors: Mapping[str, Sequence[Mapping[str, float]]],
    ) -> dict[str, Any]:
        vehicle_position = vehicle["transform"]["position"]
        staged_value = pallet_bounds[str(staged["placementId"])]
        target_value = rack_bounds[str(target["placementId"])]
        target_position = target["transform"]["position"]
        home = _point(vehicle_position["x"], vehicle_position["z"])
        pickup = _point(
            staged_value[2] + length / 2.0,
            (staged_value[1] + staged_value[3]) / 2.0,
        )
        access_pickup = _point(access_x, pickup["z"])
        cross_entry = _point(access_x, cross_z)
        aisle_entry = _point(rack_aisle_x, cross_z)
        shelf_pre_align = _point(rack_aisle_x, target_position["z"])
        shelf = _point(
            math.ceil(
                (target_value[2] + length / 2.0)
                / REFERENCE_RECEIVING_PLANNER_GRID_METERS
            ) * REFERENCE_RECEIVING_PLANNER_GRID_METERS,
            target_position["z"],
        )
        west = math.pi
        segments = [
            _segment(
                "approach-inbound-pallet",
                "receiving_pick",
                home,
                pickup,
                display_offset_meters=0.0,
                goal_heading=west,
                traversable_polygons=[corridors["bank"]],
            ),
            _segment(
                "loaded-enter-access-aisle",
                "loaded_putaway",
                pickup,
                access_pickup,
                display_offset_meters=0.12,
                traversable_polygons=[
                    corridors["bank"], corridors["access"]
                ],
            ),
            _segment(
                "loaded-access-aisle",
                "loaded_putaway",
                access_pickup,
                cross_entry,
                display_offset_meters=0.12,
                traversable_polygons=[
                    corridors["access"], corridors["cross"]
                ],
            ),
            _segment(
                "loaded-cross-aisle",
                "loaded_putaway",
                cross_entry,
                aisle_entry,
                display_offset_meters=0.12,
                traversable_polygons=[
                    corridors["access"],
                    corridors["cross"],
                    corridors["rackAisle"],
                ],
            ),
            _segment(
                "loaded-rack-aisle",
                "loaded_putaway",
                aisle_entry,
                shelf_pre_align,
                display_offset_meters=0.12,
                traversable_polygons=[
                    corridors["cross"], corridors["rackAisle"]
                ],
            ),
            _segment(
                "loaded-shelf-align",
                "loaded_putaway",
                shelf_pre_align,
                shelf,
                display_offset_meters=0.12,
                goal_heading=west,
                traversable_polygons=[corridors["rackAisle"]],
            ),
            _segment(
                "empty-shelf-withdraw",
                "return_empty",
                shelf,
                shelf_pre_align,
                display_offset_meters=-0.12,
                traversable_polygons=[corridors["rackAisle"]],
            ),
            _segment(
                "empty-rack-aisle",
                "return_empty",
                shelf_pre_align,
                aisle_entry,
                display_offset_meters=-0.12,
                traversable_polygons=[
                    corridors["cross"], corridors["rackAisle"]
                ],
            ),
            _segment(
                "empty-cross-aisle",
                "return_empty",
                aisle_entry,
                cross_entry,
                display_offset_meters=-0.12,
                traversable_polygons=[
                    corridors["access"],
                    corridors["cross"],
                    corridors["rackAisle"],
                ],
            ),
            _segment(
                "empty-access-aisle",
                "return_empty",
                cross_entry,
                access_pickup,
                display_offset_meters=-0.12,
                traversable_polygons=[
                    corridors["access"], corridors["cross"]
                ],
            ),
            _segment(
                "empty-return-to-staging",
                "return_empty",
                access_pickup,
                pickup,
                display_offset_meters=-0.12,
                traversable_polygons=[
                    corridors["bank"], corridors["access"]
                ],
            ),
            _segment(
                "empty-return-home",
                "return_empty",
                pickup,
                home,
                display_offset_meters=-0.12,
                traversable_polygons=[corridors["bank"]],
            ),
        ]
        seed = {
            "schemaVersion": REFERENCE_RECEIVING_SCHEMA_VERSION,
            "preset": preset,
            "cycleKey": cycle_key,
            "vehiclePlacementId": vehicle["placementId"],
            "stagedPalletPlacementId": staged["placementId"],
            "targetRackPlacementId": target["placementId"],
        }
        return {
            "cycleKey": cycle_key,
            "cycleLabel": cycle_label,
            "routeId": _stable_id("rt-rcv", seed),
            "vehiclePlacementId": str(vehicle["placementId"]),
            "stagedPalletPlacementId": str(staged["placementId"]),
            "targetRackPlacementId": str(target["placementId"]),
            "points": {
                "home": home,
                "pickup": pickup,
                "accessPickup": access_pickup,
                "crossAisleEntry": cross_entry,
                "rackAisleEntry": aisle_entry,
                "shelfPreAlign": shelf_pre_align,
                "shelfService": shelf,
            },
            "segments": segments,
            "reviewedStopActions": [
                {
                    "stop": "1",
                    "placementId": str(staged["placementId"]),
                    "actions": ["pick"],
                },
                {
                    "stop": "2",
                    "zoneId": str(zone["zoneId"]),
                    "actions": ["travel_loaded", "use_cross_aisle"],
                },
                {
                    "stop": "3",
                    "placementId": str(target["placementId"]),
                    "actions": ["align", "place"],
                },
                {
                    "stop": "4",
                    "placementId": str(vehicle["placementId"]),
                    "actions": ["withdraw", "return_empty"],
                },
            ],
        }

    cycles = [
        build_cycle(
            cycle_key="lower_staging_to_lower_racks",
            cycle_label="Lower staging to lower rack block",
            vehicle=moving_lower,
            staged=selected_lower_pallet,
            target=lower_target,
            cross_z=lower_cross_z,
            corridors=lower_corridors,
        ),
        build_cycle(
            cycle_key="upper_staging_to_middle_racks",
            cycle_label="Upper staging to middle rack block",
            vehicle=moving_upper,
            staged=selected_upper_pallet,
            target=upper_target,
            cross_z=upper_cross_z,
            corridors=upper_corridors,
        ),
    ]
    moving_ids = {
        str(item["vehiclePlacementId"])
        for item in cycles
    }
    selected_pallet_ids = {
        str(item["stagedPalletPlacementId"])
        for item in cycles
    }
    parked_ids = sorted(
        str(item["placementId"])
        for item in [*forklifts, *pallet_trucks]
        if str(item["placementId"]) not in moving_ids
    )
    return {
        "schemaVersion": REFERENCE_RECEIVING_SCHEMA_VERSION,
        "preset": preset,
        "cycleKind": "receiving_putaway",
        "zoneId": str(zone["zoneId"]),
        "cycles": cycles,
        "parkedVehiclePlacementIds": parked_ids,
        "scopePlacementIds": sorted(
            str(item["placementId"]) for item in placements
        ),
        "excludedObstaclePlacementIds": sorted(
            moving_ids | selected_pallet_ids
        ),
        "traversablePolygons": [
            lower_corridors["bank"],
            lower_corridors["cross"],
            lower_corridors["rackAisle"],
            upper_corridors["bank"],
            upper_corridors["cross"],
            upper_corridors["rackAisle"],
        ],
        "geometryAuthority": (
            "derived_from_exact_reference_receiving_zone_placement_and_catalog_geometry"
        ),
        "loadValidationStatus": "not_evaluated",
        "productionEligible": False,
    }


__all__ = [
    "REFERENCE_RECEIVING_PUTAWAY_PRESET",
    "REFERENCE_RECEIVING_PLANNER_GRID_METERS",
    "REFERENCE_RECEIVING_SCHEMA_VERSION",
    "REFERENCE_RECEIVING_ZONE_LABEL",
    "derive_reference_receiving_cycles",
]
