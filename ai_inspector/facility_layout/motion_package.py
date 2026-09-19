"""Revision-bound, read-only Facility Layout motion playback packages."""

from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from threading import RLock
import time
from typing import Any, Callable, Mapping, Sequence

from .errors import FacilityNotFoundError, FacilityValidationError
from .motion_validation_context import (
    motion_validation_context_fingerprint,
    validate_motion_package_playback_context,
    validate_motion_validation_context_spec,
)
from .routing import ROUTER_VERSION, ROUTING_ENGINE_VERSION


FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1 = "facility-motion-package-v1"
FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2 = "facility-motion-package-v2"
FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3 = "facility-motion-package-v3"
# Compatibility alias. Existing builders remain v1 unless v2 is requested explicitly.
FACILITY_MOTION_PACKAGE_SCHEMA_VERSION = FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1
FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES = 8 * 1024 * 1024
FACILITY_MOTION_PACKAGE_STORE_TTL_SECONDS = 1800.0
FACILITY_MOTION_PACKAGE_STORE_MAXIMUM_ENTRIES = 64
FACILITY_MOTION_QUALIFICATION = (
    "Replays one deterministically planned traversal against nominal geometry "
    "at an exact vehicle revision. It does not establish throughput, "
    "congestion, traffic safety, or regulatory compliance."
)
FACILITY_NAVIGATION_MOTION_QUALIFICATION = (
    "Replays one accepted revision-bound navigation journey for an existing "
    "placed actor on a shared display clock. Presentation timing is not process "
    "timing and does not establish throughput, congestion, staffing, traffic "
    "safety, or regulatory compliance."
)


