"""Deterministic synthetic Facility Planning packages and evaluation corpus."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re
from typing import Any, Mapping, Sequence

from .canonical import layout_revision
from .facility_planning import (
    FACILITY_PLANNING_PACKAGE_SCHEMA,
    FacilityPlanningPackageError,
    canonicalize_facility_planning_package,
    compile_facility_planning_package,
)
from .facility_program import FacilityProgramError
from .industrial_patterns import FacilityIndustrialPatternError
from .knowledge_foundation import canonical_facility_knowledge_bytes
from .operations import create_layout_document
from .program_execution import (
    FacilityProgramExecutionError,
    compile_facility_program_operation_plan,
    execute_facility_program_operation_plan,
)


SYNTHETIC_FACILITY_CORPUS_SCHEMA = "facility-planning-synthetic-corpus-v1"
SYNTHETIC_FACILITY_EVALUATION_SCHEMA = (
    "facility-planning-synthetic-corpus-evaluation-v1"
)
SYNTHETIC_FACILITY_NEGATIVE_SCHEMA = (
    "facility-planning-synthetic-negative-cases-v1"
)

_SCENARIO_EVIDENCE_ID = "synthetic-facility-scenario"
_CATALOG_EVIDENCE_ID = "private-asset-catalog-revision"
_FIXED_CREATED_AT = "2026-08-30T00:00:00Z"


class SyntheticFacilityCorpusError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _resource(
    key: str,
    asset_id: str,
    quantity: int,
    target: str,
    pattern: str,
    *,
    orientation: str = "catalog_default",
    role: str = "production",
    spacing: float | None = 0.5,
    variant_quantities: Sequence[int] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "asset_id": asset_id,
        "quantity": quantity,
        "target": target,
        "pattern": pattern,
        "orientation": orientation,
        "role": role,
        "spacing": spacing,
        "variant_quantities": (
            None if variant_quantities is None else list(variant_quantities)
        ),
    }


def _route(
    key: str,
    label: str,
    source: str,
    target: str,
    *,
    via: Sequence[str] = (),
    kind: str = "material",
    width: float = 4.0,
    scope: str = "primary",
    direction: str = "two_way",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "source": source,
        "target": target,
        "via": list(via),
        "kind": kind,
        "width": width,
        "scope": scope,
        "direction": direction,
    }


def _group(
    key: str,
    parent: str,
    labels: Sequence[str],
    *,
    zone_types: Sequence[str] | None = None,
    rows: Sequence[Sequence[str]] = (),
) -> dict[str, Any]:
    labels = list(labels)
    return {
        "key": key,
        "parent": parent,
        "labels": labels,
        "zone_types": list(zone_types or ("workcell",) * len(labels)),
        "rows": [list(row) for row in rows],
    }


def _recipe(
    key: str,
    target: str,
    member_batches: Sequence[str],
    *,
    strategies: Sequence[str] = ("line", "l", "u"),
    objective: str = "smallest_envelope",
    spacing: float = 1.5,
) -> dict[str, Any]:
    return {
        "key": key,
        "target": target,
        "member_batches": list(member_batches),
        "strategies": list(strategies),
        "objective": objective,
        "spacing": spacing,
    }


def _family(
    key: str,
    source: str,
    targets: Sequence[str],
) -> dict[str, Any]:
    return {"key": key, "source": source, "targets": list(targets)}


def _area_marking(
    key: str,
    marking_type: str,
    label: str,
    target: str,
    *,
    count: int = 2,
    rows: int = 1,
    columns: int = 2,
    pitch_along: float = 4.0,
    pitch_across: float = 2.0,
    width: float = 2.5,
    depth: float = 1.5,
    orientation: str = "east_west",
) -> dict[str, Any]:
    return {
        "key": key,
        "marking_type": marking_type,
        "label": label,
        "target": target,
        "count": count,
        "rows": rows,
        "columns": columns,
        "pitch_along": pitch_along,
        "pitch_across": pitch_across,
        "width": width,
        "depth": depth,
        "orientation": orientation,
    }


_VARIANTS = (
    {
        "variant_id": "pilot",
        "label": "Pilot",
        "size_scale": 0.9,
        "quantity_scale": 0.75,
        "spacing_scale": 0.9,
    },
    {
        "variant_id": "balanced",
        "label": "Balanced",
        "size_scale": 1.0,
        "quantity_scale": 1.0,
        "spacing_scale": 1.0,
    },
    {
        "variant_id": "expanded",
        "label": "Expanded",
        "size_scale": 1.2,
        "quantity_scale": 1.25,
        "spacing_scale": 1.1,
    },
    {
        "variant_id": "high-throughput",
        "label": "High Throughput",
        "size_scale": 1.4,
        "quantity_scale": 1.5,
        "spacing_scale": 1.2,
    },
)


_ARCHETYPES = (
    {
        "archetype_id": "linear-discrete-assembly",
        "display_name": "Linear Discrete Assembly",
        "description": "A straight-through component machining and product assembly flow.",
        "traits": ["linear_flow", "discrete_assembly", "single_material_spine"],
        "base_size": [260.0, 120.0],
        "rows": [["Receiving", "Material Stores", "Machining", "Subassembly", "Final Assembly", "Inspection", "Shipping"]],
        "departments": [
            ["Receiving", "receiving", 10],
            ["Material Stores", "storage", 15],
            ["Machining", "workcell", 18],
            ["Subassembly", "workcell", 15],
            ["Final Assembly", "workcell", 20],
            ["Inspection", "inspection", 12],
            ["Shipping", "shipping", 10],
        ],
        "resources": [
            _resource("receiving-forklift", "asset-forklift", 1, "Receiving", "parking_rows", role="material_handling"),
            _resource("material-racks", "asset-pallet-rack", 18, "Material Stores", "rack_bank", orientation="long_side_north_south", role="storage", spacing=0.5),
            _resource("machine-tools", "asset-cnc-mill", 6, "Machining", "machine_rows", orientation="long_side_east_west", spacing=1.0),
            _resource("subassembly-benches", "asset-workbench", 8, "Subassembly", "assembly_bench_rows", orientation="long_side_east_west", spacing=1.0),
            _resource("final-benches", "asset-workbench-w84-d48", 10, "Final Assembly", "assembly_bench_rows", orientation="long_side_east_west", spacing=1.25),
            _resource("inspection-stations", "asset-assembled-laboratory-workstation", 3, "Inspection", "inspection_islands", orientation="long_side_east_west", spacing=1.0),
            _resource("shipping-pallets", "asset-pallet-1200x1000", 8, "Shipping", "pallet_staging", role="staging", spacing=0.5),
        ],
        "routes": [_route("material-spine", "Linear Material Spine", "Receiving", "Shipping", via=("Material Stores", "Machining", "Subassembly", "Final Assembly", "Inspection"), width=5.0)],
        "groups": [],
        "recipes": [],
        "families": [],
        "markings": [_area_marking("shipping-bays", "parking_box", "Shipping Staging", "Shipping", count=3, columns=3)],
    },
    {
        "archetype_id": "high-mix-job-shop",
        "display_name": "High-Mix Job Shop",
        "description": "A flexible job shop with shared machining, fabrication, and assembly resources.",
        "traits": ["high_mix", "shared_resources", "two_row_flow"],
        "base_size": [230.0, 150.0],
        "rows": [["Inbound", "Stockroom", "Cutting", "Machining"], ["Fabrication", "Flexible Assembly", "Quality", "Dispatch"]],
        "departments": [
            ["Inbound", "receiving", 10], ["Stockroom", "storage", 14],
            ["Cutting", "workcell", 11], ["Machining", "workcell", 17],
            ["Fabrication", "workcell", 15], ["Flexible Assembly", "workcell", 16],
            ["Quality", "inspection", 9], ["Dispatch", "shipping", 8],
        ],
        "resources": [
            _resource("stock-racks", "asset-pallet-rack", 20, "Stockroom", "rack_bank", role="storage", spacing=0.5),
            _resource("cutting-mills", "asset-cnc-mill", 3, "Cutting", "machine_rows", spacing=1.0),
            _resource("machining-mills", "asset-cnc-mill", 5, "Machining", "machine_rows", orientation="long_side_east_west", spacing=1.0),
            _resource("machining-lathes", "asset-cnc-lathe", 4, "Machining", "machine_rows", orientation="long_side_east_west", spacing=1.0),
            _resource("fabrication-benches", "asset-workbench-w72-d36", 8, "Fabrication", "assembly_bench_rows", spacing=1.0),
            _resource("flexible-benches", "asset-workbench", 12, "Flexible Assembly", "assembly_bench_rows", spacing=1.0),
            _resource("quality-stations", "asset-assembled-laboratory-workstation", 4, "Quality", "inspection_islands", spacing=1.0),
        ],
        "routes": [
            _route("job-shop-spine", "Job Shop Material Spine", "Inbound", "Dispatch", via=("Stockroom", "Machining", "Flexible Assembly", "Quality"), width=4.5),
            _route("fabrication-feed", "Fabrication Feed", "Cutting", "Fabrication", kind="material", width=3.5, scope="local"),
        ],
        "groups": [], "recipes": [], "families": [],
        "markings": [_area_marking("inbound-staging", "parking_box", "Inbound Staging", "Inbound", count=4, columns=4)],
    },
    {
        "archetype_id": "distribution-center",
        "display_name": "Distribution Center",
        "description": "A reserve-storage and forward-pick operation with inbound and outbound staging.",
        "traits": ["warehouse", "rack_dense", "inbound_outbound_flow"],
        "base_size": [320.0, 210.0],
        "rows": [["Inbound Docks", "Reserve Storage", "Forward Pick"], ["Packing", "Sortation", "Outbound Docks"]],
        "departments": [
            ["Inbound Docks", "receiving", 12], ["Reserve Storage", "storage", 30],
            ["Forward Pick", "storage", 18], ["Packing", "workcell", 14],
            ["Sortation", "staging", 12], ["Outbound Docks", "shipping", 14],
        ],
        "resources": [
            _resource("reserve-racks", "asset-pallet-rack", 72, "Reserve Storage", "rack_bank", orientation="long_side_north_south", role="storage", spacing=0.5),
            _resource("forward-racks", "asset-pallet-rack", 36, "Forward Pick", "rack_bank", orientation="long_side_north_south", role="storage", spacing=0.5),
            _resource("inbound-forklifts", "asset-forklift", 3, "Inbound Docks", "parking_rows", role="material_handling", spacing=1.0),
            _resource("packing-tables", "asset-mobile-folding-worktable", 10, "Packing", "packaging_islands", spacing=1.0),
            _resource("sortation-pallets", "asset-pallet-1200x1000", 18, "Sortation", "pallet_staging", role="staging", spacing=0.5),
            _resource("outbound-forklifts", "asset-forklift", 2, "Outbound Docks", "parking_rows", role="material_handling", spacing=1.0),
        ],
        "routes": [
            _route("warehouse-loop-a", "Inbound Storage Route", "Inbound Docks", "Forward Pick", via=("Reserve Storage",), width=5.0),
            _route("warehouse-loop-b", "Outbound Storage Route", "Forward Pick", "Outbound Docks", via=("Packing", "Sortation"), width=5.0),
        ],
        "groups": [], "recipes": [], "families": [],
        "markings": [
            _area_marking("inbound-bays", "parking_box", "Inbound Bays", "Inbound Docks", count=4, columns=4, width=3.0, depth=5.0, pitch_along=5.0),
            _area_marking("outbound-bays", "parking_box", "Outbound Bays", "Outbound Docks", count=4, columns=4, width=3.0, depth=5.0, pitch_along=5.0),
        ],
    },
    {
        "archetype_id": "robotic-fabrication",
        "display_name": "Robotic Fabrication",
        "description": "Guarded robotic workcells supplied from fabrication and verified before dispatch.",
        "traits": ["automation", "guard_dense", "replicated_cells"],
        "base_size": [250.0, 170.0],
        "rows": [["Inbound Metals", "Fabrication", "Automation"], ["Verification", "Maintenance", "Outbound"]],
        "departments": [
            ["Inbound Metals", "receiving", 10], ["Fabrication", "workcell", 18],
            ["Automation", "workcell", 36], ["Verification", "inspection", 12],
            ["Maintenance", "service", 12], ["Outbound", "shipping", 12],
        ],
        "groups": [_group("robot-cells", "Automation", ["Robot Cell A", "Robot Cell B", "Robot Cell C", "Robot Cell D"], rows=(("Robot Cell A", "Robot Cell B"), ("Robot Cell C", "Robot Cell D")))],
        "resources": [
            _resource("fabrication-benches", "asset-workbench-w84-d48", 8, "Fabrication", "assembly_bench_rows", spacing=1.0),
            *[
                resource
                for cell_key, cell_label in (
                    ("a", "Robot Cell A"),
                    ("b", "Robot Cell B"),
                    ("c", "Robot Cell C"),
                    ("d", "Robot Cell D"),
                )
                for resource in (
                    _resource(
                        f"robot-cell-{cell_key}-guards",
                        "asset-5987t55-wire-mesh-machine-guard-panel",
                        12,
                        cell_label,
                        "guard_run_closed",
                        role="safety",
                        variant_quantities=(12, 16, 20, 24),
                    ),
                    _resource(
                        f"robot-cell-{cell_key}-robot",
                        "asset-adtech-sa6-robot",
                        1,
                        cell_label,
                        "robot_cell_interior",
                        role="automation",
                    ),
                    _resource(
                        f"robot-cell-{cell_key}-operator",
                        "asset-operator",
                        1,
                        cell_label,
                        "robot_cell_interior",
                        role="operator",
                    ),
                )
            ],
            _resource("verification-stations", "asset-assembled-laboratory-workstation", 4, "Verification", "inspection_islands", spacing=1.0),
            _resource("maintenance-crane", "asset-crane-2-ton", 1, "Maintenance", "maintenance_group", role="maintenance"),
            _resource("maintenance-cabinet", "asset-roll-away-cabinet", 2, "Maintenance", "maintenance_group", role="tooling"),
        ],
        "routes": [_route("robotic-spine", "Robotic Material Spine", "Inbound Metals", "Outbound", via=("Fabrication", "Automation", "Verification"), width=5.0)],
        "recipes": [],
        "families": [],
        "markings": [_area_marking("robot-keep-clear", "keep_clear", "Robot Cell Keep Clear", "Robot Cell A", count=1, columns=1, pitch_along=1.0, width=5.0, depth=5.0)],
    },
    {
        "archetype_id": "electronics-assembly",
        "display_name": "Electronics Assembly",
        "description": "A bench-oriented electronics build with controlled stores, test, and pack-out.",
        "traits": ["bench_assembly", "test_intensive", "pedestrian_flow"],
        "base_size": [190.0, 130.0],
        "rows": [["Receiving", "Controlled Stores", "Bench Assembly"], ["Electrical Test", "Rework", "Pack and Ship"]],
        "departments": [
            ["Receiving", "receiving", 10], ["Controlled Stores", "storage", 18],
            ["Bench Assembly", "workcell", 30], ["Electrical Test", "inspection", 18],
            ["Rework", "workcell", 12], ["Pack and Ship", "shipping", 12],
        ],
        "groups": [_group("assembly-islands", "Bench Assembly", ["Assembly Island A", "Assembly Island B", "Assembly Island C"], rows=(("Assembly Island A", "Assembly Island B", "Assembly Island C"),))],
        "resources": [
            _resource("controlled-racks", "asset-pallet-rack", 12, "Controlled Stores", "rack_bank", role="storage", spacing=0.5),
            _resource("island-benches", "asset-workbench-w72-d36", 6, "Assembly Island A", "assembly_bench_rows", spacing=1.0),
            _resource("island-operators", "asset-operator", 3, "Assembly Island A", "robot_cell_interior", role="operator"),
            _resource("test-stations", "asset-assembled-laboratory-workstation", 8, "Electrical Test", "inspection_islands", spacing=1.0),
            _resource("rework-benches", "asset-workbench-w60-d48", 4, "Rework", "assembly_bench_rows", spacing=1.0),
            _resource("packing-tables", "asset-mobile-folding-worktable", 4, "Pack and Ship", "packaging_islands", spacing=1.0),
        ],
        "routes": [
            _route("electronics-material", "Electronics Material Route", "Receiving", "Pack and Ship", via=("Controlled Stores", "Bench Assembly", "Electrical Test"), width=3.5),
            _route("electronics-personnel", "Electronics Personnel Walk", "Rework", "Electrical Test", kind="pedestrian", width=2.0, scope="local"),
        ],
        "recipes": [_recipe("assembly-island-recipe", "Assembly Island A", ("island-benches", "island-operators"), spacing=1.25)],
        "families": [_family("assembly-island-family", "assembly-island-recipe", ("Assembly Island B", "Assembly Island C"))],
        "markings": [_area_marking("pack-bays", "parking_box", "Pack-Out Bays", "Pack and Ship", count=2, columns=2)],
    },
    {
        "archetype_id": "fabrication-weld-paint",
        "display_name": "Fabrication Weld and Paint",
        "description": "A metal-fabrication sequence with separated preparation, finishing, and inspection areas.",
        "traits": ["fabrication", "separated_processes", "material_flow"],
        "base_size": [270.0, 160.0],
        "rows": [["Raw Stock", "Cutting", "Welding", "Paint Preparation"], ["Finishing", "Cure Staging", "Inspection", "Shipping"]],
        "departments": [
            ["Raw Stock", "storage", 15], ["Cutting", "workcell", 12],
            ["Welding", "workcell", 18], ["Paint Preparation", "workcell", 12],
            ["Finishing", "workcell", 15], ["Cure Staging", "staging", 12],
            ["Inspection", "inspection", 8], ["Shipping", "shipping", 8],
        ],
        "resources": [
            _resource("raw-stock-racks", "asset-pallet-rack", 20, "Raw Stock", "rack_bank", role="storage", spacing=0.5),
            _resource("cutting-machines", "asset-cnc-mill", 4, "Cutting", "machine_rows", spacing=1.0),
            _resource("weld-benches", "asset-workbench-w84-d48", 10, "Welding", "assembly_bench_rows", spacing=1.0),
            _resource("paint-prep-tables", "asset-mobile-folding-worktable", 6, "Paint Preparation", "packaging_islands", spacing=1.0),
            _resource("finishing-tables", "asset-mobile-folding-worktable", 6, "Finishing", "packaging_islands", spacing=1.0),
            _resource("cure-pallets", "asset-pallet-1200x1000", 12, "Cure Staging", "pallet_staging", role="staging", spacing=0.5),
            _resource("inspection-workstations", "asset-assembled-laboratory-workstation", 3, "Inspection", "inspection_islands", spacing=1.0),
        ],
        "routes": [_route("fabrication-flow", "Fabrication Material Route", "Raw Stock", "Shipping", via=("Cutting", "Welding", "Paint Preparation", "Finishing", "Cure Staging", "Inspection"), width=5.0)],
        "groups": [], "recipes": [], "families": [],
        "markings": [_area_marking("cure-staging-boxes", "parking_box", "Cure Staging Positions", "Cure Staging", count=4, columns=4)],
    },
    {
        "archetype_id": "remanufacturing-depot",
        "display_name": "Remanufacturing Depot",
        "description": "A reverse-flow depot for intake, teardown, repair, rebuild, and test.",
        "traits": ["reverse_logistics", "maintenance", "rework_loop"],
        "base_size": [220.0, 150.0],
        "rows": [["Returns Intake", "Teardown", "Clean and Inspect"], ["Repair", "Reassembly", "Functional Test", "Dispatch"]],
        "departments": [
            ["Returns Intake", "receiving", 12], ["Teardown", "service", 16],
            ["Clean and Inspect", "inspection", 14], ["Repair", "service", 18],
            ["Reassembly", "workcell", 18], ["Functional Test", "inspection", 12],
            ["Dispatch", "shipping", 10],
        ],
        "resources": [
            _resource("intake-pallets", "asset-pallet-1200x1000", 10, "Returns Intake", "pallet_staging", role="staging", spacing=0.5),
            _resource("teardown-benches", "asset-workbench-w84-d60", 6, "Teardown", "assembly_bench_rows", spacing=1.0),
            _resource("clean-inspect-stations", "asset-assembled-laboratory-workstation", 4, "Clean and Inspect", "inspection_islands", spacing=1.0),
            _resource("repair-benches", "asset-workbench-w84-d48", 8, "Repair", "assembly_bench_rows", spacing=1.0),
            _resource("repair-crane", "asset-crane-2-ton", 1, "Repair", "maintenance_group", role="maintenance"),
            _resource("reassembly-benches", "asset-workbench", 8, "Reassembly", "assembly_bench_rows", spacing=1.0),
            _resource("test-lifts", "asset-lift-table-30x96", 3, "Functional Test", "inspection_islands", role="inspection", spacing=1.0),
        ],
        "routes": [
            _route("remanufacturing-main", "Remanufacturing Main Route", "Returns Intake", "Dispatch", via=("Teardown", "Clean and Inspect", "Repair", "Reassembly", "Functional Test"), width=4.0),
            _route("repair-return", "Repair Return Loop", "Functional Test", "Repair", kind="material", width=3.0, scope="local"),
        ],
        "groups": [], "recipes": [], "families": [],
        "markings": [_area_marking("returns-hold", "parking_box", "Returns Hold", "Returns Intake", count=3, columns=3)],
    },
    {
        "archetype_id": "mixed-model-cellular",
        "display_name": "Mixed-Model Cellular Manufacturing",
        "description": "Shared machining feeds replicated mixed-model assembly cells and centralized verification.",
        "traits": ["cellular", "mixed_model", "replicated_modules"],
        "base_size": [240.0, 170.0],
        "rows": [["Inbound", "Shared Machining", "Cellular Assembly"], ["Shared Quality", "Finished Goods", "Outbound"]],
        "departments": [
            ["Inbound", "receiving", 10], ["Shared Machining", "workcell", 20],
            ["Cellular Assembly", "workcell", 36], ["Shared Quality", "inspection", 14],
            ["Finished Goods", "storage", 12], ["Outbound", "shipping", 8],
        ],
        "groups": [_group("product-cells", "Cellular Assembly", ["Product Cell A", "Product Cell B", "Product Cell C"], rows=(("Product Cell A", "Product Cell B", "Product Cell C"),))],
        "resources": [
            _resource("shared-mills", "asset-cnc-mill", 6, "Shared Machining", "machine_rows", spacing=1.0),
            _resource("shared-lathes", "asset-cnc-lathe", 4, "Shared Machining", "machine_rows", spacing=1.0),
            _resource("cell-benches", "asset-workbench-w72-d36", 6, "Product Cell A", "assembly_bench_rows", spacing=1.0),
            _resource("cell-operators", "asset-operator", 3, "Product Cell A", "robot_cell_interior", role="operator"),
            _resource("cell-cart", "asset-user-library-mobile-cart", 1, "Product Cell A", "maintenance_group", role="material_handling"),
            _resource("quality-stations", "asset-assembled-laboratory-workstation", 5, "Shared Quality", "inspection_islands", spacing=1.0),
            _resource("finished-racks", "asset-pallet-rack", 12, "Finished Goods", "rack_bank", role="storage", spacing=0.5),
        ],
        "routes": [_route("cellular-spine", "Cellular Material Spine", "Inbound", "Outbound", via=("Shared Machining", "Cellular Assembly", "Shared Quality", "Finished Goods"), width=4.5)],
        "recipes": [_recipe("product-cell-recipe", "Product Cell A", ("cell-benches", "cell-operators", "cell-cart"), spacing=1.25)],
        "families": [_family("product-cell-family", "product-cell-recipe", ("Product Cell B", "Product Cell C"))],
        "markings": [_area_marking("outbound-staging", "parking_box", "Outbound Staging", "Outbound", count=2, columns=2)],
    },
    {
        "archetype_id": "warehouse-production-hybrid",
        "display_name": "Warehouse Production Hybrid",
        "description": "Integrated storage, production, WIP, and fulfillment within one shared facility.",
        "traits": ["warehouse_factory_hybrid", "wip_buffers", "shared_logistics"],
        "base_size": [300.0, 190.0],
        "rows": [["Receiving", "Raw Storage", "Production"], ["WIP Supermarket", "Packaging", "Finished Goods", "Dispatch"]],
        "departments": [
            ["Receiving", "receiving", 10], ["Raw Storage", "storage", 24],
            ["Production", "workcell", 25], ["WIP Supermarket", "storage", 12],
            ["Packaging", "workcell", 10], ["Finished Goods", "storage", 12],
            ["Dispatch", "shipping", 7],
        ],
        "resources": [
            _resource("raw-racks", "asset-pallet-rack", 48, "Raw Storage", "rack_bank", role="storage", spacing=0.5),
            _resource("production-benches", "asset-workbench", 18, "Production", "assembly_bench_rows", spacing=1.0),
            _resource("wip-racks", "asset-pallet-rack", 20, "WIP Supermarket", "rack_bank", role="storage", spacing=0.5),
            _resource("packaging-tables", "asset-mobile-folding-worktable", 8, "Packaging", "packaging_islands", spacing=1.0),
            _resource("finished-racks", "asset-pallet-rack", 24, "Finished Goods", "rack_bank", role="storage", spacing=0.5),
            _resource("receiving-forklifts", "asset-forklift", 2, "Receiving", "parking_rows", role="material_handling", spacing=1.0),
        ],
        "routes": [
            _route("hybrid-inbound", "Hybrid Inbound Route", "Receiving", "WIP Supermarket", via=("Raw Storage", "Production"), width=5.0),
            _route("hybrid-outbound", "Hybrid Outbound Route", "WIP Supermarket", "Dispatch", via=("Packaging", "Finished Goods"), width=5.0),
        ],
        "groups": [], "recipes": [], "families": [],
        "markings": [_area_marking("dispatch-bays", "parking_box", "Dispatch Bays", "Dispatch", count=3, columns=3, width=3.0, depth=5.0, pitch_along=5.0)],
    },
    {
        "archetype_id": "laboratory-pilot-plant",
        "display_name": "Laboratory Pilot Plant",
        "description": "A low-volume pilot build with preparation, laboratory testing, and controlled rework.",
        "traits": ["pilot_build", "laboratory", "low_density"],
        "base_size": [170.0, 120.0],
        "rows": [["Sample Receiving", "Preparation", "Pilot Build"], ["Laboratory Test", "Rework", "Archive and Ship"]],
        "departments": [
            ["Sample Receiving", "receiving", 10], ["Preparation", "workcell", 18],
            ["Pilot Build", "workcell", 25], ["Laboratory Test", "inspection", 25],
            ["Rework", "workcell", 12], ["Archive and Ship", "shipping", 10],
        ],
        "resources": [
            _resource("prep-tables", "asset-mobile-folding-worktable", 5, "Preparation", "packaging_islands", spacing=1.0),
            _resource("pilot-benches", "asset-workbench-w60-d48", 8, "Pilot Build", "assembly_bench_rows", spacing=1.0),
            _resource("laboratory-stations", "asset-assembled-laboratory-workstation", 10, "Laboratory Test", "inspection_islands", spacing=1.0),
            _resource("rework-benches", "asset-workbench-w48-d48", 4, "Rework", "assembly_bench_rows", spacing=1.0),
            _resource("archive-racks", "asset-pallet-rack", 8, "Archive and Ship", "rack_bank", role="storage", spacing=0.5),
        ],
        "routes": [
            _route("pilot-material", "Pilot Material Route", "Sample Receiving", "Archive and Ship", via=("Preparation", "Pilot Build", "Laboratory Test"), width=3.0),
            _route("pilot-rework", "Pilot Rework Loop", "Laboratory Test", "Rework", kind="pedestrian", width=2.0, scope="local"),
        ],
        "groups": [], "recipes": [], "families": [],
        "markings": [_area_marking("sample-hold", "parking_box", "Sample Hold", "Sample Receiving", count=2, columns=2)],
    },
    {
        "archetype_id": "heavy-equipment-assembly",
        "display_name": "Heavy Equipment Assembly",
        "description": "A crane- and lift-assisted heavy assembly flow with subassembly and final test.",
        "traits": ["heavy_assembly", "lifting_resources", "large_footprints"],
        "base_size": [340.0, 210.0],
        "rows": [["Heavy Receiving", "Fabrication", "Subassembly"], ["Final Assembly", "Heavy Test", "Finished Equipment", "Shipping"]],
        "departments": [
            ["Heavy Receiving", "receiving", 12], ["Fabrication", "workcell", 18],
            ["Subassembly", "workcell", 18], ["Final Assembly", "workcell", 25],
            ["Heavy Test", "inspection", 12], ["Finished Equipment", "storage", 8],
            ["Shipping", "shipping", 7],
        ],
        "resources": [
            _resource("fabrication-machines", "asset-cnc-mill", 6, "Fabrication", "machine_rows", spacing=1.5),
            _resource("subassembly-benches", "asset-workbench-w96-d60", 10, "Subassembly", "assembly_bench_rows", spacing=1.5),
            _resource("subassembly-crane", "asset-crane-2-ton", 1, "Subassembly", "maintenance_group", role="lifting"),
            _resource("final-benches", "asset-workbench-w96-d96", 12, "Final Assembly", "assembly_bench_rows", spacing=2.0),
            _resource("final-crane", "asset-crane-8-ton", 1, "Final Assembly", "maintenance_group", role="lifting"),
            _resource("test-lift-tables", "asset-lift-table-30x96", 4, "Heavy Test", "inspection_islands", role="inspection", spacing=1.5),
            _resource("finished-lifts", "asset-mobile-lift-mmle-50d", 6, "Finished Equipment", "parking_rows", role="finished_product", spacing=1.0),
        ],
        "routes": [_route("heavy-material", "Heavy Equipment Material Route", "Heavy Receiving", "Shipping", via=("Fabrication", "Subassembly", "Final Assembly", "Heavy Test", "Finished Equipment"), width=6.0)],
        "groups": [], "recipes": [], "families": [],
        "markings": [_area_marking("finished-parking", "parking_box", "Finished Equipment Positions", "Finished Equipment", count=4, columns=4, width=4.0, depth=6.0, pitch_along=6.0)],
    },
    {
        "archetype_id": "compact-urban-factory",
        "display_name": "Compact Urban Factory",
        "description": "A vertically constrained footprint represented as tightly planned shared departments and micro-cells.",
        "traits": ["compact", "shared_areas", "space_constrained"],
        "base_size": [160.0, 120.0],
        "rows": [["Urban Receiving", "Shared Stores", "Machine Room"], ["Micro Assembly", "Inspection and Pack", "Urban Dispatch"]],
        "departments": [
            ["Urban Receiving", "receiving", 10], ["Shared Stores", "storage", 18],
            ["Machine Room", "workcell", 20], ["Micro Assembly", "workcell", 28],
            ["Inspection and Pack", "inspection", 16], ["Urban Dispatch", "shipping", 8],
        ],
        "groups": [_group("micro-cells", "Micro Assembly", ["Micro Cell A", "Micro Cell B"], rows=(("Micro Cell A", "Micro Cell B"),))],
        "resources": [
            _resource("urban-racks", "asset-pallet-rack", 10, "Shared Stores", "rack_bank", role="storage", spacing=0.35),
            _resource("urban-machines", "asset-cnc-mill", 3, "Machine Room", "machine_rows", spacing=0.75),
            _resource("micro-benches", "asset-workbench-w48-d48", 4, "Micro Cell A", "assembly_bench_rows", spacing=0.75, variant_quantities=(3, 4, 4, 4)),
            _resource("micro-operators", "asset-operator", 2, "Micro Cell A", "robot_cell_interior", role="operator", variant_quantities=(2, 2, 2, 2)),
            _resource("compact-inspection", "asset-assembled-laboratory-workstation", 3, "Inspection and Pack", "inspection_islands", spacing=0.75),
            _resource("compact-pack", "asset-mobile-folding-worktable", 2, "Inspection and Pack", "packaging_islands", spacing=0.75),
        ],
        "routes": [_route("urban-spine", "Urban Material Spine", "Urban Receiving", "Urban Dispatch", via=("Shared Stores", "Machine Room", "Micro Assembly", "Inspection and Pack"), width=3.0)],
        "recipes": [_recipe("micro-cell-recipe", "Micro Cell A", ("micro-benches", "micro-operators"), spacing=0.5)],
        "families": [_family("micro-cell-family", "micro-cell-recipe", ("Micro Cell B",))],
        "markings": [_area_marking("urban-dispatch-bays", "parking_box", "Urban Dispatch", "Urban Dispatch", count=2, columns=2, width=2.5, depth=4.0, pitch_along=4.0)],
    },
)


def synthetic_facility_archetypes() -> tuple[dict[str, Any], ...]:
    return tuple(deepcopy(item) for item in _ARCHETYPES)


def synthetic_facility_variants() -> tuple[dict[str, Any], ...]:
    return tuple(deepcopy(item) for item in _VARIANTS)


def _catalog_index(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("assetId") or ""): item
        for item in asset_catalog
        if isinstance(item, Mapping) and item.get("assetId")
    }


def _catalog_identity(
    catalog: Mapping[str, Mapping[str, Any]], asset_id: str
) -> dict[str, str]:
    asset = catalog.get(asset_id)
    if asset is None:
        raise SyntheticFacilityCorpusError(
            "synthetic_facility_asset_unavailable",
            "A synthetic scenario references an unavailable catalog asset.",
            details={"assetId": asset_id},
        )
    return {
        "assetId": str(asset["assetId"]),
        "assetDefinitionRevision": str(asset["assetDefinitionRevision"]),
        "displayName": str(asset["displayName"]),
    }


def _split(archetype_index: int, variant_index: int) -> str:
    if archetype_index >= 8:
        return "heldout"
    return "development" if variant_index < 3 else "evaluation"


def _exact_shares(
    departments: Sequence[Sequence[Any]],
) -> dict[str, float]:
    total = sum(float(item[2]) for item in departments)
    result: dict[str, float] = {}
    running = 0.0
    for index, item in enumerate(departments):
        if index == len(departments) - 1:
            share = 1.0 - running
        else:
            share = float(item[2]) / total
            running += share
        result[str(item[0])] = share
    return result


def _variant_quantity(
    resource: Mapping[str, Any], variant: Mapping[str, Any], variant_index: int
) -> int:
    exact = resource.get("variant_quantities")
    if isinstance(exact, Sequence) and not isinstance(exact, (str, bytes)):
        return int(exact[variant_index])
    return max(1, int(math.ceil(int(resource["quantity"]) * float(variant["quantity_scale"]))))


def build_synthetic_facility_planning_package(
    archetype_id: str,
    variant_id: str,
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one coordinate-free, illustrative, production-ineligible package."""

    try:
        archetype = next(
            item
            for item in _ARCHETYPES
            if item["archetype_id"] == archetype_id
        )
        variant_index, variant = next(
            (index, item)
            for index, item in enumerate(_VARIANTS)
            if item["variant_id"] == variant_id
        )
    except StopIteration as exc:
        raise SyntheticFacilityCorpusError(
            "synthetic_facility_scenario_unknown",
            "The requested synthetic facility archetype or variant is unavailable.",
            details={"archetypeId": archetype_id, "variantId": variant_id},
        ) from exc

    package_id = f"syn-fac-{archetype_id}-{variant_id}-v1"
    scenario_core = {
        "schemaVersion": SYNTHETIC_FACILITY_CORPUS_SCHEMA,
        "packageId": package_id,
        "archetypeId": archetype_id,
        "variantId": variant_id,
        "archetype": archetype,
        "variant": variant,
    }
    scenario_revision = _revision(scenario_core)
    catalog = _catalog_index(asset_catalog)
    catalog_revision = _revision(
        [
            {
                "assetId": item["assetId"],
                "assetDefinitionRevision": item["assetDefinitionRevision"],
            }
            for item in sorted(
                asset_catalog, key=lambda value: str(value.get("assetId") or "")
            )
            if isinstance(item, Mapping)
            and item.get("assetId")
            and item.get("assetDefinitionRevision")
        ]
    )
    shares = _exact_shares(archetype["departments"])
    department_by_label = {
        str(item[0]): f"dept-{_slug(str(item[0]))}"
        for item in archetype["departments"]
    }
    flattened_labels = [label for row in archetype["rows"] for label in row]
    process_by_label = {
        label: f"process-{index:02d}-{_slug(label)}"
        for index, label in enumerate(flattened_labels, start=1)
    }
    process_steps = []
    previous: str | None = None
    for label in flattened_labels:
        process_id = process_by_label[label]
        process_steps.append(
            {
                "processStepId": process_id,
                "label": f"Process {label}",
                "predecessorProcessStepIds": [] if previous is None else [previous],
                "departmentId": department_by_label[label],
                "stationRef": f"station-{_slug(label)}",
                "materialAndWipClasses": ["synthetic-work-content"],
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
            }
        )
        previous = process_id

    row_by_label = {
        label: row_index
        for row_index, row in enumerate(archetype["rows"], start=1)
        for label in row
    }
    department_specs = {
        str(item[0]): (str(item[1]), float(item[2]))
        for item in archetype["departments"]
    }
    departments = [
        {
            "departmentId": department_by_label[label],
            "label": label,
            "zoneType": department_specs[label][0],
            "areaShare": shares[label],
            "row": row_by_label[label],
            "processStepRefs": [process_by_label[label]],
            "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
        }
        for label in flattened_labels
    ]
    area_groups = []
    for group in archetype["groups"]:
        labels = list(group["labels"])
        rows = list(group["rows"])
        area_groups.append(
            {
                "areaGroupId": f"area-group-{group['key']}",
                "parentDepartmentId": department_by_label[group["parent"]],
                "labels": labels,
                "zoneTypes": list(group["zone_types"]),
                "proportions": [1.0 / len(labels)] * (len(labels) - 1)
                + [1.0 - ((len(labels) - 1) / len(labels))],
                "arrangement": "row_stack" if rows else "columns",
                "orientation": "horizontal",
                "rows": (
                    []
                    if not rows
                    else [
                        {"labels": list(row), "proportion": len(row) / len(labels)}
                        for row in rows
                    ]
                ),
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
            }
        )

    process_ids = [item["processStepId"] for item in process_steps]
    equipment = []
    for resource in archetype["resources"]:
        identity = _catalog_identity(catalog, str(resource["asset_id"]))
        spacing = resource.get("spacing")
        equipment.append(
            {
                "requirementId": str(resource["key"]),
                "selectedCatalogIdentity": identity,
                "catalogCandidates": [deepcopy(identity)],
                "quantity": _variant_quantity(resource, variant, variant_index),
                "targetArea": str(resource["target"]),
                "placementPattern": str(resource["pattern"]),
                "semanticOrientation": str(resource["orientation"]),
                "resourceRole": str(resource["role"]),
                "authoredSpacing": (
                    None
                    if spacing is None
                    else {
                        "value": round(float(spacing) * float(variant["spacing_scale"]), 6),
                        "unit": "m",
                        "evidenceRef": _SCENARIO_EVIDENCE_ID,
                    }
                ),
                "processStepRefs": process_ids,
                "placementDependencies": [],
                "evidenceRefs": [
                    _SCENARIO_EVIDENCE_ID,
                    _CATALOG_EVIDENCE_ID,
                ],
            }
        )

    routes = []
    for route in archetype["routes"]:
        route_areas = [route["source"], *route["via"], route["target"]]
        route_process_refs = [
            process_by_label[label]
            for label in flattened_labels
            if label in route_areas
        ]
        routes.append(
            {
                "routeId": f"route-{route['key']}",
                "scope": route["scope"],
                "label": route["label"],
                "routeKind": route["kind"],
                "width": route["width"],
                "sourceUnit": "m",
                "sourceArea": route["source"],
                "targetArea": route["target"],
                "viaAreas": list(route["via"]),
                "direction": route["direction"],
                "processStepRefs": route_process_refs,
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
            }
        )

    recipes = [
        {
            "recipe_id": str(recipe["key"]),
            "target_area": str(recipe["target"]),
            "member_batches": list(recipe["member_batches"]),
            "candidate_strategies": list(recipe["strategies"]),
            "selected_strategy_or_objective": str(recipe["objective"]),
            "authored_spacing": {
                "value": round(
                    float(recipe["spacing"]) * float(variant["spacing_scale"]), 6
                ),
                "unit": "m",
                "evidence_ref": _SCENARIO_EVIDENCE_ID,
            },
            "process_order": [],
            "interfaces": [],
            "evidence_refs": [_SCENARIO_EVIDENCE_ID],
        }
        for recipe in archetype["recipes"]
    ]
    families = [
        {
            "family_id": str(family["key"]),
            "source_recipe_or_cell": str(family["source"]),
            "target_areas": list(family["targets"]),
            "allowed_transform_mode": "translate_exact",
            "preserve_source": True,
            "conformance_requirements": ["exact_relative_geometry"],
            "composable_with": [],
            "evidence_refs": [_SCENARIO_EVIDENCE_ID],
        }
        for family in archetype["families"]
    ]
    markings = [
        {
            "communication_id": str(marking["key"]),
            "marking_type": str(marking["marking_type"]),
            "label": str(marking["label"]),
            "anchor_relationship": {
                "kind": "area",
                "target_area": str(marking["target"]),
                "route_label": None,
                "placement_id": None,
            },
            "count": int(marking["count"]),
            "rows": int(marking["rows"]),
            "columns": int(marking["columns"]),
            "pitch": {
                "along": float(marking["pitch_along"]),
                "across": float(marking["pitch_across"]),
            },
            "semantic_orientation": str(marking["orientation"]),
            "width": float(marking["width"]),
            "depth": float(marking["depth"]),
            "source_unit": "m",
            "dimension_evidence_refs": [_SCENARIO_EVIDENCE_ID],
        }
        for marking in archetype["markings"]
    ]

    width = round(float(archetype["base_size"][0]) * float(variant["size_scale"]), 6)
    depth = round(float(archetype["base_size"][1]) * float(variant["size_scale"]), 6)
    display_name = f"{variant['label']} {archetype['display_name']} Synthetic Prototype"
    package = {
        "schemaVersion": FACILITY_PLANNING_PACKAGE_SCHEMA,
        "packageId": package_id,
        "displayName": display_name,
        "productRef": {
            "productId": f"SYN-{archetype_id.upper()}",
            "productRevision": scenario_revision,
            "displayName": f"Synthetic {archetype['display_name']} Product Family",
        },
        "sourcePackageRefs": [
            {
                "sourceId": f"synthetic-scenario-{archetype_id}",
                "sourceRevision": scenario_revision,
                "sourceType": "synthetic_facility_scenario",
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
                "evidenceId": _SCENARIO_EVIDENCE_ID,
                "sourceType": "synthetic_facility_scenario_generator",
                "sourceLocator": f"synthetic://facility-planning/{archetype_id}/{variant_id}",
                "sourceRevision": scenario_revision,
                "evidenceClass": "SYNTHETIC_DEMO",
                "authority": "illustrative",
                "reviewStatus": "pending",
                "synthetic": True,
            },
            {
                "evidenceId": _CATALOG_EVIDENCE_ID,
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
            "width": width,
            "depth": depth,
            "sourceUnit": "m",
            "displayName": display_name,
            "gridSize": 1.0,
            "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
        },
        "planningInputs": [
            {
                "inputId": "synthetic-process-routing",
                "kind": "process_routing",
                "statement": "The process sequence is illustrative and exists only to exercise facility-planning behavior.",
                "value": process_ids,
                "unit": None,
                "subjectRefs": [package_id],
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
            },
            {
                "inputId": "synthetic-demand",
                "kind": "demand_or_takt",
                "statement": "The scenario intensity is synthetic and does not establish production demand or capacity.",
                "value": int(round(8 * float(variant["quantity_scale"]))),
                "unit": "illustrative_units_per_shift",
                "subjectRefs": [package_id],
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
            },
            {
                "inputId": "synthetic-capability-map",
                "kind": "capability_mapping",
                "statement": "Exact catalog assets are bound for deterministic physical-fit evaluation only.",
                "value": [item["requirementId"] for item in equipment],
                "unit": None,
                "subjectRefs": process_ids,
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID, _CATALOG_EVIDENCE_ID],
            },
            {
                "inputId": "synthetic-adjacency",
                "kind": "adjacency_or_separation",
                "statement": "Department rows and routes are authored scenario relationships, not safety or compliance requirements.",
                "value": [item["routeId"] for item in routes],
                "unit": None,
                "subjectRefs": [item["departmentId"] for item in departments],
                "evidenceRefs": [_SCENARIO_EVIDENCE_ID],
            },
        ],
        "processSteps": process_steps,
        "departments": departments,
        "areaGroups": area_groups,
        "equipmentRequirements": equipment,
        "routes": routes,
        "cellRecipes": recipes,
        "moduleFamilies": families,
        "floorCommunication": markings,
        "presentationIntent": {
            "fit_to_occupied_content": True,
            "semantic_zoom": True,
            "overview_label_priority": "macro_then_child",
            "plan_layers": ["departments", "routes", "resources", "markings"],
            "three_d_layers": ["shell", "resources", "routes"],
        },
        "unresolvedFindings": [],
    }
    canonical = canonicalize_facility_planning_package(package)
    if canonical["authority"] != {
        "knowledgeStatus": "inferred",
        "authority": "illustrative",
        "reviewStatus": "pending",
        "productionEligible": False,
        "planningClaim": "illustrative_prototype",
        "reviewReceiptId": None,
    }:
        raise SyntheticFacilityCorpusError(
            "synthetic_facility_authority_drift",
            "Synthetic package authority differs from the fixed illustrative boundary.",
        )
    return canonical


