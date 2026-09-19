"""Durable, revision-bound cache for derived Facility activity scenarios."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .activity_scenario import (
    FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS,
    validate_facility_activity_scenario,
)
from .errors import FacilityValidationError
from .motion_package import validate_facility_motion_package_for_playback


FACILITY_ACTIVITY_ARTIFACT_SCHEMA_VERSION = (
    "facility-activity-scenario-artifact-v1"
)
FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES = 8 * 1024 * 1024

_CACHE_KEY_FIELDS = {
    "tenantId",
    "siteId",
    "layoutId",
    "layoutRevision",
    "preset",
    "compilerRevision",
    "maximumActors",
}
_PAYLOAD_FIELDS = {
    "tenantId",
    "siteId",
    "layoutId",
    "layoutRevision",
    "scenario",
    "actorPayloads",
    "candidatePresentation",
}


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            "The Facility activity artifact is not canonical JSON.",
        ) from exc


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            f"{field} must be a non-empty string.",
        )
    return value


def _revision(value: Any, field: str) -> str:
    revision = _text(value, field)
    if len(revision) != 64 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            f"{field} must be a lowercase SHA-256 revision.",
        )
    return revision


def _cache_key(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEY_FIELDS:
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            "The Facility activity artifact cache key is invalid.",
        )
    maximum_actors = value["maximumActors"]
    if (
        isinstance(maximum_actors, bool)
        or not isinstance(maximum_actors, int)
        or maximum_actors < 1
        or maximum_actors > FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS
    ):
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            "The Facility activity artifact actor bound is invalid.",
        )
    return {
        "tenantId": _text(value["tenantId"], "cacheKey.tenantId"),
        "siteId": _text(value["siteId"], "cacheKey.siteId"),
        "layoutId": _text(value["layoutId"], "cacheKey.layoutId"),
        "layoutRevision": _revision(
            value["layoutRevision"], "cacheKey.layoutRevision"
        ),
        "preset": _text(value["preset"], "cacheKey.preset"),
        "compilerRevision": _text(
            value["compilerRevision"], "cacheKey.compilerRevision"
        ),
        "maximumActors": maximum_actors,
    }


def _actor_package_ids(actor: Mapping[str, Any]) -> list[str]:
    values = [
        actor.get("motionPackageId"),
        actor.get("returnMotionPackageId"),
        actor.get("endTransferMotionPackageId"),
        actor.get("startTransferMotionPackageId"),
        *(actor.get("cycleMotionPackageIds") or []),
    ]
    return [str(value) for value in values if value is not None]


def _validate_payload(
    payload: Mapping[str, Any],
    cache_key: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            "The Facility activity artifact payload is invalid.",
        )
    for field in ("tenantId", "siteId", "layoutId", "layoutRevision"):
        if payload.get(field) != cache_key[field]:
            raise FacilityValidationError(
                "facility_activity_artifact_binding_mismatch",
                "The Facility activity artifact does not match its cache key.",
                details={"field": field},
            )

    scenario = validate_facility_activity_scenario(payload["scenario"])
    actors = scenario["actors"]
    if (
        scenario["layoutRevision"] != cache_key["layoutRevision"]
        or len(actors) != cache_key["maximumActors"]
    ):
        raise FacilityValidationError(
            "facility_activity_artifact_binding_mismatch",
            "The cached scenario revision or actor count changed.",
        )

    package_to_placement: dict[str, str] = {}
    for actor in actors:
        placement_id = str(actor["placementId"])
        for package_id in _actor_package_ids(actor):
            previous = package_to_placement.setdefault(package_id, placement_id)
            if previous != placement_id:
                raise FacilityValidationError(
                    "facility_activity_artifact_invalid",
                    "A cached motion package is bound to multiple actors.",
                )

    actor_payloads = payload["actorPayloads"]
    if (
        not isinstance(actor_payloads, Mapping)
        or set(actor_payloads) != set(package_to_placement)
    ):
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            "The cached scenario does not contain its exact motion package set.",
        )
    canonical_actor_payloads: dict[str, dict[str, Any]] = {}
    for package_id in sorted(actor_payloads):
        package_payload = actor_payloads[package_id]
        if not isinstance(package_payload, Mapping):
            raise FacilityValidationError(
                "facility_activity_artifact_invalid",
                "A cached motion package payload is invalid.",
            )
        package = validate_facility_motion_package_for_playback(
            package_payload.get("package"),
            active_layout_revision=cache_key["layoutRevision"],
            active_validation_context_fingerprint=package_payload.get(
                "activeValidationContextFingerprint"
            ),
        )
        if package["packageId"] != package_id:
            raise FacilityValidationError(
                "facility_activity_artifact_binding_mismatch",
                "A cached motion package ID changed.",
            )
        movement = package["movement"]
        movement_placement_id = movement.get(
            "actorPlacementId", movement.get("vehiclePlacementId")
        )
        if (
            movement_placement_id is not None
            and movement_placement_id != package_to_placement[package_id]
        ):
            raise FacilityValidationError(
                "facility_activity_artifact_binding_mismatch",
                "A cached motion package belongs to another actor placement.",
            )
        detached = deepcopy(dict(package_payload))
        detached["package"] = package
        canonical_actor_payloads[package_id] = detached

    presentation = payload["candidatePresentation"]
    if not isinstance(presentation, Mapping) or (
        presentation.get("sourceLayoutId") != cache_key["layoutId"]
        or presentation.get("sourceLayoutRevision")
        != cache_key["layoutRevision"]
    ):
        raise FacilityValidationError(
            "facility_activity_artifact_binding_mismatch",
            "The cached candidate presentation belongs to another layout.",
        )
    candidate_counts = presentation.get("candidateCounts")
    if not isinstance(candidate_counts, Mapping) or (
        candidate_counts.get("displayedActors") != len(actors)
    ):
        raise FacilityValidationError(
            "facility_activity_artifact_invalid",
            "The cached candidate presentation actor count changed.",
        )

    return {
        "tenantId": cache_key["tenantId"],
        "siteId": cache_key["siteId"],
        "layoutId": cache_key["layoutId"],
        "layoutRevision": cache_key["layoutRevision"],
        "scenario": scenario,
        "actorPayloads": canonical_actor_payloads,
        "candidatePresentation": deepcopy(dict(presentation)),
    }


class FacilityActivityScenarioArtifactCache:
    """Store validated derived scenarios without changing a Facility layout."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._lock = RLock()

    def _path(self, cache_key: Mapping[str, Any]) -> Path:
        canonical_key = _cache_key(cache_key)
        digest = hashlib.sha256(_canonical_bytes(canonical_key)).hexdigest()
        return self.root / f"{digest}.json"

    @staticmethod
    def _artifact(
        cache_key: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        canonical_key = _cache_key(cache_key)
        canonical_payload = _validate_payload(payload, canonical_key)
        body = {
            "schemaVersion": FACILITY_ACTIVITY_ARTIFACT_SCHEMA_VERSION,
            "cacheKey": canonical_key,
            "payload": canonical_payload,
        }
        return {
            **body,
            "artifactFingerprint": hashlib.sha256(
                _canonical_bytes(body)
            ).hexdigest(),
        }

    def get(self, cache_key: Mapping[str, Any]) -> dict[str, Any] | None:
        canonical_key = _cache_key(cache_key)
        path = self._path(canonical_key)
        try:
            with self._lock:
                if not path.is_file():
                    return None
                if path.stat().st_size > (
                    FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES
                ):
                    return None
                raw = path.read_bytes()
            if len(raw) > FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES:
                return None
            artifact = json.loads(raw.decode("ascii"))
            if not isinstance(artifact, Mapping) or set(artifact) != {
                "schemaVersion",
                "cacheKey",
                "payload",
                "artifactFingerprint",
            }:
                return None
            if artifact.get("schemaVersion") != (
                FACILITY_ACTIVITY_ARTIFACT_SCHEMA_VERSION
            ):
                return None
            artifact_key = _cache_key(artifact["cacheKey"])
            if artifact_key != canonical_key:
                return None
            body = {
                "schemaVersion": artifact["schemaVersion"],
                "cacheKey": artifact_key,
                "payload": artifact["payload"],
            }
            if artifact.get("artifactFingerprint") != hashlib.sha256(
                _canonical_bytes(body)
            ).hexdigest():
                return None
            return _validate_payload(artifact["payload"], canonical_key)
        except (
            FacilityValidationError,
            json.JSONDecodeError,
            OSError,
            UnicodeError,
        ):
            return None

    def put(
        self,
        cache_key: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> Path:
        artifact = self._artifact(cache_key, payload)
        raw = _canonical_bytes(artifact)
        if len(raw) > FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES:
            raise FacilityValidationError(
                "facility_activity_artifact_too_large",
                "The Facility activity artifact exceeds its canonical byte budget.",
                details={
                    "canonicalBytes": len(raw),
                    "maximumCanonicalBytes": (
                        FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES
                    ),
                },
            )
        path = self._path(artifact["cacheKey"])
        temporary_name: str | None = None
        try:
            with self._lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=".activity-",
                    suffix=".tmp",
                    dir=path.parent,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                for attempt in range(6):
                    try:
                        os.replace(temporary_name, path)
                        temporary_name = None
                        break
                    except (FileNotFoundError, PermissionError):
                        if attempt == 5:
                            raise
                        time.sleep(0.02 * (attempt + 1))
        except OSError as exc:
            raise FacilityValidationError(
                "facility_activity_artifact_unavailable",
                "The Facility activity artifact cache is unavailable.",
            ) from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
        return path


__all__ = [
    "FACILITY_ACTIVITY_ARTIFACT_MAXIMUM_CANONICAL_BYTES",
    "FACILITY_ACTIVITY_ARTIFACT_SCHEMA_VERSION",
    "FacilityActivityScenarioArtifactCache",
]
