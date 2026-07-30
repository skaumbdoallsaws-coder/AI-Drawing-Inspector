"""Domain-neutral transaction types and validation.

The transaction kernel binds an exact proposed mutation to a target, base
revision, dependency fingerprint, principal, and session. Domain adapters own
document semantics, validation, regeneration, and persistence.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Protocol


MAX_IDENTIFIER_LENGTH = 128
MAX_ACTION_LENGTH = 64
MAX_TOKEN_LENGTH = 256
MAX_OPAQUE_PAYLOAD_BYTES = 2 * 1024 * 1024

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,63}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~:-]{7,255}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class TransactionError(RuntimeError):
    """Base error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TransactionValidationError(TransactionError):
    pass


class TransactionNotFoundError(TransactionError):
    pass


class TransactionExpiredError(TransactionError):
    pass


class TransactionCancelledError(TransactionError):
    pass


class TransactionBindingError(TransactionError):
    pass


class TransactionAuthorizationError(TransactionError):
    pass


class TransactionReplayError(TransactionError):
    pass


class TransactionIdempotencyConflictError(TransactionError):
    pass


class TransactionPreparedError(TransactionError):
    pass


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TransactionValidationError(
            "invalid_transaction_field",
            f"{field_name} must be a string.",
        )
    return value


def validate_identifier(value: Any, field_name: str) -> str:
    cleaned = _require_string(value, field_name).strip()
    if (
        not cleaned
        or len(cleaned) > MAX_IDENTIFIER_LENGTH
        or cleaned in {".", ".."}
        or _IDENTIFIER_RE.fullmatch(cleaned) is None
    ):
        raise TransactionValidationError(
            "invalid_transaction_identifier",
            (
                f"{field_name} must be a path-free identifier containing at "
                f"most {MAX_IDENTIFIER_LENGTH} characters."
            ),
        )
    return cleaned


def validate_action(value: Any) -> str:
    cleaned = _require_string(value, "action").strip()
    if len(cleaned) > MAX_ACTION_LENGTH or _ACTION_RE.fullmatch(cleaned) is None:
        raise TransactionValidationError(
            "invalid_transaction_action",
            "action must be a lowercase domain action identifier.",
        )
    return cleaned


def validate_token(value: Any, field_name: str) -> str:
    cleaned = _require_string(value, field_name).strip()
    if len(cleaned) > MAX_TOKEN_LENGTH or _TOKEN_RE.fullmatch(cleaned) is None:
        raise TransactionValidationError(
            "invalid_transaction_token",
            f"{field_name} is malformed.",
        )
    return cleaned


def validate_idempotency_key(value: Any) -> str:
    cleaned = _require_string(value, "idempotencyKey").strip()
    if _IDEMPOTENCY_RE.fullmatch(cleaned) is None:
        raise TransactionValidationError(
            "invalid_idempotency_key",
            "idempotencyKey must contain between 8 and 128 safe characters.",
        )
    return cleaned


def validate_hash(value: Any, field_name: str) -> str:
    cleaned = _require_string(value, field_name).strip()
    if _HASH_RE.fullmatch(cleaned) is None:
        raise TransactionValidationError(
            "invalid_transaction_hash",
            f"{field_name} must be a lowercase 64-character SHA-256 hash.",
        )
    return cleaned


