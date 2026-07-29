"""Durable, resumable industrial-asset intake jobs.

This module owns job lifecycle and job-scoped staging only. It deliberately
does not publish catalog records or write authoritative asset registries.
Completed jobs expose a validated publication candidate that a separate,
approved transaction may consume.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence

from .schema_v1 import (
    canonical_json_bytes,
    canonical_json_sha256,
    canonical_relative_path,
    validate_json_value,
)


JOB_SCHEMA_VERSION = 1
JOB_RECORD_KIND = "industrial_asset_intake_job"
JOB_ID_RE = re.compile(r"^iaj-[0-9a-f]{24}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+_-]{7,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)

DEFAULT_INTAKE_STAGES = (
    "discovery",
    "dependency_resolution",
    "package_identity",
    "geometry_extraction",
    "coordinate_normalization",
    "spatial_metadata",
    "web_artifacts",
    "semantic_enrichment",
    "candidate_validation",
)

ACTIVE_STATUSES = {"pending", "running", "cancel_requested"}
TERMINAL_STATUSES = {"cancelled", "failed", "completed", "quarantined"}
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES

LEGAL_TRANSITIONS = {
    "pending": {"running", "cancelled", "failed", "quarantined"},
    "running": {
        "pending",
        "cancel_requested",
        "cancelled",
        "failed",
        "completed",
        "quarantined",
    },
    "cancel_requested": {"cancelled", "failed", "quarantined"},
    "failed": {"pending"},
    "cancelled": set(),
    "completed": set(),
    "quarantined": set(),
}

MAX_STORAGE_ROOT_LENGTH = 4096
MAX_JOB_RECORD_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 256 * 1024
MAX_STAGE_METADATA_BYTES = 256 * 1024
MAX_STAGES = 64
MAX_STAGE_NAME_LENGTH = 64
MAX_STAGE_OUTPUTS = 2048
MAX_STAGE_OUTPUT_PATH_LENGTH = 512
MAX_FINDINGS = 512
MAX_JOBS = 10_000

_PROTECTED_REQUEST_PATH_KEYS = {
    "jobPath",
    "localPath",
    "outputPath",
    "publicationPath",
    "registryPath",
    "sourcePath",
    "stagingPath",
}

_RECORD_FIELDS = {
    "schemaVersion",
    "recordKind",
    "jobId",
    "idempotencyKeyHash",
    "requestFingerprint",
    "request",
    "tenantId",
    "requestedBy",
    "sourceFingerprint",
    "requestedRoot",
    "configuration",
    "status",
    "currentStage",
    "stagePlan",
    "stageCheckpoints",
    "stagingPath",
    "attempts",
    "maximumAttempts",
    "recoveryCount",
    "createdAt",
    "updatedAt",
    "completedAt",
    "cancellation",
    "failure",
    "findings",
    "candidateAssetId",
    "candidateDefinitionRevision",
    "candidateRenderBundleRevision",
}

_ROOT_LOCKS: dict[str, threading.RLock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


class IndustrialAssetJobError(RuntimeError):
    """Base error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class IndustrialAssetJobValidationError(IndustrialAssetJobError):
    pass


class IndustrialAssetJobNotFoundError(IndustrialAssetJobError):
    pass


class IndustrialAssetJobConflictError(IndustrialAssetJobError):
    pass


class IndustrialAssetJobCorruptionError(IndustrialAssetJobError):
    pass


class IndustrialAssetJobStateError(IndustrialAssetJobError):
    pass


def _shared_root_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(str(root))
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _ROOT_LOCKS[key] = lock
        return lock


def _utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise IndustrialAssetJobValidationError(
            "invalid_job_clock",
            "The job clock must return a datetime.",
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise IndustrialAssetJobValidationError(
            "invalid_job_clock",
            "The job clock must return a timezone-aware datetime.",
        )
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _validate_timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            f"{field_name} is not a canonical UTC timestamp.",
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            f"{field_name} is not a valid UTC timestamp.",
        ) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            f"{field_name} must use UTC.",
        )
    return value


def _validate_safe_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or SAFE_PRINCIPAL_RE.fullmatch(value) is None:
        raise IndustrialAssetJobValidationError(
            "invalid_intake_request",
            f"{field_name} must be a bounded safe identifier.",
        )
    return value


def _validate_stage_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_STAGE_NAME_LENGTH
        or re.fullmatch(r"[a-z][a-z0-9_]*", value) is None
    ):
        raise IndustrialAssetJobValidationError(
            "invalid_intake_stage",
            "Stage names must be bounded lowercase identifiers.",
        )
    return value


def _validate_stage_plan(stages: Iterable[str]) -> tuple[str, ...]:
    try:
        result = tuple(_validate_stage_name(item) for item in stages)
    except TypeError as exc:
        raise IndustrialAssetJobValidationError(
            "invalid_intake_stage_plan",
            "The stage plan must be an iterable of stage names.",
        ) from exc
    if not result or len(result) > MAX_STAGES or len(set(result)) != len(result):
        raise IndustrialAssetJobValidationError(
            "invalid_intake_stage_plan",
            "The stage plan must contain unique stages within configured limits.",
        )
    return result


def _validate_idempotency_key(value: Any) -> str:
    if not isinstance(value, str) or IDEMPOTENCY_KEY_RE.fullmatch(value) is None:
        raise IndustrialAssetJobValidationError(
            "invalid_intake_idempotency_key",
            "The idempotency key must contain 8 to 128 safe characters.",
        )
    return value


def _validate_job_id(value: Any) -> str:
    if not isinstance(value, str) or JOB_ID_RE.fullmatch(value) is None:
        raise IndustrialAssetJobValidationError(
            "invalid_intake_job_id",
            "The intake job ID is invalid.",
        )
    return value


def _job_id_for_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"iaj-{digest[:24]}"


def _detached_json(value: Any, *, maximum_bytes: int) -> Any:
    try:
        return validate_json_value(value, maximum_bytes=maximum_bytes)
    except ValueError as exc:
        raise IndustrialAssetJobValidationError(
            "invalid_intake_job_payload",
            str(exc),
        ) from exc


