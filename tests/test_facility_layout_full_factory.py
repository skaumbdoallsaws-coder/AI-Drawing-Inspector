from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from ai_inspector.facility_layout.full_factory import (
    FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY,
    FULL_FACTORY_SCOPE,
    FacilityFullFactoryError,
    canonicalize_full_factory_request,
    compile_full_factory_program,
    full_factory_tool_spec,
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
from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
)
from ai_inspector.facility_layout.operations import create_layout_document


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _layout() -> dict:
    return create_layout_document(
        layout_id="fl-full-factory",
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
        policy_set_ref={
            "policySetId": "policy-a",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-28T00:00:00Z",
    )


def _coordinator(root: Path) -> FacilityGenerationCoordinator:
    return FacilityGenerationCoordinator(
        FacilityGenerationRunRepository(root, clock=lambda: NOW),
        feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
        environ_provider=lambda: {},
        clock=lambda: NOW,
    )


def _program() -> dict:
    labels = [
        "North West",
        "North Center",
        "North East",
        "Inbound",
        "Restricted Area",
        "Dispatch",
        "South West",
        "South Center",
        "South East",
    ]
    return {
        "facility_envelope": {
            "width": 120,
            "depth": 90,
            "source_unit": "m",
            "display_name": "FLI-026 Factory",
            "grid_size": 1,
        },
        "departments": {
            "count": 9,
            "labels": labels,
            "proportions": None,
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [
                {
                    "labels": ["North West", "North Center", "North East"],
                    "proportion": None,
                },
                {
                    "labels": ["Inbound", "Restricted Area", "Dispatch"],
                    "proportion": None,
                },
                {
                    "labels": ["South West", "South Center", "South East"],
                    "proportion": None,
                },
            ],
        },
        "circulation": {
            "routes": [
                {
                    "route_kind": "material",
                    "width": 4,
                    "source_unit": "m",
                    "source_department": "Inbound",
                    "target_department": "Dispatch",
                    "via_departments": [],
                    "direction": "two_way",
                    "label": "Inbound to Dispatch material aisle",
                },
                {
                    "route_kind": "pedestrian",
                    "width": 2,
                    "source_unit": "m",
                    "source_department": "North Center",
                    "target_department": "South Center",
                    "via_departments": [],
                    "direction": "two_way",
                    "label": "North to South pedestrian aisle",
                },
            ],
            "crossings": [
                {
                    "route_labels": [
                        "Inbound to Dispatch material aisle",
                        "North to South pedestrian aisle",
                    ],
                    "width": 4,
                    "depth": 3,
                    "source_unit": "m",
                    "label": "Central pedestrian crossing",
                }
            ],
        },
        "subdivisions": [
            {
                "parent_department": "South East",
                "count": 3,
                "labels": ["Kitting", "Electrical Build", "Test"],
                "proportions": None,
                "arrangement": "row_stack",
                "orientation": "horizontal",
                "rows": [
                    {
                        "labels": ["Kitting", "Electrical Build", "Test"],
                        "proportion": None,
                    }
                ],
            }
        ],
        "asset_placements": [
            {
                "asset_name": "Assembly Workbench",
                "quantity": 2,
                "target_area": "Electrical Build",
                "orientation_mode": "long_side_east_west",
                "facing_direction": None,
                "resource_role": "production",
                "access_requirement": "physical_only",
            }
        ],
        "seed_cell": {
            "target_area": "Electrical Build",
            "candidate_strategies": ["line", "l", "u"],
            "selected_strategy": None,
            "objective": "smallest_envelope",
            "preferred_gap_meters": 1,
            "invert_u": False,
        },
        "cell_replication": {
            "source_cell": "Electrical Build",
            "target_areas": ["Kitting", "Test"],
            "copy_current_edited_state": False,
        },
        "execution_mode": "authorized_draft_run",
    }


def _multi_family_program() -> dict:
    program = _program()
    program["asset_placements"] = [
        {
            "asset_name": "Assembly Workbench",
            "quantity": 2,
            "target_area": "Electrical Build",
            "orientation_mode": "long_side_east_west",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
        },
        {
            "asset_name": "Assembly Workbench",
            "quantity": 2,
            "target_area": "South West",
            "orientation_mode": "long_side_east_west",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
        },
    ]
    program["seed_cell"] = None
    program["cell_replication"] = None
    program["cell_recipes"] = [
        {
            "target_area": "Electrical Build",
            "candidate_strategies": ["line", "l", "u"],
            "selected_strategy": "line",
            "objective": "smallest_envelope",
            "preferred_gap_meters": 1,
            "invert_u": False,
        },
        {
            "target_area": "South West",
            "candidate_strategies": ["line", "l", "u"],
            "selected_strategy": "line",
            "objective": "smallest_envelope",
            "preferred_gap_meters": 1,
            "invert_u": False,
        },
    ]
    program["module_families"] = [
        {
            "source_cell": "Electrical Build",
            "target_areas": ["Kitting"],
            "copy_current_edited_state": False,
        },
        {
            "source_cell": "South West",
            "target_areas": ["South Center"],
            "copy_current_edited_state": False,
        },
    ]
    return program


def test_full_factory_contract_rejects_geometry_and_unresolved_assets() -> None:
    program = _program()
    program["asset_placements"][0]["x"] = 10
    with pytest.raises(FacilityFullFactoryError) as exc:
        canonicalize_full_factory_request(program)
    assert exc.value.code == "full_factory_model_geometry_or_unknown_field"

    program = _program()
    program["asset_placements"][0]["asset_name"] = "Some Workbench"
    with pytest.raises(FacilityFullFactoryError) as exc:
        compile_full_factory_program(program, list(LOCAL_ASSET_CATALOG))
    assert exc.value.code == "full_factory_asset_name_unresolved"


def test_full_factory_tool_contract_exposes_multiple_recipe_families() -> None:
    schema = full_factory_tool_spec()["input_schema"]

    assert schema["properties"]["cell_recipes"]["maxItems"] == 24
    assert schema["properties"]["module_families"]["maxItems"] == 24
    assert schema["properties"]["cell_recipes"]["items"][
        "additionalProperties"
    ] is False
    assert schema["properties"]["module_families"]["items"][
        "additionalProperties"
    ] is False
    assert {"seed_cell", "cell_replication"} <= set(schema["required"])


@pytest.mark.parametrize(
    ("quantity", "accepted"),
    [(899, True), (900, True), (901, False)],
)
def test_full_factory_asset_budget_boundary(quantity: int, accepted: bool) -> None:
    program = _program()
    template = program["asset_placements"][0]
    remaining = quantity
    requests = []
    while remaining:
        batch_quantity = min(50, remaining)
        requests.append({**template, "quantity": batch_quantity})
        remaining -= batch_quantity
    program["asset_placements"] = requests

    if accepted:
        canonical = canonicalize_full_factory_request(program)
        assert sum(item["quantity"] for item in canonical["asset_placements"]) == quantity
        assert quantity <= FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY
    else:
        with pytest.raises(FacilityFullFactoryError) as exc:
            canonicalize_full_factory_request(program)
        assert exc.value.code == "full_factory_program_budget_exceeded"


def test_full_factory_normalizes_equivalent_explicit_row_encoding() -> None:
    program = _program()
    program["subdivisions"][0]["arrangement"] = "rows"
    program["subdivisions"][0]["proportions"] = []

    canonical = canonicalize_full_factory_request(program)

    subdivision = canonical["subdivisions"][0]
    assert subdivision["arrangement"] == "row_stack"
    assert subdivision["proportions"] == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    assert subdivision["rows"] == [
        {
            "labels": ["Kitting", "Electrical Build", "Test"],
            "proportion": 1.0,
        }
    ]


def test_full_factory_run_resumes_g1_through_g6_as_one_unsaved_draft(
    tmp_path: Path,
) -> None:
    root = tmp_path / "full-factory-runs"
    base = _layout()
    started = _coordinator(root).start_full_factory_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=base["layoutId"],
        user_id="user-a",
        session_id="session-full-factory",
        base_layout=base,
        base_layout_revision=layout_revision(base),
        full_factory_request=_program(),
        asset_catalog=list(LOCAL_ASSET_CATALOG),
        prototype_mode=True,
    )
    assert started["workflowScope"] == FULL_FACTORY_SCOPE
    assert started["fullFactoryProgramRevision"]
    assert started["currentStageId"] == "facility_envelope"
    assert started["receiptChain"] == []

    response = started
    for expected in FACILITY_GENERATION_STAGES:
        coordinator = _coordinator(root)
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=base,
            current_base_revision=layout_revision(base),
        )
        assert response["completedStageId"] == expected["stageId"]

    assert response["status"] == "complete"
    assert response["saveEligibility"] == "eligible"
    assert len(response["receiptChain"]) == 10
    assert response["draftLayout"]["displayName"] == "FLI-026 Factory"
    assert len(response["departmentLabels"]) == 9
    assert len(response["draftLayout"]["zones"]) == 12
    assert len(response["draftLayout"]["routes"]) == 2
    assert len(response["draftLayout"]["floorMarkings"]) == 1
    assert len(response["draftLayout"]["placements"]) == 6
    assert all(
        stage["status"] in {"complete", "cancelled"}
        for stage in response["stageGraph"]
    )
    assert {
        stage["stageId"]
        for stage in response["stageGraph"]
        if stage["status"] == "complete"
    } >= {
        "facility_envelope",
        "macro_departments",
        "primary_circulation",
        "department_subdivisions",
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "deterministic_validation",
        "review_and_save",
    }
    assert layout_revision(base) == started["baseLayoutRevision"]

    undone = _coordinator(root).undo_to_base(
        tenant_id="tenant-a",
        site_id="site-a",
        run_id=started["runId"],
    )
    assert undone["run"]["status"] == "cancelled"
    assert undone["restoredLayout"] == base
    assert len(undone["supersededReceiptIds"]) == 10