def validate_timestamp(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransactionValidationError(
            "invalid_transaction_timestamp",
            f"{field_name} must be a finite non-negative number.",
        )
    converted = float(value)
    if not math.isfinite(converted) or converted < 0:
        raise TransactionValidationError(
            "invalid_transaction_timestamp",
            f"{field_name} must be a finite non-negative number.",
        )
    return converted


def copy_mapping(value: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TransactionValidationError(
            "invalid_transaction_payload",
            f"{field_name} must be an object.",
        )
    return deepcopy(dict(value))


@dataclass(frozen=True)
class TransactionTarget:
    """Stable domain target without filesystem semantics."""

    domain: str
    scope_id: str
    resource_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain", validate_identifier(self.domain, "domain"))
        object.__setattr__(
            self,
            "scope_id",
            validate_identifier(self.scope_id, "scopeId"),
        )
        object.__setattr__(
            self,
            "resource_id",
            validate_identifier(self.resource_id, "resourceId"),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "domain": self.domain,
            "scopeId": self.scope_id,
            "resourceId": self.resource_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionTarget":
        return cls(
            domain=value.get("domain"),
            scope_id=value.get("scopeId"),
            resource_id=value.get("resourceId"),
        )


@dataclass(frozen=True)
class PrincipalBinding:
    principal_id: str
    session_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            validate_identifier(self.principal_id, "principalId"),
        )
        object.__setattr__(
            self,
            "session_id",
            validate_identifier(self.session_id, "sessionId"),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "principalId": self.principal_id,
            "sessionId": self.session_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PrincipalBinding":
        return cls(
            principal_id=value.get("principalId"),
            session_id=value.get("sessionId"),
        )


@dataclass(frozen=True)
class ExactBinding:
    target: TransactionTarget
    base_revision: str
    diff_hash: str
    dependency_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, TransactionTarget):
            raise TransactionValidationError(
                "invalid_transaction_target",
                "target must be a TransactionTarget.",
            )
        object.__setattr__(
            self,
            "base_revision",
            validate_hash(self.base_revision, "baseRevision"),
        )
        object.__setattr__(
            self,
            "diff_hash",
            validate_hash(self.diff_hash, "diffHash"),
        )
        object.__setattr__(
            self,
            "dependency_fingerprint",
            validate_hash(
                self.dependency_fingerprint,
                "dependencyFingerprint",
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target.to_dict(),
            "baseRevision": self.base_revision,
            "diffHash": self.diff_hash,
            "dependencyFingerprint": self.dependency_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactBinding":
        target = value.get("target")
        if not isinstance(target, Mapping):
            raise TransactionValidationError(
                "invalid_transaction_target",
                "binding.target must be an object.",
            )
        return cls(
            target=TransactionTarget.from_dict(target),
            base_revision=value.get("baseRevision"),
            diff_hash=value.get("diffHash"),
            dependency_fingerprint=value.get("dependencyFingerprint"),
        )


@dataclass(frozen=True)
class ProposalRequest:
    action: str
    binding: ExactBinding
    principal: Optional[PrincipalBinding]
    payload: Mapping[str, Any] = field(default_factory=dict)
    public_summary: Mapping[str, Any] = field(default_factory=dict)
    principal_claimable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", validate_action(self.action))
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "binding must be an ExactBinding.",
            )
        if self.principal is not None and not isinstance(
            self.principal,
            PrincipalBinding,
        ):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principal must be a PrincipalBinding or null.",
            )
        if not isinstance(self.principal_claimable, bool):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principalClaimable must be a boolean.",
            )
        if self.principal is None and not self.principal_claimable:
            raise TransactionValidationError(
                "transaction_principal_required",
                "A proposal principal is required.",
            )
        if self.principal is not None and self.principal_claimable:
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "A principal-bound proposal cannot also be claimable.",
            )
        object.__setattr__(
            self,
            "payload",
            copy_mapping(self.payload, "payload"),
        )
        object.__setattr__(
            self,
            "public_summary",
            copy_mapping(self.public_summary, "publicSummary"),
        )


@dataclass(frozen=True)
class ProposalRecord:
    proposal_id: str
    action: str
    binding: ExactBinding
    principal: Optional[PrincipalBinding]
    payload: Mapping[str, Any]
    public_summary: Mapping[str, Any]
    created_at: float
    expires_at: float
    status: str = "active"
    principal_claimable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proposal_id",
            validate_token(self.proposal_id, "proposalId"),
        )
        object.__setattr__(self, "action", validate_action(self.action))
        if self.principal is not None and not isinstance(
            self.principal,
            PrincipalBinding,
        ):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principal must be a PrincipalBinding or null.",
            )
        if not isinstance(self.principal_claimable, bool):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principalClaimable must be a boolean.",
            )
        if self.principal is None and not self.principal_claimable:
            raise TransactionValidationError(
                "transaction_principal_required",
                "A proposal principal is required.",
            )
        if self.principal is not None and self.principal_claimable:
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "A principal-bound proposal cannot also be claimable.",
            )
        object.__setattr__(
            self,
            "payload",
            copy_mapping(self.payload, "payload"),
        )
        object.__setattr__(
            self,
            "public_summary",
            copy_mapping(self.public_summary, "publicSummary"),
        )
        object.__setattr__(
            self,
            "created_at",
            validate_timestamp(self.created_at, "createdAt"),
        )
        object.__setattr__(
            self,
            "expires_at",
            validate_timestamp(self.expires_at, "expiresAt"),
        )
        if self.expires_at <= self.created_at:
            raise TransactionValidationError(
                "invalid_transaction_lifetime",
                "Proposal expiry must be after creation.",
            )
        if self.status not in {"active", "cancelled"}:
            raise TransactionValidationError(
                "invalid_transaction_status",
                "Proposal status is invalid.",
            )

    def public_dict(self) -> Dict[str, Any]:
        return {
            "proposalId": self.proposal_id,
            "action": self.action,
            **self.binding.to_dict(),
            "principal": (
                self.principal.to_dict()
                if self.principal is not None
                else None
            ),
            "principalClaimable": self.principal_claimable,
            "summary": deepcopy(dict(self.public_summary)),
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class ApprovalRequest:
    proposal_id: str
    binding: ExactBinding
    principal: PrincipalBinding
    idempotency_key: str
    explicit_approval: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proposal_id",
            validate_token(self.proposal_id, "proposalId"),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            validate_idempotency_key(self.idempotency_key),
        )
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "binding must be an ExactBinding.",
            )
        if not isinstance(self.principal, PrincipalBinding):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principal must be a PrincipalBinding.",
            )
        if not isinstance(self.explicit_approval, bool):
            raise TransactionValidationError(
                "invalid_explicit_approval",
                "explicitApproval must be a boolean.",
            )


