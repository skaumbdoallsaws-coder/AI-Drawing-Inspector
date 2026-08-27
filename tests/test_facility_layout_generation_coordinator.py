from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.generation_coordinator import (
    FacilityGenerationCoordinator,
    FacilityGenerationCoordinatorError,
    build_g1_facility_intent,
)
from ai_inspector.facility_layout.generation_run_repository import (
    FacilityGenerationRunRepository,
)
from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
    FacilityKnowledgeContractError,
)
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.provider_config import (
    FacilityProviderConfigurationError,
)


NOW = datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)


def _layout() -> dict:
    return create_layout_document(
        layout_id="fl-g1-coordinator",
        display_name="Empty Facility",
        association={"siteId": "site-a", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "origin-a",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-a",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-a",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-26T00:00:00Z",
    )


def _coordinator(
    root: Path,
    *,
    environ: dict[str, str] | None = None,
) -> FacilityGenerationCoordinator:
    source = environ if environ is not None else {}
    return FacilityGenerationCoordinator(
        FacilityGenerationRunRepository(root, clock=lambda: NOW),
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        environ_provider=lambda: source,
        clock=lambda: NOW,
    )


def _start(
    coordinator: FacilityGenerationCoordinator,
    layout: dict,
    *,
    execution_mode: str = "authorized_draft_run",
) -> dict:
    return coordinator.start_g1_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=layout["layoutId"],
        user_id="user-a",
        session_id=f"session-{execution_mode}",
        base_layout=layout,
        base_layout_revision=layout_revision(layout),
        envelope_request={
            "width": 300,
            "depth": 200,
            "sourceUnit": "ft",
            "displayName": "North Plant",
        },
        department_request={
            "count": 4,
            "labels": [
                "Receiving",
                "Machining",
                "Assembly",
                "Inspection",
            ],
            "proportions": [2, 3, 3, 2],
            "arrangement": "deterministic_grid",
            "orientation": "auto",
        },
        execution_mode=execution_mode,
        prototype_mode=True,
    )


def test_g1_intent_is_coordinate_free_and_requires_explicit_save() -> None:
    intent = build_g1_facility_intent(
        envelope_request={
            "width": 100,
            "depth": 80,
            "sourceUnit": "m",
            "displayName": "Intent Plant",
        },
        department_request={
            "count": 2,
            "labels": ["Receiving + Raw Material", "Assembly / Kitting"],
        },
    )
    assert intent["savePolicy"] == "explicit_user_command"
    assert intent["mode"] == "greenfield"
    assert intent["departments"][0]["semanticType"] == "receiving_raw_material"
    serialized = repr(intent)
    assert "worldX" not in serialized
    assert "vertices" not in serialized


def test_authorized_g1_run_resumes_through_exactly_ten_stages_and_saves(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    layout = _layout()
    coordinator = _coordinator(root)
    started = _start(coordinator, layout)
    assert started["currentStageId"] == "facility_envelope"
    assert started["receiptChain"] == []
    assert started["writable"] is True
    assert "ownerToken" not in repr(started)

    response = started
    for expected_stage in [item["stageId"] for item in FACILITY_GENERATION_STAGES]:
        # Reconstructing both objects proves restart-safe continuation state.
        coordinator = _coordinator(root)
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
        assert response["completedStageId"] == expected_stage

    assert response["status"] == "complete"
    assert response["currentStageId"] is None
    assert len(response["receiptChain"]) == 10
    assert response["saveEligibility"] == "eligible"
    assert response["cumulativeProposal"]["receiptChain"] == response["receiptChain"]
    assert response["draftLayout"]["displayName"] == "North Plant"
    assert len(response["draftLayout"]["zones"]) == 4
    assert response["draftLayout"]["routes"] == []
    assert response["draftLayout"]["placements"] == []
    cancelled = {
        stage["stageId"]
        for stage in response["stageGraph"]
        if stage["status"] == "cancelled"
    }
    assert cancelled == {
        "primary_circulation",
        "department_subdivisions",
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "floor_communication",
    }
    assert any(
        entry["path"] == "/zones"
        for entry in response["cumulativeDiff"]["entries"]
    )

    persisted: list[tuple[dict, str]] = []

    def persist(document: dict, base_revision: str) -> dict:
        persisted.append((deepcopy(document), base_revision))
        return {
            "layout": deepcopy(document),
            "revision": layout_revision(document),
            "changed": True,
        }

    saved = coordinator.save_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_cumulative_diff_hash=response["cumulativeProposal"][
            "cumulativeDiffHash"
        ],
        explicit_approval=True,
        approved_by="user-a",
        persist=persist,
    )
    assert len(persisted) == 1
    assert saved["run"]["status"] == "saved"
    assert saved["saveReceipt"]["approvalSource"] == "explicit_user_command"


