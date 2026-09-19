from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.facility_program import (
    canonicalize_facility_program,
    facility_program_from_full_factory,
)
from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
    canonical_facility_knowledge_bytes,
)
from ai_inspector.facility_layout.generation_coordinator import (
    FacilityGenerationCoordinator,
)
from ai_inspector.facility_layout.generation_run_repository import (
    FacilityGenerationRunRepository,
)
from ai_inspector.facility_layout.host import (
    LOCAL_ASSET_CATALOG,
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.program_execution import (
    FACILITY_PROGRAM_WORKFLOW_SCOPE,
    FacilityProgramExecutionError,
    amend_facility_program_resource_batch,
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
    validate_facility_program_operation_plan,
)


def _request() -> dict:
    return {
        "facility_envelope": {
            "width": 90,
            "depth": 45,
            "source_unit": "m",
            "display_name": "Program Factory",
            "grid_size": 1,
        },
        "departments": {
            "count": 3,
            "labels": ["Cell A", "Cell B", "Shipping"],
            "proportions": None,
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [
                {"labels": ["Cell A", "Cell B", "Shipping"], "proportion": None}
            ],
        },
        "circulation": {"routes": [], "crossings": []},
        "subdivisions": [],
        "asset_placements": [
            {
                "asset_name": "Assembly Workbench",
                "quantity": 4,
                "target_area": "Cell A",
                "orientation_mode": "long_side_east_west",
                "facing_direction": None,
                "resource_role": "production",
                "access_requirement": "physical_only",
            }
        ],
        "seed_cell": {
            "target_area": "Cell A",
            "candidate_strategies": ["line", "l", "u"],
            "selected_strategy": None,
            "objective": "smallest_envelope",
            "preferred_gap_meters": 1.5,
            "invert_u": False,
        },
        "cell_replication": {
            "source_cell": "Cell A",
            "target_areas": ["Cell B"],
            "copy_current_edited_state": False,
        },
        "execution_mode": "authorized_draft_run",
    }


def _base() -> dict:
    return create_layout_document(
        layout_id="fl-program-execution",
        display_name="Blank Facility",
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
        policy_set_ref={"policySetId": "policy-a", "policySetRevision": "c" * 64},
        created_at="2026-08-29T17:00:00Z",
    )


def test_coordinate_free_program_builds_patterns_and_multiple_module_stages() -> None:
    program = facility_program_from_full_factory(_request(), list(LOCAL_ASSET_CATALOG))
    assert program["resource_batches"][0]["placement_pattern"] == "assembly_bench_rows"

    base = _base()
    plan = compile_facility_program_operation_plan(
        program, base, list(LOCAL_ASSET_CATALOG)
    )
    result = execute_facility_program_operation_plan(base, plan)

    assert result["status"] == "complete"
    assert result["saved"] is False
    assert result["undoLayout"] == base
    assert result["counts"] == {
        "zones": 3,
        "routes": 0,
        "placements": 8,
        "floorMarkings": 0,
    }
    generated = result["draftLayout"]["placements"]
    assert sum(
        item.get("metadata", {}).get("generatedBy")
        == "facility_industrial_patterns_rq3"
        for item in generated
    ) == 4
    assert sum(
        item.get("metadata", {}).get("generatedBy")
        == "facility_cell_replication_g6"
        for item in generated
    ) == 4
    assert result["authority"]["production_eligible"] is False


def test_spatial_failure_preserves_bounded_entity_and_batch_feedback(monkeypatch) -> None:
    # Fault injection tests the error contract, not physical collision detection.
    import ai_inspector.facility_layout.program_execution as execution
    program = facility_program_from_full_factory(_request(), list(LOCAL_ASSET_CATALOG))
    original = execution.diagnose_layout
    observed = {}
    def failure(layout, *args, **kwargs):
        result = original(layout, *args, **kwargs)
        placements = [item for item in layout["placements"] if item.get("metadata", {}).get("batchId")]
        ids = [item["placementId"] for item in placements[:2]]
        observed["batchIds"] = sorted({item["metadata"]["batchId"] for item in placements[:2]})
        result["findings"].append({"code": "placement_collision", "severity": "error", "subjectRefs": ids,
                                   "details": {"placementIds": ids}})
        return result
    monkeypatch.setattr(execution, "diagnose_layout", failure)
    with pytest.raises(FacilityProgramExecutionError) as error:
        compile_facility_program_operation_plan(program, _base(), list(LOCAL_ASSET_CATALOG))
    assert error.value.code == "facility_program_spatial_validation_failed"
    assert error.value.details["affectedBatchIds"] == observed["batchIds"]
    assert error.value.details["findings"][0]["subjectRefs"]
    assert "authoredSpacing" in error.value.details["repairParameters"]


def test_resource_batch_amendment_is_local_unsaved_and_exactly_undoable() -> None:
    request = _request()
    request["asset_placements"][0].update(
        {
            "asset_name": "Pallet Rack",
            "quantity": 1,
            "orientation_mode": "long_side_north_south",
            "resource_role": "storage",
        }
    )
    request["seed_cell"] = None
    request["cell_replication"] = None
    program = facility_program_from_full_factory(
        request, list(LOCAL_ASSET_CATALOG)
    )
    batch = program["resource_batches"][0]
    base = _base()
    built = execute_facility_program_operation_plan(
        base,
        compile_facility_program_operation_plan(
            program, base, list(LOCAL_ASSET_CATALOG)
        ),
    )
    current = built["draftLayout"]

    amended = amend_facility_program_resource_batch(
        current,
        program,
        list(LOCAL_ASSET_CATALOG),
        batch_id=batch["batch_id"],
        patch={"semantic_orientation": "long_side_east_west"},
    )

    assert amended["status"] == "complete"
    assert amended["saved"] is False
    assert amended["removedPlacementCount"] == 1
    assert amended["placedPlacementCount"] == 1
    assert amended["validation"]["status"] == "valid"
    assert amended["undoLayout"] == current
    assert len(amended["draftLayout"]["placements"]) == 1
    assert amended["draftLayout"]["placements"] != current["placements"]
    for collection in ("zones", "routes", "floorMarkings"):
        assert canonical_facility_knowledge_bytes(
            amended["draftLayout"][collection]
        ) == canonical_facility_knowledge_bytes(current[collection])


def test_resource_batch_amendment_fails_closed_when_a_recipe_depends_on_it() -> None:
    program = facility_program_from_full_factory(
        _request(), list(LOCAL_ASSET_CATALOG)
    )
    base = _base()
    built = execute_facility_program_operation_plan(
        base,
        compile_facility_program_operation_plan(
            program, base, list(LOCAL_ASSET_CATALOG)
        ),
    )
    batch = program["resource_batches"][0]

    with pytest.raises(FacilityProgramExecutionError) as exc:
        amend_facility_program_resource_batch(
            built["draftLayout"],
            program,
            list(LOCAL_ASSET_CATALOG),
            batch_id=batch["batch_id"],
            patch={"quantity": 3},
        )

    assert exc.value.code == "facility_program_local_amendment_has_dependents"


def _multi_family_request() -> dict:
    request = _request()
    request["departments"] = {
        "count": 6,
        "labels": ["Bench A", "Bench B", "Bench C", "Rack A", "Rack B", "Rack C"],
        "proportions": None,
        "arrangement": "row_stack",
        "orientation": "horizontal",
        "rows": [
            {"labels": ["Bench A", "Bench B", "Bench C"], "proportion": None},
            {"labels": ["Rack A", "Rack B", "Rack C"], "proportion": None},
        ],
    }
    request["asset_placements"] = [
        {
            "asset_name": "Assembly Workbench",
            "quantity": 4,
            "target_area": "Bench A",
            "orientation_mode": "long_side_east_west",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
        },
        {
            "asset_name": "Pallet Rack",
            "quantity": 4,
            "target_area": "Rack A",
            "orientation_mode": "long_side_east_west",
            "facing_direction": None,
            "resource_role": "storage",
            "access_requirement": "physical_only",
        },
    ]
    request["seed_cell"]["target_area"] = "Bench A"
    request["cell_replication"] = {
        "source_cell": "Bench A",
        "target_areas": ["Bench B", "Bench C"],
        "copy_current_edited_state": False,
    }
    return request


def _multi_family_program() -> dict:
    program = facility_program_from_full_factory(
        _multi_family_request(), list(LOCAL_ASSET_CATALOG)
    )
    rack_batch = next(
        item for item in program["resource_batches"] if item["target_area"] == "Rack A"
    )
    program["cell_recipes"].append(
        {
            "recipe_id": "recipe-002",
            "target_area": "Rack A",
            "member_batches": [rack_batch["batch_id"]],
            "candidate_strategies": ["line", "l", "u"],
            "selected_strategy_or_objective": "smallest_envelope",
            "authored_spacing": {
                "value": 1.5,
                "unit": "m",
                "evidence_ref": "user-authored-rack-gap",
            },
            "process_order": [],
            "interfaces": [],
            "evidence_refs": [],
        }
    )
    program["module_families"].append(
        {
            "family_id": "family-002",
            "source_recipe_or_cell": "recipe-002",
            "target_areas": ["Rack B", "Rack C"],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": [],
        }
    )
    return canonicalize_facility_program(program)


def test_multiple_families_execute_in_stable_order_and_localize_changes() -> None:
    base = _base()
    program = _multi_family_program()
    first_plan = compile_facility_program_operation_plan(
        program, base, list(LOCAL_ASSET_CATALOG)
    )
    first = execute_facility_program_operation_plan(base, first_plan)["draftLayout"]
    assert len(first["placements"]) == 24

    changed_program = _multi_family_program()
    family = next(
        item for item in changed_program["module_families"] if item["family_id"] == "family-002"
    )
    family["target_areas"] = ["Rack B"]
    changed_program = canonicalize_facility_program(changed_program)
    second_plan = compile_facility_program_operation_plan(
        changed_program, base, list(LOCAL_ASSET_CATALOG)
    )
    second = execute_facility_program_operation_plan(base, second_plan)["draftLayout"]
    assert len(second["placements"]) == 20

    def bench_family(layout: dict) -> bytes:
        values = [
            item
            for item in layout["placements"]
            if item.get("metadata", {}).get("targetArea") in {"Bench B", "Bench C"}
        ]
        return canonical_facility_knowledge_bytes(values)

    assert bench_family(first) == bench_family(second)


def test_local_routes_and_markings_preserve_primary_route_bytes() -> None:
    base = _base()
    primary = {
        "route_kind": "material",
        "width": 4,
        "source_unit": "m",
        "source_department": "Cell A",
        "target_department": "Shipping",
        "via_departments": [],
        "direction": "two_way",
        "label": "Primary Material Spine",
    }
    local = {
        "route_id": "local-personnel-link",
        "route_kind": "pedestrian",
        "width": 2,
        "source_unit": "m",
        "source_area": "Cell B",
        "target_area": "Shipping",
        "via_areas": [],
        "direction": "two_way",
        "label": "Local Personnel Link",
        "clearance": None,
        "vehicle_profile_ref": None,
        "evidence_refs": ["user-authored-local-route"],
    }
    primary_only = facility_program_from_full_factory(
        _request(), list(LOCAL_ASSET_CATALOG)
    )
    primary_only["route_network"]["primary_routes"] = [primary]
    primary_only = canonicalize_facility_program(primary_only)
    primary_result = execute_facility_program_operation_plan(
        base,
        compile_facility_program_operation_plan(
            primary_only, base, list(LOCAL_ASSET_CATALOG)
        ),
    )["draftLayout"]

    complete = facility_program_from_full_factory(
        _request(), list(LOCAL_ASSET_CATALOG)
    )
    complete["route_network"] = {
        "primary_routes": [primary],
        "local_routes": [local],
    }
    complete["floor_communication"] = [
        {
            "communication_id": "local-direction-arrows",
            "marking_type": "direction_arrow",
            "label": "Personnel Direction",
            "anchor_relationship": {
                "kind": "route",
                "target_area": None,
                "route_label": "Local Personnel Link",
                "placement_id": None,
            },
            "count": 2,
            "rows": 1,
            "columns": 2,
            "pitch": {"along": 3, "across": 2},
            "semantic_orientation": "route_aligned",
            "width": 1,
            "depth": 0.5,
            "source_unit": "m",
            "dimension_evidence_refs": ["user-authored-marking-dimensions"],
        }
    ]
    complete = canonicalize_facility_program(complete)
    complete_result = execute_facility_program_operation_plan(
        base,
        compile_facility_program_operation_plan(
            complete, base, list(LOCAL_ASSET_CATALOG)
        ),
    )["draftLayout"]

    primary_before = next(
        item for item in primary_result["routes"] if item["label"] == primary["label"]
    )
    primary_after = next(
        item for item in complete_result["routes"] if item["label"] == primary["label"]
    )
    assert canonical_facility_knowledge_bytes(primary_after) == canonical_facility_knowledge_bytes(
        primary_before
    )
    assert len(complete_result["routes"]) == 2
    assert len(complete_result["floorMarkings"]) == 2


def test_operation_plan_revision_and_batch_dependencies_fail_closed() -> None:
    plan = compile_facility_program_operation_plan(
        _multi_family_program(), _base(), list(LOCAL_ASSET_CATALOG)
    )
    assert validate_facility_program_operation_plan(plan) == plan

    tampered = {**plan, "expectedDraftRevision": "0" * 64}
    with pytest.raises(FacilityProgramExecutionError) as exc:
        validate_facility_program_operation_plan(tampered)
    assert exc.value.code == "facility_program_operation_plan_revision_mismatch"


def test_facility_program_runs_through_durable_receipts_without_saving(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)
    repository = FacilityGenerationRunRepository(
        tmp_path / "facility-program-runs", clock=lambda: now
    )
    coordinator = FacilityGenerationCoordinator(
        repository,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        environ_provider=lambda: {},
        clock=lambda: now,
    )
    base = _base()
    program = _multi_family_program()
    started = coordinator.start_facility_program_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=base["layoutId"],
        user_id="user-a",
        session_id="session-program",
        base_layout=base,
        base_layout_revision=layout_revision(base),
        facility_program=program,
        asset_catalog=list(LOCAL_ASSET_CATALOG),
        prototype_mode=True,
    )

    assert started["workflowScope"] == FACILITY_PROGRAM_WORKFLOW_SCOPE
    assert started["facilityProgramRevision"]
    artifact = repository.get_facility_program_artifact(
        "tenant-a", "site-a", started["runId"]
    )
    assert artifact["program"] == program
    assert artifact["operationPlan"]["expectedCounts"]["placements"] == 24

    response = started
    for expected_stage in FACILITY_GENERATION_STAGES:
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=base,
            current_base_revision=layout_revision(base),
        )
        assert response["completedStageId"] == expected_stage["stageId"]

    assert response["status"] == "complete"
    assert response["saveEligibility"] == "eligible"
    assert len(response["draftLayout"]["placements"]) == 24
    assert layout_revision(base) == started["baseLayoutRevision"]
    validation_stage = next(
        item
        for item in response["stageGraph"]
        if item["stageId"] == "deterministic_validation"
    )
    assert validation_stage["validation"]["checks"]["facilityProgram"][
        "status"
    ] == "valid"

    undone = coordinator.undo_to_base(
        tenant_id="tenant-a", site_id="site-a", run_id=started["runId"]
    )
    assert undone["restoredLayout"] == base


