from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from pathlib import Path

import pytest

from ai_inspector.facility_layout.generation_run_repository import (
    FacilityGenerationRunConflictError,
    FacilityGenerationRunNotFoundError,
    FacilityGenerationRunRepository,
    FacilityGenerationRunRepositoryError,
)


BASE_REVISION = "0" * 64
INTENT_HASH = "1" * 64
DEPENDENCY_FINGERPRINT = "2" * 64


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 26, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def _create(
    repository: FacilityGenerationRunRepository,
    *,
    session_id: str = "session-a",
    writable: bool = True,
    layout_id: str = "fl-a",
    run_id: str | None = None,
) -> dict:
    return repository.create_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=layout_id,
        user_id="user-a",
        session_id=session_id,
        base_layout_revision=BASE_REVISION,
        effective_provider="anthropic",
        effective_model="claude-sonnet-4-5-20250929",
        reasoning_effort=None,
        intent_hash=INTENT_HASH,
        dependency_fingerprint=DEPENDENCY_FINGERPRINT,
        prototype_mode=True,
        writable=writable,
        run_id=run_id,
    )


def _concurrent_create_worker(
    root: str,
    session_id: str,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    repository = FacilityGenerationRunRepository(root, lock_timeout_seconds=3)
    start.wait(10)
    try:
        created = _create(repository, session_id=session_id, writable=True)
    except FacilityGenerationRunRepositoryError as exc:
        results.put(("error", exc.code))
    except Exception as exc:  # pragma: no cover - diagnostic for child failures
        results.put(("unexpected", type(exc).__name__, str(exc)))
    else:
        results.put(("success", created["run"]["runId"]))


def test_run_and_session_mapping_survive_repository_restart(tmp_path: Path) -> None:
    clock = _Clock()
    root = tmp_path / "facility"
    first = FacilityGenerationRunRepository(root, clock=clock)
    created = _create(first, run_id="fgr-restart")
    reopened = FacilityGenerationRunRepository(root, clock=clock)
    fetched = reopened.get_run("tenant-a", "site-a", "fgr-restart")
    resolved = reopened.resolve_session_run("tenant-a", "site-a", "session-a")
    assert fetched == created
    assert resolved == created
    assert created["run"]["writableLease"]["ownerToken"].startswith("lease-")


def test_only_one_writable_run_per_layout_but_read_only_runs_coexist(
    tmp_path: Path,
) -> None:
    repository = FacilityGenerationRunRepository(tmp_path / "facility")
    first = _create(repository, session_id="session-write", writable=True)
    with pytest.raises(FacilityGenerationRunConflictError) as exc:
        _create(repository, session_id="session-conflict", writable=True)
    assert exc.value.code == "generation_writable_lease_conflict"
    preview_a = _create(repository, session_id="session-preview-a", writable=False)
    preview_b = _create(repository, session_id="session-preview-b", writable=False)
    assert preview_a["run"]["layoutId"] == first["run"]["layoutId"]
    assert preview_b["run"]["layoutId"] == first["run"]["layoutId"]


def test_run_rejects_non_frozen_provider_configuration_before_writing(
    tmp_path: Path,
) -> None:
    repository = FacilityGenerationRunRepository(tmp_path / "facility")
    with pytest.raises(FacilityGenerationRunRepositoryError) as exc:
        repository.create_run(
            tenant_id="tenant-a",
            site_id="site-a",
            workspace_id="workspace-a",
            layout_id="fl-a",
            user_id="user-a",
            session_id="session-a",
            base_layout_revision=BASE_REVISION,
            effective_provider="anthropic",
            effective_model="claude-opus-5",
            reasoning_effort=None,
            intent_hash=INTENT_HASH,
            dependency_fingerprint=DEPENDENCY_FINGERPRINT,
            prototype_mode=True,
            writable=True,
            run_id="fgr-wrong-model",
        )
    assert exc.value.code == "facility_model_mismatch"
    assert not list((tmp_path / "facility").rglob("fgr-wrong-model.json"))


def test_update_uses_revision_compare_and_swap_and_lease_token(tmp_path: Path) -> None:
    repository = FacilityGenerationRunRepository(tmp_path / "facility")
    created = _create(repository, run_id="fgr-cas")
    candidate = deepcopy(created["run"])
    candidate["stageGraph"][0]["status"] = "running"
    token = candidate["writableLease"]["ownerToken"]
    updated = repository.update_run(
        candidate,
        expected_run_revision=created["runRevision"],
        lease_owner_token=token,
    )
    assert updated["run"]["stageGraph"][0]["status"] == "running"
    with pytest.raises(FacilityGenerationRunConflictError) as stale:
        repository.update_run(
            candidate,
            expected_run_revision=created["runRevision"],
            lease_owner_token=token,
        )
    assert stale.value.code == "generation_run_revision_conflict"
    next_candidate = deepcopy(updated["run"])
    with pytest.raises(FacilityGenerationRunConflictError) as lease:
        repository.update_run(
            next_candidate,
            expected_run_revision=updated["runRevision"],
            lease_owner_token="lease-wrong",
        )
    assert lease.value.code == "generation_writable_lease_conflict"


def test_competing_layout_revision_stales_run_and_invalidates_stages(
    tmp_path: Path,
) -> None:
    repository = FacilityGenerationRunRepository(tmp_path / "facility")
    created = _create(repository, run_id="fgr-stale")
    stale = repository.mark_stale_for_layout_revision(
        "tenant-a",
        "site-a",
        "fgr-stale",
        current_layout_revision="9" * 64,
    )
    assert stale["run"]["status"] == "stale"
    assert stale["run"]["writable"] is False
    assert stale["run"]["saveEligibility"] == "blocked"
    assert stale["run"]["invalidations"][0]["reason"] == "base_layout_revision_changed"
    assert stale["runRevision"] != created["runRevision"]


def test_explicit_save_receipt_is_revision_bound_and_retained(tmp_path: Path) -> None:
    clock = _Clock()
    repository = FacilityGenerationRunRepository(tmp_path / "facility", clock=clock)
    created = _create(repository, run_id="fgr-save")
    run = deepcopy(created["run"])
    token = run["writableLease"]["ownerToken"]
    for stage in run["stageGraph"]:
        stage["status"] = "complete"
        stage["validation"] = {"status": "valid", "findingIds": []}
    run["currentStageId"] = "review_and_save"
    run["receiptChain"] = ["receipt-a"]
    run["cumulativeDiffHash"] = "3" * 64
    run["saveEligibility"] = "eligible"
    run["cumulativeProposal"] = {
        "proposalId": "proposal-a",
        "runId": run["runId"],
        "baseLayoutRevision": run["baseLayoutRevision"],
        "draftLayoutRevision": "4" * 64,
        "receiptChain": ["receipt-a"],
        "dependencyFingerprint": run["dependencyFingerprint"],
        "cumulativeDiffHash": run["cumulativeDiffHash"],
        "validation": {"status": "valid", "findingIds": []},
        "saveEligibility": "eligible",
        "generatedAt": "2026-08-26T00:00:00.000000Z",
    }
    eligible = repository.update_run(
        run,
        expected_run_revision=created["runRevision"],
        lease_owner_token=token,
    )
    receipt = {
        "schemaVersion": 1,
        "saveReceiptId": "save-receipt-a",
        "runId": run["runId"],
        "tenantId": "tenant-a",
        "siteId": "site-a",
        "workspaceId": "workspace-a",
        "layoutId": "fl-a",
        "baseLayoutRevision": BASE_REVISION,
        "savedLayoutRevision": "5" * 64,
        "cumulativeDiffHash": "3" * 64,
        "dependencyFingerprint": DEPENDENCY_FINGERPRINT,
        "receiptChain": ["receipt-a"],
        "approvedBy": "user-a",
        "approvedAt": "2026-08-26T00:00:01.000000Z",
        "persistedAt": "2026-08-26T00:00:02.000000Z",
        "approvalSource": "explicit_user_command",
    }
    saved = repository.record_saved_receipt(
        receipt,
        expected_run_revision=eligible["runRevision"],
        lease_owner_token=token,
    )
    assert saved["run"]["status"] == "saved"
    assert saved["run"]["writable"] is False
    assert saved["run"]["saveEligibility"] == "saved"
    assert repository.resolve_session_run("tenant-a", "site-a", "session-a") is None
    retained = repository.get_saved_receipt(
        "tenant-a", "site-a", "fl-a", "5" * 64, "save-receipt-a"
    )
    assert retained["receipt"] == receipt


def test_idle_expiry_becomes_30_day_tombstone_then_is_collected(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    repository = FacilityGenerationRunRepository(tmp_path / "facility", clock=clock)
    _create(repository, run_id="fgr-expiry")
    clock.advance(hours=25)
    with pytest.raises(FacilityGenerationRunRepositoryError) as expired:
        repository.get_run("tenant-a", "site-a", "fgr-expiry")
    assert expired.value.code == "generation_run_expired"
    collected = repository.garbage_collect("tenant-a", "site-a")
    assert collected["tombstonedRuns"] == 1
    tombstone = repository.get_tombstone("tenant-a", "site-a", "fgr-expiry")
    assert tombstone["status"] == "expired"
    with pytest.raises(FacilityGenerationRunNotFoundError):
        repository.get_run("tenant-a", "site-a", "fgr-expiry")
    clock.advance(days=31)
    assert repository.garbage_collect("tenant-a", "site-a")["deletedTombstones"] == 1
    with pytest.raises(FacilityGenerationRunNotFoundError):
        repository.get_tombstone("tenant-a", "site-a", "fgr-expiry")


def test_bounded_orphan_lock_recovery(tmp_path: Path) -> None:
    repository = FacilityGenerationRunRepository(
        tmp_path / "facility",
        lock_stale_seconds=1,
    )
    lock_path = repository._lock_path("tenant-a", "site-a")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("orphan", encoding="ascii")
    os.utime(lock_path, (1, 1))
    created = _create(repository, run_id="fgr-orphan-recovery")
    assert created["run"]["runId"] == "fgr-orphan-recovery"
    assert not lock_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="KF1 production contention target is Windows")
def test_cross_process_single_writer_lease_is_synchronized(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    root = str(tmp_path / "facility")
    processes = [
        context.Process(
            target=_concurrent_create_worker,
            args=(root, f"session-{index}", start, results),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert sum(item[0] == "success" for item in outcomes) == 1
    assert outcomes.count(("error", "generation_writable_lease_conflict")) == 1


def test_generation_store_never_rewrites_existing_layout_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    saved_layout = workspace / "tenant-a" / "site-a" / "layouts" / "fl-a.json"
    saved_layout.parent.mkdir(parents=True)
    payload = b'{"recordKind":"existing_saved_layout","revision":"unchanged"}'
    saved_layout.write_bytes(payload)
    repository = FacilityGenerationRunRepository(workspace)
    _create(repository, run_id="fgr-layout-isolation")
    assert saved_layout.read_bytes() == payload