@dataclass(frozen=True)
class ApprovalRecord:
    approval_token: str
    proposal_id: str
    action: str
    binding: ExactBinding
    principal: PrincipalBinding
    idempotency_key: str
    request_fingerprint: str
    created_at: float
    expires_at: float
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_token",
            validate_token(self.approval_token, "approvalToken"),
        )
        object.__setattr__(
            self,
            "proposal_id",
            validate_token(self.proposal_id, "proposalId"),
        )
        object.__setattr__(self, "action", validate_action(self.action))
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "binding must be an ExactBinding.",
            )
        if not isinstance(self.principal, PrincipalBinding):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principal must be a PrincipalBinding.",
            )
        object.__setattr__(
            self,
            "idempotency_key",
            validate_idempotency_key(self.idempotency_key),
        )
        object.__setattr__(
            self,
            "request_fingerprint",
            validate_hash(self.request_fingerprint, "requestFingerprint"),
        )
        object.__setattr__(
            self,
            "created_at",
            validate_timestamp(self.created_at, "createdAt"),
        )
        object.__setattr__(
            self,
            "expires_at",
            validate_timestamp(self.expires_at, "expiresAt"),
        )
        if self.expires_at <= self.created_at:
            raise TransactionValidationError(
                "invalid_transaction_lifetime",
                "Approval expiry must be after creation.",
            )
        if self.status not in {"active", "cancelled"}:
            raise TransactionValidationError(
                "invalid_transaction_status",
                "Approval status is invalid.",
            )

    def public_dict(self) -> Dict[str, Any]:
        return {
            "approvalToken": self.approval_token,
            "proposalId": self.proposal_id,
            "action": self.action,
            **self.binding.to_dict(),
            "principal": self.principal.to_dict(),
            "idempotencyKey": self.idempotency_key,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class ApplyRequest:
    approval_token: str
    binding: ExactBinding
    principal: PrincipalBinding
    idempotency_key: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "approval_token",
            validate_token(self.approval_token, "approvalToken"),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            validate_idempotency_key(self.idempotency_key),
        )
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "binding must be an ExactBinding.",
            )
        if not isinstance(self.principal, PrincipalBinding):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principal must be a PrincipalBinding.",
            )


@dataclass(frozen=True)
class MutationPlan:
    binding: ExactBinding
    payload: Mapping[str, Any] = field(default_factory=dict)
    recovery: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "Mutation plan binding must be exact.",
            )
        object.__setattr__(
            self,
            "payload",
            copy_mapping(self.payload, "mutationPayload"),
        )
        object.__setattr__(
            self,
            "recovery",
            copy_mapping(self.recovery, "mutationRecovery"),
        )


@dataclass(frozen=True)
class CommitResult:
    revision: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "revision",
            validate_hash(self.revision, "revision"),
        )
        object.__setattr__(
            self,
            "payload",
            copy_mapping(self.payload, "commitPayload"),
        )