class FacilityMotionPackageError(FacilityValidationError):
    """Stable validation error for motion package construction and playback."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise FacilityMotionPackageError(
            "facility_motion_package_invalid_json",
            "Facility motion data must be finite JSON-compatible data.",
        ) from exc


def _detached(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("ascii"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _fail(code: str, message: str, path: str) -> None:
    raise FacilityMotionPackageError(code, message, details={"path": path})


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(
            "facility_motion_package_schema_invalid",
            "Expected an object.",
            path,
        )
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    path: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required - optional)
    if missing:
        _fail(
            "facility_motion_package_schema_invalid",
            f"Missing required fields: {', '.join(missing)}.",
            path,
        )
    if unknown:
        _fail(
            "facility_motion_package_unknown_field",
            f"Unknown fields: {', '.join(unknown)}.",
            path,
        )


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(
            "facility_motion_package_schema_invalid",
            "Expected a non-empty string.",
            path,
        )
    return value


def _number(value: Any, path: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(
            "facility_motion_package_schema_invalid",
            "Expected a finite number.",
            path,
        )
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        _fail(
            "facility_motion_package_schema_invalid",
            "Expected a finite number in the supported range.",
            path,
        )
    return result


def _pose(value: Any, path: str) -> None:
    pose = _mapping(value, path)
    _exact_keys(pose, {"x", "z", "heading", "gear"}, path)
    _number(pose["x"], f"{path}.x")
    _number(pose["z"], f"{path}.z")
    _number(pose["heading"], f"{path}.heading")
    if pose["gear"] not in {"forward", "reverse"}:
        _fail(
            "facility_motion_package_schema_invalid",
            "gear must be forward or reverse.",
            f"{path}.gear",
        )


def _pose_series(
    poses: Any,
    cumulative: Any,
    path: str,
) -> None:
    if not isinstance(poses, list) or not poses:
        _fail(
            "facility_motion_package_schema_invalid",
            "A replayable movement requires at least one pose.",
            f"{path}.poses",
        )
    if not isinstance(cumulative, list) or len(cumulative) != len(poses):
        _fail(
            "facility_motion_package_schema_invalid",
            "cumulativeDistance must align one-to-one with poses.",
            f"{path}.cumulativeDistance",
        )
    previous = -math.inf
    for index, pose in enumerate(poses):
        _pose(pose, f"{path}.poses[{index}]")
        distance = _number(
            cumulative[index],
            f"{path}.cumulativeDistance[{index}]",
            minimum=0.0,
        )
        if distance < previous:
            _fail(
                "facility_motion_package_schema_invalid",
                "cumulativeDistance must be monotonic.",
                f"{path}.cumulativeDistance[{index}]",
            )
        previous = distance
    if float(cumulative[0]) != 0.0:
        _fail(
            "facility_motion_package_schema_invalid",
            "cumulativeDistance must begin at zero.",
            f"{path}.cumulativeDistance[0]",
        )


def _vehicle_ref(value: Any, path: str) -> None:
    ref = _mapping(value, path)
    _exact_keys(
        ref,
        {"vehicleProfileId", "vehicleProfileRevision"},
        path,
    )
    _text(ref["vehicleProfileId"], f"{path}.vehicleProfileId")
    _text(ref["vehicleProfileRevision"], f"{path}.vehicleProfileRevision")


def _actor_profile_ref(value: Any, path: str) -> None:
    ref = _mapping(value, path)
    _exact_keys(ref, {"profileKind", "profileId", "profileRevision"}, path)
    if ref["profileKind"] not in {"pedestrian", "vehicle"}:
        _fail(
            "facility_motion_package_schema_invalid",
            "actorProfileRef.profileKind must be pedestrian or vehicle.",
            f"{path}.profileKind",
        )
    _text(ref["profileId"], f"{path}.profileId")
    revision = _text(ref["profileRevision"], f"{path}.profileRevision")
    if len(revision) != 64 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        _fail(
            "facility_motion_package_schema_invalid",
            "actorProfileRef.profileRevision must be a lowercase SHA-256 hash.",
            f"{path}.profileRevision",
        )


def _lane_binding(value: Any, path: str) -> None:
    item = _mapping(value, path)
    _exact_keys(
        item,
        {
            "schemaVersion",
            "bindingVersion",
            "status",
            "travelDirection",
            "routeId",
            "sourceMarkingIds",
            "lateralOffsetMeters",
            "laneCenterline",
            "evidenceStatus",
            "qualification",
        },
        path,
        optional={
            "sourceLateralOffsetMeters",
            "executionAdjustmentMeters",
        },
    )
    if item["schemaVersion"] != 1:
        _fail(
            "facility_motion_package_schema_invalid",
            "Unsupported lane-binding schema.",
            f"{path}.schemaVersion",
        )
    _text(item["bindingVersion"], f"{path}.bindingVersion")
    if item["status"] not in {"direction_markings", "centerline_unmarked"}:
        _fail(
            "facility_motion_package_schema_invalid",
            "Unsupported lane-binding status.",
            f"{path}.status",
        )
    if item["travelDirection"] not in {"forward", "reverse"}:
        _fail(
            "facility_motion_package_schema_invalid",
            "Unsupported lane travel direction.",
            f"{path}.travelDirection",
        )
    _text(item["routeId"], f"{path}.routeId")
    marking_ids = item["sourceMarkingIds"]
    if (
        not isinstance(marking_ids, list)
        or not all(isinstance(marking_id, str) and marking_id for marking_id in marking_ids)
        or marking_ids != sorted(set(marking_ids))
    ):
        _fail(
            "facility_motion_package_schema_invalid",
            "Lane marking IDs must be unique and sorted.",
            f"{path}.sourceMarkingIds",
        )
    _number(item["lateralOffsetMeters"], f"{path}.lateralOffsetMeters")
    has_source_offset = "sourceLateralOffsetMeters" in item
    has_adjustment = "executionAdjustmentMeters" in item
    if has_source_offset != has_adjustment:
        _fail(
            "facility_motion_package_schema_invalid",
            "An adjusted lane requires both source offset and execution adjustment.",
            path,
        )
    if has_source_offset:
        source_offset = _number(
            item["sourceLateralOffsetMeters"],
            f"{path}.sourceLateralOffsetMeters",
        )
        adjustment = _number(
            item["executionAdjustmentMeters"],
            f"{path}.executionAdjustmentMeters",
        )
        if abs(
            source_offset + adjustment - float(item["lateralOffsetMeters"])
        ) > 1.0e-6:
            _fail(
                "facility_motion_package_schema_invalid",
                "The adjusted lane offset does not reconcile with its source offset.",
                path,
            )
    centerline = item["laneCenterline"]
    if not isinstance(centerline, list) or len(centerline) < 2:
        _fail(
            "facility_motion_package_schema_invalid",
            "A lane binding requires at least two centerline points.",
            f"{path}.laneCenterline",
        )
    for index, point in enumerate(centerline):
        point_value = _mapping(point, f"{path}.laneCenterline[{index}]")
        _exact_keys(
            point_value,
            {"x", "y", "z"},
            f"{path}.laneCenterline[{index}]",
        )
        for axis in ("x", "y", "z"):
            _number(
                point_value[axis],
                f"{path}.laneCenterline[{index}].{axis}",
            )
    if item["status"] == "direction_markings":
        if not marking_ids or item["evidenceStatus"] != "derived":
            _fail(
                "facility_motion_package_schema_invalid",
                "A marked lane requires derived marking evidence.",
                path,
            )
    elif marking_ids or float(item["lateralOffsetMeters"]) != 0.0:
        _fail(
            "facility_motion_package_schema_invalid",
            "An unmarked centerline cannot claim a lane offset or markings.",
            path,
        )
    if item["evidenceStatus"] not in {"derived", "unknown"}:
        _fail(
            "facility_motion_package_schema_invalid",
            "Unsupported lane evidence status.",
            f"{path}.evidenceStatus",
        )
    _text(item["qualification"], f"{path}.qualification")


def _swept_envelope(value: Any, path: str, *, valid: bool) -> None:
    envelope = _mapping(value, path)
    _exact_keys(
        envelope,
        {
            "valid",
            "sampledPoseCount",
            "projectedSampleCount",
            "sampleSpacingMeters",
            "effectiveWidthMeters",
            "effectiveLengthMeters",
            "sweptEnvelopeRevision",
            "sweptBounds",
            "geometry",
            "findings",
        },
        path,
    )
    if envelope["valid"] is not valid:
        _fail(
            "facility_motion_package_schema_invalid",
            "Swept-envelope validity does not match movement outcome.",
            f"{path}.valid",
        )
    for field in ("sampledPoseCount", "projectedSampleCount"):
        value_at_field = envelope[field]
        if (
            isinstance(value_at_field, bool)
            or not isinstance(value_at_field, int)
            or value_at_field < 1
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                f"{field} must be a positive integer.",
                f"{path}.{field}",
            )
    for field in (
        "sampleSpacingMeters",
        "effectiveWidthMeters",
        "effectiveLengthMeters",
    ):
        _number(envelope[field], f"{path}.{field}", minimum=0.0)
    _text(envelope["sweptEnvelopeRevision"], f"{path}.sweptEnvelopeRevision")
    _mapping(envelope["sweptBounds"], f"{path}.sweptBounds")
    geometry = _mapping(envelope["geometry"], f"{path}.geometry")
    _exact_keys(
        geometry,
        {
            "polygons",
            "ringOrientation",
            "startVertexRule",
            "precisionDecimals",
            "polygonSortKey",
        },
        f"{path}.geometry",
    )
    if not isinstance(geometry["polygons"], list) or not geometry["polygons"]:
        _fail(
            "facility_motion_package_schema_invalid",
            "Swept geometry requires at least one polygon.",
            f"{path}.geometry.polygons",
        )
    if not isinstance(envelope["findings"], list):
        _fail(
            "facility_motion_package_schema_invalid",
            "findings must be an array.",
            f"{path}.findings",
        )


def _clearance(value: Any, path: str) -> None:
    clearance = _mapping(value, path)
    _exact_keys(clearance, {"sampleSpacingMeters", "samples"}, path)
    _number(
        clearance["sampleSpacingMeters"],
        f"{path}.sampleSpacingMeters",
        minimum=0.0,
    )
    if not isinstance(clearance["samples"], list) or not clearance["samples"]:
        _fail(
            "facility_motion_package_schema_invalid",
            "Clearance requires every validated sample.",
            f"{path}.samples",
        )
    previous = -math.inf
    for index, raw in enumerate(clearance["samples"]):
        sample_path = f"{path}.samples[{index}]"
        sample = _mapping(raw, sample_path)
        _exact_keys(
            sample,
            {"distanceMeters", "nearestObstacleIds", "clearanceMeters"},
            sample_path,
        )
        distance = _number(
            sample["distanceMeters"],
            f"{sample_path}.distanceMeters",
            minimum=0.0,
        )
        if distance < previous:
            _fail(
                "facility_motion_package_schema_invalid",
                "Clearance samples must be ordered by distance.",
                f"{sample_path}.distanceMeters",
            )
        previous = distance
        if not isinstance(sample["nearestObstacleIds"], list) or not all(
            isinstance(item, str) and item
            for item in sample["nearestObstacleIds"]
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                "nearestObstacleIds must contain stable IDs.",
                f"{sample_path}.nearestObstacleIds",
            )
        if sample["clearanceMeters"] is not None:
            _number(
                sample["clearanceMeters"],
                f"{sample_path}.clearanceMeters",
                minimum=0.0,
            )


def _blocking(value: Any, path: str) -> None:
    blocking = _mapping(value, path)
    localized = blocking.get("localized")
    if localized is True:
        _exact_keys(
            blocking,
            {
                "localized",
                "blockingSampleIndex",
                "blockingPose",
                "blockingDistanceMeters",
                "blockingObstacleIds",
            },
            path,
        )
        if (
            isinstance(blocking["blockingSampleIndex"], bool)
            or not isinstance(blocking["blockingSampleIndex"], int)
            or blocking["blockingSampleIndex"] < 0
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                "blockingSampleIndex must be a non-negative integer.",
                f"{path}.blockingSampleIndex",
            )
        _pose(blocking["blockingPose"], f"{path}.blockingPose")
        _number(
            blocking["blockingDistanceMeters"],
            f"{path}.blockingDistanceMeters",
            minimum=0.0,
        )
    elif localized is False:
        _exact_keys(blocking, {"localized", "blockingObstacleIds"}, path)
    else:
        _fail(
            "facility_motion_package_schema_invalid",
            "blocking.localized must be a boolean.",
            f"{path}.localized",
        )
    if not isinstance(blocking["blockingObstacleIds"], list) or not all(
        isinstance(item, str) and item for item in blocking["blockingObstacleIds"]
    ):
        _fail(
            "facility_motion_package_schema_invalid",
            "blockingObstacleIds must contain stable IDs.",
            f"{path}.blockingObstacleIds",
        )


def _validate_navigation_motion_package(
    package: Mapping[str, Any],
) -> dict[str, Any]:
    value = _mapping(package, "package")
    _exact_keys(
        value,
        {
            "schemaVersion",
            "packageId",
            "plannerVersions",
            "generationLayoutRevision",
            "validationContextFingerprint",
            "navigationSnapshotId",
            "qualification",
            "movement",
        },
        "package",
    )
    if value["schemaVersion"] != FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3:
        _fail(
            "facility_motion_package_schema_unsupported",
            "Unsupported Facility navigation motion package schema.",
            "package.schemaVersion",
        )
    package_id = _text(value["packageId"], "package.packageId")
    planners = _mapping(value["plannerVersions"], "package.plannerVersions")
    if not planners or len(planners) > 16:
        _fail(
            "facility_motion_package_schema_invalid",
            "Navigation motion plannerVersions require between 1 and 16 entries.",
            "package.plannerVersions",
        )
    for key, version in planners.items():
        _text(key, "package.plannerVersions key")
        _text(version, f"package.plannerVersions.{key}")
    for field in ("generationLayoutRevision", "validationContextFingerprint"):
        revision = _text(value[field], f"package.{field}")
        if len(revision) != 64 or any(
            character not in "0123456789abcdef" for character in revision
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                f"{field} must be a lowercase SHA-256 hash.",
                f"package.{field}",
            )
    _text(value["navigationSnapshotId"], "package.navigationSnapshotId")
    if value["qualification"] != FACILITY_NAVIGATION_MOTION_QUALIFICATION:
        _fail(
            "facility_motion_package_qualification_invalid",
            "The mandatory navigation motion qualification was changed.",
            "package.qualification",
        )
    movement = _mapping(value["movement"], "package.movement")
    _exact_keys(
        movement,
        {
            "outcome",
            "movementId",
            "movementProgramId",
            "journeySolutionId",
            "navigationSnapshotId",
            "actorClass",
            "actorPlacementId",
            "actorProfileRef",
            "presentationDurationSeconds",
            "presentationTimingAuthority",
            "distanceMeters",
            "poses",
            "cumulativeDistance",
            "validation",
            "sourceRevisions",
        },
        "package.movement",
    )
    if movement["outcome"] != "accepted":
        _fail(
            "facility_motion_outcome_invalid",
            "Navigation motion packages serialize accepted journeys only.",
            "package.movement.outcome",
        )
    for field in (
        "movementId",
        "movementProgramId",
        "journeySolutionId",
        "navigationSnapshotId",
        "actorPlacementId",
    ):
        _text(movement[field], f"package.movement.{field}")
    if movement["navigationSnapshotId"] != value["navigationSnapshotId"]:
        _fail(
            "facility_motion_package_schema_invalid",
            "The movement and package navigation snapshot identities differ.",
            "package.movement.navigationSnapshotId",
        )
    if movement["actorClass"] not in {"pedestrian", "vehicle"}:
        _fail(
            "facility_motion_package_schema_invalid",
            "Navigation motion actorClass must be pedestrian or vehicle.",
            "package.movement.actorClass",
        )
    _actor_profile_ref(movement["actorProfileRef"], "package.movement.actorProfileRef")
    if movement["actorProfileRef"]["profileKind"] != movement["actorClass"]:
        _fail(
            "facility_motion_package_schema_invalid",
            "actorProfileRef.profileKind must match actorClass.",
            "package.movement.actorProfileRef.profileKind",
        )
    _number(
        movement["presentationDurationSeconds"],
        "package.movement.presentationDurationSeconds",
        minimum=0.001,
    )
    if movement["presentationTimingAuthority"] not in {
        "derived_display_only",
        "user_authored",
        "controlled_source",
    }:
        _fail(
            "facility_motion_package_schema_invalid",
            "Unsupported presentationTimingAuthority.",
            "package.movement.presentationTimingAuthority",
        )
    distance = _number(
        movement["distanceMeters"],
        "package.movement.distanceMeters",
        minimum=0.0,
    )
    _pose_series(
        movement["poses"],
        movement["cumulativeDistance"],
        "package.movement",
    )
    if not math.isclose(
        float(movement["cumulativeDistance"][-1]),
        distance,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        _fail(
            "facility_motion_package_schema_invalid",
            "The final cumulative distance must equal distanceMeters.",
            "package.movement.cumulativeDistance",
        )
    validation = _mapping(movement["validation"], "package.movement.validation")
    _exact_keys(
        validation,
        {"identity", "topology", "direction", "physical", "authority", "stale"},
        "package.movement.validation",
    )
    for field, status in validation.items():
        if status not in {"pass", "refused", "unknown", "not_applicable"}:
            _fail(
                "facility_motion_package_schema_invalid",
                "Unsupported journey validation status.",
                f"package.movement.validation.{field}",
            )
    revisions = _mapping(
        movement["sourceRevisions"],
        "package.movement.sourceRevisions",
    )
    if not revisions or len(revisions) > 16:
        _fail(
            "facility_motion_package_schema_invalid",
            "sourceRevisions require between 1 and 16 entries.",
            "package.movement.sourceRevisions",
        )
    for key, revision in revisions.items():
        _text(key, "package.movement.sourceRevisions key")
        _text(revision, f"package.movement.sourceRevisions.{key}")
    identity = _detached(value)
    identity.pop("packageId")
    expected_id = f"fmp-{_hash(identity)}"
    if package_id != expected_id:
        _fail(
            "facility_motion_package_id_mismatch",
            "Facility Motion Package ID does not match its canonical content.",
            "package.packageId",
        )
    return _detached(value)


def validate_facility_motion_package(
    package: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a closed v1 or v2 package and return a detached copy."""

    if isinstance(package, Mapping) and package.get("schemaVersion") == (
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3
    ):
        return _validate_navigation_motion_package(package)
    value = _mapping(package, "package")
    schema_version = value.get("schemaVersion")
    if schema_version == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1:
        revision_field = "layoutRevision"
        additional_fields: set[str] = set()
    elif schema_version == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2:
        revision_field = "generationLayoutRevision"
        additional_fields = {
            "validationContextSpec",
            "validationContextFingerprint",
        }
    else:
        _fail(
            "facility_motion_package_schema_unsupported",
            "Unsupported Facility Motion Package schema.",
            "package.schemaVersion",
        )
    _exact_keys(
        value,
        {
            "schemaVersion",
            "packageId",
            "plannerVersions",
            revision_field,
            "obstacleContextRevision",
            "qualification",
            "movement",
        } | additional_fields,
        "package",
    )
    package_id = _text(value["packageId"], "package.packageId")
    versions = _mapping(value["plannerVersions"], "package.plannerVersions")
    _exact_keys(
        versions,
        {"routingEngineVersion", "routerVersion"},
        "package.plannerVersions",
    )
    _text(versions["routingEngineVersion"], "package.plannerVersions.routingEngineVersion")
    _text(versions["routerVersion"], "package.plannerVersions.routerVersion")
    _text(value[revision_field], f"package.{revision_field}")
    _text(value["obstacleContextRevision"], "package.obstacleContextRevision")
    if schema_version == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2:
        validate_motion_validation_context_spec(value["validationContextSpec"])
        fingerprint = _text(
            value["validationContextFingerprint"],
            "package.validationContextFingerprint",
        )
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                "validationContextFingerprint must be a lowercase SHA-256 hash.",
                "package.validationContextFingerprint",
            )
    if value["qualification"] != FACILITY_MOTION_QUALIFICATION:
        _fail(
            "facility_motion_package_qualification_invalid",
            "The mandatory motion qualification was changed.",
            "package.qualification",
        )

    movement = _mapping(value["movement"], "package.movement")
    outcome = movement.get("outcome")
    common = {"outcome", "movementId", "routeId", "vehicleProfileRef"}
    optional = {"vehiclePlacementId", "laneBinding"}
    if outcome == "accepted":
        required = common | {
            "routeFingerprint",
            "plannerDurationEstimateSeconds",
            "distanceMeters",
            "poses",
            "cumulativeDistance",
            "carriedPlacementIds",
            "sweptEnvelope",
            "clearance",
        }
        _exact_keys(movement, required, "package.movement", optional=optional)
        _text(movement["routeFingerprint"], "package.movement.routeFingerprint")
        _number(
            movement["plannerDurationEstimateSeconds"],
            "package.movement.plannerDurationEstimateSeconds",
            minimum=0.0,
        )
        distance = _number(
            movement["distanceMeters"],
            "package.movement.distanceMeters",
            minimum=0.0,
        )
        _pose_series(
            movement["poses"],
            movement["cumulativeDistance"],
            "package.movement",
        )
        if not math.isclose(
            float(movement["cumulativeDistance"][-1]),
            distance,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                "The final cumulative distance must equal distanceMeters.",
                "package.movement.cumulativeDistance",
            )
        if not isinstance(movement["carriedPlacementIds"], list) or not all(
            isinstance(item, str) and item
            for item in movement["carriedPlacementIds"]
        ):
            _fail(
                "facility_motion_package_schema_invalid",
                "carriedPlacementIds must contain stable IDs.",
                "package.movement.carriedPlacementIds",
            )
        if "vehiclePlacementId" not in movement and movement["carriedPlacementIds"]:
            _fail(
                "facility_motion_package_proxy_cannot_carry",
                "A profile-derived proxy cannot carry layout placements.",
                "package.movement.carriedPlacementIds",
            )
        _swept_envelope(
            movement["sweptEnvelope"],
            "package.movement.sweptEnvelope",
            valid=True,
        )
        _clearance(movement["clearance"], "package.movement.clearance")
    elif outcome == "envelope_refused":
        required = common | {
            "attemptFingerprint",
            "attemptedPoses",
            "cumulativeDistance",
            "blocking",
            "sweptEnvelope",
        }
        _exact_keys(movement, required, "package.movement", optional=optional)
        _text(movement["attemptFingerprint"], "package.movement.attemptFingerprint")
        _pose_series(
            movement["attemptedPoses"],
            movement["cumulativeDistance"],
            "package.movement",
        )
        _blocking(movement["blocking"], "package.movement.blocking")
        _swept_envelope(
            movement["sweptEnvelope"],
            "package.movement.sweptEnvelope",
            valid=False,
        )
    elif outcome == "unroutable":
        required = common | {"findings"}
        _exact_keys(
            movement,
            required,
            "package.movement",
            optional={"laneBinding"},
        )
        if not isinstance(movement["findings"], list) or not movement["findings"]:
            _fail(
                "facility_motion_package_schema_invalid",
                "An unroutable movement requires findings.",
                "package.movement.findings",
            )
    else:
        _fail(
            "facility_motion_package_schema_invalid",
            "Unsupported movement outcome.",
            "package.movement.outcome",
        )

    _text(movement["movementId"], "package.movement.movementId")
    _text(movement["routeId"], "package.movement.routeId")
    _vehicle_ref(movement["vehicleProfileRef"], "package.movement.vehicleProfileRef")
    if "laneBinding" in movement:
        _lane_binding(movement["laneBinding"], "package.movement.laneBinding")
        if movement["laneBinding"]["routeId"] != movement["routeId"]:
            _fail(
                "facility_motion_package_schema_invalid",
                "The lane binding must reference the movement route.",
                "package.movement.laneBinding.routeId",
            )
    if "vehiclePlacementId" in movement:
        _text(movement["vehiclePlacementId"], "package.movement.vehiclePlacementId")
    identity = _detached(value)
    identity.pop("packageId")
    expected_id = f"fmp-{_hash(identity)}"
    if package_id != expected_id:
        _fail(
            "facility_motion_package_id_mismatch",
            "Facility Motion Package ID does not match its canonical content.",
            "package.packageId",
        )
    return _detached(value)


