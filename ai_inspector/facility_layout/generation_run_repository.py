"""Durable, revision-aware Facility Layout generation-run persistence."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4

from .canonical import canonicalize_layout, layout_revision
from .knowledge_foundation import (
    FACILITY_GENERATION_RUN_SCHEMA_VERSION,
    canonical_facility_knowledge_bytes,
    default_generation_stage_graph,
    validate_facility_intent,
    validate_generation_run,
    validate_generation_save_receipt,
    validate_generation_stage_receipt,
)
from .provider_config import (
    FacilityProviderConfig,
    FacilityProviderConfigurationError,
    assert_facility_provider_configuration,
)


FACILITY_GENERATION_RUN_IDLE_SECONDS = 24 * 60 * 60
FACILITY_GENERATION_TOMBSTONE_RETENTION_SECONDS = 30 * 24 * 60 * 60
FACILITY_GENERATION_LOCK_STALE_SECONDS = 120
FACILITY_GENERATION_LOCK_TIMEOUT_SECONDS = 5.0

_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_RUN_ID_RE = re.compile(r"^fgr-[A-Za-z0-9][A-Za-z0-9._:-]{0,124}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNSAVED_TERMINAL_STATUSES = frozenset({"cancelled", "expired", "stale"})
_RUN_IMMUTABLE_FIELDS = frozenset(
    {
        "schemaVersion",
        "runId",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "userId",
        "sessionId",
        "baseLayoutRevision",
        "effectiveProvider",
        "effectiveModel",
        "reasoningEffort",
        "intentHash",
        "createdAt",
        "prototypeMode",
    }
)


class FacilityGenerationRunRepositoryError(RuntimeError):
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


class FacilityGenerationRunNotFoundError(FacilityGenerationRunRepositoryError):
    def __init__(self) -> None:
        super().__init__("generation_run_not_found", "Generation run was not found.")


class FacilityGenerationRunConflictError(FacilityGenerationRunRepositoryError):
    pass


class FacilityGenerationRunIntegrityError(FacilityGenerationRunRepositoryError):
    pass


def _native_fs_path(path: Path) -> str:
    absolute = os.path.abspath(os.fspath(path))
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _timestamp(value: datetime) -> str:
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FacilityGenerationRunIntegrityError(
            "generation_run_timestamp_invalid",
            f"{field} is not a valid UTC timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        raise FacilityGenerationRunIntegrityError(
            "generation_run_timestamp_invalid",
            f"{field} is not timezone-aware.",
        )
    return parsed.astimezone(timezone.utc)


def _record_revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _STABLE_ID_RE.fullmatch(value) is None:
        raise FacilityGenerationRunRepositoryError(
            "generation_scope_invalid",
            f"{field} must be a stable identifier.",
            details={"field": field},
        )
    return value


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise FacilityGenerationRunRepositoryError(
            "generation_run_id_invalid",
            "runId must be a stable Facility generation-run identifier.",
        )
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise FacilityGenerationRunRepositoryError(
            "generation_revision_invalid",
            f"{field} must be a lowercase SHA-256 digest.",
        )
    return value


def _read_bytes(path: Path) -> bytes:
    try:
        with open(_native_fs_path(path), "rb") as stream:
            return stream.read()
    except FileNotFoundError as exc:
        raise FacilityGenerationRunNotFoundError() from exc
    except OSError as exc:
        raise FacilityGenerationRunIntegrityError(
            "generation_store_unreadable",
            "Generation-run storage could not be read.",
        ) from exc


def _read_record(path: Path, record_kind: str) -> dict[str, Any]:
    payload = _read_bytes(path)
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FacilityGenerationRunIntegrityError(
            "generation_record_invalid",
            "Generation-run record is not canonical JSON.",
        ) from exc
    if not isinstance(value, dict) or value.get("recordKind") != record_kind:
        raise FacilityGenerationRunIntegrityError(
            "generation_record_invalid",
            "Generation-run record kind is invalid.",
        )
    if payload != canonical_facility_knowledge_bytes(value):
        raise FacilityGenerationRunIntegrityError(
            "generation_record_not_canonical",
            "Generation-run record is not canonical.",
        )
    return value


class FacilityGenerationRunRepository:
    """Restart-safe run, lease, session, tombstone, and save-receipt store."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime | str] | None = None,
        idle_seconds: int = FACILITY_GENERATION_RUN_IDLE_SECONDS,
        tombstone_retention_seconds: int = (
            FACILITY_GENERATION_TOMBSTONE_RETENTION_SECONDS
        ),
        lock_stale_seconds: int = FACILITY_GENERATION_LOCK_STALE_SECONDS,
        lock_timeout_seconds: float = FACILITY_GENERATION_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.root = Path(root).resolve()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.idle_seconds = int(idle_seconds)
        self.tombstone_retention_seconds = int(tombstone_retention_seconds)
        self.lock_stale_seconds = int(lock_stale_seconds)
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        if (
            self.idle_seconds < 1
            or self.tombstone_retention_seconds < 1
            or self.lock_stale_seconds < 1
            or self.lock_timeout_seconds <= 0
        ):
            raise ValueError("Generation-run retention and lock limits must be positive.")
        try:
            os.makedirs(_native_fs_path(self.root), exist_ok=True)
        except OSError as exc:
            raise FacilityGenerationRunIntegrityError(
                "generation_root_unavailable",
                "Generation-run storage root is unavailable.",
            ) from exc

    def _now(self) -> datetime:
        value = self._clock()
        if isinstance(value, str):
            return _parse_timestamp(value, "clock")
        if not isinstance(value, datetime):
            raise FacilityGenerationRunIntegrityError(
                "generation_clock_invalid",
                "Generation-run clock returned an unsupported value.",
            )
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _scope_root(self, tenant_id: str, site_id: str) -> Path:
        tenant_id = _identifier(tenant_id, "tenantId")
        site_id = _identifier(site_id, "siteId")
        candidate = self.root / tenant_id / site_id / "generation-runs"
        root_text = os.path.normcase(os.path.abspath(os.fspath(self.root)))
        candidate_text = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        try:
            contained = os.path.commonpath((root_text, candidate_text)) == root_text
        except ValueError:
            contained = False
        if not contained:
            raise FacilityGenerationRunRepositoryError(
                "generation_scope_invalid",
                "Generation-run scope escapes its configured root.",
            )
        return candidate

    def _run_path(self, tenant_id: str, site_id: str, run_id: str) -> Path:
        return self._scope_root(tenant_id, site_id) / "runs" / f"{_run_id(run_id)}.json"

    def _tombstone_path(self, tenant_id: str, site_id: str, run_id: str) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "tombstones"
            / f"{_run_id(run_id)}.json"
        )

    def _session_path(self, tenant_id: str, site_id: str, session_id: str) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "sessions"
            / f"{_identifier(session_id, 'sessionId')}.json"
        )

    def _lease_path(self, tenant_id: str, site_id: str, layout_id: str) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "leases"
            / f"{_identifier(layout_id, 'layoutId')}.json"
        )

    def _lock_path(self, tenant_id: str, site_id: str) -> Path:
        return self._scope_root(tenant_id, site_id) / ".write.lock"

    def _save_receipt_path(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        saved_revision: str,
        save_receipt_id: str,
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "saved-receipts"
            / _identifier(layout_id, "layoutId")
            / _sha256(saved_revision, "savedLayoutRevision")
            / f"{_identifier(save_receipt_id, 'saveReceiptId')}.json"
        )

    def _execution_intent_path(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "intent.json"
        )

    def _base_layout_path(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "base-layout.json"
        )

    def _draft_checkpoint_path(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "draft.json"
        )

    def _stage_receipt_path(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        receipt_id: str,
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "stage-receipts"
            / f"{_identifier(receipt_id, 'receiptId')}.json"
        )

    def _stage_draft_path(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        receipt_id: str,
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "stage-drafts"
            / f"{_identifier(receipt_id, 'receiptId')}.json"
        )

    def _receipt_supersession_path(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        receipt_id: str,
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "receipt-supersessions"
            / f"{_identifier(receipt_id, 'receiptId')}.json"
        )

    def _checkpoint_transaction_path(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "transactions"
            / "stage-checkpoint.json"
        )

    def _save_intent_path(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> Path:
        return (
            self._scope_root(tenant_id, site_id)
            / "run-artifacts"
            / _run_id(run_id)
            / "transactions"
            / "save-intent.json"
        )

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

    def _atomic_write(self, path: Path, value: Mapping[str, Any]) -> None:
        payload = canonical_facility_knowledge_bytes(value)
        parent = _native_fs_path(path.parent)
        native_path = _native_fs_path(path)
        temporary_name: str | None = None
        try:
            os.makedirs(parent, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".fgr-", suffix=".tmp", dir=parent
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._replace_file(temporary_name, native_path)
            temporary_name = None
        except OSError as exc:
            raise FacilityGenerationRunIntegrityError(
                "generation_store_write_failed",
                "Generation-run storage could not be written.",
            ) from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            os.unlink(_native_fs_path(path))
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise FacilityGenerationRunIntegrityError(
                "generation_store_delete_failed",
                "Generation-run storage could not remove a record.",
            ) from exc

    @contextmanager
    def _write_lock(self, tenant_id: str, site_id: str) -> Iterator[None]:
        path = self._lock_path(tenant_id, site_id)
        os.makedirs(_native_fs_path(path.parent), exist_ok=True)
        owner_token = f"lock-{uuid4().hex}"
        deadline = time.monotonic() + self.lock_timeout_seconds
        acquired = False
        metadata = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "recordKind": "facility_generation_write_lock",
            "ownerToken": owner_token,
            "processId": os.getpid(),
            "createdAt": _timestamp(self._now()),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        while not acquired:
            try:
                descriptor = os.open(_native_fs_path(path), flags, 0o600)
                try:
                    payload = canonical_facility_knowledge_bytes(metadata)
                    os.write(descriptor, payload)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                acquired = True
            except FileExistsError:
                try:
                    age = max(0.0, time.time() - os.stat(_native_fs_path(path)).st_mtime)
                except FileNotFoundError:
                    continue
                if age >= self.lock_stale_seconds:
                    stale = path.with_name(f"{path.name}.stale-{uuid4().hex}")
                    try:
                        os.rename(_native_fs_path(path), _native_fs_path(stale))
                    except FileNotFoundError:
                        continue
                    except OSError:
                        pass
                    else:
                        self._remove(stale)
                        continue
                if time.monotonic() >= deadline:
                    raise FacilityGenerationRunConflictError(
                        "generation_write_lock_timeout",
                        "Generation-run storage is busy.",
                    )
                time.sleep(0.02)
            except OSError as exc:
                raise FacilityGenerationRunIntegrityError(
                    "generation_write_lock_failed",
                    "Generation-run cross-process lock could not be acquired.",
                ) from exc
        try:
            yield
        finally:
            try:
                current = _read_record(path, "facility_generation_write_lock")
            except FacilityGenerationRunRepositoryError:
                current = None
            if current is not None and current.get("ownerToken") == owner_token:
                self._remove(path)

    def _run_envelope(self, run: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_generation_run(run)
        return {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "recordKind": "facility_generation_run",
            "runRevision": _record_revision(normalized),
            "run": normalized,
        }

    def _load_run_envelope(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        envelope = _read_record(
            self._run_path(tenant_id, site_id, run_id),
            "facility_generation_run",
        )
        run = envelope.get("run")
        if not isinstance(run, Mapping):
            raise FacilityGenerationRunIntegrityError(
                "generation_run_invalid",
                "Generation-run envelope has no run payload.",
            )
        normalized = validate_generation_run(run)
        revision = _record_revision(normalized)
        if envelope.get("runRevision") != revision:
            raise FacilityGenerationRunIntegrityError(
                "generation_run_revision_mismatch",
                "Generation-run bytes do not match the stored revision.",
            )
        envelope["run"] = normalized
        return envelope

    def _load_optional(self, path: Path, record_kind: str) -> dict[str, Any] | None:
        try:
            return _read_record(path, record_kind)
        except FacilityGenerationRunNotFoundError:
            return None

    def _write_immutable_record(
        self,
        path: Path,
        record_kind: str,
        record: Mapping[str, Any],
        *,
        conflict_code: str,
    ) -> None:
        existing = self._load_optional(path, record_kind)
        if existing is not None and existing != record:
            raise FacilityGenerationRunIntegrityError(
                conflict_code,
                "A durable generation artifact conflicts with its transaction journal.",
            )
        if existing is None:
            self._atomic_write(path, record)

    @staticmethod
    def _validate_checkpoint_transaction(
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "schemaVersion",
            "recordKind",
            "transactionId",
            "transactionRevision",
            "runId",
            "expectedRunRevision",
            "nextRunEnvelope",
            "draftRecord",
            "receiptRecord",
            "stageDraftRecord",
            "leaseRecord",
            "createdAt",
        }
        if set(value) != required:
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_invalid",
                "Stage-checkpoint transaction fields are invalid.",
            )
        if (
            value["schemaVersion"] != FACILITY_GENERATION_RUN_SCHEMA_VERSION
            or value["recordKind"]
            != "facility_generation_checkpoint_transaction"
        ):
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_invalid",
                "Stage-checkpoint transaction version or kind is invalid.",
            )
        unsigned = deepcopy(dict(value))
        revision = unsigned.pop("transactionRevision")
        if revision != _record_revision(unsigned):
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_revision_mismatch",
                "Stage-checkpoint transaction revision is invalid.",
            )
        run_id = _run_id(value["runId"])
        _identifier(value["transactionId"], "transactionId")
        _sha256(value["expectedRunRevision"], "expectedRunRevision")
        _parse_timestamp(value["createdAt"], "transaction.createdAt")
        next_envelope = value["nextRunEnvelope"]
        if not isinstance(next_envelope, Mapping):
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_invalid",
                "Stage-checkpoint transaction has no next run envelope.",
            )
        next_run = validate_generation_run(next_envelope.get("run"))
        if (
            next_run["runId"] != run_id
            or next_envelope.get("recordKind") != "facility_generation_run"
            or next_envelope.get("runRevision") != _record_revision(next_run)
        ):
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_invalid",
                "Stage-checkpoint transaction run envelope is invalid.",
            )
        receipt_record = value["receiptRecord"]
        stage_draft = value["stageDraftRecord"]
        draft_record = value["draftRecord"]
        receipt_payload = (
            receipt_record.get("receipt")
            if isinstance(receipt_record, Mapping)
            else None
        )
        if (
            not isinstance(receipt_record, Mapping)
            or receipt_record.get("recordKind")
            != "facility_generation_stage_receipt"
            or not isinstance(receipt_payload, Mapping)
            or not isinstance(stage_draft, Mapping)
            or stage_draft.get("recordKind") != "facility_generation_draft"
            or not isinstance(draft_record, Mapping)
            or draft_record.get("recordKind") != "facility_generation_draft"
            or receipt_payload.get("runId") != run_id
            or stage_draft.get("runId") != run_id
            or draft_record.get("runId") != run_id
        ):
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_invalid",
                "Stage-checkpoint transaction artifacts are invalid.",
            )
        if value["leaseRecord"] is not None:
            lease = value["leaseRecord"]
            if not isinstance(lease, Mapping) or lease.get("runId") != run_id:
                raise FacilityGenerationRunIntegrityError(
                    "generation_checkpoint_transaction_invalid",
                    "Stage-checkpoint transaction lease is invalid.",
                )
        return deepcopy(dict(value))

    def _apply_checkpoint_transaction_locked(
        self,
        tenant_id: str,
        site_id: str,
        transaction: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = self._validate_checkpoint_transaction(transaction)
        run_id = value["runId"]
        current = self._load_run_envelope(tenant_id, site_id, run_id)
        next_envelope = deepcopy(value["nextRunEnvelope"])
        if current["runRevision"] not in {
            value["expectedRunRevision"],
            next_envelope["runRevision"],
        }:
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_conflict",
                "A stage-checkpoint transaction cannot be reconciled with the run.",
                details={"currentRunRevision": current["runRevision"]},
            )
        receipt_record = deepcopy(value["receiptRecord"])
        receipt = receipt_record["receipt"]
        stage_draft = deepcopy(value["stageDraftRecord"])
        draft_record = deepcopy(value["draftRecord"])
        self._write_immutable_record(
            self._stage_receipt_path(
                tenant_id, site_id, run_id, receipt["receiptId"]
            ),
            "facility_generation_stage_receipt",
            receipt_record,
            conflict_code="generation_stage_receipt_journal_conflict",
        )
        self._write_immutable_record(
            self._stage_draft_path(
                tenant_id, site_id, run_id, receipt["receiptId"]
            ),
            "facility_generation_draft",
            stage_draft,
            conflict_code="generation_stage_draft_journal_conflict",
        )
        current_draft = self._load_optional(
            self._draft_checkpoint_path(tenant_id, site_id, run_id),
            "facility_generation_draft",
        )
        allowed_draft_revisions = {
            receipt["baseDraftRevision"],
            receipt["resultDraftRevision"],
        }
        if (
            current_draft is not None
            and current_draft.get("draftLayoutRevision")
            not in allowed_draft_revisions
        ):
            raise FacilityGenerationRunIntegrityError(
                "generation_checkpoint_transaction_conflict",
                "A stage-checkpoint transaction found an unrelated draft revision.",
            )
        self._atomic_write(
            self._draft_checkpoint_path(tenant_id, site_id, run_id),
            draft_record,
        )
        self._atomic_write(
            self._run_path(tenant_id, site_id, run_id), next_envelope
        )
        lease = value["leaseRecord"]
        if lease is not None:
            self._atomic_write(
                self._lease_path(
                    tenant_id, site_id, next_envelope["run"]["layoutId"]
                ),
                lease,
            )
        self._remove(
            self._checkpoint_transaction_path(tenant_id, site_id, run_id)
        )
        return {
            "run": deepcopy(next_envelope),
            "draft": draft_record,
            "stageReceipt": receipt_record,
        }

    def _reconcile_checkpoint_transaction(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> None:
        path = self._checkpoint_transaction_path(tenant_id, site_id, run_id)
        if not os.path.exists(_native_fs_path(path)):
            return
        with self._write_lock(tenant_id, site_id):
            transaction = self._load_optional(
                path, "facility_generation_checkpoint_transaction"
            )
            if transaction is not None:
                self._apply_checkpoint_transaction_locked(
                    tenant_id, site_id, transaction
                )

    @staticmethod
    def _lease_payload(
        *,
        run_id: str,
        layout_id: str,
        owner_token: str,
        base_layout_revision: str,
        acquired_at: str,
        updated_at: str,
        expires_at: str,
    ) -> dict[str, Any]:
        value = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "recordKind": "facility_generation_layout_lease",
            "runId": run_id,
            "layoutId": layout_id,
            "ownerToken": owner_token,
            "baseLayoutRevision": base_layout_revision,
            "acquiredAt": acquired_at,
            "updatedAt": updated_at,
            "expiresAt": expires_at,
        }
        value["leaseRevision"] = _record_revision(value)
        return value

    @staticmethod
    def _run_lease_view(lease: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "layoutId": lease["layoutId"],
            "runId": lease["runId"],
            "ownerToken": lease["ownerToken"],
            "leaseRevision": lease["leaseRevision"],
            "acquiredAt": lease["acquiredAt"],
            "updatedAt": lease["updatedAt"],
            "expiresAt": lease["expiresAt"],
        }

    def _validate_lease_record(self, lease: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "schemaVersion",
            "recordKind",
            "runId",
            "layoutId",
            "ownerToken",
            "baseLayoutRevision",
            "acquiredAt",
            "updatedAt",
            "expiresAt",
            "leaseRevision",
        }
        if set(lease) != required:
            raise FacilityGenerationRunIntegrityError(
                "generation_lease_invalid",
                "Generation writable lease fields are invalid.",
            )
        unsigned = deepcopy(dict(lease))
        revision = unsigned.pop("leaseRevision")
        if revision != _record_revision(unsigned):
            raise FacilityGenerationRunIntegrityError(
                "generation_lease_revision_mismatch",
                "Generation writable lease revision is invalid.",
            )
        _run_id(lease["runId"])
        _identifier(lease["layoutId"], "layoutId")
        _identifier(lease["ownerToken"], "ownerToken")
        _sha256(lease["baseLayoutRevision"], "baseLayoutRevision")
        for field in ("acquiredAt", "updatedAt", "expiresAt"):
            _parse_timestamp(lease[field], f"lease.{field}")
        return deepcopy(dict(lease))

    def _active_lease(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        path = self._lease_path(tenant_id, site_id, layout_id)
        record = self._load_optional(path, "facility_generation_layout_lease")
        if record is None:
            return None
        lease = self._validate_lease_record(record)
        if _parse_timestamp(lease["expiresAt"], "lease.expiresAt") <= now:
            self._remove(path)
            return None
        try:
            envelope = self._load_run_envelope(tenant_id, site_id, lease["runId"])
        except FacilityGenerationRunNotFoundError:
            self._remove(path)
            return None
        run = envelope["run"]
        if run["status"] in _UNSAVED_TERMINAL_STATUSES or not run["writable"]:
            self._remove(path)
            return None
        return lease

    def create_run(
        self,
        *,
        tenant_id: str,
        site_id: str,
        workspace_id: str,
        layout_id: str,
        user_id: str,
        session_id: str,
        base_layout_revision: str,
        effective_provider: str,
        effective_model: str,
        reasoning_effort: str | None,
        intent_hash: str,
        dependency_fingerprint: str,
        prototype_mode: bool,
        writable: bool,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = _identifier(tenant_id, "tenantId")
        site_id = _identifier(site_id, "siteId")
        workspace_id = _identifier(workspace_id, "workspaceId")
        layout_id = _identifier(layout_id, "layoutId")
        user_id = _identifier(user_id, "userId")
        session_id = _identifier(session_id, "sessionId")
        run_id = _run_id(run_id or f"fgr-{uuid4().hex}")
        _sha256(base_layout_revision, "baseLayoutRevision")
        _sha256(intent_hash, "intentHash")
        _sha256(dependency_fingerprint, "dependencyFingerprint")
        try:
            assert_facility_provider_configuration(
                FacilityProviderConfig(
                    provider=effective_provider,
                    model=effective_model,
                    reasoning_effort=reasoning_effort,
                    provider_source="generation_run_request",
                    model_source="generation_run_request",
                    reasoning_effort_source="generation_run_request",
                    compatibility_fallbacks_used=(),
                )
            )
        except FacilityProviderConfigurationError as exc:
            raise FacilityGenerationRunRepositoryError(
                exc.code,
                str(exc),
                details=exc.details,
            ) from exc
        now = self._now()
        now_text = _timestamp(now)
        expires_at = _timestamp(now + timedelta(seconds=self.idle_seconds))
        run_path = self._run_path(tenant_id, site_id, run_id)
        tombstone_path = self._tombstone_path(tenant_id, site_id, run_id)
        session_path = self._session_path(tenant_id, site_id, session_id)
        lease_path = self._lease_path(tenant_id, site_id, layout_id)
        with self._write_lock(tenant_id, site_id):
            if os.path.exists(_native_fs_path(run_path)) or os.path.exists(
                _native_fs_path(tombstone_path)
            ):
                raise FacilityGenerationRunConflictError(
                    "generation_run_exists",
                    "Generation run ID already exists.",
                    details={"runId": run_id},
                )
            session_record = self._load_optional(
                session_path, "facility_generation_session_binding"
            )
            if session_record is not None:
                try:
                    existing = self._load_run_envelope(
                        tenant_id, site_id, session_record["runId"]
                    )["run"]
                except FacilityGenerationRunNotFoundError:
                    self._remove(session_path)
                else:
                    if existing["status"] not in _UNSAVED_TERMINAL_STATUSES | {"saved"}:
                        raise FacilityGenerationRunConflictError(
                            "generation_session_already_bound",
                            "Session already has an active generation run.",
                            details={"runId": existing["runId"]},
                        )
                    self._remove(session_path)
            lease = None
            if writable:
                existing_lease = self._active_lease(
                    tenant_id, site_id, layout_id, now
                )
                if existing_lease is not None:
                    raise FacilityGenerationRunConflictError(
                        "generation_writable_lease_conflict",
                        "Another writable generation run owns this layout.",
                        details={"runId": existing_lease["runId"]},
                    )
                lease = self._lease_payload(
                    run_id=run_id,
                    layout_id=layout_id,
                    owner_token=f"lease-{uuid4().hex}",
                    base_layout_revision=base_layout_revision,
                    acquired_at=now_text,
                    updated_at=now_text,
                    expires_at=expires_at,
                )
            run = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "runId": run_id,
                "tenantId": tenant_id,
                "siteId": site_id,
                "workspaceId": workspace_id,
                "layoutId": layout_id,
                "userId": user_id,
                "sessionId": session_id,
                "baseLayoutRevision": base_layout_revision,
                "effectiveProvider": effective_provider,
                "effectiveModel": effective_model,
                "reasoningEffort": reasoning_effort,
                "intentHash": intent_hash,
                "dependencyFingerprint": dependency_fingerprint,
                "stageGraph": default_generation_stage_graph(),
                "currentStageId": "facility_envelope",
                "resumePoint": {
                    "stageId": "facility_envelope",
                    "substageId": None,
                    "turnSequence": 0,
                },
                "receiptChain": [],
                "invalidations": [],
                "status": "active",
                "writable": bool(writable),
                "writableLease": self._run_lease_view(lease) if lease else None,
                "prototypeMode": bool(prototype_mode),
                "createdAt": now_text,
                "updatedAt": now_text,
                "lastActivityAt": now_text,
                "expiresAt": expires_at,
                "cumulativeDiffHash": None,
                "cumulativeProposal": None,
                "saveEligibility": "blocked",
                "terminalReason": None,
            }
            envelope = self._run_envelope(run)
            session_binding = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_session_binding",
                "tenantId": tenant_id,
                "siteId": site_id,
                "sessionId": session_id,
                "runId": run_id,
                "boundAt": now_text,
                "updatedAt": now_text,
            }
            try:
                self._atomic_write(run_path, envelope)
                if lease is not None:
                    self._atomic_write(lease_path, lease)
                self._atomic_write(session_path, session_binding)
            except Exception:
                self._remove(run_path)
                if lease is not None:
                    self._remove(lease_path)
                self._remove(session_path)
                raise
        return deepcopy(envelope)

    def initialize_execution_artifacts(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        *,
        intent: Mapping[str, Any],
        base_layout: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist the immutable intent and first restart-safe draft checkpoint."""

        normalized_intent = validate_facility_intent(intent)
        normalized_layout = canonicalize_layout(deepcopy(dict(base_layout)))
        draft_revision = layout_revision(normalized_layout)
        with self._write_lock(tenant_id, site_id):
            envelope = self._load_run_envelope(tenant_id, site_id, run_id)
            run = envelope["run"]
            if draft_revision != run["baseLayoutRevision"]:
                raise FacilityGenerationRunConflictError(
                    "generation_base_layout_revision_mismatch",
                    "Execution base layout does not match the generation run.",
                    details={
                        "expected": run["baseLayoutRevision"],
                        "observed": draft_revision,
                    },
                )
            if _record_revision(normalized_intent) != run["intentHash"]:
                raise FacilityGenerationRunConflictError(
                    "generation_intent_hash_mismatch",
                    "Execution intent does not match the generation run.",
                )
            intent_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_intent",
                "runId": run["runId"],
                "intentRevision": run["intentHash"],
                "intent": normalized_intent,
            }
            base_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_base_layout",
                "runId": run["runId"],
                "baseLayoutRevision": run["baseLayoutRevision"],
                "document": normalized_layout,
            }
            draft_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_draft",
                "runId": run["runId"],
                "baseLayoutRevision": run["baseLayoutRevision"],
                "draftLayoutRevision": draft_revision,
                "receiptChain": [],
                "document": normalized_layout,
            }
            intent_path = self._execution_intent_path(tenant_id, site_id, run_id)
            base_path = self._base_layout_path(tenant_id, site_id, run_id)
            draft_path = self._draft_checkpoint_path(tenant_id, site_id, run_id)
            existing_intent = self._load_optional(
                intent_path, "facility_generation_intent"
            )
            existing_draft = self._load_optional(
                draft_path, "facility_generation_draft"
            )
            existing_base = self._load_optional(
                base_path, "facility_generation_base_layout"
            )
            if existing_intent is not None and existing_intent != intent_record:
                raise FacilityGenerationRunConflictError(
                    "generation_intent_artifact_exists",
                    "A different immutable intent is already bound to this run.",
                )
            if existing_draft is not None and existing_draft != draft_record:
                raise FacilityGenerationRunConflictError(
                    "generation_draft_artifact_exists",
                    "A different draft checkpoint is already bound to this run.",
                )
            if existing_base is not None and existing_base != base_record:
                raise FacilityGenerationRunConflictError(
                    "generation_base_layout_artifact_exists",
                    "A different immutable base layout is already bound to this run.",
                )
            if existing_intent is None:
                self._atomic_write(intent_path, intent_record)
            if existing_base is None:
                self._atomic_write(base_path, base_record)
            if existing_draft is None:
                self._atomic_write(draft_path, draft_record)
        return {
            "intent": deepcopy(intent_record),
            "base": deepcopy(base_record),
            "draft": deepcopy(draft_record),
            "runRevision": envelope["runRevision"],
        }

    def get_execution_artifacts(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        envelope = self.get_run(tenant_id, site_id, run_id)
        intent = _read_record(
            self._execution_intent_path(tenant_id, site_id, run_id),
            "facility_generation_intent",
        )
        base = _read_record(
            self._base_layout_path(tenant_id, site_id, run_id),
            "facility_generation_base_layout",
        )
        draft = _read_record(
            self._draft_checkpoint_path(tenant_id, site_id, run_id),
            "facility_generation_draft",
        )
        if (
            intent.get("runId") != run_id
            or base.get("runId") != run_id
            or draft.get("runId") != run_id
        ):
            raise FacilityGenerationRunIntegrityError(
                "generation_artifact_run_mismatch",
                "Execution artifact does not belong to the requested run.",
            )
        base_document = canonicalize_layout(deepcopy(base.get("document")))
        if layout_revision(base_document) != envelope["run"]["baseLayoutRevision"]:
            raise FacilityGenerationRunIntegrityError(
                "generation_base_layout_revision_mismatch",
                "Immutable generation base layout revision is invalid.",
            )
        if _record_revision(intent.get("intent")) != envelope["run"]["intentHash"]:
            raise FacilityGenerationRunIntegrityError(
                "generation_intent_revision_mismatch",
                "Immutable generation intent revision is invalid.",
            )
        document = canonicalize_layout(deepcopy(draft.get("document")))
        if layout_revision(document) != draft.get("draftLayoutRevision"):
            raise FacilityGenerationRunIntegrityError(
                "generation_draft_revision_mismatch",
                "Durable generation draft revision is invalid.",
            )
        if draft.get("receiptChain") != envelope["run"].get("receiptChain"):
            raise FacilityGenerationRunIntegrityError(
                "generation_draft_receipt_chain_mismatch",
                "Durable draft and generation run receipt chains differ.",
            )
        return {
            "run": envelope,
            "intent": deepcopy(intent),
            "base": deepcopy(base),
            "draft": deepcopy(draft),
        }

    def record_stage_checkpoint(
        self,
        receipt: Mapping[str, Any],
        draft_layout: Mapping[str, Any],
        stage_update: Mapping[str, Any],
        *,
        expected_run_revision: str,
        lease_owner_token: str | None,
        next_stage_id: str | None,
    ) -> dict[str, Any]:
        """Append one immutable receipt and atomically advance the durable draft."""

        normalized_receipt = validate_generation_stage_receipt(receipt)
        normalized_draft = canonicalize_layout(deepcopy(dict(draft_layout)))
        result_revision = layout_revision(normalized_draft)
        if normalized_receipt["resultDraftRevision"] != result_revision:
            raise FacilityGenerationRunConflictError(
                "generation_stage_result_revision_mismatch",
                "Stage receipt does not bind the supplied draft checkpoint.",
            )
        tenant_id = str(stage_update.get("tenantId") or "")
        site_id = str(stage_update.get("siteId") or "")
        run_id = normalized_receipt["runId"]
        expected_run_revision = _sha256(
            expected_run_revision, "expectedRunRevision"
        )
        self._reconcile_checkpoint_transaction(tenant_id, site_id, run_id)
        with self._write_lock(tenant_id, site_id):
            envelope = self._load_run_envelope(tenant_id, site_id, run_id)
            run = deepcopy(envelope["run"])
            if envelope["runRevision"] != expected_run_revision:
                raise FacilityGenerationRunConflictError(
                    "generation_run_revision_conflict",
                    "Generation run changed before its stage checkpoint was recorded.",
                    details={"currentRunRevision": envelope["runRevision"]},
                )
            lease_path = self._lease_path(tenant_id, site_id, run["layoutId"])
            lease = None
            if run["writable"]:
                lease_record = self._load_optional(
                    lease_path, "facility_generation_layout_lease"
                )
                if lease_record is None:
                    raise FacilityGenerationRunConflictError(
                        "generation_writable_lease_lost",
                        "Stage checkpoint requires the writable generation lease.",
                    )
                lease = self._validate_lease_record(lease_record)
                if (
                    lease["runId"] != run_id
                    or lease_owner_token is None
                    or lease["ownerToken"] != lease_owner_token
                ):
                    raise FacilityGenerationRunConflictError(
                        "generation_writable_lease_conflict",
                        "Stage checkpoint lease token does not match.",
                    )
            elif lease_owner_token is not None:
                raise FacilityGenerationRunConflictError(
                    "generation_preview_lease_forbidden",
                    "Preview-only stage checkpoints cannot carry a writable lease token.",
                )
            if normalized_receipt["stageId"] != run["currentStageId"]:
                raise FacilityGenerationRunConflictError(
                    "generation_stage_order_invalid",
                    "Stage checkpoint is not for the current eligible stage.",
                )
            stage_index = next(
                index
                for index, item in enumerate(run["stageGraph"])
                if item["stageId"] == normalized_receipt["stageId"]
            )
            expected_next_stage_id = (
                run["stageGraph"][stage_index + 1]["stageId"]
                if stage_index + 1 < len(run["stageGraph"])
                else None
            )
            failed = normalized_receipt["status"] == "failed"
            allowed_next_stage_id = (
                normalized_receipt["stageId"] if failed else expected_next_stage_id
            )
            if next_stage_id != allowed_next_stage_id:
                raise FacilityGenerationRunConflictError(
                    "generation_stage_transition_invalid",
                    "Stage checkpoint does not advance through the frozen stage order.",
                    details={"expectedNextStageId": allowed_next_stage_id},
                )
            draft_path = self._draft_checkpoint_path(tenant_id, site_id, run_id)
            current_draft = _read_record(
                draft_path, "facility_generation_draft"
            )
            if current_draft["draftLayoutRevision"] != normalized_receipt[
                "baseDraftRevision"
            ]:
                raise FacilityGenerationRunConflictError(
                    "generation_draft_revision_conflict",
                    "Stage checkpoint was compiled from a stale draft revision.",
                )
            if normalized_receipt["dependencyFingerprint"] != run[
                "dependencyFingerprint"
            ]:
                raise FacilityGenerationRunConflictError(
                    "generation_dependency_fingerprint_mismatch",
                    "Stage checkpoint dependency fingerprint is stale.",
                )
            receipt_path = self._stage_receipt_path(
                tenant_id, site_id, run_id, normalized_receipt["receiptId"]
            )
            receipt_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_stage_receipt",
                "receiptRevision": _record_revision(normalized_receipt),
                "receipt": normalized_receipt,
            }
            stage_draft_path = self._stage_draft_path(
                tenant_id, site_id, run_id, normalized_receipt["receiptId"]
            )
            existing_receipt = self._load_optional(
                receipt_path, "facility_generation_stage_receipt"
            )
            if existing_receipt is not None and existing_receipt != receipt_record:
                raise FacilityGenerationRunConflictError(
                    "generation_stage_receipt_exists",
                    "A different immutable stage receipt already uses this ID.",
                )
            stage = next(
                item
                for item in run["stageGraph"]
                if item["stageId"] == normalized_receipt["stageId"]
            )
            mutable_stage_fields = {
                "status",
                "inputs",
                "selectedCommandIds",
                "previewId",
                "substageGraph",
                "validation",
                "affectedStableIds",
                "assumptions",
                "unresolvedFindings",
            }
            unknown_stage_fields = sorted(set(stage_update) - mutable_stage_fields - {"tenantId", "siteId"})
            if unknown_stage_fields:
                raise FacilityGenerationRunRepositoryError(
                    "generation_stage_update_invalid",
                    "Stage checkpoint update contains unsupported fields.",
                    details={"unknown": unknown_stage_fields},
                )
            for field in mutable_stage_fields:
                if field in stage_update:
                    stage[field] = deepcopy(stage_update[field])
            if failed and stage["status"] != "blocked":
                raise FacilityGenerationRunConflictError(
                    "generation_failed_stage_not_blocked",
                    "A failed stage receipt must leave its stage blocked.",
                )
            if not failed and stage["status"] not in {"complete", "cancelled"}:
                raise FacilityGenerationRunConflictError(
                    "generation_valid_stage_not_closed",
                    "A valid stage receipt must complete or cancel its stage.",
                )
            stage["operationReceiptIds"].append(normalized_receipt["receiptId"])
            run["receiptChain"].append(normalized_receipt["receiptId"])
            run["currentStageId"] = next_stage_id
            turn_sequence = normalized_receipt["turnSequence"] + 1
            run["resumePoint"] = (
                {
                    "stageId": next_stage_id,
                    "substageId": None,
                    "turnSequence": turn_sequence,
                }
                if next_stage_id is not None
                else None
            )
            run["status"] = (
                "blocked"
                if failed
                else "complete" if next_stage_id is None else "active"
            )
            run["saveEligibility"] = "blocked"
            draft_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_draft",
                "runId": run_id,
                "baseLayoutRevision": run["baseLayoutRevision"],
                "draftLayoutRevision": result_revision,
                "receiptChain": list(run["receiptChain"]),
                "document": normalized_draft,
            }
            now = self._now()
            now_text = _timestamp(now)
            expires_at = _timestamp(now + timedelta(seconds=self.idle_seconds))
            run["updatedAt"] = now_text
            run["lastActivityAt"] = now_text
            run["expiresAt"] = expires_at
            if lease is not None:
                lease = self._lease_payload(
                    run_id=run_id,
                    layout_id=run["layoutId"],
                    owner_token=lease["ownerToken"],
                    base_layout_revision=run["baseLayoutRevision"],
                    acquired_at=lease["acquiredAt"],
                    updated_at=now_text,
                    expires_at=expires_at,
                )
                run["writableLease"] = self._run_lease_view(lease)
            normalized_run = validate_generation_run(run)
            next_envelope = self._run_envelope(normalized_run)
            transaction = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_checkpoint_transaction",
                "transactionId": f"checkpoint-{normalized_receipt['receiptId']}",
                "runId": run_id,
                "expectedRunRevision": expected_run_revision,
                "nextRunEnvelope": next_envelope,
                "draftRecord": draft_record,
                "receiptRecord": receipt_record,
                "stageDraftRecord": deepcopy(draft_record),
                "leaseRecord": deepcopy(lease),
                "createdAt": now_text,
            }
            unsigned_transaction = deepcopy(transaction)
            transaction["transactionRevision"] = _record_revision(
                unsigned_transaction
            )
            transaction_path = self._checkpoint_transaction_path(
                tenant_id, site_id, run_id
            )
            existing_transaction = self._load_optional(
                transaction_path,
                "facility_generation_checkpoint_transaction",
            )
            if existing_transaction is not None and existing_transaction != transaction:
                raise FacilityGenerationRunIntegrityError(
                    "generation_checkpoint_transaction_exists",
                    "A different stage-checkpoint transaction is already pending.",
                )
            if existing_transaction is None:
                self._atomic_write(transaction_path, transaction)
            result = self._apply_checkpoint_transaction_locked(
                tenant_id, site_id, transaction
            )
        return result

    def get_run(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        *,
        allow_expired: bool = False,
    ) -> dict[str, Any]:
        self._reconcile_checkpoint_transaction(tenant_id, site_id, run_id)
        envelope = self._load_run_envelope(tenant_id, site_id, run_id)
        run = envelope["run"]
        now = self._now()
        if (
            run["status"] not in {"saved", "expired"}
            and _parse_timestamp(run["expiresAt"], "expiresAt") <= now
        ):
            self.expire_run(tenant_id, site_id, run_id)
            if not allow_expired:
                raise FacilityGenerationRunRepositoryError(
                    "generation_run_expired",
                    "Generation run expired after 24 hours without activity.",
                    details={"runId": run_id},
                )
            envelope = self._load_run_envelope(tenant_id, site_id, run_id)
        return deepcopy(envelope)

    def get_stage_receipt(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        receipt_id: str,
    ) -> dict[str, Any]:
        receipt = _read_record(
            self._stage_receipt_path(
                tenant_id, site_id, run_id, receipt_id
            ),
            "facility_generation_stage_receipt",
        )
        supersession = self._load_optional(
            self._receipt_supersession_path(
                tenant_id, site_id, run_id, receipt_id
            ),
            "facility_generation_receipt_supersession",
        )
        return {
            **deepcopy(receipt),
            "effectiveStatus": "superseded" if supersession else "valid",
            "supersession": deepcopy(supersession),
        }

    def get_stage_draft(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        receipt_id: str,
    ) -> dict[str, Any]:
        """Return the immutable draft snapshot produced by one stage receipt."""

        receipt = self.get_stage_receipt(
            tenant_id, site_id, run_id, receipt_id
        )
        draft = _read_record(
            self._stage_draft_path(
                tenant_id, site_id, run_id, receipt_id
            ),
            "facility_generation_draft",
        )
        expected_revision = receipt["receipt"]["resultDraftRevision"]
        document = canonicalize_layout(deepcopy(draft.get("document")))
        if layout_revision(document) != expected_revision:
            raise FacilityGenerationRunIntegrityError(
                "generation_stage_draft_revision_mismatch",
                "Immutable stage draft does not match its receipt.",
            )
        return deepcopy(draft)

    def supersede_stage_receipt(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        receipt_id: str,
        *,
        invalidation_id: str,
        reason: str,
    ) -> dict[str, Any]:
        _identifier(invalidation_id, "invalidationId")
        if not isinstance(reason, str) or not reason.strip():
            raise FacilityGenerationRunRepositoryError(
                "generation_receipt_supersession_invalid",
                "Receipt supersession requires a non-empty reason.",
            )
        with self._write_lock(tenant_id, site_id):
            receipt = _read_record(
                self._stage_receipt_path(
                    tenant_id, site_id, run_id, receipt_id
                ),
                "facility_generation_stage_receipt",
            )
            path = self._receipt_supersession_path(
                tenant_id, site_id, run_id, receipt_id
            )
            record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_receipt_supersession",
                "runId": _run_id(run_id),
                "receiptId": _identifier(receipt_id, "receiptId"),
                "receiptRevision": receipt["receiptRevision"],
                "invalidationId": invalidation_id,
                "reason": reason.strip(),
                "supersededAt": _timestamp(self._now()),
            }
            existing = self._load_optional(
                path, "facility_generation_receipt_supersession"
            )
            if existing is not None and existing != record:
                raise FacilityGenerationRunConflictError(
                    "generation_receipt_already_superseded",
                    "Stage receipt already has a different supersession record.",
                )
            if existing is None:
                self._atomic_write(path, record)
        return deepcopy(record)

    def resolve_session_run(
        self, tenant_id: str, site_id: str, session_id: str
    ) -> dict[str, Any] | None:
        path = self._session_path(tenant_id, site_id, session_id)
        binding = self._load_optional(path, "facility_generation_session_binding")
        if binding is None:
            return None
        try:
            return self.get_run(tenant_id, site_id, binding["runId"])
        except (
            FacilityGenerationRunNotFoundError,
            FacilityGenerationRunRepositoryError,
        ) as exc:
            if isinstance(exc, FacilityGenerationRunRepositoryError) and exc.code not in {
                "generation_run_not_found",
                "generation_run_expired",
            }:
                raise
            with self._write_lock(tenant_id, site_id):
                self._remove(path)
            return None

    def update_run(
        self,
        run: Mapping[str, Any],
        *,
        expected_run_revision: str,
        lease_owner_token: str | None = None,
    ) -> dict[str, Any]:
        candidate = deepcopy(dict(run))
        tenant_id = _identifier(candidate.get("tenantId"), "tenantId")
        site_id = _identifier(candidate.get("siteId"), "siteId")
        run_id = _run_id(candidate.get("runId"))
        expected_run_revision = _sha256(expected_run_revision, "expectedRunRevision")
        now = self._now()
        with self._write_lock(tenant_id, site_id):
            current_envelope = self._load_run_envelope(tenant_id, site_id, run_id)
            current = current_envelope["run"]
            if current_envelope["runRevision"] != expected_run_revision:
                raise FacilityGenerationRunConflictError(
                    "generation_run_revision_conflict",
                    "Generation run changed after it was read.",
                    details={"currentRunRevision": current_envelope["runRevision"]},
                )
            for field in _RUN_IMMUTABLE_FIELDS:
                if candidate.get(field) != current.get(field):
                    raise FacilityGenerationRunConflictError(
                        "generation_run_immutable_field_changed",
                        f"Generation run field {field} is immutable.",
                    )
            lease = None
            if current["writable"]:
                lease_path = self._lease_path(
                    tenant_id, site_id, current["layoutId"]
                )
                lease_record = self._load_optional(
                    lease_path, "facility_generation_layout_lease"
                )
                if lease_record is None:
                    raise FacilityGenerationRunConflictError(
                        "generation_writable_lease_lost",
                        "Writable generation run no longer owns a lease.",
                    )
                lease = self._validate_lease_record(lease_record)
                if (
                    lease["runId"] != run_id
                    or lease_owner_token is None
                    or lease["ownerToken"] != lease_owner_token
                ):
                    raise FacilityGenerationRunConflictError(
                        "generation_writable_lease_conflict",
                        "Writable generation lease token does not match.",
                    )
                if _parse_timestamp(lease["expiresAt"], "lease.expiresAt") <= now:
                    raise FacilityGenerationRunConflictError(
                        "generation_writable_lease_expired",
                        "Writable generation lease has expired.",
                    )
            now_text = _timestamp(now)
            expires_at = _timestamp(now + timedelta(seconds=self.idle_seconds))
            candidate["updatedAt"] = now_text
            candidate["lastActivityAt"] = now_text
            candidate["expiresAt"] = expires_at
            releasing = candidate["status"] in _UNSAVED_TERMINAL_STATUSES | {"saved"}
            if releasing:
                candidate["writable"] = False
                candidate["writableLease"] = None
                candidate["saveEligibility"] = (
                    "saved" if candidate["status"] == "saved" else "blocked"
                )
            elif lease is not None:
                lease = self._lease_payload(
                    run_id=run_id,
                    layout_id=current["layoutId"],
                    owner_token=lease["ownerToken"],
                    base_layout_revision=current["baseLayoutRevision"],
                    acquired_at=lease["acquiredAt"],
                    updated_at=now_text,
                    expires_at=expires_at,
                )
                candidate["writable"] = True
                candidate["writableLease"] = self._run_lease_view(lease)
            normalized = validate_generation_run(candidate)
            next_envelope = self._run_envelope(normalized)
            self._atomic_write(
                self._run_path(tenant_id, site_id, run_id), next_envelope
            )
            if lease is not None and not releasing:
                self._atomic_write(
                    self._lease_path(tenant_id, site_id, current["layoutId"]),
                    lease,
                )
            if releasing:
                self._remove(
                    self._lease_path(tenant_id, site_id, current["layoutId"])
                )
                self._remove(
                    self._session_path(tenant_id, site_id, current["sessionId"])
                )
        return deepcopy(next_envelope)

    def expire_run(self, tenant_id: str, site_id: str, run_id: str) -> dict[str, Any]:
        with self._write_lock(tenant_id, site_id):
            envelope = self._load_run_envelope(tenant_id, site_id, run_id)
            run = deepcopy(envelope["run"])
            if run["status"] == "saved":
                return deepcopy(envelope)
            now = self._now()
            now_text = _timestamp(now)
            run["status"] = "expired"
            run["terminalReason"] = "idle_timeout"
            run["writable"] = False
            run["writableLease"] = None
            run["saveEligibility"] = "blocked"
            run["updatedAt"] = now_text
            run["lastActivityAt"] = now_text
            run["expiresAt"] = now_text
            next_envelope = self._run_envelope(run)
            self._atomic_write(
                self._run_path(tenant_id, site_id, run_id), next_envelope
            )
            self._remove(self._lease_path(tenant_id, site_id, run["layoutId"]))
            self._remove(self._session_path(tenant_id, site_id, run["sessionId"]))
            return deepcopy(next_envelope)

    def mark_stale_for_layout_revision(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        *,
        current_layout_revision: str,
    ) -> dict[str, Any]:
        current_layout_revision = _sha256(
            current_layout_revision, "currentLayoutRevision"
        )
        envelope = self.get_run(tenant_id, site_id, run_id)
        run = envelope["run"]
        if run["baseLayoutRevision"] == current_layout_revision:
            return envelope
        now_text = _timestamp(self._now())
        invalidation_id = f"inv-{uuid4().hex}"
        affected = [
            stage["stageId"]
            for stage in run["stageGraph"]
            if stage["status"] not in {"pending", "cancelled"}
        ] or [item["stageId"] for item in run["stageGraph"]]
        invalidation = {
            "invalidationId": invalidation_id,
            "upstreamStageId": "facility_envelope",
            "affectedStageIds": affected,
            "reason": "base_layout_revision_changed",
            "dependencyFingerprintBefore": run["dependencyFingerprint"],
            "dependencyFingerprintAfter": current_layout_revision,
            "createdAt": now_text,
            "resolved": False,
        }
        run["invalidations"].append(invalidation)
        for stage in run["stageGraph"]:
            if stage["stageId"] in affected:
                stage["status"] = "invalidated"
                stage["invalidationEdges"].append(invalidation_id)
        run["dependencyFingerprint"] = current_layout_revision
        run["status"] = "stale"
        run["terminalReason"] = "base_layout_revision_changed"
        run["saveEligibility"] = "blocked"
        updated = self.update_run(
            run,
            expected_run_revision=envelope["runRevision"],
            lease_owner_token=(
                run["writableLease"]["ownerToken"]
                if run["writableLease"] is not None
                else None
            ),
        )
        for receipt_id in run["receiptChain"]:
            self.supersede_stage_receipt(
                tenant_id,
                site_id,
                run_id,
                receipt_id,
                invalidation_id=invalidation_id,
                reason="base_layout_revision_changed",
            )
        return updated

    def invalidate_stage_chain(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        *,
        upstream_stage_id: str,
        reason: str,
        dependency_fingerprint_after: str,
        expected_run_revision: str,
        lease_owner_token: str,
    ) -> dict[str, Any]:
        """Supersede one stage and its descendants, then restore the prior draft."""

        if reason not in {
            "upstream_dependency_changed",
            "source_revision_changed",
            "provider_configuration_changed",
            "user_cancelled",
        }:
            raise FacilityGenerationRunRepositoryError(
                "generation_invalidation_reason_invalid",
                "Stage-chain invalidation reason is unsupported.",
            )
        dependency_fingerprint_after = _sha256(
            dependency_fingerprint_after, "dependencyFingerprintAfter"
        )
        expected_run_revision = _sha256(
            expected_run_revision, "expectedRunRevision"
        )
        with self._write_lock(tenant_id, site_id):
            envelope = self._load_run_envelope(tenant_id, site_id, run_id)
            if envelope["runRevision"] != expected_run_revision:
                raise FacilityGenerationRunConflictError(
                    "generation_run_revision_conflict",
                    "Generation run changed before invalidation.",
                    details={"currentRunRevision": envelope["runRevision"]},
                )
            run = deepcopy(envelope["run"])
            stage_ids = [item["stageId"] for item in run["stageGraph"]]
            if upstream_stage_id not in stage_ids:
                raise FacilityGenerationRunRepositoryError(
                    "generation_stage_not_found",
                    "Invalidation upstream stage is unknown.",
                )
            upstream_index = stage_ids.index(upstream_stage_id)
            lease_path = self._lease_path(tenant_id, site_id, run["layoutId"])
            lease_record = self._load_optional(
                lease_path, "facility_generation_layout_lease"
            )
            if lease_record is None:
                raise FacilityGenerationRunConflictError(
                    "generation_writable_lease_lost",
                    "Stage invalidation requires the writable generation lease.",
                )
            lease = self._validate_lease_record(lease_record)
            if (
                lease["runId"] != run_id
                or lease["ownerToken"] != lease_owner_token
            ):
                raise FacilityGenerationRunConflictError(
                    "generation_writable_lease_conflict",
                    "Stage invalidation lease token does not match.",
                )
            receipt_stage_by_id: dict[str, str] = {}
            for receipt_id in run["receiptChain"]:
                record = _read_record(
                    self._stage_receipt_path(
                        tenant_id, site_id, run_id, receipt_id
                    ),
                    "facility_generation_stage_receipt",
                )
                receipt_stage_by_id[receipt_id] = record["receipt"]["stageId"]
            retained_receipts = [
                receipt_id
                for receipt_id in run["receiptChain"]
                if stage_ids.index(receipt_stage_by_id[receipt_id]) < upstream_index
            ]
            superseded_receipts = [
                receipt_id
                for receipt_id in run["receiptChain"]
                if receipt_id not in retained_receipts
            ]
            if retained_receipts:
                restored = _read_record(
                    self._stage_draft_path(
                        tenant_id,
                        site_id,
                        run_id,
                        retained_receipts[-1],
                    ),
                    "facility_generation_draft",
                )
                restored_document = canonicalize_layout(
                    deepcopy(restored["document"])
                )
            else:
                base = _read_record(
                    self._base_layout_path(tenant_id, site_id, run_id),
                    "facility_generation_base_layout",
                )
                restored_document = canonicalize_layout(
                    deepcopy(base["document"])
                )
            invalidation_id = f"inv-{uuid4().hex}"
            now = self._now()
            now_text = _timestamp(now)
            affected_stage_ids = stage_ids[upstream_index:]
            invalidation = {
                "invalidationId": invalidation_id,
                "upstreamStageId": upstream_stage_id,
                "affectedStageIds": affected_stage_ids,
                "reason": reason,
                "dependencyFingerprintBefore": run["dependencyFingerprint"],
                "dependencyFingerprintAfter": dependency_fingerprint_after,
                "createdAt": now_text,
                "resolved": False,
            }
            run["invalidations"].append(invalidation)
            for index, stage in enumerate(run["stageGraph"]):
                if index < upstream_index:
                    continue
                stage["status"] = "ready" if index == upstream_index else "pending"
                stage["validation"] = {"status": "pending", "findingIds": []}
                stage["invalidationEdges"].append(invalidation_id)
                stage["previewId"] = None
                stage["unresolvedFindings"] = []
            run["receiptChain"] = retained_receipts
            run["currentStageId"] = upstream_stage_id
            run["resumePoint"] = {
                "stageId": upstream_stage_id,
                "substageId": None,
                "turnSequence": len(retained_receipts),
            }
            run["dependencyFingerprint"] = dependency_fingerprint_after
            run["status"] = "active"
            run["terminalReason"] = None
            run["cumulativeDiffHash"] = None
            run["cumulativeProposal"] = None
            run["saveEligibility"] = "blocked"
            expires_at = _timestamp(now + timedelta(seconds=self.idle_seconds))
            run["updatedAt"] = now_text
            run["lastActivityAt"] = now_text
            run["expiresAt"] = expires_at
            lease = self._lease_payload(
                run_id=run_id,
                layout_id=run["layoutId"],
                owner_token=lease["ownerToken"],
                base_layout_revision=run["baseLayoutRevision"],
                acquired_at=lease["acquiredAt"],
                updated_at=now_text,
                expires_at=expires_at,
            )
            run["writableLease"] = self._run_lease_view(lease)
            draft_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_draft",
                "runId": run_id,
                "baseLayoutRevision": run["baseLayoutRevision"],
                "draftLayoutRevision": layout_revision(restored_document),
                "receiptChain": retained_receipts,
                "document": restored_document,
            }
            for receipt_id in superseded_receipts:
                receipt_record = _read_record(
                    self._stage_receipt_path(
                        tenant_id, site_id, run_id, receipt_id
                    ),
                    "facility_generation_stage_receipt",
                )
                supersession_path = self._receipt_supersession_path(
                    tenant_id, site_id, run_id, receipt_id
                )
                supersession = {
                    "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                    "recordKind": "facility_generation_receipt_supersession",
                    "runId": run_id,
                    "receiptId": receipt_id,
                    "receiptRevision": receipt_record["receiptRevision"],
                    "invalidationId": invalidation_id,
                    "reason": reason,
                    "supersededAt": now_text,
                }
                existing = self._load_optional(
                    supersession_path,
                    "facility_generation_receipt_supersession",
                )
                if existing is not None and existing != supersession:
                    raise FacilityGenerationRunConflictError(
                        "generation_receipt_already_superseded",
                        "A stage receipt already has a different supersession.",
                    )
                if existing is None:
                    self._atomic_write(supersession_path, supersession)
            next_envelope = self._run_envelope(validate_generation_run(run))
            self._atomic_write(
                self._draft_checkpoint_path(tenant_id, site_id, run_id),
                draft_record,
            )
            self._atomic_write(
                self._run_path(tenant_id, site_id, run_id), next_envelope
            )
            self._atomic_write(lease_path, lease)
        return {
            "run": deepcopy(next_envelope),
            "draft": deepcopy(draft_record),
            "invalidation": deepcopy(invalidation),
            "supersededReceiptIds": superseded_receipts,
        }

    def prepare_save_intent(
        self,
        tenant_id: str,
        site_id: str,
        run_id: str,
        *,
        expected_run_revision: str,
        lease_owner_token: str,
        cumulative_diff_hash: str,
        approved_by: str,
    ) -> dict[str, Any]:
        """Freeze one explicit approval before external layout persistence."""

        run_id = _run_id(run_id)
        expected_run_revision = _sha256(
            expected_run_revision, "expectedRunRevision"
        )
        cumulative_diff_hash = _sha256(
            cumulative_diff_hash, "cumulativeDiffHash"
        )
        approved_by = _identifier(approved_by, "approvedBy")
        self._reconcile_checkpoint_transaction(tenant_id, site_id, run_id)
        with self._write_lock(tenant_id, site_id):
            envelope = self._load_run_envelope(tenant_id, site_id, run_id)
            run = envelope["run"]
            if envelope["runRevision"] != expected_run_revision:
                raise FacilityGenerationRunConflictError(
                    "generation_run_revision_conflict",
                    "Generation run changed before Save approval was prepared.",
                    details={"currentRunRevision": envelope["runRevision"]},
                )
            if (
                run["status"] != "complete"
                or run["saveEligibility"] != "eligible"
                or run["cumulativeDiffHash"] != cumulative_diff_hash
            ):
                raise FacilityGenerationRunConflictError(
                    "generation_run_not_save_eligible",
                    "Generation run is not eligible for the approved cumulative diff.",
                )
            lease_path = self._lease_path(
                tenant_id, site_id, run["layoutId"]
            )
            lease_record = self._load_optional(
                lease_path, "facility_generation_layout_lease"
            )
            if lease_record is None:
                raise FacilityGenerationRunConflictError(
                    "generation_writable_lease_lost",
                    "Save approval requires the writable generation lease.",
                )
            lease = self._validate_lease_record(lease_record)
            if (
                lease["runId"] != run_id
                or lease["ownerToken"] != lease_owner_token
            ):
                raise FacilityGenerationRunConflictError(
                    "generation_writable_lease_conflict",
                    "Save approval lease token does not match the writable run.",
                )
            path = self._save_intent_path(tenant_id, site_id, run_id)
            existing = self._load_optional(
                path, "facility_generation_save_intent"
            )
            if existing is not None:
                unsigned_existing = deepcopy(existing)
                existing_revision = unsigned_existing.pop(
                    "intentRevision", None
                )
                if existing_revision != _record_revision(unsigned_existing):
                    raise FacilityGenerationRunIntegrityError(
                        "generation_save_intent_revision_mismatch",
                        "Pending Save approval revision is invalid.",
                    )
                if (
                    existing.get("runRevision") != expected_run_revision
                    or existing.get("cumulativeDiffHash")
                    != cumulative_diff_hash
                    or existing.get("approvedBy") != approved_by
                ):
                    raise FacilityGenerationRunConflictError(
                        "generation_save_intent_conflict",
                        "A different explicit Save approval is already pending.",
                    )
                return deepcopy(existing)
            intent = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_save_intent",
                "runId": run_id,
                "runRevision": expected_run_revision,
                "cumulativeDiffHash": cumulative_diff_hash,
                "receiptChain": list(run["receiptChain"]),
                "approvedBy": approved_by,
                "approvedAt": _timestamp(self._now()),
            }
            intent["intentRevision"] = _record_revision(intent)
            self._atomic_write(path, intent)
            return deepcopy(intent)

    def record_saved_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        expected_run_revision: str,
        lease_owner_token: str,
    ) -> dict[str, Any]:
        normalized = validate_generation_save_receipt(receipt)
        tenant_id = normalized["tenantId"]
        site_id = normalized["siteId"]
        expected_run_revision = _sha256(
            expected_run_revision, "expectedRunRevision"
        )
        with self._write_lock(tenant_id, site_id):
            envelope = self._load_run_envelope(
                tenant_id, site_id, normalized["runId"]
            )
            run = deepcopy(envelope["run"])
            if envelope["runRevision"] != expected_run_revision:
                raise FacilityGenerationRunConflictError(
                    "generation_run_revision_conflict",
                    "Generation run changed before its save receipt was recorded.",
                    details={"currentRunRevision": envelope["runRevision"]},
                )
            for field, receipt_field in (
                ("workspaceId", "workspaceId"),
                ("layoutId", "layoutId"),
                ("baseLayoutRevision", "baseLayoutRevision"),
                ("cumulativeDiffHash", "cumulativeDiffHash"),
                ("dependencyFingerprint", "dependencyFingerprint"),
            ):
                if run[field] != normalized[receipt_field]:
                    raise FacilityGenerationRunConflictError(
                        "generation_save_receipt_mismatch",
                        f"Save receipt {receipt_field} does not match the run.",
                    )
            if run["saveEligibility"] != "eligible" or run["cumulativeProposal"] is None:
                raise FacilityGenerationRunConflictError(
                    "generation_run_not_save_eligible",
                    "Generation run has no valid cumulative proposal to save.",
                )
            if run["receiptChain"] != normalized["receiptChain"]:
                raise FacilityGenerationRunConflictError(
                    "receipt_chain_invalid",
                    "Save receipt does not bind the complete ordered receipt chain.",
                )
            lease_path = self._lease_path(tenant_id, site_id, run["layoutId"])
            lease_record = self._load_optional(
                lease_path, "facility_generation_layout_lease"
            )
            if lease_record is None:
                raise FacilityGenerationRunConflictError(
                    "generation_writable_lease_lost",
                    "Save cannot proceed without the writable run lease.",
                )
            lease = self._validate_lease_record(lease_record)
            if (
                lease["runId"] != run["runId"]
                or lease["ownerToken"] != lease_owner_token
            ):
                raise FacilityGenerationRunConflictError(
                    "generation_writable_lease_conflict",
                    "Save lease token does not match the writable run.",
                )
            path = self._save_receipt_path(
                tenant_id,
                site_id,
                run["layoutId"],
                normalized["savedLayoutRevision"],
                normalized["saveReceiptId"],
            )
            receipt_record = {
                "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
                "recordKind": "facility_generation_save_receipt",
                "receiptRevision": _record_revision(normalized),
                "receipt": normalized,
            }
            receipt_existed = os.path.exists(_native_fs_path(path))
            if receipt_existed:
                existing = _read_record(path, "facility_generation_save_receipt")
                if existing.get("receipt") != normalized:
                    raise FacilityGenerationRunConflictError(
                        "generation_save_receipt_exists",
                        "A different save receipt already uses this ID.",
                    )
            now_text = _timestamp(self._now())
            run["status"] = "saved"
            run["terminalReason"] = None
            run["writable"] = False
            run["writableLease"] = None
            run["saveEligibility"] = "saved"
            run["cumulativeProposal"]["saveEligibility"] = "saved"
            run["updatedAt"] = now_text
            run["lastActivityAt"] = now_text
            run["expiresAt"] = now_text
            saved_envelope = self._run_envelope(run)
            try:
                if not receipt_existed:
                    self._atomic_write(path, receipt_record)
                self._atomic_write(
                    self._run_path(tenant_id, site_id, run["runId"]),
                    saved_envelope,
                )
            except Exception:
                if not receipt_existed:
                    self._remove(path)
                raise
            self._remove(lease_path)
            self._remove(
                self._session_path(tenant_id, site_id, run["sessionId"])
            )
            self._remove(
                self._save_intent_path(tenant_id, site_id, run["runId"])
            )
            return deepcopy(saved_envelope)

    def get_saved_receipt(
        self,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        saved_layout_revision: str,
        save_receipt_id: str,
    ) -> dict[str, Any]:
        record = _read_record(
            self._save_receipt_path(
                tenant_id,
                site_id,
                layout_id,
                saved_layout_revision,
                save_receipt_id,
            ),
            "facility_generation_save_receipt",
        )
        receipt = validate_generation_save_receipt(record.get("receipt"))
        if record.get("receiptRevision") != _record_revision(receipt):
            raise FacilityGenerationRunIntegrityError(
                "generation_save_receipt_revision_mismatch",
                "Generation save receipt revision is invalid.",
            )
        return deepcopy(record)

    def _write_tombstone(
        self,
        run: Mapping[str, Any],
        run_revision: str,
        now: datetime,
    ) -> dict[str, Any]:
        value = {
            "schemaVersion": FACILITY_GENERATION_RUN_SCHEMA_VERSION,
            "recordKind": "facility_generation_run_tombstone",
            "runId": run["runId"],
            "tenantId": run["tenantId"],
            "siteId": run["siteId"],
            "workspaceId": run["workspaceId"],
            "layoutId": run["layoutId"],
            "userId": run["userId"],
            "sessionId": run["sessionId"],
            "baseLayoutRevision": run["baseLayoutRevision"],
            "status": run["status"],
            "terminalReason": run["terminalReason"],
            "createdAt": run["createdAt"],
            "lastActivityAt": run["lastActivityAt"],
            "terminatedAt": _timestamp(now),
            "deleteAfter": _timestamp(
                now + timedelta(seconds=self.tombstone_retention_seconds)
            ),
            "finalRunRevision": run_revision,
        }
        value["tombstoneRevision"] = _record_revision(value)
        self._atomic_write(
            self._tombstone_path(
                run["tenantId"], run["siteId"], run["runId"]
            ),
            value,
        )
        return value

    def get_tombstone(
        self, tenant_id: str, site_id: str, run_id: str
    ) -> dict[str, Any]:
        record = _read_record(
            self._tombstone_path(tenant_id, site_id, run_id),
            "facility_generation_run_tombstone",
        )
        unsigned = deepcopy(record)
        revision = unsigned.pop("tombstoneRevision", None)
        if revision != _record_revision(unsigned):
            raise FacilityGenerationRunIntegrityError(
                "generation_tombstone_revision_mismatch",
                "Generation-run tombstone revision is invalid.",
            )
        return deepcopy(record)

    def garbage_collect(self, tenant_id: str, site_id: str) -> dict[str, int]:
        now = self._now()
        scope = self._scope_root(tenant_id, site_id)
        counts = {"expiredRuns": 0, "tombstonedRuns": 0, "deletedTombstones": 0}
        with self._write_lock(tenant_id, site_id):
            runs_root = scope / "runs"
            if os.path.isdir(_native_fs_path(runs_root)):
                for entry in list(os.scandir(_native_fs_path(runs_root))):
                    if not entry.is_file() or not entry.name.endswith(".json"):
                        continue
                    run_id = entry.name[:-5]
                    try:
                        envelope = self._load_run_envelope(
                            tenant_id, site_id, run_id
                        )
                    except FacilityGenerationRunRepositoryError:
                        raise
                    run = envelope["run"]
                    if (
                        run["status"] not in {"saved", "expired"}
                        and _parse_timestamp(run["expiresAt"], "expiresAt") <= now
                    ):
                        run["status"] = "expired"
                        run["terminalReason"] = "idle_timeout"
                        run["writable"] = False
                        run["writableLease"] = None
                        run["saveEligibility"] = "blocked"
                        run["updatedAt"] = _timestamp(now)
                        run["lastActivityAt"] = _timestamp(now)
                        run["expiresAt"] = _timestamp(now)
                        envelope = self._run_envelope(run)
                        self._atomic_write(
                            self._run_path(tenant_id, site_id, run_id), envelope
                        )
                        counts["expiredRuns"] += 1
                    if run["status"] in _UNSAVED_TERMINAL_STATUSES:
                        self._write_tombstone(
                            run, envelope["runRevision"], now
                        )
                        self._remove(
                            self._lease_path(tenant_id, site_id, run["layoutId"])
                        )
                        self._remove(
                            self._session_path(tenant_id, site_id, run["sessionId"])
                        )
                        self._remove(
                            self._run_path(tenant_id, site_id, run_id)
                        )
                        counts["tombstonedRuns"] += 1
            tombstones_root = scope / "tombstones"
            if os.path.isdir(_native_fs_path(tombstones_root)):
                for entry in list(os.scandir(_native_fs_path(tombstones_root))):
                    if not entry.is_file() or not entry.name.endswith(".json"):
                        continue
                    path = Path(entry.path)
                    record = _read_record(
                        path, "facility_generation_run_tombstone"
                    )
                    if _parse_timestamp(record["deleteAfter"], "deleteAfter") <= now:
                        self._remove(path)
                        counts["deletedTombstones"] += 1
        return counts


__all__ = [
    "FACILITY_GENERATION_LOCK_STALE_SECONDS",
    "FACILITY_GENERATION_LOCK_TIMEOUT_SECONDS",
    "FACILITY_GENERATION_RUN_IDLE_SECONDS",
    "FACILITY_GENERATION_TOMBSTONE_RETENTION_SECONDS",
    "FacilityGenerationRunConflictError",
    "FacilityGenerationRunIntegrityError",
    "FacilityGenerationRunNotFoundError",
    "FacilityGenerationRunRepository",
    "FacilityGenerationRunRepositoryError",
]
