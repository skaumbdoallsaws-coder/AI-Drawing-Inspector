"""Durable immutable records and CAS heads for Facility design loops."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import uuid4

from .design_brief import (
    canonical_design_bytes,
    design_revision,
    validate_facility_design_brief,
)


FACILITY_DESIGN_MAXIMUM_ACTIVE_BRIEFS_PER_LAYOUT = 16
FACILITY_DESIGN_MAXIMUM_REVISIONS_PER_BRIEF = 256
FACILITY_DESIGN_LOCK_STALE_SECONDS = 120
FACILITY_DESIGN_LOCK_TIMEOUT_SECONDS = 5.0
FACILITY_DESIGN_RUN_IDLE_SECONDS = 24 * 60 * 60
FACILITY_DESIGN_RUN_TOMBSTONE_SECONDS = 30 * 24 * 60 * 60


class FacilityDesignRepositoryError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


class FacilityDesignRepositoryConflictError(FacilityDesignRepositoryError):
    pass


class FacilityDesignRepositoryNotFoundError(FacilityDesignRepositoryError):
    pass


class FacilityDesignRepositoryIntegrityError(FacilityDesignRepositoryError):
    pass


def _native_path(path: Path) -> str:
    absolute = os.path.abspath(os.fspath(path))
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise FacilityDesignRepositoryError(
            "facility_design_scope_invalid",
            f"{field} must be a stable identifier.",
        )
    if not value[0].isalnum() or any(
        not (character.isalnum() or character in "._:-") for character in value
    ):
        raise FacilityDesignRepositoryError(
            "facility_design_scope_invalid",
            f"{field} must be a stable identifier.",
        )
    return value


def _revision(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FacilityDesignRepositoryError(
            "facility_design_revision_invalid",
            f"{field} must be a lowercase SHA-256 revision.",
        )
    return value


def _timestamp(value: datetime) -> str:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise FacilityDesignRepositoryIntegrityError(
            "facility_design_record_corrupt",
            f"{field} must be an ISO timestamp.",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FacilityDesignRepositoryIntegrityError(
            "facility_design_record_corrupt",
            f"{field} must be an ISO timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise FacilityDesignRepositoryIntegrityError(
            "facility_design_record_corrupt",
            f"{field} must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path, *, missing_code: str) -> dict[str, Any]:
    try:
        payload = Path(_native_path(path)).read_bytes()
        value = json.loads(payload.decode("ascii"))
    except FileNotFoundError as exc:
        raise FacilityDesignRepositoryNotFoundError(
            missing_code,
            "Facility design record was not found.",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FacilityDesignRepositoryIntegrityError(
            "facility_design_record_corrupt",
            "Facility design record cannot be read as canonical JSON.",
        ) from exc
    if not isinstance(value, dict):
        raise FacilityDesignRepositoryIntegrityError(
            "facility_design_record_corrupt",
            "Facility design record must be an object.",
        )
    return value


def _exists(path: Path) -> bool:
    return os.path.exists(_native_path(path))


def _walk_json_files(root: Path) -> Iterator[Path]:
    if not _exists(root):
        return
    for current, _directories, files in os.walk(_native_path(root)):
        for filename in files:
            if filename.endswith(".json"):
                yield Path(current) / filename


class FacilityDesignRepository:
    """Filesystem-backed briefs, artifacts, heads, and reference pins."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        lock_stale_seconds: int = FACILITY_DESIGN_LOCK_STALE_SECONDS,
        lock_timeout_seconds: float = FACILITY_DESIGN_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.root = Path(root).resolve()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock_stale_seconds = int(lock_stale_seconds)
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        if self.lock_stale_seconds < 1 or self.lock_timeout_seconds <= 0:
            raise ValueError("Facility design lock limits must be positive.")
        os.makedirs(_native_path(self.root), exist_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_clock_invalid",
                "Facility design repository clock is invalid.",
            )
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _scope(self, tenant_id: str, site_id: str) -> Path:
        tenant = _identifier(tenant_id, "tenantId")
        site = _identifier(site_id, "siteId")
        candidate = self.root / tenant / site / "design-loop"
        root_text = os.path.normcase(os.path.abspath(os.fspath(self.root)))
        candidate_text = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        try:
            contained = os.path.commonpath((root_text, candidate_text)) == root_text
        except ValueError:
            contained = False
        if not contained:
            raise FacilityDesignRepositoryError(
                "facility_design_scope_invalid",
                "Facility design scope escapes its configured root.",
            )
        return candidate

    def _brief_root(self, tenant_id: str, site_id: str, brief_id: str) -> Path:
        return self._scope(tenant_id, site_id) / "briefs" / _identifier(brief_id, "briefId")

    def _brief_revision_path(
        self, tenant_id: str, site_id: str, brief_id: str, revision: str
    ) -> Path:
        return self._brief_root(tenant_id, site_id, brief_id) / "revisions" / f"{_revision(revision, 'briefRevision')}.json"

    def _head_path(self, tenant_id: str, site_id: str, brief_id: str) -> Path:
        return self._brief_root(tenant_id, site_id, brief_id) / "head.json"

    def _artifact_path(
        self,
        tenant_id: str,
        site_id: str,
        artifact_kind: str,
        artifact_id: str,
        artifact_revision: str,
    ) -> Path:
        return (
            self._scope(tenant_id, site_id)
            / "artifacts"
            / _identifier(artifact_kind, "artifactKind")
            / _identifier(artifact_id, "artifactId")
            / f"{_revision(artifact_revision, 'artifactRevision')}.json"
        )

    def _pin_path(
        self,
        tenant_id: str,
        site_id: str,
        artifact_revision: str,
        brief_id: str,
    ) -> Path:
        return (
            self._scope(tenant_id, site_id)
            / "pins"
            / _revision(artifact_revision, "artifactRevision")
            / f"{_identifier(brief_id, 'briefId')}.json"
        )

    def _owner_pin_path(
        self,
        tenant_id: str,
        site_id: str,
        artifact_revision: str,
        owner_kind: str,
        owner_id: str,
    ) -> Path:
        return (
            self._scope(tenant_id, site_id)
            / "pins"
            / _revision(artifact_revision, "artifactRevision")
            / f"{_identifier(owner_kind, 'ownerKind')}--{_identifier(owner_id, 'ownerId')}.json"
        )

    def _run_path(self, tenant_id: str, site_id: str, run_id: str) -> Path:
        return (
            self._scope(tenant_id, site_id)
            / "runs"
            / f"{_identifier(run_id, 'runId')}.json"
        )

    def _run_tombstone_path(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> Path:
        return (
            self._scope(tenant_id, site_id)
            / "run-tombstones"
            / f"{_identifier(run_id, 'runId')}.json"
        )

    def _transaction_root(
        self, tenant_id: str, site_id: str, transaction_id: str
    ) -> Path:
        return (
            self._scope(tenant_id, site_id)
            / "transactions"
            / _identifier(transaction_id, "transactionId")
        )

    def _transaction_revision_path(
        self,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        transaction_revision: str,
    ) -> Path:
        return (
            self._transaction_root(tenant_id, site_id, transaction_id)
            / "revisions"
            / f"{_revision(transaction_revision, 'transactionRevision')}.json"
        )

    def _transaction_head_path(
        self, tenant_id: str, site_id: str, transaction_id: str
    ) -> Path:
        return self._transaction_root(tenant_id, site_id, transaction_id) / "head.json"

    def _lock_path(self, tenant_id: str, site_id: str) -> Path:
        return self._scope(tenant_id, site_id) / ".write.lock"

    @staticmethod
    def _replace_file(source: str, destination: str) -> None:
        for attempt in range(6):
            try:
                os.replace(source, destination)
                return
            except (FileNotFoundError, PermissionError):
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))

    @staticmethod
    def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
        payload = canonical_design_bytes(value)
        os.makedirs(_native_path(path.parent), exist_ok=True)
        temporary_name: str | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=_native_path(path.parent)
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            FacilityDesignRepository._replace_file(
                temporary_name, _native_path(path)
            )
            temporary_name = None
        except OSError as exc:
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_store_write_failed",
                "Facility design record could not be written atomically.",
            ) from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    @contextmanager
    def _write_lock(self, tenant_id: str, site_id: str) -> Iterator[None]:
        path = self._lock_path(tenant_id, site_id)
        os.makedirs(_native_path(path.parent), exist_ok=True)
        token = f"fdl-lock-{uuid4().hex}"
        deadline = time.monotonic() + self.lock_timeout_seconds
        metadata = {
            "recordKind": "facility_design_write_lock",
            "ownerToken": token,
            "processId": os.getpid(),
            "createdAt": _timestamp(self._now()),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        while True:
            try:
                descriptor = os.open(_native_path(path), flags, 0o600)
                try:
                    os.write(descriptor, canonical_design_bytes(metadata))
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                break
            except FileExistsError:
                try:
                    age = max(0.0, time.time() - os.stat(_native_path(path)).st_mtime)
                except FileNotFoundError:
                    continue
                if age >= self.lock_stale_seconds:
                    stale = path.with_name(f"{path.name}.stale-{uuid4().hex}")
                    try:
                        os.replace(_native_path(path), _native_path(stale))
                        os.unlink(_native_path(stale))
                    except (FileNotFoundError, OSError):
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise FacilityDesignRepositoryConflictError(
                        "facility_design_write_lock_timeout",
                        "Facility design storage is busy.",
                    )
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                current = _read_json(path, missing_code="facility_design_lock_missing")
            except FacilityDesignRepositoryError:
                current = None
            if current is not None and current.get("ownerToken") == token:
                try:
                    os.unlink(_native_path(path))
                except FileNotFoundError:
                    pass

    def _brief_envelope(self, brief: Mapping[str, Any]) -> dict[str, Any]:
        record = validate_facility_design_brief(brief)
        return {
            "recordKind": "facility_design_brief",
            "briefRevision": record["briefRevision"],
            "brief": record,
        }

    def _read_head(self, tenant_id: str, site_id: str, brief_id: str) -> dict[str, Any]:
        head = _read_json(
            self._head_path(tenant_id, site_id, brief_id),
            missing_code="facility_design_brief_not_found",
        )
        required = {
            "recordKind",
            "briefId",
            "briefRevision",
            "briefSemanticFingerprint",
            "layoutId",
            "status",
            "updatedAt",
            "headRevision",
        }
        if set(head) != required or head.get("recordKind") != "facility_design_brief_head":
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_head_corrupt",
                "Facility design brief head is invalid.",
            )
        expected = deepcopy(head)
        recorded = expected.pop("headRevision")
        if recorded != design_revision(expected):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_head_revision_mismatch",
                "Facility design brief head failed its integrity check.",
            )
        return head

    def _head_for(self, brief: Mapping[str, Any]) -> dict[str, Any]:
        body = brief["semanticBody"]
        head = {
            "recordKind": "facility_design_brief_head",
            "briefId": brief["briefId"],
            "briefRevision": brief["briefRevision"],
            "briefSemanticFingerprint": brief["briefSemanticFingerprint"],
            "layoutId": body["layoutId"],
            "status": body["status"],
            "updatedAt": _timestamp(self._now()),
        }
        head["headRevision"] = design_revision(head)
        return head

    def _active_brief_count(self, tenant_id: str, site_id: str, layout_id: str) -> int:
        heads_root = self._scope(tenant_id, site_id) / "briefs"
        if not _exists(heads_root):
            return 0
        count = 0
        for path in _walk_json_files(heads_root):
            if path.name != "head.json":
                continue
            try:
                head = _read_json(path, missing_code="facility_design_brief_not_found")
            except FacilityDesignRepositoryError:
                continue
            if head.get("layoutId") == layout_id and head.get("status") == "active":
                count += 1
        return count

    def create_brief(
        self,
        *,
        tenant_id: str,
        site_id: str,
        brief: Mapping[str, Any],
        artifact_refs: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        record = validate_facility_design_brief(brief)
        if record["parentBriefRevision"] is not None:
            raise FacilityDesignRepositoryConflictError(
                "facility_design_brief_parent_invalid",
                "Initial Facility design brief cannot have a parent revision.",
            )
        with self._write_lock(tenant_id, site_id):
            head_path = self._head_path(tenant_id, site_id, record["briefId"])
            if _exists(head_path):
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_brief_exists",
                    "Facility design brief already exists.",
                )
            if (
                record["semanticBody"]["status"] == "active"
                and self._active_brief_count(
                    tenant_id, site_id, record["semanticBody"]["layoutId"]
                )
                >= FACILITY_DESIGN_MAXIMUM_ACTIVE_BRIEFS_PER_LAYOUT
            ):
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_active_brief_limit_exceeded",
                    "This layout already has the maximum number of active design briefs.",
                )
            self._atomic_write(
                self._brief_revision_path(
                    tenant_id, site_id, record["briefId"], record["briefRevision"]
                ),
                self._brief_envelope(record),
            )
            self._atomic_write(head_path, self._head_for(record))
            self._replace_pins_locked(
                tenant_id, site_id, record["briefId"], artifact_refs
            )
        return self.get_brief(tenant_id, site_id, record["briefId"])

    def advance_brief(
        self,
        *,
        tenant_id: str,
        site_id: str,
        brief: Mapping[str, Any],
        expected_brief_revision: str,
        artifact_refs: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        record = validate_facility_design_brief(brief)
        expected = _revision(expected_brief_revision, "expectedBriefRevision")
        with self._write_lock(tenant_id, site_id):
            head = self._read_head(tenant_id, site_id, record["briefId"])
            if head["briefRevision"] != expected:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_brief_revision_conflict",
                    "Facility design brief changed after it was read.",
                    details={"currentBriefRevision": head["briefRevision"]},
                )
            if record["parentBriefRevision"] != expected:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_brief_parent_invalid",
                    "New brief revision must name the current head as its parent.",
                )
            revision_dir = self._brief_root(
                tenant_id, site_id, record["briefId"]
            ) / "revisions"
            revision_count = (
                sum(1 for _path in _walk_json_files(revision_dir))
                if _exists(revision_dir)
                else 0
            )
            if revision_count >= FACILITY_DESIGN_MAXIMUM_REVISIONS_PER_BRIEF:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_brief_revision_limit_exceeded",
                    "Facility design brief reached its immutable revision limit.",
                )
            path = self._brief_revision_path(
                tenant_id, site_id, record["briefId"], record["briefRevision"]
            )
            if _exists(path):
                existing = _read_json(path, missing_code="facility_design_brief_not_found")
                if existing != self._brief_envelope(record):
                    raise FacilityDesignRepositoryIntegrityError(
                        "facility_design_brief_revision_collision",
                        "Immutable Facility design brief revision conflicts with existing bytes.",
                    )
            else:
                self._atomic_write(path, self._brief_envelope(record))
            self._atomic_write(
                self._head_path(tenant_id, site_id, record["briefId"]),
                self._head_for(record),
            )
            self._replace_pins_locked(
                tenant_id, site_id, record["briefId"], artifact_refs
            )
        return self.get_brief(tenant_id, site_id, record["briefId"])

    def get_brief(
        self,
        tenant_id: str,
        site_id: str,
        brief_id: str,
        *,
        brief_revision: str | None = None,
    ) -> dict[str, Any]:
        head = self._read_head(tenant_id, site_id, brief_id)
        revision = (
            _revision(brief_revision, "briefRevision")
            if brief_revision is not None
            else head["briefRevision"]
        )
        envelope = _read_json(
            self._brief_revision_path(tenant_id, site_id, brief_id, revision),
            missing_code="facility_design_brief_revision_not_found",
        )
        if set(envelope) != {"recordKind", "briefRevision", "brief"}:
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_brief_record_corrupt",
                "Facility design brief envelope is invalid.",
            )
        record = validate_facility_design_brief(envelope["brief"])
        if envelope["briefRevision"] != record["briefRevision"] or revision != record["briefRevision"]:
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_brief_revision_mismatch",
                "Facility design brief path, envelope, and content revisions differ.",
            )
        return {"head": deepcopy(head), "brief": record}

    def store_artifact(
        self,
        *,
        tenant_id: str,
        site_id: str,
        artifact_kind: str,
        artifact_id: str,
        artifact_revision: str,
        artifact: Mapping[str, Any],
    ) -> dict[str, Any]:
        artifact_kind = _identifier(artifact_kind, "artifactKind")
        artifact_id = _identifier(artifact_id, "artifactId")
        artifact_revision = _revision(artifact_revision, "artifactRevision")
        envelope = {
            "recordKind": "facility_design_artifact",
            "artifactKind": artifact_kind,
            "artifactId": artifact_id,
            "artifactRevision": artifact_revision,
            "artifactHash": design_revision(artifact),
            "artifact": deepcopy(dict(artifact)),
            "storedAt": _timestamp(self._now()),
        }
        path = self._artifact_path(
            tenant_id, site_id, artifact_kind, artifact_id, artifact_revision
        )
        with self._write_lock(tenant_id, site_id):
            if _exists(path):
                current = _read_json(path, missing_code="facility_design_artifact_not_found")
                comparable = deepcopy(dict(current))
                comparable["storedAt"] = envelope["storedAt"]
                if comparable != envelope:
                    raise FacilityDesignRepositoryIntegrityError(
                        "facility_design_artifact_revision_collision",
                        "Immutable Facility design artifact conflicts with existing bytes.",
                    )
                return deepcopy(current)
            else:
                self._atomic_write(path, envelope)
        return deepcopy(envelope)

    def get_artifact(
        self,
        tenant_id: str,
        site_id: str,
        artifact_kind: str,
        artifact_id: str,
        artifact_revision: str,
    ) -> dict[str, Any]:
        envelope = _read_json(
            self._artifact_path(
                tenant_id, site_id, artifact_kind, artifact_id, artifact_revision
            ),
            missing_code="facility_design_artifact_not_found",
        )
        expected_fields = {
            "recordKind",
            "artifactKind",
            "artifactId",
            "artifactRevision",
            "artifactHash",
            "artifact",
            "storedAt",
        }
        if (
            set(envelope) != expected_fields
            or envelope.get("recordKind") != "facility_design_artifact"
            or envelope.get("artifactKind") != artifact_kind
            or envelope.get("artifactId") != artifact_id
            or envelope.get("artifactRevision") != artifact_revision
        ):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_artifact_record_corrupt",
                "Facility design artifact envelope is invalid.",
            )
        artifact = envelope.get("artifact")
        if not isinstance(artifact, Mapping) or envelope.get("artifactHash") != design_revision(artifact):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_artifact_integrity_mismatch",
                "Facility design artifact failed its integrity check.",
            )
        return deepcopy(envelope)

    def list_brief_heads(
        self,
        tenant_id: str,
        site_id: str,
        *,
        layout_id: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        if layout_id is not None:
            layout_id = _identifier(layout_id, "layoutId")
        root = self._scope(tenant_id, site_id) / "briefs"
        if not _exists(root):
            return []
        heads = []
        for path in _walk_json_files(root):
            if path.name != "head.json":
                continue
            head = _read_json(path, missing_code="facility_design_brief_not_found")
            if layout_id is not None and head.get("layoutId") != layout_id:
                continue
            if active_only and head.get("status") != "active":
                continue
            heads.append(self._read_head(tenant_id, site_id, str(head.get("briefId"))))
        return sorted(heads, key=lambda item: item["briefId"])

    def _replace_pins_locked(
        self,
        tenant_id: str,
        site_id: str,
        brief_id: str,
        artifact_refs: Sequence[Mapping[str, Any]],
    ) -> None:
        brief_id = _identifier(brief_id, "briefId")
        scope = self._scope(tenant_id, site_id)
        pins_root = scope / "pins"
        if _exists(pins_root):
            for path in _walk_json_files(pins_root):
                if path.name != f"{brief_id}.json":
                    continue
                try:
                    os.unlink(_native_path(path))
                except FileNotFoundError:
                    pass
        for raw_ref in artifact_refs:
            if not isinstance(raw_ref, Mapping):
                raise FacilityDesignRepositoryError(
                    "facility_design_artifact_ref_invalid",
                    "Artifact reference must be an object.",
                )
            ref = deepcopy(dict(raw_ref))
            if set(ref) != {"artifactKind", "artifactId", "artifactRevision"}:
                raise FacilityDesignRepositoryError(
                    "facility_design_artifact_ref_invalid",
                    "Artifact reference fields are invalid.",
                )
            artifact_kind = _identifier(ref["artifactKind"], "artifactKind")
            artifact_id = _identifier(ref["artifactId"], "artifactId")
            artifact_revision = _revision(ref["artifactRevision"], "artifactRevision")
            artifact_path = self._artifact_path(
                tenant_id, site_id, artifact_kind, artifact_id, artifact_revision
            )
            if not _exists(artifact_path):
                raise FacilityDesignRepositoryNotFoundError(
                    "facility_design_artifact_not_found",
                    "Cannot pin a missing Facility design artifact.",
                    details={"artifactId": artifact_id},
                )
            pin = {
                "recordKind": "facility_design_artifact_pin",
                "briefId": brief_id,
                "artifactKind": artifact_kind,
                "artifactId": artifact_id,
                "artifactRevision": artifact_revision,
                "pinnedAt": _timestamp(self._now()),
            }
            pin["pinRevision"] = design_revision(pin)
            self._atomic_write(
                self._pin_path(
                    tenant_id, site_id, artifact_revision, brief_id
                ),
                pin,
            )

    def _replace_owner_pins_locked(
        self,
        tenant_id: str,
        site_id: str,
        owner_kind: str,
        owner_id: str,
        artifact_refs: Sequence[Mapping[str, Any]],
        *,
        previous_artifact_refs: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        owner_kind = _identifier(owner_kind, "ownerKind")
        owner_id = _identifier(owner_id, "ownerId")
        filename = f"{owner_kind}--{owner_id}.json"
        desired_by_revision: dict[str, tuple[str, str]] = {}
        for raw_ref in artifact_refs:
            if not isinstance(raw_ref, Mapping) or set(raw_ref) != {
                "artifactKind",
                "artifactId",
                "artifactRevision",
            }:
                raise FacilityDesignRepositoryError(
                    "facility_design_artifact_ref_invalid",
                    "Artifact reference fields are invalid.",
                )
            ref = deepcopy(dict(raw_ref))
            artifact_kind = _identifier(ref["artifactKind"], "artifactKind")
            artifact_id = _identifier(ref["artifactId"], "artifactId")
            artifact_revision = _revision(
                ref["artifactRevision"], "artifactRevision"
            )
            desired_by_revision[artifact_revision] = (
                artifact_kind,
                artifact_id,
            )
            if not _exists(
                self._artifact_path(
                    tenant_id,
                    site_id,
                    artifact_kind,
                    artifact_id,
                    artifact_revision,
                )
            ):
                raise FacilityDesignRepositoryNotFoundError(
                    "facility_design_artifact_not_found",
                    "Cannot pin a missing Facility design artifact.",
                    details={"artifactId": artifact_id},
                )

        existing_paths: list[Path] = []
        if previous_artifact_refs is None:
            pins_root = self._scope(tenant_id, site_id) / "pins"
            if _exists(pins_root):
                existing_paths = [
                    path
                    for path in _walk_json_files(pins_root)
                    if path.name == filename
                ]
        else:
            for raw_ref in previous_artifact_refs:
                if not isinstance(raw_ref, Mapping) or set(raw_ref) != {
                    "artifactKind",
                    "artifactId",
                    "artifactRevision",
                }:
                    raise FacilityDesignRepositoryError(
                        "facility_design_artifact_ref_invalid",
                        "Previous artifact reference fields are invalid.",
                    )
                revision = _revision(
                    raw_ref["artifactRevision"], "artifactRevision"
                )
                existing_paths.append(
                    self._owner_pin_path(
                        tenant_id,
                        site_id,
                        revision,
                        owner_kind,
                        owner_id,
                    )
                )

        for path in set(existing_paths):
            if path.parent.name in desired_by_revision:
                continue
            try:
                os.unlink(_native_path(path))
            except FileNotFoundError:
                pass

        for artifact_revision, (
            artifact_kind,
            artifact_id,
        ) in desired_by_revision.items():
            pin = {
                "recordKind": "facility_design_artifact_pin",
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "artifactKind": artifact_kind,
                "artifactId": artifact_id,
                "artifactRevision": artifact_revision,
                "pinnedAt": _timestamp(self._now()),
            }
            pin["pinRevision"] = design_revision(pin)
            path = self._owner_pin_path(
                tenant_id,
                site_id,
                artifact_revision,
                owner_kind,
                owner_id,
            )
            if _exists(path):
                current = _read_json(
                    path,
                    missing_code="facility_design_artifact_pin_not_found",
                )
                if (
                    current.get("recordKind")
                    == "facility_design_artifact_pin"
                    and current.get("ownerKind") == owner_kind
                    and current.get("ownerId") == owner_id
                    and current.get("artifactKind") == artifact_kind
                    and current.get("artifactId") == artifact_id
                    and current.get("artifactRevision")
                    == artifact_revision
                    and current.get("pinRevision")
                    == design_revision({
                        key: value
                        for key, value in current.items()
                        if key != "pinRevision"
                    })
                ):
                    continue
            self._atomic_write(path, pin)

    def pin_artifacts(
        self,
        *,
        tenant_id: str,
        site_id: str,
        owner_kind: str,
        owner_id: str,
        artifact_refs: Sequence[Mapping[str, Any]],
    ) -> None:
        with self._write_lock(tenant_id, site_id):
            self._replace_owner_pins_locked(
                tenant_id, site_id, owner_kind, owner_id, artifact_refs
            )

    def pin_brief_artifacts(
        self,
        *,
        tenant_id: str,
        site_id: str,
        brief_id: str,
        artifact_refs: Sequence[Mapping[str, Any]],
    ) -> None:
        """Replace durable pins owned by an active brief head."""

        with self._write_lock(tenant_id, site_id):
            self._replace_pins_locked(
                tenant_id, site_id, brief_id, artifact_refs
            )

    def release_owner_pins(
        self,
        *,
        tenant_id: str,
        site_id: str,
        owner_kind: str,
        owner_id: str,
    ) -> int:
        owner_kind = _identifier(owner_kind, "ownerKind")
        owner_id = _identifier(owner_id, "ownerId")
        filename = f"{owner_kind}--{owner_id}.json"
        removed = 0
        with self._write_lock(tenant_id, site_id):
            root = self._scope(tenant_id, site_id) / "pins"
            if not _exists(root):
                return 0
            for path in _walk_json_files(root):
                if path.name != filename:
                    continue
                try:
                    os.unlink(_native_path(path))
                    removed += 1
                except FileNotFoundError:
                    pass
        return removed

    @staticmethod
    def _run_envelope(run: Mapping[str, Any]) -> dict[str, Any]:
        body = deepcopy(dict(run))
        return {
            "recordKind": "facility_design_run",
            "runRevision": design_revision(body),
            "run": body,
        }

    @staticmethod
    def _validate_run_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(value, Mapping)
            or set(value) != {"recordKind", "runRevision", "run"}
            or value.get("recordKind") != "facility_design_run"
            or not isinstance(value.get("run"), Mapping)
        ):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_run_record_corrupt",
                "Facility design run envelope is invalid.",
            )
        run = deepcopy(dict(value["run"]))
        for field in ("runId", "tenantId", "siteId", "layoutId", "briefId"):
            _identifier(run.get(field), field)
        if value.get("runRevision") != design_revision(run):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_run_revision_mismatch",
                "Facility design run failed its integrity check.",
            )
        return {"recordKind": "facility_design_run", "runRevision": value["runRevision"], "run": run}

    def create_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run: Mapping[str, Any],
        artifact_refs: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        envelope = self._validate_run_envelope(self._run_envelope(run))
        if envelope["run"]["tenantId"] != tenant_id or envelope["run"]["siteId"] != site_id:
            raise FacilityDesignRepositoryConflictError(
                "facility_design_run_scope_mismatch",
                "Facility design run scope does not match its repository path.",
            )
        path = self._run_path(tenant_id, site_id, envelope["run"]["runId"])
        with self._write_lock(tenant_id, site_id):
            if _exists(path) or _exists(
                self._run_tombstone_path(
                    tenant_id, site_id, envelope["run"]["runId"]
                )
            ):
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_run_exists",
                    "Facility design run already exists.",
                )
            self._atomic_write(path, envelope)
            self._replace_owner_pins_locked(
                tenant_id,
                site_id,
                "run",
                envelope["run"]["runId"],
                artifact_refs,
            )
        return deepcopy(envelope)

    def get_run(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        path = self._run_path(tenant_id, site_id, run_id)
        if not _exists(path):
            tombstone_path = self._run_tombstone_path(
                tenant_id, site_id, run_id
            )
            if _exists(tombstone_path):
                tombstone = self.get_run_tombstone(
                    tenant_id, site_id, run_id
                )
                raise FacilityDesignRepositoryNotFoundError(
                    "facility_design_run_expired",
                    "Facility design run expired; retained brief and transaction artifacts remain available.",
                    details={"tombstone": tombstone},
                )
        value = _read_json(path, missing_code="facility_design_run_not_found")
        return self._validate_run_envelope(value)

    def update_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run: Mapping[str, Any],
        expected_run_revision: str,
        artifact_refs: Sequence[Mapping[str, Any]] = (),
        previous_artifact_refs: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        expected = _revision(expected_run_revision, "expectedRunRevision")
        next_envelope = self._validate_run_envelope(self._run_envelope(run))
        run_id = next_envelope["run"]["runId"]
        with self._write_lock(tenant_id, site_id):
            current = self._validate_run_envelope(
                _read_json(
                    self._run_path(tenant_id, site_id, run_id),
                    missing_code="facility_design_run_not_found",
                )
            )
            if current["runRevision"] != expected:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_run_revision_conflict",
                    "Facility design run changed after it was read.",
                    details={"currentRunRevision": current["runRevision"]},
                )
            for field in (
                "schemaVersion",
                "runId",
                "tenantId",
                "siteId",
                "workspaceId",
                "layoutId",
                "briefId",
                "createdAt",
            ):
                if next_envelope["run"].get(field) != current["run"].get(field):
                    raise FacilityDesignRepositoryConflictError(
                        "facility_design_run_immutable_field_changed",
                        f"Facility design run field {field} is immutable.",
                    )
            self._atomic_write(
                self._run_path(tenant_id, site_id, run_id), next_envelope
            )
            self._replace_owner_pins_locked(
                tenant_id,
                site_id,
                "run",
                run_id,
                artifact_refs,
                previous_artifact_refs=previous_artifact_refs,
            )
        return deepcopy(next_envelope)

    @staticmethod
    def _run_tombstone(
        run_envelope: Mapping[str, Any], *, expired_at: datetime
    ) -> dict[str, Any]:
        run = run_envelope["run"]
        record = {
            "recordKind": "facility_design_run_tombstone",
            "runId": run["runId"],
            "runRevision": run_envelope["runRevision"],
            "tenantId": run["tenantId"],
            "siteId": run["siteId"],
            "layoutId": run["layoutId"],
            "briefId": run["briefId"],
            "priorStatus": run["status"],
            "terminalReason": run.get("terminalReason"),
            "expiredAt": _timestamp(expired_at),
            "deleteAfter": _timestamp(
                expired_at
                + timedelta(seconds=FACILITY_DESIGN_RUN_TOMBSTONE_SECONDS)
            ),
        }
        record["tombstoneRevision"] = design_revision(record)
        return record

    @staticmethod
    def _validate_run_tombstone(value: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "recordKind",
            "runId",
            "runRevision",
            "tenantId",
            "siteId",
            "layoutId",
            "briefId",
            "priorStatus",
            "terminalReason",
            "expiredAt",
            "deleteAfter",
            "tombstoneRevision",
        }
        record = deepcopy(dict(value))
        if set(record) != expected or record.get("recordKind") != "facility_design_run_tombstone":
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_run_tombstone_corrupt",
                "Facility design run tombstone is invalid.",
            )
        for field in ("runId", "tenantId", "siteId", "layoutId", "briefId", "priorStatus"):
            _identifier(record.get(field), field)
        _revision(record.get("runRevision"), "runRevision")
        _parse_timestamp(record.get("expiredAt"), "expiredAt")
        _parse_timestamp(record.get("deleteAfter"), "deleteAfter")
        unsigned = deepcopy(record)
        recorded = unsigned.pop("tombstoneRevision", None)
        if recorded != design_revision(unsigned):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_run_tombstone_revision_mismatch",
                "Facility design run tombstone failed its integrity check.",
            )
        return record

    def get_run_tombstone(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        return self._validate_run_tombstone(
            _read_json(
                self._run_tombstone_path(tenant_id, site_id, run_id),
                missing_code="facility_design_run_tombstone_not_found",
            )
        )

    def expire_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        run_id: str,
        expected_run_revision: str | None = None,
    ) -> dict[str, Any]:
        """Expire one idle run atomically and release only run-owned pins."""

        now = self._now()
        path = self._run_path(tenant_id, site_id, run_id)
        tombstone_path = self._run_tombstone_path(
            tenant_id, site_id, run_id
        )
        with self._write_lock(tenant_id, site_id):
            if not _exists(path) and _exists(tombstone_path):
                return self._validate_run_tombstone(
                    _read_json(
                        tombstone_path,
                        missing_code="facility_design_run_tombstone_not_found",
                    )
                )
            envelope = self._validate_run_envelope(
                _read_json(path, missing_code="facility_design_run_not_found")
            )
            if expected_run_revision is not None and envelope["runRevision"] != _revision(
                expected_run_revision, "expectedRunRevision"
            ):
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_run_revision_conflict",
                    "Facility design run changed before expiry.",
                    details={"currentRunRevision": envelope["runRevision"]},
                )
            if _parse_timestamp(envelope["run"]["expiresAt"], "expiresAt") > now:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_run_not_expired",
                    "Facility design run has not reached its idle expiry.",
                )
            tombstone = self._run_tombstone(envelope, expired_at=now)
            self._atomic_write(tombstone_path, tombstone)
            try:
                os.unlink(_native_path(path))
            except FileNotFoundError:
                pass
            self._replace_owner_pins_locked(
                tenant_id, site_id, "run", run_id, ()
            )
        return tombstone

    def collect_expired_run_tombstones(
        self, tenant_id: str, site_id: str
    ) -> list[str]:
        """Delete tombstones only after their fixed 30-day retention."""

        removed: list[str] = []
        now = self._now()
        with self._write_lock(tenant_id, site_id):
            root = self._scope(tenant_id, site_id) / "run-tombstones"
            if not _exists(root):
                return []
            for path in sorted(_walk_json_files(root), key=lambda item: item.name):
                tombstone = self._validate_run_tombstone(
                    _read_json(
                        path,
                        missing_code="facility_design_run_tombstone_not_found",
                    )
                )
                if _parse_timestamp(tombstone["deleteAfter"], "deleteAfter") > now:
                    continue
                try:
                    os.unlink(_native_path(path))
                except FileNotFoundError:
                    continue
                removed.append(tombstone["runId"])
        return removed

    @staticmethod
    def _transaction_envelope(transaction: Mapping[str, Any]) -> dict[str, Any]:
        body = deepcopy(dict(transaction))
        revision = body.get("transactionRevision")
        if revision is None:
            body["transactionRevision"] = ""
            unsigned = deepcopy(body)
            unsigned.pop("transactionRevision")
            body["transactionRevision"] = design_revision(unsigned)
        return {
            "recordKind": "facility_design_transaction",
            "transactionRevision": body["transactionRevision"],
            "transaction": body,
        }

    @staticmethod
    def _validate_transaction_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(value, Mapping)
            or set(value) != {"recordKind", "transactionRevision", "transaction"}
            or value.get("recordKind") != "facility_design_transaction"
            or not isinstance(value.get("transaction"), Mapping)
        ):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_transaction_record_corrupt",
                "Facility design transaction envelope is invalid.",
            )
        transaction = deepcopy(dict(value["transaction"]))
        for field in ("transactionId", "designRunId", "layoutId", "status"):
            _identifier(transaction.get(field), field)
        unsigned = deepcopy(transaction)
        recorded = unsigned.pop("transactionRevision", None)
        if (
            recorded != value.get("transactionRevision")
            or recorded != design_revision(unsigned)
        ):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_transaction_revision_mismatch",
                "Facility design transaction failed its integrity check.",
            )
        return {
            "recordKind": "facility_design_transaction",
            "transactionRevision": recorded,
            "transaction": transaction,
        }

    def create_transaction(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction: Mapping[str, Any],
        artifact_refs: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        envelope = self._validate_transaction_envelope(
            self._transaction_envelope(transaction)
        )
        body = envelope["transaction"]
        revision_path = self._transaction_revision_path(
            tenant_id, site_id, body["transactionId"], body["transactionRevision"]
        )
        head_path = self._transaction_head_path(
            tenant_id, site_id, body["transactionId"]
        )
        head = {
            "recordKind": "facility_design_transaction_head",
            "transactionId": body["transactionId"],
            "transactionRevision": body["transactionRevision"],
            "designRunId": body["designRunId"],
            "layoutId": body["layoutId"],
            "status": body["status"],
            "updatedAt": body["updatedAt"],
        }
        head["headRevision"] = design_revision(head)
        with self._write_lock(tenant_id, site_id):
            if _exists(head_path):
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_transaction_exists",
                    "Facility design transaction already exists.",
                )
            self._atomic_write(revision_path, envelope)
            self._atomic_write(head_path, head)
            self._replace_owner_pins_locked(
                tenant_id,
                site_id,
                "transaction",
                body["transactionId"],
                artifact_refs,
            )
        return deepcopy(envelope)

    def get_transaction(
        self,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        *,
        transaction_revision: str | None = None,
    ) -> dict[str, Any]:
        head = _read_json(
            self._transaction_head_path(tenant_id, site_id, transaction_id),
            missing_code="facility_design_transaction_not_found",
        )
        unsigned_head = deepcopy(head)
        recorded_head = unsigned_head.pop("headRevision", None)
        if (
            head.get("recordKind") != "facility_design_transaction_head"
            or recorded_head != design_revision(unsigned_head)
        ):
            raise FacilityDesignRepositoryIntegrityError(
                "facility_design_transaction_head_corrupt",
                "Facility design transaction head is invalid.",
            )
        revision = (
            _revision(transaction_revision, "transactionRevision")
            if transaction_revision is not None
            else _revision(head.get("transactionRevision"), "transactionRevision")
        )
        envelope = _read_json(
            self._transaction_revision_path(
                tenant_id, site_id, transaction_id, revision
            ),
            missing_code="facility_design_transaction_revision_not_found",
        )
        return self._validate_transaction_envelope(envelope)

    def advance_transaction(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction: Mapping[str, Any],
        expected_transaction_revision: str,
        artifact_refs: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        expected = _revision(
            expected_transaction_revision, "expectedTransactionRevision"
        )
        body = deepcopy(dict(transaction))
        body.pop("transactionRevision", None)
        envelope = self._validate_transaction_envelope(
            self._transaction_envelope(body)
        )
        body = envelope["transaction"]
        transaction_id = body["transactionId"]
        with self._write_lock(tenant_id, site_id):
            current = self.get_transaction(
                tenant_id, site_id, transaction_id
            )
            if current["transactionRevision"] != expected:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_transaction_revision_conflict",
                    "Facility design transaction changed after it was read.",
                    details={
                        "currentTransactionRevision": current[
                            "transactionRevision"
                        ]
                    },
                )
            for field in (
                "schemaVersion",
                "transactionId",
                "designRunId",
                "layoutId",
                "rootUndoFrameRef",
                "createdAt",
            ):
                if body.get(field) != current["transaction"].get(field):
                    raise FacilityDesignRepositoryConflictError(
                        "facility_design_transaction_immutable_field_changed",
                        f"Facility design transaction field {field} is immutable.",
                    )
            revision_path = self._transaction_revision_path(
                tenant_id,
                site_id,
                transaction_id,
                body["transactionRevision"],
            )
            if _exists(revision_path):
                existing = self._validate_transaction_envelope(
                    _read_json(
                        revision_path,
                        missing_code="facility_design_transaction_revision_not_found",
                    )
                )
                if existing != envelope:
                    raise FacilityDesignRepositoryIntegrityError(
                        "facility_design_transaction_revision_collision",
                        "Immutable Facility design transaction revision conflicts with existing bytes.",
                    )
            else:
                self._atomic_write(revision_path, envelope)
            head = {
                "recordKind": "facility_design_transaction_head",
                "transactionId": transaction_id,
                "transactionRevision": body["transactionRevision"],
                "designRunId": body["designRunId"],
                "layoutId": body["layoutId"],
                "status": body["status"],
                "updatedAt": body["updatedAt"],
            }
            head["headRevision"] = design_revision(head)
            self._atomic_write(
                self._transaction_head_path(tenant_id, site_id, transaction_id),
                head,
            )
            self._replace_owner_pins_locked(
                tenant_id,
                site_id,
                "transaction",
                transaction_id,
                artifact_refs,
            )
        return deepcopy(envelope)

    def restore_transaction_head(
        self,
        *,
        tenant_id: str,
        site_id: str,
        transaction_id: str,
        expected_transaction_revision: str,
        restore_transaction_revision: str,
        artifact_refs: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """CAS a failed replacement back to one exact immutable revision."""

        transaction_id = _identifier(transaction_id, "transactionId")
        expected = _revision(
            expected_transaction_revision, "expectedTransactionRevision"
        )
        target = _revision(
            restore_transaction_revision, "restoreTransactionRevision"
        )
        with self._write_lock(tenant_id, site_id):
            current = self.get_transaction(tenant_id, site_id, transaction_id)
            if current["transactionRevision"] != expected:
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_transaction_revision_conflict",
                    "Facility design transaction changed before recovery.",
                    details={
                        "currentTransactionRevision": current[
                            "transactionRevision"
                        ]
                    },
                )
            restored = self.get_transaction(
                tenant_id,
                site_id,
                transaction_id,
                transaction_revision=target,
            )
            body = restored["transaction"]
            if body["status"] != "active":
                raise FacilityDesignRepositoryConflictError(
                    "facility_design_transaction_restore_target_invalid",
                    "Only an active prior proposal transaction can be restored.",
                )
            head = {
                "recordKind": "facility_design_transaction_head",
                "transactionId": transaction_id,
                "transactionRevision": target,
                "designRunId": body["designRunId"],
                "layoutId": body["layoutId"],
                "status": body["status"],
                "updatedAt": body["updatedAt"],
            }
            head["headRevision"] = design_revision(head)
            self._atomic_write(
                self._transaction_head_path(
                    tenant_id, site_id, transaction_id
                ),
                head,
            )
            self._replace_owner_pins_locked(
                tenant_id,
                site_id,
                "transaction",
                transaction_id,
                artifact_refs,
            )
        return deepcopy(restored)

    def artifact_pin_count(
        self, tenant_id: str, site_id: str, artifact_revision: str
    ) -> int:
        path = self._scope(tenant_id, site_id) / "pins" / _revision(
            artifact_revision, "artifactRevision"
        )
        return sum(1 for _path in _walk_json_files(path)) if _exists(path) else 0

    def release_brief_pins(
        self,
        tenant_id: str,
        site_id: str,
        brief_id: str,
    ) -> int:
        brief_id = _identifier(brief_id, "briefId")
        removed = 0
        with self._write_lock(tenant_id, site_id):
            root = self._scope(tenant_id, site_id) / "pins"
            if not _exists(root):
                return 0
            for path in _walk_json_files(root):
                if path.name != f"{brief_id}.json":
                    continue
                try:
                    os.unlink(_native_path(path))
                    removed += 1
                except FileNotFoundError:
                    pass
        return removed

    def collect_unpinned_artifacts(
        self,
        tenant_id: str,
        site_id: str,
        *,
        older_than: datetime,
    ) -> list[dict[str, str]]:
        cutoff = older_than
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        cutoff_epoch = cutoff.astimezone(timezone.utc).timestamp()
        removed: list[dict[str, str]] = []
        with self._write_lock(tenant_id, site_id):
            root = self._scope(tenant_id, site_id) / "artifacts"
            if not _exists(root):
                return []
            for path in _walk_json_files(root):
                revision = path.stem
                try:
                    _revision(revision, "artifactRevision")
                except FacilityDesignRepositoryError:
                    continue
                envelope = _read_json(
                    path,
                    missing_code="facility_design_artifact_not_found",
                )
                stored_epoch = _parse_timestamp(
                    envelope.get("storedAt"), "storedAt"
                ).timestamp()
                if stored_epoch >= cutoff_epoch or self.artifact_pin_count(
                    tenant_id, site_id, revision
                ):
                    continue
                try:
                    os.unlink(_native_path(path))
                except FileNotFoundError:
                    continue
                removed.append(
                    {
                        "artifactKind": str(envelope.get("artifactKind") or ""),
                        "artifactId": str(envelope.get("artifactId") or ""),
                        "artifactRevision": revision,
                    }
                )
        return sorted(
            removed,
            key=lambda item: (
                item["artifactKind"],
                item["artifactId"],
                item["artifactRevision"],
            ),
        )


__all__ = [
    "FACILITY_DESIGN_LOCK_STALE_SECONDS",
    "FACILITY_DESIGN_LOCK_TIMEOUT_SECONDS",
    "FACILITY_DESIGN_MAXIMUM_ACTIVE_BRIEFS_PER_LAYOUT",
    "FACILITY_DESIGN_MAXIMUM_REVISIONS_PER_BRIEF",
    "FacilityDesignRepository",
    "FacilityDesignRepositoryConflictError",
    "FacilityDesignRepositoryError",
    "FacilityDesignRepositoryIntegrityError",
    "FacilityDesignRepositoryNotFoundError",
]