def canonical_facility_motion_package_bytes(
    package: Mapping[str, Any],
) -> bytes:
    canonical = validate_facility_motion_package(package)
    payload = _canonical_bytes(canonical)
    if len(payload) > FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES:
        raise FacilityMotionPackageError(
            "facility_motion_package_too_large",
            "The complete motion evidence exceeds the canonical package budget.",
            details={
                "canonicalBytes": len(payload),
                "maximumCanonicalBytes": (
                    FACILITY_MOTION_PACKAGE_MAXIMUM_CANONICAL_BYTES
                ),
            },
        )
    return payload


def _cumulative_distance(
    poses: Sequence[Mapping[str, Any]],
    final_distance_meters: float | None = None,
) -> list[float]:
    result = [0.0]
    for index in range(1, len(poses)):
        previous = poses[index - 1]
        current = poses[index]
        result.append(
            result[-1]
            + math.dist(
                (float(previous["x"]), float(previous["z"])),
                (float(current["x"]), float(current["z"])),
            )
        )
    if final_distance_meters is not None and result[-1] > 0.0:
        scale = float(final_distance_meters) / result[-1]
        result = [item * scale for item in result]
        result[-1] = float(final_distance_meters)
    return [round(item, 6) for item in result]


def _canonical_poses(poses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "x": round(float(pose["x"]), 6),
            "z": round(float(pose["z"]), 6),
            "heading": round(float(pose["heading"]), 9),
            "gear": str(pose.get("gear") or "forward"),
        }
        for pose in poses
    ]


