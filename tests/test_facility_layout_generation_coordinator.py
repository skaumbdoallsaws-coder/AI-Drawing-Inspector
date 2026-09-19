from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.circulation import (
    analyze_primary_circulation_network,
    analyze_primary_circulation_obstacles,
    analyze_primary_circulation_conflicts,
)
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.generation_coordinator import (
    FacilityGenerationCoordinator,
    FacilityGenerationCoordinatorError,
    build_g1_facility_intent,
)
from ai_inspector.facility_layout.generation_run_repository import (
    FacilityGenerationRunRepository,
)
from ai_inspector.facility_layout.host import LOCAL_ASSET_CATALOG
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


def test_primary_circulation_amends_same_run_and_preserves_follow_up_identity(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    completed = started
    for _ in FACILITY_GENERATION_STAGES:
        completed = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    original_zone_bytes = repr(completed["draftLayout"]["zones"])
    original_diff_hash = completed["cumulativeProposal"]["cumulativeDiffHash"]

    routed = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=completed["draftLayoutRevision"],
        circulation_request={
            "action": "create",
            "route_kind": "material",
            "width": 6,
            "source_unit": "m",
            "source_department": "Receiving",
            "target_department": "Inspection",
            "via_departments": ["Machining", "Assembly"],
            "direction": "two_way",
            "label": None,
            "execution_mode": "authorized_draft_run",
        },
    )
    assert routed["status"] == "complete"
    assert routed["runId"] == started["runId"]
    assert routed["circulation"] == {
        "action": "create",
        "routeCount": 1,
        "saved": False,
        "areaAccounting": "overlay",
    }
    assert routed["cumulativeProposal"]["cumulativeDiffHash"] != original_diff_hash
    assert repr(routed["draftLayout"]["zones"]) == original_zone_bytes
    route = routed["draftLayout"]["routes"][0]
    route_id = route["routeId"]
    assert route["corridorWidth"] == 6.0
    assert next(
        stage
        for stage in routed["stageGraph"]
        if stage["stageId"] == "primary_circulation"
    )["status"] == "complete"

    narrowed = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=routed["draftLayoutRevision"],
        circulation_request={
            "action": "edit_recent",
            "route_kind": "material",
            "width": 5,
            "source_unit": "m",
            "source_department": None,
            "target_department": None,
            "via_departments": [],
            "direction": "two_way",
            "label": None,
            "execution_mode": "authorized_draft_run",
        },
    )
    edited_route = narrowed["draftLayout"]["routes"][0]
    assert edited_route["routeId"] == route_id
    assert edited_route["corridorWidth"] == 5.0
    assert edited_route["sourceEndpoint"] == route["sourceEndpoint"]
    assert edited_route["targetEndpoint"] == route["targetEndpoint"]
    assert narrowed["circulation"]["action"] == "edit_recent"
    assert len(narrowed["supersededReceiptIds"]) == 8


