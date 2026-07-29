"""Process Map compatibility adapter for the shared transaction kernel."""

from __future__ import annotations

import hashlib
import secrets
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ai_inspector.transactions import (
    ApplyOutcome,
    ApplyRequest,
    ApprovalRecord,
    ApprovalRequest,
    ExactBinding,
    InMemoryReceiptStore,
    PrincipalBinding,
    ProposalRecord,
    ProposalRequest,
    TransactionAdapter,
    TransactionKernel,
    TransactionNotFoundError,
    TransactionTarget,
    VolatileTransactionStore,
    canonical_json_bytes,
)


def _process_map_token_factory(prefix: str) -> str:
    aliases = {"txp": "pmp", "txa": "pma", "txr": "pmr"}
    return f"{aliases.get(prefix, prefix)}-{secrets.token_urlsafe(24)}"


def _dependency_fingerprint(
    spatial_binding_hash: Optional[str],
    semantic_binding_hash: Optional[str],
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "semanticBindingHash": semantic_binding_hash or None,
                "spatialBindingHash": spatial_binding_hash or None,
            }
        )
    ).hexdigest()


def _principal(user_id: str, session_id: str) -> PrincipalBinding:
    user = user_id.strip() if isinstance(user_id, str) else ""
    session = session_id.strip() if isinstance(session_id, str) else ""
    return PrincipalBinding(
        principal_id=(
            "usr:"
            + hashlib.sha256(user.encode("utf-8")).hexdigest()[:32]
        ),
        session_id=(
            "ses:"
            + hashlib.sha256(session.encode("utf-8")).hexdigest()[:32]
        ),
    )


def process_map_binding(
    *,
    product_id: str,
    map_id: str,
    base_revision: str,
    diff_hash: str,
    spatial_binding_hash: Optional[str] = None,
    semantic_binding_hash: Optional[str] = None,
) -> ExactBinding:
    return ExactBinding(
        target=TransactionTarget(
            domain="process-map",
            scope_id=product_id,
            resource_id=map_id,
        ),
        base_revision=base_revision,
        diff_hash=diff_hash,
        dependency_fingerprint=_dependency_fingerprint(
            spatial_binding_hash,
            semantic_binding_hash,
        ),
    )


class ProcessMapTransactionRuntime:
    """Preserve the public Process Map API on the shared transaction kernel."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        limit: int,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._limit = limit
        self._build_kernel()

    def _build_kernel(self) -> None:
        self._kernel = TransactionKernel(
            state_store=VolatileTransactionStore(
                max_proposals=self._limit,
                max_approvals=self._limit,
            ),
            receipt_store=InMemoryReceiptStore(max_records=self._limit),
            token_factory=_process_map_token_factory,
            proposal_lifetime_seconds=self._ttl_seconds,
            approval_lifetime_seconds=self._ttl_seconds,
        )

    @property
    def kernel(self) -> TransactionKernel:
        return self._kernel

    def reset(self) -> None:
        """Simulate a process restart; pending authority fails closed."""

        self._build_kernel()

    @staticmethod
    def binding_from_record(record: Mapping[str, Any]) -> ExactBinding:
        return process_map_binding(
            product_id=record["productId"],
            map_id=record["mapId"],
            base_revision=record["baseRevision"],
            diff_hash=record["diffHash"],
            spatial_binding_hash=record.get("spatialBindingHash"),
            semantic_binding_hash=record.get("semanticBindingHash"),
        )

    def propose(self, record: Mapping[str, Any]) -> ProposalRecord:
        proposal = self._kernel.propose(
            ProposalRequest(
                action=record["action"],
                binding=self.binding_from_record(record),
                principal=None,
                principal_claimable=True,
                payload={"record": deepcopy(dict(record))},
                public_summary={
                    "productId": record["productId"],
                    "mapId": record["mapId"],
                    "wouldSave": bool(record.get("wouldSave")),
                },
            )
        )
        return proposal

    def get_record(self, proposal_id: str) -> Dict[str, Any]:
        proposal = self._kernel.get_proposal(proposal_id)
        record = proposal.payload.get("record")
        if not isinstance(record, Mapping):
            raise TransactionNotFoundError(
                "proposal_not_found",
                "Process-map proposal payload is unavailable.",
            )
        result = deepcopy(dict(record))
        result["proposalId"] = proposal.proposal_id
        return result

    def cancel(
        self,
        proposal_id: str,
        *,
        user_id: str,
        session_id: str,
    ) -> ProposalRecord:
        return self._kernel.cancel_proposal(
            proposal_id,
            principal=_principal(user_id, session_id),
        )

    def approve(
        self,
        *,
        proposal_id: str,
        binding: ExactBinding,
        user_id: str,
        session_id: str,
        idempotency_key: str,
        explicit_approval: bool,
    ) -> ApprovalRecord:
        return self._kernel.approve(
            ApprovalRequest(
                proposal_id=proposal_id,
                binding=binding,
                principal=_principal(user_id, session_id),
                idempotency_key=idempotency_key,
                explicit_approval=explicit_approval,
            )
        )

    def apply(
        self,
        *,
        approval_token: str,
        binding: ExactBinding,
        user_id: str,
        session_id: str,
        idempotency_key: str,
        adapter: TransactionAdapter,
    ) -> ApplyOutcome:
        return self._kernel.apply(
            ApplyRequest(
                approval_token=approval_token,
                binding=binding,
                principal=_principal(user_id, session_id),
                idempotency_key=idempotency_key,
            ),
            adapter,
        )

    @staticmethod
    def legacy_receipt(outcome: ApplyOutcome) -> Dict[str, Any]:
        receipt = outcome.receipt
        metadata = receipt.payload.get("legacyReceipt")
        result = deepcopy(dict(metadata)) if isinstance(metadata, Mapping) else {}
        result.update(
            {
                "receiptId": receipt.receipt_id,
                "proposalId": receipt.proposal_id,
                "action": receipt.action,
                "productId": receipt.binding.target.scope_id,
                "mapId": receipt.binding.target.resource_id,
                "baseRevision": receipt.binding.base_revision,
                "revision": receipt.revision,
                "diffHash": receipt.binding.diff_hash,
                "idempotencyKey": receipt.idempotency_key,
            }
        )
        return result

    def resolve_receipts(
        self,
        receipts: Any,
        *,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        if (
            not isinstance(receipts, Sequence)
            or isinstance(receipts, (str, bytes, bytearray))
        ):
            return []
        requested: List[str] = []
        for item in list(receipts)[-max(1, min(24, int(limit))):]:
            if not isinstance(item, Mapping):
                continue
            receipt_id = item.get("receiptId")
            if (
                isinstance(receipt_id, str)
                and receipt_id
                and receipt_id not in requested
            ):
                requested.append(receipt_id)

        resolved: List[Dict[str, Any]] = []
        for receipt_id in requested:
            try:
                receipt = self._kernel.get_receipt(receipt_id)
            except TransactionNotFoundError:
                continue
            resolved.append(
                self.legacy_receipt(ApplyOutcome(receipt=receipt))
            )
        return resolved