def _swept_package_view(swept: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "valid": swept.get("valid") is True,
        "sampledPoseCount": int(swept["sampledPoseCount"]),
        "projectedSampleCount": int(swept["projectedSampleCount"]),
        "sampleSpacingMeters": swept["sampleSpacingMeters"],
        "effectiveWidthMeters": swept["effectiveWidthMeters"],
        "effectiveLengthMeters": swept["effectiveLengthMeters"],
        "sweptEnvelopeRevision": swept["sweptEnvelopeRevision"],
        "sweptBounds": deepcopy(swept["sweptBounds"]),
        "geometry": deepcopy(swept["geometry"]),
        "findings": deepcopy(swept.get("findings", [])),
    }


def _carried_placement_ids(
    layout: Mapping[str, Any],
    vehicle_placement_id: str | None,
) -> list[str]:
    if vehicle_placement_id is None:
        return []
    placement_ids = {
        str(item.get("placementId"))
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    if vehicle_placement_id not in placement_ids:
        raise FacilityMotionPackageError(
            "facility_motion_vehicle_placement_missing",
            "The selected vehicle placement is not present in this layout revision.",
            details={"vehiclePlacementId": vehicle_placement_id},
        )
    return sorted(
        str(item["placementId"])
        for item in layout.get("placements", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("snapRelationship"), Mapping)
        and item["snapRelationship"].get("supportPlacementId")
        == vehicle_placement_id
        and isinstance(item.get("placementId"), str)
        and item.get("placementId")
    )


def _refused_trajectory(
    route_result: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[float]]:
    poses = _canonical_poses(route_result.get("poses", []))
    if not poses:
        return [], []
    swept = _mapping(route_result.get("sweptVolume"), "routeResult.sweptVolume")
    blocking = _mapping(swept.get("blocking"), "routeResult.sweptVolume.blocking")
    if blocking.get("localized") is not True:
        return poses, _cumulative_distance(poses)
    limit = float(blocking["blockingDistanceMeters"])
    cumulative = _cumulative_distance(poses)
    last_index = bisect_right(cumulative, limit + 1e-9)
    truncated = poses[:last_index]
    distances = cumulative[:last_index]
    blocking_pose = _canonical_poses([blocking["blockingPose"]])[0]
    if not truncated or distances[-1] < limit - 1e-6:
        truncated.append(blocking_pose)
        distances.append(round(limit, 6))
    else:
        truncated[-1] = blocking_pose
        distances[-1] = round(limit, 6)
    return truncated, distances


def build_facility_motion_package(
    route_result: Mapping[str, Any],
    *,
    layout: Mapping[str, Any],
    layout_revision: str,
    obstacle_context_revision: str,
    route_id: str,
    vehicle_profile_ref: Mapping[str, Any],
    vehicle_placement_id: str | None = None,
    lane_binding: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Serialize one planner result without re-planning or re-validating it."""

    layout_revision = _text(layout_revision, "layoutRevision")
    obstacle_context_revision = _text(
        obstacle_context_revision,
        "obstacleContextRevision",
    )
    route_id = _text(route_id, "routeId")
    _vehicle_ref(vehicle_profile_ref, "vehicleProfileRef")
    source_revisions = route_result.get("sourceRevisions")
    if not isinstance(source_revisions, Mapping):
        source_revisions = {}
    if source_revisions.get("layout") != layout_revision:
        raise FacilityMotionPackageError(
            "facility_motion_layout_revision_mismatch",
            "The planner result is not bound to the requested layout revision.",
            details={
                "layoutRevision": layout_revision,
                "plannerLayoutRevision": source_revisions.get("layout"),
            },
        )
    if source_revisions.get("vehicle") != vehicle_profile_ref.get(
        "vehicleProfileRevision"
    ):
        raise FacilityMotionPackageError(
            "facility_motion_vehicle_revision_mismatch",
            "The planner result is not bound to the requested vehicle revision.",
        )

    outcome = route_result.get("outcome")
    if outcome is None:
        outcome = "accepted" if route_result.get("accepted") is True else "unroutable"
    movement_seed = {
        "outcome": outcome,
        "routeId": route_id,
        "routeFingerprint": route_result.get("routeFingerprint"),
        "attemptFingerprint": route_result.get("attemptFingerprint"),
        "vehicleProfileRef": dict(vehicle_profile_ref),
        "vehiclePlacementId": vehicle_placement_id,
        "laneBinding": dict(lane_binding) if lane_binding is not None else None,
    }
    movement_id = f"fmm-{_hash(movement_seed)[:24]}"
    common = {
        "outcome": outcome,
        "movementId": movement_id,
        "routeId": route_id,
        "vehicleProfileRef": _detached(vehicle_profile_ref),
    }
    if vehicle_placement_id is not None and outcome != "unroutable":
        common["vehiclePlacementId"] = _text(
            vehicle_placement_id,
            "vehiclePlacementId",
        )
    if lane_binding is not None:
        lane_value = _detached(lane_binding)
        _lane_binding(lane_value, "laneBinding")
        if lane_value["routeId"] != route_id:
            raise FacilityMotionPackageError(
                "facility_motion_lane_route_mismatch",
                "The lane binding does not reference the requested route.",
            )
        common["laneBinding"] = lane_value

    if outcome == "accepted":
        if route_result.get("accepted") is not True or not route_result.get(
            "routeFingerprint"
        ):
            raise FacilityMotionPackageError(
                "facility_motion_outcome_inconsistent",
                "An accepted movement requires an accepted planner result.",
            )
        poses = _canonical_poses(route_result.get("poses", []))
        cumulative = _cumulative_distance(
            poses,
            float(route_result["distanceMeters"]),
        )
        swept = _mapping(route_result.get("sweptVolume"), "routeResult.sweptVolume")
        movement = {
            **common,
            "routeFingerprint": str(route_result["routeFingerprint"]),
            "plannerDurationEstimateSeconds": route_result[
                "estimatedTravelSeconds"
            ],
            "distanceMeters": route_result["distanceMeters"],
            "poses": poses,
            "cumulativeDistance": cumulative,
            "carriedPlacementIds": _carried_placement_ids(
                layout,
                vehicle_placement_id,
            ),
            "sweptEnvelope": _swept_package_view(swept),
            "clearance": deepcopy(swept["clearance"]),
        }
    elif outcome == "envelope_refused":
        if route_result.get("accepted") is not False or not route_result.get(
            "attemptFingerprint"
        ):
            raise FacilityMotionPackageError(
                "facility_motion_outcome_inconsistent",
                "An envelope refusal requires a domain-separated attempt fingerprint.",
            )
        poses, cumulative = _refused_trajectory(route_result)
        if not poses:
            raise FacilityMotionPackageError(
                "facility_motion_outcome_inconsistent",
                "An envelope refusal requires a localized attempted trajectory.",
            )
        swept = _mapping(route_result.get("sweptVolume"), "routeResult.sweptVolume")
        movement = {
            **common,
            "attemptFingerprint": str(route_result["attemptFingerprint"]),
            "attemptedPoses": poses,
            "cumulativeDistance": cumulative,
            "blocking": deepcopy(swept["blocking"]),
            "sweptEnvelope": _swept_package_view(swept),
        }
    elif outcome == "unroutable":
        if route_result.get("accepted") is not False:
            raise FacilityMotionPackageError(
                "facility_motion_outcome_inconsistent",
                "An unroutable movement requires a rejected planner result.",
            )
        if route_result.get("poses") or route_result.get("routeFingerprint") or route_result.get(
            "attemptFingerprint"
        ):
            raise FacilityMotionPackageError(
                "facility_motion_outcome_inconsistent",
                "An unroutable movement cannot carry trajectory evidence.",
            )
        movement = {
            **common,
            "findings": deepcopy(route_result.get("findings", [])),
        }
    else:
        raise FacilityMotionPackageError(
            "facility_motion_outcome_invalid",
            "Unsupported planner movement outcome.",
        )

    package_without_id = {
        "schemaVersion": FACILITY_MOTION_PACKAGE_SCHEMA_VERSION,
        "plannerVersions": {
            "routingEngineVersion": str(
                route_result.get("routingEngineVersion") or ROUTING_ENGINE_VERSION
            ),
            "routerVersion": str(
                route_result.get("routerVersion") or ROUTER_VERSION
            ),
        },
        "layoutRevision": layout_revision,
        "obstacleContextRevision": obstacle_context_revision,
        "qualification": FACILITY_MOTION_QUALIFICATION,
        "movement": movement,
    }
    package = {
        "packageId": f"fmp-{_hash(package_without_id)}",
        **package_without_id,
    }
    canonical = validate_facility_motion_package(package)
    payload = canonical_facility_motion_package_bytes(canonical)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    result = {
        "package": canonical,
        "facilityMotionEnvelope": {
            "packageId": canonical["packageId"],
            "generatedAt": timestamp,
        },
        "canonicalBytes": len(payload),
        "summary": facility_motion_package_summary(canonical),
    }
    return result


def build_facility_motion_package_v2(
    route_result: Mapping[str, Any],
    *,
    layout: Mapping[str, Any],
    layout_revision: str,
    obstacle_context_revision: str,
    route_id: str,
    vehicle_profile_ref: Mapping[str, Any],
    validation_context_spec: Mapping[str, Any],
    validation_context_projection: Mapping[str, Any],
    vehicle_placement_id: str | None = None,
    lane_binding: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Promote one proven v1 movement into the narrow-staleness v2 union."""

    built = build_facility_motion_package(
        route_result,
        layout=layout,
        layout_revision=layout_revision,
        obstacle_context_revision=obstacle_context_revision,
        route_id=route_id,
        vehicle_profile_ref=vehicle_profile_ref,
        vehicle_placement_id=vehicle_placement_id,
        lane_binding=lane_binding,
        generated_at=generated_at,
    )
    v1 = built["package"]
    canonical_spec = validate_motion_validation_context_spec(
        validation_context_spec
    )
    fingerprint = motion_validation_context_fingerprint(
        validation_context_projection
    )
    package_without_id = {
        "schemaVersion": FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
        "plannerVersions": deepcopy(v1["plannerVersions"]),
        "generationLayoutRevision": v1["layoutRevision"],
        "validationContextSpec": canonical_spec,
        "validationContextFingerprint": fingerprint,
        "obstacleContextRevision": v1["obstacleContextRevision"],
        "qualification": v1["qualification"],
        "movement": deepcopy(v1["movement"]),
    }
    package = {
        "packageId": f"fmp-{_hash(package_without_id)}",
        **package_without_id,
    }
    canonical = validate_facility_motion_package(package)
    payload = canonical_facility_motion_package_bytes(canonical)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    return {
        "package": canonical,
        "facilityMotionEnvelope": {
            "packageId": canonical["packageId"],
            "generatedAt": timestamp,
        },
        "canonicalBytes": len(payload),
        "summary": facility_motion_package_summary(canonical),
    }


def build_navigation_journey_motion_package(
    journey: Mapping[str, Any],
    *,
    actor_class: str,
    actor_profile_ref: Mapping[str, Any],
    presentation_duration_seconds: float | None = None,
    presentation_timing_authority: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Serialize one accepted navigation journey without re-planning it."""

    from .navigation_contract import validate_journey_solution

    canonical_journey = validate_journey_solution(journey)
    if canonical_journey["outcome"] != "accepted":
        raise FacilityMotionPackageError(
            "facility_navigation_journey_not_replayable",
            "Only accepted navigation journeys can become motion packages.",
        )
    if actor_class not in {"pedestrian", "vehicle"}:
        raise FacilityMotionPackageError(
            "facility_navigation_actor_class_invalid",
            "Navigation playback requires a pedestrian or vehicle actor.",
        )
    profile_ref = _detached(actor_profile_ref)
    _actor_profile_ref(profile_ref, "actorProfileRef")
    if profile_ref["profileKind"] != actor_class:
        raise FacilityMotionPackageError(
            "facility_navigation_actor_profile_mismatch",
            "The actor profile kind does not match the navigation actor class.",
        )
    distance = float(canonical_journey["distanceMeters"])
    if presentation_duration_seconds is None:
        duration = max(4.0, min(120.0, distance))
        timing_authority = "derived_display_only"
    else:
        duration = _number(
            presentation_duration_seconds,
            "presentationDurationSeconds",
            minimum=0.001,
        )
        timing_authority = presentation_timing_authority or "user_authored"
    if timing_authority not in {
        "derived_display_only",
        "user_authored",
        "controlled_source",
    }:
        raise FacilityMotionPackageError(
            "facility_navigation_presentation_timing_authority_invalid",
            "Presentation timing requires an explicit supported authority.",
        )
    poses = _canonical_poses(canonical_journey["poses"])
    cumulative = _cumulative_distance(poses, distance)
    movement_seed = {
        "journeySolutionId": canonical_journey["journeySolutionId"],
        "actorClass": actor_class,
        "actorProfileRef": profile_ref,
        "presentationDurationSeconds": round(float(duration), 6),
        "presentationTimingAuthority": timing_authority,
    }
    movement = {
        "outcome": "accepted",
        "movementId": f"fmm-{_hash(movement_seed)[:24]}",
        "movementProgramId": canonical_journey["movementProgramId"],
        "journeySolutionId": canonical_journey["journeySolutionId"],
        "navigationSnapshotId": canonical_journey["navigationSnapshotId"],
        "actorClass": actor_class,
        "actorPlacementId": canonical_journey["actorPlacementId"],
        "actorProfileRef": profile_ref,
        "presentationDurationSeconds": round(float(duration), 6),
        "presentationTimingAuthority": timing_authority,
        "distanceMeters": distance,
        "poses": poses,
        "cumulativeDistance": cumulative,
        "validation": deepcopy(canonical_journey["validation"]),
        "sourceRevisions": deepcopy(canonical_journey["sourceRevisions"]),
    }
    package_without_id = {
        "schemaVersion": FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3,
        "plannerVersions": {
            **deepcopy(canonical_journey["plannerVersions"]),
            "motion_serializer": FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3,
        },
        "generationLayoutRevision": canonical_journey[
            "generationLayoutRevision"
        ],
        "validationContextFingerprint": canonical_journey[
            "validationContextFingerprint"
        ],
        "navigationSnapshotId": canonical_journey["navigationSnapshotId"],
        "qualification": FACILITY_NAVIGATION_MOTION_QUALIFICATION,
        "movement": movement,
    }
    package = {
        "packageId": f"fmp-{_hash(package_without_id)}",
        **package_without_id,
    }
    canonical = validate_facility_motion_package(package)
    payload = canonical_facility_motion_package_bytes(canonical)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    return {
        "package": canonical,
        "facilityMotionEnvelope": {
            "packageId": canonical["packageId"],
            "generatedAt": timestamp,
        },
        "canonicalBytes": len(payload),
        "summary": facility_motion_package_summary(canonical),
    }


def validate_facility_motion_package_for_playback(
    package: Mapping[str, Any],
    *,
    active_layout_revision: str,
    active_validation_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Validate package identity, then reject stale evidence before playback."""

    canonical = validate_facility_motion_package(package)
    validate_motion_package_playback_context(
        canonical,
        active_layout_revision=active_layout_revision,
        active_validation_context_fingerprint=(
            active_validation_context_fingerprint
        ),
    )
    return canonical


def facility_motion_package_summary(package: Mapping[str, Any]) -> dict[str, Any]:
    canonical = validate_facility_motion_package(package)
    movement = canonical["movement"]
    if canonical["schemaVersion"] == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3:
        return {
            "packageId": canonical["packageId"],
            "schemaVersion": canonical["schemaVersion"],
            "outcome": movement["outcome"],
            "movementProgramId": movement["movementProgramId"],
            "journeySolutionId": movement["journeySolutionId"],
            "actorClass": movement["actorClass"],
            "actorPlacementId": movement["actorPlacementId"],
            "distanceMeters": movement["distanceMeters"],
            "presentationDurationSeconds": movement[
                "presentationDurationSeconds"
            ],
            "presentationTimingAuthority": movement[
                "presentationTimingAuthority"
            ],
            "validationContextFingerprint": canonical[
                "validationContextFingerprint"
            ],
            "qualification": FACILITY_NAVIGATION_MOTION_QUALIFICATION,
        }
    summary = {
        "packageId": canonical["packageId"],
        "schemaVersion": canonical["schemaVersion"],
        "outcome": movement["outcome"],
        "routeId": movement["routeId"],
        "vehicleProfileRef": deepcopy(movement["vehicleProfileRef"]),
        "qualification": FACILITY_MOTION_QUALIFICATION,
    }
    if canonical["schemaVersion"] == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2:
        summary["validationContextFingerprint"] = canonical[
            "validationContextFingerprint"
        ]
    if "laneBinding" in movement:
        summary["laneBinding"] = deepcopy(movement["laneBinding"])
    if movement["outcome"] == "accepted":
        summary.update(
            {
                "distanceMeters": movement["distanceMeters"],
                "plannerDurationEstimateSeconds": movement[
                    "plannerDurationEstimateSeconds"
                ],
                "sampleSpacingMeters": movement["clearance"][
                    "sampleSpacingMeters"
                ],
            }
        )
    elif movement["outcome"] == "envelope_refused":
        summary["blocking"] = deepcopy(movement["blocking"])
        summary["sampleSpacingMeters"] = movement["sweptEnvelope"][
            "sampleSpacingMeters"
        ]
    else:
        summary["findingCodes"] = sorted(
            {
                str(item.get("code"))
                for item in movement["findings"]
                if isinstance(item, Mapping) and item.get("code")
            }
        )
    return summary


def sample_motion_at_distance(
    movement: Mapping[str, Any],
    distance_meters: float,
) -> dict[str, Any]:
    """Pure arc-length sampler for accepted or envelope-refused trajectories."""

    outcome = movement.get("outcome")
    poses = movement.get("poses") if outcome == "accepted" else movement.get(
        "attemptedPoses"
    )
    cumulative = movement.get("cumulativeDistance")
    if not isinstance(poses, list) or not poses or not isinstance(cumulative, list):
        raise FacilityMotionPackageError(
            "facility_motion_not_replayable",
            "This movement has no trajectory to replay.",
        )
    requested = _number(distance_meters, "distanceMeters")
    target = min(max(requested, 0.0), float(cumulative[-1]))
    if target <= 0.0:
        result = deepcopy(poses[0])
        result.update(
            {
                "distanceMeters": 0.0,
                "lowerPoseIndex": 0,
                "upperPoseIndex": 0,
                "interpolationRatio": 0.0,
            }
        )
        return result
    if target >= float(cumulative[-1]):
        index = len(poses) - 1
        result = deepcopy(poses[index])
        result.update(
            {
                "distanceMeters": float(cumulative[-1]),
                "lowerPoseIndex": index,
                "upperPoseIndex": index,
                "interpolationRatio": 0.0,
            }
        )
        return result
    upper = bisect_right([float(item) for item in cumulative], target)
    lower = upper - 1
    span = float(cumulative[upper]) - float(cumulative[lower])
    ratio = 0.0 if span <= 0.0 else (target - float(cumulative[lower])) / span
    start = poses[lower]
    end = poses[upper]
    start_heading = float(start["heading"])
    end_heading = float(end["heading"])
    heading_delta = math.atan2(
        math.sin(end_heading - start_heading),
        math.cos(end_heading - start_heading),
    )
    return {
        "x": float(start["x"]) + (float(end["x"]) - float(start["x"])) * ratio,
        "z": float(start["z"]) + (float(end["z"]) - float(start["z"])) * ratio,
        "heading": start_heading + heading_delta * ratio,
        "gear": str(start.get("gear") or "forward"),
        "distanceMeters": target,
        "lowerPoseIndex": lower,
        "upperPoseIndex": upper,
        "interpolationRatio": ratio,
    }


def sample_motion_at_time(
    movement: Mapping[str, Any],
    time_seconds: float,
) -> dict[str, Any]:
    """Sample an accepted movement using its planner duration estimate."""

    if movement.get("outcome") != "accepted":
        raise FacilityMotionPackageError(
            "facility_motion_time_sampling_unavailable",
            "Time sampling is available only for accepted movements.",
        )
    duration = _number(
        movement.get("plannerDurationEstimateSeconds"),
        "plannerDurationEstimateSeconds",
        minimum=0.0,
    )
    if duration <= 0.0:
        return sample_motion_at_distance(movement, 0.0)
    elapsed = min(max(_number(time_seconds, "timeSeconds"), 0.0), duration)
    distance = float(movement["distanceMeters"]) * elapsed / duration
    result = sample_motion_at_distance(movement, distance)
    result["timeSeconds"] = elapsed
    return result


class FacilityMotionPackageStore:
    """Bounded in-memory cache for browser-only full motion packages."""

    def __init__(
        self,
        *,
        ttl_seconds: float = FACILITY_MOTION_PACKAGE_STORE_TTL_SECONDS,
        maximum_entries: int = FACILITY_MOTION_PACKAGE_STORE_MAXIMUM_ENTRIES,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or maximum_entries < 1:
            raise ValueError("motion package store limits must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.maximum_entries = int(maximum_entries)
        self._clock = clock or time.monotonic
        self._lock = RLock()
        self._entries: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()

    def _prune(self, now: float) -> None:
        expired = [
            package_id
            for package_id, (_, expires_at) in self._entries.items()
            if expires_at <= now
        ]
        for package_id in expired:
            self._entries.pop(package_id, None)
        while len(self._entries) > self.maximum_entries:
            self._entries.popitem(last=False)

    def put(self, package_id: str, payload: Mapping[str, Any]) -> None:
        package_id = _text(package_id, "packageId")
        detached = _detached(payload)
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._entries.pop(package_id, None)
            self._entries[package_id] = (detached, now + self.ttl_seconds)
            self._prune(now)

    def get(self, package_id: str) -> dict[str, Any]:
        package_id = _text(package_id, "packageId")
        now = self._clock()
        with self._lock:
            self._prune(now)
            entry = self._entries.get(package_id)
            if entry is None:
                raise FacilityNotFoundError(
                    "facility_motion_package_not_found",
                    "The Facility Motion Package is unavailable or expired.",
                    details={"packageId": package_id},
                )
            self._entries.move_to_end(package_id)
            return _detached(entry[0])

    def diagnostics(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            return {
                "entryCount": len(self._entries),
                "maximumEntries": self.maximum_entries,
                "ttlSeconds": self.ttl_seconds,
            }