def test_g23_crossing_and_local_path_amendment_share_the_durable_run(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    labels = [
        "North West",
        "North Center",
        "North East",
        "Inbound",
        "Center",
        "Dispatch",
        "South West",
        "South Center",
        "South East",
    ]
    started = coordinator.start_g1_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=layout["layoutId"],
        user_id="user-a",
        session_id="session-g23",
        base_layout=layout,
        base_layout_revision=layout_revision(layout),
        envelope_request={
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "G2.3 Plant",
        },
        department_request={
            "count": len(labels),
            "labels": labels,
            "proportions": [1.0 / len(labels)] * len(labels),
            "arrangement": "row_stack",
            "orientation": "auto",
            "rows": [
                {"labels": labels[0:3], "proportion": None},
                {"labels": labels[3:6], "proportion": None},
                {"labels": labels[6:9], "proportion": None},
            ],
        },
        execution_mode="authorized_draft_run",
        prototype_mode=True,
    )
    current = started
    for _ in FACILITY_GENERATION_STAGES:
        current = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    for request in (
        {
            "action": "create",
            "route_kind": "material",
            "width": 4,
            "source_unit": "m",
            "source_department": "Inbound",
            "target_department": "Dispatch",
            "via_departments": [],
            "direction": "two_way",
            "label": "Main material aisle",
            "execution_mode": "authorized_draft_run",
        },
        {
            "action": "create",
            "route_kind": "pedestrian",
            "width": 2,
            "source_unit": "m",
            "source_department": "North Center",
            "target_department": "South Center",
            "via_departments": [],
            "direction": "two_way",
            "label": "Center walkway",
            "execution_mode": "authorized_draft_run",
        },
    ):
        current = coordinator.amend_primary_circulation(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_draft_revision=current["draftLayoutRevision"],
            circulation_request=request,
        )
    before_marking = deepcopy(current["draftLayout"])
    network = analyze_primary_circulation_network(before_marking)
    eligible = [
        item
        for item in network["crossings"]
        if item["intersectionType"] == "point"
        and item["mixedPedestrianMaterialTraffic"] is True
    ]
    assert len(eligible) == 1

    marked = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=current["draftLayoutRevision"],
        circulation_request={
            "action": "add_crossing",
            "network_scope": "route_network",
            "crossing_route_ids": eligible[0]["routeIds"],
            "crossing_width": 4,
            "crossing_depth": 3,
            "crossing_width_unit": "m",
            "crossing_depth_unit": "m",
            "preserve_departments": True,
            "preserve_routes": True,
            "execution_mode": "authorized_draft_run",
        },
    )
    assert marked["draftLayout"]["zones"] == before_marking["zones"]
    assert marked["draftLayout"]["routes"] == before_marking["routes"]
    assert len(marked["draftLayout"]["floorMarkings"]) == 1
    assert marked["circulation"]["crossingCreation"]["status"] == "marked"
    assert marked["circulation"]["networkAnalysis"][
        "unmarkedMixedTrafficPointCrossingCount"
    ] == 0
    original_route_ids = [
        route["routeId"] for route in marked["draftLayout"]["routes"]
    ]
    original_material_route = deepcopy(marked["draftLayout"]["routes"][0])

    rerouted = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=marked["draftLayoutRevision"],
        circulation_request={
            "action": "edit_recent",
            "route_kind": "pedestrian",
            "width": 2,
            "source_unit": "m",
            "source_department": "North Center",
            "target_department": "South Center",
            "via_departments": ["Center"],
            "direction": "two_way",
            "label": "Center walkway",
            "execution_mode": "authorized_draft_run",
        },
    )
    assert [
        route["routeId"] for route in rerouted["draftLayout"]["routes"]
    ] == original_route_ids
    assert rerouted["draftLayout"]["routes"][0] == original_material_route
    assert len(rerouted["draftLayout"]["floorMarkings"]) == 1
    assert analyze_primary_circulation_network(rerouted["draftLayout"])[
        "unmarkedMixedTrafficPointCrossingCount"
    ] == 0


