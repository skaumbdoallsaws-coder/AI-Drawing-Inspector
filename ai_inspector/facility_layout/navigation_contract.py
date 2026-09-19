"""Closed NAV1 contracts for durable intent and derived navigation evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .errors import FacilityValidationError


FACILITY_NAVIGATION_SCHEMA_VERSION = 1
FACILITY_NAVIGATION_CONTRACT_VERSION = "facility-navigation-contract-v1"
FACILITY_NAVIGATION_SNAPSHOT_SCHEMA = "facility-navigation-snapshot-v1"
FACILITY_NAVIGATION_JOURNEY_SCHEMA = "facility-navigation-journey-v1"
FACILITY_NAVIGATION_GEOMETRY_PRECISION = 6
FACILITY_NAVIGATION_COMPUTATIONAL_EPSILON = 1.0e-9
FACILITY_NAVIGATION_INFLUENCE_MARGIN_METERS = 0.0

FACILITY_NAVIGATION_LIMITS = {
    "anchors": 2_000,
    "movementPrograms": 1_000,
    "manualPathConstraints": 1_000,
    "handoffPrograms": 1_000,
    "orderedStopsPerProgram": 128,
    "referencesPerProgram": 256,
    "evidencePerRecord": 64,
    "polylinePointsPerConstraint": 2_048,
    "snapshotWalkableRegions": 2_000,
    "snapshotObstacleRecords": 25_000,
    "snapshotNodes": 25_000,
    "snapshotEdges": 100_000,
    "snapshotComponents": 2_000,
    "journeyOrderedAnchors": 256,
    "journeyNetworkEdges": 25_000,
    "journeyCenterlinePoints": 25_000,
    "journeyPoses": 25_000,
    "candidateAlternatives": 16,
    "canonicalExtensionBytes": 2 * 1024 * 1024,
    "canonicalSnapshotBytes": 8 * 1024 * 1024,
    "canonicalJourneyBytes": 8 * 1024 * 1024,
    "sageSummaryBytes": 8_192,
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_ANCHOR_KINDS = frozenset({
    "actor_home",
    "station_operate",
    "station_load",
    "station_unload",
    "station_inspect",
    "fifo_input",
    "fifo_output",
    "cell_entrance",
    "aisle_access",
    "crossing",
    "vehicle_parking",
    "vehicle_turnaround",
    "handoff_endpoint",
})
_INTERACTION_KINDS = frozenset({
    "none",
    "operate",
    "load",
    "unload",
    "inspect",
    "park",
    "turnaround",
    "handoff",
    "enter",
    "exit",
})
_ACTOR_CLASSES = frozenset({"pedestrian", "vehicle"})
_POSITION_AUTHORITIES = frozenset({
    "ui_authored",
    "controlled_source",
    "derived",
    "inferred",
    "unknown",
})
_EVIDENCE_STATUSES = frozenset({"authored", "derived", "inferred", "unknown"})
_REVIEW_STATUSES = frozenset({"pending", "confirmed", "rejected"})
_LOOP_MODES = frozenset({
    "one_way",
    "closed_loop",
    "out_and_return",
    "paired_lane_return",
    "task_cycle",
})
_CONSTRAINT_MODES = frozenset({
    "guide",
    "locked_segment",
    "complete_override",
    "avoid_region",
    "preferred_corridor",
})
_CONSTRAINT_DIRECTIONS = frozenset({"forward", "reverse", "bidirectional"})
_OWNER_KINDS = frozenset({
    "placement",
    "zone",
    "route",
    "marking",
    "process_binding",
    "asset_connector",
})
_DERIVED_SOURCE_KINDS = frozenset({
    "zone_anchor",
    "route_endpoint",
    "marking_center",
    "placement_transform",
    "placement_access",
    "process_binding",
    "asset_connector",
})
_APPROACH_DIRECTIONS = frozenset({
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
    "any",
})
_TIMING_AUTHORITIES = frozenset({
    "topology_only",
    "presentation_only",
    "user_authored",
    "controlled_source",
    "unknown",
})
_SEQUENCE_POLICIES = frozenset({
    "topology_only",
    "source_before_target",
    "bidirectional_transfer",
    "authored_sequence",
})
_WRITER_KINDS = frozenset({"user", "controlled_import", "deterministic_generator", "model"})


class FacilityNavigationContractError(FacilityValidationError):
    """A NAV1 contract or authority boundary was violated."""


@dataclass(frozen=True)
class NavigationIdentityIndex:
    placement_ids: frozenset[str] = frozenset()
    zone_ids: frozenset[str] = frozenset()
    route_ids: frozenset[str] = frozenset()
    marking_ids: frozenset[str] = frozenset()
    process_binding_ids: frozenset[str] = frozenset()
    zone_anchor_ids: frozenset[str] = frozenset()
    asset_connector_ids: frozenset[str] = frozenset()


def _fail(code: str, message: str, path: str, **details: Any) -> None:
    raise FacilityNavigationContractError(
        code,
        message,
        details={"path": path, **details},
    )


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise FacilityNavigationContractError(
            "facility_navigation_invalid_json",
            "Navigation data must be finite JSON-compatible data.",
        ) from error


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def navigation_stable_id(prefix: str, seed: Any) -> str:
    if prefix not in {"na", "nmp", "nmc", "nhp", "nss", "njs", "nst", "nne"}:
        raise ValueError("Unsupported navigation identity prefix.")
    return f"{prefix}-{_fingerprint(seed)[:24]}"


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_navigation_schema_invalid", "Expected an object.", path)
    return value


def _array(value: Any, path: str, *, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        _fail("facility_navigation_schema_invalid", "Expected an array.", path)
    if len(value) > maximum:
        _fail(
            "facility_navigation_resource_limit_exceeded",
            "Navigation collection exceeds its pre-allocation limit.",
            path,
            maximumItems=maximum,
            actualItems=len(value),
        )
    return value


def _closed(
    value: Mapping[str, Any],
    fields: Iterable[str],
    path: str,
    *,
    optional: Iterable[str] = (),
) -> None:
    required = set(fields)
    optional_set = set(optional)
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional_set)
    if missing:
        _fail(
            "facility_navigation_schema_invalid",
            f"Missing required fields: {', '.join(missing)}.",
            path,
        )
    if unknown:
        _fail(
            "facility_navigation_unknown_field",
            f"Unknown fields: {', '.join(unknown)}.",
            path,
        )


def _text(value: Any, path: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail(
            "facility_navigation_schema_invalid",
            "Expected a bounded non-empty string.",
            path,
        )
    return value


def _stable_id(value: Any, path: str, *, prefix: str | None = None) -> str:
    result = _text(value, path)
    if not _ID_RE.fullmatch(result) or (prefix and not result.startswith(f"{prefix}-")):
        _fail(
            "facility_navigation_identity_invalid",
            "Expected a stable navigation identity.",
            path,
            requiredPrefix=prefix,
        )
    return result


def _revision(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        _fail(
            "facility_navigation_revision_invalid",
            "Expected a lowercase SHA-256 revision.",
            path,
        )
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("facility_navigation_schema_invalid", "Expected a finite number.", path)
    result = float(value)
    if not math.isfinite(result):
        _fail("facility_navigation_schema_invalid", "Expected a finite number.", path)
    return result


def _point(value: Any, path: str) -> dict[str, float]:
    item = _mapping(value, path)
    _closed(item, {"x", "z"}, path)
    return {
        "x": round(_number(item["x"], f"{path}.x"), FACILITY_NAVIGATION_GEOMETRY_PRECISION),
        "z": round(_number(item["z"], f"{path}.z"), FACILITY_NAVIGATION_GEOMETRY_PRECISION),
    }


def _enum(value: Any, allowed: frozenset[str], path: str) -> str:
    result = _text(value, path)
    if result not in allowed:
        _fail(
            "facility_navigation_schema_invalid",
            "Value is outside the closed navigation vocabulary.",
            path,
            allowed=sorted(allowed),
        )
    return result


def _id_array(
    value: Any,
    path: str,
    *,
    maximum: int,
    ordered: bool = False,
    allow_repeats: bool = False,
) -> list[str]:
    values = _array(value, path, maximum=maximum)
    result = [_stable_id(item, f"{path}[{index}]") for index, item in enumerate(values)]
    if not allow_repeats and len(result) != len(set(result)):
        _fail("facility_navigation_duplicate_id", "Identifiers must be unique.", path)
    return result if ordered else sorted(result)


def _evidence(value: Any, path: str) -> list[str]:
    return _id_array(
        value,
        path,
        maximum=FACILITY_NAVIGATION_LIMITS["evidencePerRecord"],
    )


def _source_revisions(value: Any, path: str) -> dict[str, str]:
    item = _mapping(value, path)
    if not item or len(item) > 64:
        _fail(
            "facility_navigation_schema_invalid",
            "Source revisions require between 1 and 64 records.",
            path,
        )
    return {
        _stable_id(key, f"{path}.{key}"): _revision(revision, f"{path}.{key}")
        for key, revision in sorted(item.items())
    }


def _review_and_evidence(item: Mapping[str, Any], path: str) -> None:
    _enum(item["evidenceStatus"], _EVIDENCE_STATUSES, f"{path}.evidenceStatus")
    _evidence(item["evidence"], f"{path}.evidence")
    _enum(item["reviewStatus"], _REVIEW_STATUSES, f"{path}.reviewStatus")


def _owner_ref(value: Any, path: str, identities: NavigationIdentityIndex) -> None:
    item = _mapping(value, path)
    _closed(item, {"ownerKind", "ownerId"}, path, optional={"connectorId"})
    kind = _enum(item["ownerKind"], _OWNER_KINDS, f"{path}.ownerKind")
    owner_id = _stable_id(item["ownerId"], f"{path}.ownerId")
    index = {
        "placement": identities.placement_ids,
        "zone": identities.zone_ids,
        "route": identities.route_ids,
        "marking": identities.marking_ids,
        "process_binding": identities.process_binding_ids,
        "asset_connector": identities.placement_ids,
    }[kind]
    if owner_id not in index:
        _fail(
            "facility_navigation_dangling_identity",
            "Navigation owner reference does not exist.",
            f"{path}.ownerId",
            ownerKind=kind,
            ownerId=owner_id,
        )
    if kind == "asset_connector":
        connector = _stable_id(item.get("connectorId"), f"{path}.connectorId")
        composite = f"{owner_id}:{connector}"
        if identities.asset_connector_ids and composite not in identities.asset_connector_ids:
            _fail(
                "facility_navigation_dangling_identity",
                "Asset connector does not exist at the bound catalog revision.",
                f"{path}.connectorId",
                connectorId=composite,
            )
    elif "connectorId" in item:
        _fail(
            "facility_navigation_schema_invalid",
            "Only an asset_connector owner may carry connectorId.",
            f"{path}.connectorId",
        )


def _derived_position_ref(value: Any, path: str, identities: NavigationIdentityIndex) -> None:
    item = _mapping(value, path)
    _closed(item, {"sourceKind", "sourceId", "sourceRevision"}, path)
    kind = _enum(item["sourceKind"], _DERIVED_SOURCE_KINDS, f"{path}.sourceKind")
    source_id = _stable_id(item["sourceId"], f"{path}.sourceId")
    _revision(item["sourceRevision"], f"{path}.sourceRevision")
    known = {
        "zone_anchor": identities.zone_anchor_ids,
        "route_endpoint": frozenset(
            f"{route_id}:{endpoint}"
            for route_id in identities.route_ids
            for endpoint in ("source", "target")
        ),
        "marking_center": identities.marking_ids,
        "placement_transform": identities.placement_ids,
        "placement_access": identities.placement_ids,
        "process_binding": identities.process_binding_ids,
        "asset_connector": identities.asset_connector_ids,
    }[kind]
    if known and source_id not in known:
        _fail(
            "facility_navigation_dangling_identity",
            "Derived position source does not exist.",
            f"{path}.sourceId",
            sourceKind=kind,
            sourceId=source_id,
        )


def navigation_identity_index(layout: Mapping[str, Any]) -> NavigationIdentityIndex:
    zone_anchor_ids = set()
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping):
            continue
        zone_id = str(zone.get("zoneId") or "")
        for anchor in zone.get("anchors", []):
            if isinstance(anchor, Mapping) and anchor.get("anchorId"):
                zone_anchor_ids.add(f"{zone_id}:{anchor['anchorId']}")
    return NavigationIdentityIndex(
        placement_ids=frozenset(
            str(item["placementId"])
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        ),
        zone_ids=frozenset(
            str(item["zoneId"])
            for item in layout.get("zones", [])
            if isinstance(item, Mapping) and item.get("zoneId")
        ),
        route_ids=frozenset(
            str(item["routeId"])
            for item in layout.get("routes", [])
            if isinstance(item, Mapping) and item.get("routeId")
        ),
        marking_ids=frozenset(
            str(item["markingId"])
            for item in layout.get("floorMarkings", [])
            if isinstance(item, Mapping) and item.get("markingId")
        ),
        process_binding_ids=frozenset(
            str(item["processBindingId"])
            for item in layout.get("processBindings", [])
            if isinstance(item, Mapping) and item.get("processBindingId")
        ),
        zone_anchor_ids=frozenset(zone_anchor_ids),
    )


def _validate_anchor(
    value: Any,
    path: str,
    identities: NavigationIdentityIndex,
) -> str:
    item = _mapping(value, path)
    fields = {
        "navigationAnchorId",
        "anchorKind",
        "ownerRef",
        "interactionKind",
        "positionAuthority",
        "localPosition",
        "derivedPositionRef",
        "approachDirections",
        "actorClasses",
        "evidenceStatus",
        "evidence",
        "reviewStatus",
    }
    _closed(item, fields, path)
    anchor_id = _stable_id(
        item["navigationAnchorId"],
        f"{path}.navigationAnchorId",
        prefix="na",
    )
    _enum(item["anchorKind"], _ANCHOR_KINDS, f"{path}.anchorKind")
    _owner_ref(item["ownerRef"], f"{path}.ownerRef", identities)
    _enum(
        item["interactionKind"],
        _INTERACTION_KINDS,
        f"{path}.interactionKind",
    )
    authority = _enum(
        item["positionAuthority"],
        _POSITION_AUTHORITIES,
        f"{path}.positionAuthority",
    )
    local_position = item["localPosition"]
    derived_ref = item["derivedPositionRef"]
    if authority in {"ui_authored", "controlled_source"}:
        if local_position is None:
            _fail(
                "facility_navigation_position_authority_invalid",
                "Authored position authority requires localPosition.",
                f"{path}.localPosition",
            )
        _point(local_position, f"{path}.localPosition")
        if authority == "ui_authored" and derived_ref is not None:
            _fail(
                "facility_navigation_position_authority_invalid",
                "A UI-authored point cannot also claim derived position authority.",
                f"{path}.derivedPositionRef",
            )
        if authority == "controlled_source":
            _derived_position_ref(
                derived_ref,
                f"{path}.derivedPositionRef",
                identities,
            )
    elif authority in {"derived", "inferred"}:
        if local_position is not None:
            _fail(
                "facility_navigation_coordinate_authority_forbidden",
                "Derived and inferred anchors reference geometry; they cannot persist generated coordinates.",
                f"{path}.localPosition",
            )
        _derived_position_ref(
            derived_ref,
            f"{path}.derivedPositionRef",
            identities,
        )
    elif local_position is not None or derived_ref is not None:
        _fail(
            "facility_navigation_position_authority_invalid",
            "Unknown position authority cannot carry position data.",
            path,
        )
    approach = _array(
        item["approachDirections"],
        f"{path}.approachDirections",
        maximum=5,
    )
    directions = [
        _enum(raw, _APPROACH_DIRECTIONS, f"{path}.approachDirections[{index}]")
        for index, raw in enumerate(approach)
    ]
    if len(directions) != len(set(directions)):
        _fail(
            "facility_navigation_schema_invalid",
            "Approach directions must be unique.",
            f"{path}.approachDirections",
        )
    actors = _array(item["actorClasses"], f"{path}.actorClasses", maximum=2)
    actor_classes = [
        _enum(raw, _ACTOR_CLASSES, f"{path}.actorClasses[{index}]")
        for index, raw in enumerate(actors)
    ]
    if not actor_classes or len(actor_classes) != len(set(actor_classes)):
        _fail(
            "facility_navigation_schema_invalid",
            "Anchor actor classes must be non-empty and unique.",
            f"{path}.actorClasses",
        )
    _review_and_evidence(item, path)
    expected_evidence = {
        "ui_authored": "authored",
        "controlled_source": "authored",
        "derived": "derived",
        "inferred": "inferred",
        "unknown": "unknown",
    }[authority]
    if item["evidenceStatus"] != expected_evidence:
        _fail(
            "facility_navigation_authority_mismatch",
            "Anchor evidence status must match its position authority.",
            f"{path}.evidenceStatus",
            positionAuthority=authority,
            expectedEvidenceStatus=expected_evidence,
        )
    return anchor_id


def _actor_profile_ref(value: Any, path: str, actor_class: str) -> None:
    item = _mapping(value, path)
    _closed(item, {"profileKind", "profileId", "profileRevision"}, path)
    profile_kind = _enum(
        item["profileKind"],
        frozenset({"pedestrian", "vehicle"}),
        f"{path}.profileKind",
    )
    if profile_kind != actor_class:
        _fail(
            "facility_navigation_actor_profile_mismatch",
            "Actor profile kind must match the movement program actor class.",
            f"{path}.profileKind",
        )
    _stable_id(item["profileId"], f"{path}.profileId")
    _revision(item["profileRevision"], f"{path}.profileRevision")


def _validate_movement_program(
    value: Any,
    path: str,
    identities: NavigationIdentityIndex,
    anchor_ids: frozenset[str],
) -> tuple[str, set[str], set[str], set[str]]:
    item = _mapping(value, path)
    fields = {
        "movementProgramId",
        "actorPlacementId",
        "actorClass",
        "actorProfileRef",
        "orderedStops",
        "loopMode",
        "requiredRouteIds",
        "requiredAnchorIds",
        "forbiddenZoneIds",
        "forbiddenRouteIds",
        "manualPathConstraintIds",
        "handoffProgramIds",
        "sourceRevisions",
        "evidenceStatus",
        "evidence",
        "reviewStatus",
    }
    _closed(item, fields, path)
    program_id = _stable_id(
        item["movementProgramId"],
        f"{path}.movementProgramId",
        prefix="nmp",
    )
    actor_id = _stable_id(item["actorPlacementId"], f"{path}.actorPlacementId")
    if actor_id not in identities.placement_ids:
        _fail(
            "facility_navigation_dangling_identity",
            "Movement program actor must be an existing placement.",
            f"{path}.actorPlacementId",
            actorPlacementId=actor_id,
        )
    actor_class = _enum(item["actorClass"], _ACTOR_CLASSES, f"{path}.actorClass")
    _actor_profile_ref(item["actorProfileRef"], f"{path}.actorProfileRef", actor_class)
    stops = _array(
        item["orderedStops"],
        f"{path}.orderedStops",
        maximum=FACILITY_NAVIGATION_LIMITS["orderedStopsPerProgram"],
    )
    stop_ids = set()
    stop_anchor_ids = []
    for index, raw in enumerate(stops):
        stop_path = f"{path}.orderedStops[{index}]"
        stop = _mapping(raw, stop_path)
        _closed(
            stop,
            {"stopId", "navigationAnchorId", "interactionKind", "required"},
            stop_path,
        )
        stop_id = _stable_id(stop["stopId"], f"{stop_path}.stopId", prefix="nst")
        if stop_id in stop_ids:
            _fail("facility_navigation_duplicate_id", "Stop IDs must be unique.", stop_path)
        stop_ids.add(stop_id)
        anchor_id = _stable_id(
            stop["navigationAnchorId"],
            f"{stop_path}.navigationAnchorId",
            prefix="na",
        )
        if anchor_id not in anchor_ids:
            _fail(
                "facility_navigation_dangling_identity",
                "Movement stop references an unknown navigation anchor.",
                f"{stop_path}.navigationAnchorId",
            )
        stop_anchor_ids.append(anchor_id)
        _enum(
            stop["interactionKind"],
            _INTERACTION_KINDS,
            f"{stop_path}.interactionKind",
        )
        if not isinstance(stop["required"], bool):
            _fail(
                "facility_navigation_schema_invalid",
                "Stop required must be boolean.",
                f"{stop_path}.required",
            )
    _enum(item["loopMode"], _LOOP_MODES, f"{path}.loopMode")
    required_routes = set(_id_array(
        item["requiredRouteIds"],
        f"{path}.requiredRouteIds",
        maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
    ))
    forbidden_routes = set(_id_array(
        item["forbiddenRouteIds"],
        f"{path}.forbiddenRouteIds",
        maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
    ))
    for route_id in required_routes | forbidden_routes:
        if route_id not in identities.route_ids:
            _fail(
                "facility_navigation_dangling_identity",
                "Movement program references an unknown route.",
                path,
                routeId=route_id,
            )
    if required_routes & forbidden_routes:
        _fail(
            "facility_navigation_constraint_conflict",
            "A route cannot be both required and forbidden.",
            path,
        )
    required_anchors = set(_id_array(
        item["requiredAnchorIds"],
        f"{path}.requiredAnchorIds",
        maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
    ))
    if not set(stop_anchor_ids).issubset(required_anchors):
        _fail(
            "facility_navigation_schema_invalid",
            "Every ordered stop must also be a required anchor.",
            f"{path}.requiredAnchorIds",
        )
    if not required_anchors.issubset(anchor_ids):
        _fail(
            "facility_navigation_dangling_identity",
            "Movement program references an unknown navigation anchor.",
            f"{path}.requiredAnchorIds",
        )
    forbidden_zones = _id_array(
        item["forbiddenZoneIds"],
        f"{path}.forbiddenZoneIds",
        maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
    )
    if any(zone_id not in identities.zone_ids for zone_id in forbidden_zones):
        _fail(
            "facility_navigation_dangling_identity",
            "Movement program references an unknown forbidden zone.",
            f"{path}.forbiddenZoneIds",
        )
    constraint_ids = set(_id_array(
        item["manualPathConstraintIds"],
        f"{path}.manualPathConstraintIds",
        maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
    ))
    handoff_ids = set(_id_array(
        item["handoffProgramIds"],
        f"{path}.handoffProgramIds",
        maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
    ))
    _source_revisions(item["sourceRevisions"], f"{path}.sourceRevisions")
    _review_and_evidence(item, path)
    return program_id, required_anchors, constraint_ids, handoff_ids


def _validate_manual_constraint(
    value: Any,
    path: str,
    program_ids: frozenset[str],
    anchor_ids: frozenset[str],
    identities: NavigationIdentityIndex,
) -> tuple[str, str]:
    item = _mapping(value, path)
    fields = {
        "manualPathConstraintId",
        "movementProgramId",
        "constraintMode",
        "authoredPolyline",
        "snapRefs",
        "lockedSegmentIndexes",
        "direction",
        "positionAuthority",
        "evidenceStatus",
        "evidence",
        "reviewStatus",
    }
    _closed(item, fields, path)
    constraint_id = _stable_id(
        item["manualPathConstraintId"],
        f"{path}.manualPathConstraintId",
        prefix="nmc",
    )
    program_id = _stable_id(
        item["movementProgramId"],
        f"{path}.movementProgramId",
        prefix="nmp",
    )
    if program_id not in program_ids:
        _fail(
            "facility_navigation_dangling_identity",
            "Manual path constraint references an unknown movement program.",
            f"{path}.movementProgramId",
        )
    _enum(item["constraintMode"], _CONSTRAINT_MODES, f"{path}.constraintMode")
    points = _array(
        item["authoredPolyline"],
        f"{path}.authoredPolyline",
        maximum=FACILITY_NAVIGATION_LIMITS["polylinePointsPerConstraint"],
    )
    if len(points) < 2:
        _fail(
            "facility_navigation_schema_invalid",
            "A manual path constraint requires at least two authored points.",
            f"{path}.authoredPolyline",
        )
    for index, point in enumerate(points):
        _point(point, f"{path}.authoredPolyline[{index}]")
    snaps = _array(
        item["snapRefs"],
        f"{path}.snapRefs",
        maximum=len(points),
    )
    snapped_indexes = set()
    for index, raw in enumerate(snaps):
        snap_path = f"{path}.snapRefs[{index}]"
        snap = _mapping(raw, snap_path)
        _closed(snap, {"pointIndex", "refKind", "refId"}, snap_path)
        point_index = snap["pointIndex"]
        if isinstance(point_index, bool) or not isinstance(point_index, int) or not 0 <= point_index < len(points):
            _fail(
                "facility_navigation_schema_invalid",
                "Snap pointIndex is outside the authored polyline.",
                f"{snap_path}.pointIndex",
            )
        if point_index in snapped_indexes:
            _fail(
                "facility_navigation_schema_invalid",
                "A manual path point can carry only one snap reference.",
                f"{snap_path}.pointIndex",
            )
        snapped_indexes.add(point_index)
        ref_kind = _enum(
            snap["refKind"],
            frozenset({"navigation_anchor", "route", "marking", "zone_anchor"}),
            f"{snap_path}.refKind",
        )
        ref_id = _stable_id(snap["refId"], f"{snap_path}.refId")
        known_refs = {
            "navigation_anchor": anchor_ids,
            "route": identities.route_ids,
            "marking": identities.marking_ids,
            "zone_anchor": identities.zone_anchor_ids,
        }[ref_kind]
        if ref_id not in known_refs:
            _fail(
                "facility_navigation_dangling_identity",
                "Manual path snap reference does not exist.",
                f"{snap_path}.refId",
                refKind=ref_kind,
                refId=ref_id,
            )
    locked = _array(
        item["lockedSegmentIndexes"],
        f"{path}.lockedSegmentIndexes",
        maximum=max(0, len(points) - 1),
    )
    if any(
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < len(points) - 1
        for index in locked
    ) or len(locked) != len(set(locked)):
        _fail(
            "facility_navigation_schema_invalid",
            "Locked segment indexes must be unique valid segment indexes.",
            f"{path}.lockedSegmentIndexes",
        )
    _enum(item["direction"], _CONSTRAINT_DIRECTIONS, f"{path}.direction")
    if item["positionAuthority"] != "ui_authored":
        _fail(
            "facility_navigation_coordinate_authority_forbidden",
            "Manual path coordinates must come from the Plan UI.",
            f"{path}.positionAuthority",
        )
    _review_and_evidence(item, path)
    if item["evidenceStatus"] != "authored":
        _fail(
            "facility_navigation_authority_mismatch",
            "A UI-authored path must carry authored evidence status.",
            f"{path}.evidenceStatus",
        )
    return constraint_id, program_id


def _validate_handoff(
    value: Any,
    path: str,
    program_anchors: Mapping[str, set[str]],
) -> tuple[str, set[str]]:
    item = _mapping(value, path)
    fields = {
        "handoffProgramId",
        "sourceMovementProgramId",
        "sourceFifoAnchorId",
        "targetMovementProgramId",
        "targetFifoAnchorId",
        "materialIdentityRef",
        "sequencePolicy",
        "timingAuthority",
        "evidenceStatus",
        "evidence",
        "reviewStatus",
    }
    _closed(item, fields, path)
    handoff_id = _stable_id(
        item["handoffProgramId"],
        f"{path}.handoffProgramId",
        prefix="nhp",
    )
    source_program = _stable_id(
        item["sourceMovementProgramId"],
        f"{path}.sourceMovementProgramId",
        prefix="nmp",
    )
    target_program = _stable_id(
        item["targetMovementProgramId"],
        f"{path}.targetMovementProgramId",
        prefix="nmp",
    )
    source_anchor = _stable_id(
        item["sourceFifoAnchorId"],
        f"{path}.sourceFifoAnchorId",
        prefix="na",
    )
    target_anchor = _stable_id(
        item["targetFifoAnchorId"],
        f"{path}.targetFifoAnchorId",
        prefix="na",
    )
    if source_program not in program_anchors or target_program not in program_anchors:
        _fail(
            "facility_navigation_dangling_identity",
            "Handoff references an unknown movement program.",
            path,
        )
    if source_anchor not in program_anchors[source_program] or target_anchor not in program_anchors[target_program]:
        _fail(
            "facility_navigation_dangling_identity",
            "Handoff FIFO anchor is not required by its movement program.",
            path,
        )
    _stable_id(item["materialIdentityRef"], f"{path}.materialIdentityRef")
    _enum(item["sequencePolicy"], _SEQUENCE_POLICIES, f"{path}.sequencePolicy")
    _enum(item["timingAuthority"], _TIMING_AUTHORITIES, f"{path}.timingAuthority")
    _review_and_evidence(item, path)
    return handoff_id, {source_program, target_program}


def _declared_ids(
    values: Sequence[Any],
    field: str,
    prefix: str,
    path: str,
) -> frozenset[str]:
    result = []
    for index, raw in enumerate(values):
        item = _mapping(raw, f"{path}[{index}]")
        result.append(
            _stable_id(item.get(field), f"{path}[{index}].{field}", prefix=prefix)
        )
    if len(result) != len(set(result)):
        _fail("facility_navigation_duplicate_id", "Navigation IDs must be unique.", path)
    return frozenset(result)


def validate_facility_navigation_extension(
    value: Any,
    identities: NavigationIdentityIndex,
) -> dict[str, Any]:
    """Validate durable navigation intent without accepting computed routes."""

    item = _mapping(value, "$.extensions.facilityNavigation")
    fields = {
        "schemaVersion",
        "anchors",
        "movementPrograms",
        "manualPathConstraints",
        "handoffPrograms",
    }
    _closed(item, fields, "$.extensions.facilityNavigation")
    if item["schemaVersion"] != FACILITY_NAVIGATION_SCHEMA_VERSION:
        _fail(
            "facility_navigation_schema_unsupported",
            "Unsupported facilityNavigation schemaVersion.",
            "$.extensions.facilityNavigation.schemaVersion",
        )
    anchors = _array(
        item["anchors"],
        "$.extensions.facilityNavigation.anchors",
        maximum=FACILITY_NAVIGATION_LIMITS["anchors"],
    )
    programs = _array(
        item["movementPrograms"],
        "$.extensions.facilityNavigation.movementPrograms",
        maximum=FACILITY_NAVIGATION_LIMITS["movementPrograms"],
    )
    constraints = _array(
        item["manualPathConstraints"],
        "$.extensions.facilityNavigation.manualPathConstraints",
        maximum=FACILITY_NAVIGATION_LIMITS["manualPathConstraints"],
    )
    handoffs = _array(
        item["handoffPrograms"],
        "$.extensions.facilityNavigation.handoffPrograms",
        maximum=FACILITY_NAVIGATION_LIMITS["handoffPrograms"],
    )
    anchor_ids = _declared_ids(
        anchors,
        "navigationAnchorId",
        "na",
        "$.extensions.facilityNavigation.anchors",
    )
    program_ids = _declared_ids(
        programs,
        "movementProgramId",
        "nmp",
        "$.extensions.facilityNavigation.movementPrograms",
    )
    constraint_ids = _declared_ids(
        constraints,
        "manualPathConstraintId",
        "nmc",
        "$.extensions.facilityNavigation.manualPathConstraints",
    )
    handoff_ids = _declared_ids(
        handoffs,
        "handoffProgramId",
        "nhp",
        "$.extensions.facilityNavigation.handoffPrograms",
    )
    for index, anchor in enumerate(anchors):
        _validate_anchor(
            anchor,
            f"$.extensions.facilityNavigation.anchors[{index}]",
            identities,
        )
    program_anchors: dict[str, set[str]] = {}
    program_constraint_refs: dict[str, set[str]] = {}
    program_handoff_refs: dict[str, set[str]] = {}
    for index, program in enumerate(programs):
        program_id, required_anchors, constraint_refs, handoff_refs = (
            _validate_movement_program(
                program,
                f"$.extensions.facilityNavigation.movementPrograms[{index}]",
                identities,
                anchor_ids,
            )
        )
        if not constraint_refs.issubset(constraint_ids):
            _fail(
                "facility_navigation_dangling_identity",
                "Movement program references an unknown manual path constraint.",
                f"$.extensions.facilityNavigation.movementPrograms[{index}].manualPathConstraintIds",
            )
        if not handoff_refs.issubset(handoff_ids):
            _fail(
                "facility_navigation_dangling_identity",
                "Movement program references an unknown handoff program.",
                f"$.extensions.facilityNavigation.movementPrograms[{index}].handoffProgramIds",
            )
        program_anchors[program_id] = required_anchors
        program_constraint_refs[program_id] = constraint_refs
        program_handoff_refs[program_id] = handoff_refs
    constraint_owners: dict[str, str] = {}
    for index, constraint in enumerate(constraints):
        constraint_id, program_id = _validate_manual_constraint(
            constraint,
            f"$.extensions.facilityNavigation.manualPathConstraints[{index}]",
            program_ids,
            anchor_ids,
            identities,
        )
        constraint_owners[constraint_id] = program_id
        if constraint_id not in program_constraint_refs[program_id]:
            _fail(
                "facility_navigation_orphan_intent",
                "Manual path constraint is not referenced by its movement program.",
                f"$.extensions.facilityNavigation.manualPathConstraints[{index}]",
            )
    for program_id, references in program_constraint_refs.items():
        for constraint_id in references:
            if constraint_owners.get(constraint_id) != program_id:
                _fail(
                    "facility_navigation_identity_mismatch",
                    "Manual path constraint belongs to a different movement program.",
                    "$.extensions.facilityNavigation.movementPrograms",
                    movementProgramId=program_id,
                    manualPathConstraintId=constraint_id,
                )
    handoff_participants: dict[str, set[str]] = {}
    for index, handoff in enumerate(handoffs):
        handoff_id, participants = _validate_handoff(
            handoff,
            f"$.extensions.facilityNavigation.handoffPrograms[{index}]",
            program_anchors,
        )
        handoff_participants[handoff_id] = participants
        if any(handoff_id not in program_handoff_refs[program_id] for program_id in participants):
            _fail(
                "facility_navigation_orphan_intent",
                "Both movement programs must reference their handoff program.",
                f"$.extensions.facilityNavigation.handoffPrograms[{index}]",
            )
    for program_id, references in program_handoff_refs.items():
        for handoff_id in references:
            if program_id not in handoff_participants.get(handoff_id, set()):
                _fail(
                    "facility_navigation_identity_mismatch",
                    "Movement program references a handoff in which it does not participate.",
                    "$.extensions.facilityNavigation.movementPrograms",
                    movementProgramId=program_id,
                    handoffProgramId=handoff_id,
                )
    detached = json.loads(_canonical_bytes(item).decode("ascii"))
    canonical_size = len(_canonical_bytes(detached))
    if canonical_size > FACILITY_NAVIGATION_LIMITS["canonicalExtensionBytes"]:
        _fail(
            "facility_navigation_resource_limit_exceeded",
            "facilityNavigation exceeds its canonical byte ceiling.",
            "$.extensions.facilityNavigation",
            canonicalBytes=canonical_size,
            maximumCanonicalBytes=FACILITY_NAVIGATION_LIMITS["canonicalExtensionBytes"],
        )
    return detached


def _canonical_record_lists(extension: dict[str, Any]) -> None:
    for anchor in extension["anchors"]:
        anchor["approachDirections"] = sorted(anchor["approachDirections"])
        anchor["actorClasses"] = sorted(anchor["actorClasses"])
        anchor["evidence"] = sorted(anchor["evidence"])
        if anchor["localPosition"] is not None:
            anchor["localPosition"] = _point(
                anchor["localPosition"],
                "$.extensions.facilityNavigation.anchors.localPosition",
            )
    extension["anchors"].sort(key=lambda item: item["navigationAnchorId"])
    for program in extension["movementPrograms"]:
        for field in (
            "requiredRouteIds",
            "requiredAnchorIds",
            "forbiddenZoneIds",
            "forbiddenRouteIds",
            "manualPathConstraintIds",
            "handoffProgramIds",
            "evidence",
        ):
            program[field] = sorted(program[field])
        program["sourceRevisions"] = dict(sorted(program["sourceRevisions"].items()))
    extension["movementPrograms"].sort(key=lambda item: item["movementProgramId"])
    for constraint in extension["manualPathConstraints"]:
        constraint["authoredPolyline"] = [
            _point(
                point,
                "$.extensions.facilityNavigation.manualPathConstraints.authoredPolyline",
            )
            for point in constraint["authoredPolyline"]
        ]
        constraint["snapRefs"].sort(
            key=lambda item: (item["pointIndex"], item["refKind"], item["refId"])
        )
        constraint["lockedSegmentIndexes"] = sorted(constraint["lockedSegmentIndexes"])
        constraint["evidence"] = sorted(constraint["evidence"])
    extension["manualPathConstraints"].sort(
        key=lambda item: item["manualPathConstraintId"]
    )
    for handoff in extension["handoffPrograms"]:
        handoff["evidence"] = sorted(handoff["evidence"])
    extension["handoffPrograms"].sort(key=lambda item: item["handoffProgramId"])


def canonicalize_facility_navigation_extension(
    value: Any,
    identities: NavigationIdentityIndex,
) -> dict[str, Any]:
    extension = deepcopy(dict(_mapping(value, "$.extensions.facilityNavigation")))
    _canonical_record_lists(extension)
    validate_facility_navigation_extension(extension, identities)
    return json.loads(_canonical_bytes(extension).decode("ascii"))


def canonical_facility_navigation_extension_bytes(
    value: Any,
    identities: NavigationIdentityIndex,
) -> bytes:
    return _canonical_bytes(canonicalize_facility_navigation_extension(value, identities))


def facility_navigation_extension_revision(
    value: Any,
    identities: NavigationIdentityIndex,
) -> str:
    return hashlib.sha256(
        canonical_facility_navigation_extension_bytes(value, identities)
    ).hexdigest()


def validate_navigation_writer_authority(
    value: Any,
    identities: NavigationIdentityIndex,
    *,
    writer_kind: str,
) -> None:
    """Prevent non-human writers from manufacturing human or controlled authority."""

    writer = _enum(writer_kind, _WRITER_KINDS, "writerKind")
    extension = validate_facility_navigation_extension(value, identities)
    if writer in {"user", "controlled_import"}:
        return
    records = [
        *extension["anchors"],
        *extension["movementPrograms"],
        *extension["manualPathConstraints"],
        *extension["handoffPrograms"],
    ]
    if extension["manualPathConstraints"]:
        _fail(
            "facility_navigation_writer_authority_forbidden",
            "Generators cannot persist UI-authored path coordinates.",
            "$.extensions.facilityNavigation.manualPathConstraints",
            writerKind=writer,
        )
    for index, record in enumerate(records):
        if record["evidenceStatus"] == "authored" or record["reviewStatus"] == "confirmed":
            _fail(
                "facility_navigation_writer_authority_forbidden",
                "A generator cannot emit authored or confirmed navigation authority.",
                "$.extensions.facilityNavigation",
                writerKind=writer,
                recordIndex=index,
            )
    for index, anchor in enumerate(extension["anchors"]):
        if anchor["positionAuthority"] in {"ui_authored", "controlled_source"}:
            _fail(
                "facility_navigation_writer_authority_forbidden",
                "A generator cannot emit UI-authored or controlled-source position authority.",
                f"$.extensions.facilityNavigation.anchors[{index}].positionAuthority",
                writerKind=writer,
            )
    for index, handoff in enumerate(extension["handoffPrograms"]):
        if handoff["timingAuthority"] in {"user_authored", "controlled_source"}:
            _fail(
                "facility_navigation_writer_authority_forbidden",
                "A generator cannot emit authored handoff timing authority.",
                f"$.extensions.facilityNavigation.handoffPrograms[{index}].timingAuthority",
                writerKind=writer,
            )


FACILITY_NAVIGATION_SNAPSHOT_QUALIFICATION = (
    "Derived traversability for one exact source and actor-profile context. "
    "It is not an editable facility, safety approval, or operational capacity claim."
)
FACILITY_NAVIGATION_JOURNEY_QUALIFICATION = (
    "Derived route evidence for one movement program and navigation snapshot. "
    "It does not establish safety, staffing, throughput, timing, or operational optimality."
)


def _source_ref(value: Any, path: str) -> None:
    item = _mapping(value, path)
    _closed(item, {"sourceKind", "sourceId", "sourceRevision"}, path)
    _stable_id(item["sourceKind"], f"{path}.sourceKind")
    _stable_id(item["sourceId"], f"{path}.sourceId")
    _revision(item["sourceRevision"], f"{path}.sourceRevision")


def _validate_snapshot_shape(value: Any) -> dict[str, Any]:
    item = _mapping(value, "navigationSnapshot")
    fields = {
        "schemaVersion",
        "navigationSnapshotId",
        "layoutRevision",
        "compilerVersion",
        "actorClass",
        "actorProfileRevision",
        "walkableRegions",
        "obstacleRecords",
        "nodes",
        "edges",
        "connectedComponents",
        "sourceRevisions",
        "geometryContextFingerprint",
        "snapshotFingerprint",
        "qualification",
    }
    _closed(item, fields, "navigationSnapshot")
    if item["schemaVersion"] != FACILITY_NAVIGATION_SNAPSHOT_SCHEMA:
        _fail(
            "facility_navigation_schema_unsupported",
            "Unsupported navigation snapshot schema.",
            "navigationSnapshot.schemaVersion",
        )
    _stable_id(
        item["navigationSnapshotId"],
        "navigationSnapshot.navigationSnapshotId",
        prefix="nss",
    )
    _revision(item["layoutRevision"], "navigationSnapshot.layoutRevision")
    _text(item["compilerVersion"], "navigationSnapshot.compilerVersion")
    _enum(item["actorClass"], _ACTOR_CLASSES, "navigationSnapshot.actorClass")
    _revision(
        item["actorProfileRevision"],
        "navigationSnapshot.actorProfileRevision",
    )
    walkable = _array(
        item["walkableRegions"],
        "navigationSnapshot.walkableRegions",
        maximum=FACILITY_NAVIGATION_LIMITS["snapshotWalkableRegions"],
    )
    obstacles = _array(
        item["obstacleRecords"],
        "navigationSnapshot.obstacleRecords",
        maximum=FACILITY_NAVIGATION_LIMITS["snapshotObstacleRecords"],
    )
    nodes = _array(
        item["nodes"],
        "navigationSnapshot.nodes",
        maximum=FACILITY_NAVIGATION_LIMITS["snapshotNodes"],
    )
    edges = _array(
        item["edges"],
        "navigationSnapshot.edges",
        maximum=FACILITY_NAVIGATION_LIMITS["snapshotEdges"],
    )
    components = _array(
        item["connectedComponents"],
        "navigationSnapshot.connectedComponents",
        maximum=FACILITY_NAVIGATION_LIMITS["snapshotComponents"],
    )
    walkable_ids = set()
    for index, raw in enumerate(walkable):
        path = f"navigationSnapshot.walkableRegions[{index}]"
        record = _mapping(raw, path)
        _closed(
            record,
            {"walkableRegionId", "geometryFingerprint", "sourceRefIds"},
            path,
        )
        region_id = _stable_id(record["walkableRegionId"], f"{path}.walkableRegionId")
        if region_id in walkable_ids:
            _fail("facility_navigation_duplicate_id", "Walkable region IDs must be unique.", path)
        walkable_ids.add(region_id)
        _revision(record["geometryFingerprint"], f"{path}.geometryFingerprint")
        _id_array(
            record["sourceRefIds"],
            f"{path}.sourceRefIds",
            maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
        )
    obstacle_ids = set()
    for index, raw in enumerate(obstacles):
        path = f"navigationSnapshot.obstacleRecords[{index}]"
        record = _mapping(raw, path)
        _closed(
            record,
            {"obstacleRecordId", "ownerRef", "role", "geometryFingerprint", "evidenceStatus"},
            path,
            optional={"serviceAnchorId"},
        )
        obstacle_id = _stable_id(record["obstacleRecordId"], f"{path}.obstacleRecordId")
        if obstacle_id in obstacle_ids:
            _fail("facility_navigation_duplicate_id", "Obstacle record IDs must be unique.", path)
        obstacle_ids.add(obstacle_id)
        _source_ref(record["ownerRef"], f"{path}.ownerRef")
        role = _enum(
            record["role"],
            frozenset({"barrier", "ordinary_obstacle", "service_target", "protected_region", "shell"}),
            f"{path}.role",
        )
        _revision(record["geometryFingerprint"], f"{path}.geometryFingerprint")
        _enum(record["evidenceStatus"], _EVIDENCE_STATUSES, f"{path}.evidenceStatus")
        if role == "barrier" and "serviceAnchorId" in record:
            _fail(
                "facility_navigation_barrier_service_forbidden",
                "Barrier records subtract from free space but cannot receive service anchors.",
                f"{path}.serviceAnchorId",
            )
        if "serviceAnchorId" in record:
            _stable_id(record["serviceAnchorId"], f"{path}.serviceAnchorId", prefix="na")
    node_ids = set()
    for index, raw in enumerate(nodes):
        path = f"navigationSnapshot.nodes[{index}]"
        node = _mapping(raw, path)
        _closed(node, {"nodeId", "nodeKind", "position"}, path, optional={"ownerRefId"})
        node_id = _stable_id(node["nodeId"], f"{path}.nodeId")
        if node_id in node_ids:
            _fail("facility_navigation_duplicate_id", "Snapshot node IDs must be unique.", path)
        node_ids.add(node_id)
        _enum(
            node["nodeKind"],
            frozenset({"anchor", "connector", "visibility", "navmesh", "lane"}),
            f"{path}.nodeKind",
        )
        _point(node["position"], f"{path}.position")
        if "ownerRefId" in node:
            _stable_id(node["ownerRefId"], f"{path}.ownerRefId")
    edge_ids = set()
    for index, raw in enumerate(edges):
        path = f"navigationSnapshot.edges[{index}]"
        edge = _mapping(raw, path)
        _closed(
            edge,
            {"edgeId", "sourceNodeId", "targetNodeId", "direction", "costMeters", "evidenceStatus"},
            path,
            optional={"derivationKind", "sourceRefIds"},
        )
        edge_id = _stable_id(edge["edgeId"], f"{path}.edgeId")
        if edge_id in edge_ids:
            _fail("facility_navigation_duplicate_id", "Snapshot edge IDs must be unique.", path)
        edge_ids.add(edge_id)
        source = _stable_id(edge["sourceNodeId"], f"{path}.sourceNodeId")
        target = _stable_id(edge["targetNodeId"], f"{path}.targetNodeId")
        if source not in node_ids or target not in node_ids:
            _fail(
                "facility_navigation_dangling_identity",
                "Snapshot edge references an unknown node.",
                path,
            )
        _enum(
            edge["direction"],
            frozenset({"forward", "reverse", "bidirectional"}),
            f"{path}.direction",
        )
        if _number(edge["costMeters"], f"{path}.costMeters") < 0:
            _fail("facility_navigation_schema_invalid", "Edge cost cannot be negative.", f"{path}.costMeters")
        _enum(edge["evidenceStatus"], _EVIDENCE_STATUSES, f"{path}.evidenceStatus")
        if "derivationKind" in edge:
            _enum(
                edge["derivationKind"],
                frozenset({
                    "network_segment",
                    "attachment_connector",
                    "navmesh_adjacency",
                    "free_space_connector",
                }),
                f"{path}.derivationKind",
            )
        if "sourceRefIds" in edge:
            _id_array(
                edge["sourceRefIds"],
                f"{path}.sourceRefIds",
                maximum=FACILITY_NAVIGATION_LIMITS["referencesPerProgram"],
            )
    component_ids = set()
    member_nodes = set()
    for index, raw in enumerate(components):
        path = f"navigationSnapshot.connectedComponents[{index}]"
        component = _mapping(raw, path)
        _closed(component, {"componentId", "nodeIds"}, path)
        component_id = _stable_id(component["componentId"], f"{path}.componentId")
        if component_id in component_ids:
            _fail("facility_navigation_duplicate_id", "Component IDs must be unique.", path)
        component_ids.add(component_id)
        members = set(_id_array(
            component["nodeIds"],
            f"{path}.nodeIds",
            maximum=FACILITY_NAVIGATION_LIMITS["snapshotNodes"],
        ))
        if not members.issubset(node_ids) or member_nodes & members:
            _fail(
                "facility_navigation_component_invalid",
                "Snapshot components must contain known, non-duplicated nodes.",
                path,
            )
        member_nodes.update(members)
    if member_nodes != node_ids:
        _fail(
            "facility_navigation_component_invalid",
            "Every snapshot node must belong to exactly one component.",
            "navigationSnapshot.connectedComponents",
        )
    _source_revisions(item["sourceRevisions"], "navigationSnapshot.sourceRevisions")
    _revision(
        item["geometryContextFingerprint"],
        "navigationSnapshot.geometryContextFingerprint",
    )
    _revision(item["snapshotFingerprint"], "navigationSnapshot.snapshotFingerprint")
    if item["qualification"] != FACILITY_NAVIGATION_SNAPSHOT_QUALIFICATION:
        _fail(
            "facility_navigation_qualification_invalid",
            "The mandatory navigation snapshot qualification changed.",
            "navigationSnapshot.qualification",
        )
    return json.loads(_canonical_bytes(item).decode("ascii"))


def _canonicalize_snapshot_lists(snapshot: dict[str, Any]) -> None:
    for region in snapshot["walkableRegions"]:
        region["sourceRefIds"] = sorted(region["sourceRefIds"])
    snapshot["walkableRegions"].sort(key=lambda item: item["walkableRegionId"])
    snapshot["obstacleRecords"].sort(key=lambda item: item["obstacleRecordId"])
    for node in snapshot["nodes"]:
        node["position"] = _point(node["position"], "navigationSnapshot.nodes.position")
    snapshot["nodes"].sort(key=lambda item: item["nodeId"])
    snapshot["edges"].sort(key=lambda item: item["edgeId"])
    for edge in snapshot["edges"]:
        if "sourceRefIds" in edge:
            edge["sourceRefIds"] = sorted(edge["sourceRefIds"])
    for component in snapshot["connectedComponents"]:
        component["nodeIds"] = sorted(component["nodeIds"])
    snapshot["connectedComponents"].sort(key=lambda item: item["componentId"])
    snapshot["sourceRevisions"] = dict(sorted(snapshot["sourceRevisions"].items()))


def seal_navigation_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(dict(value))
    snapshot["schemaVersion"] = FACILITY_NAVIGATION_SNAPSHOT_SCHEMA
    snapshot["qualification"] = FACILITY_NAVIGATION_SNAPSHOT_QUALIFICATION
    snapshot.pop("navigationSnapshotId", None)
    snapshot.pop("snapshotFingerprint", None)
    _canonicalize_snapshot_lists(snapshot)
    fingerprint = _fingerprint(snapshot)
    snapshot["snapshotFingerprint"] = fingerprint
    snapshot["navigationSnapshotId"] = f"nss-{fingerprint[:24]}"
    return validate_navigation_snapshot(snapshot)


def validate_navigation_snapshot(value: Any) -> dict[str, Any]:
    snapshot = _validate_snapshot_shape(value)
    identity = deepcopy(snapshot)
    snapshot_id = identity.pop("navigationSnapshotId")
    fingerprint = identity.pop("snapshotFingerprint")
    expected = _fingerprint(identity)
    if fingerprint != expected or snapshot_id != f"nss-{expected[:24]}":
        _fail(
            "facility_navigation_snapshot_identity_mismatch",
            "Snapshot identity does not match canonical content.",
            "navigationSnapshot.navigationSnapshotId",
        )
    canonical_size = len(_canonical_bytes(snapshot))
    if canonical_size > FACILITY_NAVIGATION_LIMITS["canonicalSnapshotBytes"]:
        _fail(
            "facility_navigation_resource_limit_exceeded",
            "Navigation snapshot exceeds its canonical byte ceiling.",
            "navigationSnapshot",
            canonicalBytes=canonical_size,
            maximumCanonicalBytes=FACILITY_NAVIGATION_LIMITS["canonicalSnapshotBytes"],
        )
    return snapshot


def _validate_journey_shape(value: Any) -> dict[str, Any]:
    item = _mapping(value, "journeySolution")
    fields = {
        "schemaVersion",
        "journeySolutionId",
        "movementProgramId",
        "navigationSnapshotId",
        "actorPlacementId",
        "generationLayoutRevision",
        "validationContextFingerprint",
        "outcome",
        "orderedAnchorIds",
        "networkEdgeIds",
        "centerline",
        "poses",
        "distanceMeters",
        "turnCount",
        "reverseUsed",
        "validation",
        "sourceRevisions",
        "plannerVersions",
        "solutionFingerprint",
        "qualification",
    }
    _closed(item, fields, "journeySolution")
    if item["schemaVersion"] != FACILITY_NAVIGATION_JOURNEY_SCHEMA:
        _fail(
            "facility_navigation_schema_unsupported",
            "Unsupported journey solution schema.",
            "journeySolution.schemaVersion",
        )
    _stable_id(item["journeySolutionId"], "journeySolution.journeySolutionId", prefix="njs")
    _stable_id(item["movementProgramId"], "journeySolution.movementProgramId", prefix="nmp")
    _stable_id(item["navigationSnapshotId"], "journeySolution.navigationSnapshotId", prefix="nss")
    _stable_id(item["actorPlacementId"], "journeySolution.actorPlacementId")
    _revision(item["generationLayoutRevision"], "journeySolution.generationLayoutRevision")
    _revision(
        item["validationContextFingerprint"],
        "journeySolution.validationContextFingerprint",
    )
    outcome = _enum(
        item["outcome"],
        frozenset({
            "accepted",
            "unreachable",
            "constraint_conflict",
            "physical_validation_refused",
            "authority_missing",
            "stale",
            "resource_refused",
        }),
        "journeySolution.outcome",
    )
    ordered_anchors = _id_array(
        item["orderedAnchorIds"],
        "journeySolution.orderedAnchorIds",
        maximum=FACILITY_NAVIGATION_LIMITS["journeyOrderedAnchors"],
        ordered=True,
        allow_repeats=True,
    )
    network_edges = _id_array(
        item["networkEdgeIds"],
        "journeySolution.networkEdgeIds",
        maximum=FACILITY_NAVIGATION_LIMITS["journeyNetworkEdges"],
        ordered=True,
    )
    centerline = _array(
        item["centerline"],
        "journeySolution.centerline",
        maximum=FACILITY_NAVIGATION_LIMITS["journeyCenterlinePoints"],
    )
    for index, point in enumerate(centerline):
        _point(point, f"journeySolution.centerline[{index}]")
    poses = _array(
        item["poses"],
        "journeySolution.poses",
        maximum=FACILITY_NAVIGATION_LIMITS["journeyPoses"],
    )
    for index, raw in enumerate(poses):
        path = f"journeySolution.poses[{index}]"
        pose = _mapping(raw, path)
        _closed(pose, {"x", "z", "heading", "gear"}, path)
        _number(pose["x"], f"{path}.x")
        _number(pose["z"], f"{path}.z")
        _number(pose["heading"], f"{path}.heading")
        _enum(pose["gear"], frozenset({"forward", "reverse"}), f"{path}.gear")
    distance = _number(item["distanceMeters"], "journeySolution.distanceMeters")
    turn_count = item["turnCount"]
    if distance < 0 or isinstance(turn_count, bool) or not isinstance(turn_count, int) or turn_count < 0:
        _fail(
            "facility_navigation_schema_invalid",
            "Journey distance and turn count must be non-negative.",
            "journeySolution",
        )
    if not isinstance(item["reverseUsed"], bool):
        _fail(
            "facility_navigation_schema_invalid",
            "Journey reverseUsed must be boolean.",
            "journeySolution.reverseUsed",
        )
    validation = _mapping(item["validation"], "journeySolution.validation")
    validation_fields = {"identity", "topology", "direction", "physical", "authority", "stale"}
    _closed(validation, validation_fields, "journeySolution.validation")
    statuses = frozenset({"pass", "refused", "unknown", "not_applicable"})
    for field in sorted(validation_fields):
        _enum(validation[field], statuses, f"journeySolution.validation.{field}")
    _source_revisions(item["sourceRevisions"], "journeySolution.sourceRevisions")
    planners = _mapping(item["plannerVersions"], "journeySolution.plannerVersions")
    if not planners or len(planners) > 16:
        _fail(
            "facility_navigation_schema_invalid",
            "Journey plannerVersions require between 1 and 16 entries.",
            "journeySolution.plannerVersions",
        )
    for key, version in planners.items():
        _stable_id(key, f"journeySolution.plannerVersions.{key}")
        _text(version, f"journeySolution.plannerVersions.{key}")
    _revision(item["solutionFingerprint"], "journeySolution.solutionFingerprint")
    if item["qualification"] != FACILITY_NAVIGATION_JOURNEY_QUALIFICATION:
        _fail(
            "facility_navigation_qualification_invalid",
            "The mandatory journey qualification changed.",
            "journeySolution.qualification",
        )
    replayable = outcome in {"accepted", "physical_validation_refused"}
    if replayable:
        if len(centerline) < 2 or not poses or not ordered_anchors:
            _fail(
                "facility_navigation_schema_invalid",
                "Replayable journey outcomes require anchors, centerline, and poses.",
                "journeySolution",
            )
    elif centerline or poses or network_edges or distance != 0:
        _fail(
            "facility_navigation_outcome_inconsistent",
            "This journey outcome cannot carry route geometry.",
            "journeySolution.outcome",
        )
    return json.loads(_canonical_bytes(item).decode("ascii"))


def _canonicalize_journey_lists(journey: dict[str, Any]) -> None:
    journey["centerline"] = [
        _point(point, "journeySolution.centerline") for point in journey["centerline"]
    ]
    journey["poses"] = [
        {
            "x": round(float(pose["x"]), FACILITY_NAVIGATION_GEOMETRY_PRECISION),
            "z": round(float(pose["z"]), FACILITY_NAVIGATION_GEOMETRY_PRECISION),
            "heading": round(float(pose["heading"]), 9),
            "gear": pose["gear"],
        }
        for pose in journey["poses"]
    ]
    journey["distanceMeters"] = round(
        float(journey["distanceMeters"]),
        FACILITY_NAVIGATION_GEOMETRY_PRECISION,
    )
    journey["sourceRevisions"] = dict(sorted(journey["sourceRevisions"].items()))
    journey["plannerVersions"] = dict(sorted(journey["plannerVersions"].items()))


def seal_journey_solution(value: Mapping[str, Any]) -> dict[str, Any]:
    journey = deepcopy(dict(value))
    journey["schemaVersion"] = FACILITY_NAVIGATION_JOURNEY_SCHEMA
    journey["qualification"] = FACILITY_NAVIGATION_JOURNEY_QUALIFICATION
    journey.pop("journeySolutionId", None)
    journey.pop("solutionFingerprint", None)
    _canonicalize_journey_lists(journey)
    fingerprint = _fingerprint(journey)
    journey["solutionFingerprint"] = fingerprint
    journey["journeySolutionId"] = f"njs-{fingerprint[:24]}"
    return validate_journey_solution(journey)


def validate_journey_solution(value: Any) -> dict[str, Any]:
    journey = _validate_journey_shape(value)
    identity = deepcopy(journey)
    journey_id = identity.pop("journeySolutionId")
    fingerprint = identity.pop("solutionFingerprint")
    expected = _fingerprint(identity)
    if fingerprint != expected or journey_id != f"njs-{expected[:24]}":
        _fail(
            "facility_navigation_journey_identity_mismatch",
            "Journey identity does not match canonical content.",
            "journeySolution.journeySolutionId",
        )
    canonical_size = len(_canonical_bytes(journey))
    if canonical_size > FACILITY_NAVIGATION_LIMITS["canonicalJourneyBytes"]:
        _fail(
            "facility_navigation_resource_limit_exceeded",
            "Journey solution exceeds its canonical byte ceiling.",
            "journeySolution",
            canonicalBytes=canonical_size,
            maximumCanonicalBytes=FACILITY_NAVIGATION_LIMITS["canonicalJourneyBytes"],
        )
    return journey


def validate_navigation_alternative_budget(count: Any) -> int:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        _fail(
            "facility_navigation_schema_invalid",
            "Candidate alternative count must be a non-negative integer.",
            "candidateAlternativeCount",
        )
    maximum = FACILITY_NAVIGATION_LIMITS["candidateAlternatives"]
    if count > maximum:
        _fail(
            "facility_navigation_resource_limit_exceeded",
            "Candidate alternatives exceed the pre-allocation limit.",
            "candidateAlternativeCount",
            maximumItems=maximum,
            actualItems=count,
        )
    return count


def navigation_field_mapping_matrix() -> list[dict[str, str]]:
    """Declare one owner for every behavior-bearing NAV1 field."""

    rows = [
        ("anchor.identity", "facilityNavigation.anchors", "new durable intent", "stable reference only"),
        ("anchor.owner", "facilityNavigation.anchors", "placement/zone/route/marking/process binding", "reference existing ID"),
        ("anchor.position", "facilityNavigation.anchors", "zone anchor, route endpoint, marking, connector, or Plan click", "reference source; only UI stores local coordinates"),
        ("anchor.service_side", "asset connector or reviewed anchor", "asset-definition connector", "reference connector; never infer from proximity"),
        ("movement.actor", "facilityNavigation.movementPrograms", "placements", "reference existing placement; never clone"),
        ("movement.profile", "facilityNavigation.movementPrograms", "published actor/vehicle profile", "bind exact profile revision"),
        ("movement.stop_order", "facilityNavigation.movementPrograms", "authored process intent", "preserve orderedStops exactly"),
        ("movement.required_routes", "facilityNavigation.movementPrograms", "routes", "reference route IDs"),
        ("movement.restrictions", "facilityNavigation.movementPrograms", "zones and routes", "reference forbidden IDs"),
        ("manual.geometry", "facilityNavigation.manualPathConstraints", "Plan pointer authoring", "ui_authored polyline only"),
        ("manual.snapping", "facilityNavigation.manualPathConstraints", "anchors/routes/markings", "reference existing IDs"),
        ("handoff.topology", "facilityNavigation.handoffPrograms", "movement programs and FIFO anchors", "reference both participants"),
        ("handoff.material", "facilityNavigation.handoffPrograms", "product/process knowledge", "reference material identity"),
        ("route.infrastructure", "routes", "existing Facility Layout", "do not copy into movement programs"),
        ("route.endpoints", "routes", "existing route endpoints", "reference route ID"),
        ("lane.direction", "motion_lanes.py", "floor markings and routes", "derive, never duplicate"),
        ("crossing.infrastructure", "floorMarkings/routes", "existing crossing marking", "reference marking ID"),
        ("process.binding", "processBindings", "existing Facility Layout", "reference binding ID"),
        ("snapshot.graph", "navigation snapshot store", "derived source projection", "never persist in layout"),
        ("journey.geometry", "journey solution store", "derived snapshot/program result", "fetch by opaque ID"),
        ("playback.presentation", "activity scenario/browser state", "journey solution", "never become process timing"),
    ]
    result = [
        {
            "behaviorField": field,
            "canonicalOwner": owner,
            "existingSource": source,
            "migrationRule": rule,
        }
        for field, owner, source, rule in rows
    ]
    if len({item["behaviorField"] for item in result}) != len(result):
        raise AssertionError("Navigation field ownership must be unique.")
    return result


def navigation_contract_manifest() -> dict[str, Any]:
    """Publish the frozen NAV1 vocabulary without granting release authority."""

    return {
        "schemaVersion": "facility-navigation-nav1-contract-manifest-v1",
        "phase": "NAV1",
        "contractVersion": FACILITY_NAVIGATION_CONTRACT_VERSION,
        "implementationStatus": "prototype_contract_frozen",
        "productionEligible": False,
        "humanApproval": None,
        "durableLayoutExtension": {
            "path": "extensions.facilityNavigation",
            "schemaVersion": FACILITY_NAVIGATION_SCHEMA_VERSION,
            "participatesInCanonicalLayoutRevision": True,
            "collections": [
                "anchors",
                "movementPrograms",
                "manualPathConstraints",
                "handoffPrograms",
            ],
            "computedRoutePersistenceAllowed": False,
        },
        "derivedArtifacts": {
            "navigationSnapshotSchema": FACILITY_NAVIGATION_SNAPSHOT_SCHEMA,
            "journeySolutionSchema": FACILITY_NAVIGATION_JOURNEY_SCHEMA,
            "persistedAsFacilityTruth": False,
        },
        "vocabulary": {
            "anchorKinds": sorted(_ANCHOR_KINDS),
            "interactionKinds": sorted(_INTERACTION_KINDS),
            "actorClasses": sorted(_ACTOR_CLASSES),
            "positionAuthorities": sorted(_POSITION_AUTHORITIES),
            "evidenceStatuses": sorted(_EVIDENCE_STATUSES),
            "reviewStatuses": sorted(_REVIEW_STATUSES),
            "loopModes": sorted(_LOOP_MODES),
            "constraintModes": sorted(_CONSTRAINT_MODES),
            "constraintDirections": sorted(_CONSTRAINT_DIRECTIONS),
            "ownerKinds": sorted(_OWNER_KINDS),
            "derivedPositionSourceKinds": sorted(_DERIVED_SOURCE_KINDS),
            "timingAuthorities": sorted(_TIMING_AUTHORITIES),
            "sequencePolicies": sorted(_SEQUENCE_POLICIES),
            "writerKinds": sorted(_WRITER_KINDS),
            "obstacleRoles": [
                "barrier",
                "ordinary_obstacle",
                "protected_region",
                "service_target",
                "shell",
            ],
        },
        "authorityRules": {
            "manualCoordinates": "ui_authored_only",
            "generatorMayConfirm": False,
            "generatorMayAuthor": False,
            "generatorMayEmitControlledSource": False,
            "inferredPromotion": "user_or_controlled_import_only",
            "barrierMayReceiveServiceAnchor": False,
        },
        "canonicalization": {
            "geometryPrecisionDecimals": FACILITY_NAVIGATION_GEOMETRY_PRECISION,
            "stableIds": True,
            "sortedIdentityCollections": True,
            "computationalEpsilon": FACILITY_NAVIGATION_COMPUTATIONAL_EPSILON,
            "influenceMarginMeters": FACILITY_NAVIGATION_INFLUENCE_MARGIN_METERS,
            "epsilonIsEngineeringClearance": False,
        },
        "resourceLimits": dict(sorted(FACILITY_NAVIGATION_LIMITS.items())),
        "sageContract": navigation_sage_contract(),
        "motionCompatibility": {
            "v1": {
                "schemaVersion": "facility-motion-package-v1",
                "staleGate": "full_layout_revision",
            },
            "v2": {
                "schemaVersion": "facility-motion-package-v2",
                "generationRevisionField": "generationLayoutRevision",
                "staleGate": "recomputed_validation_context_fingerprint",
                "missingContextBehavior": "refuse_before_first_frame",
            },
        },
    }


def navigation_sage_contract() -> dict[str, Any]:
    """Return the coordinate-free schema exposed to Sage."""

    result = {
        "schemaVersion": "facility-navigation-sage-contract-v1",
        "allowedIntent": {
            "actorPlacementId": "existing placement ID",
            "actorClass": sorted(_ACTOR_CLASSES),
            "orderedAnchorIds": "existing navigation anchor IDs in user order",
            "loopMode": sorted(_LOOP_MODES),
            "requiredRouteIds": "existing route IDs",
            "forbiddenZoneIds": "existing zone IDs",
            "forbiddenRouteIds": "existing route IDs",
            "manualPathConstraintIds": "existing UI-authored constraint IDs",
            "handoffProgramIds": "existing handoff IDs",
        },
        "readOnlyDerivedReferences": {
            "navigationSnapshotId": "opaque server artifact ID",
            "journeySolutionId": "opaque server artifact ID",
            "validationContextFingerprint": "revision identity only",
        },
        "authority": {
            "generatorEvidenceStatuses": ["derived", "inferred", "unknown"],
            "generatorReviewStatus": "pending",
            "directPathAuthoring": "ui_only",
            "controlledOrHumanAuthority": "not_grantable_by_sage",
        },
        "forbiddenInputFields": [
            "localPosition",
            "derivedPosition",
            "authoredPolyline",
            "position",
            "poses",
            "centerline",
            "worldCoordinates",
            "screenCoordinates",
        ],
        "resourceLimits": {
            "orderedStops": FACILITY_NAVIGATION_LIMITS["orderedStopsPerProgram"],
            "candidateAlternatives": FACILITY_NAVIGATION_LIMITS["candidateAlternatives"],
            "maximumSummaryBytes": FACILITY_NAVIGATION_LIMITS["sageSummaryBytes"],
        },
    }
    if len(_canonical_bytes(result)) > FACILITY_NAVIGATION_LIMITS["sageSummaryBytes"]:
        raise AssertionError("The coordinate-free Sage contract exceeds its budget.")
    return result


def build_navigation_sage_summary(value: Any) -> dict[str, Any]:
    """Build bounded ID-and-semantics context without exposing coordinates."""

    extension = _mapping(value, "facilityNavigation")
    collections = (
        ("anchors", "navigationAnchorId", ("anchorKind", "interactionKind", "positionAuthority", "reviewStatus")),
        ("movementPrograms", "movementProgramId", ("actorPlacementId", "actorClass", "loopMode", "reviewStatus")),
        ("manualPathConstraints", "manualPathConstraintId", ("movementProgramId", "constraintMode", "direction", "reviewStatus")),
        ("handoffPrograms", "handoffProgramId", ("sourceMovementProgramId", "targetMovementProgramId", "sequencePolicy", "timingAuthority", "reviewStatus")),
    )
    summary: dict[str, Any] = {
        "schemaVersion": "facility-navigation-sage-summary-v1",
        "extensionRevision": _fingerprint(extension),
        "counts": {},
        "records": {},
        "truncated": {},
        "qualification": (
            "IDs and semantic constraints only; dense geometry and authored path points are excluded."
        ),
    }
    remaining_records = 48
    for collection, identity_field, fields in collections:
        records = extension.get(collection, [])
        if not isinstance(records, list):
            records = []
        summary["counts"][collection] = len(records)
        take = min(len(records), remaining_records)
        selected = []
        for raw in sorted(
            (item for item in records if isinstance(item, Mapping)),
            key=lambda item: str(item.get(identity_field) or ""),
        )[:take]:
            record = {identity_field: raw.get(identity_field)}
            record.update({field: raw.get(field) for field in fields})
            selected.append(record)
        summary["records"][collection] = selected
        summary["truncated"][collection] = max(0, len(records) - take)
        remaining_records -= take
    payload_size = len(_canonical_bytes(summary))
    if payload_size > FACILITY_NAVIGATION_LIMITS["sageSummaryBytes"]:
        _fail(
            "facility_navigation_sage_summary_too_large",
            "Bounded Sage navigation context exceeds its byte budget.",
            "navigationSummary",
            canonicalBytes=payload_size,
            maximumCanonicalBytes=FACILITY_NAVIGATION_LIMITS["sageSummaryBytes"],
        )
    summary["canonicalBytes"] = payload_size
    summary["estimatedTokensBytes4"] = (payload_size + 3) // 4
    return summary


__all__ = [
    "FACILITY_NAVIGATION_COMPUTATIONAL_EPSILON",
    "FACILITY_NAVIGATION_CONTRACT_VERSION",
    "FACILITY_NAVIGATION_GEOMETRY_PRECISION",
    "FACILITY_NAVIGATION_INFLUENCE_MARGIN_METERS",
    "FACILITY_NAVIGATION_JOURNEY_QUALIFICATION",
    "FACILITY_NAVIGATION_JOURNEY_SCHEMA",
    "FACILITY_NAVIGATION_LIMITS",
    "FACILITY_NAVIGATION_SCHEMA_VERSION",
    "FACILITY_NAVIGATION_SNAPSHOT_QUALIFICATION",
    "FACILITY_NAVIGATION_SNAPSHOT_SCHEMA",
    "FacilityNavigationContractError",
    "NavigationIdentityIndex",
    "build_navigation_sage_summary",
    "canonical_facility_navigation_extension_bytes",
    "canonicalize_facility_navigation_extension",
    "facility_navigation_extension_revision",
    "navigation_field_mapping_matrix",
    "navigation_contract_manifest",
    "navigation_identity_index",
    "navigation_sage_contract",
    "navigation_stable_id",
    "seal_journey_solution",
    "seal_navigation_snapshot",
    "validate_facility_navigation_extension",
    "validate_journey_solution",
    "validate_navigation_alternative_budget",
    "validate_navigation_snapshot",
    "validate_navigation_writer_authority",
]
