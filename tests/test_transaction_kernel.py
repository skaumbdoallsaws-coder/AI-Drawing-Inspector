"""Contract tests for the domain-neutral transaction kernel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import pytest

from ai_inspector.transactions import (
    ApplyRequest,
    ApprovalRequest,
    CommitResult,
    ExactBinding,
    InMemoryReceiptStore,
    JsonReceiptStore,
    MutationPlan,
    PrincipalBinding,
    ProposalRequest,
    ReconciliationResult,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionCancelledError,
    TransactionExpiredError,
    TransactionIdempotencyConflictError,
    TransactionKernel,
    TransactionNotFoundError,
    TransactionPreparedError,
    TransactionReplayError,
    TransactionTarget,
    TransactionValidationError,
    canonical_json_bytes,
)


def _hash(character: str) -> str:
    return character * 64


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SequentialTokens:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}-fixture-token-{self.count:04d}"


class RecordingAdapter:
    def __init__(
        self,
        *,
        revision: str = _hash("e"),
        commit_error: Optional[Exception] = None,
        reconciliation: Optional[ReconciliationResult] = None,
    ) -> None:
        self.revision = revision
        self.commit_error = commit_error
        self.reconciliation = (
            reconciliation
            if reconciliation is not None
            else ReconciliationResult.not_committed()
        )
        self.regenerate_calls = []
        self.commit_calls = []
        self.reconcile_calls = []

    def regenerate(self, proposal):
        self.regenerate_calls.append(proposal)
        return MutationPlan(
            binding=proposal.binding,
            payload={
                "action": proposal.action,
                "proposalId": proposal.proposal_id,
            },
        )

    def commit(self, plan):
        self.commit_calls.append(plan)
        if self.commit_error is not None:
            raise self.commit_error
        return CommitResult(
            revision=self.revision,
            payload={"createdIds": ["fixture-1"], "warnings": []},
        )

    def reconcile_prepared(self, prepared):
        self.reconcile_calls.append(prepared)
        return self.reconciliation


def _target(
    *,
    scope_id: str = "plant-001",
    resource_id: str = "layout-main",
) -> TransactionTarget:
    return TransactionTarget(
        domain="facility-layout",
        scope_id=scope_id,
        resource_id=resource_id,
    )


def _binding(
    *,
    target: Optional[TransactionTarget] = None,
    base_revision: str = _hash("a"),
    diff_hash: str = _hash("b"),
    dependency_fingerprint: str = _hash("c"),
) -> ExactBinding:
    return ExactBinding(
        target=target or _target(),
        base_revision=base_revision,
        diff_hash=diff_hash,
        dependency_fingerprint=dependency_fingerprint,
    )


def _principal(
    *,
    principal_id: str = "user-001",
    session_id: str = "session-001",
) -> PrincipalBinding:
    return PrincipalBinding(
        principal_id=principal_id,
        session_id=session_id,
    )


def _kernel(
    *,
    clock: Optional[FakeClock] = None,
    tokens: Optional[SequentialTokens] = None,
    receipt_store=None,
    proposal_lifetime: float = 60.0,
    approval_lifetime: float = 30.0,
) -> TransactionKernel:
    return TransactionKernel(
        receipt_store=receipt_store,
        clock=clock or FakeClock(),
        token_factory=tokens or SequentialTokens(),
        proposal_lifetime_seconds=proposal_lifetime,
        approval_lifetime_seconds=approval_lifetime,
    )


def _propose(
    kernel: TransactionKernel,
    *,
    binding: Optional[ExactBinding] = None,
    principal: Optional[PrincipalBinding] = None,
):
    exact_binding = binding or _binding()
    owner = principal or _principal()
    proposal = kernel.propose(
        ProposalRequest(
            action="facility_layout.apply",
            binding=exact_binding,
            principal=owner,
            payload={"operations": [{"op": "place", "id": "rack-001"}]},
            public_summary={"operationCount": 1},
        )
    )
    return proposal, exact_binding, owner


def _approve(
    kernel: TransactionKernel,
    *,
    binding: Optional[ExactBinding] = None,
    principal: Optional[PrincipalBinding] = None,
    idempotency_key: str = "idem-fixture-0001",
):
    proposal, exact_binding, owner = _propose(
        kernel,
        binding=binding,
        principal=principal,
    )
    approval = kernel.approve(
        ApprovalRequest(
            proposal_id=proposal.proposal_id,
            binding=exact_binding,
            principal=owner,
            idempotency_key=idempotency_key,
            explicit_approval=True,
        )
    )
    request = ApplyRequest(
        approval_token=approval.approval_token,
        binding=exact_binding,
        principal=owner,
        idempotency_key=idempotency_key,
    )
    return proposal, approval, request


def test_proposal_and_approval_have_independent_bounded_lifetimes():
    proposal_clock = FakeClock()
    proposal_kernel = _kernel(
        clock=proposal_clock,
        proposal_lifetime=10,
        approval_lifetime=5,
    )
    proposal, _, _ = _propose(proposal_kernel)
    assert proposal.expires_at - proposal.created_at == 10
    proposal_clock.advance(10)
    with pytest.raises(TransactionExpiredError) as error:
        proposal_kernel.get_proposal(proposal.proposal_id)
    assert error.value.code == "proposal_expired"

    approval_clock = FakeClock()
    approval_kernel = _kernel(
        clock=approval_clock,
        proposal_lifetime=20,
        approval_lifetime=4,
    )
    _, approval, request = _approve(approval_kernel)
    assert approval.expires_at - approval.created_at == 4
    approval_clock.advance(4)
    adapter = RecordingAdapter()
    with pytest.raises(TransactionExpiredError) as error:
        approval_kernel.apply(request, adapter)
    assert error.value.code == "approval_expired"
    assert adapter.regenerate_calls == []
    assert adapter.commit_calls == []


def test_approval_cannot_outlive_its_proposal():
    clock = FakeClock()
    kernel = _kernel(
        clock=clock,
        proposal_lifetime=3,
        approval_lifetime=30,
    )
    proposal, approval, _ = _approve(kernel)
    assert approval.expires_at == proposal.expires_at


def test_explicit_approval_is_required():
    kernel = _kernel()
    proposal, binding, principal = _propose(kernel)
    with pytest.raises(TransactionAuthorizationError) as error:
        kernel.approve(
            ApprovalRequest(
                proposal_id=proposal.proposal_id,
                binding=binding,
                principal=principal,
                idempotency_key="idem-fixture-0002",
                explicit_approval=False,
            )
        )
    assert error.value.code == "explicit_approval_required"


def test_cancellation_invalidates_proposal_and_every_approval():
    kernel = _kernel()
    proposal, approval, request = _approve(kernel)

    cancelled = kernel.cancel(
        proposal.proposal_id,
        principal=proposal.principal,
    )
    assert cancelled.status == "cancelled"
    assert (
        kernel.cancel(
            proposal.proposal_id,
            principal=proposal.principal,
        )
        == cancelled
    )

    with pytest.raises(TransactionCancelledError) as proposal_error:
        kernel.get_proposal(proposal.proposal_id)
    assert proposal_error.value.code == "proposal_cancelled"

    adapter = RecordingAdapter()
    with pytest.raises(TransactionCancelledError) as approval_error:
        kernel.apply(request, adapter)
    assert approval_error.value.code == "approval_cancelled"
    assert adapter.commit_calls == []
    assert approval.status == "active"


def test_only_the_bound_principal_and_session_can_cancel():
    kernel = _kernel()
    proposal, _, _ = _propose(kernel)
    with pytest.raises(TransactionAuthorizationError) as error:
        kernel.cancel(
            proposal.proposal_id,
            principal=_principal(session_id="session-other"),
        )
    assert error.value.code == "transaction_principal_mismatch"
    assert kernel.get_proposal(proposal.proposal_id).status == "active"


@pytest.mark.parametrize(
    "principal",
    [
        _principal(principal_id="user-other"),
        _principal(session_id="session-other"),
    ],
)
def test_approval_is_bound_to_principal_and_session(principal):
    kernel = _kernel()
    proposal, binding, owner = _propose(kernel)
    with pytest.raises(TransactionAuthorizationError) as error:
        kernel.approve(
            ApprovalRequest(
                proposal_id=proposal.proposal_id,
                binding=binding,
                principal=principal,
                idempotency_key="idem-fixture-0003",
                explicit_approval=True,
            )
        )
    assert error.value.code == "transaction_principal_mismatch"
    assert owner != principal


def test_apply_is_bound_to_principal_and_session():
    kernel = _kernel()
    _, _, request = _approve(kernel)
    altered = ApplyRequest(
        approval_token=request.approval_token,
        binding=request.binding,
        principal=_principal(session_id="session-other"),
        idempotency_key=request.idempotency_key,
    )
    adapter = RecordingAdapter()
    with pytest.raises(TransactionAuthorizationError) as error:
        kernel.apply(altered, adapter)
    assert error.value.code == "transaction_principal_mismatch"
    assert adapter.commit_calls == []


@pytest.mark.parametrize(
    "altered_binding",
    [
        _binding(target=_target(resource_id="layout-other")),
        _binding(base_revision=_hash("d")),
        _binding(diff_hash=_hash("d")),
        _binding(dependency_fingerprint=_hash("d")),
    ],
    ids=["target", "base-revision", "diff-hash", "dependencies"],
)
def test_approval_requires_the_exact_mutation_binding(altered_binding):
    kernel = _kernel()
    proposal, binding, principal = _propose(kernel)
    assert altered_binding != binding
    with pytest.raises(TransactionBindingError) as error:
        kernel.approve(
            ApprovalRequest(
                proposal_id=proposal.proposal_id,
                binding=altered_binding,
                principal=principal,
                idempotency_key="idem-fixture-0004",
                explicit_approval=True,
            )
        )
    assert error.value.code == "transaction_binding_mismatch"


def test_apply_rejects_an_altered_binding_before_regeneration():
    kernel = _kernel()
    _, _, request = _approve(kernel)
    altered = ApplyRequest(
        approval_token=request.approval_token,
        binding=_binding(diff_hash=_hash("d")),
        principal=request.principal,
        idempotency_key=request.idempotency_key,
    )
    adapter = RecordingAdapter()
    with pytest.raises(TransactionBindingError) as error:
        kernel.apply(altered, adapter)
    assert error.value.code == "transaction_binding_mismatch"
    assert adapter.regenerate_calls == []


def test_domain_adapter_must_regenerate_the_exact_approved_diff():
    kernel = _kernel()
    _, _, request = _approve(kernel)

    class AlteringAdapter(RecordingAdapter):
        def regenerate(self, proposal):
            self.regenerate_calls.append(proposal)
            return MutationPlan(
                binding=_binding(diff_hash=_hash("f")),
                payload={},
            )

    adapter = AlteringAdapter()
    with pytest.raises(TransactionBindingError) as error:
        kernel.apply(request, adapter)
    assert error.value.code == "transaction_binding_mismatch"
    assert adapter.commit_calls == []


def test_in_memory_store_rejects_exact_replay_for_process_map_compatibility():
    kernel = _kernel(receipt_store=InMemoryReceiptStore())
    _, _, request = _approve(kernel)
    adapter = RecordingAdapter()

    first = kernel.apply(request, adapter)
    assert first.replayed is False
    assert first.recovered is False
    assert first.receipt.revision == _hash("e")
    assert len(adapter.commit_calls) == 1

    with pytest.raises(TransactionReplayError) as error:
        kernel.apply(request, adapter)
    assert error.value.code == "idempotency_replay"
    assert len(adapter.commit_calls) == 1
    assert kernel.get_receipt(first.receipt.receipt_id) == first.receipt


def test_same_idempotency_key_with_changed_request_fails():
    store = InMemoryReceiptStore()
    kernel = _kernel(receipt_store=store)
    _, _, request = _approve(kernel)
    kernel.apply(request, RecordingAdapter())

    changed = ApplyRequest(
        approval_token=request.approval_token,
        binding=_binding(dependency_fingerprint=_hash("d")),
        principal=request.principal,
        idempotency_key=request.idempotency_key,
    )
    with pytest.raises(TransactionIdempotencyConflictError) as error:
        kernel.apply(changed, RecordingAdapter())
    assert error.value.code == "idempotency_key_conflict"


def test_duplicate_approval_is_rejected_before_apply():
    kernel = _kernel()
    proposal, binding, principal = _propose(kernel)
    request = ApprovalRequest(
        proposal_id=proposal.proposal_id,
        binding=binding,
        principal=principal,
        idempotency_key="idem-fixture-0005",
        explicit_approval=True,
    )
    kernel.approve(request)
    with pytest.raises(TransactionReplayError) as error:
        kernel.approve(request)
    assert error.value.code == "approval_replay"


def test_restart_loses_unprepared_approval_and_fails_closed():
    clock = FakeClock()
    tokens = SequentialTokens()
    receipt_store = InMemoryReceiptStore()
    first_kernel = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=receipt_store,
    )
    _, _, request = _approve(first_kernel)

    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=receipt_store,
    )
    adapter = RecordingAdapter()
    with pytest.raises(TransactionNotFoundError) as error:
        restarted.apply(request, adapter)
    assert error.value.code == "approval_not_found"
    assert adapter.regenerate_calls == []
    assert adapter.commit_calls == []


def test_json_store_recovers_exact_finalized_retry_after_restart(tmp_path):
    clock = FakeClock()
    tokens = SequentialTokens()
    root = tmp_path / "facility-layout-transactions"
    first_kernel = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    _, _, request = _approve(first_kernel)
    first_adapter = RecordingAdapter()
    first = first_kernel.apply(request, first_adapter)
    assert len(first_adapter.commit_calls) == 1

    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    retry_adapter = RecordingAdapter()
    retried = restarted.apply(request, retry_adapter)
    assert retried.receipt == first.receipt
    assert retried.replayed is True
    assert retried.recovered is True
    assert retry_adapter.regenerate_calls == []
    assert retry_adapter.reconcile_calls == []
    assert retry_adapter.commit_calls == []


def _leave_durable_prepared_record(tmp_path):
    clock = FakeClock()
    tokens = SequentialTokens()
    root = tmp_path / "prepared-transactions"
    store = JsonReceiptStore(root)
    kernel = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=store,
    )
    _, _, request = _approve(kernel)
    adapter = RecordingAdapter(commit_error=RuntimeError("commit interrupted"))
    with pytest.raises(RuntimeError, match="commit interrupted"):
        kernel.apply(request, adapter)
    fingerprint = kernel.request_fingerprint(
        request.binding,
        request.principal,
        request.idempotency_key,
    )
    record = store.lookup(request.idempotency_key, fingerprint)
    assert record is not None
    assert record.state == "prepared"
    assert len(adapter.commit_calls) == 1
    return clock, tokens, root, request, record


def test_prepared_record_reconciles_committed_result_without_recommit(tmp_path):
    clock, tokens, root, request, prepared_record = (
        _leave_durable_prepared_record(tmp_path)
    )
    committed = CommitResult(
        revision=_hash("f"),
        payload={"createdIds": ["fixture-1"], "warnings": []},
    )
    recovery_adapter = RecordingAdapter(
        reconciliation=ReconciliationResult.committed(committed)
    )
    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    recovered = restarted.apply(request, recovery_adapter)

    assert recovered.replayed is True
    assert recovered.recovered is True
    assert recovered.receipt.receipt_id == prepared_record.prepared.receipt_id
    assert recovered.receipt.revision == _hash("f")
    assert len(recovery_adapter.reconcile_calls) == 1
    assert recovery_adapter.regenerate_calls == []
    assert recovery_adapter.commit_calls == []

    second_restart = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    exact_retry = second_restart.apply(request, RecordingAdapter())
    assert exact_retry.receipt == recovered.receipt


def test_recovery_adopts_receipt_written_before_finalize_crash(
    tmp_path,
    monkeypatch,
):
    clock = FakeClock()
    tokens = SequentialTokens()
    root = tmp_path / "receipt-before-idempotency-crash"
    store = JsonReceiptStore(root)
    kernel = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=store,
    )
    _, _, request = _approve(kernel)
    committed = CommitResult(
        revision=_hash("f"),
        payload={"createdIds": ["fixture-1"], "warnings": []},
    )
    adapter = RecordingAdapter(revision=committed.revision)
    original_write = store._atomic_write

    def fail_finalized_idempotency_write(path, data):
        if (
            path.parent.name == "idempotency"
            and b'"state": "finalized"' in data
        ):
            raise OSError("simulated crash before idempotency finalize")
        original_write(path, data)

    monkeypatch.setattr(
        store,
        "_atomic_write",
        fail_finalized_idempotency_write,
    )
    with pytest.raises(
        OSError,
        match="simulated crash before idempotency finalize",
    ):
        kernel.apply(request, adapter)
    receipt_files = list((root / "receipts").glob("*.json"))
    assert len(receipt_files) == 1
    orphaned_receipt = json.loads(
        receipt_files[0].read_text(encoding="ascii")
    )

    clock.advance(7)
    recovery_adapter = RecordingAdapter(
        reconciliation=ReconciliationResult.committed(committed)
    )
    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    recovered = restarted.apply(request, recovery_adapter)
    assert recovered.replayed is True
    assert recovered.recovered is True
    assert recovered.receipt.created_at == orphaned_receipt["createdAt"]
    assert recovered.receipt.revision == committed.revision
    assert recovered.receipt.payload == committed.payload
    assert recovery_adapter.commit_calls == []

    exact_retry = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    ).apply(request, RecordingAdapter())
    assert exact_retry.receipt == recovered.receipt


def test_prepared_unknown_outcome_fails_without_guessing(tmp_path):
    clock, tokens, root, request, _ = _leave_durable_prepared_record(tmp_path)
    adapter = RecordingAdapter(
        reconciliation=ReconciliationResult.unknown()
    )
    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    with pytest.raises(TransactionPreparedError) as error:
        restarted.apply(request, adapter)
    assert error.value.code == "prepared_transaction_pending"
    assert len(adapter.reconcile_calls) == 1
    assert adapter.regenerate_calls == []
    assert adapter.commit_calls == []


def test_prepared_not_committed_after_restart_still_requires_live_approval(
    tmp_path,
):
    clock, tokens, root, request, _ = _leave_durable_prepared_record(tmp_path)
    adapter = RecordingAdapter(
        reconciliation=ReconciliationResult.not_committed()
    )
    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    with pytest.raises(TransactionNotFoundError) as error:
        restarted.apply(request, adapter)
    assert error.value.code == "approval_not_found"
    assert len(adapter.reconcile_calls) == 1
    assert adapter.regenerate_calls == []
    assert adapter.commit_calls == []


def test_prepared_not_committed_can_retry_while_approval_is_still_live(
    tmp_path,
):
    clock = FakeClock()
    root = tmp_path / "same-process-retry"
    kernel = _kernel(
        clock=clock,
        receipt_store=JsonReceiptStore(root),
    )
    _, _, request = _approve(kernel)
    failed_adapter = RecordingAdapter(
        commit_error=RuntimeError("nothing committed")
    )
    with pytest.raises(RuntimeError, match="nothing committed"):
        kernel.apply(request, failed_adapter)

    retry_adapter = RecordingAdapter(
        reconciliation=ReconciliationResult.not_committed()
    )
    outcome = kernel.apply(request, retry_adapter)
    assert outcome.replayed is False
    assert len(retry_adapter.reconcile_calls) == 1
    assert len(retry_adapter.regenerate_calls) == 1
    assert len(retry_adapter.commit_calls) == 1


def test_same_key_changed_request_fails_after_json_store_restart(tmp_path):
    clock = FakeClock()
    tokens = SequentialTokens()
    root = tmp_path / "durable-conflict"
    kernel = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    _, _, request = _approve(kernel)
    kernel.apply(request, RecordingAdapter())

    restarted = _kernel(
        clock=clock,
        tokens=tokens,
        receipt_store=JsonReceiptStore(root),
    )
    changed = ApplyRequest(
        approval_token=request.approval_token,
        binding=_binding(base_revision=_hash("d")),
        principal=request.principal,
        idempotency_key=request.idempotency_key,
    )
    with pytest.raises(TransactionIdempotencyConflictError) as error:
        restarted.apply(changed, RecordingAdapter())
    assert error.value.code == "idempotency_key_conflict"


def test_canonical_json_bytes_are_sorted_ascii_and_newline_terminated():
    value = {"z": 1, "a": "caf\u00e9", "nested": {"b": 2, "a": 1}}
    expected = (
        b"{\n"
        b'  "a": "caf\\u00e9",\n'
        b'  "nested": {\n'
        b'    "a": 1,\n'
        b'    "b": 2\n'
        b"  },\n"
        b'  "z": 1\n'
        b"}\n"
    )
    assert canonical_json_bytes(value) == expected
    assert all(byte < 128 for byte in expected)


def test_json_store_uses_hashed_paths_and_canonical_record_bytes(tmp_path):
    root = tmp_path / "canonical-store"
    store = JsonReceiptStore(root)
    kernel = _kernel(receipt_store=store)
    _, _, request = _approve(
        kernel,
        idempotency_key="human-visible-idempotency-key",
    )
    outcome = kernel.apply(request, RecordingAdapter())

    key_digest = hashlib.sha256(
        request.idempotency_key.encode("utf-8")
    ).hexdigest()
    receipt_digest = hashlib.sha256(
        outcome.receipt.receipt_id.encode("utf-8")
    ).hexdigest()
    idempotency_path = root / "idempotency" / f"{key_digest}.json"
    receipt_path = root / "receipts" / f"{receipt_digest}.json"
    assert idempotency_path.is_file()
    assert receipt_path.is_file()
    assert request.idempotency_key not in idempotency_path.name
    assert outcome.receipt.receipt_id not in receipt_path.name

    for path in (idempotency_path, receipt_path):
        raw = path.read_bytes()
        parsed = json.loads(raw.decode("ascii"))
        assert raw == canonical_json_bytes(parsed)
        assert all(byte < 128 for byte in raw)


def test_identifiers_and_store_paths_are_bounded_and_path_free(tmp_path):
    with pytest.raises(TransactionValidationError) as target_error:
        TransactionTarget(
            domain="facility-layout",
            scope_id="plant-001",
            resource_id="../outside",
        )
    assert target_error.value.code == "invalid_transaction_identifier"

    with pytest.raises(TransactionValidationError) as long_id_error:
        TransactionTarget(
            domain="facility-layout",
            scope_id="s" * 129,
            resource_id="layout-main",
        )
    assert long_id_error.value.code == "invalid_transaction_identifier"

    with pytest.raises(TransactionValidationError) as path_error:
        JsonReceiptStore("x" * 4097)
    assert path_error.value.code == "invalid_transaction_store_path"

    store = JsonReceiptStore(tmp_path / "safe-root")
    with pytest.raises(TransactionValidationError) as key_error:
        store.lookup("../bad-key", _hash("a"))
    assert key_error.value.code == "invalid_idempotency_key"


def test_non_json_and_oversized_proposal_payloads_fail_before_storage():
    kernel = _kernel()
    with pytest.raises(TransactionValidationError) as non_json:
        kernel.propose(
            ProposalRequest(
                action="facility_layout.apply",
                binding=_binding(),
                principal=_principal(),
                payload={"unsupported": object()},
            )
        )
    assert non_json.value.code == "invalid_transaction_payload"

    with pytest.raises(TransactionValidationError) as too_large:
        kernel.propose(
            ProposalRequest(
                action="facility_layout.apply",
                binding=_binding(),
                principal=_principal(),
                payload={"content": "x" * (2 * 1024 * 1024)},
            )
        )
    assert too_large.value.code == "transaction_payload_too_large"


def test_token_and_clock_factories_are_injected_and_validated():
    clock = FakeClock(123.5)
    tokens = SequentialTokens()
    kernel = _kernel(clock=clock, tokens=tokens)
    proposal, _, _ = _propose(kernel)
    assert proposal.created_at == 123.5
    assert proposal.proposal_id == "txp-fixture-token-0001"

    invalid_tokens = TransactionKernel(
        clock=clock,
        token_factory=lambda _prefix: "../bad",
    )
    with pytest.raises(TransactionValidationError) as error:
        _propose(invalid_tokens)
    assert error.value.code == "invalid_transaction_token"


def test_proposal_requires_a_bound_or_explicitly_claimable_principal():
    with pytest.raises(TransactionValidationError) as missing:
        ProposalRequest(
            action="process_map.apply",
            binding=_binding(),
            principal=None,
        )
    assert missing.value.code == "transaction_principal_required"

    with pytest.raises(TransactionValidationError) as conflicting:
        ProposalRequest(
            action="process_map.apply",
            binding=_binding(),
            principal=_principal(),
            principal_claimable=True,
        )
    assert conflicting.value.code == "invalid_transaction_principal"


def test_claimable_proposal_binds_the_first_explicit_approval_principal():
    kernel = _kernel()
    binding = _binding()
    owner = _principal()
    proposal = kernel.propose(
        ProposalRequest(
            action="process_map.apply",
            binding=binding,
            principal=None,
            principal_claimable=True,
            payload={"legacyCompatibility": True},
        )
    )
    assert proposal.principal is None
    assert proposal.principal_claimable is True
    assert proposal.public_dict()["principal"] is None

    approval = kernel.approve(
        ApprovalRequest(
            proposal_id=proposal.proposal_id,
            binding=binding,
            principal=owner,
            idempotency_key="legacy-claim-0001",
            explicit_approval=True,
        )
    )
    assert approval.principal == owner

    outcome = kernel.apply(
        ApplyRequest(
            approval_token=approval.approval_token,
            binding=binding,
            principal=owner,
            idempotency_key="legacy-claim-0001",
        ),
        RecordingAdapter(),
    )
    assert outcome.receipt.principal == owner


def test_claimable_proposal_rejects_a_different_apply_principal():
    kernel = _kernel()
    binding = _binding()
    owner = _principal()
    proposal = kernel.propose(
        ProposalRequest(
            action="process_map.apply",
            binding=binding,
            principal=None,
            principal_claimable=True,
        )
    )
    approval = kernel.approve(
        ApprovalRequest(
            proposal_id=proposal.proposal_id,
            binding=binding,
            principal=owner,
            idempotency_key="legacy-claim-0002",
            explicit_approval=True,
        )
    )
    with pytest.raises(TransactionAuthorizationError) as error:
        kernel.apply(
            ApplyRequest(
                approval_token=approval.approval_token,
                binding=binding,
                principal=_principal(principal_id="user-002"),
                idempotency_key="legacy-claim-0002",
            ),
            RecordingAdapter(),
        )
    assert error.value.code == "transaction_principal_mismatch"


def test_claimable_proposal_can_be_cancelled_by_opaque_token():
    kernel = _kernel()
    proposal = kernel.propose(
        ProposalRequest(
            action="process_map.apply",
            binding=_binding(),
            principal=None,
            principal_claimable=True,
        )
    )
    cancelled = kernel.cancel_proposal(
        proposal.proposal_id,
        principal=_principal(),
    )
    assert cancelled.status == "cancelled"
    with pytest.raises(TransactionCancelledError):
        kernel.get_proposal(proposal.proposal_id)