def test_primary_circulation_conflicts_resolve_in_same_durable_run(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    completed = started
    for _ in FACILITY_GENERATION_STAGES:
        completed = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    current = completed
    for circulation in (
        {
            "action": "create",
            "route_kind": "forklift",
            "width": 5,
            "source_unit": "m",
            "source_department": "Receiving",
            "target_department": "Inspection",
            "via_departments": ["Machining", "Assembly"],
            "direction": "one_way",
            "label": None,
            "execution_mode": "authorized_draft_run",
        },
        {
            "action": "create",
            "route_kind": "pedestrian",
            "width": 2,
            "source_unit": "m",
            "source_department": "Machining",
            "target_department": "Assembly",
            "via_departments": [],
            "direction": "two_way",
            "label": None,
            "execution_mode": "authorized_draft_run",
        },
    ):
        current = coordinator.amend_primary_circulation(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_draft_revision=current["draftLayoutRevision"],
            circulation_request=circulation,
        )
    before = deepcopy(current["draftLayout"])
    assert analyze_primary_circulation_conflicts(before)[
        "mixedTrafficConflictCount"
    ] >= 1

    resolved = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=current["draftLayoutRevision"],
        circulation_request={
            "action": "resolve_conflicts",
            "route_kind": None,
            "width": None,
            "source_unit": None,
            "source_department": None,
            "target_department": None,
            "via_departments": [],
            "direction": None,
            "label": None,
            "conflict_scope": "mixed_traffic",
            "minimum_separation": 1.0,
            "separation_unit": "m",
            "preserve_departments": True,
            "adjust_route_kind": "auto_shortest",
            "execution_mode": "authorized_draft_run",
        },
    )

    assert resolved["status"] == "complete"
    assert resolved["runId"] == started["runId"]
    assert resolved["draftLayout"]["zones"] == before["zones"]
    assert [route["routeId"] for route in resolved["draftLayout"]["routes"]] == [
        route["routeId"] for route in before["routes"]
    ]
    assert [route["corridorWidth"] for route in resolved["draftLayout"]["routes"]] == [
        route["corridorWidth"] for route in before["routes"]
    ]
    resolution = resolved["circulation"]["conflictResolution"]
    assert resolution["status"] == "resolved"
    assert resolution["minimumSeparationMeters"] == 1.0
    assert resolution["separationAuthority"] == "user_authored"
    assert resolution["preservedDepartments"] is True
    assert resolution["adjustmentMode"] == "auto_shortest"
    assert resolution["selectedAlternativeId"] in {
        "reroute_pedestrian",
        "reroute_material",
    }
    assert len(resolution["alternatives"]) == 2
    assert resolved["circulation"]["conflictAnalysis"][
        "mixedTrafficConflictCount"
    ] == 0


def test_primary_circulation_obstacle_reroute_is_revision_bound_in_same_run(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    completed = started
    for _ in FACILITY_GENERATION_STAGES:
        completed = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    routed = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=completed["draftLayoutRevision"],
        circulation_request={
            "action": "create",
            "route_kind": "material",
            "width": 4,
            "source_unit": "m",
            "source_department": "Receiving",
            "target_department": "Inspection",
            "via_departments": [],
            "direction": "two_way",
            "label": None,
            "execution_mode": "authorized_draft_run",
        },
    )
    before = deepcopy(routed["draftLayout"])
    route = before["routes"][0]
    first, second = route["centerline"][:2]
    center_x = (float(first["x"]) + float(second["x"])) / 2.0
    center_z = (float(first["z"]) + float(second["z"])) / 2.0
    obstacle_context = {
        "schemaVersion": 1,
        "obstacles": [
            {
                "obstacleId": "placement:durable-machine",
                "obstacleKind": "placement_footprint",
                "boundary": [
                    {"x": center_x - 2, "z": center_z - 2},
                    {"x": center_x + 2, "z": center_z - 2},
                    {"x": center_x + 2, "z": center_z + 2},
                    {"x": center_x - 2, "z": center_z + 2},
                ],
                "evidenceStatus": "derived",
                "sourceRef": "durable-machine",
            }
        ],
        "sourceRevisions": {
            "layout": routed["draftLayoutRevision"],
            "asset:durable-machine": "9" * 64,
        },
    }
    assert analyze_primary_circulation_obstacles(
        before,
        obstacle_context,
    )["routeObstacleConflictCount"] == 1

    rerouted = coordinator.amend_primary_circulation(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=routed["draftLayoutRevision"],
        circulation_request={
            "action": "avoid_obstacles",
            "obstacle_scope": "static_geometry",
            "minimum_clearance": 1,
            "clearance_unit": "m",
            "preserve_departments": True,
            "preserve_route_identity": True,
            "route_id": route["routeId"],
            "vehicle_profile_id": None,
            "vehicle_profile_revision": None,
            "allow_reverse": None,
            "execution_mode": "authorized_draft_run",
        },
        obstacle_context=obstacle_context,
    )

    assert rerouted["status"] == "complete"
    assert rerouted["runId"] == started["runId"]
    assert rerouted["draftLayout"]["zones"] == before["zones"]
    assert rerouted["draftLayout"]["routes"][0]["routeId"] == route["routeId"]
    assert rerouted["draftLayout"]["routes"][0]["corridorWidth"] == 4.0
    obstacle = rerouted["circulation"]["obstacleAvoidance"]
    assert obstacle["status"] == "clear"
    assert obstacle["minimumClearanceMeters"] == 1.0
    assert obstacle["clearanceAuthority"] == "user_authored"
    assert obstacle["vehicleTurningValidated"] is False
    assert obstacle["preservedDepartments"] is True
    assert obstacle["preservedRouteIdentity"] is True


