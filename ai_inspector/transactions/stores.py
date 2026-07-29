"""Volatile transaction state and durable receipt/idempotency stores."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Union

from .types import (
    ApprovalRecord,
    IdempotencyRecord,
    PreparedRecord,
    ProposalRecord,
    TransactionIdempotencyConflictError,
    TransactionNotFoundError,
    TransactionPreparedError,
    TransactionReceipt,
    TransactionValidationError,
    validate_idempotency_key,
    validate_token,
)


MAX_STORE_RECORDS = 4096
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_STORAGE_ROOT_LENGTH = 4096


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON as deterministic, human-readable ASCII bytes."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TransactionValidationError(
            "invalid_transaction_payload",
            f"Transaction data is not canonical JSON: {exc}",
        ) from exc
    return (text + "\n").encode("ascii")


class ReceiptStore(Protocol):
    """Persistence boundary consumed by the transaction kernel."""

    recover_exact_retries: bool

    def lookup(
        self,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Optional[IdempotencyRecord]:
        ...

    def prepare(self, prepared: PreparedRecord) -> IdempotencyRecord:
        ...

    def finalize(
        self,
        prepared: PreparedRecord,
        receipt: TransactionReceipt,
    ) -> IdempotencyRecord:
        ...

    def get_receipt(self, receipt_id: str) -> TransactionReceipt:
        ...


def _validate_capacity(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TransactionValidationError(
            "invalid_transaction_capacity",
            f"{field_name} must be an integer.",
        )
    if value < 1 or value > MAX_STORE_RECORDS:
        raise TransactionValidationError(
            "invalid_transaction_capacity",
            f"{field_name} must be between 1 and {MAX_STORE_RECORDS}.",
        )
    return value


class VolatileTransactionStore:
    """In-process proposal and approval state.

    This store is intentionally non-durable. Constructing a new instance after
    restart loses every proposal and approval, so authorization fails closed.
    """

    def __init__(
        self,
        *,
        max_proposals: int = 512,
        max_approvals: int = 512,
    ) -> None:
        self._max_proposals = _validate_capacity(max_proposals, "maxProposals")
        self._max_approvals = _validate_capacity(max_approvals, "maxApprovals")
        self._proposals: "OrderedDict[str, ProposalRecord]" = OrderedDict()
        self._approvals: "OrderedDict[str, ApprovalRecord]" = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _make_room(
        records: "OrderedDict[str, Any]",
        *,
        capacity: int,
        now: float,
        kind: str,
    ) -> None:
        removable = [
            record_id
            for record_id, record in records.items()
            if record.status != "active" or record.expires_at <= now
        ]
        for record_id in removable:
            records.pop(record_id, None)
            if len(records) < capacity:
                return
        if len(records) >= capacity:
            raise TransactionValidationError(
                "transaction_capacity_exceeded",
                f"Too many active {kind} records.",
            )

    def put_proposal(self, proposal: ProposalRecord, *, now: float) -> None:
        if not isinstance(proposal, ProposalRecord):
            raise TransactionValidationError(
                "invalid_proposal_record",
                "proposal must be a ProposalRecord.",
            )
        with self._lock:
            if proposal.proposal_id not in self._proposals:
                self._make_room(
                    self._proposals,
                    capacity=self._max_proposals,
                    now=now,
                    kind="proposal",
                )
            self._proposals[proposal.proposal_id] = deepcopy(proposal)
            self._proposals.move_to_end(proposal.proposal_id)

    def get_proposal(self, proposal_id: str) -> Optional[ProposalRecord]:
        proposal_id = validate_token(proposal_id, "proposalId")
        with self._lock:
            record = self._proposals.get(proposal_id)
            return deepcopy(record) if record is not None else None

    def put_approval(self, approval: ApprovalRecord, *, now: float) -> None:
        if not isinstance(approval, ApprovalRecord):
            raise TransactionValidationError(
                "invalid_approval_record",
                "approval must be an ApprovalRecord.",
            )
        with self._lock:
            if approval.approval_token not in self._approvals:
                self._make_room(
                    self._approvals,
                    capacity=self._max_approvals,
                    now=now,
                    kind="approval",
                )
            self._approvals[approval.approval_token] = deepcopy(approval)
            self._approvals.move_to_end(approval.approval_token)

    def get_approval(self, approval_token: str) -> Optional[ApprovalRecord]:
        approval_token = validate_token(approval_token, "approvalToken")
        with self._lock:
            record = self._approvals.get(approval_token)
            return deepcopy(record) if record is not None else None

    def find_approval_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Optional[ApprovalRecord]:
        key = validate_idempotency_key(idempotency_key)
        with self._lock:
            for record in reversed(tuple(self._approvals.values())):
                if record.idempotency_key == key:
                    return deepcopy(record)
        return None

    def cancel_proposal(self, proposal_id: str) -> ProposalRecord:
        proposal_id = validate_token(proposal_id, "proposalId")
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise TransactionNotFoundError(
                    "proposal_not_found",
                    "Proposal was not found.",
                )
            if proposal.status != "cancelled":
                proposal = replace(proposal, status="cancelled")
                self._proposals[proposal_id] = proposal
            for token, approval in tuple(self._approvals.items()):
                if (
                    approval.proposal_id == proposal_id
                    and approval.status != "cancelled"
                ):
                    self._approvals[token] = replace(
                        approval,
                        status="cancelled",
                    )
            return deepcopy(proposal)

    def consume(self, proposal_id: str, approval_token: str) -> None:
        proposal_id = validate_token(proposal_id, "proposalId")
        approval_token = validate_token(approval_token, "approvalToken")
        with self._lock:
            self._proposals.pop(proposal_id, None)
            self._approvals.pop(approval_token, None)
            for token, approval in tuple(self._approvals.items()):
                if approval.proposal_id == proposal_id:
                    self._approvals.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._proposals.clear()
            self._approvals.clear()


class InMemoryReceiptStore:
    """Compatibility receipt store with strict replay rejection."""

    recover_exact_retries = False

    def __init__(self, *, max_records: int = MAX_STORE_RECORDS) -> None:
        self._max_records = _validate_capacity(max_records, "maxRecords")
        self._records: Dict[str, IdempotencyRecord] = {}
        self._receipts: Dict[str, TransactionReceipt] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _verify_fingerprint(
        record: IdempotencyRecord,
        request_fingerprint: str,
    ) -> None:
        if record.prepared.request_fingerprint != request_fingerprint:
            raise TransactionIdempotencyConflictError(
                "idempotency_key_conflict",
                "The idempotency key is already bound to another request.",
            )

    def lookup(
        self,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Optional[IdempotencyRecord]:
        key = validate_idempotency_key(idempotency_key)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            self._verify_fingerprint(record, request_fingerprint)
            return deepcopy(record)

    def prepare(self, prepared: PreparedRecord) -> IdempotencyRecord:
        if not isinstance(prepared, PreparedRecord):
            raise TransactionValidationError(
                "invalid_prepared_record",
                "prepared must be a PreparedRecord.",
            )
        with self._lock:
            existing = self._records.get(prepared.idempotency_key)
            if existing is not None:
                self._verify_fingerprint(
                    existing,
                    prepared.request_fingerprint,
                )
                if existing.prepared != prepared:
                    raise TransactionIdempotencyConflictError(
                        "prepared_transaction_conflict",
                        "Prepared transaction identity does not match.",
                    )
                return deepcopy(existing)
            if len(self._records) >= self._max_records:
                raise TransactionValidationError(
                    "transaction_capacity_exceeded",
                    "Too many idempotency records.",
                )
            record = IdempotencyRecord("prepared", deepcopy(prepared))
            self._records[prepared.idempotency_key] = record
            return deepcopy(record)

    def finalize(
        self,
        prepared: PreparedRecord,
        receipt: TransactionReceipt,
    ) -> IdempotencyRecord:
        candidate = IdempotencyRecord("finalized", prepared, receipt)
        with self._lock:
            existing = self._records.get(prepared.idempotency_key)
            if existing is None:
                raise TransactionPreparedError(
                    "prepared_record_not_found",
                    "Transaction must be prepared before finalization.",
                )
            self._verify_fingerprint(
                existing,
                prepared.request_fingerprint,
            )
            if existing.prepared != prepared:
                raise TransactionIdempotencyConflictError(
                    "prepared_transaction_conflict",
                    "Prepared transaction identity does not match.",
                )
            if existing.state == "finalized":
                if existing != candidate:
                    raise TransactionIdempotencyConflictError(
                        "receipt_conflict",
                        "Finalized transaction receipt does not match.",
                    )
                return deepcopy(existing)
            known_receipt = self._receipts.get(receipt.receipt_id)
            if known_receipt is not None and known_receipt != receipt:
                raise TransactionIdempotencyConflictError(
                    "receipt_conflict",
                    "Receipt ID is already bound to another result.",
                )
            self._receipts[receipt.receipt_id] = deepcopy(receipt)
            self._records[prepared.idempotency_key] = deepcopy(candidate)
            return deepcopy(candidate)

    def get_receipt(self, receipt_id: str) -> TransactionReceipt:
        receipt_id = validate_token(receipt_id, "receiptId")
        with self._lock:
            receipt = self._receipts.get(receipt_id)
            if receipt is None:
                raise TransactionNotFoundError(
                    "receipt_not_found",
                    "Transaction receipt was not found.",
                )
            return deepcopy(receipt)


_ROOT_LOCKS: Dict[str, threading.RLock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


def _shared_root_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(str(root))
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _ROOT_LOCKS[key] = lock
        return lock


def _native_fs_path(path: Path) -> str:
    """Return an extended Windows path for deep transaction stores."""

    value = os.path.abspath(str(path))
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


class JsonReceiptStore:
    """Canonical atomic receipt store with durable exact-retry recovery."""

    recover_exact_retries = True

    def __init__(self, root: Union[str, os.PathLike[str]]) -> None:
        if isinstance(root, bytes) or not isinstance(root, (str, os.PathLike)):
            raise TransactionValidationError(
                "invalid_transaction_store_path",
                "Receipt store root must be a filesystem path.",
            )
        raw = os.fspath(root)
        if (
            not raw
            or "\x00" in raw
            or len(raw) > MAX_STORAGE_ROOT_LENGTH
        ):
            raise TransactionValidationError(
                "invalid_transaction_store_path",
                "Receipt store root is empty or exceeds the path limit.",
            )
        try:
            resolved = Path(raw).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TransactionValidationError(
                "invalid_transaction_store_path",
                "Receipt store root could not be resolved.",
            ) from exc
        if resolved == Path(resolved.anchor):
            raise TransactionValidationError(
                "invalid_transaction_store_path",
                "Receipt store root cannot be a filesystem root.",
            )
        if resolved.exists() and not resolved.is_dir():
            raise TransactionValidationError(
                "invalid_transaction_store_path",
                "Receipt store root must be a directory.",
            )
        self.root = resolved
        self._idempotency_dir = self._safe_child("idempotency")
        self._receipt_dir = self._safe_child("receipts")
        self._lock = _shared_root_lock(self.root)
        with self._lock:
            self._idempotency_dir.mkdir(parents=True, exist_ok=True)
            self._receipt_dir.mkdir(parents=True, exist_ok=True)

    def _safe_child(self, *parts: str) -> Path:
        candidate = self.root.joinpath(*parts)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise TransactionValidationError(
                "invalid_transaction_store_path",
                "Receipt store path escaped its configured root.",
            ) from exc
        return candidate

    @staticmethod
    def _filename(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest() + ".json"

    def _idempotency_path(self, key: str) -> Path:
        return self._safe_child("idempotency", self._filename(key))

    def _receipt_path(self, receipt_id: str) -> Path:
        return self._safe_child("receipts", self._filename(receipt_id))

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        for attempt in range(6):
            temporary_name: Optional[str] = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                native_parent = _native_fs_path(path.parent)
                native_path = _native_fs_path(path)
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=native_parent,
                    prefix=".txn-",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary_name = handle.name
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, native_path)
                temporary_name = None
                return
            except (FileNotFoundError, PermissionError):
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
            finally:
                if temporary_name is not None:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass

    @staticmethod
    def _read_mapping(path: Path) -> Mapping[str, Any]:
        try:
            native_path = _native_fs_path(path)
            size = os.stat(native_path).st_size
            if size < 1 or size > MAX_RECORD_BYTES:
                raise TransactionValidationError(
                    "corrupt_transaction_store",
                    "Transaction record size is invalid.",
                )
            with open(native_path, "rb") as stream:
                raw = stream.read()
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise TransactionValidationError(
                "transaction_store_read_failed",
                "Transaction record could not be read.",
            ) from exc
        if any(byte > 0x7F for byte in raw):
            raise TransactionValidationError(
                "corrupt_transaction_store",
                "Transaction record is not ASCII.",
            )
        try:
            parsed = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransactionValidationError(
                "corrupt_transaction_store",
                "Transaction record is not valid JSON.",
            ) from exc
        if not isinstance(parsed, Mapping):
            raise TransactionValidationError(
                "corrupt_transaction_store",
                "Transaction record must contain an object.",
            )
        if raw != canonical_json_bytes(parsed):
            raise TransactionValidationError(
                "corrupt_transaction_store",
                "Transaction record is not in canonical form.",
            )
        return parsed

    def _load_idempotency(self, key: str) -> Optional[IdempotencyRecord]:
        path = self._idempotency_path(key)
        try:
            parsed = self._read_mapping(path)
        except FileNotFoundError:
            return None
        return IdempotencyRecord.from_dict(parsed)

    def _load_receipt(self, receipt_id: str) -> Optional[TransactionReceipt]:
        path = self._receipt_path(receipt_id)
        try:
            parsed = self._read_mapping(path)
        except FileNotFoundError:
            return None
        return TransactionReceipt.from_dict(parsed)

    @staticmethod
    def _verify_fingerprint(
        record: IdempotencyRecord,
        request_fingerprint: str,
    ) -> None:
        if record.prepared.request_fingerprint != request_fingerprint:
            raise TransactionIdempotencyConflictError(
                "idempotency_key_conflict",
                "The idempotency key is already bound to another request.",
            )

    def lookup(
        self,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Optional[IdempotencyRecord]:
        key = validate_idempotency_key(idempotency_key)
        with self._lock:
            record = self._load_idempotency(key)
            if record is None:
                return None
            self._verify_fingerprint(record, request_fingerprint)
            return deepcopy(record)

    def prepare(self, prepared: PreparedRecord) -> IdempotencyRecord:
        if not isinstance(prepared, PreparedRecord):
            raise TransactionValidationError(
                "invalid_prepared_record",
                "prepared must be a PreparedRecord.",
            )
        with self._lock:
            existing = self._load_idempotency(prepared.idempotency_key)
            if existing is not None:
                self._verify_fingerprint(
                    existing,
                    prepared.request_fingerprint,
                )
                if existing.prepared != prepared:
                    raise TransactionIdempotencyConflictError(
                        "prepared_transaction_conflict",
                        "Prepared transaction identity does not match.",
                    )
                return deepcopy(existing)
            record = IdempotencyRecord("prepared", prepared)
            self._atomic_write(
                self._idempotency_path(prepared.idempotency_key),
                canonical_json_bytes(record.to_dict()),
            )
            return deepcopy(record)

    def finalize(
        self,
        prepared: PreparedRecord,
        receipt: TransactionReceipt,
    ) -> IdempotencyRecord:
        candidate = IdempotencyRecord("finalized", prepared, receipt)
        with self._lock:
            existing = self._load_idempotency(prepared.idempotency_key)
            if existing is None:
                raise TransactionPreparedError(
                    "prepared_record_not_found",
                    "Transaction must be prepared before finalization.",
                )
            self._verify_fingerprint(
                existing,
                prepared.request_fingerprint,
            )
            if existing.prepared != prepared:
                raise TransactionIdempotencyConflictError(
                    "prepared_transaction_conflict",
                    "Prepared transaction identity does not match.",
                )
            if existing.state == "finalized":
                if existing != candidate:
                    raise TransactionIdempotencyConflictError(
                        "receipt_conflict",
                        "Finalized transaction receipt does not match.",
                    )
                return deepcopy(existing)
            known_receipt = self._load_receipt(receipt.receipt_id)
            if known_receipt is not None and known_receipt != receipt:
                recovered_candidate = replace(
                    receipt,
                    created_at=known_receipt.created_at,
                )
                if known_receipt != recovered_candidate:
                    raise TransactionIdempotencyConflictError(
                        "receipt_conflict",
                        "Receipt ID is already bound to another result.",
                    )
                # A prior finalize may have written the immutable receipt and
                # crashed before advancing the idempotency record. Adopt that
                # hash-verified receipt, including its original timestamp.
                receipt = known_receipt
                candidate = IdempotencyRecord(
                    "finalized",
                    prepared,
                    receipt,
                )
            if known_receipt is None:
                self._atomic_write(
                    self._receipt_path(receipt.receipt_id),
                    canonical_json_bytes(receipt.to_dict()),
                )
            self._atomic_write(
                self._idempotency_path(prepared.idempotency_key),
                canonical_json_bytes(candidate.to_dict()),
            )
            return deepcopy(candidate)

    def get_receipt(self, receipt_id: str) -> TransactionReceipt:
        receipt_id = validate_token(receipt_id, "receiptId")
        with self._lock:
            receipt = self._load_receipt(receipt_id)
            if receipt is None:
                raise TransactionNotFoundError(
                    "receipt_not_found",
                    "Transaction receipt was not found.",
                )
            return deepcopy(receipt)
