from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import pytest

import ai_inspector.facility_layout.soak_evidence as soak_evidence

from ai_inspector.facility_layout.soak_evidence import (
    SoakEvidenceError,
    append_soak_event,
    facility_build_identity,
    load_soak_events,
    start_soak_campaign,
    summarize_soak_events,
    verified_apply_evidence,
    verified_dismissal_evidence,
)
from ai_inspector.transactions import (
    ApplyRequest,
    ApprovalRequest,
    CommitResult,
    ExactBinding,
    JsonReceiptStore,
    MutationPlan,
    PreparedRecord,
    PrincipalBinding,
    ProposalRequest,
    ReconciliationResult,
    TransactionKernel,
    TransactionReceipt,
    TransactionTarget,
)


BUILD = {
    "algorithm": "sha256-canonical-source-list-v1",
    "gitCommit": "abc123",
    "aggregateSha256": "a" * 64,
    "files": [],
}
START = "2026-07-30T00:00:00Z"


class _Clock:
    def __init__(self, value: str) -> None:
        self.set(value)

    def set(self, value: str) -> None:
        self.value = datetime.fromisoformat(
            value[:-1] + "+00:00"
        ).astimezone(timezone.utc)

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    value = _Clock(START)
    monkeypatch.setattr(soak_evidence, "_current_utc", value)
    return value


def _start(path: Path, clock: _Clock):
    clock.set(START)
    return start_soak_campaign(
        path,
        build_identity=BUILD,
    )


def _append(
    path: Path,
    kind: str,
    evidence: dict,
    *,
    when: str,
    clock: _Clock,
    build: dict = BUILD,
):
    clock.set(when)
    return append_soak_event(
        path,
        kind=kind,
        evidence=evidence,
        build_identity=build,
    )


def test_recording_api_exposes_no_timestamp_override():
    assert "started_at_utc" not in inspect.signature(
        start_soak_campaign
    ).parameters
    assert "occurred_at_utc" not in inspect.signature(
        append_soak_event
    ).parameters


def test_soak_events_are_source_bound_chained_and_fail_closed(
    tmp_path: Path,
    clock: _Clock,
):
    path = tmp_path / "soak.json"
    _start(path, clock)
    _append(
        path,
        "editing_session",
        {
            "layoutId": "fl-layout-01",
            "sessionId": "session-01",
            "layoutRevision": "1" * 64,
        },
        when="2026-07-30T00:01:00Z",
        clock=clock,
    )
    _append(
        path,
        "agent_preview",
        {
            "layoutId": "fl-layout-01",
            "proposalId": "proposal-01",
            "baseRevision": "1" * 64,
            "displayedForReview": True,
        },
        when="2026-07-30T00:02:00Z",
        clock=clock,
    )
    ledger = load_soak_events(path)
    result = summarize_soak_events(
        ledger,
        evaluated_at_utc="2026-08-13T00:03:00Z",
    )
    assert result["checks"]["eventChainValid"] is True
    assert result["observed"]["layouts"] == 1
    assert result["observed"]["editingSessions"] == 1
    assert result["observed"]["agentPreviews"] == 1
    assert result["status"] == "activity_requirements_pending"

    changed_build = deepcopy(BUILD)
    changed_build["aggregateSha256"] = "b" * 64
    with pytest.raises(SoakEvidenceError, match="build changed"):
        _append(
            path,
            "editing_session",
            {
                "layoutId": "fl-layout-01",
                "sessionId": "session-02",
                "layoutRevision": "1" * 64,
            },
            when="2026-07-30T00:04:00Z",
            clock=clock,
            build=changed_build,
        )

    raw = json.loads(path.read_text(encoding="ascii"))
    raw["events"][0]["evidence"]["sessionId"] = "tampered"
    assert summarize_soak_events(
        raw,
        evaluated_at_utc="2026-08-13T00:03:00Z",
    )["status"] == "evidence_chain_invalid"


def test_soak_dismissal_requires_byte_identity(tmp_path: Path):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_bytes(b'{"layout":1}\n')
    after.write_bytes(before.read_bytes())
    evidence = verified_dismissal_evidence(
        before,
        after,
        layout_id="fl-layout-01",
        proposal_id="proposal-01",
    )
    assert evidence["beforeSha256"] == evidence["afterSha256"]

    after.write_bytes(b'{"layout":2}\n')
    with pytest.raises(SoakEvidenceError, match="changed"):
        verified_dismissal_evidence(
            before,
            after,
            layout_id="fl-layout-01",
            proposal_id="proposal-01",
        )