def test_durable_facility_program_chains_local_resource_amendments(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 29, 18, 15, tzinfo=timezone.utc)
    repository = FacilityGenerationRunRepository(
        tmp_path / "facility-program-amendment-runs", clock=lambda: now
    )
    coordinator = FacilityGenerationCoordinator(
        repository,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        environ_provider=lambda: {},
        clock=lambda: now,
    )
    request = _request()
    request["asset_placements"][0].update(
        {
            "asset_name": "Pallet Rack",
            "quantity": 1,
            "orientation_mode": "long_side_north_south",
            "resource_role": "storage",
        }
    )
    request["seed_cell"] = None
    request["cell_replication"] = None
    program = facility_program_from_full_factory(
        request, list(LOCAL_ASSET_CATALOG)
    )
    batch_id = program["resource_batches"][0]["batch_id"]
    base = _base()
    started = coordinator.start_facility_program_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=base["layoutId"],
        user_id="user-a",
        session_id="session-program-amendment",
        base_layout=base,
        base_layout_revision=layout_revision(base),
        facility_program=program,
        asset_catalog=list(LOCAL_ASSET_CATALOG),
        prototype_mode=True,
    )
    run = started
    for _ in FACILITY_GENERATION_STAGES:
        run = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=base,
            current_base_revision=layout_revision(base),
        )
    initial_receipt_count = len(run["receiptChain"])
    initial_zones = canonical_facility_knowledge_bytes(
        run["draftLayout"]["zones"]
    )

    first = coordinator.amend_facility_program_resource_batch(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=base,
        current_base_revision=layout_revision(base),
        expected_draft_revision=run["draftLayoutRevision"],
        resource_batch_id=batch_id,
        patch={"semantic_orientation": "long_side_east_west"},
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    assert first["status"] == "complete"
    assert first["saveEligibility"] == "eligible"
    assert first["facilityProgramAmendmentCount"] == 1
    assert len(first["receiptChain"]) == initial_receipt_count + 1
    assert first["facilityProgramAmendment"]["saved"] is False
    assert canonical_facility_knowledge_bytes(
        first["draftLayout"]["zones"]
    ) == initial_zones

    second = coordinator.amend_facility_program_resource_batch(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
        current_base_layout=base,
        current_base_revision=layout_revision(base),
        expected_draft_revision=first["draftLayoutRevision"],
        resource_batch_id=batch_id,
        patch={
            "authored_spacing": {
                "value": 1,
                "unit": "m",
                "evidence_ref": "user-authored-test-spacing",
            }
        },
        asset_catalog=list(LOCAL_ASSET_CATALOG),
    )
    assert second["facilityProgramAmendmentCount"] == 2
    assert second["facilityProgramAmendment"]["placedPlacementCount"] == 1
    assert len(second["receiptChain"]) == initial_receipt_count + 2
    effective = repository.get_effective_facility_program(
        "tenant-a", "site-a", started["runId"]
    )
    effective_batch = next(
        item
        for item in effective["program"]["resource_batches"]
        if item["batch_id"] == batch_id
    )
    assert effective_batch["quantity"] == 1
    assert effective_batch["semantic_orientation"] == "long_side_east_west"
    assert effective_batch["authored_spacing"]["value"] == 1.0
    assert [
        item["sequence"] for item in effective["amendments"]
    ] == [1, 2]

    undone = coordinator.undo_to_base(
        tenant_id="tenant-a", site_id="site-a", run_id=started["runId"]
    )
    assert undone["restoredLayout"] == base


def test_durable_facility_program_validates_multi_route_stage_by_checkpoint(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 29, 18, 30, tzinfo=timezone.utc)
    repository = FacilityGenerationRunRepository(
        tmp_path / "facility-program-route-runs", clock=lambda: now
    )
    coordinator = FacilityGenerationCoordinator(
        repository,
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        environ_provider=lambda: {},
        clock=lambda: now,
    )
    base = _base()
    program = facility_program_from_full_factory(
        _request(), list(LOCAL_ASSET_CATALOG)
    )
    program["route_network"]["primary_routes"] = [
        {
            "route_kind": "material",
            "width": 3,
            "source_unit": "m",
            "source_department": "Cell A",
            "target_department": "Shipping",
            "via_departments": ["Cell B"],
            "direction": "two_way",
            "label": "Program Material Route",
        }
    ]
    program = canonicalize_facility_program(program)
    started = coordinator.start_facility_program_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=base["layoutId"],
        user_id="user-a",
        session_id="session-program-route",
        base_layout=base,
        base_layout_revision=layout_revision(base),
        facility_program=program,
        asset_catalog=list(LOCAL_ASSET_CATALOG),
        prototype_mode=True,
    )

    response = started
    for expected_stage in FACILITY_GENERATION_STAGES:
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=base,
            current_base_revision=layout_revision(base),
        )
        assert response["completedStageId"] == expected_stage["stageId"]
        completed = next(
            item
            for item in response["stageGraph"]
            if item["stageId"] == expected_stage["stageId"]
        )
        assert completed["validation"]["checks"]["facilityProgramStage"][
            "status"
        ] == "valid"

    assert response["status"] == "complete"
    assert len(response["draftLayout"]["routes"]) == 1