@dataclass(frozen=True)
class PreparedRecord:
    receipt_id: str
    proposal_id: str
    action: str
    binding: ExactBinding
    principal: PrincipalBinding
    idempotency_key: str
    request_fingerprint: str
    prepared_at: float
    recovery: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            validate_token(self.receipt_id, "receiptId"),
        )
        object.__setattr__(
            self,
            "proposal_id",
            validate_token(self.proposal_id, "proposalId"),
        )
        object.__setattr__(self, "action", validate_action(self.action))
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "Prepared transaction binding must be exact.",
            )
        if not isinstance(self.principal, PrincipalBinding):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "Prepared transaction principal is invalid.",
            )
        object.__setattr__(
            self,
            "idempotency_key",
            validate_idempotency_key(self.idempotency_key),
        )
        object.__setattr__(
            self,
            "request_fingerprint",
            validate_hash(self.request_fingerprint, "requestFingerprint"),
        )
        object.__setattr__(
            self,
            "prepared_at",
            validate_timestamp(self.prepared_at, "preparedAt"),
        )
        object.__setattr__(
            self,
            "recovery",
            copy_mapping(self.recovery, "preparedRecovery"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "receiptId": self.receipt_id,
            "proposalId": self.proposal_id,
            "action": self.action,
            "binding": self.binding.to_dict(),
            "principal": self.principal.to_dict(),
            "idempotencyKey": self.idempotency_key,
            "requestFingerprint": self.request_fingerprint,
            "preparedAt": self.prepared_at,
        }
        if self.recovery:
            result["recovery"] = deepcopy(dict(self.recovery))
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreparedRecord":
        binding = value.get("binding")
        principal = value.get("principal")
        if not isinstance(binding, Mapping) or not isinstance(principal, Mapping):
            raise TransactionValidationError(
                "invalid_prepared_record",
                "Prepared transaction binding and principal are required.",
            )
        return cls(
            receipt_id=value.get("receiptId"),
            proposal_id=value.get("proposalId"),
            action=value.get("action"),
            binding=ExactBinding.from_dict(binding),
            principal=PrincipalBinding.from_dict(principal),
            idempotency_key=value.get("idempotencyKey"),
            request_fingerprint=value.get("requestFingerprint"),
            prepared_at=value.get("preparedAt"),
            recovery=value.get("recovery") or {},
        )


@dataclass(frozen=True)
class TransactionReceipt:
    receipt_id: str
    proposal_id: str
    action: str
    binding: ExactBinding
    principal: PrincipalBinding
    idempotency_key: str
    request_fingerprint: str
    revision: str
    created_at: float
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            validate_token(self.receipt_id, "receiptId"),
        )
        object.__setattr__(
            self,
            "proposal_id",
            validate_token(self.proposal_id, "proposalId"),
        )
        object.__setattr__(self, "action", validate_action(self.action))
        if not isinstance(self.binding, ExactBinding):
            raise TransactionValidationError(
                "invalid_transaction_binding",
                "Receipt binding must be exact.",
            )
        if not isinstance(self.principal, PrincipalBinding):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "Receipt principal is invalid.",
            )
        object.__setattr__(
            self,
            "idempotency_key",
            validate_idempotency_key(self.idempotency_key),
        )
        object.__setattr__(
            self,
            "request_fingerprint",
            validate_hash(self.request_fingerprint, "requestFingerprint"),
        )
        object.__setattr__(
            self,
            "revision",
            validate_hash(self.revision, "revision"),
        )
        object.__setattr__(
            self,
            "created_at",
            validate_timestamp(self.created_at, "createdAt"),
        )
        object.__setattr__(
            self,
            "payload",
            copy_mapping(self.payload, "receiptPayload"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "receiptId": self.receipt_id,
            "proposalId": self.proposal_id,
            "action": self.action,
            "binding": self.binding.to_dict(),
            "principal": self.principal.to_dict(),
            "idempotencyKey": self.idempotency_key,
            "requestFingerprint": self.request_fingerprint,
            "revision": self.revision,
            "createdAt": self.created_at,
            "payload": deepcopy(dict(self.payload)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransactionReceipt":
        binding = value.get("binding")
        principal = value.get("principal")
        if not isinstance(binding, Mapping) or not isinstance(principal, Mapping):
            raise TransactionValidationError(
                "invalid_transaction_receipt",
                "Receipt binding and principal are required.",
            )
        return cls(
            receipt_id=value.get("receiptId"),
            proposal_id=value.get("proposalId"),
            action=value.get("action"),
            binding=ExactBinding.from_dict(binding),
            principal=PrincipalBinding.from_dict(principal),
            idempotency_key=value.get("idempotencyKey"),
            request_fingerprint=value.get("requestFingerprint"),
            revision=value.get("revision"),
            created_at=value.get("createdAt"),
            payload=value.get("payload") or {},
        )


@dataclass(frozen=True)
class IdempotencyRecord:
    state: str
    prepared: PreparedRecord
    receipt: Optional[TransactionReceipt] = None

    def __post_init__(self) -> None:
        if not isinstance(self.prepared, PreparedRecord):
            raise TransactionValidationError(
                "invalid_idempotency_state",
                "Idempotency state requires a prepared record.",
            )
        if self.state not in {"prepared", "finalized"}:
            raise TransactionValidationError(
                "invalid_idempotency_state",
                "Idempotency state must be prepared or finalized.",
            )
        if self.state == "prepared" and self.receipt is not None:
            raise TransactionValidationError(
                "invalid_idempotency_state",
                "A prepared record cannot contain a receipt.",
            )
        if self.state == "finalized" and self.receipt is None:
            raise TransactionValidationError(
                "invalid_idempotency_state",
                "A finalized record requires a receipt.",
            )
        if self.receipt is not None:
            if not isinstance(self.receipt, TransactionReceipt):
                raise TransactionValidationError(
                    "invalid_idempotency_state",
                    "Finalized receipt is invalid.",
                )
            prepared_identity = (
                self.prepared.receipt_id,
                self.prepared.proposal_id,
                self.prepared.action,
                self.prepared.binding,
                self.prepared.principal,
                self.prepared.idempotency_key,
                self.prepared.request_fingerprint,
            )
            receipt_identity = (
                self.receipt.receipt_id,
                self.receipt.proposal_id,
                self.receipt.action,
                self.receipt.binding,
                self.receipt.principal,
                self.receipt.idempotency_key,
                self.receipt.request_fingerprint,
            )
            if prepared_identity != receipt_identity:
                raise TransactionValidationError(
                    "invalid_idempotency_state",
                    "Finalized receipt does not match its prepared record.",
                )

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "schemaVersion": 1,
            "state": self.state,
            "prepared": self.prepared.to_dict(),
        }
        if self.receipt is not None:
            result["receipt"] = self.receipt.to_dict()
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdempotencyRecord":
        if value.get("schemaVersion") != 1:
            raise TransactionValidationError(
                "unsupported_idempotency_record",
                "Unsupported idempotency record schema.",
            )
        prepared = value.get("prepared")
        receipt = value.get("receipt")
        if not isinstance(prepared, Mapping):
            raise TransactionValidationError(
                "invalid_idempotency_record",
                "Idempotency record is missing prepared state.",
            )
        return cls(
            state=value.get("state"),
            prepared=PreparedRecord.from_dict(prepared),
            receipt=(
                TransactionReceipt.from_dict(receipt)
                if isinstance(receipt, Mapping)
                else None
            ),
        )


class ReconciliationState(str, Enum):
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReconciliationResult:
    state: ReconciliationState
    commit_result: Optional[CommitResult] = None

    def __post_init__(self) -> None:
        if self.state is ReconciliationState.COMMITTED and self.commit_result is None:
            raise TransactionValidationError(
                "invalid_reconciliation_result",
                "Committed reconciliation requires a commit result.",
            )
        if self.state is not ReconciliationState.COMMITTED and self.commit_result is not None:
            raise TransactionValidationError(
                "invalid_reconciliation_result",
                "Only committed reconciliation may include a commit result.",
            )

    @classmethod
    def committed(cls, result: CommitResult) -> "ReconciliationResult":
        return cls(ReconciliationState.COMMITTED, result)

    @classmethod
    def not_committed(cls) -> "ReconciliationResult":
        return cls(ReconciliationState.NOT_COMMITTED)

    @classmethod
    def unknown(cls) -> "ReconciliationResult":
        return cls(ReconciliationState.UNKNOWN)


@dataclass(frozen=True)
class ApplyOutcome:
    receipt: TransactionReceipt
    replayed: bool = False
    recovered: bool = False


class TransactionAdapter(Protocol):
    """Domain boundary used by :class:`TransactionKernel`."""

    def regenerate(self, proposal: ProposalRecord) -> MutationPlan:
        """Regenerate the exact proposed mutation against current dependencies."""

    def commit(self, plan: MutationPlan) -> CommitResult:
        """Apply one validated mutation atomically through the domain repository."""

    def reconcile_prepared(self, prepared: PreparedRecord) -> ReconciliationResult:
        """Resolve an interrupted prepared record without guessing."""