def _reject_protected_request_paths(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _PROTECTED_REQUEST_PATH_KEYS:
                raise IndustrialAssetJobValidationError(
                    "invalid_intake_request",
                    "The intake request may not persist protected filesystem paths.",
                )
            _reject_protected_request_paths(item)
    elif isinstance(value, list):
        for item in value:
            _reject_protected_request_paths(item)


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise IndustrialAssetJobValidationError(
            "invalid_intake_request",
            "The intake request must be an object.",
        )
    detached = _detached_json(request, maximum_bytes=MAX_REQUEST_BYTES)
    if not isinstance(detached, dict):
        raise IndustrialAssetJobValidationError(
            "invalid_intake_request",
            "The intake request must be an object.",
        )
    _reject_protected_request_paths(detached)
    tenant_id = _validate_safe_identifier(detached.get("tenantId"), "tenantId")
    requested_by = _validate_safe_identifier(
        detached.get("requestedBy"),
        "requestedBy",
    )
    source_fingerprint = detached.get("sourceFingerprint")
    if (
        not isinstance(source_fingerprint, str)
        or SHA256_RE.fullmatch(source_fingerprint) is None
    ):
        raise IndustrialAssetJobValidationError(
            "invalid_intake_request",
            "sourceFingerprint must be a lowercase SHA-256 digest.",
        )
    requested_root = detached.get("requestedRoot")
    if requested_root is not None:
        try:
            detached["requestedRoot"] = canonical_relative_path(requested_root)
        except ValueError as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_intake_request",
                "requestedRoot must be a portable relative CAD path.",
            ) from exc
    configuration = detached.get("configuration")
    if configuration is not None and (
        not isinstance(configuration, str)
        or not configuration.strip()
        or len(configuration) > 256
    ):
        raise IndustrialAssetJobValidationError(
            "invalid_intake_request",
            "configuration must be null or a non-empty bounded string.",
        )
    detached["tenantId"] = tenant_id
    detached["requestedBy"] = requested_by
    return detached


def _validate_artifact_relative_path(value: Any) -> str:
    if not isinstance(value, str) or len(value) > MAX_STAGE_OUTPUT_PATH_LENGTH:
        raise IndustrialAssetJobValidationError(
            "invalid_staged_artifact_path",
            "Staged artifact paths must be bounded relative paths.",
        )
    try:
        return canonical_relative_path(value)
    except ValueError as exc:
        raise IndustrialAssetJobValidationError(
            "invalid_staged_artifact_path",
            "Staged artifact paths must not escape job staging.",
        ) from exc


def _first_incomplete_stage(record: Mapping[str, Any]) -> str | None:
    completed = set(record["stageCheckpoints"])
    return next(
        (stage for stage in record["stagePlan"] if stage not in completed),
        None,
    )


def _validate_checkpoint(
    checkpoint: Any,
    *,
    stage: str,
    maximum_attempts: int,
) -> None:
    if not isinstance(checkpoint, Mapping):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A stage checkpoint is not an object.",
        )
    if set(checkpoint) != {
        "stage",
        "status",
        "attempt",
        "completedAt",
        "outputs",
        "metadata",
    }:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A stage checkpoint has unsupported fields.",
        )
    if checkpoint["stage"] != stage or checkpoint["status"] != "completed":
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A stage checkpoint has an invalid identity or status.",
        )
    attempt = checkpoint["attempt"]
    if (
        isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt < 1
        or attempt > maximum_attempts
    ):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A stage checkpoint has an invalid attempt.",
        )
    _validate_timestamp(checkpoint["completedAt"], "checkpoint.completedAt")
    outputs = checkpoint["outputs"]
    if not isinstance(outputs, list) or len(outputs) > MAX_STAGE_OUTPUTS:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A stage checkpoint has invalid outputs.",
        )
    previous_path = ""
    seen: set[str] = set()
    for output in outputs:
        if not isinstance(output, Mapping) or set(output) != {
            "relativePath",
            "byteLength",
            "sha256",
        }:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "A stage output record is invalid.",
            )
        try:
            relative = _validate_artifact_relative_path(output["relativePath"])
        except IndustrialAssetJobValidationError as exc:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "A stage output path is invalid.",
            ) from exc
        if relative in seen or (previous_path and relative <= previous_path):
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "Stage outputs must be unique and canonically sorted.",
            )
        previous_path = relative
        seen.add(relative)
        length = output["byteLength"]
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "A stage output byte length is invalid.",
            )
        if not isinstance(output["sha256"], str) or SHA256_RE.fullmatch(
            output["sha256"]
        ) is None:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "A stage output digest is invalid.",
            )
    try:
        validate_json_value(
            checkpoint["metadata"],
            maximum_bytes=MAX_STAGE_METADATA_BYTES,
        )
    except ValueError as exc:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "Stage checkpoint metadata is invalid.",
        ) from exc


