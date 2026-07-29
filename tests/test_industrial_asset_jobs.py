from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.industrial_assets.jobs import (
    IndustrialAssetIntakeJobStore,
    IndustrialAssetJobConflictError,
    IndustrialAssetJobCorruptionError,
    IndustrialAssetJobStateError,
    IndustrialAssetJobValidationError,
)
from ai_inspector.industrial_assets.schema_v1 import canonical_json_bytes


SOURCE_FINGERPRINT = hashlib.sha256(b"fixture-source").hexdigest()
DEFINITION_REVISION = hashlib.sha256(b"definition").hexdigest()
RENDER_REVISION = hashlib.sha256(b"render").hexdigest()


class FixtureClock:
    def __init__(self):
        self.value = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def _request(**overrides):
    request = {
        "tenantId": "tenant-fixture",
        "requestedBy": "user-fixture",
        "sourceFingerprint": SOURCE_FINGERPRINT,
        "requestedRoot": "Cell/Robot.SLDASM",
        "configuration": "Default",
        "extractionInputs": {
            "extractor": "standalone",
            "extractorVersion": "p2-fixture",
        },
    }
    request.update(overrides)
    return request


def _store(tmp_path, *, stages=("discover", "extract", "validate"), **kwargs):
    return IndustrialAssetIntakeJobStore(
        tmp_path / "intake-store",
        stages=stages,
        clock=kwargs.pop("clock", FixtureClock()),
        **kwargs,
    )


def _create(store, key="fixture-intake-key-0001", **request_overrides):
    return store.create_job(
        _request(**request_overrides),
        idempotency_key=key,
    )


def _write_stage_output(store, job_id, relative_path, payload=b"artifact"):
    target = store.staging_directory(job_id) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def _complete_all_stages(store, job):
    current = store.start_job(job["jobId"])
    for stage in current["stagePlan"]:
        relative = f"{stage}/output.bin"
        _write_stage_output(
            store,
            job["jobId"],
            relative,
            payload=stage.encode("ascii"),
        )
        current = store.checkpoint_stage(
            job["jobId"],
            stage,
            output_paths=[relative],
            metadata={"stage": stage},
        )
    return current


def test_create_persists_canonical_job_with_bounded_safe_paths(tmp_path):
    store = _store(tmp_path)
    job = _create(store)

    assert job["jobId"].startswith("iaj-")
    assert len(job["jobId"]) == 28
    assert job["status"] == "pending"
    assert job["currentStage"] == "discover"
    assert job["stagingPath"] == f"staging/{job['jobId']}"
    assert job["createdAt"] == "2026-07-28T12:00:00.000000Z"
    assert "fixture-intake-key-0001" not in json.dumps(job)

    path = store.root / "jobs" / f"{job['jobId']}.json"
    raw = path.read_bytes()
    parsed = json.loads(raw.decode("ascii"))
    assert raw == canonical_json_bytes(parsed)
    assert not tuple(path.parent.glob("*.tmp"))
    assert store.staging_directory(job["jobId"]).is_dir()


def test_exact_idempotent_request_returns_same_job(tmp_path):
    store = _store(tmp_path)
    first = _create(store)
    second = _create(store)

    assert second == first
    assert len(store.list_jobs()) == 1


def test_changed_request_with_same_idempotency_key_fails_closed(tmp_path):
    store = _store(tmp_path)
    _create(store)

    with pytest.raises(IndustrialAssetJobConflictError) as error:
        _create(store, configuration="Alternate")

    assert error.value.code == "intake_idempotency_conflict"
    assert len(store.list_jobs()) == 1


@pytest.mark.parametrize(
    "key",
    ("short", "../escape-key", "spaces are rejected"),
)
def test_idempotency_key_is_bounded_and_path_safe(tmp_path, key):
    store = _store(tmp_path)
    with pytest.raises(IndustrialAssetJobValidationError):
        _create(store, key=key)
    assert store.list_jobs() == []


def test_request_rejects_absolute_or_traversing_requested_root(tmp_path):
    store = _store(tmp_path)
    for index, requested_root in enumerate(
        ("C:\\private\\Machine.SLDASM", "../Machine.SLDASM")
    ):
        with pytest.raises(IndustrialAssetJobValidationError) as error:
            _create(
                store,
                key=f"fixture-unsafe-root-{index:04d}",
                requestedRoot=requested_root,
            )
        assert error.value.code == "invalid_intake_request"