def test_full_factory_run_supports_multiple_independent_cell_families(
    tmp_path: Path,
) -> None:
    root = tmp_path / "full-factory-multi-runs"
    base = _layout()
    coordinator = _coordinator(root)
    started = coordinator.start_full_factory_run(
        tenant_id="tenant-a",
        site_id="site-a",
        workspace_id="workspace-a",
        layout_id=base["layoutId"],
        user_id="user-a",
        session_id="session-full-factory-multi",
        base_layout=base,
        base_layout_revision=layout_revision(base),
        full_factory_request=_multi_family_program(),
        asset_catalog=list(LOCAL_ASSET_CATALOG),
        prototype_mode=True,
    )

    response = started
    for _ in FACILITY_GENERATION_STAGES:
        response = coordinator.continue_run(
            tenant_id="tenant-a",
            site_id="site-a",
            run_id=started["runId"],
            current_base_layout=base,
            current_base_revision=layout_revision(base),
        )

    assert response["status"] == "complete"
    assert len(response["draftLayout"]["placements"]) == 8
    seed_stage = next(
        item for item in response["stageGraph"] if item["stageId"] == "seed_cells"
    )
    module_stage = next(
        item
        for item in response["stageGraph"]
        if item["stageId"] == "repeated_modules"
    )
    assert seed_stage["validation"]["checks"]["seedCells"]["recipeCount"] == 2
    assert module_stage["validation"]["checks"]["repeatedModules"][
        "familyCount"
    ] == 2