def _validate_job_record(document: Any) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "An intake job record must be an object.",
        )
    if document.get("schemaVersion") != JOB_SCHEMA_VERSION:
        raise IndustrialAssetJobCorruptionError(
            "unsupported_intake_job_schema",
            "The intake job schema version is unsupported.",
        )
    if document.get("recordKind") != JOB_RECORD_KIND:
        raise IndustrialAssetJobCorruptionError(
            "unsupported_intake_job_record",
            "The intake job record kind is unsupported.",
        )
    if set(document) != _RECORD_FIELDS:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The intake job record has missing or unsupported fields.",
        )
    try:
        job_id = _validate_job_id(document["jobId"])
        request = _validate_request(document["request"])
        stages = _validate_stage_plan(document["stagePlan"])
    except IndustrialAssetJobValidationError as exc:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            str(exc),
        ) from exc
    if document["requestFingerprint"] != canonical_json_sha256(request):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The intake request fingerprint does not match its payload.",
        )
    if (
        not isinstance(document["idempotencyKeyHash"], str)
        or SHA256_RE.fullmatch(document["idempotencyKeyHash"]) is None
        or job_id != f"iaj-{document['idempotencyKeyHash'][:24]}"
    ):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The intake job identity binding is invalid.",
        )
    projected = {
        "tenantId": document["tenantId"],
        "requestedBy": document["requestedBy"],
        "sourceFingerprint": document["sourceFingerprint"],
        "requestedRoot": document["requestedRoot"],
        "configuration": document["configuration"],
    }
    expected = {
        "tenantId": request["tenantId"],
        "requestedBy": request["requestedBy"],
        "sourceFingerprint": request["sourceFingerprint"],
        "requestedRoot": request.get("requestedRoot"),
        "configuration": request.get("configuration"),
    }
    if projected != expected:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The intake request projection is inconsistent.",
        )
    status = document["status"]
    if status not in ALL_STATUSES:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The intake job status is invalid.",
        )
    current_stage = document["currentStage"]
    if current_stage is not None and current_stage not in stages:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The current intake stage is invalid.",
        )
    checkpoints = document["stageCheckpoints"]
    if not isinstance(checkpoints, Mapping):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "Stage checkpoints must be an object.",
        )
    checkpoint_names = set(checkpoints)
    expected_prefix = set(stages[: len(checkpoints)])
    if checkpoint_names != expected_prefix:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "Stage checkpoints must form a completed stage-plan prefix.",
        )
    maximum_attempts = document["maximumAttempts"]
    attempts = document["attempts"]
    recovery_count = document["recoveryCount"]
    if (
        isinstance(maximum_attempts, bool)
        or not isinstance(maximum_attempts, int)
        or maximum_attempts < 1
        or maximum_attempts > 100
        or isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or attempts < 0
        or attempts > maximum_attempts
        or isinstance(recovery_count, bool)
        or not isinstance(recovery_count, int)
        or recovery_count < 0
    ):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The intake attempt counters are invalid.",
        )
    for stage, checkpoint in checkpoints.items():
        _validate_checkpoint(
            checkpoint,
            stage=stage,
            maximum_attempts=maximum_attempts,
        )
    first_incomplete = _first_incomplete_stage(document)
    if status == "completed":
        if first_incomplete is not None or current_stage is not None:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "A completed job still has incomplete stages.",
            )
        if document["completedAt"] is None:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "A completed job is missing completedAt.",
            )
    elif status in {"pending", "running", "cancel_requested"}:
        if current_stage != first_incomplete:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "The current stage does not match completed checkpoints.",
            )
    if status == "cancelled" and document["completedAt"] is None:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A cancelled job is missing completedAt.",
        )
    if status not in {"completed", "cancelled"} and document["completedAt"] is not None:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A non-completed job has completedAt.",
        )
    if document["stagingPath"] != f"staging/{job_id}":
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The job staging path is not job-scoped.",
        )
    _validate_timestamp(document["createdAt"], "createdAt")
    _validate_timestamp(document["updatedAt"], "updatedAt")
    if document["completedAt"] is not None:
        _validate_timestamp(document["completedAt"], "completedAt")
    findings = document["findings"]
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The job findings are invalid.",
        )
    try:
        validate_json_value(findings, maximum_bytes=MAX_STAGE_METADATA_BYTES)
        validate_json_value(
            document["cancellation"],
            maximum_bytes=MAX_STAGE_METADATA_BYTES,
        )
        validate_json_value(
            document["failure"],
            maximum_bytes=MAX_STAGE_METADATA_BYTES,
        )
    except ValueError as exc:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "Job lifecycle metadata is invalid.",
        ) from exc
    cancellation = document["cancellation"]
    if cancellation is not None:
        required_cancellation = {
            "requestedAt",
            "completedAt",
            "retainStagedArtifacts",
            "retainedArtifacts",
        }
        if (
            not isinstance(cancellation, Mapping)
            or set(cancellation) != required_cancellation
            or not isinstance(cancellation["retainStagedArtifacts"], bool)
            or not isinstance(cancellation["retainedArtifacts"], list)
        ):
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "The cancellation record is invalid.",
            )
        _validate_timestamp(cancellation["requestedAt"], "cancellation.requestedAt")
        if cancellation["completedAt"] is not None:
            _validate_timestamp(
                cancellation["completedAt"],
                "cancellation.completedAt",
            )
        if status in {"cancel_requested", "cancelled"}:
            if status == "cancelled" and cancellation["completedAt"] is None:
                raise IndustrialAssetJobCorruptionError(
                    "corrupt_intake_job",
                    "A cancelled job has an incomplete cancellation record.",
                )
        elif status != "failed":
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "Only a cancelling or cancelled job may carry cancellation data.",
            )
    elif status in {"cancel_requested", "cancelled"}:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The job status requires a cancellation record.",
        )
    failure = document["failure"]
    if failure is not None:
        if (
            not isinstance(failure, Mapping)
            or set(failure) != {"code", "message", "transient", "failedAt"}
            or not isinstance(failure["code"], str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", failure["code"]) is None
            or not isinstance(failure["message"], str)
            or not failure["message"]
            or len(failure["message"]) > 1024
            or not isinstance(failure["transient"], bool)
        ):
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "The job failure record is invalid.",
            )
        _validate_timestamp(failure["failedAt"], "failure.failedAt")
        if status not in {"failed", "quarantined"}:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "Only a failed or quarantined job may carry failure data.",
            )
    elif status in {"failed", "quarantined"}:
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "The job status requires a failure record.",
        )
    for field in (
        "candidateDefinitionRevision",
        "candidateRenderBundleRevision",
    ):
        value = document[field]
        if value is not None and (
            not isinstance(value, str) or SHA256_RE.fullmatch(value) is None
        ):
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                f"{field} must be null or a SHA-256 digest.",
            )
    candidate_id = document["candidateAssetId"]
    if candidate_id is not None and (
        not isinstance(candidate_id, str)
        or len(candidate_id) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", candidate_id) is None
    ):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "candidateAssetId is invalid.",
        )
    if status == "completed" and (
        candidate_id is None
        or document["candidateDefinitionRevision"] is None
        or document["candidateRenderBundleRevision"] is None
    ):
        raise IndustrialAssetJobCorruptionError(
            "corrupt_intake_job",
            "A completed job is missing its candidate revision binding.",
        )
    return json.loads(canonical_json_bytes(document).decode("ascii"))