def test_no_persistence_occurs_before_separate_explicit_save(tmp_path: Path) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    response = started
    for _ in FACILITY_GENERATION_STAGES:
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    calls = []
    with pytest.raises(FacilityGenerationCoordinatorError) as exc:
        coordinator.save_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_cumulative_diff_hash=response["cumulativeProposal"][
                "cumulativeDiffHash"
            ],
            explicit_approval=False,
            approved_by="user-a",
            persist=lambda document, revision: calls.append((document, revision)),
        )
    assert exc.value.code == "explicit_approval_required"
    assert calls == []


def test_stage_checkpoint_journal_recovers_after_process_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runs"
    layout = _layout()
    coordinator = _coordinator(root)
    started = _start(coordinator, layout)
    repository = coordinator.repository
    original_write = repository._atomic_write
    interrupted = False

    def interrupt_after_run_replace(path: Path, value: dict) -> None:
        nonlocal interrupted
        original_write(path, value)
        if (
            not interrupted
            and path.parent.name == "runs"
            and path.name == f"{started['runId']}.json"
        ):
            interrupted = True
            raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(repository, "_atomic_write", interrupt_after_run_replace)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )

    reopened = _coordinator(root)
    artifacts = reopened.repository.get_execution_artifacts(
        "tenant-a", "site-a", started["runId"]
    )
    receipt_id = artifacts["run"]["run"]["stageGraph"][0][
        "operationReceiptIds"
    ][0]
    assert artifacts["run"]["run"]["receiptChain"] == [receipt_id]
    assert artifacts["run"]["run"]["currentStageId"] == "macro_departments"
    receipt = reopened.repository.get_stage_receipt(
        "tenant-a", "site-a", started["runId"], receipt_id
    )
    assert artifacts["draft"]["draftLayoutRevision"] == receipt["receipt"][
        "resultDraftRevision"
    ]
    transaction = reopened.repository._checkpoint_transaction_path(
        "tenant-a", "site-a", started["runId"]
    )
    assert not transaction.exists()


def test_save_recovers_idempotently_after_layout_persisted_before_receipt(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    response = started
    for _ in FACILITY_GENERATION_STAGES:
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )

    persisted = {
        "layout": deepcopy(layout),
        "revision": layout_revision(layout),
    }

    def persist_then_interrupt(document: dict, base_revision: str) -> dict:
        assert base_revision == layout_revision(layout)
        persisted["layout"] = deepcopy(document)
        persisted["revision"] = layout_revision(document)
        raise RuntimeError("response lost after persistence")

    with pytest.raises(RuntimeError, match="response lost after persistence"):
        coordinator.save_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_cumulative_diff_hash=response["cumulativeProposal"][
                "cumulativeDiffHash"
            ],
            explicit_approval=True,
            approved_by="user-a",
            persist=persist_then_interrupt,
        )

    def unexpected_persist(document: dict, base_revision: str) -> dict:
        raise AssertionError("recovery must not persist the approved draft twice")

    reopened = _coordinator(tmp_path / "runs")
    recovered = reopened.save_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=persisted["layout"],
        current_base_revision=persisted["revision"],
        expected_cumulative_diff_hash=response["cumulativeProposal"][
            "cumulativeDiffHash"
        ],
        explicit_approval=True,
        approved_by="user-a",
        persist=unexpected_persist,
    )
    assert recovered["run"]["status"] == "saved"
    assert recovered["savedLayout"]["recovered"] is True

    replayed = reopened.save_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=persisted["layout"],
        current_base_revision=persisted["revision"],
        expected_cumulative_diff_hash=response["cumulativeProposal"][
            "cumulativeDiffHash"
        ],
        explicit_approval=True,
        approved_by="user-a",
        persist=unexpected_persist,
    )
    assert replayed["saveReceipt"] == recovered["saveReceipt"]