def test_full_factory_http_run_keeps_saved_layout_blank_until_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_PROVIDER",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_FACILITY_LAYOUT_SAGE_OPENAI_REASONING_EFFORT",
        "INSPECTORPRO_SAGE_PROVIDER",
        "INSPECTORPRO_SAGE_ANTHROPIC_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_MODEL",
        "INSPECTORPRO_SAGE_OPENAI_REASONING_EFFORT",
    ):
        monkeypatch.delenv(name, raising=False)
    host = LocalFacilityLayoutHost(tmp_path / "host")
    app = FastAPI()
    app.include_router(host.create_router())
    client = TestClient(app)
    headers = {"X-InspectorPro-Session": "full-factory-http-session"}
    try:
        baseline = client.get("/api/facility-layout-bootstrap").json()[
            "layout"
        ]
        started = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/full-factory",
            headers=headers,
            json={
                "prototypeMode": True,
                "supersedeActiveDraft": True,
                "workspaceId": "workspace-facility-layout",
                "fullFactory": _program(),
            },
        )
        assert started.status_code == 200, started.text
        run = started.json()
        for expected in FACILITY_GENERATION_STAGES:
            continued = client.post(
                f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
                f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/continue",
                headers=headers,
                json={},
            )
            assert continued.status_code == 200, continued.text
            run = continued.json()
            assert run["completedStageId"] == expected["stageId"]
        assert run["status"] == "complete"
        assert run["workflowScope"] == FULL_FACTORY_SCOPE
        assert len(run["draftLayout"]["placements"]) == 6
        persisted = client.get("/api/facility-layout-bootstrap").json()[
            "layout"
        ]
        assert persisted["revision"] == baseline["revision"]
        assert persisted["layout"] == baseline["layout"]

        undone = client.post(
            f"/api/facility-layout-generation/{LOCAL_SITE_ID}/"
            f"{LOCAL_LAYOUT_ID}/runs/{run['runId']}/undo",
            headers=headers,
            json={},
        )
        assert undone.status_code == 200, undone.text
        assert undone.json()["restoredLayout"] == baseline["layout"]
    finally:
        client.close()