def test_facility_program_http_path_preserves_saved_layout_until_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    host = LocalFacilityLayoutHost(
        tmp_path / "facility-program-host",
        private_assets=False,
    )
    app = FastAPI()
    app.include_router(host.create_router())
    client = TestClient(app)
    headers = {"X-InspectorPro-Session": "facility-program-http"}
    try:
        baseline = client.get("/api/facility-layout-bootstrap").json()["layout"]
        request = _request()
        request["asset_placements"][0].update(
            {
                "asset_name": "Pallet Rack",
                "quantity": 1,
                "orientation_mode": "long_side_north_south",
                "resource_role": "storage",
            }
        )
        request["seed_cell"] = None
        request["cell_replication"] = None
        program = facility_program_from_full_factory(
            request, list(LOCAL_ASSET_CATALOG)
        )
        resource_batch_id = program["resource_batches"][0]["batch_id"]
        started = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/"
            "facility-program",
            headers=headers,
            json={
                "prototypeMode": True,
                "supersedeActiveDraft": True,
                "workspaceId": "workspace-facility-layout",
                "facilityProgram": program,
            },
        )
        assert started.status_code == 200, started.text
        run = started.json()
        for _ in FACILITY_GENERATION_STAGES:
            response = client.post(
                f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/"
                f"runs/{run['runId']}/continue",
                headers=headers,
                json={},
            )
            assert response.status_code == 200, response.text
            run = response.json()
        assert run["status"] == "complete"
        assert run["workflowScope"] == FACILITY_PROGRAM_WORKFLOW_SCOPE
        persisted = client.get("/api/facility-layout-bootstrap").json()["layout"]
        assert persisted == baseline

        amended = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/"
            f"runs/{run['runId']}/facility-program/resource-batch",
            headers=headers,
            json={
                "prototypeMode": True,
                "expectedDraftRevision": run["draftLayoutRevision"],
                "resourceBatchId": resource_batch_id,
                "patch": {
                    "semantic_orientation": "long_side_east_west"
                },
            },
        )
        assert amended.status_code == 200, amended.text
        run = amended.json()
        assert run["facilityProgramAmendmentCount"] == 1
        assert run["facilityProgramAmendment"]["saved"] is False
        persisted = client.get("/api/facility-layout-bootstrap").json()["layout"]
        assert persisted == baseline

        undone = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/"
            f"runs/{run['runId']}/undo",
            headers=headers,
            json={},
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["restoredLayout"] == baseline["layout"]
    finally:
        client.close()
