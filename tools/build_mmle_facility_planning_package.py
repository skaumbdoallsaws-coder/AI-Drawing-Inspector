"""Build the non-production MMLE-50D Facility Planning Package benchmark."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_inspector.facility_layout.facility_planning import (
    FACILITY_PLANNING_PACKAGE_SCHEMA,
    canonicalize_facility_planning_package,
)
from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_facility_knowledge_bytes,
)


AKP_RELATIVE = Path(
    "generated/training/mmle-50d-497533f6/assembly_knowledge/"
    "akp-dcd00b22c1abe6d78cfb51f5"
)
OUTPUT_RELATIVE = Path(
    "generated/facility_planning/mmle-50d/"
    "mmle-50d-facility-planning-package-v1.json"
)

# These are illustrative packing gaps for the synthetic benchmark. They are
# not operating, safety, egress, or equipment-service clearances.
PROTOTYPE_REPEAT_GAP_METERS = 0.25
PROTOTYPE_MACHINE_GAP_METERS = 1.0


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _source_revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_index(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("assetId") or ""): item
        for item in catalog
        if isinstance(item, Mapping) and item.get("assetId")
    }


def _identity(catalog: Mapping[str, Mapping[str, Any]], asset_id: str) -> dict[str, str]:
    asset = catalog.get(asset_id)
    if asset is None:
        raise RuntimeError(f"Required private catalog asset is unavailable: {asset_id}")
    return {
        "assetId": str(asset["assetId"]),
        "assetDefinitionRevision": str(asset["assetDefinitionRevision"]),
        "displayName": str(asset["displayName"]),
    }


def _equipment(
    catalog: Mapping[str, Mapping[str, Any]],
    requirement_id: str,
    asset_id: str,
    quantity: int,
    target_area: str,
    pattern: str,
    orientation: str,
    role: str,
    process_refs: Sequence[str],
    *,
    spacing: float | None = None,
    dependencies: Sequence[str] = (),
) -> dict[str, Any]:
    identity = _identity(catalog, asset_id)
    return {
        "requirementId": requirement_id,
        "selectedCatalogIdentity": identity,
        "catalogCandidates": [deepcopy(identity)],
        "quantity": quantity,
        "targetArea": target_area,
        "placementPattern": pattern,
        "semanticOrientation": orientation,
        "resourceRole": role,
        "authoredSpacing": (
            None
            if spacing is None
            else {
                "value": spacing,
                "unit": "m",
                "evidenceRef": "mmle-synthetic-facility-scenario",
            }
        ),
        "processStepRefs": list(process_refs),
        "placementDependencies": list(dependencies),
        "evidenceRefs": [
            "mmle-synthetic-facility-scenario",
            "private-asset-catalog-revision",
        ],
    }


def _area_group(
    group_id: str,
    parent_id: str,
    labels: Sequence[str],
    zone_types: Sequence[str],
    proportions: Sequence[float],
    *,
    rows: Sequence[Mapping[str, Any]] = (),
    arrangement: str = "columns",
) -> dict[str, Any]:
    return {
        "areaGroupId": group_id,
        "parentDepartmentId": parent_id,
        "labels": list(labels),
        "zoneTypes": list(zone_types),
        "proportions": list(proportions),
        "arrangement": arrangement,
        "orientation": "horizontal",
        "rows": [deepcopy(dict(item)) for item in rows],
        "evidenceRefs": ["mmle-synthetic-facility-scenario"],
    }


def _route(
    route_id: str,
    scope: str,
    label: str,
    route_kind: str,
    width: float,
    source: str,
    target: str,
    via: Sequence[str],
    process_refs: Sequence[str],
) -> dict[str, Any]:
    return {
        "routeId": route_id,
        "scope": scope,
        "label": label,
        "routeKind": route_kind,
        "width": width,
        "sourceUnit": "m",
        "sourceArea": source,
        "targetArea": target,
        "viaAreas": list(via),
        "direction": "two_way",
        "processStepRefs": list(process_refs),
        "evidenceRefs": ["mmle-synthetic-facility-scenario"],
    }


def _marking_array(
    marking_id: str,
    marking_type: str,
    label: str,
    *,
    target_area: str | None = None,
    route_label: str | None = None,
    count: int,
    rows: int,
    columns: int,
    pitch_along: float,
    pitch_across: float,
    width: float,
    depth: float,
) -> dict[str, Any]:
    return {
        "communication_id": marking_id,
        "marking_type": marking_type,
        "label": label,
        "anchor_relationship": {
            "kind": "route" if route_label else "area",
            "target_area": target_area,
            "route_label": route_label,
            "placement_id": None,
        },
        "count": count,
        "rows": rows,
        "columns": columns,
        "pitch": {"along": pitch_along, "across": pitch_across},
        "semantic_orientation": "route_aligned" if route_label else "north_south",
        "width": width,
        "depth": depth,
        "source_unit": "m",
        "dimension_evidence_refs": ["mmle-synthetic-facility-scenario"],
    }


def build_mmle_facility_planning_package(
    project_root: str | Path,
    *,
    asset_catalog: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    akp_root = root / AKP_RELATIVE
    process = _read_json(akp_root / "process_candidates.json")
    package = _read_json(akp_root / "package.json")
    catalog_values = tuple(asset_catalog or build_private_local_asset_catalog(root))
    catalog = _catalog_index(catalog_values)
    catalog_revision = _revision(
        [
            {
                "assetId": item["assetId"],
                "assetDefinitionRevision": item["assetDefinitionRevision"],
            }
            for item in sorted(catalog_values, key=lambda value: str(value.get("assetId") or ""))
        ]
    )

    source_operations = {
        str(item["operationId"]): item
        for item in process.get("operationFamilies", [])
    }
    roots = {
        operation_id
        for operation_id, item in source_operations.items()
        if not item.get("predecessorOperationIds")
    }
    final_source = "op-final-release"
    department_by_operation = {
        "op-in-process-inspection": "inspection-packing-finished",
        "op-functional-test": "inspection-packing-finished",
        "op-final-release": "inspection-packing-finished",
    }
    process_steps = [
        {
            "processStepId": "scenario-receive-materials",
            "label": "Receive and stage materials",
            "predecessorProcessStepIds": [],
            "departmentId": "receiving-raw-material",
            "stationRef": "scenario-inbound-station",
            "materialAndWipClasses": ["raw-material", "purchased-components"],
            "evidenceRefs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "processStepId": "scenario-machine-components",
            "label": "Machine benchmark component families",
            "predecessorProcessStepIds": ["scenario-receive-materials"],
            "departmentId": "machining-hall",
            "stationRef": "scenario-machining-resources",
            "materialAndWipClasses": ["machined-components"],
            "evidenceRefs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "processStepId": "scenario-automated-preparation",
            "label": "Run benchmark automated preparation cells",
            "predecessorProcessStepIds": ["scenario-machine-components"],
            "departmentId": "automation-robot-cells",
            "stationRef": "scenario-robot-cell-family",
            "materialAndWipClasses": ["prepared-components"],
            "evidenceRefs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "processStepId": "scenario-support-maintenance",
            "label": "Provide tooling and maintenance support",
            "predecessorProcessStepIds": [],
            "departmentId": "material-maintenance",
            "stationRef": "scenario-maintenance-support",
            "materialAndWipClasses": ["tooling", "service-equipment"],
            "evidenceRefs": ["mmle-synthetic-facility-scenario"],
        },
    ]
    for operation_id, item in source_operations.items():
        predecessors = list(item.get("predecessorOperationIds") or [])
        if operation_id in roots:
            predecessors.append("scenario-automated-preparation")
        process_steps.append(
            {
                "processStepId": operation_id,
                "label": str(item["label"]),
                "predecessorProcessStepIds": predecessors,
                "departmentId": department_by_operation.get(operation_id, "assembly-kitting"),
                "stationRef": str((item.get("resourceRefs") or ["scenario-assembly-station"])[0]),
                "materialAndWipClasses": ["mmle-assembly-wip"],
                "evidenceRefs": [
                    "mmle-akp-process-candidates",
                    "mmle-synthetic-facility-scenario",
                ],
            }
        )
    process_steps.extend(
        [
            {
                "processStepId": "scenario-package-product",
                "label": "Package completed prototype product",
                "predecessorProcessStepIds": [final_source],
                "departmentId": "inspection-packing-finished",
                "stationRef": "scenario-packaging-stations",
                "materialAndWipClasses": ["packaged-product"],
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
            {
                "processStepId": "scenario-dispatch-product",
                "label": "Stage packaged prototype product for dispatch",
                "predecessorProcessStepIds": ["scenario-package-product"],
                "departmentId": "inspection-packing-finished",
                "stationRef": "scenario-finished-goods",
                "materialAndWipClasses": ["finished-product"],
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
        ]
    )

    departments = [
        ("receiving-raw-material", "Receiving + Raw Material", "receiving", 0.17, 1),
        ("machining-hall", "Machining Hall", "workcell", 0.20, 1),
        ("automation-robot-cells", "Automation + Robot Cells", "workcell", 0.23, 1),
        ("material-maintenance", "Material Handling + Maintenance", "workcell", 0.14, 2),
        ("assembly-kitting", "Assembly + Kitting", "workcell", 0.16, 2),
        (
            "inspection-packing-finished",
            "Inspection + Packaging + Finished Goods",
            "inspection",
            0.10,
            2,
        ),
    ]
    process_by_department: dict[str, list[str]] = {}
    for item in process_steps:
        process_by_department.setdefault(item["departmentId"], []).append(item["processStepId"])
    department_records = [
        {
            "departmentId": department_id,
            "label": label,
            "zoneType": zone_type,
            "areaShare": share,
            "row": row,
            "processStepRefs": process_by_department.get(department_id, []),
            "evidenceRefs": ["mmle-synthetic-facility-scenario"],
        }
        for department_id, label, zone_type, share, row in departments
    ]

    manufacturing_cells = [f"Manufacturing Cell A{index:02d}" for index in range(1, 13)]
    assembly_cells = [f"Assembly Cell A{index:02d}" for index in range(1, 5)]
    assembly_lines = [f"Assembly Line L{index:02d}" for index in range(1, 4)]
    kitting_islands = [f"Kitting Island K{index:02d}" for index in range(1, 3)]
    inspection_stations = [f"Inspection Station Q{index:02d}" for index in range(1, 5)]
    packaging_stations = [f"Packaging Station P{index:02d}" for index in range(1, 5)]
    finished_rows = [f"Finished Goods Rack Row R{index:02d}" for index in range(1, 5)]
    area_groups = [
        _area_group(
            "inbound-functional-areas",
            "receiving-raw-material",
            ["Receiving Dock", "Raw Material Rack Bank", "Inbound Staging"],
            ["dock", "storage", "staging"],
            [0.15, 0.70, 0.15],
        ),
        _area_group(
            "manufacturing-cells",
            "automation-robot-cells",
            manufacturing_cells,
            ["workcell"] * len(manufacturing_cells),
            [1 / 12] * 12,
            arrangement="row_stack",
            rows=[
                {"labels": manufacturing_cells[0:4], "proportion": 1 / 3},
                {"labels": manufacturing_cells[4:8], "proportion": 1 / 3},
                {"labels": manufacturing_cells[8:12], "proportion": 1 / 3},
            ],
        ),
        _area_group(
            "assembly-functional-areas",
            "assembly-kitting",
            [*assembly_cells, *assembly_lines, *kitting_islands],
            ["workcell"] * 9,
            [1 / 9] * 9,
            arrangement="row_stack",
            rows=[
                {"labels": assembly_cells, "proportion": 4 / 9},
                {"labels": assembly_lines, "proportion": 3 / 9},
                {"labels": kitting_islands, "proportion": 2 / 9},
            ],
        ),
        _area_group(
            "final-functional-areas",
            "inspection-packing-finished",
            [*inspection_stations, *packaging_stations, *finished_rows],
            [
                *(["inspection"] * len(inspection_stations)),
                *(["workcell"] * len(packaging_stations)),
                *(["storage"] * len(finished_rows)),
            ],
            [1 / 12] * 12,
            arrangement="row_stack",
            rows=[
                {"labels": inspection_stations, "proportion": 1 / 3},
                {"labels": packaging_stations, "proportion": 1 / 3},
                {"labels": finished_rows, "proportion": 1 / 3},
            ],
        ),
        _area_group(
            "maintenance-functional-areas",
            "material-maintenance",
            ["Equipment Parking", "Maintenance Shop", "Tooling + Utilities"],
            ["staging", "workcell", "workcell"],
            [0.30, 0.45, 0.25],
        ),
    ]

    receive = ["scenario-receive-materials"]
    machine = ["scenario-machine-components"]
    automate = ["scenario-automated-preparation"]
    assemble = ["op-build-lift-mechanism", "op-install-lift-and-platform"]
    inspect = ["op-in-process-inspection", "op-functional-test"]
    support = ["scenario-support-maintenance"]
    equipment = [
        _equipment(catalog, "raw-material-racks", "asset-pallet-rack", 90, "Raw Material Rack Bank", "rack_bank", "long_side_north_south", "storage", receive, spacing=PROTOTYPE_REPEAT_GAP_METERS),
        _equipment(catalog, "inbound-pallets", "asset-pallet-1200x1000", 16, "Inbound Staging", "pallet_staging", "long_side_north_south", "staging", receive, spacing=PROTOTYPE_REPEAT_GAP_METERS),
        _equipment(catalog, "inbound-pallet-trucks", "asset-pallet-truck-simple", 4, "Inbound Staging", "parking_rows", "long_side_north_south", "material_handling", receive),
        _equipment(catalog, "receiving-forklifts", "asset-forklift-2610x2264x986-minimum-height-green", 4, "Receiving Dock", "parking_rows", "long_side_north_south", "material_handling", receive, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "cnc-mills", "asset-cnc-mill", 7, "Machining Hall", "machine_rows", "long_side_east_west", "production", machine, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "cnc-lathes", "asset-haas-st30-lathe", 7, "Machining Hall", "machine_rows", "long_side_east_west", "production", machine, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "boring-machines", "asset-doosan-dbc130-ii", 5, "Machining Hall", "machine_rows", "long_side_east_west", "production", machine, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "surface-grinders", "asset-okamoto-surface-grinder", 3, "Machining Hall", "machine_rows", "long_side_east_west", "production", machine, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "edm-machines", "asset-sinker-edm", 2, "Machining Hall", "machine_rows", "long_side_east_west", "production", machine, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "band-saws", "asset-vertical-band-saw", 2, "Machining Hall", "machine_rows", "long_side_east_west", "production", machine, spacing=PROTOTYPE_MACHINE_GAP_METERS),
        _equipment(catalog, "machining-pallets", "asset-pallet-1200x1000", 6, "Machining Hall", "pallet_staging", "long_side_east_west", "staging", machine, spacing=PROTOTYPE_REPEAT_GAP_METERS),
        _equipment(catalog, "robot-cell-guards", "asset-5987t55-wire-mesh-machine-guard-panel", 38, manufacturing_cells[0], "guard_run_closed", "long_side_east_west", "guarding", automate),
        _equipment(catalog, "robot-cell-robot", "asset-abb-irb6650-robot", 1, manufacturing_cells[0], "robot_cell_interior", "long_side_east_west", "production", automate),
        _equipment(catalog, "robot-cell-tooling", "asset-carr-lane-cl-400-ptpb", 1, manufacturing_cells[0], "robot_cell_interior", "long_side_east_west", "tooling", automate),
        _equipment(catalog, "robot-cell-lift-table", "asset-lift-table-30x96", 1, manufacturing_cells[0], "robot_cell_interior", "long_side_east_west", "material_handling", automate),
        _equipment(catalog, "assembly-cell-benches", "asset-workbench-w84-d48", 5, assembly_cells[0], "assembly_bench_rows", "long_side_east_west", "production", assemble, spacing=1.5),
        _equipment(catalog, "assembly-cell-operator", "asset-operator", 1, assembly_cells[0], "assembly_bench_rows", "long_side_east_west", "operator", assemble),
        _equipment(catalog, "assembly-cell-drawers", "asset-user-library-drawers-4-6in-x-42in-w", 1, assembly_cells[0], "assembly_bench_rows", "long_side_east_west", "tooling", assemble),
        _equipment(catalog, "assembly-cell-cabinet", "asset-roll-away-cabinet", 1, assembly_cells[0], "assembly_bench_rows", "long_side_east_west", "tooling", assemble),
        _equipment(catalog, "assembly-line-benches", "asset-workbench-w72-d36", 4, assembly_lines[0], "assembly_bench_rows", "long_side_east_west", "production", assemble, spacing=1.5),
        _equipment(catalog, "assembly-line-operators", "asset-operator", 2, assembly_lines[0], "assembly_bench_rows", "long_side_east_west", "operator", assemble),
        _equipment(catalog, "assembly-line-cabinet", "asset-roll-away-cabinet", 1, assembly_lines[0], "assembly_bench_rows", "long_side_east_west", "tooling", assemble),
        _equipment(catalog, "kitting-bench", "asset-workbench-w60-d60", 1, kitting_islands[0], "assembly_bench_rows", "long_side_east_west", "kitting", assemble),
        _equipment(catalog, "kitting-carts", "asset-user-library-mobile-cart", 2, kitting_islands[0], "assembly_bench_rows", "long_side_east_west", "material_handling", assemble),
        _equipment(catalog, "kitting-operator", "asset-operator", 1, kitting_islands[0], "assembly_bench_rows", "long_side_east_west", "operator", assemble),
        _equipment(catalog, "kitting-pallets", "asset-pallet-1200x1000", 2, kitting_islands[0], "pallet_staging", "long_side_east_west", "staging", assemble),
        _equipment(catalog, "inspection-workstation", "asset-assembled-laboratory-workstation", 1, inspection_stations[0], "inspection_islands", "long_side_east_west", "inspection", inspect),
        _equipment(catalog, "inspection-table", "asset-mobile-folding-worktable", 1, inspection_stations[0], "inspection_islands", "long_side_east_west", "inspection", inspect),
        _equipment(catalog, "inspection-drawers", "asset-user-library-drawers-4-6in-x-42in-w", 1, inspection_stations[0], "inspection_islands", "long_side_east_west", "tooling", inspect),
        _equipment(catalog, "inspection-operator", "asset-operator", 1, inspection_stations[0], "inspection_islands", "long_side_east_west", "operator", inspect),
        _equipment(catalog, "packaging-bench", "asset-workbench-w72-d36", 1, packaging_stations[0], "packaging_islands", "long_side_east_west", "packaging", ["scenario-package-product"]),
        _equipment(catalog, "packaging-cart", "asset-user-library-mobile-cart", 1, packaging_stations[0], "packaging_islands", "long_side_east_west", "material_handling", ["scenario-package-product"]),
        _equipment(catalog, "packaging-operator", "asset-operator", 1, packaging_stations[0], "packaging_islands", "long_side_east_west", "operator", ["scenario-package-product"]),
        _equipment(catalog, "packaging-pallets", "asset-pallet-1200x1000", 2, packaging_stations[0], "pallet_staging", "long_side_east_west", "staging", ["scenario-package-product"]),
        _equipment(catalog, "finished-goods-racks", "asset-pallet-rack", 12, finished_rows[0], "rack_bank", "long_side_north_south", "storage", ["scenario-dispatch-product"], spacing=PROTOTYPE_REPEAT_GAP_METERS),
        _equipment(catalog, "finished-goods-pallets", "asset-pallet-1200x1000", 10, "Inspection + Packaging + Finished Goods", "pallet_staging", "long_side_north_south", "staging", ["scenario-dispatch-product"], spacing=PROTOTYPE_REPEAT_GAP_METERS),
        _equipment(catalog, "finished-goods-forklift", "asset-forklift", 1, "Inspection + Packaging + Finished Goods", "parking_rows", "long_side_north_south", "material_handling", ["scenario-dispatch-product"]),
        _equipment(catalog, "finished-goods-pallet-truck", "asset-pallet-truck-simple", 1, "Inspection + Packaging + Finished Goods", "parking_rows", "long_side_north_south", "material_handling", ["scenario-dispatch-product"]),
        _equipment(catalog, "maintenance-crane-2t", "asset-crane-2-ton", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "maintenance-lift-table", "asset-lift-table-30x96", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "maintenance-drawers", "asset-user-library-drawers-4-6in-x-42in-w", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "tooling", support),
        _equipment(catalog, "maintenance-crane-8t", "asset-crane-8-ton", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "maintenance-jack", "asset-centralizing-jack", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "maintenance-hoist", "asset-crane-montagem", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "maintenance-table", "asset-mobile-folding-worktable", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "maintenance-cabinet", "asset-roll-away-cabinet", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "tooling", support),
        _equipment(catalog, "maintenance-winch", "asset-winch-model", 1, "Maintenance Shop", "maintenance_group", "long_side_east_west", "maintenance", support),
        _equipment(catalog, "tooling-drawers", "asset-user-library-drawers-4-6in-x-42in-w", 1, "Tooling + Utilities", "maintenance_group", "long_side_east_west", "tooling", support),
        _equipment(catalog, "tooling-hideaway-cabinets", "asset-hideaway-cabinet", 4, "Tooling + Utilities", "maintenance_group", "long_side_east_west", "tooling", support),
        _equipment(catalog, "tooling-cart", "asset-user-library-mobile-cart", 1, "Tooling + Utilities", "maintenance_group", "long_side_east_west", "material_handling", support),
        _equipment(catalog, "tooling-shelves", "asset-tooling-shelves", 4, "Tooling + Utilities", "maintenance_group", "long_side_east_west", "tooling", support),
        _equipment(catalog, "parking-all-terrain-truck", "asset-all-terrain-pallet-truck", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-compact-forklift", "asset-forklift-2610x2264x986-minimum-height-green", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-electric-forklift", "asset-forklift", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-pallet-truck", "asset-pallet-truck-simple", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-telescopic-forklift", "asset-forklift-telescopic-red", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-reversible-forklift", "asset-reversible-fork-lift-truck", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-platform-truck", "asset-2329t24-steel-flush-platform-truck", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "parking-roll-container", "asset-tr1631-machine-guard-enclosure", 1, "Equipment Parking", "parking_rows", "long_side_north_south", "material_handling", support),
        _equipment(catalog, "assembly-finished-lift", "asset-mobile-lift-mmle-50d", 1, "Assembly + Kitting", "parking_rows", "long_side_east_west", "finished_product", ["op-final-release"]),
    ]

    recipes = [
        ("assembly-cell-recipe", assembly_cells[0], ["assembly-cell-benches", "assembly-cell-operator", "assembly-cell-drawers", "assembly-cell-cabinet"]),
        ("assembly-line-recipe", assembly_lines[0], ["assembly-line-benches", "assembly-line-operators", "assembly-line-cabinet"]),
        ("kitting-island-recipe", kitting_islands[0], ["kitting-bench", "kitting-carts", "kitting-operator", "kitting-pallets"]),
        ("inspection-station-recipe", inspection_stations[0], ["inspection-workstation", "inspection-table", "inspection-drawers", "inspection-operator"]),
        ("packaging-station-recipe", packaging_stations[0], ["packaging-bench", "packaging-cart", "packaging-operator", "packaging-pallets"]),
    ]
    cell_recipes = [
        {
            "recipe_id": recipe_id,
            "target_area": target,
            "member_batches": members,
            "candidate_strategies": ["line", "l", "u"],
            "selected_strategy_or_objective": "smallest_envelope",
            "authored_spacing": {
                "value": 1.5,
                "unit": "m",
                "evidence_ref": "mmle-synthetic-facility-scenario",
            },
            "process_order": [],
            "interfaces": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        }
        for recipe_id, target, members in recipes
    ]
    module_families = [
        {
            "family_id": "robot-cell-family",
            "source_recipe_or_cell": manufacturing_cells[0],
            "target_areas": manufacturing_cells[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry", "exact_catalog_revisions"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "family_id": "assembly-cell-family",
            "source_recipe_or_cell": "assembly-cell-recipe",
            "target_areas": assembly_cells[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "family_id": "assembly-line-family",
            "source_recipe_or_cell": "assembly-line-recipe",
            "target_areas": assembly_lines[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "family_id": "kitting-island-family",
            "source_recipe_or_cell": "kitting-island-recipe",
            "target_areas": kitting_islands[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "family_id": "inspection-station-family",
            "source_recipe_or_cell": "inspection-station-recipe",
            "target_areas": inspection_stations[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "family_id": "packaging-station-family",
            "source_recipe_or_cell": "packaging-station-recipe",
            "target_areas": packaging_stations[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
        {
            "family_id": "finished-goods-rack-family",
            "source_recipe_or_cell": finished_rows[0],
            "target_areas": finished_rows[1:],
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": ["mmle-synthetic-facility-scenario"],
        },
    ]

    all_flow_steps = [
        "scenario-receive-materials",
        "scenario-machine-components",
        "scenario-automated-preparation",
        "op-build-lift-mechanism",
        "op-in-process-inspection",
        "scenario-package-product",
        "scenario-dispatch-product",
    ]
    routes = [
        _route("main-forklift-boulevard", "primary", "Main Forklift Boulevard", "forklift", 5, "Receiving + Raw Material", "Inspection + Packaging + Finished Goods", ["Machining Hall", "Automation + Robot Cells", "Assembly + Kitting"], all_flow_steps),
        _route("machining-material-aisle-1", "local", "Machining Material Aisle 1", "forklift", 4, "Raw Material Rack Bank", "Machining Hall", [], ["scenario-receive-materials", "scenario-machine-components"]),
        _route("machining-material-aisle-2", "local", "Machining Material Aisle 2", "forklift", 4, "Machining Hall", manufacturing_cells[0], [], ["scenario-machine-components", "scenario-automated-preparation"]),
        _route("assembly-feed-aisle", "local", "Assembly Feed Aisle", "forklift", 4, manufacturing_cells[0], assembly_cells[0], [manufacturing_cells[5]], ["scenario-automated-preparation", "op-build-lift-mechanism"]),
        _route("tooling-service-aisle", "local", "Tooling Service Aisle", "forklift", 3, "Tooling + Utilities", assembly_lines[-1], [kitting_islands[-1]], ["scenario-support-maintenance", "op-install-lift-and-platform"]),
        _route("assembly-cell-pedestrian-aisle", "local", "Assembly Cell Pedestrian Aisle", "pedestrian", 2, assembly_cells[0], assembly_cells[-1], [], ["op-build-lift-mechanism"]),
        _route("automation-pedestrian-connector", "local", "Automation Pedestrian Connector", "pedestrian", 2, manufacturing_cells[1], manufacturing_cells[9], [manufacturing_cells[5]], ["scenario-automated-preparation"]),
        _route("maintenance-pedestrian-walkway", "local", "Maintenance Pedestrian Walkway", "pedestrian", 2, "Equipment Parking", "Tooling + Utilities", ["Maintenance Shop"], ["scenario-support-maintenance"]),
    ]

    floor_communication = [
        _marking_array(
            "equipment-parking-boxes",
            "parking_box",
            "Equipment Parking",
            target_area="Equipment Parking",
            count=30,
            rows=5,
            columns=6,
            pitch_along=5,
            pitch_across=6,
            width=3,
            depth=5,
        ),
        _marking_array(
            "main-flow-arrows",
            "direction_arrow",
            "Main Material Flow",
            route_label="Main Forklift Boulevard",
            count=6,
            rows=1,
            columns=6,
            pitch_along=20,
            pitch_across=1,
            width=2,
            depth=1,
        ),
    ]
    floor_communication.extend(
        _marking_array(
            f"robot-cell-keep-clear-{index:02d}",
            "keep_clear",
            f"Cell A{index:02d} Keep Clear",
            target_area=label,
            count=1,
            rows=1,
            columns=1,
            pitch_along=1,
            pitch_across=1,
            width=6,
            depth=6,
        )
        for index, label in enumerate(manufacturing_cells, start=1)
    )
    floor_communication.extend(
        [
            {
                "route_labels": ["Main Forklift Boulevard", "Assembly Cell Pedestrian Aisle"],
                "width": 4,
                "depth": 3,
                "source_unit": "m",
                "label": "West Pedestrian Crossing",
            },
            {
                "route_labels": ["Tooling Service Aisle", "Maintenance Pedestrian Walkway"],
                "width": 4,
                "depth": 3,
                "source_unit": "m",
                "label": "Service Pedestrian Crossing",
            },
        ]
    )

    scenario_revision = _source_revision(Path(__file__).resolve())
    process_revision = str(process["sourceRevision"])
    package_revision = str(package["packageRevision"])
    result = {
        "schemaVersion": FACILITY_PLANNING_PACKAGE_SCHEMA,
        "packageId": "mmle-50d-facility-planning-v1",
        "displayName": "MMLE-50D Prototype Production Plant",
        "productRef": {
            "productId": "MMLE-50D",
            "productRevision": process_revision,
            "displayName": "MMLE-50D Electric Mobile Lift",
        },
        "sourcePackageRefs": [
            {
                "sourceId": str(package["packageId"]),
                "sourceRevision": package_revision,
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
        "evidenceRegister": [
            {
                "evidenceId": "mmle-akp-process-candidates",
                "sourceType": "assembly_knowledge_process_candidates",
                "sourceLocator": (AKP_RELATIVE / "process_candidates.json").as_posix(),
                "sourceRevision": process_revision,
                "evidenceClass": "SYNTHETIC_DEMO",
                "authority": "illustrative",
                "reviewStatus": "pending",
                "synthetic": True,
            },
            {
                "evidenceId": "mmle-synthetic-facility-scenario",
                "sourceType": "facility_scenario_builder",
                "sourceLocator": "tools/build_mmle_facility_planning_package.py",
                "sourceRevision": scenario_revision,
                "evidenceClass": "SYNTHETIC_DEMO",
                "authority": "illustrative",
                "reviewStatus": "pending",
                "synthetic": True,
            },
            {
                "evidenceId": "private-asset-catalog-revision",
                "sourceType": "industrial_asset_catalog",
                "sourceLocator": "generated/industrial_assets/local_library/catalog.json",
                "sourceRevision": catalog_revision,
                "evidenceClass": "CATALOG_DERIVED",
                "authority": "supporting",
                "reviewStatus": "pending",
                "synthetic": False,
            },
        ],
        "facilityEnvelope": {
            "width": 300,
            "depth": 200,
            "sourceUnit": "m",
            "displayName": "MMLE-50D Prototype Production Plant",
            "gridSize": 1,
            "evidenceRefs": ["mmle-synthetic-facility-scenario"],
        },
        "planningInputs": [
            {
                "inputId": "mmle-process-routing",
                "kind": "process_routing",
                "statement": "The synthetic facility flow extends the MMLE assembly sequence with illustrative receiving, machining, automation, packaging, and dispatch steps.",
                "value": [item["processStepId"] for item in process_steps],
                "unit": None,
                "subjectRefs": ["MMLE-50D"],
                "evidenceRefs": ["mmle-akp-process-candidates", "mmle-synthetic-facility-scenario"],
            },
            {
                "inputId": "mmle-synthetic-demand",
                "kind": "demand_or_takt",
                "statement": "The benchmark assumes twelve prototype units per illustrative shift; it is not a released demand or capacity value.",
                "value": 12,
                "unit": "prototype_units_per_shift",
                "subjectRefs": ["MMLE-50D"],
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
            {
                "inputId": "mmle-capability-map",
                "kind": "capability_mapping",
                "statement": "The synthetic scenario binds process families to exact catalog assets for deterministic fit testing only.",
                "value": [item["requirementId"] for item in equipment],
                "unit": None,
                "subjectRefs": [item["processStepId"] for item in process_steps],
                "evidenceRefs": ["mmle-synthetic-facility-scenario", "private-asset-catalog-revision"],
            },
            {
                "inputId": "mmle-adjacency-flow",
                "kind": "adjacency_or_separation",
                "statement": "Department rows and routes follow the authored synthetic material-flow order; no safety separation is implied.",
                "value": [item[1] for item in departments],
                "unit": None,
                "subjectRefs": [item[0] for item in departments],
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
            {
                "inputId": "mmle-storage-staging",
                "kind": "storage_and_staging",
                "statement": "Rack, pallet, parking, and finished-goods quantities are synthetic benchmark inputs rather than calculated capacity.",
                "value": {"racks": 138, "pallets": 44, "parkingBoxes": 30},
                "unit": "count",
                "subjectRefs": ["receiving-raw-material", "inspection-packing-finished"],
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
            {
                "inputId": "mmle-staffing",
                "kind": "staffing",
                "statement": "Twenty operator figures are illustrative workstation resources, not an approved staffing plan.",
                "value": 20,
                "unit": "operator_stations",
                "subjectRefs": ["assembly-kitting", "inspection-packing-finished"],
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
        ],
        "processSteps": process_steps,
        "departments": department_records,
        "areaGroups": area_groups,
        "equipmentRequirements": equipment,
        "routes": routes,
        "cellRecipes": cell_recipes,
        "moduleFamilies": module_families,
        "floorCommunication": floor_communication,
        "presentationIntent": {
            "fit_to_occupied_content": True,
            "semantic_zoom": True,
            "overview_label_priority": [
                "macro_departments",
                "primary_routes",
                "child_areas",
                "assets",
            ],
            "plan_layers": ["zones", "routes", "markings", "assets"],
            "three_d_layers": ["floor", "zones", "routes", "assets"],
        },
        "unresolvedFindings": [
            {
                "findingId": "mmle-site-policy-unavailable",
                "code": "facility_site_policy_unavailable",
                "issue": "Approved egress, fire, clearance, and vehicle policies are not present in the synthetic package.",
                "risk": "safety_and_compliance",
                "requiredAction": "Provide controlled site policy before any production or compliance claim.",
                "blocking": False,
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
            {
                "findingId": "mmle-utilities-floor-loading-unavailable",
                "code": "facility_engineering_inputs_unavailable",
                "issue": "Utilities, service access, floor loading, and anchoring requirements are not available.",
                "risk": "installation_engineering",
                "requiredAction": "Provide controlled facility and equipment installation requirements before release.",
                "blocking": False,
                "evidenceRefs": ["mmle-synthetic-facility-scenario"],
            },
        ],
    }
    return canonicalize_facility_planning_package(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    output = (args.output or (root / OUTPUT_RELATIVE)).resolve()
    package = build_mmle_facility_planning_package(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(package, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "packageRevision": _revision(package),
                "processSteps": len(package["processSteps"]),
                "departments": len(package["departments"]),
                "areaGroups": len(package["areaGroups"]),
                "equipmentRequirements": len(package["equipmentRequirements"]),
                "routes": len(package["routes"]),
                "floorCommunication": len(package["floorCommunication"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
