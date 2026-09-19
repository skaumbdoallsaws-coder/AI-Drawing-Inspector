"""Enumerate existing actors and evaluate candidate movement programs.

This never invents an actor, a station, a stop, or a process step. It reports
what the saved layout actually contains, then decides for each candidate
program whether the authored evidence needed to route it exists.

A candidate that lacks authored stops returns ``needs_authored_stops`` with the
exact missing authority named. Guessing a plausible sequence from proximity is
the failure mode this module exists to prevent.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

try:  # pragma: no cover - exercised through the geometry-backed paths
    from shapely.geometry import LineString, Point, Polygon
except ImportError:  # pragma: no cover
    LineString = Point = Polygon = None  # type: ignore[assignment]

MOVEMENT_INVENTORY_SCHEMA_VERSION = "facility-movement-inventory-v1"

NEEDS_AUTHORED_STOPS = "needs_authored_stops"
NEEDS_PUBLISHED_VEHICLE_PROFILE = "needs_published_vehicle_profile"
NEEDS_DIRECTIONAL_LANES = "needs_directional_lanes"
NEEDS_CIRCULATION_ROUTE = "needs_circulation_route"

MOVEMENT_QUALIFICATION = (
    "Prototype candidate movement. Enumerates existing actors and reports which "
    "programs have authored routing evidence. It does not establish safety, "
    "staffing, timing, throughput, capacity, collision avoidance, ergonomics, "
    "regulatory compliance, or production scheduling."
)

#: Asset substrings that identify a mobile actor. Membership here means the
#: placement *can* move; it never implies what work it performs.
_OPERATOR_TOKENS = ("operator",)
_VEHICLE_TOKENS = ("forklift", "pallet-truck", "pallet_truck")
_MOBILE_TOKENS = ("mobile-cart", "mobile_cart", "platform-truck")


def _actor_kind(asset_id: str) -> str | None:
    lowered = asset_id.lower()
    if any(token in lowered for token in _OPERATOR_TOKENS):
        return "operator"
    if any(token in lowered for token in _VEHICLE_TOKENS):
        return "vehicle"
    if any(token in lowered for token in _MOBILE_TOKENS):
        return "mobile_equipment"
    return None


def _polygon(zone: Mapping[str, Any]):
    return Polygon([(point["x"], point["z"]) for point in zone["boundary"]])


def contained_area_zone_labels(
    layout: Mapping[str, Any],
    root_zone_labels: Sequence[str],
) -> list[str]:
    """Return each root and every zone geometrically contained by it."""

    if Polygon is None:  # pragma: no cover
        raise RuntimeError("Shapely is required to resolve a movement area.")
    requested = set(root_zone_labels)
    roots = [
        zone
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping) and zone.get("label") in requested
    ]
    resolved_root_labels = {str(zone.get("label") or "") for zone in roots}
    missing = sorted(requested - resolved_root_labels)
    if missing:
        raise ValueError(f"Movement area zones are unavailable: {missing}")
    root_polygons = [_polygon(zone) for zone in roots]
    labels = {
        str(zone.get("label") or "")
        for zone in layout.get("zones", [])
        if (
            isinstance(zone, Mapping)
            and str(zone.get("label") or "")
            and any(root.covers(_polygon(zone)) for root in root_polygons)
        )
    }
    return sorted(labels)


def enumerate_area(
    layout: Mapping[str, Any],
    area_zone_labels: Sequence[str],
) -> dict[str, Any]:
    """Report every zone, actor, and station inside the named zones.

    Placement-to-zone assignment is by exact geometric containment in the
    smallest containing zone. That is a stable spatial relationship, not a
    proximity guess, and it carries no process meaning.
    """

    if Polygon is None:  # pragma: no cover
        raise RuntimeError("Shapely is required to enumerate a movement area.")

    wanted = set(area_zone_labels)
    zones = [
        {
            "zoneId": zone["zoneId"],
            "label": zone["label"],
            "zoneType": zone.get("zoneType"),
            "anchorCount": len(zone.get("anchors") or []),
            "polygon": _polygon(zone),
        }
        for zone in layout.get("zones") or []
        if zone.get("label") in wanted
    ]

    actors: list[dict[str, Any]] = []
    stations: list[dict[str, Any]] = []
    for placement in layout.get("placements") or []:
        position = placement["transform"]["position"]
        point = Point(position["x"], position["z"])
        containing = [zone for zone in zones if zone["polygon"].covers(point)]
        if not containing:
            continue
        zone = min(containing, key=lambda item: item["polygon"].area)
        record = {
            "placementId": placement["placementId"],
            "assetId": placement["assetId"],
            "assetDefinitionRevision": placement.get("assetDefinitionRevision"),
            "zoneId": zone["zoneId"],
            "zoneLabel": zone["label"],
            "position": {"x": position["x"], "z": position["z"]},
            "supportPlacementId": (placement.get("snapRelationship") or {}).get(
                "supportPlacementId"
            ),
        }
        kind = _actor_kind(placement["assetId"])
        if kind is not None:
            actors.append(dict(record, actorKind=kind))
        else:
            stations.append(record)

    routes_in_area = []
    for route in layout.get("routes") or []:
        centerline = route.get("centerline") or []
        if len(centerline) < 2:
            continue
        line = LineString([(point["x"], point["z"]) for point in centerline])
        covered = 0.0
        for zone in zones:
            piece = line.intersection(zone["polygon"])
            if not piece.is_empty:
                covered = max(covered, float(piece.length))
        aisle = (route.get("extensions") or {}).get("facilityAisle") or {}
        if covered > 0.0:
            routes_in_area.append(
                {
                    "routeId": route["routeId"],
                    "routeKind": route.get("routeKind"),
                    "direction": aisle.get("direction"),
                    "lengthInAreaMeters": round(covered, 6),
                }
            )

    directional_markings = [
        marking["markingId"]
        for marking in layout.get("floorMarkings") or []
        if marking.get("markingType") == "direction_arrow"
        and any(
            zone["polygon"].covers(
                Point(
                    (marking.get("transform") or {}).get("position", {}).get("x", 0.0),
                    (marking.get("transform") or {}).get("position", {}).get("z", 0.0),
                )
            )
            for zone in zones
        )
    ]

    return {
        "schemaVersion": MOVEMENT_INVENTORY_SCHEMA_VERSION,
        "zones": [
            {key: zone[key] for key in ("zoneId", "label", "zoneType", "anchorCount")}
            for zone in zones
        ],
        "actors": sorted(actors, key=lambda item: item["placementId"]),
        "stations": sorted(stations, key=lambda item: item["placementId"]),
        "routesInArea": routes_in_area,
        "directionalMarkingIds": directional_markings,
        "authoredAnchorCount": sum(zone["anchorCount"] for zone in zones),
        "processBindingCount": len(layout.get("processBindings") or []),
        "qualification": MOVEMENT_QUALIFICATION,
    }


def _published_profiles(profiles: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in profiles if str(item.get("status") or "") == "published"]


def evaluate_candidates(
    inventory: Mapping[str, Any],
    *,
    vehicle_profiles: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Decide, per candidate program, whether authored evidence supports it."""

    actors = list(inventory["actors"])
    operators = [item for item in actors if item["actorKind"] == "operator"]
    vehicles = [item for item in actors if item["actorKind"] == "vehicle"]
    anchors = int(inventory["authoredAnchorCount"])
    bindings = int(inventory["processBindingCount"])
    routes = list(inventory["routesInArea"])
    published = _published_profiles(vehicle_profiles)

    def missing_stop_authority() -> list[str]:
        reasons = []
        if anchors == 0:
            reasons.append("no authored zone anchors define where an actor stops")
        if bindings == 0:
            reasons.append("no process bindings define which actor performs which work")
        if not routes:
            reasons.append("no authored route enters the area")
        return reasons

    candidates: list[dict[str, Any]] = []

    for label, zone_prefix in (
        ("inspection_operator_journey", "Inpection Station"),
        ("packaging_operator_journey", "Packaging Station"),
    ):
        eligible = [
            item for item in operators if str(item["zoneLabel"]).startswith(zone_prefix)
        ]
        reasons = missing_stop_authority()
        candidates.append(
            {
                "candidateId": label,
                "status": "unavailable" if reasons else "available",
                "code": NEEDS_AUTHORED_STOPS if reasons else None,
                "actorPlacementIds": [item["placementId"] for item in eligible],
                "candidateZoneIds": sorted({item["zoneId"] for item in eligible}),
                "orderedStopIds": [],
                "missingAuthority": reasons,
            }
        )

    for label, source_prefix, target_prefix in (
        ("inspection_to_packaging_handoff", "Inpection Station", "Packaging Station"),
        ("packaging_to_finished_goods_handoff", "Packaging Station", "Finished Goods"),
    ):
        source = [i for i in inventory["stations"] if str(i["zoneLabel"]).startswith(source_prefix)]
        target = [i for i in inventory["stations"] if str(i["zoneLabel"]).startswith(target_prefix)]
        reasons = []
        if anchors == 0:
            reasons.append("no authored FIFO endpoint anchors exist at either end")
        if bindings == 0:
            reasons.append("no process binding declares a product transfer")
        if not source or not target:
            reasons.append("one or both handoff endpoints are absent")
        candidates.append(
            {
                "candidateId": label,
                "status": "unavailable" if reasons else "available",
                "code": NEEDS_AUTHORED_STOPS if reasons else None,
                "sourcePlacementIds": [item["placementId"] for item in source],
                "targetPlacementIds": [item["placementId"] for item in target],
                "orderedStopIds": [],
                "missingAuthority": reasons,
                "topologyOnly": True,
            }
        )

    vehicle_reasons: list[str] = []
    code = None
    if not vehicles:
        vehicle_reasons.append("no existing vehicle placement in the area")
        code = NEEDS_AUTHORED_STOPS
    matched = [
        profile
        for profile in published
        if any(
            (profile.get("assetDefinitionRef") or {}).get("assetId") == vehicle["assetId"]
            for vehicle in vehicles
        )
    ]
    if not matched:
        vehicle_reasons.append(
            "no published vehicle profile is bound to an existing vehicle asset "
            f"({len(published)} published of {len(vehicle_profiles)} known)"
        )
        code = NEEDS_PUBLISHED_VEHICLE_PROFILE
    directional = [item for item in routes if item.get("direction") == "one_way"]
    if not directional:
        vehicle_reasons.append(
            "no one-way lane exists; a return leg cannot use an opposite lane"
        )
        code = code or NEEDS_DIRECTIONAL_LANES
    if not routes:
        vehicle_reasons.append("no authored route enters the area")
        code = code or NEEDS_CIRCULATION_ROUTE
    candidates.append(
        {
            "candidateId": "finished_goods_vehicle_journey",
            "status": "unavailable" if vehicle_reasons else "available",
            "code": code,
            "actorPlacementIds": [item["placementId"] for item in vehicles],
            "orderedStopIds": [],
            "missingAuthority": vehicle_reasons,
        }
    )

    return candidates


def build_movement_report(
    layout: Mapping[str, Any],
    area_zone_labels: Sequence[str],
    *,
    vehicle_profiles: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Inventory plus candidate evaluation, ready for a tool response."""

    inventory = enumerate_area(layout, area_zone_labels)
    candidates = evaluate_candidates(inventory, vehicle_profiles=vehicle_profiles)
    available = [item for item in candidates if item["status"] == "available"]
    return {
        "schemaVersion": MOVEMENT_INVENTORY_SCHEMA_VERSION,
        "inventory": inventory,
        "candidates": candidates,
        "availableCandidateCount": len(available),
        "unavailableCandidateCount": len(candidates) - len(available),
        "qualification": MOVEMENT_QUALIFICATION,
    }
