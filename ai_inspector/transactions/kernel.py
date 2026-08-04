"""Domain-neutral proposal, approval, and atomic-commit orchestration."""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from copy import deepcopy
from typing import Any, Callable, Optional

from .stores import (
    InMemoryReceiptStore,
    ReceiptStore,
    VolatileTransactionStore,
    canonical_json_bytes,
)
from .types import (
    MAX_OPAQUE_PAYLOAD_BYTES,
    ApplyOutcome,
    ApplyRequest,
    ApprovalRecord,
    ApprovalRequest,
    CommitResult,
    ExactBinding,
    MutationPlan,
    PreparedRecord,
    PrincipalBinding,
    ProposalRecord,
    ProposalRequest,
    ReconciliationResult,
    ReconciliationState,
    TransactionAdapter,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionCancelledError,
    TransactionExpiredError,
    TransactionIdempotencyConflictError,
    TransactionNotFoundError,
    TransactionPreparedError,
    TransactionReceipt,
    TransactionReplayError,
    TransactionValidationError,
    validate_timestamp,
    validate_token,
)


Clock = Callable[[], float]
TokenFactory = Callable[[str], str]
MAX_LIFETIME_SECONDS = 24 * 60 * 60


def default_token_factory(prefix: str) -> str:
    """Create an opaque bounded token suitable for public APIs."""

    return f"{prefix}-{secrets.token_urlsafe(24)}"


