from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.facility_planning import (
    FACILITY_PLANNING_PACKAGE_SCHEMA,
    FacilityPlanningPackageError,
    analyze_facility_planning_impact,
    canonicalize_facility_planning_package,
    compile_facility_planning_package,
    facility_planning_model_summary,
)
from ai_inspector.facility_layout.host import LOCAL_ASSET_CATALOG
from ai_inspector.facility_layout.operations import create_layout_document
from ai_inspector.facility_layout.program_execution import (
    FacilityProgramExecutionError,
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
)


def _base() -> dict:
    return create_layout_document(
        layout_id="fl-planning-package",
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
        created_at="2026-08-29T20:00:00Z",
    )


def _identity(display_name: str) -> dict:
    asset = next(item for item in LOCAL_ASSET_CATALOG if item["displayName"] == display_name)
    return {
        "assetId": asset["assetId"],
        "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "displayName": asset["displayName"],
    }


def _package() -> dict:
    evidence = {
        "evidenceId": "synthetic-scenario-v1",
        "sourceType": "facility_scenario",
        "sourceLocator": "tests/fixtures/facility-planning/scenario-v1.json",
        "sourceRevision": "1" * 64,
        "evidenceClass": "SYNTHETIC_DEMO",
        "authority": "illustrative",
        "reviewStatus": "pending",
        "synthetic": True,
    }
    steps = [
        {
            "processStepId": "receive-material",
            "label": "Receive material",
            "predecessorProcessStepIds": [],
            "departmentId": "receiving",
            "stationRef": "receiving-station",
            "materialAndWipClasses": ["raw-material"],
            "evidenceRefs": ["synthetic-scenario-v1"],
        },
        {
            "processStepId": "assemble-product",
            "label": "Assemble product",
            "predecessorProcessStepIds": ["receive-material"],
            "departmentId": "assembly",
            "stationRef": "assembly-bench",
            "materialAndWipClasses": ["assembly-wip"],
            "evidenceRefs": ["synthetic-scenario-v1"],
        },
        {
            "processStepId": "inspect-product",
            "label": "Inspect product",
            "predecessorProcessStepIds": ["assemble-product"],
            "departmentId": "inspection",
            "stationRef": "inspection-station",
            "materialAndWipClasses": ["finished-product"],
            "evidenceRefs": ["synthetic-scenario-v1"],
        },
    ]
    return {
        "schemaVersion": FACILITY_PLANNING_PACKAGE_SCHEMA,
        "packageId": "planning-package-demo-v1",
        "displayName": "Planning Package Factory",
        "productRef": {
            "productId": "product-demo",
            "productRevision": "2" * 64,
            "displayName": "Demo Product",
        },
        "sourcePackageRefs": [
            {
                "sourceId": "process-package-demo",
                "sourceRevision": "3" * 64,
                "sourceType": "assembly_knowledge_package",
            }
        ],
        "authority": {
            "knowledgeStatus": "inferred",
            "authority": "illustrative",
            "reviewStatus": "pending",
            "productionEligible": False,
            "planningClaim": "illustrative_prototype",
            "reviewReceiptId": None,
        },
        "evidenceRegister": [evidence],
        "facilityEnvelope": {
            "width": 90,
            "depth": 60,
            "sourceUnit": "m",
            "displayName": "Planning Package Factory",
            "gridSize": 1,
            "evidenceRefs": ["synthetic-scenario-v1"],
        },
        "planningInputs": [
            {
                "inputId": "input-routing",
                "kind": "process_routing",
                "statement": "Material follows receive, assemble, then inspect.",
                "value": ["receive-material", "assemble-product", "inspect-product"],
                "unit": None,
                "subjectRefs": ["receive-material", "assemble-product", "inspect-product"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
            {
                "inputId": "input-demand",
                "kind": "demand_or_takt",
                "statement": "The synthetic scenario assumes one prototype batch per shift.",
                "value": 1,
                "unit": "batch_per_shift",
                "subjectRefs": ["product-demo"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
            {
                "inputId": "input-capability",
                "kind": "capability_mapping",
                "statement": "Assembly workbenches support the synthetic assembly step.",
                "value": "Assembly Workbench",
                "unit": None,
                "subjectRefs": ["assemble-product"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
            {
                "inputId": "input-adjacency",
                "kind": "adjacency_or_separation",
                "statement": "The synthetic process sequence determines department adjacency order.",
                "value": "receiving_to_assembly_to_inspection",
                "unit": None,
                "subjectRefs": ["receiving", "assembly", "inspection"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
        ],
        "processSteps": steps,
        "departments": [
            {
                "departmentId": "receiving",
                "label": "Receiving",
                "zoneType": "receiving",
                "areaShare": 0.25,
                "row": 1,
                "processStepRefs": ["receive-material"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
            {
                "departmentId": "assembly",
                "label": "Assembly",
                "zoneType": "workcell",
                "areaShare": 0.5,
                "row": 1,
                "processStepRefs": ["assemble-product"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
            {
                "departmentId": "inspection",
                "label": "Inspection",
                "zoneType": "inspection",
                "areaShare": 0.25,
                "row": 2,
                "processStepRefs": ["inspect-product"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            },
        ],
        "areaGroups": [
            {
                "areaGroupId": "assembly-cells",
                "parentDepartmentId": "assembly",
                "labels": ["Assembly Cell A", "Assembly Cell B"],
                "zoneTypes": ["workcell", "workcell"],
                "proportions": [0.5, 0.5],
                "arrangement": "columns",
                "orientation": "horizontal",
                "rows": [],
                "evidenceRefs": ["synthetic-scenario-v1"],
            }
        ],
        "equipmentRequirements": [
            {
                "requirementId": "assembly-workbenches",
                "selectedCatalogIdentity": _identity("Assembly Workbench"),
                "catalogCandidates": [_identity("Assembly Workbench")],
                "quantity": 4,
                "targetArea": "Assembly Cell A",
                "placementPattern": "assembly_bench_rows",
                "semanticOrientation": "long_side_east_west",
                "resourceRole": "production",
                "authoredSpacing": {
                    "value": 1.5,
                    "unit": "m",
                    "evidenceRef": "synthetic-scenario-v1",
                },
                "processStepRefs": ["assemble-product"],
                "placementDependencies": [],
                "evidenceRefs": ["synthetic-scenario-v1"],
            }
        ],
        "routes": [
            {
                "routeId": "material-spine",
                "scope": "primary",
                "label": "Material Spine",
                "routeKind": "material",
                "width": 4,
                "sourceUnit": "m",
                "sourceArea": "Receiving",
                "targetArea": "Inspection",
                "viaAreas": ["Assembly"],
                "direction": "two_way",
                "processStepRefs": ["receive-material", "assemble-product", "inspect-product"],
                "evidenceRefs": ["synthetic-scenario-v1"],
            }
        ],
        "cellRecipes": [
            {
                "recipe_id": "assembly-cell-recipe",
                "target_area": "Assembly Cell A",
                "member_batches": ["assembly-workbenches"],
                "candidate_strategies": ["line", "l", "u"],
                "selected_strategy_or_objective": "smallest_envelope",
                "authored_spacing": {
                    "value": 1.5,
                    "unit": "m",
                    "evidence_ref": "synthetic-scenario-v1",
                },
                "process_order": [],
                "interfaces": [],
                "evidence_refs": ["synthetic-scenario-v1"],
            }
        ],
        "moduleFamilies": [
            {
                "family_id": "assembly-cell-family",
                "source_recipe_or_cell": "assembly-cell-recipe",
                "target_areas": ["Assembly Cell B"],
                "allowed_transform_mode": "translate_exact",
                "preserve_source": True,
                "conformance_requirements": ["exact_relative_geometry"],
                "composable_with": [],
                "evidence_refs": ["synthetic-scenario-v1"],
            }
        ],
        "floorCommunication": [],
        "presentationIntent": {
            "fit_to_occupied_content": True,
            "semantic_zoom": True,
        },
        "unresolvedFindings": [],
    }


def test_planning_package_compiles_and_executes_as_unsaved_prototype() -> None:
    package = _package()
    compiled = compile_facility_planning_package(package, list(LOCAL_ASSET_CATALOG))

    assert compiled["blockingFindingCount"] == 0
    assert compiled["productionEligible"] is False
    assert {item["facilityEntityType"] for item in compiled["provenance"]} >= {
        "department",
        "resource_batch",
        "route",
    }
    program = compiled["facilityProgram"]
    plan = compile_facility_program_operation_plan(program, _base(), list(LOCAL_ASSET_CATALOG))
    result = execute_facility_program_operation_plan(_base(), plan)

    assert result["saved"] is False
    assert result["undoLayout"] == _base()
    assert result["counts"] == {
        "zones": 5,
        "routes": 1,
        "placements": 8,
        "floorMarkings": 0,
    }


def test_missing_quantity_becomes_a_blocking_finding_not_a_default() -> None:
    package = _package()
    package["equipmentRequirements"][0]["quantity"] = None
    compiled = compile_facility_planning_package(package, list(LOCAL_ASSET_CATALOG))

    assert compiled["blockingFindingCount"] == 1
    assert compiled["findings"][0]["code"] == "facility_planning_equipment_quantity_missing"
    assert compiled["facilityProgram"]["resource_batches"] == []
    with pytest.raises(FacilityProgramExecutionError) as exc:
        compile_facility_program_operation_plan(
            compiled["facilityProgram"], _base(), list(LOCAL_ASSET_CATALOG)
        )
    assert exc.value.code == "facility_program_blocking_findings"


def test_synthetic_evidence_and_illustrative_package_cannot_self_promote() -> None:
    package = _package()
    package["evidenceRegister"][0]["reviewStatus"] = "confirmed"
    with pytest.raises(FacilityPlanningPackageError) as exc:
        canonicalize_facility_planning_package(package)
    assert exc.value.code == "facility_planning_synthetic_authority_forbidden"

    package = _package()
    package["authority"].update(
        {
            "authority": "controlled",
            "reviewStatus": "confirmed",
            "productionEligible": True,
            "planningClaim": "production_realistic",
            "reviewReceiptId": "review-receipt-not-trusted",
        }
    )
    with pytest.raises(FacilityPlanningPackageError) as exc:
        compile_facility_planning_package(package, list(LOCAL_ASSET_CATALOG))
    assert exc.value.code == "facility_planning_review_receipt_untrusted"


def test_model_authored_coordinates_are_rejected_before_compilation() -> None:
    package = _package()
    package["departments"][0]["position"] = {"x": 1, "z": 2}
    with pytest.raises(FacilityPlanningPackageError) as exc:
        canonicalize_facility_planning_package(package)
    assert exc.value.code == "facility_planning_model_geometry_forbidden"


def test_process_change_invalidates_only_related_and_downstream_scopes() -> None:
    impact = analyze_facility_planning_impact(_package(), ["assemble-product"])

    assert impact["affectedProcessStepIds"] == ["assemble-product", "inspect-product"]
    assert impact["affectedDepartmentIds"] == ["assembly", "inspection"]
    assert impact["affectedEquipmentRequirementIds"] == ["assembly-workbenches"]
    assert impact["affectedRouteIds"] == ["material-spine"]
    assert "receiving" not in impact["affectedDepartmentIds"]


def test_same_planner_produces_distinct_programs_for_distinct_packages() -> None:
    manual = _package()

    warehouse = deepcopy(_package())
    warehouse["packageId"] = "planning-package-warehouse-v1"
    warehouse["displayName"] = "Warehouse Flow Prototype"
    warehouse["facilityEnvelope"].update(
        {"displayName": "Warehouse Flow Prototype", "width": 150, "depth": 80}
    )
    warehouse["processSteps"][1]["label"] = "Store material"
    warehouse["processSteps"][2]["label"] = "Dispatch material"
    warehouse["departments"][0]["label"] = "Inbound Dock"
    warehouse["departments"][1]["label"] = "Storage"
    warehouse["departments"][2]["label"] = "Outbound Dock"
    warehouse["areaGroups"][0]["labels"] = ["Storage A", "Storage B"]
    warehouse["equipmentRequirements"][0].update(
        {
            "requirementId": "storage-racks",
            "selectedCatalogIdentity": _identity("Pallet Rack"),
            "catalogCandidates": [_identity("Pallet Rack")],
            "quantity": 12,
            "targetArea": "Storage A",
            "placementPattern": "rack_bank",
            "resourceRole": "storage",
        }
    )
    warehouse["routes"][0].update(
        {
            "routeId": "warehouse-spine",
            "label": "Warehouse Spine",
            "sourceArea": "Inbound Dock",
            "targetArea": "Outbound Dock",
            "viaAreas": ["Storage"],
            "width": 5,
        }
    )
    warehouse["cellRecipes"][0].update(
        {
            "target_area": "Storage A",
            "member_batches": ["storage-racks"],
        }
    )
    warehouse["moduleFamilies"][0]["target_areas"] = ["Storage B"]

    machining = deepcopy(_package())
    machining["packageId"] = "planning-package-machining-v1"
    machining["displayName"] = "Machining Flow Prototype"
    machining["facilityEnvelope"].update(
        {"displayName": "Machining Flow Prototype", "width": 130, "depth": 90}
    )
    machining["processSteps"][1]["label"] = "Machine components"
    machining["processSteps"][2]["label"] = "Measure components"
    machining["departments"][0]["label"] = "Material Prep"
    machining["departments"][1]["label"] = "Machining"
    machining["departments"][2]["label"] = "Metrology"
    machining["areaGroups"][0]["labels"] = ["Machine Bay A", "Machine Bay B"]
    machining["equipmentRequirements"][0].update(
        {
            "requirementId": "cnc-machines",
            "selectedCatalogIdentity": _identity("CNC Milling Machine"),
            "catalogCandidates": [_identity("CNC Milling Machine")],
            "quantity": 6,
            "targetArea": "Machine Bay A",
            "placementPattern": "machine_rows",
        }
    )
    machining["routes"][0].update(
        {
            "routeId": "machining-spine",
            "label": "Machining Spine",
            "sourceArea": "Material Prep",
            "targetArea": "Metrology",
            "viaAreas": ["Machining"],
            "width": 4.5,
        }
    )
    machining["cellRecipes"][0].update(
        {
            "target_area": "Machine Bay A",
            "member_batches": ["cnc-machines"],
        }
    )
    machining["moduleFamilies"][0]["target_areas"] = ["Machine Bay B"]

    programs = [
        compile_facility_planning_package(package, list(LOCAL_ASSET_CATALOG))[
            "facilityProgram"
        ]
        for package in (manual, warehouse, machining)
    ]
    signatures = {
        (
            tuple(program["macro_departments"][0]["labels"]),
            tuple(
                (batch["exact_catalog_identity"]["asset_id"], batch["quantity"])
                for batch in program["resource_batches"]
            ),
            tuple(
                route["label"]
                for route in program["route_network"]["primary_routes"]
            ),
        )
        for program in programs
    }
    assert len(signatures) == 3
    assert len(
        {program["identity"]["source_revision_refs"][0] for program in programs}
    ) == 3


def test_sage_summary_is_bounded_and_states_the_claim_boundary() -> None:
    compiled = compile_facility_planning_package(_package(), list(LOCAL_ASSET_CATALOG))
    summary = facility_planning_model_summary(compiled)

    assert summary["status"] == "prototype_ready"
    assert summary["productionEligible"] is False
    assert "does not establish safety" in summary["claimBoundary"]