def test_soak_apply_reads_canonical_durable_receipt(tmp_path: Path):
    store_root = tmp_path / "transactions"
    store = JsonReceiptStore(store_root)
    binding = ExactBinding(
        target=TransactionTarget(
            domain="facility-layout",
            scope_id="scope-01",
            resource_id="fl-layout-01",
        ),
        base_revision="1" * 64,
        diff_hash="2" * 64,
        dependency_fingerprint="3" * 64,
    )
    principal = PrincipalBinding("checker-01", "session-01")

    class _Adapter:
        def regenerate(self, proposal):
            return MutationPlan(binding=proposal.binding, payload={})

        def commit(self, _plan):
            return CommitResult(
                revision="f" * 64,
                payload={
                    "operationResult": {
                        "canonicalDiff": {"afterRevision": "f" * 64}
                    }
                },
            )

        def reconcile_prepared(self, _prepared):
            return ReconciliationResult.not_committed()

    kernel = TransactionKernel(receipt_store=store)
    proposal = kernel.propose(
        ProposalRequest(
            action="apply-layout-plan",
            binding=binding,
            principal=principal,
        )
    )
    approval = kernel.approve(
        ApprovalRequest(
            proposal_id=proposal.proposal_id,
            binding=binding,
            principal=principal,
            idempotency_key="soak-apply-01",
            explicit_approval=True,
        )
    )
    receipt = kernel.apply(
        ApplyRequest(
            approval_token=approval.approval_token,
            binding=binding,
            principal=principal,
            idempotency_key="soak-apply-01",
        ),
        _Adapter(),
    ).receipt

    evidence = verified_apply_evidence(
        store_root,
        receipt_id=receipt.receipt_id,
        layout_id="fl-layout-01",
    )
    assert evidence["receiptId"] == receipt.receipt_id
    assert evidence["resultingRevision"] == "f" * 64
    assert evidence["approvalFingerprint"] == receipt.approval_fingerprint
    assert evidence["explicitApprovalBound"] is True
    assert evidence["durablyRetrieved"] is True
    assert evidence["retrievalMethod"] == "canonical_transaction_store"

    with pytest.raises(SoakEvidenceError, match="different layout"):
        verified_apply_evidence(
            store_root,
            receipt_id=receipt.receipt_id,
            layout_id="fl-layout-02",
        )
    with pytest.raises(SoakEvidenceError, match="could not be retrieved"):
        verified_apply_evidence(
            store_root,
            receipt_id="flr-missing",
            layout_id="fl-layout-01",
        )


def test_soak_apply_rejects_receipt_without_approval_binding(
    tmp_path: Path,
):
    store_root = tmp_path / "unapproved-transactions"
    store = JsonReceiptStore(store_root)
    binding = ExactBinding(
        target=TransactionTarget(
            domain="facility-layout",
            scope_id="scope-01",
            resource_id="fl-layout-01",
        ),
        base_revision="1" * 64,
        diff_hash="2" * 64,
        dependency_fingerprint="3" * 64,
    )
    principal = PrincipalBinding("checker-01", "session-01")
    prepared = PreparedRecord(
        receipt_id="flr-unapproved-01",
        proposal_id="flp-unapproved-01",
        action="apply-layout-plan",
        binding=binding,
        principal=principal,
        idempotency_key="soak-unapproved-01",
        request_fingerprint="4" * 64,
        prepared_at=1.0,
    )
    receipt = TransactionReceipt(
        receipt_id=prepared.receipt_id,
        proposal_id=prepared.proposal_id,
        action=prepared.action,
        binding=binding,
        principal=principal,
        idempotency_key=prepared.idempotency_key,
        request_fingerprint=prepared.request_fingerprint,
        revision="f" * 64,
        created_at=2.0,
        payload={
            "operationResult": {
                "canonicalDiff": {"afterRevision": "f" * 64}
            }
        },
    )
    store.prepare(prepared)
    store.finalize(prepared, receipt)

    with pytest.raises(SoakEvidenceError, match="explicit approval"):
        verified_apply_evidence(
            store_root,
            receipt_id=receipt.receipt_id,
            layout_id="fl-layout-01",
        )


def test_soak_apply_does_not_create_missing_receipt_store(
    tmp_path: Path,
):
    store_root = tmp_path / "missing-transactions"

    with pytest.raises(
        SoakEvidenceError,
        match="receipt store does not exist",
    ):
        verified_apply_evidence(
            store_root,
            receipt_id="flr-missing",
            layout_id="fl-layout-01",
        )

    assert not store_root.exists()