def test_request_rejects_nested_protected_filesystem_paths(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(IndustrialAssetJobValidationError) as error:
        _create(
            store,
            key="fixture-protected-path-0001",
            extractionInputs={
                "extractor": {
                    "sourcePath": "C:\\private\\Machine.SLDASM",
                }
            },
        )
    assert error.value.code == "invalid_intake_request"
    assert store.list_jobs() == []


def test_stage_checkpoints_are_ordered_hashed_and_idempotent(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    running = store.start_job(job["jobId"])
    assert running["attempts"] == 1

    _write_stage_output(store, job["jobId"], "discover/result.json", b"{}")
    with pytest.raises(IndustrialAssetJobStateError) as out_of_order:
        store.checkpoint_stage(job["jobId"], "extract")
    assert out_of_order.value.code == "intake_stage_out_of_order"

    checkpointed = store.checkpoint_stage(
        job["jobId"],
        "discover",
        output_paths=["discover/result.json"],
        metadata={"recordCount": 1},
    )
    output = checkpointed["stageCheckpoints"]["discover"]["outputs"][0]
    assert output == {
        "relativePath": "discover/result.json",
        "byteLength": 2,
        "sha256": hashlib.sha256(b"{}").hexdigest(),
    }
    assert checkpointed["currentStage"] == "extract"

    repeated = store.checkpoint_stage(
        job["jobId"],
        "discover",
        output_paths=["discover/result.json"],
        metadata={"recordCount": 1},
    )
    assert repeated == checkpointed

    with pytest.raises(IndustrialAssetJobConflictError):
        store.checkpoint_stage(
            job["jobId"],
            "discover",
            output_paths=["discover/result.json"],
            metadata={"recordCount": 2},
        )


def test_restart_recovery_resumes_from_first_incomplete_checkpoint(tmp_path):
    clock = FixtureClock()
    first = _store(tmp_path, clock=clock)
    job = _create(first)
    first.start_job(job["jobId"])
    _write_stage_output(first, job["jobId"], "discover/result.json", b"valid")
    first.checkpoint_stage(
        job["jobId"],
        "discover",
        output_paths=["discover/result.json"],
    )
    partial = _write_stage_output(
        first,
        job["jobId"],
        "extract/partial.glb",
        b"partial-not-checkpointed",
    )

    restarted = _store(tmp_path, clock=clock)
    recovered = restarted.recover()
    current = next(item for item in recovered if item["jobId"] == job["jobId"])

    assert current["status"] == "pending"
    assert current["currentStage"] == "extract"
    assert current["recoveryCount"] == 1
    assert not partial.exists()
    assert (
        restarted.staging_directory(job["jobId"])
        / "discover"
        / "result.json"
    ).read_bytes() == b"valid"

    resumed = restarted.start_job(job["jobId"])
    assert resumed["status"] == "running"
    assert resumed["attempts"] == 2
    assert resumed["currentStage"] == "extract"


def test_default_stage_plan_survives_canonical_key_sorting(tmp_path):
    clock = FixtureClock()
    store = IndustrialAssetIntakeJobStore(
        tmp_path / "default-stage-store",
        clock=clock,
    )
    job = _create(store, key="fixture-default-stages-0001")
    store.start_job(job["jobId"])
    first_two = job["stagePlan"][:2]
    for stage in first_two:
        relative = f"{stage}/output.bin"
        _write_stage_output(store, job["jobId"], relative, stage.encode("ascii"))
        store.checkpoint_stage(
            job["jobId"],
            stage,
            output_paths=[relative],
        )

    restarted = IndustrialAssetIntakeJobStore(
        store.root,
        clock=clock,
    )
    loaded = restarted.get_job(job["jobId"])
    assert set(loaded["stageCheckpoints"]) == set(first_two)
    assert loaded["currentStage"] == job["stagePlan"][2]


def test_recovery_quarantines_tampered_checkpoint_output(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    store.start_job(job["jobId"])
    output = _write_stage_output(
        store,
        job["jobId"],
        "discover/result.json",
        b"original",
    )
    store.checkpoint_stage(
        job["jobId"],
        "discover",
        output_paths=["discover/result.json"],
    )
    output.write_bytes(b"tampered")

    recovered = store.recover()
    current = next(item for item in recovered if item["jobId"] == job["jobId"])

    assert current["status"] == "quarantined"
    assert current["failure"]["code"] == "checkpoint_artifact_invalid"
    assert not store.staging_directory(job["jobId"], create=False).exists()
    assert (store.root / "quarantine" / job["jobId"]).is_dir()
    assert store.recover()[0] == current


def test_recovery_quarantines_tampered_completed_output(tmp_path):
    store = _store(tmp_path, stages=("validate",))
    job = _create(store, key="fixture-completed-tamper-0001")
    store.start_job(job["jobId"])
    output = _write_stage_output(
        store,
        job["jobId"],
        "validate/candidate.json",
        b"valid-candidate",
    )
    store.checkpoint_stage(
        job["jobId"],
        "validate",
        output_paths=["validate/candidate.json"],
    )
    store.complete_job(
        job["jobId"],
        candidate_asset_id="asset-completed-fixture",
        candidate_definition_revision=DEFINITION_REVISION,
        candidate_render_bundle_revision=RENDER_REVISION,
    )
    output.write_bytes(b"tampered-candidate")

    current = store.recover()[0]
    assert current["status"] == "quarantined"
    assert current["completedAt"] is None
    with pytest.raises(IndustrialAssetJobStateError):
        store.get_publication_candidate(job["jobId"])


def test_pending_cancellation_cleans_staging_and_stops_work(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    artifact = _write_stage_output(
        store,
        job["jobId"],
        "discover/partial.json",
        b"partial",
    )

    cancelled = store.cancel_job(job["jobId"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["completedAt"] is not None
    assert cancelled["cancellation"]["retainedArtifacts"] == []
    assert not artifact.exists()
    with pytest.raises(IndustrialAssetJobStateError):
        store.start_job(job["jobId"])


def test_running_cancellation_can_retain_a_hashed_staging_inventory(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    store.start_job(job["jobId"])
    _write_stage_output(
        store,
        job["jobId"],
        "extract/partial.glb",
        b"partial",
    )

    requested = store.request_cancellation(
        job["jobId"],
        retain_staged_artifacts=True,
    )
    assert requested["status"] == "cancel_requested"
    with pytest.raises(IndustrialAssetJobStateError):
        store.checkpoint_stage(job["jobId"], "discover")

    cancelled = store.acknowledge_cancellation(job["jobId"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation"]["retainedArtifacts"] == [
        {
            "relativePath": "extract/partial.glb",
            "byteLength": 7,
            "sha256": hashlib.sha256(b"partial").hexdigest(),
        }
    ]
    assert store.staging_directory(job["jobId"]).is_dir()


def test_restart_completes_pending_cancellation_without_running_work(tmp_path):
    clock = FixtureClock()
    first = _store(tmp_path, clock=clock)
    job = _create(first)
    first.start_job(job["jobId"])
    first.request_cancellation(job["jobId"])

    restarted = _store(tmp_path, clock=clock)
    recovered = restarted.recover()
    current = next(item for item in recovered if item["jobId"] == job["jobId"])

    assert current["status"] == "cancelled"
    assert current["completedAt"] is not None
    assert not restarted.staging_directory(job["jobId"], create=False).exists()


def test_recovery_accepts_cancelled_job_with_intentionally_cleaned_staging(tmp_path):
    store = _store(tmp_path)
    job = _create(store, key="fixture-cancelled-recovery-0001")
    store.start_job(job["jobId"])
    _write_stage_output(store, job["jobId"], "discover/result.json", b"valid")
    store.checkpoint_stage(
        job["jobId"],
        "discover",
        output_paths=["discover/result.json"],
    )
    store.cancel_job(job["jobId"])

    recovered = store.recover()
    assert recovered[0]["status"] == "cancelled"
    assert not (store.root / "quarantine" / job["jobId"]).exists()


def test_partial_job_never_exposes_a_publication_candidate(tmp_path):
    store = _store(tmp_path)
    job = _create(store)

    with pytest.raises(IndustrialAssetJobStateError) as error:
        store.get_publication_candidate(job["jobId"])

    assert error.value.code == "intake_candidate_not_ready"
    assert not (store.root / "registry").exists()
    assert not (store.root / "published").exists()


def test_complete_requires_every_checkpoint_and_returns_validated_candidate(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    store.start_job(job["jobId"])

    with pytest.raises(IndustrialAssetJobStateError) as incomplete:
        store.complete_job(
            job["jobId"],
            candidate_asset_id="asset-fixture",
            candidate_definition_revision=DEFINITION_REVISION,
            candidate_render_bundle_revision=RENDER_REVISION,
        )
    assert incomplete.value.code == "intake_stages_incomplete"

    _complete_all_stages(_store(tmp_path), job)
    completed = store.complete_job(
        job["jobId"],
        candidate_asset_id="asset-fixture",
        candidate_definition_revision=DEFINITION_REVISION,
        candidate_render_bundle_revision=RENDER_REVISION,
    )
    assert completed["status"] == "completed"
    assert completed["currentStage"] is None

    candidate = store.get_publication_candidate(job["jobId"])
    assert candidate["candidateAssetId"] == "asset-fixture"
    assert candidate["candidateDefinitionRevision"] == DEFINITION_REVISION
    assert candidate["candidateRenderBundleRevision"] == RENDER_REVISION
    assert len(candidate["checkpointFingerprint"]) == 64
    assert len(candidate["artifactInventory"]) == len(
        completed["stagePlan"]
    )
    selected = candidate["artifactInventory"][0]
    resolved = store.resolve_checkpointed_artifacts(
        job["jobId"],
        {selected["sha256"]: selected["byteLength"]},
    )
    assert list(resolved) == [selected["sha256"]]
    assert resolved[selected["sha256"]].is_file()
    with pytest.raises(IndustrialAssetJobValidationError) as missing:
        store.resolve_checkpointed_artifacts(
            job["jobId"],
            {"f" * 64: 12},
        )
    assert missing.value.code == "publication_artifact_missing"
    assert not (store.root / "registry").exists()


def test_transient_failures_are_resumable_with_bounded_attempts(tmp_path):
    store = _store(tmp_path, maximum_attempts=2)
    job = _create(store)
    store.start_job(job["jobId"])
    failed = store.fail_job(
        job["jobId"],
        code="extractor_busy",
        message="The extractor is temporarily busy.",
        transient=True,
    )
    assert failed["status"] == "failed"

    resumed = store.resume_job(job["jobId"])
    assert resumed["status"] == "running"
    assert resumed["attempts"] == 2
    store.fail_job(
        job["jobId"],
        code="extractor_busy",
        message="The extractor remains busy.",
        transient=True,
    )
    with pytest.raises(IndustrialAssetJobStateError) as exhausted:
        store.resume_job(job["jobId"])
    assert exhausted.value.code == "intake_job_attempts_exhausted"


def test_nontransient_failure_cannot_resume(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    failed = store.fail_job(
        job["jobId"],
        code="dependency_ambiguous",
        message="Dependency resolution is ambiguous.",
        transient=False,
    )
    assert failed["status"] == "failed"
    with pytest.raises(IndustrialAssetJobStateError) as error:
        store.resume_job(job["jobId"])
    assert error.value.code == "intake_job_not_resumable"


def test_active_staging_cannot_be_cleaned(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    with pytest.raises(IndustrialAssetJobStateError) as error:
        store.cleanup_staging(job["jobId"])
    assert error.value.code == "intake_staging_still_active"


def test_completed_staging_cannot_be_cleaned_before_publication(tmp_path):
    store = _store(tmp_path, stages=("validate",))
    job = _create(store, key="fixture-completed-cleanup-0001")
    store.start_job(job["jobId"])
    _write_stage_output(store, job["jobId"], "validate/result.json", b"{}")
    store.checkpoint_stage(
        job["jobId"],
        "validate",
        output_paths=["validate/result.json"],
    )
    store.complete_job(
        job["jobId"],
        candidate_asset_id="asset-cleanup-fixture",
        candidate_definition_revision=DEFINITION_REVISION,
        candidate_render_bundle_revision=RENDER_REVISION,
    )

    with pytest.raises(IndustrialAssetJobStateError) as error:
        store.cleanup_staging(job["jobId"])
    assert error.value.code == "intake_staging_still_active"


def test_abandoned_staging_is_quarantined_on_recovery(tmp_path):
    store = _store(tmp_path)
    abandoned = store.root / "staging" / "iaj-aaaaaaaaaaaaaaaaaaaaaaaa"
    abandoned.mkdir()
    (abandoned / "partial.bin").write_bytes(b"partial")

    assert store.recover() == []
    assert not abandoned.exists()
    quarantine = list((store.root / "quarantine").glob("abandoned-*"))
    assert len(quarantine) == 1
    assert (quarantine[0] / "partial.bin").read_bytes() == b"partial"


def test_corrupt_noncanonical_and_unsupported_records_fail_closed(tmp_path):
    store = _store(tmp_path)
    job = _create(store)
    path = store.root / "jobs" / f"{job['jobId']}.json"

    parsed = json.loads(path.read_text("ascii"))
    path.write_text(json.dumps(parsed), encoding="ascii")
    with pytest.raises(IndustrialAssetJobCorruptionError) as noncanonical:
        store.get_job(job["jobId"])
    assert noncanonical.value.code == "corrupt_intake_job"

    parsed["schemaVersion"] = 999
    path.write_bytes(canonical_json_bytes(parsed))
    with pytest.raises(IndustrialAssetJobCorruptionError) as unsupported:
        store.recover()
    assert unsupported.value.code == "unsupported_intake_job_schema"


def test_job_filename_mismatch_and_unknown_job_file_fail_closed(tmp_path):
    store = _store(tmp_path)
    (store.root / "jobs" / "unexpected.json").write_bytes(
        canonical_json_bytes({"schemaVersion": 1})
    )

    with pytest.raises(IndustrialAssetJobCorruptionError) as error:
        store.list_jobs()

    assert error.value.code == "unsupported_intake_job_file"


def test_store_root_and_stage_plan_are_bounded(tmp_path):
    with pytest.raises(IndustrialAssetJobValidationError):
        IndustrialAssetIntakeJobStore(
            "relative/jobs",
            stages=("discover",),
        )
    with pytest.raises(IndustrialAssetJobValidationError):
        IndustrialAssetIntakeJobStore(
            tmp_path / "jobs",
            stages=("duplicate", "duplicate"),
        )
