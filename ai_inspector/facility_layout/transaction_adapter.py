"""Facility Layout adapter surface for the shared transaction kernel."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Mapping

from ai_inspector.transactions import (
    ApplyOutcome,
    ApplyRequest,
    ApprovalRecord,
    ApprovalRequest,
    ExactBinding,
    InMemoryReceiptStore,
    JsonReceiptStore,
    PrincipalBinding,
    ProposalRecord,
    ProposalRequest,
    TransactionAdapter,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionKernel,
    TransactionNotFoundError,
    TransactionTarget,
    VolatileTransactionStore,
)


def _token_factory(prefix: str) -> str:
    aliases = {"txp": "flp", "txa": "fla", "txr": "flr"}
    return f"{aliases.get(prefix, prefix)}-{secrets.token_urlsafe(24)}"


def _canonical_identity_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _required_identity(value: Any, field_name: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} is required")
    return cleaned


def facility_transaction_scope_id(tenant_id: str, site_id: str) -> str:
    """Return an opaque transaction scope for one tenant-owned site."""

    tenant = _required_identity(tenant_id, "tenant_id")
    site = _required_identity(site_id, "site_id")
    digest = hashlib.sha256(
        _canonical_identity_bytes({"tenantId": tenant, "siteId": site})
    ).hexdigest()
    return f"fls:{digest}"


def facility_transaction_target(
    *,
    tenant_id: str,
    site_id: str,
    layout_id: str,
) -> TransactionTarget:
    return TransactionTarget(
        domain="facility-layout",
        scope_id=facility_transaction_scope_id(tenant_id, site_id),
        resource_id=_required_identity(layout_id, "layout_id"),
    )


def deterministic_facility_proposal_id(
    *,
    layout_id: str,
    base_revision: str,
    proposal_type: str,
    semantic_plan_hash: str,
    dependency_fingerprint: str,
) -> str:
    """Derive proposal identity only from the approved semantic contract."""

    identity = {
        "layoutId": _required_identity(layout_id, "layout_id"),
        "baseRevision": _required_identity(
            base_revision,
            "base_revision",
        ),
        "proposalType": _required_identity(
            proposal_type,
            "proposal_type",
        ),
        "semanticPlanHash": _required_identity(
            semantic_plan_hash,
            "semantic_plan_hash",
        ),
        "dependencyFingerprint": _required_identity(
            dependency_fingerprint,
            "dependency_fingerprint",
        ),
    }
    return (
        "flp-"
        + hashlib.sha256(_canonical_identity_bytes(identity)).hexdigest()
    )


def _opaque_principal_id(tenant_id: str, principal_id: str) -> str:
    tenant = _required_identity(tenant_id, "tenant_id")
    user = _required_identity(principal_id, "principal_id")
    return (
        "usr:"
        + hashlib.sha256(
            _canonical_identity_bytes(
                {"tenantId": tenant, "principalId": user}
            )
        ).hexdigest()[:32]
    )


def facility_transaction_principal(
    tenant_id: str,
    principal_id: str,
    session_id: str,
) -> PrincipalBinding:
    """Bind authority to opaque stable hashes, not public user identifiers."""

    tenant = _required_identity(tenant_id, "tenant_id")
    session = _required_identity(session_id, "session_id")
    return PrincipalBinding(
        principal_id=_opaque_principal_id(tenant, principal_id),
        session_id=(
            "ses:"
            + hashlib.sha256(
                _canonical_identity_bytes(
                    {"tenantId": tenant, "sessionId": session}
                )
            ).hexdigest()[:32]
        ),
    )


def _facility_proposal_owner(
    tenant_id: str,
    principal_id: str,
) -> PrincipalBinding:
    """Bind proposal creation to an owner before a UI session approves it."""

    tenant = _required_identity(tenant_id, "tenant_id")
    user = _required_identity(principal_id, "principal_id")
    return PrincipalBinding(
        principal_id=_opaque_principal_id(tenant, user),
        session_id=(
            "own:"
            + hashlib.sha256(
                _canonical_identity_bytes(
                    {
                        "tenantId": tenant,
                        "principalId": user,
                        "purpose": "facility-layout-proposal-owner-v1",
                    }
                )
            ).hexdigest()[:32]
        ),
    )


def facility_layout_binding(
    *,
    tenant_id: str,
    site_id: str,
    layout_id: str,
    base_revision: str,
    diff_hash: str,
    dependency_fingerprint: str,
) -> ExactBinding:
    return ExactBinding(
        target=facility_transaction_target(
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        ),
        base_revision=base_revision,
        diff_hash=diff_hash,
        dependency_fingerprint=dependency_fingerprint,
    )


class FacilityLayoutTransactionRuntime:
    """Durable receipts with restart-fail-closed proposal authority."""

    def __init__(
        self,
        *,
        receipt_root: str | Path | None = None,
        proposal_lifetime_seconds: float = 15 * 60,
        approval_lifetime_seconds: float = 5 * 60,
        limit: int = 512,
        require_distinct_approver: bool = False,
    ) -> None:
        receipt_store = (
            JsonReceiptStore(receipt_root)
            if receipt_root is not None
            else InMemoryReceiptStore(max_records=limit)
        )
        state_store = VolatileTransactionStore(
            max_proposals=limit,
            max_approvals=limit,
        )
        self._state_store = state_store
        self._receipt_store = receipt_store
        self._proposal_lifetime_seconds = proposal_lifetime_seconds
        self._approval_lifetime_seconds = approval_lifetime_seconds
        self.require_distinct_approver = bool(require_distinct_approver)
        self._authority_lock = threading.RLock()
        self.kernel = TransactionKernel(
            state_store=state_store,
            receipt_store=receipt_store,
            token_factory=_token_factory,
            proposal_lifetime_seconds=proposal_lifetime_seconds,
            approval_lifetime_seconds=approval_lifetime_seconds,
        )

    @staticmethod
    def _assert_target(
        binding: ExactBinding,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
    ) -> None:
        if binding.target != facility_transaction_target(
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        ):
            raise TransactionNotFoundError(
                "proposal_not_found",
                "Facility Layout transaction was not found.",
            )

    @staticmethod
    def _assert_owner(
        proposal: ProposalRecord,
        *,
        tenant_id: str,
        principal_id: str,
    ) -> PrincipalBinding:
        owner = _facility_proposal_owner(tenant_id, principal_id)
        if (
            proposal.principal is None
            or proposal.principal.principal_id != owner.principal_id
        ):
            raise TransactionAuthorizationError(
                "transaction_principal_mismatch",
                "Transaction proposal belongs to another principal.",
            )
        return owner

    def _proposal_kernel(self, proposal_id: str) -> TransactionKernel:
        def token_factory(prefix: str) -> str:
            return proposal_id if prefix == "txp" else _token_factory(prefix)

        return TransactionKernel(
            state_store=self._state_store,
            receipt_store=self._receipt_store,
            token_factory=token_factory,
            proposal_lifetime_seconds=self._proposal_lifetime_seconds,
            approval_lifetime_seconds=self._approval_lifetime_seconds,
        )

    def propose(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        proposal_id: str,
        binding: ExactBinding,
        payload: Mapping[str, Any],
        public_summary: Mapping[str, Any],
    ) -> ProposalRecord:
        owner = _facility_proposal_owner(tenant_id, principal_id)
        requested_payload = deepcopy(dict(payload))
        requested_summary = deepcopy(dict(public_summary))
        with self._authority_lock:
            existing = self._state_store.get_proposal(proposal_id)
            if (
                existing is not None
                and existing.status == "active"
                and existing.expires_at > time.time()
            ):
                self._assert_owner(
                    existing,
                    tenant_id=tenant_id,
                    principal_id=principal_id,
                )
                if (
                    existing.action != "apply-layout-plan"
                    or existing.binding != binding
                    or existing.payload != requested_payload
                    or existing.public_summary != requested_summary
                ):
                    raise TransactionBindingError(
                        "proposal_identity_conflict",
                        "Deterministic proposal identity is already bound.",
                    )
                return existing
            return self._proposal_kernel(proposal_id).propose(
                ProposalRequest(
                    action="apply-layout-plan",
                    binding=binding,
                    principal=owner,
                    principal_claimable=False,
                    payload=requested_payload,
                    public_summary=requested_summary,
                )
            )

    def get_proposal(
        self,
        proposal_id: str,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        principal_id: str,
    ) -> ProposalRecord:
        proposal = self.kernel.get_proposal(proposal_id)
        self._assert_target(
            proposal.binding,
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        )
        self._assert_owner(
            proposal,
            tenant_id=tenant_id,
            principal_id=principal_id,
        )
        return proposal

    def _get_proposal_for_approval(
        self,
        proposal_id: str,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
    ) -> ProposalRecord:
        """Resolve only the exact proposal target for an authorized approval."""

        proposal = self.kernel.get_proposal(proposal_id)
        self._assert_target(
            proposal.binding,
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        )
        return proposal

    def cancel(
        self,
        proposal_id: str,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        principal_id: str,
        session_id: str,
    ) -> ProposalRecord:
        with self._authority_lock:
            proposal = self.get_proposal(
                proposal_id,
                tenant_id=tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                principal_id=principal_id,
            )
            owner = self._assert_owner(
                proposal,
                tenant_id=tenant_id,
                principal_id=principal_id,
            )
            principal = facility_transaction_principal(
                tenant_id,
                principal_id,
                session_id,
            )
            if proposal.principal != owner and proposal.principal != principal:
                raise TransactionAuthorizationError(
                    "transaction_principal_mismatch",
                    "Transaction proposal belongs to another session.",
                )
            return self.kernel.cancel_proposal(
                proposal_id,
                principal=(
                    owner if proposal.principal == owner else principal
                ),
            )

    def approve(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        proposal_id: str,
        binding: ExactBinding,
        principal_id: str,
        session_id: str,
        idempotency_key: str,
        explicit_approval: bool,
        authorization_mode: str = "explicit",
    ) -> ApprovalRecord:
        with self._authority_lock:
            proposal = self._get_proposal_for_approval(
                proposal_id,
                tenant_id=tenant_id,
                site_id=site_id,
                layout_id=layout_id,
            )
            principal = facility_transaction_principal(
                tenant_id,
                principal_id,
                session_id,
            )
            if (
                self.require_distinct_approver
                and proposal.principal is not None
                and proposal.principal.principal_id
                == principal.principal_id
            ):
                raise TransactionAuthorizationError(
                    "maker_checker_required",
                    (
                        "Facility Layout pilot approval requires a principal "
                        "other than the proposal creator."
                    ),
                )
            if (
                proposal.principal is not None
                and proposal.principal.session_id.startswith("own:")
            ):
                proposal = replace(proposal, principal=principal)
                self._state_store.put_proposal(
                    proposal,
                    now=time.time(),
                )
            elif proposal.principal != principal:
                raise TransactionAuthorizationError(
                    "transaction_principal_mismatch",
                    "Transaction proposal belongs to another approver.",
                )
            return self.kernel.approve(
                ApprovalRequest(
                    proposal_id=proposal_id,
                    binding=binding,
                    principal=principal,
                    idempotency_key=idempotency_key,
                    explicit_approval=explicit_approval,
                    authorization_mode=authorization_mode,
                )
            )

    def apply(
        self,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        approval_token: str,
        binding: ExactBinding,
        principal_id: str,
        session_id: str,
        idempotency_key: str,
        adapter: TransactionAdapter,
    ) -> ApplyOutcome:
        self._assert_target(
            binding,
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        )
        approval = self._state_store.get_approval(approval_token)
        if approval is not None:
            self._assert_target(
                approval.binding,
                tenant_id=tenant_id,
                site_id=site_id,
                layout_id=layout_id,
            )
        return self.kernel.apply(
            ApplyRequest(
                approval_token=approval_token,
                binding=binding,
                principal=facility_transaction_principal(
                    tenant_id,
                    principal_id,
                    session_id,
                ),
                idempotency_key=idempotency_key,
            ),
            adapter,
        )


__all__ = [
    "FacilityLayoutTransactionRuntime",
    "deterministic_facility_proposal_id",
    "facility_layout_binding",
    "facility_transaction_scope_id",
    "facility_transaction_target",
    "facility_transaction_principal",
]