def test_g3_subdivision_amends_and_replaces_same_parent_without_geometry_drift(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    current = started
    for _ in FACILITY_GENERATION_STAGES:
        current = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    macro_before = {
        zone["zoneId"]: deepcopy(zone) for zone in current["draftLayout"]["zones"]
    }
    routed_collections_before = {
        field: deepcopy(current["draftLayout"].get(field, []))
        for field in (
            "routes",
            "floorMarkings",
            "placements",
            "utilityNetworks",
            "processBindings",
            "groups",
        )
    }

    subdivided = coordinator.amend_department_subdivisions(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=current["draftLayoutRevision"],
        subdivision_request={
            "parent_department": "Assembly",
            "count": 4,
            "labels": [
                "Kitting",
                "Mechanical Build",
                "Electrical Build",
                "Test",
            ],
            "proportions": None,
            "arrangement": "row_stack",
            "orientation": "auto",
            "rows": [
                {
                    "labels": ["Kitting", "Mechanical Build"],
                    "proportion": None,
                },
                {
                    "labels": ["Electrical Build", "Test"],
                    "proportion": None,
                },
            ],
            "preserve_parent": True,
            "execution_mode": "authorized_draft_run",
        },
    )
    assert subdivided["status"] == "complete"
    assert subdivided["subdivisions"]["action"] == "add"
    assert subdivided["subdivisions"]["childLabels"] == [
        "Kitting",
        "Mechanical Build",
        "Electrical Build",
        "Test",
    ]
    assert len(subdivided["draftLayout"]["zones"]) == 8
    by_id = {zone["zoneId"]: zone for zone in subdivided["draftLayout"]["zones"]}
    assert all(by_id[zone_id] == zone for zone_id, zone in macro_before.items())
    assert all(
        subdivided["draftLayout"].get(field, []) == value
        for field, value in routed_collections_before.items()
    )

    replaced = coordinator.amend_department_subdivisions(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=subdivided["draftLayoutRevision"],
        subdivision_request={
            "parent_department": "Assembly",
            "count": 2,
            "labels": ["Mechanical Build", "Electrical Build"],
            "proportions": [60, 40],
            "arrangement": "columns",
            "orientation": "auto",
            "rows": None,
            "preserve_parent": True,
            "execution_mode": "authorized_draft_run",
        },
    )
    assert replaced["subdivisions"]["action"] == "replace"
    assert len(replaced["draftLayout"]["zones"]) == 6
    assert replaced["subdivisions"]["childLabels"] == [
        "Mechanical Build",
        "Electrical Build",
    ]
    by_id = {zone["zoneId"]: zone for zone in replaced["draftLayout"]["zones"]}
    assert all(by_id[zone_id] == zone for zone_id, zone in macro_before.items())
    assert replaced["saveEligibility"] == "eligible"
    undone = coordinator.undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["restoredLayout"] == layout
    assert undone["restoredLayoutRevision"] == layout_revision(layout)


def test_g4_assets_append_to_g3_child_with_exact_revision_and_one_undo(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    current = started
    for _ in FACILITY_GENERATION_STAGES:
        current = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    subdivided = coordinator.amend_department_subdivisions(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=current["draftLayoutRevision"],
        subdivision_request={
            "parent_department": "Assembly",
            "count": 2,
            "labels": ["Mechanical Build", "Test"],
            "proportions": None,
            "arrangement": "columns",
            "orientation": "auto",
            "rows": None,
            "preserve_parent": True,
            "execution_mode": "authorized_draft_run",
        },
    )
    zones_before = deepcopy(subdivided["draftLayout"]["zones"])
    routes_before = deepcopy(subdivided["draftLayout"]["routes"])
    machine = next(
        item for item in LOCAL_ASSET_CATALOG
        if item["assetId"] == "asset-cnc-mill"
    )
    placed = coordinator.amend_asset_placements(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=subdivided["draftLayoutRevision"],
        asset_request={
            "asset_id": machine["assetId"],
            "asset_definition_revision": machine[
                "assetDefinitionRevision"
            ],
            "quantity": 2,
            "target_area": "Mechanical Build",
            "orientation_mode": "long_side_east_west",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
            "preserve_hierarchy": True,
            "execution_mode": "authorized_draft_run",
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    assert placed["status"] == "complete"
    assert placed["draftLayout"]["zones"] == zones_before
    assert placed["draftLayout"]["routes"] == routes_before
    assert placed["assetPlacements"]["quantity"] == 2
    assert placed["assetPlacements"]["accessValidatedCount"] == 0
    assert placed["assetPlacements"]["accessUnverifiedCount"] == 2
    generated = placed["draftLayout"]["placements"]
    assert len(generated) == 2
    assert all(item["assetId"] == machine["assetId"] for item in generated)
    assert all(
        item["assetDefinitionRevision"]
        == machine["assetDefinitionRevision"]
        for item in generated
    )
    assert all(
        item["metadata"]["targetArea"] == "Mechanical Build"
        and item["metadata"]["orientationMode"]
        == "long_side_east_west"
        and item["metadata"]["accessStatus"] == "unverified"
        for item in generated
    )
    with pytest.raises(FacilityGenerationCoordinatorError) as exc:
        coordinator.amend_asset_placements(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_draft_revision=placed["draftLayoutRevision"],
            asset_request={
                "asset_id": machine["assetId"],
                "asset_definition_revision": machine[
                    "assetDefinitionRevision"
                ],
                "quantity": 1,
                "target_area": "Test",
                "orientation_mode": "auto",
                "facing_direction": None,
                "resource_role": "inspection",
                "access_requirement": "registered_access_required",
                "preserve_hierarchy": True,
                "execution_mode": "authorized_draft_run",
            },
            asset_catalog=list(LOCAL_ASSET_CATALOG),
        )
    assert exc.value.code == "facility_asset_access_evidence_unavailable"
    preserved = coordinator.get_run("tenant-a", "site-a", started["runId"])
    assert preserved["status"] == "complete"
    assert preserved["draftLayoutRevision"] == placed["draftLayoutRevision"]
    assert preserved["draftLayout"]["placements"] == generated
    undone = coordinator.undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["restoredLayout"] == layout
    assert undone["restoredLayoutRevision"] == layout_revision(layout)


def test_g5_cell_composition_reflows_exact_g4_resources_in_same_durable_run(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    current = started
    for _ in FACILITY_GENERATION_STAGES:
        current = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    machine = next(
        item for item in LOCAL_ASSET_CATALOG
        if item["assetId"] == "asset-cnc-mill"
    )
    placed = coordinator.amend_asset_placements(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=current["draftLayoutRevision"],
        asset_request={
            "asset_id": machine["assetId"],
            "asset_definition_revision": machine[
                "assetDefinitionRevision"
            ],
            "quantity": 4,
            "target_area": "Assembly",
            "orientation_mode": "auto",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
            "preserve_hierarchy": True,
            "execution_mode": "authorized_draft_run",
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    zones_before = {
        zone["zoneId"]: deepcopy(zone["boundary"])
        for zone in placed["draftLayout"]["zones"]
    }
    routes_before = deepcopy(placed["draftLayout"]["routes"])
    markings_before = deepcopy(placed["draftLayout"]["floorMarkings"])
    placement_identity = {
        item["placementId"]: {
            "assetId": item["assetId"],
            "assetDefinitionRevision": item["assetDefinitionRevision"],
            "quaternion": deepcopy(item["transform"]["quaternion"]),
        }
        for item in placed["draftLayout"]["placements"]
    }

    composed = coordinator.amend_cell_composition(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=placed["draftLayoutRevision"],
        cell_request={
            "target_area": "Assembly",
            "candidate_strategies": ["line"],
            "selected_strategy": "line",
            "objective": "shortest_travel",
            "preferred_gap_meters": 1.0,
            "invert_u": False,
            "process_sequence_placement_ids": [],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )

    assert composed["status"] == "complete"
    assert composed["cellComposition"]["selectedStrategy"] == "line"
    assert composed["cellComposition"]["selectedStrategyLabel"] == (
        "Straight / I-line"
    )
    assert composed["cellComposition"]["preferredGapAuthority"] == (
        "user_authored"
    )
    assert composed["cellComposition"]["saved"] is False
    zones_after = {
        zone["zoneId"]: zone
        for zone in composed["draftLayout"]["zones"]
    }
    assert set(zones_after) == set(zones_before)
    assert all(
        zones_after[zone_id]["boundary"] == boundary
        for zone_id, boundary in zones_before.items()
    )
    assembly_zone = next(
        zone for zone in zones_after.values()
        if zone["label"] == "Assembly"
    )
    assert assembly_zone["extensions"]["cellGroup"]["groupKind"] == (
        "manufacturing_cell"
    )
    assert composed["draftLayout"]["routes"] == routes_before
    assert composed["draftLayout"]["floorMarkings"] == markings_before
    by_id = {
        item["placementId"]: item
        for item in composed["draftLayout"]["placements"]
    }
    assert set(by_id) == set(placement_identity)
    for placement_id, expected in placement_identity.items():
        actual = by_id[placement_id]
        assert actual["assetId"] == expected["assetId"]
        assert (
            actual["assetDefinitionRevision"]
            == expected["assetDefinitionRevision"]
        )
        assert actual["transform"]["quaternion"] == expected["quaternion"]
        assert actual["metadata"]["layoutProvenance"]["command"] == (
            "cell_layout"
        )
        assert actual["metadata"]["accessStatus"] == "unverified"
    seed_stage = next(
        stage for stage in composed["stageGraph"]
        if stage["stageId"] == "seed_cells"
    )
    assert seed_stage["status"] == "complete"
    assert composed["saveEligibility"] == "eligible"

    composed_before_rejection = deepcopy(composed["draftLayout"])
    composed_revision = composed["draftLayoutRevision"]
    with pytest.raises(FacilityGenerationCoordinatorError) as exc:
        coordinator.amend_cell_composition(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_draft_revision=composed_revision,
            cell_request={
                "target_area": "Assembly",
                "candidate_strategies": ["line"],
                "selected_strategy": "line",
                "objective": "shortest_travel",
                "preferred_gap_meters": 20.0,
                "invert_u": False,
                "process_sequence_placement_ids": [],
                "preserve_departments": True,
                "preserve_routes": True,
                "preserve_markings": True,
                "preserve_locked_and_manual": True,
                "execution_mode": "authorized_draft_run",
            },
            asset_catalog=list(LOCAL_ASSET_CATALOG),
        )
    assert exc.value.code in {
        "facility_cell_no_feasible_strategy",
        "facility_cell_selected_strategy_rejected",
    }
    preserved = coordinator.get_run("tenant-a", "site-a", started["runId"])
    assert preserved["draftLayoutRevision"] == composed_revision
    assert preserved["draftLayout"] == composed_before_rejection

    undone = coordinator.undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["restoredLayout"] == layout
    assert undone["restoredLayoutRevision"] == layout_revision(layout)


def test_g6_replicates_qualified_cell_in_same_durable_run(
    tmp_path: Path,
) -> None:
    layout = _layout()
    coordinator = _coordinator(tmp_path / "runs")
    started = _start(coordinator, layout)
    current = started
    for _ in FACILITY_GENERATION_STAGES:
        current = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    machine = next(
        item
        for item in LOCAL_ASSET_CATALOG
        if item["assetId"] == "asset-cnc-mill"
    )
    placed = coordinator.amend_asset_placements(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=current["draftLayoutRevision"],
        asset_request={
            "asset_id": machine["assetId"],
            "asset_definition_revision": machine[
                "assetDefinitionRevision"
            ],
            "quantity": 3,
            "target_area": "Assembly",
            "orientation_mode": "auto",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
            "preserve_hierarchy": True,
            "execution_mode": "authorized_draft_run",
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    composed = coordinator.amend_cell_composition(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=placed["draftLayoutRevision"],
        cell_request={
            "target_area": "Assembly",
            "candidate_strategies": ["line"],
            "selected_strategy": "line",
            "objective": "shortest_travel",
            "preferred_gap_meters": 1.0,
            "invert_u": False,
            "process_sequence_placement_ids": [],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    source_before = {
        item["placementId"]: deepcopy(item)
        for item in composed["draftLayout"]["placements"]
    }
    zone_boundaries = {
        item["zoneId"]: deepcopy(item["boundary"])
        for item in composed["draftLayout"]["zones"]
    }
    replicated = coordinator.amend_cell_replication(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
        expected_draft_revision=composed["draftLayoutRevision"],
        replication_request={
            "source_cell": "Assembly",
            "target_areas": ["Machining", "Inspection"],
            "copy_current_edited_state": False,
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_source_cell": True,
            "preserve_manual_and_locked": True,
            "execution_mode": "authorized_draft_run",
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    summary = replicated["cellReplication"]
    assert replicated["status"] == "complete"
    assert summary["replicaCount"] == 2
    assert summary["copiedPlacementCount"] == 6
    assert summary["authoredStrategy"] == "line"
    assert summary["validationStatus"] == "valid"
    assert summary["saved"] is False
    by_id = {
        item["placementId"]: item
        for item in replicated["draftLayout"]["placements"]
    }
    assert all(by_id[item] == value for item, value in source_before.items())
    assert {
        item["zoneId"]: item["boundary"]
        for item in replicated["draftLayout"]["zones"]
    } == zone_boundaries
    repeated_stage = next(
        item
        for item in replicated["stageGraph"]
        if item["stageId"] == "repeated_modules"
    )
    assert repeated_stage["status"] == "complete"
    assert replicated["saveEligibility"] == "eligible"
    assert replicated["supersededReceiptIds"]
    undone = coordinator.undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["restoredLayout"] == layout
    assert undone["restoredLayoutRevision"] == layout_revision(layout)


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


def test_oversized_stage_splits_into_restart_safe_bounded_substages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runs"
    layout = _layout()
    coordinator = _coordinator(root)
    started = _start(coordinator, layout)
    original_compile = FacilityGenerationCoordinator._compile_stage

    def compile_large_stage(self, stage_id, draft, intent, stage_inputs=None):
        if stage_id != "floor_communication":
            return original_compile(self, stage_id, draft, intent, stage_inputs)
        operations = [
            {"op": "rename_layout", "displayName": f"Large Factory {index:04d}"}
            for index in range(1, 1202)
        ]
        return {
            "stageId": stage_id,
            "selectedCommandIds": [],
            "operations": operations,
            "plannedInstanceCount": len(operations),
            "normalizedRequest": {"scope": "production_hardening_fixture"},
            "assumptions": [],
            "validationPlan": ["bounded_operation_substages"],
            "expectedSummary": {"saved": False},
        }

    monkeypatch.setattr(
        FacilityGenerationCoordinator, "_compile_stage", compile_large_stage
    )
    response = started
    while response["currentStageId"] != "floor_communication":
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )

    receipt_ids = []
    for expected_substage, expected_count in (
        ("floor_communication-01", 500),
        ("floor_communication-02", 500),
        ("floor_communication-03", 201),
    ):
        coordinator = _coordinator(root)
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
        receipt = response["stageReceipt"]
        receipt_ids.append(receipt["receiptId"])
        assert receipt["substageId"] == expected_substage
        assert receipt["operationCount"] == expected_count
        assert receipt["plannedInstanceCount"] == expected_count
        assert receipt["operationCount"] <= 500

    assert response["completedStageId"] == "floor_communication"
    assert response["currentStageId"] == "deterministic_validation"
    assert response["draftLayout"]["displayName"] == "Large Factory 1201"
    artifacts = coordinator.repository.get_execution_artifacts(
        "tenant-a", "site-a", started["runId"]
    )
    stage = next(
        item
        for item in artifacts["run"]["run"]["stageGraph"]
        if item["stageId"] == "floor_communication"
    )
    assert [item["operationCount"] for item in stage["substageGraph"]] == [
        500,
        500,
        201,
    ]
    assert all(item["status"] == "complete" for item in stage["substageGraph"])
    assert stage["operationReceiptIds"] == receipt_ids

    while response["currentStageId"]:
        coordinator = _coordinator(root)
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    assert response["status"] == "complete"
    assert response["saveEligibility"] == "eligible"
    assert response["cumulativeProposal"]["receiptChain"] == response[
        "receiptChain"
    ]
    assert len(response["receiptChain"]) == 12

    undone = coordinator.undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["restoredLayout"] == layout


def test_oversized_stage_failure_keeps_prior_checkpoint_and_blocks_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runs"
    layout = _layout()
    coordinator = _coordinator(root)
    started = _start(coordinator, layout)
    original_compile = FacilityGenerationCoordinator._compile_stage

    def compile_failing_stage(self, stage_id, draft, intent, stage_inputs=None):
        if stage_id != "floor_communication":
            return original_compile(self, stage_id, draft, intent, stage_inputs)
        operations = [
            {"op": "rename_layout", "displayName": f"Checkpoint {index:04d}"}
            for index in range(1, 1002)
        ]
        operations[500] = {"op": "unsupported_failure_injection"}
        return {
            "stageId": stage_id,
            "selectedCommandIds": [],
            "operations": operations,
            "plannedInstanceCount": len(operations),
            "normalizedRequest": {"scope": "production_hardening_fixture"},
            "assumptions": [],
            "validationPlan": ["bounded_operation_substages"],
            "expectedSummary": {"saved": False},
        }

    monkeypatch.setattr(
        FacilityGenerationCoordinator, "_compile_stage", compile_failing_stage
    )
    response = started
    while response["currentStageId"] != "floor_communication":
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
        )
    first = coordinator.continue_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
    )
    assert first["status"] == "active"
    assert first["draftLayout"]["displayName"] == "Checkpoint 0500"

    restarted = _coordinator(root)
    failed = restarted.continue_run(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=layout,
        current_base_revision=layout_revision(layout),
    )
    assert failed["status"] == "blocked"
    assert failed["saveEligibility"] == "blocked"
    assert failed["draftLayout"]["displayName"] == "Checkpoint 0500"
    assert failed["stageReceipt"]["substageId"] == "floor_communication-02"
    assert failed["stageReceipt"]["operationCount"] == 500
    assert failed["stageReceipt"]["status"] == "failed"
    assert failed["stageReceipt"]["validation"]["findingIds"] == [
        "unknown_facility_layout_operation"
    ]
    with pytest.raises(FacilityGenerationCoordinatorError) as exc:
        restarted.save_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=layout,
            current_base_revision=layout_revision(layout),
            expected_cumulative_diff_hash=None,
            explicit_approval=True,
            approved_by="user-a",
            persist=lambda document, revision: None,
        )
    assert exc.value.code == "generation_run_not_save_eligible"
