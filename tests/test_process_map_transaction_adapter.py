"""Compatibility tests for Process Map use of the shared transaction kernel."""

from __future__ import annotations

from ai_inspector.process_map.transaction_adapter import (
    ProcessMapTransactionRuntime,
    process_map_binding,
)
from ai_inspector.transactions import (
    CommitResult,
    MutationPlan,
    ReconciliationResult,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionCancelledError,
    TransactionNotFoundError,
    TransactionReplayError,
)


def _hash(character: str) -> str:
    return character * 64


def _record(**overrides):
    value = {
        "productId": "fixture-product",
        "mapId": "default",
        "baseRevision": _hash("a"),
        "diffHash": _hash("b"),
        "action": "apply_operations",
        "wouldSave": True,
        "operations": [{"op": "add_process_step"}],
    }
    value.update(overrides)
    return value


class _Adapter:
    def regenerate(self, proposal):
        return MutationPlan(
            binding=proposal.binding,
            payload={"proposalId": proposal.proposal_id},
        )

    def commit(self, _plan):
        return CommitResult(
            revision=_hash("e"),
            payload={
                "legacyReceipt": {
                    "userId": "fixture-user",
                    "sessionId": "fixture-session",
                    "warnings": [],
                }
            },
        )

    def reconcile_prepared(self, _prepared):
        return ReconciliationResult.not_committed()


def _runtime():
    return ProcessMapTransactionRuntime(ttl_seconds=300, limit=32)


def _binding(record):
    return process_map_binding(
        product_id=record["productId"],
        map_id=record["mapId"],
        base_revision=record["baseRevision"],
        diff_hash=record["diffHash"],
        spatial_binding_hash=record.get("spatialBindingHash"),
        semantic_binding_hash=record.get("semanticBindingHash"),
    )


def test_adapter_preserves_process_map_token_prefixes_and_receipt_shape():
    runtime = _runtime()
    record = _record()
    proposal = runtime.propose(record)
    assert proposal.proposal_id.startswith("pmp-")
    approval = runtime.approve(
        proposal_id=proposal.proposal_id,
        binding=_binding(record),
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-adapter-0001",
        explicit_approval=True,
    )
    assert approval.approval_token.startswith("pma-")
    outcome = runtime.apply(
        approval_token=approval.approval_token,
        binding=_binding(record),
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-adapter-0001",
        adapter=_Adapter(),
    )
    receipt = runtime.legacy_receipt(outcome)
    assert receipt["receiptId"].startswith("pmr-")
    assert receipt["proposalId"] == proposal.proposal_id
    assert receipt["productId"] == "fixture-product"
    assert receipt["mapId"] == "default"
    assert receipt["userId"] == "fixture-user"
    assert runtime.resolve_receipts([receipt]) == [receipt]


def test_adapter_binds_first_approval_to_exact_user_and_session():
    runtime = _runtime()
    record = _record()
    proposal = runtime.propose(record)
    approval = runtime.approve(
        proposal_id=proposal.proposal_id,
        binding=_binding(record),
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-adapter-0002",
        explicit_approval=True,
    )
    try:
        runtime.apply(
            approval_token=approval.approval_token,
            binding=_binding(record),
            user_id="another-user",
            session_id="fixture-session",
            idempotency_key="fixture-adapter-0002",
            adapter=_Adapter(),
        )
    except TransactionAuthorizationError as error:
        assert error.code == "transaction_principal_mismatch"
    else:
        raise AssertionError("wrong principal was accepted")


def test_adapter_rejects_changed_dependency_binding_and_replay():
    runtime = _runtime()
    record = _record(spatialBindingHash=_hash("c"))
    proposal = runtime.propose(record)
    try:
        runtime.approve(
            proposal_id=proposal.proposal_id,
            binding=process_map_binding(
                product_id=record["productId"],
                map_id=record["mapId"],
                base_revision=record["baseRevision"],
                diff_hash=record["diffHash"],
                spatial_binding_hash=_hash("d"),
            ),
            user_id="fixture-user",
            session_id="fixture-session",
            idempotency_key="fixture-adapter-0003",
            explicit_approval=True,
        )
    except TransactionBindingError as error:
        assert error.code == "transaction_binding_mismatch"
    else:
        raise AssertionError("changed dependency binding was accepted")

    approval = runtime.approve(
        proposal_id=proposal.proposal_id,
        binding=_binding(record),
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-adapter-0003",
        explicit_approval=True,
    )
    runtime.apply(
        approval_token=approval.approval_token,
        binding=_binding(record),
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-adapter-0003",
        adapter=_Adapter(),
    )
    try:
        runtime.apply(
            approval_token=approval.approval_token,
            binding=_binding(record),
            user_id="fixture-user",
            session_id="fixture-session",
            idempotency_key="fixture-adapter-0003",
            adapter=_Adapter(),
        )
    except TransactionReplayError as error:
        assert error.code == "idempotency_replay"
    else:
        raise AssertionError("replayed apply was accepted")


def test_adapter_cancellation_and_restart_fail_closed():
    runtime = _runtime()
    record = _record()
    proposal = runtime.propose(record)
    runtime.cancel(
        proposal.proposal_id,
        user_id="fixture-user",
        session_id="fixture-session",
    )
    try:
        runtime.get_record(proposal.proposal_id)
    except TransactionCancelledError:
        pass
    else:
        raise AssertionError("cancelled proposal remained active")

    proposal = runtime.propose(record)
    runtime.reset()
    try:
        runtime.get_record(proposal.proposal_id)
    except TransactionNotFoundError:
        pass
    else:
        raise AssertionError("proposal survived a simulated restart")


def test_separate_runtime_instances_do_not_share_authority():
    first = _runtime()
    second = _runtime()
    proposal = first.propose(_record())
    try:
        second.get_record(proposal.proposal_id)
    except TransactionNotFoundError:
        pass
    else:
        raise AssertionError("transaction authority leaked across runtimes")
