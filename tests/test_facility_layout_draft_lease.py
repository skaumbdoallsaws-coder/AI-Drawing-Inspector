from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_inspector.facility_layout.facility_draft_lease import (
    FacilityDraftLeaseConflictError,
    FacilityDraftLeaseRepository,
)
from ai_inspector.facility_layout.generation_run_repository import (
    FacilityGenerationRunRepository,
)


BASE = "0" * 64
DRAFT_A = "1" * 64
DRAFT_B = "2" * 64
ROOT_FP = "3" * 64
A_FP = "4" * 64
B_FP = "5" * 64


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 6, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **values: int) -> None:
        self.current += timedelta(**values)


def _generation(repository: FacilityGenerationRunRepository) -> dict:
    return repository.create_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id="fl-a",
        user_id="user-a",
        session_id="session-a",
        base_layout_revision=BASE,
        effective_provider="anthropic",
        effective_model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        intent_hash="6" * 64,
        dependency_fingerprint="7" * 64,
        prototype_mode=True,
        writable=True,
        run_id="fgr-shared-lease",
    )


def _source_owner(lease: dict) -> dict:
    return {
        "ownerKind": lease["ownerKind"],
        "ownerRunId": lease["ownerRunId"],
        "ownerToken": lease["ownerToken"],
        "leaseRevision": lease["leaseRevision"],
    }


def _prepare(
    leases: FacilityDraftLeaseRepository,
    lease: dict | None,
    *,
    design_run_id: str = "fdlr-a",
    source_draft: str = BASE,
    root: str = ROOT_FP,
    previous: str = ROOT_FP,
    expected: str = A_FP,
) -> dict:
    return leases.prepare_adoption(
        tenant_id="tenant-a",
        site_id="site-a",
        layout_id="fl-a",
        design_run_id=design_run_id,
        base_saved_layout_revision=BASE,
        current_draft_revision=source_draft,
        editor_generation_id="editor-generation-1",
        proposal_binding={"proposalId": "proposal-a", "proposalRevision": "8" * 64},
        expected_source_owner=_source_owner(lease) if lease is not None else None,
        root_installation_fingerprint=root,
        previous_installation_fingerprint=previous,
        expected_installation_fingerprint=expected,
    )


def _commit(
    leases: FacilityDraftLeaseRepository, prepared: dict, result: str = DRAFT_A
) -> dict:
    return leases.commit_adoption(
        tenant_id="tenant-a",
        site_id="site-a",
        adoption_id=prepared["adoption"]["adoptionId"],
        adoption_token=prepared["adoptionToken"],
        expected_adoption_revision=prepared["adoption"]["adoptionRevision"],
        expected_prepared_lease_revision=prepared["lease"]["leaseRevision"],
        result_draft_revision=result,
    )


def _ack(
    leases: FacilityDraftLeaseRepository,
    prepared: dict,
    committed: dict,
    observed: str,
) -> dict:
    return leases.acknowledge_adoption(
        tenant_id="tenant-a",
        site_id="site-a",
        adoption_id=prepared["adoption"]["adoptionId"],
        adoption_token=prepared["adoptionToken"],
        expected_adoption_revision=committed["adoption"]["adoptionRevision"],
        observed_installation_fingerprint=observed,
    )


def test_generation_and_design_use_one_physical_lease_namespace(tmp_path: Path) -> None:
    clock = _Clock()
    generation = FacilityGenerationRunRepository(tmp_path, clock=clock)
    created = _generation(generation)
    leases = FacilityDraftLeaseRepository(tmp_path, clock=clock)
    observed = leases.inspect("tenant-a", "site-a", "fl-a")
    assert observed["active"] is True
    assert observed["lease"]["ownerKind"] == "generation_run"
    assert observed["lease"]["ownerRunId"] == created["run"]["runId"]
    with pytest.raises(FacilityDraftLeaseConflictError) as caught:
        leases.acquire(
            tenant_id="tenant-a",
            site_id="site-a",
            layout_id="fl-a",
            owner_kind="design_run",
            owner_run_id="fdlr-conflict",
            base_saved_layout_revision=BASE,
            current_draft_revision=BASE,
        )
    assert caught.value.code == "facility_draft_lease_conflict"


def test_adoption_is_single_use_and_blocks_every_competing_writer(tmp_path: Path) -> None:
    clock = _Clock()
    generation = FacilityGenerationRunRepository(tmp_path, clock=clock)
    _generation(generation)
    leases = FacilityDraftLeaseRepository(tmp_path, clock=clock)
    source = leases.inspect("tenant-a", "site-a", "fl-a")["lease"]
    prepared = _prepare(leases, source)
    assert prepared["lease"]["status"] == "adopting"
    with pytest.raises(FacilityDraftLeaseConflictError):
        leases.acquire(
            tenant_id="tenant-a",
            site_id="site-a",
            layout_id="fl-a",
            owner_kind="manual_write",
            owner_run_id="manual-a",
            base_saved_layout_revision=BASE,
            current_draft_revision=BASE,
        )
    committed = _commit(leases, prepared)
    assert committed["lease"]["ownerKind"] == "design_run"
    assert committed["lease"]["status"] == "review_required"
    acknowledged = _ack(leases, prepared, committed, A_FP)
    assert acknowledged["lease"]["status"] == "active"
    with pytest.raises(FacilityDraftLeaseConflictError) as caught:
        _commit(leases, prepared)
    assert caught.value.code == "facility_draft_lease_adoption_revision_conflict"