def test_soak_rejects_backdating_and_unreviewed_previews(
    tmp_path: Path,
    clock: _Clock,
):
    path = tmp_path / "soak.json"
    _start(path, clock)
    with pytest.raises(SoakEvidenceError, match="predate"):
        _append(
            path,
            "editing_session",
            {
                "layoutId": "fl-layout-01",
                "sessionId": "session-01",
                "layoutRevision": "1" * 64,
            },
            when="2026-07-29T23:59:59Z",
            clock=clock,
        )
    with pytest.raises(SoakEvidenceError, match="displayed"):
        _append(
            path,
            "agent_preview",
            {
                "layoutId": "fl-layout-01",
                "proposalId": "proposal-01",
                "baseRevision": "1" * 64,
                "displayedForReview": False,
            },
            when="2026-07-30T00:01:00Z",
            clock=clock,
        )


def test_campaign_metadata_is_bound_into_the_event_chain(
    tmp_path: Path,
    clock: _Clock,
):
    path = tmp_path / "soak.json"
    _start(path, clock)
    raw = json.loads(path.read_text(encoding="ascii"))
    original_genesis = raw["campaignGenesisSha256"]
    assert raw["chainHeadSha256"] == original_genesis

    raw["campaign"]["startedAtUtc"] = "2026-07-29T00:00:00Z"
    path.write_text(
        json.dumps(raw, sort_keys=True) + "\n",
        encoding="ascii",
    )
    with pytest.raises(SoakEvidenceError, match="hash chain is invalid"):
        load_soak_events(path)

    result = summarize_soak_events(
        raw,
        evaluated_at_utc="2026-08-13T00:00:00Z",
    )
    assert result["checks"]["eventChainValid"] is False
    assert result["status"] == "evidence_chain_invalid"


def test_soak_requires_exactly_fourteen_times_twenty_four_hours(
    tmp_path: Path,
    clock: _Clock,
):
    path = tmp_path / "soak.json"
    ledger = _start(path, clock)

    early = summarize_soak_events(
        ledger,
        evaluated_at_utc="2026-08-12T23:59:59Z",
    )
    assert early["elapsedSeconds"] == (14 * 24 * 60 * 60) - 1
    assert early["checks"]["elapsedDurationMet"] is False
    assert early["status"] == "elapsed_duration_pending"

    boundary = summarize_soak_events(
        ledger,
        evaluated_at_utc="2026-08-13T00:00:00Z",
    )
    assert boundary["elapsedSeconds"] == 14 * 24 * 60 * 60
    assert boundary["checks"]["elapsedDurationMet"] is True
    assert boundary["status"] == "activity_requirements_pending"


def test_build_identity_includes_nested_write_workflows(tmp_path: Path):
    nested = (
        tmp_path
        / "ai_inspector"
        / "facility_layout"
        / "workflows"
        / "publish.py"
    )
    nested.parent.mkdir(parents=True)
    nested.write_text("VALUE = 1\n", encoding="ascii")
    recorder = tmp_path / "tools" / "record_facility_layout_soak.py"
    recorder.parent.mkdir(parents=True)
    recorder.write_text("VALUE = 1\n", encoding="ascii")
    transaction = (
        tmp_path / "ai_inspector" / "transactions" / "kernel.py"
    )
    transaction.parent.mkdir(parents=True)
    transaction.write_text("VALUE = 1\n", encoding="ascii")
    first = facility_build_identity(tmp_path)
    assert any(
        item["path"]
        == "ai_inspector/facility_layout/workflows/publish.py"
        for item in first["files"]
    )
    assert any(
        item["path"] == "tools/record_facility_layout_soak.py"
        for item in first["files"]
    )
    assert any(
        item["path"] == "ai_inspector/transactions/kernel.py"
        for item in first["files"]
    )

    nested.write_text("VALUE = 2\n", encoding="ascii")
    second = facility_build_identity(tmp_path)
    assert first["aggregateSha256"] != second["aggregateSha256"]

    recorder.write_text("VALUE = 2\n", encoding="ascii")
    third = facility_build_identity(tmp_path)
    assert second["aggregateSha256"] != third["aggregateSha256"]

    transaction.write_text("VALUE = 2\n", encoding="ascii")
    fourth = facility_build_identity(tmp_path)
    assert third["aggregateSha256"] != fourth["aggregateSha256"]