class IndustrialAssetIntakeJobStore:
    """Canonical JSON job store with job-local staging and restart recovery."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        stages: Sequence[str] = DEFAULT_INTAKE_STAGES,
        clock: Callable[[], datetime] | None = None,
        maximum_attempts: int = 3,
    ) -> None:
        if isinstance(root, bytes) or not isinstance(root, (str, os.PathLike)):
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_root",
                "The intake store root must be a filesystem path.",
            )
        raw = os.fspath(root)
        if (
            not raw
            or "\x00" in raw
            or len(raw) > MAX_STORAGE_ROOT_LENGTH
            or not Path(raw).is_absolute()
        ):
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_root",
                "The intake store root must be a bounded absolute path.",
            )
        try:
            resolved = Path(raw).resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_root",
                "The intake store root could not be resolved.",
            ) from exc
        if resolved == Path(resolved.anchor):
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_root",
                "The intake store root cannot be a filesystem root.",
            )
        if resolved.exists() and not resolved.is_dir():
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_root",
                "The intake store root must be a directory.",
            )
        if (
            isinstance(maximum_attempts, bool)
            or not isinstance(maximum_attempts, int)
            or maximum_attempts < 1
            or maximum_attempts > 100
        ):
            raise IndustrialAssetJobValidationError(
                "invalid_intake_attempt_limit",
                "maximum_attempts must be between 1 and 100.",
            )
        self.root = resolved
        self.stage_plan = _validate_stage_plan(stages)
        self._clock = clock or _default_clock
        self.maximum_attempts = maximum_attempts
        self._lock = _shared_root_lock(resolved)
        self._jobs_dir = self._safe_child("jobs")
        self._staging_dir = self._safe_child("staging")
        self._quarantine_dir = self._safe_child("quarantine")
        with self._lock:
            self._jobs_dir.mkdir(parents=True, exist_ok=True)
            self._staging_dir.mkdir(parents=True, exist_ok=True)
            self._quarantine_dir.mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return _utc_timestamp(self._clock())

    def _safe_child(self, *parts: str) -> Path:
        candidate = self.root.joinpath(*parts)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_path",
                "An intake store path escaped its configured root.",
            ) from exc
        return candidate

    def _job_path(self, job_id: str) -> Path:
        return self._safe_child("jobs", f"{_validate_job_id(job_id)}.json")

    def staging_directory(self, job_id: str, *, create: bool = True) -> Path:
        job_id = _validate_job_id(job_id)
        path = self._safe_child("staging", job_id)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(6):
                try:
                    os.replace(temporary, path)
                    temporary = None
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    import time

                    time.sleep(0.02 * (attempt + 1))
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _read_canonical_mapping(path: Path) -> dict[str, Any]:
        try:
            size = path.stat().st_size
            if size < 1 or size > MAX_JOB_RECORD_BYTES:
                raise IndustrialAssetJobCorruptionError(
                    "corrupt_intake_job",
                    "The intake job record size is invalid.",
                )
            raw = path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise IndustrialAssetJobCorruptionError(
                "intake_job_read_failed",
                "The intake job record could not be read.",
            ) from exc
        if any(byte > 0x7F for byte in raw):
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "The intake job record is not ASCII.",
            )
        try:
            value = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "The intake job record is not valid JSON.",
            ) from exc
        if not isinstance(value, Mapping) or raw != canonical_json_bytes(value):
            raise IndustrialAssetJobCorruptionError(
                "corrupt_intake_job",
                "The intake job record is not canonical JSON.",
            )
        return dict(value)

    def _write_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        validated = _validate_job_record(record)
        self._atomic_write(
            self._job_path(validated["jobId"]),
            canonical_json_bytes(validated),
        )
        return deepcopy(validated)

    def _load_record(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        try:
            raw = self._read_canonical_mapping(path)
        except FileNotFoundError as exc:
            raise IndustrialAssetJobNotFoundError(
                "intake_job_not_found",
                "The industrial-asset intake job was not found.",
            ) from exc
        return _validate_job_record(raw)

    def create_job(
        self,
        request: Mapping[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        key = _validate_idempotency_key(idempotency_key)
        detached_request = _validate_request(request)
        request_fingerprint = canonical_json_sha256(detached_request)
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        job_id = f"iaj-{key_hash[:24]}"
        with self._lock:
            path = self._job_path(job_id)
            if path.exists():
                existing = self._load_record(job_id)
                if (
                    existing["idempotencyKeyHash"] != key_hash
                    or existing["requestFingerprint"] != request_fingerprint
                    or existing["request"] != detached_request
                    or existing["stagePlan"] != list(self.stage_plan)
                ):
                    raise IndustrialAssetJobConflictError(
                        "intake_idempotency_conflict",
                        "The idempotency key is already bound to another request.",
                    )
                return deepcopy(existing)
            if len(tuple(self._jobs_dir.glob("iaj-*.json"))) >= MAX_JOBS:
                raise IndustrialAssetJobValidationError(
                    "intake_job_capacity_exceeded",
                    "The durable intake job store is at capacity.",
                )
            now = self._now()
            record = {
                "schemaVersion": JOB_SCHEMA_VERSION,
                "recordKind": JOB_RECORD_KIND,
                "jobId": job_id,
                "idempotencyKeyHash": key_hash,
                "requestFingerprint": request_fingerprint,
                "request": detached_request,
                "tenantId": detached_request["tenantId"],
                "requestedBy": detached_request["requestedBy"],
                "sourceFingerprint": detached_request["sourceFingerprint"],
                "requestedRoot": detached_request.get("requestedRoot"),
                "configuration": detached_request.get("configuration"),
                "status": "pending",
                "currentStage": self.stage_plan[0],
                "stagePlan": list(self.stage_plan),
                "stageCheckpoints": {},
                "stagingPath": f"staging/{job_id}",
                "attempts": 0,
                "maximumAttempts": self.maximum_attempts,
                "recoveryCount": 0,
                "createdAt": now,
                "updatedAt": now,
                "completedAt": None,
                "cancellation": None,
                "failure": None,
                "findings": [],
                "candidateAssetId": None,
                "candidateDefinitionRevision": None,
                "candidateRenderBundleRevision": None,
            }
            created = self._write_record(record)
            self.staging_directory(job_id)
            return created

    create = create_job

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._load_record(job_id))

    get = get_job

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            paths = sorted(self._jobs_dir.glob("*.json"), key=lambda item: item.name)
            if len(paths) > MAX_JOBS:
                raise IndustrialAssetJobCorruptionError(
                    "intake_job_capacity_exceeded",
                    "The intake job directory exceeds its configured capacity.",
                )
            result = []
            for path in paths:
                if re.fullmatch(r"iaj-[0-9a-f]{24}\.json", path.name) is None:
                    raise IndustrialAssetJobCorruptionError(
                        "unsupported_intake_job_file",
                        "The intake job directory contains an unsupported record.",
                    )
                record = _validate_job_record(
                    self._read_canonical_mapping(path)
                )
                if path != self._job_path(record["jobId"]):
                    raise IndustrialAssetJobCorruptionError(
                        "corrupt_intake_job",
                        "An intake job filename does not match its record.",
                    )
                result.append(record)
            return deepcopy(result)

    def _transition(
        self,
        record: dict[str, Any],
        target: str,
        *,
        now: str,
    ) -> dict[str, Any]:
        if target not in ALL_STATUSES:
            raise IndustrialAssetJobStateError(
                "invalid_intake_job_transition",
                "The requested intake job status is unsupported.",
            )
        current = record["status"]
        if target != current and target not in LEGAL_TRANSITIONS[current]:
            raise IndustrialAssetJobStateError(
                "invalid_intake_job_transition",
                f"An intake job cannot transition from {current} to {target}.",
            )
        record["status"] = target
        record["updatedAt"] = now
        return record

    def start_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._load_record(job_id)
            if record["status"] == "running":
                return record
            if record["status"] == "failed":
                failure = record.get("failure") or {}
                if not failure.get("transient"):
                    raise IndustrialAssetJobStateError(
                        "intake_job_not_resumable",
                        "Only a classified transient failure may be resumed.",
                    )
                self._transition(record, "pending", now=self._now())
                record["failure"] = None
            if record["status"] != "pending":
                raise IndustrialAssetJobStateError(
                    "intake_job_not_startable",
                    "The intake job cannot start from its current state.",
                )
            if record["attempts"] >= record["maximumAttempts"]:
                raise IndustrialAssetJobStateError(
                    "intake_job_attempts_exhausted",
                    "The intake job exhausted its bounded attempts.",
                )
            now = self._now()
            self._transition(record, "running", now=now)
            record["attempts"] += 1
            record["currentStage"] = _first_incomplete_stage(record)
            return self._write_record(record)

    start = start_job

    def _staged_file(self, job_id: str, relative_path: str) -> Path:
        root = self.staging_directory(job_id)
        target = (root / relative_path).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_staged_artifact_path",
                "A staged artifact escaped job staging.",
            ) from exc
        return target

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        descriptor: int | None = None
        try:
            before = path.lstat()
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(
                before.st_mode
            ):
                raise IndustrialAssetJobValidationError(
                    "unsafe_staged_artifact",
                    "Staged artifacts must be regular files, not links.",
                )
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise IndustrialAssetJobValidationError(
                    "unsafe_staged_artifact",
                    "A staged artifact changed before it was opened.",
                )
            if (
                before.st_dev,
                before.st_ino,
            ) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise IndustrialAssetJobValidationError(
                    "staged_artifact_changed",
                    "A staged artifact changed before it was opened.",
                )
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = None
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            after = path.lstat()
        except FileNotFoundError as exc:
            raise IndustrialAssetJobValidationError(
                "staged_artifact_missing",
                "A checkpoint output is missing.",
            ) from exc
        except OSError as exc:
            raise IndustrialAssetJobValidationError(
                "staged_artifact_unreadable",
                "A checkpoint output could not be read.",
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if (
            before.st_size,
            before.st_mtime_ns,
            before.st_dev,
            getattr(before, "st_ino", 0),
        ) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_dev,
            getattr(after, "st_ino", 0),
        ):
            raise IndustrialAssetJobValidationError(
                "staged_artifact_changed",
                "A checkpoint output changed while it was hashed.",
            )
        return digest.hexdigest(), after.st_size

    def _output_records(
        self,
        job_id: str,
        output_paths: Iterable[str],
    ) -> list[dict[str, Any]]:
        try:
            paths = sorted(
                {_validate_artifact_relative_path(item) for item in output_paths}
            )
        except TypeError as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_staged_artifact_path",
                "Checkpoint outputs must be an iterable of relative paths.",
            ) from exc
        if len(paths) > MAX_STAGE_OUTPUTS:
            raise IndustrialAssetJobValidationError(
                "stage_output_limit_exceeded",
                "The checkpoint exceeds the staged-output limit.",
            )
        result = []
        for relative in paths:
            digest, byte_length = self._hash_file(
                self._staged_file(job_id, relative)
            )
            result.append(
                {
                    "relativePath": relative,
                    "byteLength": byte_length,
                    "sha256": digest,
                }
            )
        return result

    def checkpoint_stage(
        self,
        job_id: str,
        stage: str,
        *,
        output_paths: Iterable[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        stage = _validate_stage_name(stage)
        detached_metadata = _detached_json(
            metadata or {},
            maximum_bytes=MAX_STAGE_METADATA_BYTES,
        )
        with self._lock:
            record = self._load_record(job_id)
            if stage not in record["stagePlan"]:
                raise IndustrialAssetJobStateError(
                    "intake_stage_not_in_plan",
                    "The checkpoint stage is not in this job's stage plan.",
                )
            if record["status"] != "running":
                raise IndustrialAssetJobStateError(
                    "intake_job_not_running",
                    "Only a running intake job may write a checkpoint.",
                )
            outputs = self._output_records(job_id, output_paths)
            existing = record["stageCheckpoints"].get(stage)
            if existing is not None:
                if (
                    existing["outputs"] == outputs
                    and existing["metadata"] == detached_metadata
                ):
                    self._verify_checkpoint_outputs(record, stages=(stage,))
                    return record
                raise IndustrialAssetJobConflictError(
                    "intake_checkpoint_conflict",
                    "The completed stage is already bound to different output.",
                )
            if record["currentStage"] != stage:
                raise IndustrialAssetJobStateError(
                    "intake_stage_out_of_order",
                    "Stages must checkpoint in the configured order.",
                )
            now = self._now()
            record["stageCheckpoints"][stage] = {
                "stage": stage,
                "status": "completed",
                "attempt": record["attempts"],
                "completedAt": now,
                "outputs": outputs,
                "metadata": detached_metadata,
            }
            record["currentStage"] = _first_incomplete_stage(record)
            record["updatedAt"] = now
            return self._write_record(record)

    checkpoint = checkpoint_stage

    def fail_job(
        self,
        job_id: str,
        *,
        code: str,
        message: str,
        transient: bool = False,
    ) -> dict[str, Any]:
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None
            or not isinstance(message, str)
            or not message
            or len(message) > 1024
        ):
            raise IndustrialAssetJobValidationError(
                "invalid_intake_failure",
                "The intake failure record is invalid.",
            )
        with self._lock:
            record = self._load_record(job_id)
            if record["status"] not in {"pending", "running", "cancel_requested"}:
                raise IndustrialAssetJobStateError(
                    "intake_job_not_failable",
                    "The intake job cannot fail from its current state.",
                )
            now = self._now()
            self._transition(record, "failed", now=now)
            record["failure"] = {
                "code": code,
                "message": message,
                "transient": bool(transient),
                "failedAt": now,
            }
            return self._write_record(record)

    fail = fail_job

    def resume_job(self, job_id: str) -> dict[str, Any]:
        return self.start_job(job_id)

    resume = resume_job

    def request_cancellation(
        self,
        job_id: str,
        *,
        retain_staged_artifacts: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(retain_staged_artifacts, bool):
            raise IndustrialAssetJobValidationError(
                "invalid_cancellation_request",
                "retain_staged_artifacts must be boolean.",
            )
        with self._lock:
            record = self._load_record(job_id)
            if record["status"] in {"cancelled", "cancel_requested"}:
                return record
            if record["status"] not in {"pending", "running"}:
                raise IndustrialAssetJobStateError(
                    "intake_job_not_cancellable",
                    "The intake job cannot be cancelled from its current state.",
                )
            now = self._now()
            record["cancellation"] = {
                "requestedAt": now,
                "completedAt": None,
                "retainStagedArtifacts": retain_staged_artifacts,
                "retainedArtifacts": [],
            }
            if record["status"] == "pending":
                self._transition(record, "cancelled", now=now)
                record["completedAt"] = now
                record = self._finalize_cancellation_staging(record)
            else:
                self._transition(record, "cancel_requested", now=now)
            return self._write_record(record)

    def acknowledge_cancellation(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._load_record(job_id)
            if record["status"] == "cancelled":
                return record
            if record["status"] != "cancel_requested":
                raise IndustrialAssetJobStateError(
                    "intake_cancellation_not_requested",
                    "The intake job has no pending cancellation.",
                )
            now = self._now()
            self._transition(record, "cancelled", now=now)
            record["completedAt"] = now
            record = self._finalize_cancellation_staging(record)
            return self._write_record(record)

    def cancel_job(
        self,
        job_id: str,
        *,
        retain_staged_artifacts: bool = False,
    ) -> dict[str, Any]:
        requested = self.request_cancellation(
            job_id,
            retain_staged_artifacts=retain_staged_artifacts,
        )
        if requested["status"] == "cancel_requested":
            return self.acknowledge_cancellation(job_id)
        return requested

    cancel = cancel_job

    def _inventory_staging(self, job_id: str) -> list[dict[str, Any]]:
        root = self.staging_directory(job_id, create=False)
        if not root.exists():
            return []
        records = []
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise IndustrialAssetJobValidationError(
                    "unsafe_staged_artifact",
                    "Staged artifact links are not allowed.",
                )
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            digest, size = self._hash_file(path)
            records.append(
                {
                    "relativePath": relative,
                    "byteLength": size,
                    "sha256": digest,
                }
            )
        if len(records) > MAX_STAGE_OUTPUTS:
            raise IndustrialAssetJobValidationError(
                "stage_output_limit_exceeded",
                "The staging directory exceeds the artifact inventory limit.",
            )
        return records

    def _finalize_cancellation_staging(
        self,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        cancellation = record["cancellation"]
        if cancellation["retainStagedArtifacts"]:
            cancellation["retainedArtifacts"] = self._inventory_staging(
                record["jobId"]
            )
        else:
            self._remove_staging(record["jobId"])
            cancellation["retainedArtifacts"] = []
        cancellation["completedAt"] = record["completedAt"]
        return record

    def _remove_staging(self, job_id: str) -> None:
        path = self.staging_directory(job_id, create=False)
        try:
            path.relative_to(self._staging_dir)
        except ValueError as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_intake_store_path",
                "The staging path escaped the configured root.",
            ) from exc
        if path.exists():
            shutil.rmtree(path)

    def cleanup_staging(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._load_record(job_id)
            if record["status"] not in {"cancelled", "failed", "quarantined"}:
                raise IndustrialAssetJobStateError(
                    "intake_staging_still_active",
                    "Staging needed by an active or unpublished completed job "
                    "cannot be cleaned.",
                )
            self._remove_staging(job_id)
            if record.get("cancellation"):
                record["cancellation"]["retainedArtifacts"] = []
                record["updatedAt"] = self._now()
                record = self._write_record(record)
            return record

    def _verify_checkpoint_outputs(
        self,
        record: Mapping[str, Any],
        *,
        stages: Iterable[str] | None = None,
    ) -> None:
        selected = set(stages) if stages is not None else None
        for stage, checkpoint in record["stageCheckpoints"].items():
            if selected is not None and stage not in selected:
                continue
            for expected in checkpoint["outputs"]:
                digest, size = self._hash_file(
                    self._staged_file(
                        record["jobId"],
                        expected["relativePath"],
                    )
                )
                if digest != expected["sha256"] or size != expected["byteLength"]:
                    raise IndustrialAssetJobCorruptionError(
                        "checkpoint_artifact_mismatch",
                        "A checkpointed staged artifact no longer matches.",
                    )

    def verify_checkpoints(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._load_record(job_id)
            self._verify_checkpoint_outputs(record)
            return record

    def complete_job(
        self,
        job_id: str,
        *,
        candidate_asset_id: str,
        candidate_definition_revision: str,
        candidate_render_bundle_revision: str,
    ) -> dict[str, Any]:
        candidate = {
            "candidateAssetId": candidate_asset_id,
            "candidateDefinitionRevision": candidate_definition_revision,
            "candidateRenderBundleRevision": candidate_render_bundle_revision,
        }
        probe = {
            **self._load_record(job_id),
            **candidate,
        }
        try:
            _validate_job_record(probe)
        except IndustrialAssetJobCorruptionError as exc:
            raise IndustrialAssetJobValidationError(
                "invalid_intake_candidate",
                str(exc),
            ) from exc
        with self._lock:
            record = self._load_record(job_id)
            if record["status"] == "completed":
                if all(record[key] == value for key, value in candidate.items()):
                    self._verify_checkpoint_outputs(record)
                    return record
                raise IndustrialAssetJobConflictError(
                    "intake_completion_conflict",
                    "The completed job is bound to another candidate.",
                )
            if record["status"] != "running":
                raise IndustrialAssetJobStateError(
                    "intake_job_not_completable",
                    "Only a running intake job may complete.",
                )
            if _first_incomplete_stage(record) is not None:
                raise IndustrialAssetJobStateError(
                    "intake_stages_incomplete",
                    "Every configured intake stage must be checkpointed.",
                )
            self._verify_checkpoint_outputs(record)
            now = self._now()
            self._transition(record, "completed", now=now)
            record["currentStage"] = None
            record["completedAt"] = now
            record.update(candidate)
            return self._write_record(record)

    complete = complete_job

    def get_publication_candidate(self, job_id: str) -> dict[str, Any]:
        """Return a validated candidate reference without publishing it."""

        with self._lock:
            record = self._load_record(job_id)
            if record["status"] != "completed":
                raise IndustrialAssetJobStateError(
                    "intake_candidate_not_ready",
                    "Partial intake output cannot be used for publication.",
                )
            self._verify_checkpoint_outputs(record)
            inventory = sorted(
                (
                    {
                        "relativePath": output["relativePath"],
                        "sha256": output["sha256"],
                        "byteLength": output["byteLength"],
                    }
                    for checkpoint in record["stageCheckpoints"].values()
                    for output in checkpoint["outputs"]
                ),
                key=lambda item: (
                    item["sha256"],
                    item["relativePath"],
                ),
            )
            return {
                "jobId": record["jobId"],
                "tenantId": record["tenantId"],
                "sourceFingerprint": record["sourceFingerprint"],
                "requestFingerprint": record["requestFingerprint"],
                "candidateAssetId": record["candidateAssetId"],
                "candidateDefinitionRevision": record[
                    "candidateDefinitionRevision"
                ],
                "candidateRenderBundleRevision": record[
                    "candidateRenderBundleRevision"
                ],
                "checkpointFingerprint": canonical_json_sha256(
                    record["stageCheckpoints"]
                ),
                "artifactInventory": inventory,
            }

    def resolve_checkpointed_artifacts(
        self,
        job_id: str,
        requirements: Mapping[str, int],
    ) -> dict[str, Path]:
        """Resolve exact staged bytes from one completed intake job."""

        if (
            not isinstance(requirements, Mapping)
            or len(requirements) > MAX_STAGE_OUTPUTS
        ):
            raise IndustrialAssetJobValidationError(
                "invalid_publication_artifacts",
                "Publication artifact requirements must be bounded.",
            )
        expected: dict[str, int] = {}
        for digest, byte_length in requirements.items():
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise IndustrialAssetJobValidationError(
                    "invalid_publication_artifacts",
                    "Publication artifact hashes must be SHA-256 values.",
                )
            if (
                isinstance(byte_length, bool)
                or not isinstance(byte_length, int)
                or byte_length < 1
            ):
                raise IndustrialAssetJobValidationError(
                    "invalid_publication_artifacts",
                    "Publication artifact lengths must be positive integers.",
                )
            expected[digest] = byte_length
        if not expected:
            raise IndustrialAssetJobValidationError(
                "invalid_publication_artifacts",
                "Publication requires at least one staged artifact.",
            )

        with self._lock:
            record = self._load_record(job_id)
            if record["status"] != "completed":
                raise IndustrialAssetJobStateError(
                    "intake_candidate_not_ready",
                    "Partial intake output cannot be used for publication.",
                )
            self._verify_checkpoint_outputs(record)
            matches: dict[str, list[Path]] = {
                digest: [] for digest in expected
            }
            for checkpoint in record["stageCheckpoints"].values():
                for output in checkpoint["outputs"]:
                    digest = output["sha256"]
                    if digest not in expected:
                        continue
                    if output["byteLength"] != expected[digest]:
                        raise IndustrialAssetJobCorruptionError(
                            "checkpoint_artifact_mismatch",
                            "A staged artifact has the expected hash but "
                            "an incompatible length.",
                        )
                    matches[digest].append(
                        self._staged_file(
                            record["jobId"],
                            output["relativePath"],
                        )
                    )

            resolved: dict[str, Path] = {}
            for digest in sorted(expected):
                candidates = sorted(
                    set(matches[digest]),
                    key=lambda item: item.as_posix(),
                )
                if not candidates:
                    raise IndustrialAssetJobValidationError(
                        "publication_artifact_missing",
                        "A render artifact is not present in the completed "
                        "intake checkpoints.",
                    )
                selected = candidates[0]
                actual_digest, actual_length = self._hash_file(selected)
                if (
                    actual_digest != digest
                    or actual_length != expected[digest]
                ):
                    raise IndustrialAssetJobCorruptionError(
                        "checkpoint_artifact_mismatch",
                        "A checkpointed publication artifact changed.",
                    )
                resolved[digest] = selected
            return resolved

    def _known_checkpoint_paths(self, record: Mapping[str, Any]) -> set[str]:
        return {
            output["relativePath"]
            for checkpoint in record["stageCheckpoints"].values()
            for output in checkpoint["outputs"]
        }

    def _remove_uncheckpointed_staging(
        self,
        record: Mapping[str, Any],
    ) -> list[str]:
        root = self.staging_directory(record["jobId"], create=False)
        if not root.exists():
            return []
        known = self._known_checkpoint_paths(record)
        removed = []
        for path in sorted(
            root.rglob("*"),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            if path.is_symlink():
                path.unlink()
                removed.append(path.relative_to(root).as_posix())
            elif path.is_file():
                relative = path.relative_to(root).as_posix()
                if relative not in known:
                    path.unlink()
                    removed.append(relative)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        return sorted(removed)

    def _quarantine_staging(self, job_id: str) -> str | None:
        source = self.staging_directory(job_id, create=False)
        if not source.exists():
            return None
        destination = self._safe_child("quarantine", job_id)
        if destination.exists():
            raise IndustrialAssetJobCorruptionError(
                "intake_quarantine_conflict",
                "A quarantine directory already exists for this job.",
            )
        os.replace(source, destination)
        return f"quarantine/{job_id}"

    def _quarantine_abandoned_staging(self, path: Path) -> str:
        digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:24]
        destination = self._safe_child("quarantine", f"abandoned-{digest}")
        if destination.exists():
            raise IndustrialAssetJobCorruptionError(
                "intake_quarantine_conflict",
                "An abandoned staging quarantine already exists.",
            )
        os.replace(path, destination)
        return destination.relative_to(self.root).as_posix()

    def recover(self) -> list[dict[str, Any]]:
        """Recover interrupted jobs and quarantine non-authoritative staging."""

        with self._lock:
            jobs = self.list_jobs()
            known_ids = {record["jobId"] for record in jobs}
            for path in sorted(self._staging_dir.iterdir(), key=lambda item: item.name):
                if path.is_symlink() or not path.is_dir():
                    raise IndustrialAssetJobCorruptionError(
                        "unsafe_intake_staging",
                        "The intake staging root contains an unsafe entry.",
                    )
                if path.name not in known_ids:
                    self._quarantine_abandoned_staging(path)

            recovered = []
            for original in jobs:
                record = deepcopy(original)
                should_verify = (
                    record["status"]
                    in {"pending", "running", "cancel_requested", "completed"}
                    or (
                        record["status"] == "cancelled"
                        and record.get("cancellation")
                        and record["cancellation"]["retainStagedArtifacts"]
                    )
                    or (
                        record["status"] == "failed"
                        and record.get("failure")
                        and record["failure"]["transient"]
                    )
                )
                try:
                    if should_verify:
                        self._verify_checkpoint_outputs(record)
                except (
                    IndustrialAssetJobCorruptionError,
                    IndustrialAssetJobValidationError,
                ) as exc:
                    now = self._now()
                    record["status"] = "quarantined"
                    record["updatedAt"] = now
                    record["completedAt"] = None
                    record["cancellation"] = None
                    record["failure"] = {
                        "code": "checkpoint_artifact_invalid",
                        "message": "Checkpointed staged output failed recovery validation.",
                        "transient": False,
                        "failedAt": now,
                    }
                    location = self._quarantine_staging(record["jobId"])
                    record["findings"].append(
                        {
                            "severity": "error",
                            "code": "checkpoint_artifact_invalid",
                            "message": str(exc),
                            "quarantinePath": location,
                        }
                    )
                    recovered.append(self._write_record(record))
                    continue

                if record["status"] in {"pending", "running"}:
                    removed = self._remove_uncheckpointed_staging(record)
                    if record["status"] == "running":
                        now = self._now()
                        self._transition(record, "pending", now=now)
                        record["recoveryCount"] += 1
                        record["currentStage"] = _first_incomplete_stage(record)
                        if removed:
                            record["findings"].append(
                                {
                                    "severity": "info",
                                    "code": "partial_stage_output_removed",
                                    "message": (
                                        "Uncheckpointed stage output was removed "
                                        "during restart recovery."
                                    ),
                                    "artifactCount": len(removed),
                                }
                            )
                        record = self._write_record(record)
                elif record["status"] == "cancel_requested":
                    now = self._now()
                    self._transition(record, "cancelled", now=now)
                    record["completedAt"] = now
                    record = self._finalize_cancellation_staging(record)
                    record = self._write_record(record)
                recovered.append(record)
            return deepcopy(recovered)


IndustrialAssetJobStore = IndustrialAssetIntakeJobStore


__all__ = [
    "ACTIVE_STATUSES",
    "ALL_STATUSES",
    "DEFAULT_INTAKE_STAGES",
    "IndustrialAssetIntakeJobStore",
    "IndustrialAssetJobConflictError",
    "IndustrialAssetJobCorruptionError",
    "IndustrialAssetJobError",
    "IndustrialAssetJobNotFoundError",
    "IndustrialAssetJobStateError",
    "IndustrialAssetJobStore",
    "IndustrialAssetJobValidationError",
    "JOB_SCHEMA_VERSION",
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATUSES",
]