def test_failed_first_install_restores_generation_owner_byte_for_byte(tmp_path: Path) -> None:
    clock = _Clock()
    generation = FacilityGenerationRunRepository(tmp_path, clock=clock)
    _generation(generation)
    leases = FacilityDraftLeaseRepository(tmp_path, clock=clock)
    source = leases.inspect("tenant-a", "site-a", "fl-a")["lease"]
    prepared = _prepare(leases, source)
    committed = _commit(leases, prepared)
    recovered = leases.recover_adoption(
        tenant_id="tenant-a",
        site_id="site-a",
        adoption_id=prepared["adoption"]["adoptionId"],
        expected_adoption_revision=committed["adoption"]["adoptionRevision"],
        observed_installation_fingerprint=ROOT_FP,
    )
    assert recovered["lease"] == source
    assert leases.inspect("tenant-a", "site-a", "fl-a")["lease"] == source


def test_failed_replacement_restores_a_not_root_o(tmp_path: Path) -> None:
    clock = _Clock()
    leases = FacilityDraftLeaseRepository(tmp_path, clock=clock)
    first = _prepare(leases, None)
    first_commit = _commit(leases, first)
    first_ack = _ack(leases, first, first_commit, A_FP)
    lease_a = deepcopy(first_ack["lease"])
    replacement = _prepare(
        leases,
        lease_a,
        source_draft=DRAFT_A,
        root=ROOT_FP,
        previous=A_FP,
        expected=B_FP,
    )
    replacement_commit = _commit(leases, replacement, DRAFT_B)
    assert replacement_commit["lease"]["ownerToken"] == lease_a["ownerToken"]
    assert replacement_commit["lease"]["priorOwnerRef"] == lease_a[
        "priorOwnerRef"
    ]
    recovered = leases.recover_adoption(
        tenant_id="tenant-a",
        site_id="site-a",
        adoption_id=replacement["adoption"]["adoptionId"],
        expected_adoption_revision=replacement_commit["adoption"]["adoptionRevision"],
        observed_installation_fingerprint=A_FP,
    )
    assert recovered["lease"] == lease_a
    assert recovered["lease"]["currentDraftRevision"] == DRAFT_A


def test_valid_undo_returns_exact_live_generation_owner(tmp_path: Path) -> None:
    clock = _Clock()
    generation = FacilityGenerationRunRepository(tmp_path, clock=clock)
    _generation(generation)
    leases = FacilityDraftLeaseRepository(tmp_path, clock=clock)
    source = leases.inspect("tenant-a", "site-a", "fl-a")["lease"]
    prepared = _prepare(leases, source)
    committed = _commit(leases, prepared)
    acknowledged = _ack(leases, prepared, committed, A_FP)
    returned = leases.return_after_undo(
        tenant_id="tenant-a",
        site_id="site-a",
        adoption_id=prepared["adoption"]["adoptionId"],
        expected_adoption_revision=acknowledged["adoption"]["adoptionRevision"],
        expected_lease_revision=acknowledged["lease"]["leaseRevision"],
        owner_token=acknowledged["lease"]["ownerToken"],
    )
    assert returned["outcome"] == "returned_to_prior_owner"
    assert returned["lease"] == source


def test_read_only_eligibility_after_expiry_cannot_mutate_new_owner(tmp_path: Path) -> None:
    clock = _Clock()
    leases = FacilityDraftLeaseRepository(tmp_path, clock=clock, idle_seconds=10)
    old = leases.acquire(
        tenant_id="tenant-a",
        site_id="site-a",
        layout_id="fl-a",
        owner_kind="design_run",
        owner_run_id="fdlr-old",
        base_saved_layout_revision=BASE,
        current_draft_revision=DRAFT_A,
    )
    clock.advance(seconds=11)
    new = leases.acquire(
        tenant_id="tenant-a",
        site_id="site-a",
        layout_id="fl-a",
        owner_kind="manual_write",
        owner_run_id="manual-new",
        base_saved_layout_revision=BASE,
        current_draft_revision=DRAFT_B,
    )
    before = deepcopy(new)
    eligibility = leases.inspect("tenant-a", "site-a", "fl-a")
    after = leases.inspect("tenant-a", "site-a", "fl-a")["lease"]
    assert eligibility["lease"]["ownerRunId"] == "manual-new"
    assert after == before
    with pytest.raises(FacilityDraftLeaseConflictError):
        leases.release(
            tenant_id="tenant-a",
            site_id="site-a",
            layout_id="fl-a",
            owner_kind="design_run",
            owner_run_id="fdlr-old",
            owner_token=old["ownerToken"],
            expected_lease_revision=old["leaseRevision"],
            reason="local_undo",
        )
    assert leases.inspect("tenant-a", "site-a", "fl-a")["lease"] == before