def test_preview_mode_has_no_writable_lease_and_cannot_save(tmp_path: Path) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout, execution_mode="preview_only")
    assert started["writable"] is False
    response = started
    for _ in FACILITY_GENERATION_STAGES:
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    assert response["status"] == "complete"
    assert response["saveEligibility"] == "blocked"


def test_guided_mode_requires_each_stage_acceptance(tmp_path: Path) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout, execution_mode="guided_draft")
    with pytest.raises(FacilityGenerationCoordinatorError) as exc:
        coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    assert exc.value.code == "generation_stage_approval_required"
    accepted = coordinator.continue_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        explicit_stage_acceptance=True,
    )
    assert accepted["completedStageId"] == "facility_envelope"


def test_provider_drift_fails_before_the_next_stage(tmp_path: Path) -> None:
    layout = _layout()
    environment: dict[str, str] = {}
    coordinator = _coordinator(tmp_path / "runs", environ=environment)
    started = _start(coordinator, layout)
    environment["INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL"] = (
        "claude-opus-5"
    )
    with pytest.raises(FacilityProviderConfigurationError) as exc:
        coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    assert exc.value.code == "facility_model_mismatch"
    fetched = coordinator.get_run("tenant-a", "site-a", started["runId"])
    assert fetched["receiptChain"] == []


def test_invalidation_supersedes_descendants_and_restores_prior_checkpoint(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    response = started
    for _ in range(4):
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    old_chain = list(response["receiptChain"])
    invalidated = coordinator.invalidate_from_stage(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        upstream_stage_id="macro_departments",
        reason="upstream_dependency_changed",
        dependency_fingerprint_after="d" * 64,
    )
    assert invalidated["currentStageId"] == "macro_departments"
    assert invalidated["receiptChain"] == old_chain[:1]
    assert invalidated["supersededReceiptIds"] == old_chain[1:]
    assert invalidated["draftLayout"]["zones"] == []
    assert "facilityPlan" in invalidated["draftLayout"]["extensions"]
    repository = coordinator.repository
    for receipt_id in old_chain[1:]:
        receipt = repository.get_stage_receipt(
            "tenant-a", "site-a", started["runId"], receipt_id
        )
        assert receipt["effectiveStatus"] == "superseded"
    rerun = coordinator.continue_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
    )
    assert rerun["completedStageId"] == "macro_departments"
    assert rerun["receiptChain"][1] not in old_chain


def test_undo_restores_exact_empty_base_and_cancels_run(tmp_path: Path) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    for _ in range(2):
        coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    undone = coordinator.undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["run"]["status"] == "cancelled"
    assert undone["restoredLayout"] == layout
    assert undone["restoredLayoutRevision"] == layout_revision(layout)
    assert len(undone["supersededReceiptIds"]) == 2


def test_complete_g1_request_replaces_nonempty_layout_in_unsaved_draft(
    tmp_path: Path,
) -> None:
    layout = _layout()
    layout["zones"].append(
        {
            "zoneId": "zn-existing-zone",
            "zoneType": "workcell",
            "label": "Existing",
            "boundary": [
                {"x": 0, "z": 0},
                {"x": 1, "z": 0},
                {"x": 1, "z": 1},
                {"x": 0, "z": 1},
            ],
            "floorElevation": 0,
            "anchors": [],
            "evidence": [],
            "extensions": {},
        }
    )
    saved_base = deepcopy(layout)
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)

    assert started["intentMode"] == "brownfield"
    assert layout == saved_base

    envelope = coordinator.continue_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
    )
    assert envelope["completedStageId"] == "facility_envelope"
    assert envelope["stageReceipt"]["selectedCommandIds"] == ["clear-all"]
    assert envelope["draftLayout"]["zones"] == []
    assert layout == saved_base

    departments = coordinator.continue_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
    )
    assert [zone["label"] for zone in departments["draftLayout"]["zones"]] == [
        "Receiving",
        "Machining",
        "Assembly",
        "Inspection",
    ]
    assert all(
        zone["zoneId"] != "zn-existing-zone"
        for zone in departments["draftLayout"]["zones"]
    )
    assert layout == saved_base


def test_coordinate_bearing_intent_is_rejected() -> None:
    with pytest.raises(FacilityKnowledgeContractError):
        build_g1_facility_intent(
            envelope_request={
                "width": 100,
                "depth": 80,
                "sourceUnit": "m",
                "displayName": "Unsafe Intent",
                "x": 20,
            },
            department_request={"count": 2},
        )
