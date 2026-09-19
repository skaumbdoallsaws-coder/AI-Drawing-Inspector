"""Shared cross-process lease for mutable Facility editor drafts.

Generation and the persistent design loop deliberately share this repository
and its on-disk namespace.  Preview work never calls it.  Browser installation
is coordinated through a single-use adoption record because filesystem writes
and a browser-memory swap cannot be one transaction.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4


FACILITY_DRAFT_LEASE_SCHEMA_VERSION = "facility-draft-lease-v1"
FACILITY_DRAFT_LEASE_IDLE_SECONDS = 24 * 60 * 60
FACILITY_DRAFT_LEASE_RECOVERY_SECONDS = 120
FACILITY_DRAFT_LEASE_LOCK_STALE_SECONDS = 120
FACILITY_DRAFT_LEASE_LOCK_TIMEOUT_SECONDS = 5.0

_OWNER_KINDS = frozenset({"generation_run", "design_run", "manual_write"})
_LEASE_STATUSES = frozenset(
    {"active", "adopting", "review_required", "released", "expired"}
)
_LIVE_STATUSES = frozenset({"active", "adopting", "review_required"})
_ADOPTION_STATUSES = frozenset(
    {
        "prepared",
        "committed",
        "acknowledged",
        "aborted",
        "recovered",
        "undone",
        "saved",
        "conflict",
    }
)


class FacilityDraftLeaseError(RuntimeError):
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


class FacilityDraftLeaseConflictError(FacilityDraftLeaseError):
    pass


class FacilityDraftLeaseIntegrityError(FacilityDraftLeaseError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_value_invalid",
            "Facility draft-lease values must be finite canonical JSON.",
        ) from exc


def _revision(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: Any, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_revision_invalid",
            f"{field} must be a lowercase SHA-256 revision.",
        )
    return text


def _identifier(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 160
        or not text[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@+-")
            for character in text
        )
    ):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_identifier_invalid",
            f"{field} must be a stable ASCII identifier.",
        )
    return text


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_timestamp_invalid",
            f"{field} must be an ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_timestamp_invalid",
            f"{field} must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _native_path(path: Path) -> str:
    text = os.path.abspath(os.fspath(path))
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        if text.startswith("\\\\"):
            return "\\\\?\\UNC\\" + text[2:]
        return "\\\\?\\" + text
    return text


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        with open(_native_path(path), "rb") as handle:
            payload = handle.read()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_record_invalid",
            "Facility draft-lease storage contains invalid JSON.",
        ) from exc
    if not isinstance(value, dict) or payload != _canonical_bytes(value):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_record_not_canonical",
            "Facility draft-lease storage is not canonical.",
        )
    return value


def _prior_owner(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_prior_owner_invalid",
            "priorOwnerRef must be an object or null.",
        )
    expected = {
        "ownerKind",
        "ownerRunId",
        "ownerToken",
        "baseSavedLayoutRevision",
        "currentDraftRevision",
        "acquiredAt",
        "expiresAt",
        "leaseRevision",
    }
    if set(value) != expected or value.get("ownerKind") not in _OWNER_KINDS:
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_prior_owner_invalid",
            "priorOwnerRef fields are invalid.",
        )
    result = deepcopy(dict(value))
    _identifier(result["ownerRunId"], "priorOwnerRef.ownerRunId")
    _identifier(result["ownerToken"], "priorOwnerRef.ownerToken")
    _sha256(result["baseSavedLayoutRevision"], "priorOwnerRef.baseSavedLayoutRevision")
    _sha256(result["currentDraftRevision"], "priorOwnerRef.currentDraftRevision")
    _sha256(result["leaseRevision"], "priorOwnerRef.leaseRevision")
    _parse_timestamp(result["acquiredAt"], "priorOwnerRef.acquiredAt")
    _parse_timestamp(result["expiresAt"], "priorOwnerRef.expiresAt")
    return result


def validate_facility_draft_lease(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_invalid",
            "Facility draft lease must be an object.",
        )
    expected = {
        "schemaVersion",
        "recordKind",
        "tenantId",
        "siteId",
        "layoutId",
        "ownerKind",
        "ownerRunId",
        "ownerToken",
        "baseSavedLayoutRevision",
        "currentDraftRevision",
        "status",
        "reviewReason",
        "priorOwnerRef",
        "acquiredAt",
        "updatedAt",
        "expiresAt",
        "recoveryDeadlineAt",
        "leaseRevision",
    }
    record = deepcopy(dict(value))
    if (
        set(record) != expected
        or record.get("schemaVersion") != FACILITY_DRAFT_LEASE_SCHEMA_VERSION
        or record.get("recordKind") != "facility_draft_lease"
        or record.get("ownerKind") not in _OWNER_KINDS
        or record.get("status") not in _LEASE_STATUSES
    ):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_invalid",
            "Facility draft-lease fields are invalid.",
        )
    for field in ("tenantId", "siteId", "layoutId", "ownerRunId", "ownerToken"):
        _identifier(record[field], field)
    for field in ("baseSavedLayoutRevision", "currentDraftRevision"):
        _sha256(record[field], field)
    for field in ("acquiredAt", "updatedAt", "expiresAt"):
        _parse_timestamp(record[field], field)
    if record["recoveryDeadlineAt"] is not None:
        _parse_timestamp(record["recoveryDeadlineAt"], "recoveryDeadlineAt")
    if record["status"] == "review_required":
        _identifier(record["reviewReason"], "reviewReason")
        if record["recoveryDeadlineAt"] is None:
            raise FacilityDraftLeaseIntegrityError(
                "facility_draft_lease_invalid",
                "A review-required lease must carry a recovery deadline.",
            )
    elif record["reviewReason"] is not None:
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_invalid",
            "reviewReason is allowed only for review-required leases.",
        )
    _prior_owner(record["priorOwnerRef"])
    unsigned = deepcopy(record)
    recorded_revision = unsigned.pop("leaseRevision")
    if recorded_revision != _revision(unsigned):
        raise FacilityDraftLeaseIntegrityError(
            "facility_draft_lease_revision_mismatch",
            "Facility draft lease failed its integrity check.",
        )
    return record


def build_facility_draft_lease(
    *,
    tenant_id: str,
    site_id: str,
    layout_id: str,
    owner_kind: str,
    owner_run_id: str,
    owner_token: str,
    base_saved_layout_revision: str,
    current_draft_revision: str,
    status: str,
    acquired_at: str,
    updated_at: str,
    expires_at: str,
    review_reason: str | None = None,
    prior_owner_ref: Mapping[str, Any] | None = None,
    recovery_deadline_at: str | None = None,
) -> dict[str, Any]:
    value = {
        "schemaVersion": FACILITY_DRAFT_LEASE_SCHEMA_VERSION,
        "recordKind": "facility_draft_lease",
        "tenantId": _identifier(tenant_id, "tenantId"),
        "siteId": _identifier(site_id, "siteId"),
        "layoutId": _identifier(layout_id, "layoutId"),
        "ownerKind": owner_kind,
        "ownerRunId": _identifier(owner_run_id, "ownerRunId"),
        "ownerToken": _identifier(owner_token, "ownerToken"),
        "baseSavedLayoutRevision": _sha256(
            base_saved_layout_revision, "baseSavedLayoutRevision"
        ),
        "currentDraftRevision": _sha256(
            current_draft_revision, "currentDraftRevision"
        ),
        "status": status,
        "reviewReason": review_reason,
        "priorOwnerRef": deepcopy(dict(prior_owner_ref)) if prior_owner_ref else None,
        "acquiredAt": _timestamp(_parse_timestamp(acquired_at, "acquiredAt")),
        "updatedAt": _timestamp(_parse_timestamp(updated_at, "updatedAt")),
        "expiresAt": _timestamp(_parse_timestamp(expires_at, "expiresAt")),
        "recoveryDeadlineAt": (
            _timestamp(_parse_timestamp(recovery_deadline_at, "recoveryDeadlineAt"))
            if recovery_deadline_at is not None
            else None
        ),
    }
    value["leaseRevision"] = _revision(value)
    return validate_facility_draft_lease(value)


def facility_draft_lease_owner_ref(lease: Mapping[str, Any]) -> dict[str, Any]:
    record = validate_facility_draft_lease(lease)
    return {
        "ownerKind": record["ownerKind"],
        "ownerRunId": record["ownerRunId"],
        "ownerToken": record["ownerToken"],
        "baseSavedLayoutRevision": record["baseSavedLayoutRevision"],
        "currentDraftRevision": record["currentDraftRevision"],
        "acquiredAt": record["acquiredAt"],
        "expiresAt": record["expiresAt"],
        "leaseRevision": record["leaseRevision"],
    }


class FacilityDraftLeaseRepository:
    """Own the single Facility draft-lease namespace for all writer kinds."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime | str] | None = None,
        idle_seconds: int = FACILITY_DRAFT_LEASE_IDLE_SECONDS,
        recovery_seconds: int = FACILITY_DRAFT_LEASE_RECOVERY_SECONDS,
        lock_stale_seconds: int = FACILITY_DRAFT_LEASE_LOCK_STALE_SECONDS,
        lock_timeout_seconds: float = FACILITY_DRAFT_LEASE_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.root = Path(root).resolve()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.idle_seconds = int(idle_seconds)
        self.recovery_seconds = int(recovery_seconds)
        self.lock_stale_seconds = int(lock_stale_seconds)
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        if min(self.idle_seconds, self.recovery_seconds, self.lock_stale_seconds) < 1:
            raise ValueError("Facility draft-lease time limits must be positive.")
        os.makedirs(_native_path(self.root), exist_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if isinstance(value, str):
            return _parse_timestamp(value, "clock")
        if not isinstance(value, datetime):
            raise FacilityDraftLeaseIntegrityError(
                "facility_draft_lease_clock_invalid",
                "Facility draft-lease clock returned an unsupported value.",
            )
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _scope(self, tenant_id: str, site_id: str) -> Path:
        tenant = _identifier(tenant_id, "tenantId")
        site = _identifier(site_id, "siteId")
        candidate = self.root / tenant / site / "generation-runs"
        if os.path.commonpath((str(self.root), str(candidate))) != str(self.root):
            raise FacilityDraftLeaseIntegrityError(
                "facility_draft_lease_scope_invalid",
                "Facility draft-lease scope escapes its configured root.",
            )
        return candidate

    def lease_path(self, tenant_id: str, site_id: str, layout_id: str) -> Path:
        return self._scope(tenant_id, site_id) / "leases" / f"{_identifier(layout_id, 'layoutId')}.json"

    def _adoption_path(self, tenant_id: str, site_id: str, adoption_id: str) -> Path:
        return self._scope(tenant_id, site_id) / "lease-adoptions" / f"{_identifier(adoption_id, 'adoptionId')}.json"

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
        payload = _canonical_bytes(value)
        os.makedirs(_native_path(path.parent), exist_ok=True)
        temporary: str | None = None
        try:
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=_native_path(path.parent)
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            FacilityDraftLeaseRepository._replace_file(
                temporary, _native_path(path)
            )
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @contextmanager
    def write_lock(self, tenant_id: str, site_id: str) -> Iterator[None]:
        path = self._lock_path(tenant_id, site_id)
        os.makedirs(_native_path(path.parent), exist_ok=True)
        token = f"facility-lease-lock-{uuid4().hex}"
        deadline = time.monotonic() + self.lock_timeout_seconds
        metadata = {
            "recordKind": "facility_draft_lease_write_lock",
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
                    os.write(descriptor, _canonical_bytes(metadata))
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
                    raise FacilityDraftLeaseConflictError(
                        "facility_draft_lease_lock_timeout",
                        "Facility draft-lease storage is busy.",
                    )
                time.sleep(0.02)
        try:
            yield
        finally:
            current = _read_json(path)
            if current is not None and current.get("ownerToken") == token:
                try:
                    os.unlink(_native_path(path))
                except FileNotFoundError:
                    pass

    def _read_lease(self, tenant_id: str, site_id: str, layout_id: str) -> dict[str, Any] | None:
        value = _read_json(self.lease_path(tenant_id, site_id, layout_id))
        if value is None:
            return None
        return validate_facility_draft_lease(value)

    @staticmethod
    def _live_at(lease: Mapping[str, Any], now: datetime) -> bool:
        if lease["status"] not in _LIVE_STATUSES:
            return False
        deadline = lease.get("recoveryDeadlineAt")
        if lease["status"] == "review_required" and deadline is not None:
            return _parse_timestamp(deadline, "recoveryDeadlineAt") > now
        return _parse_timestamp(lease["expiresAt"], "expiresAt") > now

    def inspect(
        self, tenant_id: str, site_id: str, layout_id: str
    ) -> dict[str, Any]:
        """Read ownership eligibility without mutating an expired lease."""

        lease = self._read_lease(tenant_id, site_id, layout_id)
        now = self._now()
        return {
            "layoutId": _identifier(layout_id, "layoutId"),
            "active": lease is not None and self._live_at(lease, now),
            "expired": lease is not None and not self._live_at(lease, now),
            "lease": deepcopy(lease),
            "observedAt": _timestamp(now),
        }

    def acquire(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        owner_kind: str,
        owner_run_id: str,
        base_saved_layout_revision: str,
        current_draft_revision: str,
        owner_token: str | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self.write_lock(tenant_id, site_id):
            current = self._read_lease(tenant_id, site_id, layout_id)
            if current is not None and self._live_at(current, now):
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_conflict",
                    "Another writer owns this Facility draft.",
                    details={
                        "ownerKind": current["ownerKind"],
                        "ownerRunId": current["ownerRunId"],
                        "leaseRevision": current["leaseRevision"],
                    },
                )
            lease = build_facility_draft_lease(
                tenant_id=tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                owner_kind=owner_kind,
                owner_run_id=owner_run_id,
                owner_token=owner_token or f"lease-{uuid4().hex}",
                base_saved_layout_revision=base_saved_layout_revision,
                current_draft_revision=current_draft_revision,
                status="active",
                acquired_at=_timestamp(now),
                updated_at=_timestamp(now),
                expires_at=_timestamp(now + timedelta(seconds=self.idle_seconds)),
            )
            self._atomic_write(self.lease_path(tenant_id, site_id, layout_id), lease)
            return deepcopy(lease)

    def renew(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        owner_kind: str,
        owner_run_id: str,
        owner_token: str,
        expected_lease_revision: str,
        current_draft_revision: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.write_lock(tenant_id, site_id):
            current = self._require_owner_locked(
                tenant_id,
                site_id,
                layout_id,
                owner_kind=owner_kind,
                owner_run_id=owner_run_id,
                owner_token=owner_token,
                expected_lease_revision=expected_lease_revision,
                allowed_statuses={"active"},
                now=now,
            )
            updated = build_facility_draft_lease(
                **self._build_args(
                    current,
                    current_draft_revision=_sha256(
                        current_draft_revision, "currentDraftRevision"
                    ),
                    updated_at=_timestamp(now),
                    expires_at=_timestamp(now + timedelta(seconds=self.idle_seconds)),
                )
            )
            self._atomic_write(self.lease_path(tenant_id, site_id, layout_id), updated)
            return deepcopy(updated)

    @staticmethod
    def _build_args(lease: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
        values = {
            "tenant_id": lease["tenantId"],
            "site_id": lease["siteId"],
            "layout_id": lease["layoutId"],
            "owner_kind": lease["ownerKind"],
            "owner_run_id": lease["ownerRunId"],
            "owner_token": lease["ownerToken"],
            "base_saved_layout_revision": lease["baseSavedLayoutRevision"],
            "current_draft_revision": lease["currentDraftRevision"],
            "status": lease["status"],
            "review_reason": lease["reviewReason"],
            "prior_owner_ref": lease["priorOwnerRef"],
            "acquired_at": lease["acquiredAt"],
            "updated_at": lease["updatedAt"],
            "expires_at": lease["expiresAt"],
            "recovery_deadline_at": lease["recoveryDeadlineAt"],
        }
        values.update(changes)
        return values

    def _require_owner_locked(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        *,
        owner_kind: str,
        owner_run_id: str,
        owner_token: str,
        expected_lease_revision: str | None,
        allowed_statuses: set[str],
        now: datetime,
    ) -> dict[str, Any]:
        current = self._read_lease(tenant_id, site_id, layout_id)
        if current is None:
            raise FacilityDraftLeaseConflictError(
                "facility_draft_lease_lost",
                "The Facility draft no longer has a writable lease.",
            )
        if expected_lease_revision is not None and current["leaseRevision"] != _sha256(
            expected_lease_revision, "expectedLeaseRevision"
        ):
            raise FacilityDraftLeaseConflictError(
                "facility_draft_lease_revision_conflict",
                "Facility draft lease changed after it was read.",
                details={"currentLeaseRevision": current["leaseRevision"]},
            )
        if (
            current["ownerKind"] != owner_kind
            or current["ownerRunId"] != owner_run_id
            or current["ownerToken"] != owner_token
        ):
            raise FacilityDraftLeaseConflictError(
                "facility_draft_lease_owner_conflict",
                "Facility draft lease belongs to another writer.",
                details={
                    "ownerKind": current["ownerKind"],
                    "ownerRunId": current["ownerRunId"],
                    "leaseRevision": current["leaseRevision"],
                },
            )
        if current["status"] not in allowed_statuses or not self._live_at(current, now):
            raise FacilityDraftLeaseConflictError(
                "facility_draft_lease_not_writable",
                "Facility draft lease is not in a writable state.",
                details={"status": current["status"]},
            )
        return current

    def prepare_adoption(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        design_run_id: str,
        base_saved_layout_revision: str,
        current_draft_revision: str,
        editor_generation_id: str,
        proposal_binding: Mapping[str, Any],
        expected_source_owner: Mapping[str, Any] | None = None,
        root_installation_fingerprint: str,
        previous_installation_fingerprint: str,
        expected_installation_fingerprint: str,
    ) -> dict[str, Any]:
        """Prepare one single-use generation/manual-to-design owner transfer."""

        now = self._now()
        adoption_id = f"fdla-{uuid4().hex}"
        raw_token = f"adopt-{uuid4().hex}{uuid4().hex}"
        with self.write_lock(tenant_id, site_id):
            current = self._read_lease(tenant_id, site_id, layout_id)
            if current is not None and not self._live_at(current, now):
                current = None
            replacement = (
                current is not None
                and current["ownerKind"] == "design_run"
                and current["ownerRunId"] == design_run_id
            )
            target_owner_token = (
                current["ownerToken"]
                if replacement
                else f"lease-{uuid4().hex}"
            )
            if expected_source_owner is None:
                if current is not None:
                    raise FacilityDraftLeaseConflictError(
                        "facility_draft_lease_conflict",
                        "A writer acquired this Facility draft before adoption.",
                    )
                provisional = build_facility_draft_lease(
                    tenant_id=tenant_id,
                    site_id=site_id,
                    layout_id=layout_id,
                    owner_kind="design_run",
                    owner_run_id=design_run_id,
                    owner_token=target_owner_token,
                    base_saved_layout_revision=base_saved_layout_revision,
                    current_draft_revision=current_draft_revision,
                    status="adopting",
                    acquired_at=_timestamp(now),
                    updated_at=_timestamp(now),
                    expires_at=_timestamp(now + timedelta(seconds=self.recovery_seconds)),
                )
                prior = None
            else:
                if current is None:
                    raise FacilityDraftLeaseConflictError(
                        "facility_draft_lease_lost",
                        "The source draft lease was released before adoption.",
                    )
                required_source = {
                    "ownerKind",
                    "ownerRunId",
                    "ownerToken",
                    "leaseRevision",
                }
                if set(expected_source_owner) != required_source or any(
                    current[field] != expected_source_owner[field]
                    for field in required_source
                ):
                    raise FacilityDraftLeaseConflictError(
                        "facility_draft_lease_owner_conflict",
                        "The source draft owner changed before adoption.",
                    )
                if current["status"] != "active":
                    raise FacilityDraftLeaseConflictError(
                        "facility_draft_lease_not_writable",
                        "Only an active source draft can be adopted.",
                    )
                if current["currentDraftRevision"] != _sha256(
                    current_draft_revision, "currentDraftRevision"
                ):
                    raise FacilityDraftLeaseConflictError(
                        "facility_draft_revision_conflict",
                        "The source editor draft changed before adoption.",
                    )
                prior = (
                    deepcopy(current["priorOwnerRef"])
                    if replacement
                    else facility_draft_lease_owner_ref(current)
                )
                provisional = build_facility_draft_lease(
                    **self._build_args(
                        current,
                        status="adopting",
                        updated_at=_timestamp(now),
                        expires_at=_timestamp(now + timedelta(seconds=self.recovery_seconds)),
                    )
                )
            record = {
                "schemaVersion": FACILITY_DRAFT_LEASE_SCHEMA_VERSION,
                "recordKind": "facility_draft_lease_adoption",
                "adoptionId": adoption_id,
                "adoptionRevision": "",
                "layoutId": _identifier(layout_id, "layoutId"),
                "designRunId": _identifier(design_run_id, "designRunId"),
                "adoptionTokenHash": hashlib.sha256(raw_token.encode("ascii")).hexdigest(),
                "targetOwnerToken": target_owner_token,
                "status": "prepared",
                "priorLease": deepcopy(current),
                "preparedLeaseRevision": provisional["leaseRevision"],
                "committedLeaseRevision": None,
                "baseSavedLayoutRevision": _sha256(
                    base_saved_layout_revision, "baseSavedLayoutRevision"
                ),
                "sourceDraftRevision": _sha256(
                    current_draft_revision, "currentDraftRevision"
                ),
                "editorGenerationId": _identifier(
                    editor_generation_id, "editorGenerationId"
                ),
                "proposalBinding": deepcopy(dict(proposal_binding)),
                "rootInstallationFingerprint": _sha256(
                    root_installation_fingerprint, "rootInstallationFingerprint"
                ),
                "previousInstallationFingerprint": _sha256(
                    previous_installation_fingerprint,
                    "previousInstallationFingerprint",
                ),
                "expectedInstallationFingerprint": _sha256(
                    expected_installation_fingerprint,
                    "expectedInstallationFingerprint",
                ),
                "preparedAt": _timestamp(now),
                "updatedAt": _timestamp(now),
                "expiresAt": _timestamp(now + timedelta(seconds=self.recovery_seconds)),
            }
            record["adoptionRevision"] = _revision(
                {key: value for key, value in record.items() if key != "adoptionRevision"}
            )
            self._atomic_write(self.lease_path(tenant_id, site_id, layout_id), provisional)
            self._atomic_write(self._adoption_path(tenant_id, site_id, adoption_id), record)
        return {
            "adoption": deepcopy(record),
            "adoptionToken": raw_token,
            "lease": deepcopy(provisional),
        }

    def _validate_adoption(self, value: Mapping[str, Any]) -> dict[str, Any]:
        expected = {
            "schemaVersion",
            "recordKind",
            "adoptionId",
            "adoptionRevision",
            "layoutId",
            "designRunId",
            "adoptionTokenHash",
            "targetOwnerToken",
            "status",
            "priorLease",
            "preparedLeaseRevision",
            "committedLeaseRevision",
            "baseSavedLayoutRevision",
            "sourceDraftRevision",
            "editorGenerationId",
            "proposalBinding",
            "rootInstallationFingerprint",
            "previousInstallationFingerprint",
            "expectedInstallationFingerprint",
            "preparedAt",
            "updatedAt",
            "expiresAt",
        }
        record = deepcopy(dict(value))
        if (
            set(record) != expected
            or record.get("schemaVersion") != FACILITY_DRAFT_LEASE_SCHEMA_VERSION
            or record.get("recordKind") != "facility_draft_lease_adoption"
            or record.get("status") not in _ADOPTION_STATUSES
            or not isinstance(record.get("proposalBinding"), Mapping)
        ):
            raise FacilityDraftLeaseIntegrityError(
                "facility_draft_lease_adoption_invalid",
                "Facility draft-lease adoption record is invalid.",
            )
        for field in ("adoptionId", "layoutId", "designRunId", "targetOwnerToken", "editorGenerationId"):
            _identifier(record[field], field)
        for field in (
            "adoptionTokenHash",
            "preparedLeaseRevision",
            "baseSavedLayoutRevision",
            "sourceDraftRevision",
            "rootInstallationFingerprint",
            "previousInstallationFingerprint",
            "expectedInstallationFingerprint",
        ):
            _sha256(record[field], field)
        if record["committedLeaseRevision"] is not None:
            _sha256(record["committedLeaseRevision"], "committedLeaseRevision")
        for field in ("preparedAt", "updatedAt", "expiresAt"):
            _parse_timestamp(record[field], field)
        if record["priorLease"] is not None:
            validate_facility_draft_lease(record["priorLease"])
        unsigned = deepcopy(record)
        recorded = unsigned.pop("adoptionRevision")
        if recorded != _revision(unsigned):
            raise FacilityDraftLeaseIntegrityError(
                "facility_draft_lease_adoption_revision_mismatch",
                "Facility draft-lease adoption failed its integrity check.",
            )
        return record

    def _read_adoption(self, tenant_id: str, site_id: str, adoption_id: str) -> dict[str, Any]:
        value = _read_json(self._adoption_path(tenant_id, site_id, adoption_id))
        if value is None:
            raise FacilityDraftLeaseConflictError(
                "facility_draft_lease_adoption_not_found",
                "Facility draft-lease adoption was not found.",
            )
        return self._validate_adoption(value)

    @staticmethod
    def _next_adoption(record: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
        value = deepcopy(dict(record))
        value.update(changes)
        value["adoptionRevision"] = ""
        value["adoptionRevision"] = _revision(
            {key: item for key, item in value.items() if key != "adoptionRevision"}
        )
        return value

    def commit_adoption(
        self,
        *,
        tenant_id: str,
        site_id: str,
        adoption_id: str,
        adoption_token: str,
        expected_adoption_revision: str,
        expected_prepared_lease_revision: str,
        result_draft_revision: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.write_lock(tenant_id, site_id):
            adoption = self._read_adoption(tenant_id, site_id, adoption_id)
            if adoption["adoptionRevision"] != _sha256(
                expected_adoption_revision, "expectedAdoptionRevision"
            ):
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_revision_conflict",
                    "Facility draft adoption changed after it was prepared.",
                )
            if adoption["status"] != "prepared" or _parse_timestamp(
                adoption["expiresAt"], "adoption.expiresAt"
            ) <= now:
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_expired",
                    "Facility draft adoption is no longer committable.",
                )
            if hashlib.sha256(str(adoption_token).encode("ascii")).hexdigest() != adoption[
                "adoptionTokenHash"
            ]:
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_token_invalid",
                    "Facility draft adoption token is invalid.",
                )
            lease = self._read_lease(tenant_id, site_id, adoption["layoutId"])
            if (
                lease is None
                or lease["leaseRevision"] != _sha256(
                    expected_prepared_lease_revision, "expectedPreparedLeaseRevision"
                )
                or lease["leaseRevision"] != adoption["preparedLeaseRevision"]
                or lease["status"] != "adopting"
            ):
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_conflict",
                    "Facility draft owner changed during adoption.",
                )
            committed = build_facility_draft_lease(
                tenant_id=tenant_id,
                site_id=site_id,
                layout_id=adoption["layoutId"],
                owner_kind="design_run",
                owner_run_id=adoption["designRunId"],
                owner_token=adoption["targetOwnerToken"],
                base_saved_layout_revision=adoption["baseSavedLayoutRevision"],
                current_draft_revision=_sha256(
                    result_draft_revision, "resultDraftRevision"
                ),
                status="review_required",
                review_reason="installation_unacknowledged",
                prior_owner_ref=(
                    deepcopy(adoption["priorLease"]["priorOwnerRef"])
                    if adoption["priorLease"] is not None
                    and adoption["priorLease"]["ownerKind"] == "design_run"
                    and adoption["priorLease"]["ownerRunId"]
                    == adoption["designRunId"]
                    else facility_draft_lease_owner_ref(adoption["priorLease"])
                    if adoption["priorLease"] is not None
                    else None
                ),
                acquired_at=_timestamp(now),
                updated_at=_timestamp(now),
                expires_at=_timestamp(now + timedelta(seconds=self.idle_seconds)),
                recovery_deadline_at=_timestamp(
                    now + timedelta(seconds=self.recovery_seconds)
                ),
            )
            next_adoption = self._next_adoption(
                adoption,
                status="committed",
                committedLeaseRevision=committed["leaseRevision"],
                updatedAt=_timestamp(now),
            )
            self._atomic_write(
                self.lease_path(tenant_id, site_id, adoption["layoutId"]), committed
            )
            self._atomic_write(
                self._adoption_path(tenant_id, site_id, adoption_id), next_adoption
            )
            return {"adoption": next_adoption, "lease": committed}

    def acknowledge_adoption(
        self,
        *,
        tenant_id: str,
        site_id: str,
        adoption_id: str,
        adoption_token: str,
        expected_adoption_revision: str,
        observed_installation_fingerprint: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.write_lock(tenant_id, site_id):
            adoption = self._read_adoption(tenant_id, site_id, adoption_id)
            if adoption["adoptionRevision"] != _sha256(
                expected_adoption_revision, "expectedAdoptionRevision"
            ) or adoption["status"] != "committed":
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_revision_conflict",
                    "Facility draft adoption is not awaiting acknowledgment.",
                )
            if hashlib.sha256(str(adoption_token).encode("ascii")).hexdigest() != adoption[
                "adoptionTokenHash"
            ]:
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_token_invalid",
                    "Facility draft adoption token is invalid.",
                )
            observed = _sha256(
                observed_installation_fingerprint,
                "observedInstallationFingerprint",
            )
            if observed != adoption["expectedInstallationFingerprint"]:
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_installation_fingerprint_conflict",
                    "The browser did not install the prepared Facility proposal.",
                    details={"observedInstallationFingerprint": observed},
                )
            lease = self._require_owner_locked(
                tenant_id,
                site_id,
                adoption["layoutId"],
                owner_kind="design_run",
                owner_run_id=adoption["designRunId"],
                owner_token=adoption["targetOwnerToken"],
                expected_lease_revision=adoption["committedLeaseRevision"],
                allowed_statuses={"review_required"},
                now=now,
            )
            active = build_facility_draft_lease(
                **self._build_args(
                    lease,
                    status="active",
                    review_reason=None,
                    recovery_deadline_at=None,
                    updated_at=_timestamp(now),
                    expires_at=_timestamp(now + timedelta(seconds=self.idle_seconds)),
                )
            )
            next_adoption = self._next_adoption(
                adoption,
                status="acknowledged",
                updatedAt=_timestamp(now),
            )
            self._atomic_write(
                self.lease_path(tenant_id, site_id, adoption["layoutId"]), active
            )
            self._atomic_write(
                self._adoption_path(tenant_id, site_id, adoption_id), next_adoption
            )
            return {"adoption": next_adoption, "lease": active}

    def recover_adoption(
        self,
        *,
        tenant_id: str,
        site_id: str,
        adoption_id: str,
        expected_adoption_revision: str,
        observed_installation_fingerprint: str,
    ) -> dict[str, Any]:
        """Recover O or A exactly; never synthesize a different browser state."""

        now = self._now()
        with self.write_lock(tenant_id, site_id):
            adoption = self._read_adoption(tenant_id, site_id, adoption_id)
            if adoption["adoptionRevision"] != _sha256(
                expected_adoption_revision, "expectedAdoptionRevision"
            ) or adoption["status"] not in {"prepared", "committed"}:
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_revision_conflict",
                    "Facility draft adoption cannot be recovered from this state.",
                )
            observed = _sha256(
                observed_installation_fingerprint,
                "observedInstallationFingerprint",
            )
            replacement = (
                adoption["priorLease"] is not None
                and adoption["priorLease"]["ownerKind"] == "design_run"
                and adoption["priorLease"]["ownerRunId"]
                == adoption["designRunId"]
            )
            if replacement and observed == adoption[
                "rootInstallationFingerprint"
            ] and observed != adoption["previousInstallationFingerprint"]:
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_replacement_root_observed",
                    "The original Undo frame cannot recover a failed replacement; restore the immediately preceding proposal or perform explicit Undo.",
                )
            if observed == adoption["expectedInstallationFingerprint"] and adoption[
                "status"
            ] == "committed":
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_installation_acknowledgment_required",
                    "The expected proposal is installed and must be acknowledged.",
                )
            if observed not in {
                adoption["rootInstallationFingerprint"],
                adoption["previousInstallationFingerprint"],
            }:
                lease = self._read_lease(tenant_id, site_id, adoption["layoutId"])
                if lease is not None and lease["ownerKind"] == "design_run" and lease[
                    "ownerRunId"
                ] == adoption["designRunId"]:
                    conflict_lease = build_facility_draft_lease(
                        **self._build_args(
                            lease,
                            status="review_required",
                            review_reason="installation_fingerprint_conflict",
                            recovery_deadline_at=_timestamp(
                                now + timedelta(seconds=self.recovery_seconds)
                            ),
                            updated_at=_timestamp(now),
                        )
                    )
                    self._atomic_write(
                        self.lease_path(tenant_id, site_id, adoption["layoutId"]),
                        conflict_lease,
                    )
                next_adoption = self._next_adoption(
                    adoption, status="conflict", updatedAt=_timestamp(now)
                )
                self._atomic_write(
                    self._adoption_path(tenant_id, site_id, adoption_id), next_adoption
                )
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_installation_fingerprint_conflict",
                    "Browser state matches neither the prepared proposal nor a recoverable prior installation.",
                )
            prior = adoption["priorLease"]
            lease_path = self.lease_path(tenant_id, site_id, adoption["layoutId"])
            if prior is None:
                try:
                    os.unlink(_native_path(lease_path))
                except FileNotFoundError:
                    pass
                restored = None
            else:
                restored = validate_facility_draft_lease(prior)
                self._atomic_write(lease_path, restored)
            next_adoption = self._next_adoption(
                adoption,
                status="recovered" if adoption["status"] == "committed" else "aborted",
                updatedAt=_timestamp(now),
            )
            self._atomic_write(
                self._adoption_path(tenant_id, site_id, adoption_id), next_adoption
            )
            return {"adoption": next_adoption, "lease": deepcopy(restored)}

    def release(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        owner_kind: str,
        owner_run_id: str,
        owner_token: str,
        expected_lease_revision: str,
        reason: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.write_lock(tenant_id, site_id):
            current = self._require_owner_locked(
                tenant_id,
                site_id,
                layout_id,
                owner_kind=owner_kind,
                owner_run_id=owner_run_id,
                owner_token=owner_token,
                expected_lease_revision=expected_lease_revision,
                allowed_statuses={"active", "review_required"},
                now=now,
            )
            released = build_facility_draft_lease(
                **self._build_args(
                    current,
                    status="released",
                    review_reason=None,
                    recovery_deadline_at=None,
                    updated_at=_timestamp(now),
                    expires_at=_timestamp(now),
                )
            )
            receipt = {
                "recordKind": "facility_draft_lease_release",
                "layoutId": released["layoutId"],
                "ownerKind": released["ownerKind"],
                "ownerRunId": released["ownerRunId"],
                "priorLeaseRevision": current["leaseRevision"],
                "releasedLeaseRevision": released["leaseRevision"],
                "reason": _identifier(reason, "reason"),
                "releasedAt": _timestamp(now),
            }
            receipt["receiptRevision"] = _revision(receipt)
            self._atomic_write(self.lease_path(tenant_id, site_id, layout_id), released)
            return {"lease": released, "receipt": receipt}

    def mark_undo_acknowledgment_pending(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        owner_run_id: str,
        owner_token: str,
        expected_lease_revision: str,
    ) -> dict[str, Any]:
        """Hold write authority while the browser restores the Undo frame."""

        now = self._now()
        with self.write_lock(tenant_id, site_id):
            current = self._read_lease(tenant_id, site_id, layout_id)
            if (
                current is not None
                and current["ownerKind"] == "design_run"
                and current["ownerRunId"] == owner_run_id
                and current["ownerToken"] == owner_token
                and current["status"] == "review_required"
                and current["reviewReason"] == "undo_unacknowledged"
                and self._live_at(current, now)
            ):
                return deepcopy(current)
            current = self._require_owner_locked(
                tenant_id,
                site_id,
                layout_id,
                owner_kind="design_run",
                owner_run_id=owner_run_id,
                owner_token=owner_token,
                expected_lease_revision=expected_lease_revision,
                allowed_statuses={"active"},
                now=now,
            )
            pending = build_facility_draft_lease(
                **self._build_args(
                    current,
                    status="review_required",
                    review_reason="undo_unacknowledged",
                    recovery_deadline_at=_timestamp(
                        now + timedelta(seconds=self.recovery_seconds)
                    ),
                    updated_at=_timestamp(now),
                    expires_at=_timestamp(now + timedelta(seconds=self.idle_seconds)),
                )
            )
            self._atomic_write(
                self.lease_path(tenant_id, site_id, layout_id), pending
            )
            return deepcopy(pending)

    def return_after_undo(
        self,
        *,
        tenant_id: str,
        site_id: str,
        adoption_id: str,
        expected_adoption_revision: str,
        expected_lease_revision: str,
        owner_token: str,
    ) -> dict[str, Any]:
        """Return an adopted lease to a live source owner, otherwise release it."""

        now = self._now()
        with self.write_lock(tenant_id, site_id):
            adoption = self._read_adoption(tenant_id, site_id, adoption_id)
            if (
                adoption["adoptionRevision"]
                != _sha256(expected_adoption_revision, "expectedAdoptionRevision")
                or adoption["status"] != "acknowledged"
            ):
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_revision_conflict",
                    "Facility draft adoption is not eligible for Undo.",
                )
            current = self._require_owner_locked(
                tenant_id,
                site_id,
                adoption["layoutId"],
                owner_kind="design_run",
                owner_run_id=adoption["designRunId"],
                owner_token=owner_token,
                expected_lease_revision=expected_lease_revision,
                allowed_statuses={"active", "review_required"},
                now=now,
            )
            prior = adoption["priorLease"]
            if (
                prior is not None
                and prior["status"] == "active"
                and _parse_timestamp(prior["expiresAt"], "priorLease.expiresAt") > now
            ):
                next_lease = validate_facility_draft_lease(prior)
                outcome = "returned_to_prior_owner"
            else:
                next_lease = build_facility_draft_lease(
                    **self._build_args(
                        current,
                        status="released",
                        review_reason=None,
                        recovery_deadline_at=None,
                        updated_at=_timestamp(now),
                        expires_at=_timestamp(now),
                    )
                )
                outcome = "released"
            next_adoption = self._next_adoption(
                adoption, status="undone", updatedAt=_timestamp(now)
            )
            self._atomic_write(
                self.lease_path(tenant_id, site_id, adoption["layoutId"]), next_lease
            )
            self._atomic_write(
                self._adoption_path(tenant_id, site_id, adoption_id), next_adoption
            )
            return {
                "outcome": outcome,
                "adoption": next_adoption,
                "lease": next_lease,
            }

    def consume_after_save(
        self,
        *,
        tenant_id: str,
        site_id: str,
        adoption_id: str,
        expected_adoption_revision: str,
        expected_lease_revision: str,
        owner_run_id: str,
        owner_token: str,
        saved_layout_revision: str,
    ) -> dict[str, Any]:
        """Consume one acknowledged design lease after an explicit Save."""

        now = self._now()
        with self.write_lock(tenant_id, site_id):
            adoption = self._read_adoption(tenant_id, site_id, adoption_id)
            if (
                adoption["adoptionRevision"]
                != _sha256(expected_adoption_revision, "expectedAdoptionRevision")
                or adoption["status"] != "acknowledged"
                or adoption["designRunId"] != owner_run_id
            ):
                raise FacilityDraftLeaseConflictError(
                    "facility_draft_lease_adoption_revision_conflict",
                    "Facility draft adoption is not eligible for Save.",
                )
            current = self._require_owner_locked(
                tenant_id,
                site_id,
                adoption["layoutId"],
                owner_kind="design_run",
                owner_run_id=owner_run_id,
                owner_token=owner_token,
                expected_lease_revision=expected_lease_revision,
                allowed_statuses={"active"},
                now=now,
            )
            saved_revision = _sha256(
                saved_layout_revision, "savedLayoutRevision"
            )
            released = build_facility_draft_lease(
                **self._build_args(
                    current,
                    base_saved_layout_revision=saved_revision,
                    current_draft_revision=saved_revision,
                    status="released",
                    review_reason=None,
                    prior_owner_ref=None,
                    recovery_deadline_at=None,
                    updated_at=_timestamp(now),
                    expires_at=_timestamp(now),
                )
            )
            next_adoption = self._next_adoption(
                adoption, status="saved", updatedAt=_timestamp(now)
            )
            receipt = {
                "recordKind": "facility_draft_lease_save_consumption",
                "layoutId": released["layoutId"],
                "designRunId": owner_run_id,
                "adoptionId": adoption_id,
                "priorLeaseRevision": current["leaseRevision"],
                "releasedLeaseRevision": released["leaseRevision"],
                "savedLayoutRevision": saved_revision,
                "savedAt": _timestamp(now),
            }
            receipt["receiptRevision"] = _revision(receipt)
            self._atomic_write(
                self.lease_path(tenant_id, site_id, adoption["layoutId"]),
                released,
            )
            self._atomic_write(
                self._adoption_path(tenant_id, site_id, adoption_id),
                next_adoption,
            )
            return {
                "outcome": "saved_and_released",
                "adoption": next_adoption,
                "lease": released,
                "receipt": receipt,
            }


__all__ = [
    "FACILITY_DRAFT_LEASE_IDLE_SECONDS",
    "FACILITY_DRAFT_LEASE_LOCK_STALE_SECONDS",
    "FACILITY_DRAFT_LEASE_LOCK_TIMEOUT_SECONDS",
    "FACILITY_DRAFT_LEASE_RECOVERY_SECONDS",
    "FACILITY_DRAFT_LEASE_SCHEMA_VERSION",
    "FacilityDraftLeaseConflictError",
    "FacilityDraftLeaseError",
    "FacilityDraftLeaseIntegrityError",
    "FacilityDraftLeaseRepository",
    "build_facility_draft_lease",
    "facility_draft_lease_owner_ref",
    "validate_facility_draft_lease",
]
