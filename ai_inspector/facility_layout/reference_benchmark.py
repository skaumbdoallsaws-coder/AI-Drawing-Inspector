"""Frozen Level-B generalization benchmark for reference-quality facilities."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Mapping, Sequence

from .canonical import layout_revision
from .facility_program import (
    canonicalize_facility_program,
    facility_program_from_full_factory,
)
from .full_factory import FacilityFullFactoryError
from .industrial_patterns import FacilityIndustrialPatternError
from .knowledge_foundation import canonical_facility_knowledge_bytes
from .operations import create_layout_document
from .program_execution import (
    FacilityProgramExecutionError,
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
)


REFERENCE_GENERALIZATION_SCHEMA = "facility-reference-generalization-v1"


def _asset(
    name: str,
    quantity: int,
    target: str,
    *,
    orientation: str = "auto",
    role: str = "production",
) -> dict[str, Any]:
    return {
        "asset_name": name,
        "quantity": quantity,
        "target_area": target,
        "orientation_mode": orientation,
        "facing_direction": None,
        "resource_role": role,
        "access_requirement": "physical_only",
    }


def _asset_batches(
    name: str,
    quantity: int,
    target: str,
    *,
    orientation: str = "auto",
    role: str = "production",
) -> tuple[dict[str, Any], ...]:
    remaining = quantity
    result = []
    while remaining:
        batch_quantity = min(50, remaining)
        result.append(
            _asset(
                name,
                batch_quantity,
                target,
                orientation=orientation,
                role=role,
            )
        )
        remaining -= batch_quantity
    return tuple(result)


def _route(
    label: str,
    source: str,
    target: str,
    *,
    via: Sequence[str] = (),
    kind: str = "material",
    width: float = 4,
    direction: str = "two_way",
) -> dict[str, Any]:
    return {
        "route_kind": kind,
        "width": width,
        "source_unit": "m",
        "source_department": source,
        "target_department": target,
        "via_departments": list(via),
        "direction": direction,
        "label": label,
    }


def _request(
    name: str,
    width: float,
    depth: float,
    rows: Sequence[Sequence[str]],
    *,
    assets: Sequence[Mapping[str, Any]] = (),
    routes: Sequence[Mapping[str, Any]] = (),
    subdivisions: Sequence[Mapping[str, Any]] = (),
    cell_recipes: Sequence[Mapping[str, Any]] = (),
    module_families: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    labels = [label for row in rows for label in row]
    return {
        "facility_envelope": {
            "width": width,
            "depth": depth,
            "source_unit": "m",
            "display_name": name,
            "grid_size": 1,
        },
        "departments": {
            "count": len(labels),
            "labels": labels,
            "proportions": None,
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [
                {"labels": list(row), "proportion": None} for row in rows
            ],
        },
        "circulation": {"routes": list(routes), "crossings": []},
        "subdivisions": list(subdivisions),
        "asset_placements": [deepcopy(dict(item)) for item in assets],
        "seed_cell": None,
        "cell_replication": None,
        "cell_recipes": [deepcopy(dict(item)) for item in cell_recipes],
        "module_families": [deepcopy(dict(item)) for item in module_families],
        "execution_mode": "authorized_draft_run",
    }


def _cell_recipe(target: str, gap: float) -> dict[str, Any]:
    return {
        "target_area": target,
        "candidate_strategies": ["line", "l", "u"],
        "selected_strategy": None,
        "objective": "smallest_envelope",
        "preferred_gap_meters": gap,
        "invert_u": False,
    }


def _module_family(source: str, targets: Sequence[str]) -> dict[str, Any]:
    return {
        "source_cell": source,
        "target_areas": list(targets),
        "copy_current_edited_state": False,
    }


def reference_generalization_cases() -> tuple[dict[str, Any], ...]:
    """Return five positive held-out factories and one negative control."""

    guard_cells = tuple(f"Weld Cell {index:02d}" for index in range(1, 7))
    guard_assets = tuple(
        item
        for cell in guard_cells
        for item in (
            _asset(
                "Wire Mesh Machine Guard Panel 5987T55",
                30,
                cell,
                role="support",
            ),
        )
    )
    guard_dense = _request(
        "Northstar Guarded Fabrication",
        320,
        180,
        (("Inbound Metals", "Automated Weld", "Verification", "Outbound"),),
        assets=guard_assets,
        subdivisions=(
            {
                "parent_department": "Automated Weld",
                "count": 6,
                "labels": list(guard_cells),
                "proportions": None,
                "arrangement": "row_stack",
                "orientation": "horizontal",
                "rows": [
                    {"labels": list(guard_cells[:3]), "proportion": None},
                    {"labels": list(guard_cells[3:]), "proportion": None},
                ],
            },
        ),
        routes=(
            _route(
                "Northstar Material Spine",
                "Inbound Metals",
                "Outbound",
                via=("Automated Weld", "Verification"),
                width=5,
            ),
        ),
    )

    zero_guard = _request(
        "Lakeside Manual Products",
        160,
        100,
        (
            ("Goods In", "Warehouse"),
            ("Machine Shop", "Manual Assembly", "Quality", "Despatch"),
        ),
        assets=(
            _asset("Pallet Rack", 24, "Warehouse", role="storage"),
            _asset("CNC Milling Machine", 6, "Machine Shop"),
            _asset("Assembly Workbench", 12, "Manual Assembly"),
            _asset("Electric Forklift", 2, "Goods In", role="material_handling"),
        ),
    )

    high_density_assets = tuple(
        item
        for label in (
            "Reserve A",
            "Reserve B",
            "Reserve C",
            "Forward A",
            "Forward B",
            "Forward C",
        )
        for item in _asset_batches("Pallet Rack", 100, label, role="storage")
    )
    over_five_hundred = _request(
        "Granite Distribution Campus",
        720,
        420,
        (
            ("Reserve A", "Reserve B", "Reserve C"),
            ("Forward A", "Forward B", "Forward C"),
        ),
        assets=high_density_assets,
    )

    loop_topology = _request(
        "Cedar Closed Loop Works",
        180,
        140,
        (("Cut", "Form"), ("Coat", "Inspect")),
        assets=(
            _asset("CNC Milling Machine", 4, "Cut"),
            _asset("Assembly Workbench", 6, "Form"),
        ),
        routes=(
            _route("Cedar Cut to Form", "Cut", "Form"),
            _route("Cedar Form to Coat", "Form", "Coat"),
            _route("Cedar Coat to Inspect", "Coat", "Inspect"),
            _route("Cedar Return Loop", "Inspect", "Cut"),
        ),
    )

    mixed_families = _request(
        "Summit Modular Manufacturing",
        240,
        180,
        (
            ("Build A", "Build B", "Build C"),
            ("Store A", "Store B", "Store C"),
            ("Machine A", "Machine B", "Machine C"),
        ),
        assets=(
            _asset("Assembly Workbench", 4, "Build A"),
            _asset("Pallet Rack", 6, "Store A", role="storage"),
            _asset("CNC Milling Machine", 3, "Machine A"),
        ),
        cell_recipes=(
            _cell_recipe("Build A", 1.5),
            _cell_recipe("Store A", 2.0),
            _cell_recipe("Machine A", 2.5),
        ),
        module_families=(
            _module_family("Build A", ("Build B", "Build C")),
            _module_family("Store A", ("Store B", "Store C")),
            _module_family("Machine A", ("Machine B", "Machine C")),
        ),
    )

    infeasible = _request(
        "Impossible Micro Factory",
        20,
        20,
        (("Micro Machining",),),
        assets=_asset_batches("CNC Milling Machine", 100, "Micro Machining"),
    )

    return (
        {
            "caseId": "guard-dense",
            "traits": ["guard_dense", "closed_guard_run"],
            "request": guard_dense,
            "expected": {"zones": 10, "routes": 1, "placements": 180, "floorMarkings": 0},
        },
        {
            "caseId": "zero-guard",
            "traits": ["zero_guarding", "mixed_resources"],
            "request": zero_guard,
            "resourceSpacingMeters": 1.0,
            "expected": {"zones": 6, "routes": 0, "placements": 44, "floorMarkings": 0},
        },
        {
            "caseId": "over-500",
            "traits": ["over_500_placements", "restart_safe_batching"],
            "request": over_five_hundred,
            "resourceSpacingMeters": 1.0,
            "expected": {"zones": 6, "routes": 0, "placements": 600, "floorMarkings": 0},
        },
        {
            "caseId": "loop-topology",
            "traits": ["loop_route_topology"],
            "request": loop_topology,
            "resourceSpacingMeters": 1.5,
            "expected": {"zones": 4, "routes": 4, "placements": 10, "floorMarkings": 0},
        },
        {
            "caseId": "mixed-cell-families",
            "traits": ["multiple_cell_families", "different_family_sizes"],
            "request": mixed_families,
            "expected": {"zones": 9, "routes": 0, "placements": 39, "floorMarkings": 0},
        },
        {
            "caseId": "infeasible-negative-control",
            "traits": ["negative_control", "no_partial_reduction"],
            "request": infeasible,
            "expectedError": "facility_program_resource_set_unplaceable",
        },
    )


def reference_generalization_benchmark() -> dict[str, Any]:
    core = {
        "schemaVersion": REFERENCE_GENERALIZATION_SCHEMA,
        "benchmarkId": "facility-reference-generalization-level-b-v1",
        "cases": list(reference_generalization_cases()),
    }
    core["benchmarkRevision"] = hashlib.sha256(
        canonical_facility_knowledge_bytes(core)
    ).hexdigest()
    return core


def _base(case_id: str) -> dict[str, Any]:
    return create_layout_document(
        layout_id=f"fl-reference-generalization-{case_id}",
        display_name="Blank Facility",
        association={"siteId": "site-benchmark", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "benchmark-origin",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "benchmark-shell",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "benchmark-policy",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-30T00:00:00Z",
    )


def evaluate_reference_generalization(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile and execute every held-out program through the public engine."""

    benchmark = reference_generalization_benchmark()
    results = []
    for case in benchmark["cases"]:
        case_id = str(case["caseId"])
        base = _base(case_id)
        try:
            program = facility_program_from_full_factory(
                case["request"], asset_catalog
            )
            spacing = case.get("resourceSpacingMeters")
            if spacing is not None:
                for batch in program["resource_batches"]:
                    batch["authored_spacing"] = {
                        "value": float(spacing),
                        "unit": "m",
                        "evidence_ref": f"{case_id}-authored-resource-spacing",
                    }
                program = canonicalize_facility_program(program)
            plan = compile_facility_program_operation_plan(
                program, base, asset_catalog
            )
            result = execute_facility_program_operation_plan(base, plan)
        except (
            FacilityFullFactoryError,
            FacilityProgramExecutionError,
            FacilityIndustrialPatternError,
        ) as exc:
            expected_error = str(case.get("expectedError") or "")
            code = str(getattr(exc, "code", ""))
            if not expected_error or code != expected_error:
                raise AssertionError(
                    f"{case_id} failed with {code or type(exc).__name__}: {exc}; "
                    f"details={getattr(exc, 'details', None)}"
                ) from exc
            results.append(
                {
                    "caseId": case_id,
                    "status": "expected_refusal",
                    "errorCode": code,
                    "baseRevisionUnchanged": layout_revision(base)
                    == layout_revision(_base(case_id)),
                }
            )
            continue

        if case.get("expectedError"):
            raise AssertionError(f"{case_id} unexpectedly produced a draft")
        if result["counts"] != case["expected"]:
            raise AssertionError(
                f"{case_id} counts differ: {result['counts']} != {case['expected']}"
            )
        requested_identities = {
            (
                item["exact_catalog_identity"]["asset_id"],
                item["exact_catalog_identity"]["asset_definition_revision"],
            )
            for item in program["resource_batches"]
        }
        actual_identities = {
            (item["assetId"], item["assetDefinitionRevision"])
            for item in result["draftLayout"]["placements"]
        }
        if actual_identities - requested_identities:
            raise AssertionError(f"{case_id} substituted a catalog revision")
        results.append(
            {
                "caseId": case_id,
                "status": "passed",
                "counts": deepcopy(result["counts"]),
                "saved": result["saved"],
                "undoExact": result["undoLayout"] == base,
                "operationPlanRevision": plan["planRevision"],
                "facilityProgramRevision": plan["programRevision"],
                "stageBatchCounts": {
                    stage["stageId"]: len(stage["batches"])
                    for stage in plan["stages"]
                },
            }
        )

    core = {
        "schemaVersion": REFERENCE_GENERALIZATION_SCHEMA,
        "benchmarkId": benchmark["benchmarkId"],
        "benchmarkRevision": benchmark["benchmarkRevision"],
        "caseCount": len(results),
        "passedCount": sum(
            item["status"] in {"passed", "expected_refusal"} for item in results
        ),
        "results": results,
    }
    core["evaluationRevision"] = hashlib.sha256(
        canonical_facility_knowledge_bytes(core)
    ).hexdigest()
    return core


__all__ = [
    "REFERENCE_GENERALIZATION_SCHEMA",
    "evaluate_reference_generalization",
    "reference_generalization_benchmark",
    "reference_generalization_cases",
]