def _base_layout(package_id: str) -> dict[str, Any]:
    return create_layout_document(
        layout_id=f"fl-{package_id}",
        display_name="Blank Synthetic Facility",
        association={"siteId": "site-synthetic-corpus", "areaId": package_id},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "synthetic-corpus-origin",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "synthetic-corpus-shell",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "synthetic-corpus-policy",
            "policySetRevision": "c" * 64,
        },
        created_at=_FIXED_CREATED_AT,
    )


def compile_synthetic_facility_example(
    package: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile and execute one package without granting Save or authority."""

    package_for_compile = deepcopy(dict(package))
    compiled = compile_facility_planning_package(package_for_compile, asset_catalog)
    if compiled["blockingFindingCount"]:
        raise SyntheticFacilityCorpusError(
            "synthetic_facility_package_blocked",
            "A positive synthetic package produced blocking planning findings.",
            details={
                "packageId": package_for_compile.get("packageId"),
                "findings": compiled["findings"],
            },
        )
    program = compiled["facilityProgram"]
    base = _base_layout(str(package_for_compile["packageId"]))
    plan = compile_facility_program_operation_plan(program, base, asset_catalog)
    result = execute_facility_program_operation_plan(base, plan)
    if result["saved"] or result["authority"].get("production_eligible"):
        raise SyntheticFacilityCorpusError(
            "synthetic_facility_authority_drift",
            "Synthetic corpus execution crossed the unsaved prototype boundary.",
        )
    return {
        "package": canonicalize_facility_planning_package(package_for_compile),
        "compiled": compiled,
        "operationPlan": plan,
        "execution": result,
    }


def synthetic_facility_intent_cases(
    package: Mapping[str, Any], metadata: Mapping[str, Any]
) -> list[dict[str, Any]]:
    package_id = str(package["packageId"])
    display_name = str(package["displayName"])
    archetype = str(metadata["archetypeId"])
    prompts = (
        f"Build the illustrative {display_name} from planning package {package_id}. Keep it unsaved.",
        f"Create an unsaved synthetic {archetype.replace('-', ' ')} facility using {package_id}; do not release it.",
        f"Generate the revision-bound prototype in {package_id} and leave final Save for me.",
    )
    return [
        {
            "caseId": f"intent-{package_id}-{index}",
            "prompt": prompt,
            "expectedAction": "generate_facility_planning_prototype_draft",
            "expectedPlanningPackageId": package_id,
            "expectedExecutionMode": "authorized_draft_run",
            "expectedAuthority": "illustrative",
            "expectedSaved": False,
            "split": metadata["split"],
        }
        for index, prompt in enumerate(prompts, start=1)
    ]


def build_synthetic_facility_corpus(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    result = []
    for archetype_index, archetype in enumerate(_ARCHETYPES):
        for variant_index, variant in enumerate(_VARIANTS):
            package = build_synthetic_facility_planning_package(
                str(archetype["archetype_id"]),
                str(variant["variant_id"]),
                asset_catalog,
            )
            metadata = {
                "archetypeId": str(archetype["archetype_id"]),
                "variantId": str(variant["variant_id"]),
                "split": _split(archetype_index, variant_index),
                "traits": list(archetype["traits"]),
            }
            result.append({"package": package, "metadata": metadata})
    return tuple(result)


def _negative_mutations() -> tuple[dict[str, Any], ...]:
    return (
        {"caseId": "synthetic-controlled-evidence", "layer": "package", "expectedCode": "facility_planning_synthetic_authority_forbidden"},
        {"caseId": "illustrative-production-promotion", "layer": "package", "expectedCode": "facility_planning_production_authority_missing"},
        {"caseId": "department-share-overflow", "layer": "package", "expectedCode": "facility_planning_department_share_invalid"},
        {"caseId": "unknown-process-predecessor", "layer": "package", "expectedCode": "facility_planning_process_predecessor_unknown"},
        {"caseId": "unknown-equipment-area", "layer": "compile", "expectedCode": "facility_planning_target_area_unknown"},
        {"caseId": "missing-equipment-quantity", "layer": "compile", "expectedCode": "facility_planning_equipment_quantity_missing"},
        {"caseId": "stale-asset-revision", "layer": "compile", "expectedCode": "facility_planning_catalog_revision_unavailable"},
        {"caseId": "missing-route-width", "layer": "compile", "expectedCode": "facility_planning_route_width_missing"},
        {"caseId": "unknown-route-area", "layer": "compile", "expectedCode": "facility_planning_route_area_unknown"},
        {"caseId": "unknown-route-process", "layer": "compile", "expectedCode": "facility_planning_route_process_unknown"},
        {"caseId": "unsupported-placement-pattern", "layer": "compile", "expectedCode": "facility_planning_pattern_unsupported"},
        {"caseId": "unplaceable-resource-density", "layer": "execution", "expectedCode": "facility_program_resource_set_unplaceable"},
    )


def _mutate_negative(package: dict[str, Any], case_id: str) -> None:
    if case_id == "synthetic-controlled-evidence":
        next(
            item
            for item in package["evidenceRegister"]
            if item.get("synthetic") is True
        )["authority"] = "controlled"
        return
    if case_id == "illustrative-production-promotion":
        package["authority"]["productionEligible"] = True
        return
    if case_id == "department-share-overflow":
        package["departments"][0]["areaShare"] += 0.1
        return
    if case_id == "unknown-process-predecessor":
        package["processSteps"][0]["predecessorProcessStepIds"] = ["missing-process"]
        return
    if case_id == "unknown-equipment-area":
        package["equipmentRequirements"][0]["targetArea"] = "Missing Area"
        return
    if case_id == "missing-equipment-quantity":
        package["equipmentRequirements"][0]["quantity"] = None
        return
    if case_id == "stale-asset-revision":
        package["equipmentRequirements"][0]["selectedCatalogIdentity"][
            "assetDefinitionRevision"
        ] = "f" * 64
        return
    if case_id == "missing-route-width":
        package["routes"][0]["width"] = None
        return
    if case_id == "unknown-route-area":
        package["routes"][0]["targetArea"] = "Missing Area"
        return
    if case_id == "unknown-route-process":
        package["routes"][0]["processStepRefs"] = ["missing-process"]
        return
    if case_id == "unsupported-placement-pattern":
        package["equipmentRequirements"][0]["placementPattern"] = "unsupported_pattern"
        return
    if case_id == "unplaceable-resource-density":
        package["facilityEnvelope"]["width"] = 20
        package["facilityEnvelope"]["depth"] = 20
        for item in package["equipmentRequirements"]:
            item["quantity"] = max(100, int(item["quantity"] or 0))
        package["floorCommunication"] = []
        return
    raise AssertionError(case_id)


def evaluate_synthetic_facility_negative_cases(
    base_package: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove illustrative authority and invalid scenarios fail closed."""

    results = []
    for case in _negative_mutations():
        package = deepcopy(dict(base_package))
        _mutate_negative(package, str(case["caseId"]))
        base = _base_layout(str(package["packageId"]))
        base_revision = layout_revision(base)
        actual_code = ""
        try:
            canonical = canonicalize_facility_planning_package(package)
            compiled = compile_facility_planning_package(canonical, asset_catalog)
            finding_codes = {
                str(item.get("code") or "")
                for item in compiled.get("findings", [])
                if item.get("blocking")
            }
            if case["layer"] == "compile":
                actual_code = str(case["expectedCode"])
                if actual_code not in finding_codes:
                    raise AssertionError(
                        f"{case['caseId']} did not produce {actual_code}: {finding_codes}"
                    )
            elif case["layer"] == "execution":
                if compiled["blockingFindingCount"]:
                    raise AssertionError(
                        f"{case['caseId']} blocked before its execution test"
                    )
                plan = compile_facility_program_operation_plan(
                    compiled["facilityProgram"], base, asset_catalog
                )
                execute_facility_program_operation_plan(base, plan)
                raise AssertionError(
                    f"{case['caseId']} unexpectedly produced a draft"
                )
            else:
                raise AssertionError(
                    f"{case['caseId']} unexpectedly passed package validation"
                )
        except (
            FacilityPlanningPackageError,
            FacilityProgramError,
            FacilityProgramExecutionError,
            FacilityIndustrialPatternError,
        ) as exc:
            actual_code = str(getattr(exc, "code", ""))
            if actual_code != case["expectedCode"]:
                raise AssertionError(
                    f"{case['caseId']} failed with {actual_code}, expected {case['expectedCode']}"
                ) from exc
        results.append(
            {
                **case,
                "status": "expected_refusal",
                "actualCode": actual_code,
                "baseRevisionUnchanged": layout_revision(base) == base_revision,
            }
        )
    core = {
        "schemaVersion": SYNTHETIC_FACILITY_NEGATIVE_SCHEMA,
        "caseCount": len(results),
        "passedCount": sum(item["status"] == "expected_refusal" for item in results),
        "cases": results,
    }
    core["evaluationRevision"] = _revision(core)
    return core


def evaluate_synthetic_facility_corpus(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile all 48 packages and return deterministic layouts and evidence."""

    examples = []
    intent_cases = []
    for record in build_synthetic_facility_corpus(asset_catalog):
        package = record["package"]
        metadata = record["metadata"]
        compiled = compile_synthetic_facility_example(package, asset_catalog)
        execution = compiled["execution"]
        program = compiled["compiled"]["facilityProgram"]
        intent_cases.extend(synthetic_facility_intent_cases(package, metadata))
        examples.append(
            {
                "package": package,
                "metadata": metadata,
                "packageRevision": compiled["compiled"]["planningPackageRevision"],
                "compileRevision": compiled["compiled"]["compileRevision"],
                "facilityProgramRevision": _revision(program),
                "operationPlanRevision": compiled["operationPlan"]["planRevision"],
                "layoutRevision": execution["draftLayoutRevision"],
                "counts": execution["counts"],
                "receiptCount": len(execution["receiptChain"]),
                "saved": execution["saved"],
                "layout": execution["draftLayout"],
            }
        )

    negative = evaluate_synthetic_facility_negative_cases(
        examples[0]["package"], asset_catalog
    )
    split_counts = {
        split: sum(item["metadata"]["split"] == split for item in examples)
        for split in ("development", "evaluation", "heldout")
    }
    core = {
        "schemaVersion": SYNTHETIC_FACILITY_EVALUATION_SCHEMA,
        "corpusId": "facility-planning-synthetic-corpus-v1",
        "authority": {
            "authority": "illustrative",
            "reviewStatus": "pending",
            "productionEligible": False,
            "claimBoundary": (
                "Synthetic packages exercise planning behavior only and do not establish "
                "production, safety, capacity, compliance, or regulatory requirements."
            ),
        },
        "summary": {
            "archetypeCount": len(_ARCHETYPES),
            "variantCount": len(_VARIANTS),
            "packageCount": len(examples),
            "layoutCount": len(examples),
            "intentCaseCount": len(intent_cases),
            "negativeCaseCount": negative["caseCount"],
            "positivePassedCount": len(examples),
            "negativePassedCount": negative["passedCount"],
            "splitCounts": split_counts,
        },
        "examples": examples,
        "intentCases": intent_cases,
        "negativeEvaluation": negative,
    }
    revision_view = deepcopy(core)
    for item in revision_view["examples"]:
        item.pop("package", None)
        item.pop("layout", None)
    core["corpusRevision"] = _revision(revision_view)
    return core


__all__ = [
    "SYNTHETIC_FACILITY_CORPUS_SCHEMA",
    "SYNTHETIC_FACILITY_EVALUATION_SCHEMA",
    "SYNTHETIC_FACILITY_NEGATIVE_SCHEMA",
    "SyntheticFacilityCorpusError",
    "build_synthetic_facility_corpus",
    "build_synthetic_facility_planning_package",
    "compile_synthetic_facility_example",
    "evaluate_synthetic_facility_corpus",
    "evaluate_synthetic_facility_negative_cases",
    "synthetic_facility_archetypes",
    "synthetic_facility_intent_cases",
    "synthetic_facility_variants",
]