def _validate_lifetime(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransactionValidationError(
            "invalid_transaction_lifetime",
            f"{field_name} must be a finite number of seconds.",
        )
    seconds = float(value)
    if (
        not math.isfinite(seconds)
        or seconds <= 0
        or seconds > MAX_LIFETIME_SECONDS
    ):
        raise TransactionValidationError(
            "invalid_transaction_lifetime",
            (
                f"{field_name} must be greater than zero and no more than "
                f"{MAX_LIFETIME_SECONDS} seconds."
            ),
        )
    return seconds


class TransactionKernel:
    """Coordinate exact, approval-bound mutations through a domain adapter."""

    def __init__(
        self,
        *,
        state_store: Optional[VolatileTransactionStore] = None,
        receipt_store: Optional[ReceiptStore] = None,
        clock: Clock = time.time,
        token_factory: TokenFactory = default_token_factory,
        proposal_lifetime_seconds: float = 15 * 60,
        approval_lifetime_seconds: float = 5 * 60,
    ) -> None:
        if not callable(clock):
            raise TransactionValidationError(
                "invalid_transaction_clock",
                "clock must be callable.",
            )
        if not callable(token_factory):
            raise TransactionValidationError(
                "invalid_token_factory",
                "tokenFactory must be callable.",
            )
        self._state = (
            state_store
            if state_store is not None
            else VolatileTransactionStore()
        )
        self._receipts: ReceiptStore = (
            receipt_store
            if receipt_store is not None
            else InMemoryReceiptStore()
        )
        self._clock = clock
        self._token_factory = token_factory
        self._proposal_lifetime = _validate_lifetime(
            proposal_lifetime_seconds,
            "proposalLifetimeSeconds",
        )
        self._approval_lifetime = _validate_lifetime(
            approval_lifetime_seconds,
            "approvalLifetimeSeconds",
        )

    @property
    def state_store(self) -> VolatileTransactionStore:
        return self._state

    @property
    def receipt_store(self) -> ReceiptStore:
        return self._receipts

    def _now(self) -> float:
        try:
            value = self._clock()
        except Exception as exc:
            raise TransactionValidationError(
                "transaction_clock_failed",
                "Transaction clock failed.",
            ) from exc
        return validate_timestamp(value, "clock")

    def _new_token(self, prefix: str, field_name: str) -> str:
        try:
            token = self._token_factory(prefix)
        except Exception as exc:
            raise TransactionValidationError(
                "token_factory_failed",
                "Transaction token factory failed.",
            ) from exc
        return validate_token(token, field_name)

    @staticmethod
    def request_fingerprint(
        binding: ExactBinding,
        principal: PrincipalBinding,
        idempotency_key: str,
    ) -> str:
        """Hash every stable field that authorizes a semantic apply request."""

        data = {
            "binding": binding.to_dict(),
            "principal": principal.to_dict(),
            "idempotencyKey": idempotency_key,
        }
        return hashlib.sha256(canonical_json_bytes(data)).hexdigest()

    @staticmethod
    def _assert_binding(actual: ExactBinding, expected: ExactBinding) -> None:
        if actual != expected:
            raise TransactionBindingError(
                "transaction_binding_mismatch",
                (
                    "Target, base revision, diff hash, or dependency "
                    "fingerprint does not match the proposal."
                ),
            )

    @staticmethod
    def _assert_principal(
        actual: PrincipalBinding,
        expected: PrincipalBinding,
    ) -> None:
        if actual != expected:
            raise TransactionAuthorizationError(
                "transaction_principal_mismatch",
                "Transaction principal or session does not match.",
            )

    def _active_proposal(
        self,
        proposal_id: str,
        *,
        now: float,
    ) -> ProposalRecord:
        proposal = self._state.get_proposal(proposal_id)
        if proposal is None:
            raise TransactionNotFoundError(
                "proposal_not_found",
                "Proposal was not found or the service restarted.",
            )
        if proposal.status == "cancelled":
            raise TransactionCancelledError(
                "proposal_cancelled",
                "Proposal has been cancelled.",
            )
        if proposal.expires_at <= now:
            raise TransactionExpiredError(
                "proposal_expired",
                "Proposal has expired.",
            )
        return proposal

    def _active_approval(
        self,
        approval_token: str,
        *,
        now: float,
    ) -> ApprovalRecord:
        approval = self._state.get_approval(approval_token)
        if approval is None:
            raise TransactionNotFoundError(
                "approval_not_found",
                "Approval was not found or the service restarted.",
            )
        if approval.status == "cancelled":
            raise TransactionCancelledError(
                "approval_cancelled",
                "Approval has been cancelled.",
            )
        if approval.expires_at <= now:
            raise TransactionExpiredError(
                "approval_expired",
                "Approval has expired.",
            )
        return approval

    def propose(self, request: ProposalRequest) -> ProposalRecord:
        if not isinstance(request, ProposalRequest):
            raise TransactionValidationError(
                "invalid_proposal_request",
                "request must be a ProposalRequest.",
            )
        opaque = canonical_json_bytes(
            {
                "payload": request.payload,
                "publicSummary": request.public_summary,
            }
        )
        if len(opaque) > MAX_OPAQUE_PAYLOAD_BYTES:
            raise TransactionValidationError(
                "transaction_payload_too_large",
                "Proposal payload exceeds the transaction size limit.",
            )
        now = self._now()
        proposal = ProposalRecord(
            proposal_id=self._new_token("txp", "proposalId"),
            action=request.action,
            binding=request.binding,
            principal=request.principal,
            payload=deepcopy(dict(request.payload)),
            public_summary=deepcopy(dict(request.public_summary)),
            created_at=now,
            expires_at=now + self._proposal_lifetime,
            principal_claimable=request.principal_claimable,
        )
        self._state.put_proposal(proposal, now=now)
        return proposal

    def get_proposal(
        self,
        proposal_id: str,
        *,
        principal: Optional[PrincipalBinding] = None,
    ) -> ProposalRecord:
        proposal = self._active_proposal(proposal_id, now=self._now())
        if principal is not None:
            if not isinstance(principal, PrincipalBinding):
                raise TransactionValidationError(
                    "invalid_transaction_principal",
                    "principal must be a PrincipalBinding.",
                )
            if proposal.principal is not None:
                self._assert_principal(principal, proposal.principal)
        return proposal

    def cancel_proposal(
        self,
        proposal_id: str,
        *,
        principal: PrincipalBinding,
    ) -> ProposalRecord:
        if not isinstance(principal, PrincipalBinding):
            raise TransactionValidationError(
                "invalid_transaction_principal",
                "principal must be a PrincipalBinding.",
            )
        proposal = self._state.get_proposal(proposal_id)
        if proposal is None:
            raise TransactionNotFoundError(
                "proposal_not_found",
                "Proposal was not found or the service restarted.",
            )
        if proposal.principal is not None:
            self._assert_principal(principal, proposal.principal)
        elif not proposal.principal_claimable:
            raise TransactionAuthorizationError(
                "transaction_principal_mismatch",
                "Transaction proposal has no claimable principal.",
            )
        if proposal.status == "cancelled":
            return proposal
        if proposal.expires_at <= self._now():
            raise TransactionExpiredError(
                "proposal_expired",
                "Proposal has expired.",
            )
        return self._state.cancel_proposal(proposal_id)

    cancel = cancel_proposal

    def approve(self, request: ApprovalRequest) -> ApprovalRecord:
        if not isinstance(request, ApprovalRequest):
            raise TransactionValidationError(
                "invalid_approval_request",
                "request must be an ApprovalRequest.",
            )
        if not request.explicit_approval:
            raise TransactionAuthorizationError(
                "explicit_approval_required",
                "An explicit user approval is required.",
            )
        now = self._now()
        proposal = self._active_proposal(request.proposal_id, now=now)
        self._assert_binding(request.binding, proposal.binding)
        if proposal.principal is not None:
            self._assert_principal(request.principal, proposal.principal)
        elif not proposal.principal_claimable:
            raise TransactionAuthorizationError(
                "transaction_principal_mismatch",
                "Transaction proposal has no claimable principal.",
            )
        fingerprint = self.request_fingerprint(
            request.binding,
            request.principal,
            request.idempotency_key,
        )

        persisted = self._receipts.lookup(
            request.idempotency_key,
            fingerprint,
        )
        if persisted is not None:
            if persisted.state == "prepared":
                raise TransactionPreparedError(
                    "transaction_already_prepared",
                    "This exact request already has a prepared transaction.",
                )
            raise TransactionReplayError(
                "idempotency_replay",
                "This exact request has already been finalized.",
            )

        prior = self._state.find_approval_by_idempotency_key(
            request.idempotency_key
        )
        if prior is not None:
            if prior.request_fingerprint != fingerprint:
                raise TransactionIdempotencyConflictError(
                    "idempotency_key_conflict",
                    "The idempotency key is bound to another approval.",
                )
            raise TransactionReplayError(
                "approval_replay",
                "This exact request has already been approved.",
            )

        expires_at = min(
            proposal.expires_at,
            now + self._approval_lifetime,
        )
        if expires_at <= now:
            raise TransactionExpiredError(
                "proposal_expired",
                "Proposal expired before approval could be issued.",
            )
        approval = ApprovalRecord(
            approval_token=self._new_token("txa", "approvalToken"),
            proposal_id=proposal.proposal_id,
            action=proposal.action,
            binding=proposal.binding,
            principal=request.principal,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            created_at=now,
            expires_at=expires_at,
        )
        self._state.put_approval(approval, now=now)
        return approval

    @staticmethod
    def _assert_adapter(value: Any) -> TransactionAdapter:
        for method_name in ("regenerate", "commit", "reconcile_prepared"):
            if not callable(getattr(value, method_name, None)):
                raise TransactionValidationError(
                    "invalid_transaction_adapter",
                    f"Transaction adapter is missing {method_name}().",
                )
        return value

    @staticmethod
    def _receipt_from_commit(
        prepared: PreparedRecord,
        result: CommitResult,
        *,
        created_at: float,
    ) -> TransactionReceipt:
        if not isinstance(result, CommitResult):
            raise TransactionValidationError(
                "invalid_commit_result",
                "Domain adapter commit result is invalid.",
            )
        return TransactionReceipt(
            receipt_id=prepared.receipt_id,
            proposal_id=prepared.proposal_id,
            action=prepared.action,
            binding=prepared.binding,
            principal=prepared.principal,
            idempotency_key=prepared.idempotency_key,
            request_fingerprint=prepared.request_fingerprint,
            revision=result.revision,
            created_at=created_at,
            payload=result.payload,
            approval_fingerprint=prepared.approval_fingerprint,
        )

    @staticmethod
    def _approval_fingerprint(approval: ApprovalRecord) -> str:
        return hashlib.sha256(
            canonical_json_bytes(approval.public_dict())
        ).hexdigest()

    def _resolve_existing(
        self,
        existing: Any,
        *,
        adapter: TransactionAdapter,
        now: float,
    ) -> Optional[ApplyOutcome]:
        if existing is None:
            return None
        if existing.state == "finalized":
            if not self._receipts.recover_exact_retries:
                raise TransactionReplayError(
                    "idempotency_replay",
                    "This exact request has already been finalized.",
                )
            return ApplyOutcome(
                receipt=deepcopy(existing.receipt),
                replayed=True,
                recovered=True,
            )

        reconciliation = adapter.reconcile_prepared(existing.prepared)
        if not isinstance(reconciliation, ReconciliationResult):
            raise TransactionValidationError(
                "invalid_reconciliation_result",
                "Domain adapter reconciliation result is invalid.",
            )
        if reconciliation.state is ReconciliationState.UNKNOWN:
            raise TransactionPreparedError(
                "prepared_transaction_pending",
                (
                    "Prepared transaction outcome is unknown; no retry was "
                    "attempted."
                ),
            )
        if reconciliation.state is ReconciliationState.COMMITTED:
            receipt = self._receipt_from_commit(
                existing.prepared,
                reconciliation.commit_result,
                created_at=now,
            )
            finalized = self._receipts.finalize(
                existing.prepared,
                receipt,
            )
            return ApplyOutcome(
                receipt=deepcopy(finalized.receipt),
                replayed=True,
                recovered=True,
            )
        return None

    def apply(
        self,
        request: ApplyRequest,
        adapter: TransactionAdapter,
    ) -> ApplyOutcome:
        if not isinstance(request, ApplyRequest):
            raise TransactionValidationError(
                "invalid_apply_request",
                "request must be an ApplyRequest.",
            )
        adapter = self._assert_adapter(adapter)
        now = self._now()
        fingerprint = self.request_fingerprint(
            request.binding,
            request.principal,
            request.idempotency_key,
        )
        existing = self._receipts.lookup(
            request.idempotency_key,
            fingerprint,
        )
        resolved = self._resolve_existing(
            existing,
            adapter=adapter,
            now=now,
        )
        if resolved is not None:
            return resolved

        approval = self._active_approval(
            request.approval_token,
            now=now,
        )
        approval_fingerprint = self._approval_fingerprint(approval)
        self._assert_binding(request.binding, approval.binding)
        self._assert_principal(request.principal, approval.principal)
        if request.idempotency_key != approval.idempotency_key:
            raise TransactionIdempotencyConflictError(
                "idempotency_key_conflict",
                "Apply request idempotency key does not match approval.",
            )
        if fingerprint != approval.request_fingerprint:
            raise TransactionBindingError(
                "transaction_request_mismatch",
                "Apply request no longer matches the approved request.",
            )
        proposal = self._active_proposal(approval.proposal_id, now=now)
        self._assert_binding(approval.binding, proposal.binding)
        if proposal.principal is not None:
            self._assert_principal(approval.principal, proposal.principal)
        elif not proposal.principal_claimable:
            raise TransactionAuthorizationError(
                "transaction_principal_mismatch",
                "Transaction proposal has no claimable principal.",
            )

        plan = adapter.regenerate(proposal)
        if not isinstance(plan, MutationPlan):
            raise TransactionValidationError(
                "invalid_mutation_plan",
                "Domain adapter returned an invalid mutation plan.",
            )
        self._assert_binding(plan.binding, approval.binding)

        if existing is None:
            prepared = PreparedRecord(
                receipt_id=self._new_token("txr", "receiptId"),
                proposal_id=proposal.proposal_id,
                action=proposal.action,
                binding=proposal.binding,
                principal=approval.principal,
                idempotency_key=approval.idempotency_key,
                request_fingerprint=approval.request_fingerprint,
                prepared_at=now,
                recovery=plan.recovery,
                approval_fingerprint=approval_fingerprint,
            )
            stored = self._receipts.prepare(prepared)
            if stored.state == "finalized":
                if self._receipts.recover_exact_retries:
                    return ApplyOutcome(
                        receipt=deepcopy(stored.receipt),
                        replayed=True,
                        recovered=True,
                    )
                raise TransactionReplayError(
                    "idempotency_replay",
                    "This exact request has already been finalized.",
                )
            prepared = stored.prepared
        else:
            prepared = existing.prepared
            if (
                prepared.proposal_id != proposal.proposal_id
                or prepared.action != proposal.action
                or prepared.binding != proposal.binding
                or prepared.principal != approval.principal
                or prepared.approval_fingerprint
                != approval_fingerprint
            ):
                raise TransactionIdempotencyConflictError(
                    "prepared_transaction_conflict",
                    "Prepared transaction does not match active approval.",
                )

        result = adapter.commit(plan)
        receipt = self._receipt_from_commit(
            prepared,
            result,
            created_at=self._now(),
        )
        finalized = self._receipts.finalize(prepared, receipt)
        self._state.consume(
            proposal.proposal_id,
            approval.approval_token,
        )
        return ApplyOutcome(receipt=deepcopy(finalized.receipt))

    def get_receipt(self, receipt_id: str) -> TransactionReceipt:
        validate_token(receipt_id, "receiptId")
        return self._receipts.get_receipt(receipt_id)
