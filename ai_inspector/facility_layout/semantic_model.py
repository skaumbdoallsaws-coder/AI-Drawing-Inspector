"""Deterministic semantic projections for revision-bound Facility Layouts.

The persisted layout remains the spatial authority. This module adds a
read-only engineering vocabulary, exact geometry-derived metrics, and clearly
labelled manufacturing priors so agents can reason about the facility without
promoting inference into authored or validated fact.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import heapq
import math
import re
from typing import Any, Mapping, Sequence

try:
    from shapely import affinity as shapely_affinity
    from shapely.errors import GEOSException
    from shapely.geometry import LineString, Point, Polygon
    from shapely.geometry.base import BaseGeometry
    from shapely.ops import nearest_points, unary_union
    from shapely.validation import make_valid
except ImportError:  # pragma: no cover - exercised by deployment preflight.
    shapely_affinity = None
    GEOSException = RuntimeError
    LineString = None
    Point = None
    Polygon = None
    BaseGeometry = Any
    unary_union = None
    nearest_points = None
    make_valid = None

from .spatial import (
    GEOMETRY_EPSILON,
    point_in_polygon,
    polygon_area,
    polygon_boundary_distance,
    polygon_bounds,
    polygon_contains_polygon,
    polygons_intersect,
    segments_intersect,
)


FACILITY_SEMANTIC_MODEL_VERSION = 1
SQUARE_METERS_TO_SQUARE_FEET = 10.763910416709722
EVIDENCE_STATUSES = ("authored", "derived", "inferred", "unknown")
_GEOMETRY_ENGINE_AVAILABLE = all(
    value is not None
    for value in (LineString, Polygon, unary_union, make_valid)
)


def _cell_strategy(
    strategy_id: str,
    label: str,
    intent: str,
    *,
    best_for: Sequence[str],
    advantages: Sequence[str],
    tradeoffs: Sequence[str],
    avoid_when: Sequence[str],
    validators: Sequence[str],
    variants: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "strategyId": strategy_id,
        "label": label,
        "command": {"commandId": "cell-layout", "preset": strategy_id},
        "semanticIntent": intent,
        "bestFor": list(best_for),
        "advantages": list(advantages),
        "tradeoffs": list(tradeoffs),
        "avoidWhen": list(avoid_when),
        "requiredInputs": [
            "process sequence",
            "equipment footprints",
            "available zone geometry",
            "material entry and exit",
            "operator and maintenance access requirements",
        ],
        "validators": list(validators),
        "variants": [deepcopy(dict(item)) for item in variants],
        "knowledgeEvidenceStatus": "inferred",
        "qualification": (
            "General manufacturing-layout prior; deterministic geometry, "
            "current policy, and asset evidence decide whether it is feasible."
        ),
    }


_COMMON_CELL_VALIDATORS = (
    "selected assets fit the target zone",
    "asset footprints do not overlap",
    "authored clearance envelopes remain unobstructed",
    "material and operator access remain connected",
    "manual and locked placements remain preserved",
)


CELL_LAYOUT_STRATEGIES = (
    _cell_strategy(
        "line",
        "Straight / I-line",
        "Arrange sequential work in one legible direction.",
        best_for=(
            "simple sequential processes",
            "one-direction material flow",
            "long or expandable rectangular zones",
        ),
        advantages=("clear process order", "simple expansion along the line"),
        tradeoffs=("can require more floor length", "end-to-end travel can grow"),
        avoid_when=(
            "input and output must share one side",
            "the available zone cannot support the required line length",
        ),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "l",
        "L-shaped cell",
        "Turn a sequential process around a corner or connect two access faces.",
        best_for=(
            "corner-shaped available space",
            "different input and output faces",
            "a process that needs one controlled turn",
        ),
        advantages=("uses corner space", "preserves a readable sequence"),
        tradeoffs=("the corner can become a pinch point",),
        avoid_when=("the turn obstructs handling or rear service access",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "u",
        "U-shaped cell",
        "Wrap sequential work around a compact operator and material envelope.",
        best_for=(
            "short operator travel",
            "one or a few operators tending sequential stations",
            "input and output on the same general side",
            "flexible staffing in a compact cell",
        ),
        advantages=(
            "compact flow",
            "close input and output",
            "good visibility across the cell",
        ),
        tradeoffs=(
            "the opening and inner aisle require deliberate access planning",
            "large equipment may leave insufficient rear service space",
        ),
        avoid_when=(
            "forklift traffic must pass through the cell",
            "equipment requires independent rear access that the U cannot preserve",
        ),
        validators=_COMMON_CELL_VALIDATORS,
        variants=(
            {
                "variantId": "invert_u_opening",
                "parameter": "invertU",
                "semanticUse": (
                    "Place the U opening on the opposite side to match authored "
                    "entry, exit, aisle, or operator access intent."
                ),
            },
        ),
    ),
    _cell_strategy(
        "grid",
        "Grid",
        "Arrange repeated resources in a regular row-and-column system.",
        best_for=(
            "modular repeated equipment",
            "large structured production halls",
            "standardized spacing and expansion",
        ),
        advantages=("predictable organization", "simple repetition and counting"),
        tradeoffs=("may ignore process sequence unless rows are assigned deliberately",),
        avoid_when=("the process depends on a non-grid sequence or irregular access",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "parallel",
        "Parallel rows",
        "Place repeated machines, racks, or stations along shared aisles.",
        best_for=(
            "machine halls",
            "pallet-rack storage",
            "repeated workstations",
            "shared longitudinal access aisles",
        ),
        advantages=("clear shared aisles", "efficient repeated placement"),
        tradeoffs=("cross-aisles and row-end maneuvering still need space",),
        avoid_when=("row ends cannot remain connected to handling routes",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "serpentine",
        "Serpentine flow",
        "Fold a long sequence into alternating passes within a bounded area.",
        best_for=("long sequential processes", "bounded rectangular zones"),
        advantages=("packs process length into a compact footprint",),
        tradeoffs=("adds turns", "can make flow and supervision less direct"),
        avoid_when=("turning or backtracking conflicts with material handling",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "loop",
        "Loop / closed cell",
        "Arrange cyclic or recirculating work around a closed path.",
        best_for=("cyclic processes", "recirculation", "return near the start"),
        advantages=("supports cyclic adjacency", "keeps related work together"),
        tradeoffs=("interior and perimeter access require separate review",),
        avoid_when=("a closed arrangement blocks egress, loading, or service access",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "spine",
        "Spine and branch",
        "Connect multiple work areas to one shared process or logistics spine.",
        best_for=(
            "departments sharing one material corridor",
            "feeder stations",
            "modular branch expansion",
        ),
        advantages=("clear shared backbone", "branches can be added incrementally"),
        tradeoffs=("the spine becomes a single critical circulation element",),
        avoid_when=("one shared spine would create an unsupported bottleneck",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "herringbone",
        "Herringbone",
        "Angle repeated resources toward a shared aisle or interface.",
        best_for=(
            "angled access to a common aisle",
            "directional loading or parking supported by authored interfaces",
        ),
        advantages=("can improve approach orientation",),
        tradeoffs=("uses width differently from square rows", "clearance is less intuitive"),
        avoid_when=(
            "asset facing or loading sides are unknown",
            "angled swept envelopes cannot be validated",
        ),
        validators=_COMMON_CELL_VALIDATORS,
    ),
    _cell_strategy(
        "cluster",
        "Cluster",
        "Keep mutually related resources close without imposing a strict line.",
        best_for=(
            "low-volume or high-variety work",
            "inspection and support operations",
            "strong adjacency with weak sequence requirements",
        ),
        advantages=("flexible adjacency", "adapts to mixed footprints"),
        tradeoffs=("flow is less self-evident", "spacing needs deliberate validation"),
        avoid_when=("a strict, traceable process sequence is required",),
        validators=_COMMON_CELL_VALIDATORS,
    ),
)

CELL_FEASIBILITY_STRATEGIES = tuple(
    item["strategyId"] for item in CELL_LAYOUT_STRATEGIES
)


def _command(
    command_id: str,
    label: str,
    group: str,
    effect: str,
    scope: str,
    semantic_use: str,
    *,
    preconditions: Sequence[str] = (),
    multi_select: bool = False,
    agent_availability: str = "ui_only",
) -> dict[str, Any]:
    return {
        "commandId": command_id,
        "label": label,
        "group": group,
        "effect": effect,
        "scope": scope,
        "semanticUse": semantic_use,
        "preconditions": list(preconditions),
        "supportsMultipleSelection": multi_select,
        "agentAvailability": agent_availability,
    }


FACILITY_COMMAND_SEMANTICS = (
    _command("assets", "Assets", "create", "read", "catalog", "Browse authorized layout resources."),
    _command("select", "Select", "selection", "viewport", "selection", "Select and move authored layout entities."),
    _command("pan", "Pan", "selection", "viewport", "viewport", "Navigate the Plan view without changing world geometry."),
    _command("rectangle-zone", "Rectangle Zone", "create", "draft_edit", "zone", "Author a rectangular operating or support region."),
    _command("polygon-zone", "Polygon Zone", "create", "draft_edit", "zone", "Author an irregular operating or support region."),
    _command("bulk-zones", "Bulk Zones", "create", "draft_edit", "zone_set", "Create several named zones from exact dimensions."),
    _command("aisle", "Aisle", "create", "draft_edit", "route", "Author a semantic corridor with a centerline, width, and traffic role."),
    _command("floor-marking", "Floor Marking", "create", "draft_edit", "marking", "Author communication paint such as arrows, lanes, crossings, or keep-clear markings."),
    _command("rotate", "Rotate 90", "arrange", "draft_edit", "selection", "Rotate selected placements by a quarter turn.", preconditions=("one or more unlocked placements",), multi_select=True),
    _command("duplicate", "Duplicate", "arrange", "draft_edit", "selection", "Create independent copies while preserving relative geometry for a group.", preconditions=("one or more duplicable entities",), multi_select=True),
    _command("delete", "Delete", "arrange", "draft_edit", "selection", "Remove selected authored entities after reference checks.", preconditions=("selection is not protected by references",), multi_select=True),
    _command("clear-all", "Clear All", "arrange", "draft_edit", "layout", "Remove all authored layout content after explicit confirmation."),
    _command("lock", "Lock", "arrange", "draft_edit", "selection", "Prevent automatic or direct movement of selected placements.", preconditions=("one or more placements",), multi_select=True),
    _command("align", "Align", "position", "draft_edit", "selection", "Align selected footprint edges or centers.", preconditions=("at least two placements",), multi_select=True),
    _command("distribute", "Distribute", "position", "draft_edit", "selection", "Create equal center spacing or equal clear gaps among selected placements.", preconditions=("at least three placements",), multi_select=True),
    _command("relative", "Relative", "position", "draft_edit", "selection", "Position one placement relative to a reference placement.", preconditions=("reference and moving placements",), multi_select=True),
    _command("distance", "Distance", "position", "draft_edit", "selection", "Measure or set edge or center distance between two placements.", preconditions=("exactly two placements",), multi_select=True),
    _command("offset", "Offset", "position", "draft_edit", "selection", "Move or copy a selection by an exact world-space offset.", preconditions=("one or more placements",), multi_select=True),
    _command("linear-pattern", "Linear Pattern", "pattern", "draft_edit", "selection", "Repeat one asset or a complete seed group along a direction.", preconditions=("one or more seed entities",), multi_select=True),
    _command("circular-pattern", "Circular Pattern", "pattern", "draft_edit", "selection", "Repeat one asset or a complete seed group around a center.", preconditions=("one or more seed entities and a center",), multi_select=True),
    _command("perimeter-pattern", "Perimeter", "pattern", "draft_edit", "selection", "Repeat guarding or another module around a rectangular perimeter.", preconditions=("one or more seed entities and perimeter dimensions",), multi_select=True),
    _command("cell-layout", "Cell Layout", "pattern", "draft_edit", "selection", "Arrange selected equipment with a named manufacturing-cell strategy.", preconditions=("selected resources and target dimensions",), multi_select=True),
    _command("create-cell-group", "Create Cell", "pattern", "draft_edit", "selection", "Create a persistent named workcell envelope from selected resources.", preconditions=("selected placements",), multi_select=True),
    _command("ungroup-cell", "Ungroup", "pattern", "draft_edit", "workcell", "Remove a workcell envelope without deleting its member equipment."),
    _command("vertical-stack", "Stack", "pattern", "draft_edit", "selection", "Stack compatible items vertically from authoritative geometry.", preconditions=("stack-compatible selected items",), multi_select=True),
    _command("surface-stack", "On Surface", "pattern", "draft_edit", "selection", "Attach multiple children to independent local X/Z positions on a support surface.", preconditions=("one support and one or more compatible child items",), multi_select=True),
    _command("mirror", "Mirror", "pattern", "draft_edit", "selection", "Mirror assets, markings, or a complete cell across a grid or construction axis.", preconditions=("selection and mirror axis",), multi_select=True),
    _command("swap", "Swap", "pattern", "draft_edit", "selection", "Exchange the centers of two entities or two complete cells.", preconditions=("exactly two compatible entities",), multi_select=True),
    _command("undo", "Undo", "history", "draft_edit", "layout", "Reverse the previous draft edit."),
    _command("redo", "Redo", "history", "draft_edit", "layout", "Restore the previously reversed draft edit."),
    _command("fit", "Fit Facility", "layout", "viewport", "viewport", "Frame the complete facility boundary."),
    _command("fit-layout", "Fit Layout", "layout", "viewport", "viewport", "Frame currently placed layout content."),
    _command("top-view", "Top View", "layout", "viewport", "viewport", "Orient the 3D camera for direct Plan comparison."),
    _command("auto-arrange", "Auto Arrange", "layout", "draft_edit", "selection", "Generate a deterministic arrangement for eligible auto placements.", preconditions=("eligible auto placements and a supported strategy",), multi_select=True),
    _command("save", "Save", "document", "persistent_save", "layout", "Validate and persist the current authored layout after an explicit user command.", agent_availability="explicit_user_commit"),
    _command("orbit", "Orbit", "3d_navigation", "viewport", "viewport", "Inspect the scene from an unconstrained exterior camera."),
    _command("walkthrough", "Walkthrough", "3d_navigation", "viewport", "viewport", "Inspect human-scale access using standing, crouching, and crawling postures."),
    _command("drone", "Drone", "3d_navigation", "viewport", "viewport", "Navigate large facilities freely in X/Y/Z with assisted collision handling."),
    _command("record", "Record", "3d_presentation", "viewport_capture", "viewport", "Record the rendered 3D viewport for review or training."),
)


AGENT_TOOL_SEMANTICS = (
    _command("search_industrial_assets", "Search industrial assets", "agent_read", "read", "catalog", "Find trusted planning-ready assets by category, capability, or text.", agent_availability="sage_read"),
    _command("inspect_facility_entities", "Inspect facility entities", "agent_read", "read", "layout", "Read exact revision-bound placements, zones, markings, routes, or utilities.", agent_availability="sage_read"),
    _command("inspect_facility_region", "Inspect facility region", "agent_read", "read", "region", "Read one stable zone or shell feature without model-authored geometry.", agent_availability="sage_read"),
    _command("inspect_facility_findings", "Inspect facility findings", "agent_read", "read", "diagnostics", "Read deterministic validation findings by stable ID or code.", agent_availability="sage_read"),
    _command("inspect_process_bindings", "Inspect process bindings", "agent_read", "read", "process_binding", "Read authored process-to-resource relationships without inferring process order from proximity.", agent_availability="sage_read"),
    _command("inspect_facility_semantics", "Inspect facility semantics", "agent_read", "read", "semantic_map", "Read deterministic facility meaning, derived metrics, command knowledge, and cell strategy knowledge.", agent_availability="sage_read"),
    _command("inspect_pattern_provenance", "Inspect pattern provenance", "agent_read", "read", "pattern_provenance", "Read authored linear, circular, or perimeter pattern seeds, parameters, members, and subsequent deviations without changing the layout.", agent_availability="sage_read"),
    _command("inspect_cell_layout_provenance", "Inspect cell-layout provenance", "agent_read", "read", "cell_layout_provenance", "Read an authored cell-layout strategy, creation parameters, members, edit history, and current geometric classification without changing the layout.", agent_availability="sage_read"),
    _command("analyze_facility_spatial", "Analyze facility spatial state", "agent_read", "read", "spatial_analysis", "Resolve human entities and calculate exact clearances, protected-area intrusions, route crossings and access, known usable route-width profiles, connected free regions, layout provenance, operator travel, authored asset/cell access, Drone passage clearance, and mounted 2D/3D transform consistency.", agent_availability="sage_read"),
    _command("analyze_facility_fit", "Analyze facility fit", "agent_read", "read", "spatial_fit", "Test one exact revisioned asset in one authored zone with bounded deterministic placement and validation; never represent this as maximum or production capacity.", agent_availability="sage_read"),
    _command("preview_facility_move", "Preview exact Facility move", "agent_preview", "preview", "selection", "Translate selected or exactly resolved placements by a cardinal distance in an authoritative validated unsaved draft while preserving rotation.", agent_availability="sage_preview"),
    _command("build_facility_layout_preview", "Build Facility Layout preview", "agent_preview", "preview", "layout", "Compile one semantic plan into a synchronized, validated 2D/3D ghost preview.", agent_availability="sage_preview"),
    _command("generate_facility_departments_draft", "Generate facility and departments", "agent_preview", "preview", "layout", "Build or explicitly replace a facility envelope and labeled macro departments through a resumable deterministic draft run; the saved layout remains unchanged until Save.", agent_availability="sage_preview"),
    _command("present_chat_visualization", "Present visualization", "presentation", "read", "chat", "Render an InspectorPro-owned chart from exact supplied values.", agent_availability="sage_presentation"),
    _command("present_chat_table", "Present table", "presentation", "read", "chat", "Render an InspectorPro-owned structured table from exact supplied values.", agent_availability="sage_presentation"),
)


_ZONE_RULES = (
    ("inspection_packaging_finished_goods", ("inspection packing", "inspection packaging", "packing finished goods"), "Inspection, packaging, and finished-goods handling", ("quality_control", "packaging", "outbound_staging")),
    ("receiving_raw_material", ("receiving", "raw material"), "Inbound receiving and raw-material staging or storage", ("inbound_receiving", "raw_material_storage")),
    ("machining", ("machining", "machine hall", "lathe", "turning"), "Primary and secondary machining with local production support", ("production", "machining")),
    ("automation_robotics", ("automation", "robot cell", "robotic"), "Automated production and guarded robot-cell operations", ("production", "automation")),
    ("assembly_kitting", ("assembly kitting", "assembly + kitting"), "Assembly and kit preparation", ("assembly", "kitting")),
    ("material_handling_maintenance", ("material handling maintenance", "material handling + maintenance"), "Material-handling, maintenance, and support operations", ("material_handling", "maintenance")),
    ("finished_goods", ("finished goods",), "Finished-goods storage and outbound staging", ("storage", "outbound_staging")),
    ("shipping", ("shipping", "dispatch"), "Outbound shipping and dispatch", ("shipping", "outbound_logistics")),
    ("receiving", ("receiving", "inbound"), "Inbound receiving and staging", ("inbound_receiving", "staging")),
    ("storage", ("warehouse", "storage", "pallet rack", "rack row"), "Material or product storage", ("storage",)),
    ("assembly", ("assembly",), "Assembly operations", ("assembly", "production")),
    ("kitting", ("kitting",), "Kit preparation and point-of-use material staging", ("kitting", "staging")),
    ("inspection_quality", ("inspection", "quality", "metrology"), "Inspection and quality-control operations", ("quality_control",)),
    ("packaging", ("packaging", "packing"), "Packaging operations", ("packaging",)),
    ("maintenance", ("maintenance", "tooling", "utilities"), "Maintenance, tooling, or utility support", ("maintenance", "support")),
    ("equipment_parking", ("equipment parking", "forklift parking", "vehicle parking"), "Material-handling equipment parking or staging", ("parking", "material_handling")),
    ("workcell", ("manufacturing cell", "assembly cell", "workcell", "cell a"), "Contained manufacturing-cell operations", ("production_cell",)),
    ("aisle", ("aisle", "walkway", "boulevard", "corridor"), "Facility circulation corridor", ("circulation",)),
    ("safety_restricted", ("safety", "restricted", "keep clear", "hazard"), "Safety, exclusion, or controlled-access region", ("safety",)),
    ("staging", ("staging", "wip", "buffer"), "Material staging or work-in-process buffer", ("staging",)),
    ("expansion", ("expansion", "future"), "Reserved future expansion area", ("expansion",)),
)


_ASSET_RULES = (
    ("cnc_machining_center", ("cnc", "machining center", "milling machine", "boring machine"), ("production_equipment", "machining"), ("machining",), ("operator_access", "material_transfer", "maintenance_access"), ("line", "parallel", "u", "l")),
    ("lathe_turning_center", ("lathe", "turning center"), ("production_equipment", "turning"), ("machining",), ("operator_access", "material_transfer", "maintenance_access"), ("line", "parallel", "u")),
    ("industrial_robot", ("robot", "fanuc", "abb irb", "adtech"), ("automation_equipment", "production_equipment"), ("automation_robotics",), ("guarded_access", "load_unload_access", "maintenance_access"), ("grid", "parallel", "cluster")),
    ("safety_guarding", ("guard", "fence", "safety panel", "gate"), ("safeguarding",), ("automation_robotics", "safety_restricted"), ("controlled_entry", "inspection_access"), ("perimeter",)),
    ("pallet_rack", ("pallet rack", "rack frame", "warehouse rack", "racking"), ("storage_system",), ("storage", "receiving_raw_material", "finished_goods"), ("material_handling_access", "aisle_access", "row_end_access"), ("parallel", "grid")),
    ("pallet_or_container", ("pallet", "tote", "bin", "container", "box"), ("material_storage", "staging_resource"), ("storage", "staging", "receiving_raw_material"), ("handling_access",), ("grid", "parallel", "cluster")),
    ("forklift_or_lift_truck", ("forklift", "fork truck", "lift truck", "telehandler"), ("material_handling_vehicle",), ("material_handling_maintenance", "receiving_raw_material", "shipping"), ("travel_route", "parking_space", "maneuvering_space"), ("grid", "parallel")),
    ("conveyor", ("conveyor",), ("material_transfer_equipment",), ("production", "automation_robotics", "packaging"), ("transfer_interfaces", "maintenance_access"), ("line", "l", "serpentine", "spine")),
    ("workbench_or_table", ("workbench", "work table", "worktable", "table", "assembly bench"), ("workstation", "support_surface"), ("assembly", "kitting", "inspection_quality", "maintenance"), ("operator_access", "material_staging"), ("line", "u", "l", "cluster")),
    ("inspection_equipment", ("inspection", "cmm", "metrology", "gauge"), ("inspection_equipment", "quality_control"), ("inspection_quality",), ("operator_access", "stable_environment", "material_transfer"), ("cluster", "line")),
    ("tool_storage", ("tool cabinet", "drawer cabinet", "cabinet", "tooling shelf"), ("point_of_use_storage",), ("machining", "assembly", "maintenance"), ("operator_access", "door_or_drawer_sweep"), ("line", "cluster")),
    ("lift_table", ("lift table", "scissor table"), ("material_handling_equipment", "support_surface"), ("material_handling_maintenance", "assembly", "staging"), ("operator_access", "vertical_sweep", "load_transfer"), ("cluster", "line")),
    ("computer_or_peripheral", ("computer", "monitor", "keyboard", "mouse", "terminal"), ("information_equipment", "surface_mounted_item"), ("workstation", "inspection_quality", "assembly"), ("operator_access", "support_surface"), ("cluster",)),
    ("operator_reference", ("operator", "person", "human", "worker"), ("personnel_reference",), ("operator_area",), ("pedestrian_access",), ("cluster", "u", "line")),
    ("building_or_structure", ("wall", "column", "building", "platform", "stairs", "cooling tower"), ("facility_structure",), ("facility", "utility"), ("structural_and_access_review",), ("preserve",)),
    ("laboratory_test_equipment", ("test bath", "test tank", "laboratory"), ("test_equipment", "quality_support"), ("inspection_quality", "laboratory"), ("operator_access", "test_work_envelope", "utility_review"), ("cluster", "line")),
    ("packaging_equipment", ("bottle filler", "packaging machine", "packing machine"), ("packaging_equipment", "production_equipment"), ("packaging",), ("operator_access", "material_transfer", "maintenance_access"), ("line", "l", "cluster")),
    ("safety_signage", ("mandatory sign", "no entry", "no left turn", "no right turn", "no u turn", "no parking", "traffic cone"), ("safety_communication", "visual_control"), ("safety_restricted", "aisle"), ("visibility_review",), ("preserve",)),
    ("safety_barrier", ("bollard", "safety railing", "crowd control barrier"), ("access_control_barrier", "safeguarding"), ("safety_restricted", "aisle"), ("route_and_access_review",), ("perimeter", "line")),
    ("facility_access_equipment", ("access stair", "platform stair", "bus shelter"), ("access_equipment", "facility_support"), ("facility", "maintenance"), ("pedestrian_access", "structural_and_access_review"), ("preserve", "cluster")),
    ("office_furniture_or_reference", ("office desk", "office chair", "telephone", "reference book", "coat hanger"), ("office_support",), ("office", "support"), ("occupant_access",), ("cluster", "line")),
    ("facility_service_fixture", ("facility sink", "paper towel dispenser", "floor fan", "road light", "public bench"), ("facility_support",), ("facility", "support"), ("service_and_access_review",), ("preserve", "cluster")),
    ("road_vehicle", ("transit bus", "flatbed", "trailer"), ("vehicle", "material_transport"), ("vehicle_parking", "receiving_raw_material", "shipping"), ("travel_route", "parking_space", "maneuvering_space"), ("grid", "parallel")),
)


_CATEGORY_SEMANTIC_RULES = (
    (("machine", "machines", "cnc machine"), "production_equipment", ("production_equipment",), ("production",), ("operator_access", "material_transfer", "maintenance_access"), ("line", "parallel", "cluster")),
    (("automation", "robot"), "automation_equipment", ("automation_equipment",), ("automation_robotics",), ("guarded_access", "load_unload_access", "maintenance_access"), ("grid", "parallel", "cluster")),
    (("material handling",), "material_handling_equipment", ("material_handling_equipment",), ("material_handling_maintenance", "receiving_raw_material", "shipping"), ("travel_route", "parking_space", "maneuvering_space"), ("grid", "parallel", "cluster")),
    (("storage", "rack"), "storage_equipment", ("storage_system",), ("storage", "receiving_raw_material", "finished_goods"), ("material_handling_access", "aisle_access"), ("grid", "parallel")),
    (("workstation", "workstations"), "workstation", ("workstation",), ("assembly", "inspection_quality", "maintenance"), ("operator_access", "material_staging"), ("line", "u", "l", "cluster")),
    (("safety", "guarding"), "safety_resource", ("safety_support",), ("safety_restricted", "aisle"), ("safety_function_review",), ("preserve", "line", "perimeter")),
    (("people", "personnel"), "personnel_reference", ("personnel_reference",), ("operator_area",), ("pedestrian_access",), ("cluster", "u", "line")),
    (("utility", "utilities"), "utility_equipment", ("utility_equipment",), ("utility", "maintenance"), ("utility_connection_review", "maintenance_access"), ("preserve", "line")),
    (("laboratory",), "laboratory_equipment", ("test_equipment", "quality_support"), ("laboratory", "inspection_quality"), ("operator_access", "utility_review"), ("cluster", "line")),
    (("packaging",), "packaging_equipment", ("packaging_equipment",), ("packaging",), ("operator_access", "material_transfer"), ("line", "cluster")),
    (("office it", "office"), "office_or_information_equipment", ("office_support", "information_support"), ("office", "support"), ("occupant_access", "support_surface_review"), ("cluster", "line")),
    (("facilities", "facility"), "facility_support_asset", ("facility_support",), ("facility", "support"), ("service_and_access_review",), ("preserve", "cluster")),
    (("vehicles", "vehicle"), "vehicle", ("vehicle",), ("vehicle_parking", "receiving_raw_material", "shipping"), ("travel_route", "parking_space", "maneuvering_space"), ("grid", "parallel")),
)


_FLOOR_MARKING_MEANINGS = {
    "direction_arrow": "communicates intended travel direction",
    "solid_line": "communicates a lane, edge, or separation line",
    "dashed_line": "communicates a permeable lane or guidance line",
    "keep_clear": "communicates an area intended to remain unobstructed",
    "crosswalk": "communicates a pedestrian crossing",
    "hazard_stripe": "communicates caution or a hazard boundary",
    "floor_text": "communicates a floor label or instruction",
    "parking_box": "communicates a designated parking or staging footprint",
}


def _normalized_text(*values: Any) -> str:
    raw = " ".join(str(value or "") for value in values).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", raw)).strip()


def _points(value: Any) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    result = []
    try:
        for point in value:
            if not isinstance(point, Mapping):
                return None
            result.append((float(point["x"]), float(point["z"])))
    except (KeyError, TypeError, ValueError):
        return None
    if abs(polygon_area(result)) <= GEOMETRY_EPSILON:
        return None
    return tuple(result)


def _round(value: float, digits: int = 6) -> float:
    result = round(float(value), digits)
    return 0.0 if result == -0.0 else result


def _polygon_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    signed_area = polygon_area(points)
    if abs(signed_area) <= GEOMETRY_EPSILON:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    factor = 1.0 / (6.0 * signed_area)
    x_value = 0.0
    z_value = 0.0
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        cross = current[0] * following[1] - following[0] * current[1]
        x_value += (current[0] + following[0]) * cross
        z_value += (current[1] + following[1]) * cross
    return x_value * factor, z_value * factor


def _zone_hierarchy(
    zones: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str | None], dict[str, int], dict[str, int]]:
    polygons: dict[str, tuple[tuple[float, float], ...]] = {}
    areas: dict[str, float] = {}
    for zone in zones:
        zone_id = str(zone.get("zoneId") or "")
        points = _points(zone.get("boundary"))
        if zone_id and points is not None:
            polygons[zone_id] = points
            areas[zone_id] = abs(polygon_area(points))
    parents: dict[str, str | None] = {}
    for zone_id, subject in polygons.items():
        candidates = []
        for candidate_id, container in polygons.items():
            if candidate_id == zone_id:
                continue
            if areas[candidate_id] <= areas[zone_id] + GEOMETRY_EPSILON:
                continue
            if polygon_contains_polygon(container, subject):
                candidates.append((areas[candidate_id], candidate_id))
        parents[zone_id] = min(candidates)[1] if candidates else None
    depths: dict[str, int] = {}
    for zone_id in polygons:
        depth = 0
        cursor = parents.get(zone_id)
        visited = {zone_id}
        while cursor and cursor not in visited:
            visited.add(cursor)
            depth += 1
            cursor = parents.get(cursor)
        depths[zone_id] = depth
    child_counts = {zone_id: 0 for zone_id in polygons}
    for parent_id in parents.values():
        if parent_id:
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1
    return parents, depths, child_counts


def _zone_semantics(zone: Mapping[str, Any]) -> dict[str, Any]:
    extensions = zone.get("extensions")
    extensions = extensions if isinstance(extensions, Mapping) else {}
    authored_type = zone.get("semanticType") or extensions.get("semanticType")
    authored_purpose = zone.get("purpose") or extensions.get("purpose")
    authored_roles = zone.get("operationalRoles") or extensions.get("operationalRoles")
    cell_group = extensions.get("cellGroup")
    cell_group = cell_group if isinstance(cell_group, Mapping) else {}
    authored_interfaces = (
        zone.get("functionalInterfaces")
        or extensions.get("functionalInterfaces")
        or cell_group.get("functionalInterfaces")
    )
    authored_interfaces = (
        deepcopy(dict(authored_interfaces))
        if isinstance(authored_interfaces, Mapping) else {}
    )
    if isinstance(authored_roles, list):
        roles = sorted({str(item) for item in authored_roles if str(item).strip()})
    else:
        roles = []
    if authored_type or authored_purpose or roles:
        semantic_type = str(authored_type or "authored_operating_area")
        purpose = str(authored_purpose or zone.get("label") or semantic_type)
        return {
            "semanticType": semantic_type,
            "purpose": purpose,
            "operationalRoles": roles,
            "functionalInterfaces": authored_interfaces,
            "functionalInterfaceEvidenceStatus": (
                "authored" if authored_interfaces else "unknown"
            ),
            "evidenceStatus": "authored",
            "method": "zone_semantic_metadata",
        }
    text = _normalized_text(
        zone.get("label"),
        zone.get("zoneType"),
    )
    for semantic_type, patterns, purpose, inferred_roles in _ZONE_RULES:
        if any(pattern in text for pattern in patterns):
            return {
                "semanticType": semantic_type,
                "purpose": purpose,
                "operationalRoles": list(inferred_roles),
                "functionalInterfaces": authored_interfaces,
                "functionalInterfaceEvidenceStatus": (
                    "authored" if authored_interfaces else "unknown"
                ),
                "evidenceStatus": "inferred",
                "method": "authored_label_and_zone_type",
            }
    zone_type = str(zone.get("zoneType") or "unknown")
    return {
        "semanticType": zone_type,
        "purpose": str(zone.get("label") or zone_type),
        "operationalRoles": [],
        "functionalInterfaces": authored_interfaces,
        "functionalInterfaceEvidenceStatus": (
            "authored" if authored_interfaces else "unknown"
        ),
        "evidenceStatus": "unknown",
        "method": "no_semantic_match",
    }


def _is_authored_cell_zone(zone: Mapping[str, Any]) -> bool:
    """Identify cell modules from authored type/group metadata, not labels."""

    extensions = zone.get("extensions")
    extensions = extensions if isinstance(extensions, Mapping) else {}
    cell_group = extensions.get("cellGroup")
    cell_group = cell_group if isinstance(cell_group, Mapping) else {}
    return bool(
        str(zone.get("zoneType") or "") == "workcell"
        or str(zone.get("semanticType") or "") == "workcell"
        or cell_group.get("groupKind") == "manufacturing_cell"
    )


def _asset_semantics(asset: Mapping[str, Any]) -> dict[str, Any]:
    authored = asset.get("facilitySemantics")
    authored = authored if isinstance(authored, Mapping) else {}
    authored_type = authored.get("semanticType")
    authored_roles = authored.get("operationalRoles")
    authored_sides = authored.get("functionalSides")
    authored_sides = (
        deepcopy(dict(authored_sides))
        if isinstance(authored_sides, Mapping) else {}
    )
    if isinstance(authored_roles, list):
        roles = sorted({str(item) for item in authored_roles if str(item).strip()})
    else:
        roles = []
    status = authored.get("evidenceStatus")
    if status not in EVIDENCE_STATUSES:
        status = "authored" if authored_type or roles else None
    text = _normalized_text(
        asset.get("assetId"),
        asset.get("displayName"),
        asset.get("category"),
        " ".join(asset.get("tags", []) if isinstance(asset.get("tags"), list) else []),
        " ".join(asset.get("capabilityIds", []) if isinstance(asset.get("capabilityIds"), list) else []),
    )
    matched = None
    fallback = None
    for rule in _ASSET_RULES:
        if any(pattern in text for pattern in rule[1]):
            matched = rule
            break
    if authored_type or roles:
        semantic_type = str(authored_type or (matched[0] if matched else "industrial_asset"))
        operational_roles = roles or list(matched[2] if matched else ())
        evidence_status = str(status)
        method = "asset_facility_semantics"
    elif matched:
        semantic_type = matched[0]
        operational_roles = list(matched[2])
        evidence_status = "inferred"
        method = "asset_name_category_tags_capabilities"
    else:
        category = _normalized_text(asset.get("category"))
        fallback = None
        for rule in _CATEGORY_SEMANTIC_RULES:
            categories = rule[0]
            if category in categories or any(item in category for item in categories):
                fallback = rule
                break
        semantic_type = fallback[1] if fallback else "industrial_asset"
        operational_roles = list(fallback[2]) if fallback else [
            "industrial_resource"
        ]
        evidence_status = "inferred" if fallback else "unknown"
        method = "asset_category" if evidence_status == "inferred" else "no_semantic_match"
    semantic_rule = matched or (fallback if not matched else None)
    typical_zones = list(semantic_rule[3]) if semantic_rule else []
    access_needs = list(semantic_rule[4]) if semantic_rule else []
    arrangements = list(semantic_rule[5]) if semantic_rule else []
    return {
        "assetId": str(asset.get("assetId") or ""),
        "assetDefinitionRevision": str(asset.get("assetDefinitionRevision") or ""),
        "displayName": str(asset.get("displayName") or asset.get("assetId") or ""),
        "category": str(asset.get("category") or "unknown"),
        "semanticType": semantic_type,
        "semanticTypeEvidenceStatus": evidence_status,
        "semanticMethod": method,
        "operationalRoles": operational_roles,
        "functionalSides": authored_sides,
        "functionalSideEvidenceStatus": (
            "authored" if authored_sides else "unknown"
        ),
        "typicalZoneFamilies": typical_zones,
        "genericAccessNeeds": access_needs,
        "arrangementAffinities": arrangements,
        "capabilityIds": sorted(str(item) for item in asset.get("capabilityIds", []) if item),
        "dimensions": deepcopy(asset.get("dimensions")),
        "footprint": deepcopy(asset.get("footprint")),
        "mobilityClassification": asset.get("mobilityClassification"),
        "allowedMountingSurfaces": deepcopy(asset.get("allowedMountingSurfaces") or []),
        "planningReady": asset.get("planningReady") is True,
        "planningReadinessEvidenceComplete": (
            asset.get("planningReadinessEvidenceComplete") is True
        ),
        "planningReadinessBlockers": deepcopy(
            asset.get("planningReadinessBlockers") or []
        ),
        "clearanceRecordCount": int(asset.get("clearanceRecordCount") or 0),
        "knowledgeQualification": (
            "Generic access needs and arrangement affinities are inferred "
            "planning priors. They do not establish exact sides, distances, "
            "capacity, or safety compliance."
        ),
    }


def classify_facility_zone_semantics(
    zone: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose the established zone classifier without exposing its rules."""

    if not isinstance(zone, Mapping):
        raise TypeError("zone must be a mapping")
    return deepcopy(_zone_semantics(zone))


def classify_facility_asset_semantics(
    asset: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose the established asset classifier for readiness projections."""

    if not isinstance(asset, Mapping):
        raise TypeError("asset must be a mapping")
    return deepcopy(_asset_semantics(asset))


def _line_points(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        return ()
    result = []
    for point in value:
        if not isinstance(point, Mapping):
            continue
        try:
            result.append((float(point["x"]), float(point["z"])))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(result)


def _line_intersects_polygon(
    line: Sequence[tuple[float, float]],
    polygon: Sequence[tuple[float, float]],
) -> bool:
    if any(point_in_polygon(point, polygon) for point in line):
        return True
    for line_index in range(max(0, len(line) - 1)):
        for polygon_index in range(len(polygon)):
            if segments_intersect(
                line[line_index],
                line[line_index + 1],
                polygon[polygon_index],
                polygon[(polygon_index + 1) % len(polygon)],
            ):
                return True
    return False


def _line_length(line: Sequence[tuple[float, float]]) -> float:
    return sum(
        math.hypot(
            line[index + 1][0] - line[index][0],
            line[index + 1][1] - line[index][1],
        )
        for index in range(max(0, len(line) - 1))
    )


def _cardinal_location(
    centroid: tuple[float, float],
    bounds: tuple[float, float, float, float] | None,
) -> str:
    if bounds is None:
        return "unknown"
    width = max(GEOMETRY_EPSILON, bounds[2] - bounds[0])
    depth = max(GEOMETRY_EPSILON, bounds[3] - bounds[1])
    x_ratio = (centroid[0] - bounds[0]) / width
    z_ratio = (centroid[1] - bounds[1]) / depth
    east_west = "west" if x_ratio < 1 / 3 else "east" if x_ratio > 2 / 3 else "center"
    north_south = "south" if z_ratio < 1 / 3 else "north" if z_ratio > 2 / 3 else "center"
    if east_west == "center" and north_south == "center":
        return "center"
    if east_west == "center":
        return north_south
    if north_south == "center":
        return east_west
    return north_south + east_west


def _scope_kind(
    semantic_type: str,
    zone_type: str,
    depth: int,
    child_count: int,
) -> str:
    if depth > 0:
        return "subzone"
    non_department = {
        "aisle",
        "safety_restricted",
        "staging",
        "equipment_parking",
    }
    if semantic_type in non_department or zone_type in {
        "aisle",
        "exclusion",
        "operator",
        "safety",
        "service",
        "utility",
    }:
        return "site_zone"
    department_types = {
        "receiving_raw_material",
        "machining",
        "automation_robotics",
        "assembly_kitting",
        "inspection_packaging_finished_goods",
        "material_handling_maintenance",
        "receiving",
        "shipping",
        "storage",
        "assembly",
        "inspection_quality",
        "packaging",
        "maintenance",
        "finished_goods",
    }
    if semantic_type in department_types or zone_type == "department" or child_count > 0:
        return "department"
    return "operating_area"


def _route_semantics(
    route: Mapping[str, Any],
    polygons: Mapping[str, Sequence[tuple[float, float]]],
) -> dict[str, Any]:
    line = _line_points(route.get("centerline"))
    route_kind = str(route.get("routeKind") or "unknown")
    role = {
        "forklift": "material_handling_route",
        "material": "material_flow_route",
        "operator": "pedestrian_route",
        "pedestrian": "pedestrian_route",
        "conveyor": "conveyor_route",
    }.get(route_kind, route_kind + "_route")
    connected = sorted(
        zone_id
        for zone_id, polygon in polygons.items()
        if len(line) >= 2 and _line_intersects_polygon(line, polygon)
    )
    source_zones = sorted(
        zone_id for zone_id, polygon in polygons.items()
        if line and point_in_polygon(line[0], polygon)
    )
    target_zones = sorted(
        zone_id for zone_id, polygon in polygons.items()
        if line and point_in_polygon(line[-1], polygon)
    )
    width = route.get("corridorWidth")
    try:
        width_value = _round(float(width))
    except (TypeError, ValueError):
        width_value = None
    clearance_status, clearance_authoritative = _aisle_evidence(route)
    return {
        "routeId": str(route.get("routeId") or ""),
        "label": str(route.get("label") or route.get("routeId") or ""),
        "routeKind": route_kind,
        "semanticRole": role,
        "semanticEvidenceStatus": "derived",
        "lengthMeters": _round(_line_length(line)),
        "corridorWidthMeters": width_value,
        "clearanceEvidenceStatus": clearance_status,
        "clearanceAuthoritative": clearance_authoritative,
        "connectedZoneIds": connected,
        "sourceZoneIds": source_zones,
        "targetZoneIds": target_zones,
        "directionEvidenceStatus": "derived" if line else "unknown",
        "qualification": (
            "Geometric connection does not by itself prove route capacity, "
            "clearance, accessibility, or operational sequence."
        ),
    }


def _marking_semantics(marking: Mapping[str, Any]) -> dict[str, Any]:
    marking_type = str(marking.get("markingType") or "unknown")
    role = str(marking.get("semanticRole") or "unknown")
    try:
        area = abs(float(marking.get("width")) * float(marking.get("depth")))
    except (TypeError, ValueError):
        area = 0.0
    return {
        "markingId": str(marking.get("markingId") or ""),
        "label": str(marking.get("label") or marking.get("text") or marking_type),
        "markingType": marking_type,
        "semanticRole": role,
        "roleEvidenceStatus": "authored" if role != "unknown" else "unknown",
        "operationalMeaning": _FLOOR_MARKING_MEANINGS.get(
            marking_type,
            "communicates authored floor information",
        ),
        "operationalMeaningEvidenceStatus": "inferred",
        "areaSquareMeters": _round(area),
        "areaEvidenceStatus": "derived" if area > 0 else "unknown",
        "layoutProvenance": _layout_provenance(marking),
        "qualification": (
            "A floor marking communicates intent; it does not prove a valid "
            "route, separation distance, clearance, or safety condition."
        ),
    }


def _process_relationship_semantics(
    bindings: Sequence[Mapping[str, Any]],
    process_maps: Sequence[Mapping[str, Any]],
    placement_zone_ids: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Derive facility flow only from revision-bound process graph edges."""

    catalog = {
        (
            str(item.get("productId") or ""),
            str(item.get("processMapId") or ""),
            str(item.get("processMapRevision") or ""),
        ): item
        for item in process_maps
        if isinstance(item, Mapping)
    }
    records = []
    unresolved = []
    bound_zone_ids: set[str] = set()
    for binding in bindings:
        binding_id = str(binding.get("processBindingId") or "")
        map_id = str(binding.get("processMapId") or "")
        revision = str(binding.get("processMapRevision") or "")
        placement_ids = sorted({
            str(item) for item in binding.get("placementIds", []) or []
            if str(item)
        })
        zone_ids = sorted({
            str(zone_id)
            for placement_id in placement_ids
            for zone_id in placement_zone_ids.get(placement_id, ())
            if str(zone_id)
        })
        bound_zone_ids.update(zone_ids)
        product_id = str(binding.get("productId") or "")
        map_record = catalog.get((product_id, map_id, revision))
        map_current = map_record is not None
        missing_placements = sorted(
            placement_id for placement_id in placement_ids
            if placement_id not in placement_zone_ids
        )
        blocker_codes = []
        if not map_current:
            blocker_codes.append("process_map_revision_not_loaded")
        if missing_placements:
            blocker_codes.append("process_binding_placement_missing")
        if blocker_codes:
            unresolved.append({
                "processBindingId": binding_id,
                "blockerCodes": blocker_codes,
                "missingPlacementIds": missing_placements,
            })
        records.append({
            "processBindingId": binding_id,
            "productId": product_id,
            "processMapId": map_id,
            "processMapRevision": revision,
            "processMapDisplayName": (
                str(map_record.get("displayName") or map_id)
                if map_record is not None else None
            ),
            "processNodeIds": sorted({
                str(item) for item in binding.get("processNodeIds", []) or []
                if str(item)
            }),
            "processEdgeIds": sorted({
                str(item) for item in binding.get("processEdgeIds", []) or []
                if str(item)
            }),
            "placementIds": placement_ids,
            "zoneIds": zone_ids,
            "routeIds": sorted({
                str(item) for item in binding.get("routeIds", []) or []
                if str(item)
            }),
            "bindingRole": str(binding.get("bindingRole") or "resource"),
            "evidenceStatus": "authored",
            "processMapRevisionLoaded": map_current,
            "blockerCodes": blocker_codes,
            "upstreamProcessBindingIds": [],
            "downstreamProcessBindingIds": [],
            "upstreamZoneIds": [],
            "downstreamZoneIds": [],
        })
    record_by_id = {
        item["processBindingId"]: item
        for item in records
        if item["processBindingId"]
    }
    node_bindings: dict[tuple[str, str, str, str], set[str]] = {}
    for item in records:
        map_key = (
            item["productId"],
            item["processMapId"],
            item["processMapRevision"],
        )
        for node_id in item["processNodeIds"]:
            node_bindings.setdefault((*map_key, node_id), set()).add(
                item["processBindingId"]
            )

    relationship_edges = []
    unresolved_graph_edges = []
    topology_loaded_count = 0
    topology_missing_count = 0
    for (product_id, map_id, revision), map_record in sorted(
        catalog.items()
    ):
        topology_loaded = bool(map_record.get("graphTopologyLoaded"))
        if topology_loaded:
            topology_loaded_count += 1
        else:
            topology_missing_count += 1
            continue
        raw_edges = map_record.get("precedenceEdges")
        raw_edges = raw_edges if isinstance(raw_edges, Sequence) else []
        for edge in raw_edges:
            if not isinstance(edge, Mapping):
                continue
            edge_id = str(edge.get("edgeId") or "")
            from_node_id = str(edge.get("fromNodeId") or "")
            to_node_id = str(edge.get("toNodeId") or "")
            edge_kind = str(edge.get("edgeKind") or "precedence")
            if not edge_id or not from_node_id or not to_node_id:
                continue
            source_binding_ids = sorted(
                node_bindings.get(
                    (product_id, map_id, revision, from_node_id),
                    (),
                )
            )
            target_binding_ids = sorted(
                node_bindings.get(
                    (product_id, map_id, revision, to_node_id),
                    (),
                )
            )
            if not source_binding_ids or not target_binding_ids:
                unresolved_graph_edges.append({
                    "productId": product_id,
                    "processMapId": map_id,
                    "processMapRevision": revision,
                    "edgeId": edge_id,
                    "fromNodeId": from_node_id,
                    "toNodeId": to_node_id,
                    "edgeKind": edge_kind,
                    "blockerCodes": ["process_edge_endpoint_not_bound"],
                })
                continue
            for source_binding_id in source_binding_ids:
                for target_binding_id in target_binding_ids:
                    if source_binding_id == target_binding_id:
                        continue
                    source_record = record_by_id[source_binding_id]
                    target_record = record_by_id[target_binding_id]
                    relationship_edges.append({
                        "productId": product_id,
                        "processMapId": map_id,
                        "processMapRevision": revision,
                        "processEdgeId": edge_id,
                        "edgeKind": edge_kind,
                        "fromNodeId": from_node_id,
                        "toNodeId": to_node_id,
                        "upstreamProcessBindingId": source_binding_id,
                        "downstreamProcessBindingId": target_binding_id,
                        "upstreamZoneIds": source_record["zoneIds"],
                        "downstreamZoneIds": target_record["zoneIds"],
                        "evidenceStatus": "derived",
                        "derivation": (
                            "revision-bound authored process edge joined to "
                            "authored facility process bindings"
                        ),
                    })
                    source_record["downstreamProcessBindingIds"].append(
                        target_binding_id
                    )
                    source_record["downstreamZoneIds"].extend(
                        target_record["zoneIds"]
                    )
                    target_record["upstreamProcessBindingIds"].append(
                        source_binding_id
                    )
                    target_record["upstreamZoneIds"].extend(
                        source_record["zoneIds"]
                    )
    for item in records:
        for field in (
            "upstreamProcessBindingIds",
            "downstreamProcessBindingIds",
            "upstreamZoneIds",
            "downstreamZoneIds",
        ):
            item[field] = sorted(set(item[field]))

    if topology_loaded_count and topology_missing_count:
        flow_status = "partial"
        flow_evidence_status = "derived"
        qualification = (
            "Upstream/downstream relationships are available only for loaded "
            "revision-bound process graphs. Other bindings remain unknown."
        )
    elif topology_loaded_count:
        flow_status = "available"
        flow_evidence_status = "derived"
        qualification = (
            "Upstream/downstream relationships are derived from exact authored "
            "process edges and authored facility bindings. They do not prove "
            "material-route continuity, throughput, or capacity."
        )
    else:
        flow_status = "unknown"
        flow_evidence_status = "unknown"
        qualification = (
            "Bindings prove resource-to-process references at exact revisions. "
            "They do not establish upstream/downstream order unless the loaded "
            "process graph or an authored route relationship supplies it."
        )
    return {
        "bindings": sorted(
            records,
            key=lambda item: item["processBindingId"],
        ),
        "boundDepartmentOrZoneIds": sorted(bound_zone_ids),
        "unresolved": sorted(
            unresolved,
            key=lambda item: item["processBindingId"],
        ),
        "relationshipEdges": sorted(
            relationship_edges,
            key=lambda item: (
                item["productId"],
                item["processMapId"],
                item["processEdgeId"],
                item["upstreamProcessBindingId"],
                item["downstreamProcessBindingId"],
            ),
        ),
        "unresolvedGraphEdges": sorted(
            unresolved_graph_edges,
            key=lambda item: (
                item["productId"],
                item["processMapId"],
                item["edgeId"],
            ),
        ),
        "graphTopologyLoadedMapCount": topology_loaded_count,
        "graphTopologyMissingMapCount": topology_missing_count,
        "flowSequenceStatus": flow_status,
        "flowSequenceEvidenceStatus": flow_evidence_status,
        "qualification": qualification,
    }


def _process_relationship_summary(
    relationships: Mapping[str, Any],
) -> dict[str, Any]:
    """Return bounded process evidence for overview and prompt contexts."""

    bindings = relationships.get("bindings")
    bindings = bindings if isinstance(bindings, Sequence) else []
    bound_zone_ids = relationships.get("boundDepartmentOrZoneIds")
    bound_zone_ids = (
        bound_zone_ids if isinstance(bound_zone_ids, Sequence) else []
    )
    unresolved = relationships.get("unresolved")
    unresolved = unresolved if isinstance(unresolved, Sequence) else []
    relationship_edges = relationships.get("relationshipEdges")
    relationship_edges = (
        relationship_edges
        if isinstance(relationship_edges, Sequence)
        else []
    )
    unresolved_edges = relationships.get("unresolvedGraphEdges")
    unresolved_edges = (
        unresolved_edges
        if isinstance(unresolved_edges, Sequence)
        else []
    )
    return {
        "bindingCount": len(bindings),
        "boundDepartmentOrZoneCount": len(bound_zone_ids),
        "unresolvedBindingCount": len(unresolved),
        "relationshipEdgeCount": len(relationship_edges),
        "unresolvedGraphEdgeCount": len(unresolved_edges),
        "graphTopologyLoadedMapCount": relationships.get(
            "graphTopologyLoadedMapCount",
            0,
        ),
        "graphTopologyMissingMapCount": relationships.get(
            "graphTopologyMissingMapCount",
            0,
        ),
        "flowSequenceStatus": relationships.get("flowSequenceStatus"),
        "flowSequenceEvidenceStatus": relationships.get(
            "flowSequenceEvidenceStatus"
        ),
        "qualification": relationships.get("qualification"),
    }


def _polygonal_geometry(value: Any) -> BaseGeometry | None:
    """Return a valid polygonal geometry without accepting line/point area."""

    if not _GEOMETRY_ENGINE_AVAILABLE or value is None:
        return None
    geometry = value
    if getattr(geometry, "is_empty", True):
        return Polygon()
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    geometry_type = getattr(geometry, "geom_type", "")
    if geometry_type in {"Polygon", "MultiPolygon"}:
        return geometry
    components = [
        item
        for item in getattr(geometry, "geoms", ())
        if getattr(item, "geom_type", "") in {"Polygon", "MultiPolygon"}
        and not item.is_empty
    ]
    if not components:
        return None
    merged = unary_union(components)
    return None if merged.is_empty else merged


def _shape_from_boundary(value: Any) -> BaseGeometry | None:
    points = _points(value)
    if points is None or not _GEOMETRY_ENGINE_AVAILABLE:
        return None
    try:
        return _polygonal_geometry(Polygon(points))
    except (TypeError, ValueError, GEOSException):
        return None


def _union_shapes(values: Sequence[BaseGeometry | None]) -> BaseGeometry | None:
    if not _GEOMETRY_ENGINE_AVAILABLE:
        return None
    shapes = [value for value in values if value is not None and not value.is_empty]
    if not shapes:
        return None
    try:
        return _polygonal_geometry(unary_union(shapes))
    except (TypeError, ValueError, GEOSException):
        return None


def _shape_area(value: BaseGeometry | None) -> float:
    return max(0.0, float(value.area)) if value is not None else 0.0


def _shape_difference(
    left: BaseGeometry | None,
    right: BaseGeometry | None,
) -> BaseGeometry | None:
    if left is None:
        return None
    if right is None:
        return left
    try:
        return _polygonal_geometry(left.difference(right))
    except (TypeError, ValueError, GEOSException):
        return None


def _shape_components(value: BaseGeometry | None) -> list[BaseGeometry]:
    if value is None or value.is_empty:
        return []
    if value.geom_type == "Polygon":
        return [value]
    result = []
    for item in getattr(value, "geoms", ()):
        if item.geom_type == "Polygon" and not item.is_empty:
            result.append(item)
        elif item.geom_type == "MultiPolygon":
            result.extend(
                child for child in item.geoms if not child.is_empty
            )
    return result


def _contiguous_region_summary(value: BaseGeometry | None) -> dict[str, Any]:
    components = sorted(
        _shape_components(value),
        key=lambda item: (-float(item.area), tuple(item.bounds)),
    )
    if not components:
        return {
            "regionCount": 0,
            "largestRegion": None,
            "evidenceStatus": "derived" if value is not None else "unknown",
        }
    largest = components[0]
    minimum_x, minimum_z, maximum_x, maximum_z = largest.bounds
    centroid = largest.centroid
    return {
        "regionCount": len(components),
        "largestRegion": {
            "areaSquareMeters": _round(largest.area),
            "areaSquareFeet": _round(
                largest.area * SQUARE_METERS_TO_SQUARE_FEET
            ),
            "axisAlignedWidthMeters": _round(maximum_x - minimum_x),
            "axisAlignedDepthMeters": _round(maximum_z - minimum_z),
            "centroid": {
                "x": _round(centroid.x),
                "z": _round(centroid.y),
            },
        },
        "evidenceStatus": "derived",
        "qualification": (
            "Dimensions are the world-axis-aligned bounds of the largest "
            "connected polygon, not a guaranteed rectangular fit envelope."
        ),
    }


def _oriented_rectangle_shape(marking: Mapping[str, Any]) -> BaseGeometry | None:
    if not _GEOMETRY_ENGINE_AVAILABLE:
        return None
    transform = marking.get("transform")
    transform = transform if isinstance(transform, Mapping) else {}
    position = transform.get("position")
    position = position if isinstance(position, Mapping) else {}
    try:
        width = abs(float(marking["width"]))
        depth = abs(float(marking["depth"]))
        x_value = float(position["x"])
        z_value = float(position["z"])
        rotation = float(transform.get("rotationDegrees", 0.0))
    except (KeyError, TypeError, ValueError):
        return None
    if width <= GEOMETRY_EPSILON or depth <= GEOMETRY_EPSILON:
        return None
    shape = Polygon((
        (-width / 2.0, -depth / 2.0),
        (width / 2.0, -depth / 2.0),
        (width / 2.0, depth / 2.0),
        (-width / 2.0, depth / 2.0),
    ))
    shape = shapely_affinity.rotate(shape, rotation, origin=(0, 0))
    shape = shapely_affinity.translate(shape, xoff=x_value, yoff=z_value)
    return _polygonal_geometry(shape)


def _route_corridor_shape(route: Mapping[str, Any]) -> BaseGeometry | None:
    if not _GEOMETRY_ENGINE_AVAILABLE:
        return None
    line = _line_points(route.get("centerline"))
    try:
        width = float(route.get("corridorWidth"))
    except (TypeError, ValueError):
        return None
    if len(line) < 2 or width <= GEOMETRY_EPSILON:
        return None
    try:
        return _polygonal_geometry(
            LineString(line).buffer(
                width / 2.0,
                cap_style="flat",
                join_style="mitre",
            )
        )
    except (TypeError, ValueError, GEOSException):
        return None


def _record_shapes(
    placement: Mapping[str, Any],
    field: str,
    *,
    floor_elevation: float,
    authoritative_only: bool = False,
    require_floor_contact: bool = True,
) -> tuple[list[BaseGeometry], int, int]:
    shapes = []
    record_count = 0
    authoritative_count = 0
    for record in placement.get(field, []) or []:
        if not isinstance(record, Mapping):
            continue
        record_count += 1
        if record.get("authoritative") is True:
            authoritative_count += 1
        if authoritative_only and record.get("authoritative") is not True:
            continue
        try:
            minimum_y = float(record.get("minimumY", floor_elevation))
            maximum_y = float(record.get("maximumY", floor_elevation))
        except (TypeError, ValueError):
            continue
        if require_floor_contact and (
            minimum_y > floor_elevation + 0.01
            or maximum_y < floor_elevation - 0.01
        ):
            continue
        shape = _shape_from_boundary(record.get("polygon"))
        if shape is not None:
            shapes.append(shape)
    return shapes, record_count, authoritative_count


def _aisle_evidence(route: Mapping[str, Any]) -> tuple[str, bool]:
    extensions = route.get("extensions")
    extensions = extensions if isinstance(extensions, Mapping) else {}
    aisle = extensions.get("facilityAisle")
    aisle = aisle if isinstance(aisle, Mapping) else {}
    status = str(aisle.get("clearanceEvidenceStatus") or "unknown")
    authoritative = route.get("clearanceAuthoritative") is True
    return status, authoritative


def _layout_provenance(value: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = value.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    extensions = value.get("extensions")
    extensions = extensions if isinstance(extensions, Mapping) else {}
    raw = metadata.get("layoutProvenance") or extensions.get("layoutProvenance")
    if isinstance(raw, Mapping):
        result = deepcopy(dict(raw))
        result["evidenceStatus"] = "authored"
        return result
    cell_group = extensions.get("cellGroup")
    if isinstance(cell_group, Mapping):
        return {
            "command": "create_cell_group",
            "authoredStrategy": None,
            "manuallyEditedSinceCreation": None,
            "evidenceStatus": "authored",
            "qualification": (
                "Manufacturing-cell membership is authored, but the original "
                "cell-layout strategy was not persisted."
            ),
        }
    return None


def _canonical_semantic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_semantic_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_canonical_semantic_value(item) for item in value]
    if isinstance(value, float):
        return _round(value)
    return value


def _current_layout_geometry(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("placementId"):
        return {
            "kind": "placement",
            "transform": deepcopy(value.get("transform")),
        }
    if value.get("markingId"):
        return {
            "kind": "floor_marking",
            "transform": deepcopy(value.get("transform")),
            "width": value.get("width"),
            "depth": value.get("depth"),
        }
    return {
        "kind": "zone",
        "boundary": deepcopy(value.get("boundary")),
    }


def _layout_pattern_groups(
    placements: Sequence[Mapping[str, Any]],
    zones: Sequence[Mapping[str, Any]],
    markings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for source in (*placements, *zones, *markings):
        provenance = _layout_provenance(source)
        if not provenance:
            continue
        provenance_id = str(provenance.get("provenanceId") or "")
        if not provenance_id:
            continue
        entity_id = str(
            source.get("placementId")
            or source.get("zoneId")
            or source.get("markingId")
            or ""
        )
        authored = provenance.get("authoredGeometry")
        current = _current_layout_geometry(source)
        geometry_available = isinstance(authored, Mapping)
        matches = bool(
            geometry_available
            and _canonical_semantic_value(authored)
            == _canonical_semantic_value(current)
        )
        group = groups.setdefault(provenance_id, {
            "provenanceId": provenance_id,
            "command": provenance.get("command"),
            "authoredStrategy": provenance.get("authoredStrategy"),
            "seedEntityIds": deepcopy(provenance.get("seedEntityIds") or []),
            "parameters": deepcopy(provenance.get("parameters") or {}),
            "members": [],
        })
        group["members"].append({
            "entityId": entity_id,
            "entityKind": current["kind"],
            "instanceIndex": provenance.get("instanceIndex"),
            "authoredGeometryAvailable": geometry_available,
            "matchesAuthoredGeometry": matches if geometry_available else None,
            "manuallyEditedSinceCreation": (
                provenance.get("manuallyEditedSinceCreation") is True
            ),
            "geometryEditedSinceCreation": (
                provenance.get("geometryEditedSinceCreation") is True
                or (geometry_available and not matches)
            ),
        })
    result = []
    for group in groups.values():
        members = sorted(
            group["members"],
            key=lambda item: (
                item["instanceIndex"] is None,
                item["instanceIndex"] if item["instanceIndex"] is not None else 0,
                item["entityId"],
            ),
        )
        available = [
            item for item in members if item["authoredGeometryAvailable"]
        ]
        if len(available) != len(members):
            status = "incomplete"
            confidence = None
        elif any(item["geometryEditedSinceCreation"] for item in members):
            status = "modified"
            confidence = _round(sum(
                item["matchesAuthoredGeometry"] is True for item in members
            ) / len(members)) if members else None
        else:
            status = "consistent"
            confidence = 1.0
        result.append({
            **{key: value for key, value in group.items() if key != "members"},
            "currentClassification": {
                "strategy": group.get("authoredStrategy"),
                "status": status,
                "confidence": confidence,
                "evidenceStatus": "derived" if available else "unknown",
                "method": "current_geometry_compared_with_authored_snapshot",
            },
            "memberCount": len(members),
            "modifiedMemberCount": sum(
                item["geometryEditedSinceCreation"] for item in members
            ),
            "members": members,
        })
    return sorted(result, key=lambda item: item["provenanceId"])


def _placement_center_in_polygon(
    placement: Mapping[str, Any],
    boundary: Sequence[tuple[float, float]],
) -> bool:
    transform = placement.get("transform")
    transform = transform if isinstance(transform, Mapping) else {}
    position = transform.get("position")
    position = position if isinstance(position, Mapping) else {}
    try:
        return point_in_polygon(
            (float(position["x"]), float(position["z"])),
            boundary,
        )
    except (KeyError, TypeError, ValueError):
        return False


def _spatial_geometry_index(
    placements: Sequence[Mapping[str, Any]],
    *,
    floor_elevation: float,
) -> list[dict[str, Any]]:
    result = []
    for placement in placements:
        all_physical, physical_count, _ = _record_shapes(
            placement,
            "physicalGeometry",
            floor_elevation=floor_elevation,
            require_floor_contact=False,
        )
        floor_physical, _, _ = _record_shapes(
            placement,
            "physicalGeometry",
            floor_elevation=floor_elevation,
        )
        all_clearance, clearance_count, authoritative_count = _record_shapes(
            placement,
            "clearanceGeometry",
            floor_elevation=floor_elevation,
            require_floor_contact=False,
        )
        floor_clearance, _, _ = _record_shapes(
            placement,
            "clearanceGeometry",
            floor_elevation=floor_elevation,
        )
        authoritative_floor_clearance, _, _ = _record_shapes(
            placement,
            "clearanceGeometry",
            floor_elevation=floor_elevation,
            authoritative_only=True,
        )
        try:
            expected_clearance_count = int(
                placement.get("clearanceRecordCount") or 0
            )
        except (TypeError, ValueError):
            expected_clearance_count = 0
        result.append({
            "placement": placement,
            "placementId": str(placement.get("placementId") or ""),
            "allPhysical": all_physical,
            "floorPhysical": floor_physical,
            "physicalRecordCount": physical_count,
            "parsedPhysicalRecordCount": len(all_physical),
            "allClearance": all_clearance,
            "floorClearance": floor_clearance,
            "authoritativeFloorClearance": authoritative_floor_clearance,
            "clearanceRecordCount": clearance_count,
            "parsedClearanceRecordCount": len(all_clearance),
            "authoritativeClearanceRecordCount": authoritative_count,
            "expectedClearanceRecordCount": expected_clearance_count,
            "planningReady": placement.get("planningReady") is True,
            "planningEvidenceComplete": (
                placement.get("planningReadinessEvidenceComplete") is True
            ),
            "planningReadinessBlockers": deepcopy(
                placement.get("planningReadinessBlockers") or []
            ),
            "geometryProjectionError": placement.get("geometryProjectionError"),
        })
    return result


def _route_network_semantics(
    routes: Sequence[Mapping[str, Any]],
    source_routes: Sequence[Mapping[str, Any]],
    geometry_index: Sequence[Mapping[str, Any]],
    source_markings: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Add exact corridor connectivity and floor-obstruction evidence."""

    source_by_id = {
        str(item.get("routeId") or ""): item
        for item in source_routes
        if str(item.get("routeId") or "")
    }
    result = [deepcopy(dict(item)) for item in routes]
    corridors = {
        str(item.get("routeId") or ""): _route_corridor_shape(
            source_by_id.get(str(item.get("routeId") or ""), {})
        )
        for item in result
    }
    movement_graph: dict[str, set[str]] = {
        str(item.get("routeId") or ""): set() for item in result
    }
    endpoint_junctions: dict[str, set[str]] = {
        route_id: set() for route_id in movement_graph
    }
    intersecting: dict[str, set[str]] = {
        route_id: set() for route_id in movement_graph
    }
    crossings_by_route: dict[str, list[dict[str, Any]]] = {
        route_id: [] for route_id in movement_graph
    }
    crosswalk_shapes = {
        str(marking.get("markingId") or ""): _oriented_rectangle_shape(marking)
        for marking in source_markings
        if (
            str(marking.get("markingType") or "") == "crosswalk"
            or str(marking.get("semanticRole") or "") == "crosswalk"
        )
    }
    movement_class = {
        "pedestrian": "pedestrian",
        "operator": "pedestrian",
        "forklift": "material",
        "material": "material",
        "conveyor": "conveyor",
    }
    route_ids = sorted(movement_graph)
    crossing_records: list[dict[str, Any]] = []
    for index, left_id in enumerate(route_ids):
        left = corridors.get(left_id)
        if left is None:
            continue
        for right_id in route_ids[index + 1:]:
            right = corridors.get(right_id)
            if right is None:
                continue
            try:
                connected = left.intersects(right)
            except (TypeError, ValueError, GEOSException):
                connected = False
            if connected:
                intersecting[left_id].add(right_id)
                intersecting[right_id].add(left_id)
                left_line = _line_points(
                    source_by_id.get(left_id, {}).get("centerline")
                )
                right_line = _line_points(
                    source_by_id.get(right_id, {}).get("centerline")
                )
                line_intersection = None
                try:
                    if len(left_line) >= 2 and len(right_line) >= 2:
                        line_intersection = LineString(left_line).intersection(
                            LineString(right_line)
                        )
                except (TypeError, ValueError, GEOSException):
                    line_intersection = None
                endpoint_junction = any(
                    Point(point).intersects(right)
                    for point in (
                        left_line[0], left_line[-1]
                    ) if left_line
                ) or any(
                    Point(point).intersects(left)
                    for point in (
                        right_line[0], right_line[-1]
                    ) if right_line
                )
                left_kind = str(
                    source_by_id.get(left_id, {}).get("routeKind") or "unknown"
                )
                right_kind = str(
                    source_by_id.get(right_id, {}).get("routeKind") or "unknown"
                )
                same_movement_class = (
                    movement_class.get(left_kind, left_kind)
                    == movement_class.get(right_kind, right_kind)
                )
                centerlines_connect = bool(
                    line_intersection is not None
                    and not line_intersection.is_empty
                )
                if endpoint_junction or (
                    same_movement_class and centerlines_connect
                ):
                    movement_graph[left_id].add(right_id)
                    movement_graph[right_id].add(left_id)
                if endpoint_junction:
                    endpoint_junctions[left_id].add(right_id)
                    endpoint_junctions[right_id].add(left_id)

                if centerlines_connect:
                    crossing_point = line_intersection.centroid
                    protected_ids = sorted(
                        marking_id
                        for marking_id, shape in crosswalk_shapes.items()
                        if shape is not None and shape.intersects(crossing_point)
                    )
                    is_mixed_traffic = {
                        movement_class.get(left_kind, left_kind),
                        movement_class.get(right_kind, right_kind),
                    } == {"material", "pedestrian"}
                    record = {
                        "crossingId": (
                            "route-crossing:" + left_id + ":" + right_id
                        ),
                        "routeIds": [left_id, right_id],
                        "routeKinds": [left_kind, right_kind],
                        "movementClasses": sorted({
                            movement_class.get(left_kind, left_kind),
                            movement_class.get(right_kind, right_kind),
                        }),
                        "position": {
                            "x": _round(crossing_point.x),
                            "z": _round(crossing_point.y),
                        },
                        "intersectionGeometryType": line_intersection.geom_type,
                        "corridorOverlapAreaSquareMeters": _round(
                            _shape_area(left.intersection(right))
                        ),
                        "mixedPedestrianMaterialTraffic": is_mixed_traffic,
                        "crosswalkMarkingIds": protected_ids,
                        "crosswalkCoverageStatus": (
                            "protected"
                            if is_mixed_traffic and protected_ids
                            else "unprotected"
                            if is_mixed_traffic
                            else "not_applicable"
                        ),
                        "evidenceStatus": "derived",
                        "qualification": (
                            "A geometric crossing is independent of route-graph "
                            "connectivity. Crosswalk coverage means authored "
                            "crosswalk geometry covers the crossing point; it "
                            "does not establish safety compliance."
                        ),
                    }
                    crossing_records.append(record)
                    crossings_by_route[left_id].append(record)
                    crossings_by_route[right_id].append(record)

    component_by_route: dict[str, str] = {}
    components = []
    unseen = set(route_ids)
    while unseen:
        seed = min(unseen)
        pending = [seed]
        members = []
        while pending:
            route_id = pending.pop()
            if route_id not in unseen:
                continue
            unseen.remove(route_id)
            members.append(route_id)
            pending.extend(sorted(
                movement_graph[route_id] & unseen,
                reverse=True,
            ))
        members.sort()
        component_id = "route-component:" + members[0]
        for route_id in members:
            component_by_route[route_id] = component_id
        components.append({
            "componentId": component_id,
            "routeIds": members,
            "routeCount": len(members),
        })

    physical_complete = all(
        item.get("physicalRecordCount", 0) >= 1
        and item.get("parsedPhysicalRecordCount")
        == item.get("physicalRecordCount")
        and not item.get("geometryProjectionError")
        for item in geometry_index
    )
    obstructed_count = 0
    unresolved_terminal_count = 0
    unknown_corridor_ids = []
    unknown_obstruction_ids = []
    for route in result:
        route_id = str(route.get("routeId") or "")
        source = source_by_id.get(route_id, {})
        line = _line_points(source.get("centerline"))
        corridor = corridors.get(route_id)
        if corridor is None:
            unknown_corridor_ids.append(route_id)

        obstructions = []
        if corridor is not None:
            for record in geometry_index:
                physical_union = _union_shapes(
                    record.get("floorPhysical", [])
                )
                overlap_area = (
                    _shape_area(physical_union.intersection(corridor))
                    if physical_union is not None
                    and physical_union.intersects(corridor)
                    else 0.0
                )
                if overlap_area > GEOMETRY_EPSILON:
                    obstructions.append({
                        "placementId": record.get("placementId"),
                        "intersectionAreaSquareMeters": _round(
                            overlap_area
                        ),
                    })
        obstructions.sort(key=lambda item: str(item["placementId"]))
        if obstructions:
            obstruction_status = "obstructed"
            obstruction_evidence = "derived"
            obstructed_count += 1
        elif corridor is None or not physical_complete:
            obstruction_status = "unknown"
            obstruction_evidence = "unknown"
            unknown_obstruction_ids.append(route_id)
        else:
            obstruction_status = "clear"
            obstruction_evidence = "derived"

        endpoint_records = []
        endpoint_zone_keys = ("sourceZoneIds", "targetZoneIds")
        for endpoint_index, endpoint_name in enumerate(("source", "target")):
            point = line[0 if endpoint_index == 0 else -1] if line else None
            connected_route_ids = []
            if point is not None and _GEOMETRY_ENGINE_AVAILABLE:
                endpoint_shape = Point(point).buffer(GEOMETRY_EPSILON)
                for other_id in sorted(
                    movement_graph.get(route_id, set())
                ):
                    other = corridors.get(other_id)
                    if other is not None and endpoint_shape.intersects(other):
                        connected_route_ids.append(other_id)
            zone_ids = list(route.get(endpoint_zone_keys[endpoint_index]) or [])
            if zone_ids:
                status = "connected_to_zone"
            elif connected_route_ids:
                status = "connected_to_route"
            elif point is None:
                status = "unknown"
            else:
                status = "unresolved_terminal"
                unresolved_terminal_count += 1
            endpoint_records.append({
                "endpoint": endpoint_name,
                "position": (
                    {"x": _round(point[0]), "z": _round(point[1])}
                    if point is not None else None
                ),
                "zoneIds": sorted(zone_ids),
                "connectedRouteIds": connected_route_ids,
                "status": status,
                "evidenceStatus": "derived" if point is not None else "unknown",
            })

        route.update({
            "geometricallyIntersectingRouteIds": sorted(
                intersecting.get(route_id, set())
            ),
            "geometricEndpointJunctionRouteIds": sorted(
                endpoint_junctions.get(route_id, set())
            ),
            "geometricMovementConnectionRouteIds": sorted(
                movement_graph.get(route_id, set())
            ),
            "geometricCrossings": deepcopy(
                crossings_by_route.get(route_id, [])
            ),
            "networkComponentId": component_by_route.get(route_id),
            "endpointConnections": endpoint_records,
            "geometricObstructionStatus": obstruction_status,
            "geometricObstructionEvidenceStatus": obstruction_evidence,
            "geometricObstructions": obstructions,
            "geometricContinuityStatus": (
                "obstructed"
                if obstruction_status == "obstructed"
                else "clear"
                if obstruction_status == "clear"
                and all(
                    item["status"] != "unresolved_terminal"
                    for item in endpoint_records
                )
                else "unresolved"
            ),
            "networkQualification": (
                "Connectivity is derived from authored corridor geometry. "
                "Obstructions are positive-area intersections with exact "
                "floor-contact geometry. This does not establish traffic "
                "capacity, maneuvering adequacy, accessibility, or compliance."
            ),
        })

    summary = {
        "routeCount": len(result),
        "corridorGeometryAvailableCount": (
            len(result) - len(unknown_corridor_ids)
        ),
        "geometricEndpointComponentCount": len(components),
        "geometricMovementComponentCount": len(components),
        "standaloneRouteCount": sum(
            not movement_graph.get(route_id) for route_id in route_ids
        ),
        "geometricCrossingCount": len(crossing_records),
        "mixedTrafficCrossingCount": sum(
            item["mixedPedestrianMaterialTraffic"]
            for item in crossing_records
        ),
        "protectedMixedTrafficCrossingCount": sum(
            item["crosswalkCoverageStatus"] == "protected"
            for item in crossing_records
        ),
        "unprotectedMixedTrafficCrossingCount": sum(
            item["crosswalkCoverageStatus"] == "unprotected"
            for item in crossing_records
        ),
        "geometricallyObstructedRouteCount": obstructed_count,
        "unknownObstructionRouteCount": len(set(unknown_obstruction_ids)),
        "unresolvedTerminalCount": unresolved_terminal_count,
        "components": components,
        "unknownCorridorGeometryRouteIds": sorted(unknown_corridor_ids),
        "physicalGeometryEvidenceComplete": physical_complete,
        "evidenceStatus": (
            "derived"
            if not unknown_corridor_ids and physical_complete
            else "unknown"
        ),
        "qualification": (
            "This is a static geometric route-network assessment. It does "
            "not prove flow capacity, turning clearance, traffic safety, or "
            "regulatory compliance."
        ),
    }
    return result, summary, sorted(
        crossing_records,
        key=lambda item: item["crossingId"],
    )


def _blocker(code: str, subject_ids: Sequence[str]) -> dict[str, Any]:
    ids = sorted({str(item) for item in subject_ids if str(item)})
    return {
        "code": code,
        "subjectCount": len(ids),
        "sampleSubjectIds": ids[:20],
    }


def _scope_spatial_metrics(
    *,
    scope_id: str,
    boundary: Sequence[tuple[float, float]],
    scope_shape: BaseGeometry | None,
    geometry_index: Sequence[Mapping[str, Any]],
    routes: Sequence[Mapping[str, Any]],
    markings: Sequence[Mapping[str, Any]],
    shell: Mapping[str, Any],
    policy: Mapping[str, Any],
    cell_envelopes: Sequence[tuple[str, BaseGeometry]] = (),
    include_all_placements: bool = False,
) -> dict[str, Any]:
    if scope_shape is None:
        return {
            "geometryEngineAvailable": _GEOMETRY_ENGINE_AVAILABLE,
            "evidenceStatus": "unknown",
            "blockers": [_blocker("scope_polygon_invalid", [scope_id])],
        }

    relevant = []
    for record in geometry_index:
        placement = record["placement"]
        intersects = any(
            shape.intersects(scope_shape)
            for shape in record["allPhysical"]
        )
        if (
            include_all_placements
            or
            intersects
            or scope_id in {
                str(item) for item in placement.get("zoneIds", []) or []
            }
            or _placement_center_in_polygon(placement, boundary)
        ):
            relevant.append(record)

    incomplete_physical = [
        item["placementId"]
        for item in relevant
        if (
            item["physicalRecordCount"] < 1
            or item["parsedPhysicalRecordCount"]
            != item["physicalRecordCount"]
            or item["geometryProjectionError"]
        )
    ]
    not_planning_ready = [
        item["placementId"]
        for item in relevant
        if not item["planningEvidenceComplete"]
    ]
    missing_clearance = [
        item["placementId"]
        for item in relevant
        if item["expectedClearanceRecordCount"] < 1
    ]
    incomplete_clearance = [
        item["placementId"]
        for item in relevant
        if (
            item["expectedClearanceRecordCount"] > 0
            and (
                item["clearanceRecordCount"]
                != item["expectedClearanceRecordCount"]
                or item["parsedClearanceRecordCount"]
                != item["clearanceRecordCount"]
            )
        )
    ]
    unauthoritative_clearance = [
        item["placementId"]
        for item in relevant
        if (
            item["expectedClearanceRecordCount"] > 0
            and item["authoritativeClearanceRecordCount"]
            != item["expectedClearanceRecordCount"]
        )
    ]

    physical_shapes = [
        shape.intersection(scope_shape)
        for item in relevant
        for shape in item["floorPhysical"]
        if shape.intersects(scope_shape)
    ]
    floor_contact_placement_count = sum(
        any(shape.intersects(scope_shape) for shape in item["floorPhysical"])
        for item in relevant
    )
    declared_clearance_shapes = [
        shape.intersection(scope_shape)
        for item in relevant
        for shape in item["floorClearance"]
        if shape.intersects(scope_shape)
    ]
    authoritative_clearance_shapes = [
        shape.intersection(scope_shape)
        for item in relevant
        for shape in item["authoritativeFloorClearance"]
        if shape.intersects(scope_shape)
    ]
    physical_union = _union_shapes(physical_shapes)
    declared_clearance_union = _union_shapes(declared_clearance_shapes)
    authoritative_clearance_union = _union_shapes(
        authoritative_clearance_shapes
    )

    applicable_cell_envelopes = [
        (zone_id, shape)
        for zone_id, shape in cell_envelopes
        if zone_id != scope_id
        and shape is not None
        and shape.intersects(scope_shape)
    ]
    cell_envelope_shapes = [
        shape.intersection(scope_shape)
        for _zone_id, shape in applicable_cell_envelopes
    ]
    cell_envelope_union = _union_shapes(cell_envelope_shapes)
    cell_envelope_ids = sorted({
        str(zone_id)
        for zone_id, _shape in applicable_cell_envelopes
    })

    route_shapes = []
    authoritative_route_shapes = []
    incomplete_route_geometry = []
    unauthoritative_routes = []
    for route in routes:
        route_id = str(route.get("routeId") or "")
        line = _line_points(route.get("centerline"))
        if len(line) < 2:
            if include_all_placements:
                incomplete_route_geometry.append(route_id)
            continue
        shape = _route_corridor_shape(route)
        if shape is None:
            if include_all_placements or _line_intersects_polygon(
                line,
                boundary,
            ):
                incomplete_route_geometry.append(route_id)
            continue
        if not shape.intersects(scope_shape):
            continue
        clipped = shape.intersection(scope_shape)
        if clipped.is_empty:
            continue
        route_shapes.append(clipped)
        _, authoritative = _aisle_evidence(route)
        if authoritative:
            authoritative_route_shapes.append(clipped)
        else:
            unauthoritative_routes.append(route_id)
    route_union = _union_shapes(route_shapes)
    authoritative_route_union = _union_shapes(authoritative_route_shapes)

    reservation_roles = {
        "pedestrian_lane",
        "forklift_lane",
        "material_flow",
        "keep_clear",
        "staging",
        "safety",
        "parking",
    }
    marking_shapes = []
    incomplete_marking_geometry = []
    unauthoritative_markings = []
    for marking in markings:
        if str(marking.get("semanticRole") or "") not in reservation_roles:
            continue
        shape = _oriented_rectangle_shape(marking)
        marking_id = str(marking.get("markingId") or "")
        if shape is None:
            transform = marking.get("transform")
            transform = transform if isinstance(transform, Mapping) else {}
            position = transform.get("position")
            position = position if isinstance(position, Mapping) else {}
            try:
                center_inside = point_in_polygon(
                    (float(position["x"]), float(position["z"])),
                    boundary,
                )
            except (KeyError, TypeError, ValueError):
                center_inside = include_all_placements
            if include_all_placements or center_inside:
                incomplete_marking_geometry.append(marking_id)
            continue
        if shape.intersects(scope_shape):
            marking_shapes.append(shape.intersection(scope_shape))
            if marking.get("evidenceAuthoritative") is not True:
                unauthoritative_markings.append(marking_id)
    marking_union = _union_shapes(marking_shapes)

    geometry_complete = not incomplete_physical
    geometric_free = (
        _shape_difference(scope_shape, physical_union)
        if geometry_complete else None
    )
    planning_reserved = _union_shapes([
        physical_union,
        declared_clearance_union,
        cell_envelope_union,
        route_union,
        marking_union,
    ])
    planning_inputs_complete = bool(
        geometry_complete
        and not incomplete_clearance
        and not incomplete_route_geometry
        and not incomplete_marking_geometry
    )
    planning_free = (
        _shape_difference(scope_shape, planning_reserved)
        if planning_inputs_complete else None
    )
    authoritative_reserved = _union_shapes([
        physical_union,
        authoritative_clearance_union,
        cell_envelope_union,
        authoritative_route_union,
        marking_union,
    ])

    shell_unresolved = shell.get("unresolvedItems")
    shell_unresolved = shell_unresolved if isinstance(shell_unresolved, list) else []
    policy_unresolved = policy.get("unresolvedItems")
    policy_unresolved = policy_unresolved if isinstance(policy_unresolved, list) else []
    reviewed_statuses = {"active", "approved", "released", "reviewed"}
    blockers = []
    for code, ids in (
        ("physical_geometry_incomplete", incomplete_physical),
        ("asset_planning_evidence_incomplete", not_planning_ready),
        ("clearance_model_absent", missing_clearance),
        ("clearance_geometry_incomplete", incomplete_clearance),
        ("clearance_evidence_not_authoritative", unauthoritative_clearance),
        ("route_geometry_incomplete", incomplete_route_geometry),
        ("route_clearance_not_authoritative", unauthoritative_routes),
        ("floor_marking_geometry_incomplete", incomplete_marking_geometry),
        ("floor_marking_intent_not_authoritative", unauthoritative_markings),
    ):
        if ids:
            blockers.append(_blocker(code, ids))
    if not _GEOMETRY_ENGINE_AVAILABLE:
        blockers.append(_blocker("polygon_geometry_engine_unavailable", [scope_id]))
    if str(shell.get("status") or "") not in reviewed_statuses:
        blockers.append(_blocker("facility_shell_not_reviewed", [
            str(shell.get("shellId") or "facility-shell")
        ]))
    if shell.get("floorGeometryAuthoritative") is not True:
        blockers.append(_blocker("facility_shell_geometry_not_authoritative", [
            str(shell.get("shellId") or "facility-shell")
        ]))
    if shell_unresolved:
        blockers.append(_blocker("facility_shell_has_unresolved_items", [
            str(item.get("findingId") or item.get("code") or index)
            for index, item in enumerate(shell_unresolved)
            if isinstance(item, Mapping)
        ]))
    if str(policy.get("status") or "") not in reviewed_statuses:
        blockers.append(_blocker("facility_policy_not_reviewed", [
            str(policy.get("policySetId") or "facility-policy")
        ]))
    if policy.get("rulesAuthoritative") is not True:
        blockers.append(_blocker("facility_policy_evidence_not_authoritative", [
            str(policy.get("policySetId") or "facility-policy")
        ]))
    if policy_unresolved:
        blockers.append(_blocker("facility_policy_has_unresolved_items", [
            str(item.get("findingId") or item.get("code") or index)
            for index, item in enumerate(policy_unresolved)
            if isinstance(item, Mapping)
        ]))

    operational_complete = not blockers
    operational_free = (
        _shape_difference(scope_shape, authoritative_reserved)
        if operational_complete else None
    )
    gross_area = _shape_area(scope_shape)
    physical_area = _shape_area(physical_union)
    clearance_only = _shape_difference(
        declared_clearance_union,
        physical_union,
    )
    occupied_and_clearance = _union_shapes([physical_union, clearance_only])
    cell_envelope_only = _shape_difference(
        cell_envelope_union,
        occupied_and_clearance,
    )
    before_routes = _union_shapes([
        physical_union,
        clearance_only,
        cell_envelope_only,
    ])
    route_only = _shape_difference(route_union, before_routes)
    before_markings = _union_shapes([
        physical_union,
        clearance_only,
        cell_envelope_only,
        route_only,
    ])
    marking_only = _shape_difference(marking_union, before_markings)
    breakdown_free = max(
        0.0,
        gross_area
        - _shape_area(physical_union)
        - _shape_area(clearance_only)
        - _shape_area(cell_envelope_only)
        - _shape_area(route_only)
        - _shape_area(marking_only),
    )
    return {
        "geometryEngineAvailable": _GEOMETRY_ENGINE_AVAILABLE,
        "grossAreaSquareMeters": _round(gross_area),
        "grossAreaSquareFeet": _round(gross_area * SQUARE_METERS_TO_SQUARE_FEET),
        "physicalFloorContact": {
            "placementCount": floor_contact_placement_count,
            "grossPolygonAreaSquareMeters": _round(sum(
                _shape_area(item) for item in physical_shapes
            )),
            "netUnionAreaSquareMeters": _round(physical_area),
            "overlapRemovedSquareMeters": _round(max(
                0.0,
                sum(_shape_area(item) for item in physical_shapes) - physical_area,
            )),
            "coveragePercent": _round(
                physical_area / gross_area * 100.0
            ) if gross_area > GEOMETRY_EPSILON else None,
            "evidenceStatus": "derived" if geometry_complete else "unknown",
            "method": "union_of_floor_contact_polygons_clipped_to_scope",
        },
        "clearanceReservedArea": {
            "declaredUnionAreaSquareMeters": _round(
                _shape_area(declared_clearance_union)
            ),
            "authoritativeUnionAreaSquareMeters": _round(
                _shape_area(authoritative_clearance_union)
            ),
            "evidenceStatus": (
                "derived"
                if not missing_clearance
                and not incomplete_clearance
                and not unauthoritative_clearance
                else "unknown"
            ),
            "modeledPlacementCount": sum(
                item["expectedClearanceRecordCount"] > 0
                for item in relevant
            ),
            "missingModelPlacementCount": len(missing_clearance),
            "missingModelPlacementIds": sorted(missing_clearance)[:20],
            "qualification": (
                "Declared area is the union of clearance geometry that is "
                "present. Missing required clearance models are uncertainty, "
                "not zero reserved area."
            ),
        },
        "cellEnvelopeReservedArea": {
            "authoredUnionAreaSquareMeters": _round(
                _shape_area(cell_envelope_union)
            ),
            "cellZoneCount": len(cell_envelope_ids),
            "cellZoneIds": cell_envelope_ids[:50],
            "evidenceStatus": "authored",
            "qualification": (
                "Descendant manufacturing-cell envelopes are authored "
                "operational allocations. They are planning reservations, "
                "not physical equipment footprint or safety clearance."
            ),
        },
        "routeReservedArea": {
            "authoredCorridorUnionAreaSquareMeters": _round(
                _shape_area(route_union)
            ),
            "authoritativeCorridorUnionAreaSquareMeters": _round(
                _shape_area(authoritative_route_union)
            ),
            "evidenceStatus": (
                "derived"
                if not incomplete_route_geometry and not unauthoritative_routes
                else "unknown"
            ),
        },
        "floorMarkingReservation": {
            "communicatedUnionAreaSquareMeters": _round(
                _shape_area(marking_union)
            ),
            "evidenceStatus": (
                "derived"
                if not incomplete_marking_geometry and not unauthoritative_markings
                else "inferred"
            ),
            "qualification": (
                "The area reflects authored operational intent; a marking alone "
                "does not prove route, clearance, or safety compliance."
            ),
        },
        "geometricFreeArea": {
            "areaSquareMeters": _round(_shape_area(geometric_free))
            if geometric_free is not None else None,
            "areaSquareFeet": _round(
                _shape_area(geometric_free) * SQUARE_METERS_TO_SQUARE_FEET
            ) if geometric_free is not None else None,
            "percent": _round(
                _shape_area(geometric_free) / gross_area * 100.0
            ) if geometric_free is not None and gross_area > GEOMETRY_EPSILON else None,
            "evidenceStatus": "derived" if geometric_free is not None else "unknown",
            "definition": "gross scope minus net floor-contact footprint union",
            "contiguousRegions": _contiguous_region_summary(geometric_free),
        },
        "knownPlanningFreeArea": {
            "areaSquareMeters": _round(_shape_area(planning_free))
            if planning_free is not None else None,
            "areaSquareFeet": _round(
                _shape_area(planning_free) * SQUARE_METERS_TO_SQUARE_FEET
            ) if planning_free is not None else None,
            "evidenceStatus": "derived" if planning_free is not None else "unknown",
            "contiguousRegions": _contiguous_region_summary(planning_free),
            "qualification": (
                "Subtracts currently declared clearances, route corridors, and "
                "semantic floor reservations. Missing required reservations "
                "remain uncertainty and are not treated as zero. This is not "
                "a compliance claim."
            ),
        },
        "operationallyUsableFreeArea": {
            "areaSquareMeters": _round(_shape_area(operational_free))
            if operational_free is not None else None,
            "areaSquareFeet": _round(
                _shape_area(operational_free) * SQUARE_METERS_TO_SQUARE_FEET
            ) if operational_free is not None else None,
            "evidenceStatus": "derived" if operational_complete else "unknown",
            "contiguousRegions": _contiguous_region_summary(operational_free),
            "qualification": (
                "Available only when physical geometry, asset clearances, route "
                "clearances, shell, and policy evidence are complete and reviewed."
            ),
        },
        "reconciledPlanningAreaBreakdown": {
            "denominator": "grossAreaSquareMeters",
            "physicalFootprintSquareMeters": _round(_shape_area(physical_union)),
            "clearanceOnlySquareMeters": _round(_shape_area(clearance_only)),
            "cellEnvelopeOnlySquareMeters": _round(
                _shape_area(cell_envelope_only)
            ),
            "routeOnlySquareMeters": _round(_shape_area(route_only)),
            "markingOnlySquareMeters": _round(_shape_area(marking_only)),
            "remainingSquareMeters": _round(breakdown_free),
            "sumSquareMeters": _round(
                _shape_area(physical_union)
                + _shape_area(clearance_only)
                + _shape_area(cell_envelope_only)
                + _shape_area(route_only)
                + _shape_area(marking_only)
                + breakdown_free
            ),
            "method": "ordered_non_overlapping_differences",
        },
        "completeness": {
            "relevantPlacementCount": len(relevant),
            "geometryComplete": geometry_complete,
            "planningReservationGeometryComplete": planning_inputs_complete,
            "operationalEvidenceComplete": operational_complete,
            "blockers": blockers,
            "unknownRequiredReservationCount": (
                len(missing_clearance)
                + len(incomplete_clearance)
                + len(incomplete_route_geometry)
                + len(incomplete_marking_geometry)
            ),
        },
    }


def _department_metric_summary(department: Mapping[str, Any]) -> dict[str, Any]:
    """Project one department into a bounded comparison record."""

    metrics = department.get("spatialMetrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    physical = metrics.get("physicalFloorContact")
    physical = physical if isinstance(physical, Mapping) else {}
    geometric = metrics.get("geometricFreeArea")
    geometric = geometric if isinstance(geometric, Mapping) else {}
    planning = metrics.get("knownPlanningFreeArea")
    planning = planning if isinstance(planning, Mapping) else {}
    operational = metrics.get("operationallyUsableFreeArea")
    operational = operational if isinstance(operational, Mapping) else {}
    completeness = metrics.get("completeness")
    completeness = completeness if isinstance(completeness, Mapping) else {}
    gross_area = department.get("areaSquareMeters")
    planning_free = planning.get("areaSquareMeters")
    operational_free = operational.get("areaSquareMeters")
    known_planning_utilization = (
        _round((float(gross_area) - float(planning_free)) / float(gross_area) * 100.0)
        if isinstance(gross_area, (int, float))
        and gross_area > GEOMETRY_EPSILON
        and isinstance(planning_free, (int, float))
        else None
    )
    operational_utilization = (
        _round((float(gross_area) - float(operational_free)) / float(gross_area) * 100.0)
        if isinstance(gross_area, (int, float))
        and gross_area > GEOMETRY_EPSILON
        and isinstance(operational_free, (int, float))
        and operational.get("evidenceStatus") == "derived"
        else None
    )
    return {
        "zoneId": department.get("zoneId"),
        "label": department.get("label"),
        "semanticType": department.get("semanticType"),
        "purpose": deepcopy(department.get("purpose") or []),
        "purposeEvidenceStatus": department.get("purposeEvidenceStatus"),
        "cardinalLocation": department.get("cardinalLocation"),
        "areaSquareMeters": department.get("areaSquareMeters"),
        "areaSquareFeet": department.get("areaSquareFeet"),
        "departmentAreaShare": deepcopy(
            department.get("departmentAreaShare") or {}
        ),
        "placementCount": department.get("placementCount"),
        "componentPlacementCount": department.get(
            "componentPlacementCount"
        ),
        "cellModuleCount": department.get("cellModuleCount"),
        "ungroupedOperationalPlacementCount": department.get(
            "ungroupedOperationalPlacementCount"
        ),
        "operationalUnitCount": department.get("operationalUnitCount"),
        "assetCategories": deepcopy(
            department.get("assetCategories") or {}
        ),
        "assetOperationalRoles": deepcopy(
            department.get("assetOperationalRoles") or {}
        ),
        "connectedRouteIds": deepcopy(
            department.get("connectedRouteIds") or []
        ),
        "netPhysicalFootprintSquareMeters": physical.get(
            "netUnionAreaSquareMeters"
        ),
        "physicalCoveragePercent": physical.get("coveragePercent"),
        "geometricFreeAreaSquareMeters": geometric.get("areaSquareMeters"),
        "geometricFreePercent": geometric.get("percent"),
        "knownPlanningFreeAreaSquareMeters": planning.get(
            "areaSquareMeters"
        ),
        "knownPlanningUtilizationPercent": known_planning_utilization,
        "operationallyUsableFreeAreaSquareMeters": operational.get(
            "areaSquareMeters"
        ),
        "operationalUtilizationPercent": operational_utilization,
        "operationalEvidenceStatus": operational.get("evidenceStatus"),
        "operationalBlockerCodes": sorted({
            str(item.get("code"))
            for item in completeness.get("blockers", [])
            if isinstance(item, Mapping) and item.get("code")
        }),
    }


DERIVED_METRIC_DEFINITIONS = (
    {
        "metricId": "department_gross_area",
        "label": "Department gross floor area",
        "unit": "m2",
        "method": "absolute area of the authored parent-department polygon",
        "evidenceStatus": "derived",
        "forbiddenSubstitutes": ["placement_count", "department_operational_utilization"],
    },
    {
        "metricId": "zone_area",
        "label": "Zone floor area",
        "unit": "m2",
        "method": "absolute shoelace area of the authored world-coordinate polygon",
        "evidenceStatus": "derived",
    },
    {
        "metricId": "gross_asset_footprint",
        "label": "Gross assigned asset footprint",
        "unit": "m2",
        "method": "sum of revision-bound asset footprint areas assigned by placement center",
        "evidenceStatus": "derived",
        "qualification": "May double-count overlapping footprints and is not net occupied area.",
    },
    {
        "metricId": "net_physical_floor_contact",
        "label": "Net physical floor-contact footprint",
        "unit": "m2",
        "method": (
            "union exact world-space physical polygons that intersect the "
            "floor plane, clipped to the requested scope"
        ),
        "evidenceStatus": "derived",
        "qualification": (
            "Overlaps are counted once and items stacked above the floor do "
            "not consume additional floor-contact area."
        ),
    },
    {
        "metricId": "gross_footprint_coverage",
        "label": "Gross footprint coverage",
        "unit": "percent",
        "method": "gross assigned asset footprint divided by exact zone polygon area",
        "evidenceStatus": "derived",
        "qualification": "Not utilization, capacity, congestion, or usable open area.",
    },
    {
        "metricId": "route_length",
        "label": "Authored route centerline length",
        "unit": "m",
        "method": "sum of X/Z centerline segment lengths",
        "evidenceStatus": "derived",
    },
    {
        "metricId": "geometric_free_area",
        "label": "Geometric free area",
        "unit": "m2",
        "method": "scope polygon minus net physical floor-contact union",
        "evidenceStatus": "derived",
        "qualification": (
            "Does not account for required clearances, protected routes, "
            "restrictions, maneuvering, access, or production capacity."
        ),
    },
    {
        "metricId": "known_planning_free_area",
        "label": "Known planning free area",
        "unit": "m2",
        "method": (
            "scope polygon minus the union of physical floor contact, declared "
            "clearances, route corridors, and semantic floor reservations"
        ),
        "evidenceStatus": "derived",
        "qualification": (
            "Available only when the current planning geometry is complete; "
            "it does not establish policy or safety compliance."
        ),
    },
    {
        "metricId": "operationally_usable_free_area",
        "label": "Operationally usable free area",
        "unit": "m2",
        "method": (
            "scope polygon minus authoritative physical, clearance, route, "
            "and semantic reservation geometry"
        ),
        "evidenceStatus": "derived",
        "qualification": (
            "Fails closed to unknown unless asset planning readiness, clearance "
            "evidence, route evidence, shell, and policy are complete and reviewed."
        ),
    },
    {
        "metricId": "department_physical_occupancy",
        "label": "Department physical occupancy",
        "unit": "percent",
        "method": "net physical floor-contact union divided by gross department area",
        "evidenceStatus": "derived",
        "forbiddenSubstitutes": ["placement_count", "department_gross_area"],
    },
    {
        "metricId": "department_known_planning_utilization",
        "label": "Known planning utilization",
        "unit": "percent",
        "method": (
            "gross department area minus known planning free area, divided "
            "by gross department area"
        ),
        "evidenceStatus": "derived",
        "qualification": (
            "Includes only currently authored reservation geometry. Missing "
            "required reservations remain explicit uncertainty."
        ),
        "forbiddenSubstitutes": ["placement_count", "department_gross_area"],
    },
    {
        "metricId": "department_operational_utilization",
        "label": "Operational utilization",
        "unit": "percent",
        "method": (
            "gross department area minus operationally usable free area, "
            "divided by gross department area"
        ),
        "evidenceStatus": "derived",
        "qualification": (
            "Unknown unless physical, clearance, route, shell, and policy "
            "evidence required by the metric is complete."
        ),
        "forbiddenSubstitutes": [
            "placement_count",
            "department_gross_area",
            "department_physical_occupancy",
        ],
    },
    {
        "metricId": "placement_count",
        "label": "Placement count",
        "unit": "count",
        "method": "count of persisted placement records in the requested scope",
        "evidenceStatus": "derived",
        "qualification": "Not an area, density, utilization, or capacity metric.",
    },
    {
        "metricId": "contiguous_free_regions",
        "label": "Contiguous free-space regions",
        "unit": "m2",
        "method": "connected polygon components after deterministic subtraction",
        "evidenceStatus": "derived",
        "qualification": (
            "The largest component bounds are descriptive and are not a "
            "candidate-equipment fit result."
        ),
    },
    {
        "metricId": "zone_boundary_distance",
        "label": "Zone-to-zone boundary distance",
        "unit": "m",
        "method": "minimum Euclidean distance between authored polygon boundaries",
        "evidenceStatus": "derived",
    },
)


def build_facility_semantic_map(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build one deterministic semantic map from revision-bound state."""

    if not isinstance(state, Mapping):
        raise TypeError("Facility semantic state must be an object.")
    zones = [
        item for item in state.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    ]
    polygons = {
        str(zone["zoneId"]): points
        for zone in zones
        for points in [_points(zone.get("boundary"))]
        if points is not None
    }
    zone_shapes = {
        zone_id: _shape_from_boundary([
            {"x": point[0], "z": point[1]} for point in points
        ])
        for zone_id, points in polygons.items()
    }
    shell = state.get("facilityShell")
    shell = shell if isinstance(shell, Mapping) else {}
    policy = state.get("facilityPolicy")
    policy = policy if isinstance(policy, Mapping) else {}
    floor_surfaces = [
        item for item in shell.get("floorSurfaces", [])
        if isinstance(item, Mapping)
    ]
    shell_shapes = [
        shape
        for item in floor_surfaces
        for shape in [_shape_from_boundary(item.get("boundary"))]
        if shape is not None
    ]
    shell_union = _union_shapes(shell_shapes)
    try:
        floor_elevation = min(
            float(item.get("elevation") or 0.0) for item in floor_surfaces
        ) if floor_surfaces else 0.0
    except (TypeError, ValueError):
        floor_elevation = 0.0
    parents, depths, child_counts = _zone_hierarchy(zones)
    cell_envelopes = []
    for zone in zones:
        zone_id = str(zone.get("zoneId") or "")
        zone_semantics = _zone_semantics(zone)
        is_cell = bool(
            _is_authored_cell_zone(zone)
            or zone_semantics.get("semanticType") == "workcell"
        )
        shape = zone_shapes.get(zone_id)
        if is_cell and shape is not None:
            cell_envelopes.append((zone_id, shape))
    all_bounds = (
        [tuple(shell_union.bounds)]
        if shell_union is not None
        else [polygon_bounds(points) for points in polygons.values()]
    )
    facility_bounds = (
        (
            min(item[0] for item in all_bounds),
            min(item[1] for item in all_bounds),
            max(item[2] for item in all_bounds),
            max(item[3] for item in all_bounds),
        )
        if all_bounds else None
    )
    assets = [
        _asset_semantics(item)
        for item in state.get("assets", [])
        if isinstance(item, Mapping) and item.get("assetId")
    ]
    asset_index = {
        (item["assetId"], item["assetDefinitionRevision"]): item
        for item in assets
    }
    placements = [
        item for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    ]
    geometry_index = _spatial_geometry_index(
        placements,
        floor_elevation=floor_elevation,
    )
    placement_counts: Counter[str] = Counter()
    category_counts: dict[str, Counter[str]] = {}
    role_counts: dict[str, Counter[str]] = {}
    placement_role_totals: Counter[str] = Counter()
    placement_semantics = []
    placement_zone_ids: dict[str, list[str]] = {}
    for placement in placements:
        key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        semantic_asset = asset_index.get(key) or _asset_semantics(placement)
        roles = semantic_asset.get("operationalRoles") or ["industrial_resource"]
        for role in roles:
            placement_role_totals[str(role)] += 1
        placement_id = str(placement.get("placementId") or "")
        zone_ids = sorted(
            str(item) for item in placement.get("zoneIds", []) or []
            if str(item)
        )
        placement_zone_ids[placement_id] = zone_ids
        placement_semantics.append({
            "placementId": placement_id,
            "assetId": key[0],
            "assetDefinitionRevision": key[1],
            "displayName": str(
                placement.get("displayName")
                or semantic_asset.get("displayName")
                or key[0]
            ),
            "category": str(
                placement.get("category")
                or semantic_asset.get("category")
                or "unknown"
            ),
            "semanticType": semantic_asset.get("semanticType"),
            "operationalRoles": list(roles),
            "functionalSides": deepcopy(
                semantic_asset.get("functionalSides") or {}
            ),
            "functionalSideEvidenceStatus": semantic_asset.get(
                "functionalSideEvidenceStatus", "unknown"
            ),
            "genericAccessNeeds": deepcopy(
                semantic_asset.get("genericAccessNeeds") or []
            ),
            "semanticEvidenceStatus": semantic_asset.get(
                "semanticTypeEvidenceStatus", "unknown"
            ),
            "zoneIds": zone_ids,
            "positionMode": placement.get("positionMode"),
            "locked": placement.get("positionMode") == "locked",
            "authorshipMode": (
                "manual"
                if placement.get("positionMode") == "manual"
                else "automatic"
                if placement.get("positionMode") == "auto"
                else "locked"
                if placement.get("positionMode") == "locked"
                else "unknown"
            ),
            "planningReady": placement.get("planningReady") is True,
            "planningReadinessEvidenceComplete": (
                placement.get("planningReadinessEvidenceComplete") is True
            ),
            "clearanceRecordCount": int(
                placement.get("clearanceRecordCount") or 0
            ),
            "layoutProvenance": _layout_provenance(placement),
        })
        for raw_zone_id in placement.get("zoneIds", []) or []:
            zone_id = str(raw_zone_id or "")
            if not zone_id:
                continue
            placement_counts[zone_id] += 1
            category_counts.setdefault(zone_id, Counter())[
                str(placement.get("category") or semantic_asset.get("category") or "unknown")
            ] += 1
            for role in roles:
                role_counts.setdefault(zone_id, Counter())[str(role)] += 1

    source_markings = [
        item for item in state.get("floorMarkings", [])
        if isinstance(item, Mapping) and item.get("markingId")
    ]
    routes = [
        _route_semantics(item, polygons)
        for item in state.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    ]
    source_routes = [
        item for item in state.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    ]
    routes, route_network_summary, route_crossings = _route_network_semantics(
        routes,
        source_routes,
        geometry_index,
        source_markings,
    )
    route_ids_by_zone: dict[str, list[str]] = {}
    for route in routes:
        for zone_id in route["connectedZoneIds"]:
            route_ids_by_zone.setdefault(zone_id, []).append(route["routeId"])

    semantic_zones = []
    for source_order, zone in enumerate(zones):
        zone_id = str(zone["zoneId"])
        points = polygons.get(zone_id)
        semantic = _zone_semantics(zone)
        area = abs(polygon_area(points)) if points is not None else None
        centroid = _polygon_centroid(points) if points is not None else None
        depth = depths.get(zone_id, 0)
        scope_kind = _scope_kind(
            semantic["semanticType"],
            str(zone.get("zoneType") or "unknown"),
            depth,
            child_counts.get(zone_id, 0),
        )
        spatial_metrics = _scope_spatial_metrics(
            scope_id=zone_id,
            boundary=points or (),
            scope_shape=zone_shapes.get(zone_id),
            geometry_index=geometry_index,
            routes=source_routes,
            markings=source_markings,
            shell=shell,
            policy=policy,
            cell_envelopes=cell_envelopes,
        )
        physical_contact = spatial_metrics.get("physicalFloorContact")
        physical_contact = (
            physical_contact
            if isinstance(physical_contact, Mapping)
            else {}
        )
        footprint = physical_contact.get("grossPolygonAreaSquareMeters")
        coverage = (
            float(footprint) / area * 100.0
            if footprint is not None
            and area is not None
            and area > GEOMETRY_EPSILON
            else None
        )
        semantic_zones.append({
            "zoneId": zone_id,
            "label": str(zone.get("label") or zone_id),
            "zoneType": str(zone.get("zoneType") or "unknown"),
            "semanticType": semantic["semanticType"],
            "purpose": semantic["purpose"],
            "purposeEvidenceStatus": semantic["evidenceStatus"],
            "purposeMethod": semantic["method"],
            "operationalRoles": semantic["operationalRoles"],
            "functionalInterfaces": deepcopy(
                semantic.get("functionalInterfaces") or {}
            ),
            "functionalInterfaceEvidenceStatus": semantic.get(
                "functionalInterfaceEvidenceStatus", "unknown"
            ),
            "layoutProvenance": _layout_provenance(zone),
            "scopeKind": scope_kind,
            "parentZoneId": parents.get(zone_id),
            "hierarchyDepth": depth,
            "childZoneCount": child_counts.get(zone_id, 0),
            "areaSquareMeters": _round(area) if area is not None else None,
            "areaSquareFeet": _round(area * SQUARE_METERS_TO_SQUARE_FEET) if area is not None else None,
            "areaEvidenceStatus": "derived" if area is not None else "unknown",
            "areaMethod": "authored_polygon_shoelace" if area is not None else None,
            "centroid": (
                {"x": _round(centroid[0]), "z": _round(centroid[1])}
                if centroid is not None else None
            ),
            "cardinalLocation": _cardinal_location(centroid, facility_bounds) if centroid is not None else "unknown",
            "cardinalLocationEvidenceStatus": "derived" if centroid is not None else "unknown",
            "placementCount": int(placement_counts.get(zone_id, 0)),
            "assetCategories": dict(sorted(category_counts.get(zone_id, Counter()).items())),
            "assetOperationalRoles": dict(sorted(role_counts.get(zone_id, Counter()).items())),
            "grossAssetFootprintAreaSquareMeters": (
                _round(float(footprint))
                if footprint is not None
                else None
            ),
            "footprintKnownPlacementCount": int(
                physical_contact.get("placementCount") or 0
            ),
            "grossFootprintCoveragePercent": _round(coverage) if coverage is not None else None,
            "grossFootprintMetricEvidenceStatus": physical_contact.get(
                "evidenceStatus", "unknown"
            ),
            "connectedRouteIds": sorted(route_ids_by_zone.get(zone_id, [])),
            "spatialMetrics": spatial_metrics,
            "sourceOrder": source_order,
        })

    departments = [item for item in semantic_zones if item["scopeKind"] == "department"]
    department_polygons = {
        item["zoneId"]: polygons[item["zoneId"]]
        for item in departments
        if item["zoneId"] in polygons
    }
    return _complete_facility_semantic_map(
        state=state,
        departments=departments,
        department_polygons=department_polygons,
        source_markings=source_markings,
        placement_zone_ids=placement_zone_ids,
        zone_shapes=zone_shapes,
        shell_union=shell_union,
        geometry_index=geometry_index,
        source_routes=source_routes,
        cell_envelopes=cell_envelopes,
        shell=shell,
        policy=policy,
        identity=(
            state.get("identity")
            if isinstance(state.get("identity"), Mapping)
            else {}
        ),
        facility_bounds=facility_bounds,
        semantic_zones=semantic_zones,
        routes=routes,
        route_network_summary=route_network_summary,
        route_crossings=route_crossings,
        assets=assets,
        placements=placements,
        placement_semantics=placement_semantics,
        placement_role_totals=placement_role_totals,
        zones=zones,
    )


_ENTITY_COLLECTION_CONTRACTS = {
    "placement": ("placements", "placementId", "displayName"),
    "zone": ("zones", "zoneId", "label"),
    "asset": ("assets", "assetId", "displayName"),
    "route": ("routes", "routeId", "label"),
    "floor_marking": ("floorMarkings", "markingId", "label"),
    "layout_pattern": ("layoutPatternGroups", "provenanceId", "provenanceId"),
}


def _query_tokens(value: Any) -> list[str]:
    text = re.sub(
        r"\b(?:the|a|an|same|current|selected|type|item|object)\b",
        " ",
        _normalized_text(value),
    )
    return [item for item in text.split() if item]


def resolve_facility_entities(
    state: Mapping[str, Any],
    *,
    query: str = "",
    entity_kinds: Sequence[str] = (),
    use_selection: bool = False,
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Resolve human labels and current selection to revision-bound entities."""

    semantic = build_facility_semantic_map(state)
    requested_kinds = tuple(entity_kinds) or tuple(
        _ENTITY_COLLECTION_CONTRACTS
    )
    invalid = sorted(set(requested_kinds) - set(_ENTITY_COLLECTION_CONTRACTS))
    if invalid:
        raise ValueError("Unsupported facility entity kind: " + ", ".join(invalid))
    maximum = max(1, min(int(maximum_results), 50))
    selection = state.get("selection")
    selection = selection if isinstance(selection, Mapping) else {}
    selection_keys = {
        "placement": "placementIds",
        "zone": "zoneIds",
        "route": "routeIds",
        "floor_marking": "floorMarkingIds",
    }
    selected_ids = {
        kind: {
            str(item) for item in selection.get(selection_keys.get(kind, ""), [])
            if str(item)
        }
        for kind in requested_kinds
    }
    tokens = _query_tokens(query)
    compact_query = " ".join(tokens)
    candidates = []
    for kind in requested_kinds:
        collection_name, id_field, label_field = _ENTITY_COLLECTION_CONTRACTS[kind]
        for record in semantic.get(collection_name, []):
            if not isinstance(record, Mapping):
                continue
            entity_id = str(record.get(id_field) or "")
            if not entity_id:
                continue
            selected = entity_id in selected_ids.get(kind, set())
            label = str(record.get(label_field) or entity_id)
            haystack = _normalized_text(
                entity_id,
                label,
                record.get("semanticType"),
                record.get("category"),
                record.get("authoredStrategy"),
            )
            if use_selection:
                if not selected:
                    continue
                score = 1000.0
                reason = "current_selection"
            elif not compact_query:
                continue
            elif compact_query in {
                _normalized_text(entity_id),
                _normalized_text(label),
            }:
                score = 900.0
                reason = "exact_label_or_id"
            elif compact_query and compact_query in haystack:
                score = 700.0 + len(compact_query) / max(len(haystack), 1)
                reason = "phrase_match"
            elif tokens and all(token in haystack for token in tokens):
                score = 500.0 + len(tokens)
                reason = "all_tokens_match"
            else:
                continue
            candidates.append({
                "entityKind": kind,
                "entityId": entity_id,
                "label": label,
                "score": _round(score),
                "matchReason": reason,
                "selected": selected,
                "assetId": record.get("assetId"),
                "assetDefinitionRevision": record.get(
                    "assetDefinitionRevision"
                ),
                "zoneIds": deepcopy(record.get("zoneIds") or []),
                "semanticType": record.get("semanticType"),
                "evidenceStatus": (
                    "authored" if reason == "current_selection" else "derived"
                ),
            })
    candidates.sort(
        key=lambda item: (-float(item["score"]), item["entityKind"], item["entityId"])
    )
    candidates = candidates[:maximum]
    if not candidates:
        status = "unresolved"
    elif len(candidates) == 1:
        status = "unique"
    elif candidates[0]["score"] > candidates[1]["score"]:
        status = "unique"
    else:
        status = "ambiguous"
    return {
        "query": query,
        "usedCurrentSelection": bool(use_selection),
        "resolutionStatus": status,
        "resolved": candidates[0] if status == "unique" else None,
        "candidates": candidates,
        "evidenceStatus": "derived",
        "qualification": (
            "Human labels and ephemeral current selection resolve to stable "
            "revision-bound entities. Ambiguous matches are never guessed."
        ),
    }


def _operational_analysis_units(
    state: Mapping[str, Any],
    *,
    unit_mode: str,
    scope_ids: set[str],
) -> list[dict[str, Any]]:
    placements = [
        item for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    ]
    shell = state.get("facilityShell")
    shell = shell if isinstance(shell, Mapping) else {}
    floor_surfaces = [
        item for item in shell.get("floorSurfaces", [])
        if isinstance(item, Mapping)
    ]
    try:
        floor_elevation = min(
            float(item.get("elevation") or 0.0) for item in floor_surfaces
        ) if floor_surfaces else 0.0
    except (TypeError, ValueError):
        floor_elevation = 0.0
    geometry_index = _spatial_geometry_index(
        placements,
        floor_elevation=floor_elevation,
    )
    zone_semantics = {
        str(item.get("zoneId")): item
        for item in build_facility_semantic_map(state).get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    raw_by_id = {
        str(item.get("placementId")): item for item in placements
    }
    raw_zones = {
        str(item.get("zoneId")): item
        for item in state.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    groups: dict[str, dict[str, Any]] = {}
    for record in geometry_index:
        placement = record["placement"]
        placement_id = str(record.get("placementId") or "")
        zone_ids = sorted({
            str(item) for item in placement.get("zoneIds", []) or [] if str(item)
        })
        if scope_ids and not scope_ids.intersection(zone_ids):
            continue
        cell_zone_ids = [
            zone_id for zone_id in zone_ids
            if _is_authored_cell_zone(raw_zones.get(zone_id, {}))
        ]
        group_zone = cell_zone_ids[-1] if cell_zone_ids else None
        key = (
            "cell:" + group_zone
            if unit_mode == "operational_units" and group_zone
            else "placement:" + placement_id
        )
        group = groups.setdefault(key, {
            "unitId": key,
            "unitKind": "cell_module" if group_zone else "placement",
            "label": (
                str(zone_semantics.get(group_zone, {}).get("label") or group_zone)
                if group_zone else str(
                    placement.get("displayName") or placement_id
                )
            ),
            "placementIds": [],
            "zoneIds": set(),
            "shapes": [],
            "geometryComplete": True,
        })
        group["placementIds"].append(placement_id)
        group["zoneIds"].update(zone_ids)
        group["shapes"].extend(record.get("floorPhysical", []))
        group["geometryComplete"] = bool(
            group["geometryComplete"]
            and record.get("physicalRecordCount", 0) >= 1
            and record.get("parsedPhysicalRecordCount")
            == record.get("physicalRecordCount")
            and not record.get("geometryProjectionError")
        )
    units = []
    for group in groups.values():
        shape = _union_shapes(group.pop("shapes"))
        units.append({
            **group,
            "placementIds": sorted(group["placementIds"]),
            "zoneIds": sorted(group["zoneIds"]),
            "shape": shape,
        })
    return sorted(units, key=lambda item: item["unitId"])


def analyze_facility_clearances(
    state: Mapping[str, Any],
    *,
    scope_ids: Sequence[str] = (),
    maximum_results: int = 10,
    unit_mode: str = "operational_units",
) -> dict[str, Any]:
    """Return exact physical separations without inventing requirements."""

    if unit_mode not in {"operational_units", "placements"}:
        raise ValueError("unitMode must be operational_units or placements")
    maximum = max(1, min(int(maximum_results), 50))
    scope = {str(item) for item in scope_ids if str(item)}
    units = _operational_analysis_units(
        state,
        unit_mode=unit_mode,
        scope_ids=scope,
    )
    records = []
    for left_index, left in enumerate(units):
        left_shape = left.get("shape")
        if left_shape is None or not left.get("geometryComplete"):
            continue
        for right in units[left_index + 1:]:
            right_shape = right.get("shape")
            if right_shape is None or not right.get("geometryComplete"):
                continue
            try:
                distance = float(left_shape.distance(right_shape))
                overlap = _shape_area(left_shape.intersection(right_shape))
            except (TypeError, ValueError, GEOSException):
                continue
            records.append({
                "subjectA": {
                    key: deepcopy(left[key])
                    for key in ("unitId", "unitKind", "label", "placementIds", "zoneIds")
                },
                "subjectB": {
                    key: deepcopy(right[key])
                    for key in ("unitId", "unitKind", "label", "placementIds", "zoneIds")
                },
                "actualEdgeToEdgeDistanceMeters": _round(distance),
                "actualEdgeToEdgeDistanceFeet": _round(distance * 3.280839895013123),
                "physicalOverlapAreaSquareMeters": _round(overlap),
                "geometricRelationship": (
                    "overlapping" if overlap > GEOMETRY_EPSILON
                    else "touching" if distance <= GEOMETRY_EPSILON
                    else "separated"
                ),
                "requirementStatus": "unknown",
                "evidenceStatus": "derived",
                "qualification": (
                    "Actual geometry is measured. Adequacy remains unknown "
                    "until an applicable required clearance is configured."
                ),
            })
    records.sort(key=lambda item: (
        item["actualEdgeToEdgeDistanceMeters"],
        item["subjectA"]["unitId"],
        item["subjectB"]["unitId"],
    ))
    incomplete = [
        item["unitId"] for item in units if not item.get("geometryComplete")
    ]
    return {
        "analysis": "clearances",
        "scopeIds": sorted(scope),
        "unitMode": unit_mode,
        "unitCount": len(units),
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "candidatePairCount": len(records),
        "incompleteGeometryUnitIds": incomplete[:20],
        "evidenceStatus": "derived" if not incomplete else "unknown",
    }


def analyze_facility_protected_intrusions(
    state: Mapping[str, Any],
    *,
    scope_ids: Sequence[str] = (),
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Intersect floor-contact geometry with authored protected areas."""

    maximum = max(1, min(int(maximum_results), 50))
    scope = {str(item) for item in scope_ids if str(item)}
    units = _operational_analysis_units(
        state,
        unit_mode="placements",
        scope_ids=scope,
    )
    protected = []
    for route in state.get("routes", []):
        if not isinstance(route, Mapping) or not route.get("routeId"):
            continue
        shape = _route_corridor_shape(route)
        if shape is not None:
            protected.append({
                "protectedAreaKind": "route",
                "protectedAreaId": str(route["routeId"]),
                "label": str(route.get("label") or route["routeId"]),
                "semanticRole": _route_semantics(route, {}).get("semanticRole"),
                "shape": shape,
            })
    protected_roles = {
        "pedestrian_lane",
        "forklift_lane",
        "material_flow",
        "keep_clear",
        "safety",
        "restricted",
    }
    for marking in state.get("floorMarkings", []):
        if not isinstance(marking, Mapping) or not marking.get("markingId"):
            continue
        role = str(marking.get("semanticRole") or "")
        marking_type = str(marking.get("markingType") or "")
        if role not in protected_roles and marking_type not in {
            "keep_clear", "restricted_zone", "crosswalk"
        }:
            continue
        shape = _oriented_rectangle_shape(marking)
        if shape is not None:
            protected.append({
                "protectedAreaKind": "floor_marking",
                "protectedAreaId": str(marking["markingId"]),
                "label": str(marking.get("label") or marking_type),
                "semanticRole": role or marking_type,
                "shape": shape,
            })
    records = []
    for unit in units:
        shape = unit.get("shape")
        if shape is None or not unit.get("geometryComplete"):
            continue
        for area in protected:
            try:
                overlap = _shape_area(shape.intersection(area["shape"]))
            except (TypeError, ValueError, GEOSException):
                continue
            if overlap <= GEOMETRY_EPSILON:
                continue
            records.append({
                "placementId": unit["placementIds"][0],
                "placementLabel": unit["label"],
                "protectedAreaKind": area["protectedAreaKind"],
                "protectedAreaId": area["protectedAreaId"],
                "protectedAreaLabel": area["label"],
                "semanticRole": area["semanticRole"],
                "intersectionAreaSquareMeters": _round(overlap),
                "evidenceStatus": "derived",
                "qualification": (
                    "Positive physical-footprint intersection with authored "
                    "protected geometry; severity and compliance require policy."
                ),
            })
    records.sort(key=lambda item: (
        -float(item["intersectionAreaSquareMeters"]),
        item["placementId"],
        item["protectedAreaId"],
    ))
    return {
        "analysis": "protected_intrusions",
        "scopeIds": sorted(scope),
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "totalCount": len(records),
        "evidenceStatus": "derived",
    }


def _linear_components(value: BaseGeometry | None) -> list[BaseGeometry]:
    if value is None or getattr(value, "is_empty", True):
        return []
    if getattr(value, "geom_type", "") in {"LineString", "LinearRing"}:
        return [value]
    result = []
    for child in getattr(value, "geoms", ()):
        result.extend(_linear_components(child))
    return result


def _geometry_coordinates(value: BaseGeometry | None) -> list[tuple[float, float]]:
    if value is None or getattr(value, "is_empty", True):
        return []
    if getattr(value, "geom_type", "") in {
        "Point", "LineString", "LinearRing",
    }:
        return [
            (float(item[0]), float(item[1])) for item in value.coords
        ]
    result = []
    exterior = getattr(value, "exterior", None)
    if exterior is not None:
        result.extend(_geometry_coordinates(exterior))
    for interior in getattr(value, "interiors", ()):
        result.extend(_geometry_coordinates(interior))
    for child in getattr(value, "geoms", ()):
        result.extend(_geometry_coordinates(child))
    return result


def _route_cross_section(
    line: LineString,
    distance: float,
    width: float,
) -> tuple[LineString, Point]:
    length = float(line.length)
    center = line.interpolate(max(0.0, min(length, distance)))
    delta = min(max(length * 0.000001, 0.001), 0.05)
    before = line.interpolate(max(0.0, distance - delta))
    after = line.interpolate(min(length, distance + delta))
    tangent_x = float(after.x - before.x)
    tangent_z = float(after.y - before.y)
    magnitude = math.hypot(tangent_x, tangent_z)
    if magnitude <= GEOMETRY_EPSILON:
        tangent_x, tangent_z, magnitude = 1.0, 0.0, 1.0
    normal_x = -tangent_z / magnitude
    normal_z = tangent_x / magnitude
    half_width = width / 2.0
    return LineString((
        (
            float(center.x) - normal_x * half_width,
            float(center.y) - normal_z * half_width,
        ),
        (
            float(center.x) + normal_x * half_width,
            float(center.y) + normal_z * half_width,
        ),
    )), center


def analyze_facility_route_widths(
    state: Mapping[str, Any],
    *,
    scope_ids: Sequence[str] = (),
    movement_class: str = "any",
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Measure nominal and known usable route width along actual geometry."""

    if movement_class not in {"material", "pedestrian", "conveyor", "any"}:
        raise ValueError(
            "movementClass must be material, pedestrian, conveyor, or any"
        )
    maximum = max(1, min(int(maximum_results), 50))
    requested_scope = {str(item) for item in scope_ids if str(item)}
    semantic = build_facility_semantic_map(state)
    semantic_routes = {
        str(item.get("routeId")): item
        for item in semantic.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    placements = [
        item for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    ]
    shell = state.get("facilityShell")
    shell = shell if isinstance(shell, Mapping) else {}
    elevations = [
        float(item.get("elevation") or 0.0)
        for item in shell.get("floorSurfaces", [])
        if isinstance(item, Mapping)
    ]
    floor_elevation = min(elevations) if elevations else 0.0
    geometry_index = _spatial_geometry_index(
        placements,
        floor_elevation=floor_elevation,
    )
    obstacles = []
    incomplete_geometry_ids = []
    for item in geometry_index:
        shape = _union_shapes(item.get("floorPhysical", []))
        if shape is not None:
            obstacles.append((str(item.get("placementId") or ""), shape))
        if not (
            item.get("physicalRecordCount", 0) >= 1
            and item.get("parsedPhysicalRecordCount")
            == item.get("physicalRecordCount")
            and not item.get("geometryProjectionError")
        ):
            incomplete_geometry_ids.append(str(item.get("placementId") or ""))
    obstacle_union = _union_shapes([shape for _, shape in obstacles])

    records = []
    unresolved_route_ids = []
    for route in state.get("routes", []):
        if not isinstance(route, Mapping) or not route.get("routeId"):
            continue
        route_id = str(route["routeId"])
        route_semantics = semantic_routes.get(route_id, {})
        route_class = _ROUTE_MOVEMENT_CLASS.get(
            str(route.get("routeKind") or ""),
            str(route.get("routeKind") or "unknown"),
        )
        if movement_class != "any" and route_class != movement_class:
            continue
        related_ids = {
            route_id,
            *(
                str(item)
                for item in route_semantics.get("connectedZoneIds", [])
                if str(item)
            ),
        }
        if requested_scope and not requested_scope.intersection(related_ids):
            continue
        points = _line_points(route.get("centerline"))
        try:
            width = float(route.get("corridorWidth"))
            line = LineString(points)
        except (TypeError, ValueError, GEOSException):
            unresolved_route_ids.append(route_id)
            continue
        if len(points) < 2 or width <= GEOMETRY_EPSILON or line.length <= 0:
            unresolved_route_ids.append(route_id)
            continue

        length = float(line.length)
        sample_distances = {0.0, length}
        regular_sample_count = min(256, max(16, int(math.ceil(length / max(
            0.25,
            min(width / 4.0, 2.0),
        )))))
        for index in range(regular_sample_count + 1):
            sample_distances.add(length * index / regular_sample_count)
        for _, obstacle in obstacles:
            if not obstacle.intersects(_route_corridor_shape(route)):
                continue
            for coordinate in _geometry_coordinates(obstacle):
                projected = float(line.project(Point(coordinate)))
                sample_distances.add(projected)
                sample_distances.add(max(0.0, projected - 0.001))
                sample_distances.add(min(length, projected + 0.001))

        samples = []
        for distance in sorted(sample_distances):
            cross_section, center = _route_cross_section(
                line,
                distance,
                width,
            )
            try:
                remaining = (
                    cross_section
                    if obstacle_union is None
                    else cross_section.difference(obstacle_union)
                )
            except (TypeError, ValueError, GEOSException):
                continue
            components = [
                item for item in _linear_components(remaining)
                if item.distance(center) <= GEOMETRY_EPSILON
            ]
            usable_width = max(
                (float(item.length) for item in components),
                default=0.0,
            )
            obstruction_ids = sorted(
                placement_id
                for placement_id, shape in obstacles
                if shape.intersects(cross_section)
            )
            samples.append({
                "distanceAlongRouteMeters": _round(distance),
                "position": {
                    "x": _round(center.x),
                    "z": _round(center.y),
                },
                "knownUsableWidthMeters": _round(usable_width),
                "knownUsableWidthFeet": _round(
                    usable_width * 3.280839895013123
                ),
                "obstructionPlacementIds": obstruction_ids,
            })
        if not samples:
            unresolved_route_ids.append(route_id)
            continue
        samples.sort(key=lambda item: (
            float(item["knownUsableWidthMeters"]),
            float(item["distanceAlongRouteMeters"]),
        ))
        minimum = samples[0]
        constrained = (
            float(minimum["knownUsableWidthMeters"])
            < width - GEOMETRY_EPSILON
        )
        records.append({
            "routeId": route_id,
            "routeLabel": str(route.get("label") or route_id),
            "routeKind": route.get("routeKind"),
            "movementClass": route_class,
            "authoredCorridorWidthMeters": _round(width),
            "authoredCorridorWidthFeet": _round(width * 3.280839895013123),
            "minimumKnownUsableWidthMeters": minimum[
                "knownUsableWidthMeters"
            ],
            "minimumKnownUsableWidthFeet": minimum[
                "knownUsableWidthFeet"
            ],
            "minimumWidthLocation": deepcopy(minimum["position"]),
            "distanceToMinimumMeters": minimum["distanceAlongRouteMeters"],
            "constrainingPlacementIds": deepcopy(
                minimum["obstructionPlacementIds"]
            ),
            "geometricWidthStatus": (
                "blocked"
                if minimum["knownUsableWidthMeters"] <= GEOMETRY_EPSILON
                else "constrained" if constrained else "nominal_width_clear"
            ),
            "policyAdequacyStatus": "unknown",
            "physicalGeometryComplete": not incomplete_geometry_ids,
            "criticalSamples": samples[:8],
            "evidenceStatus": "derived",
            "qualification": (
                "Usable width is the contiguous cross-route segment containing "
                "the authored centerline after subtracting known floor-contact "
                "physical geometry. It does not establish vehicle capacity, "
                "turning clearance, or regulatory adequacy."
            ),
        })
    records.sort(key=lambda item: (
        float(item["minimumKnownUsableWidthMeters"]),
        item["routeId"],
    ))
    return {
        "analysis": "route_widths",
        "scopeIds": sorted(requested_scope),
        "movementClass": movement_class,
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "totalCount": len(records),
        "unresolvedRouteIds": sorted(unresolved_route_ids),
        "incompletePhysicalGeometryPlacementIds": sorted(
            item for item in incomplete_geometry_ids if item
        )[:20],
        "evidenceStatus": "derived" if records else "unknown",
    }


_FREE_SPACE_METRICS = {
    "geometric": (
        "geometricFreeArea",
        "geometric_free_area",
        "Gross scope minus the union of physical floor-contact geometry.",
    ),
    "known_planning": (
        "knownPlanningFreeArea",
        "known_planning_free_area",
        (
            "Gross scope minus physical footprints and every currently authored "
            "clearance, route, keep-clear, and restricted reservation. Missing "
            "required reservations remain uncertainty."
        ),
    ),
    "operational": (
        "operationallyUsableFreeArea",
        "operationally_usable_free_area",
        (
            "Gross scope minus authoritative physical and operational "
            "reservations, available only when all evidence gates pass."
        ),
    ),
}


def analyze_facility_free_space(
    state: Mapping[str, Any],
    *,
    scope_ids: Sequence[str] = (),
    metric: str = "geometric",
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Return exact free-space metrics and connected-region evidence."""

    if metric not in _FREE_SPACE_METRICS:
        raise ValueError(
            "freeSpaceMetric must be geometric, known_planning, or operational"
        )
    maximum = max(1, min(int(maximum_results), 50))
    requested_scope = {str(item) for item in scope_ids if str(item)}
    semantic = build_facility_semantic_map(state)
    collection = [
        item for item in semantic.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    ]
    if requested_scope:
        collection = [
            item for item in collection
            if str(item.get("zoneId")) in requested_scope
        ]
    else:
        collection = [
            item for item in collection
            if item.get("scopeKind") == "department"
        ]
    source_key, metric_id, definition = _FREE_SPACE_METRICS[metric]
    records = []
    for scope in collection:
        metrics = scope.get("spatialMetrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        value = metrics.get(source_key)
        value = value if isinstance(value, Mapping) else {}
        completeness = metrics.get("completeness")
        completeness = completeness if isinstance(completeness, Mapping) else {}
        gross_area = metrics.get("grossAreaSquareMeters")
        free_area = value.get("areaSquareMeters")
        percent = value.get("percent")
        if (
            percent is None
            and isinstance(gross_area, (int, float))
            and gross_area > GEOMETRY_EPSILON
            and isinstance(free_area, (int, float))
        ):
            percent = _round(float(free_area) / float(gross_area) * 100.0)
        records.append({
            "scopeId": scope.get("zoneId"),
            "scopeLabel": scope.get("label"),
            "scopeKind": scope.get("scopeKind"),
            "metricId": metric_id,
            "grossAreaSquareMeters": gross_area,
            "freeAreaSquareMeters": free_area,
            "freeAreaSquareFeet": value.get("areaSquareFeet"),
            "freeAreaPercent": percent,
            "contiguousRegions": deepcopy(
                value.get("contiguousRegions") or {
                    "regionCount": 0,
                    "largestRegion": None,
                    "evidenceStatus": "unknown",
                }
            ),
            "evidenceStatus": value.get("evidenceStatus", "unknown"),
            "unknownRequiredReservationCount": completeness.get(
                "unknownRequiredReservationCount", 0
            ),
            "blockerCodes": sorted({
                str(item.get("code"))
                for item in completeness.get("blockers", [])
                if isinstance(item, Mapping) and item.get("code")
            }),
            "definition": definition,
            "qualification": value.get("qualification"),
        })
    records.sort(key=lambda item: (
        item["freeAreaSquareMeters"] is None,
        -float(item["freeAreaSquareMeters"] or 0.0),
        str(item["scopeId"]),
    ))
    unresolved_scope_ids = sorted(
        requested_scope - {str(item.get("scopeId")) for item in records}
    )
    return {
        "analysis": "free_space",
        "freeSpaceMetric": metric,
        "metricId": metric_id,
        "scopeIds": sorted(requested_scope),
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "totalCount": len(records),
        "unresolvedScopeIds": unresolved_scope_ids,
        "evidenceStatus": (
            "derived"
            if records and all(item["evidenceStatus"] == "derived" for item in records)
            else "unknown"
        ),
        "metricFidelity": (
            "This result never substitutes placement count, gross area, or "
            "another free-space definition for the requested metric."
        ),
    }


def analyze_facility_layout_provenance(
    state: Mapping[str, Any],
    *,
    query: str = "",
    scope_ids: Sequence[str] = (),
    use_selection: bool = False,
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Retrieve authored pattern/cell provenance and current drift."""

    maximum = max(1, min(int(maximum_results), 50))
    semantic = build_facility_semantic_map(state)
    requested_scope = {str(item) for item in scope_ids if str(item)}
    resolution = None
    if query or use_selection:
        resolution = resolve_facility_entities(
            state,
            query=query,
            entity_kinds=("zone", "placement", "layout_pattern"),
            use_selection=use_selection,
            maximum_results=20,
        )
        if resolution.get("resolutionStatus") == "unique":
            resolved = resolution.get("resolved") or {}
            requested_scope.add(str(resolved.get("entityId") or ""))
        elif resolution.get("resolutionStatus") in {"ambiguous", "unresolved"}:
            return {
                "analysis": "layout_provenance",
                "query": query,
                "resolution": resolution,
                "records": [],
                "returnedCount": 0,
                "totalCount": 0,
                "evidenceStatus": "unknown",
            }
    requested_scope.discard("")
    placement_zone_ids = {
        str(item.get("placementId")): {
            str(zone_id) for zone_id in item.get("zoneIds", []) if str(zone_id)
        }
        for item in semantic.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    records = []
    for group in semantic.get("layoutPatternGroups", []):
        if not isinstance(group, Mapping):
            continue
        member_ids = {
            str(item.get("entityId"))
            for item in group.get("members", [])
            if isinstance(item, Mapping) and item.get("entityId")
        }
        member_zone_ids = {
            zone_id
            for member_id in member_ids
            for zone_id in placement_zone_ids.get(member_id, set())
        }
        related_ids = (
            member_ids
            | member_zone_ids
            | {str(group.get("provenanceId") or "")}
            | {
                str(item) for item in group.get("seedEntityIds", [])
                if str(item)
            }
        )
        if requested_scope and not requested_scope.intersection(related_ids):
            continue
        records.append({
            "provenanceId": group.get("provenanceId"),
            "command": group.get("command"),
            "authoredStrategy": group.get("authoredStrategy"),
            "seedEntityIds": deepcopy(group.get("seedEntityIds") or []),
            "parameters": deepcopy(group.get("parameters") or {}),
            "memberCount": group.get("memberCount"),
            "modifiedMemberCount": group.get("modifiedMemberCount"),
            "currentClassification": deepcopy(
                group.get("currentClassification") or {}
            ),
            "members": deepcopy(group.get("members") or []),
            "relatedZoneIds": sorted(member_zone_ids),
            "evidenceStatus": "authored",
            "qualification": (
                "The creation command and parameters are authored provenance. "
                "Current conformance is derived by comparing current geometry "
                "with the authored geometry snapshot."
            ),
        })
    records.sort(key=lambda item: str(item.get("provenanceId") or ""))
    return {
        "analysis": "layout_provenance",
        "query": query,
        "scopeIds": sorted(requested_scope),
        "resolution": resolution,
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "totalCount": len(records),
        "evidenceStatus": "authored" if records else "unknown",
    }


_ROUTE_MOVEMENT_CLASS = {
    "pedestrian": "pedestrian",
    "operator": "pedestrian",
    "forklift": "material",
    "material": "material",
    "conveyor": "conveyor",
}


def _geometry_anchor_points(value: BaseGeometry | None) -> list[Point]:
    if value is None or getattr(value, "is_empty", True):
        return []
    geometry_type = getattr(value, "geom_type", "")
    if geometry_type == "Point":
        return [value]
    if geometry_type == "LineString":
        coordinates = list(value.coords)
        if not coordinates:
            return []
        return [Point(coordinates[0]), Point(coordinates[-1])]
    result = []
    for child in getattr(value, "geoms", ()):
        result.extend(_geometry_anchor_points(child))
    return result


def _route_path_search(
    routes: Sequence[Mapping[str, Any]],
    source_routes: Mapping[str, Mapping[str, Any]],
    source_shape: BaseGeometry,
    target_shape: BaseGeometry,
    *,
    excluded_route_ids: set[str],
) -> dict[str, Any] | None:
    lines: dict[str, LineString] = {}
    cut_distances: dict[str, set[float]] = {}
    for route in routes:
        route_id = str(route.get("routeId") or "")
        if not route_id or route_id in excluded_route_ids:
            continue
        points = _line_points(source_routes.get(route_id, {}).get("centerline"))
        if len(points) < 2:
            continue
        try:
            line = LineString(points)
        except (TypeError, ValueError, GEOSException):
            continue
        lines[route_id] = line
        cut_distances[route_id] = {0.0, float(line.length)}

    route_ids = sorted(lines)
    for index, left_id in enumerate(route_ids):
        left = lines[left_id]
        for right_id in route_ids[index + 1:]:
            right = lines[right_id]
            try:
                anchors = _geometry_anchor_points(left.intersection(right))
            except (TypeError, ValueError, GEOSException):
                anchors = []
            for point in anchors:
                cut_distances[left_id].add(float(left.project(point)))
                cut_distances[right_id].add(float(right.project(point)))
        for scope_shape in (source_shape, target_shape):
            try:
                anchors = _geometry_anchor_points(left.intersection(scope_shape))
            except (TypeError, ValueError, GEOSException):
                anchors = []
            for point in anchors:
                cut_distances[left_id].add(float(left.project(point)))

    def node_key(point: Point) -> tuple[float, float]:
        return (round(float(point.x), 7), round(float(point.y), 7))

    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float, str]]] = {}
    node_points: dict[tuple[float, float], Point] = {}
    for route_id in route_ids:
        line = lines[route_id]
        distances = sorted(cut_distances[route_id])
        route_nodes = []
        for distance in distances:
            point = line.interpolate(distance)
            key = node_key(point)
            node_points[key] = point
            graph.setdefault(key, [])
            route_nodes.append((distance, key))
        for left, right in zip(route_nodes, route_nodes[1:]):
            distance = max(0.0, float(right[0] - left[0]))
            if distance <= GEOMETRY_EPSILON or left[1] == right[1]:
                continue
            graph[left[1]].append((right[1], distance, route_id))
            graph[right[1]].append((left[1], distance, route_id))

    source_nodes = {
        key for key, point in node_points.items()
        if source_shape.buffer(GEOMETRY_EPSILON).covers(point)
    }
    target_nodes = {
        key for key, point in node_points.items()
        if target_shape.buffer(GEOMETRY_EPSILON).covers(point)
    }
    if not source_nodes or not target_nodes:
        return None
    distances = {node: 0.0 for node in source_nodes}
    predecessor: dict[
        tuple[float, float], tuple[tuple[float, float], str]
    ] = {}
    queue = [(0.0, node) for node in sorted(source_nodes)]
    heapq.heapify(queue)
    destination = None
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > distances.get(node, math.inf) + GEOMETRY_EPSILON:
            continue
        if node in target_nodes:
            destination = node
            break
        for neighbor, edge_length, route_id in graph.get(node, []):
            candidate = distance + edge_length
            if candidate + GEOMETRY_EPSILON >= distances.get(neighbor, math.inf):
                continue
            distances[neighbor] = candidate
            predecessor[neighbor] = (node, route_id)
            heapq.heappush(queue, (candidate, neighbor))
    if destination is None:
        return None
    nodes = [destination]
    edge_route_ids = []
    cursor = destination
    while cursor not in source_nodes:
        previous, route_id = predecessor[cursor]
        edge_route_ids.append(route_id)
        nodes.append(previous)
        cursor = previous
    nodes.reverse()
    edge_route_ids.reverse()
    path_route_ids = []
    for route_id in edge_route_ids:
        if not path_route_ids or path_route_ids[-1] != route_id:
            path_route_ids.append(route_id)
    return {
        "routeIds": path_route_ids,
        "distanceMeters": _round(distances[destination]),
        "distanceFeet": _round(
            distances[destination] * 3.280839895013123
        ),
        "sourceAccessPoint": {"x": nodes[0][0], "z": nodes[0][1]},
        "targetAccessPoint": {"x": nodes[-1][0], "z": nodes[-1][1]},
        "nodeCount": len(nodes),
    }


def _resolve_zone_scope(
    state: Mapping[str, Any],
    *,
    query: str,
    supplied_ids: Sequence[str],
) -> tuple[set[str], dict[str, Any] | None]:
    zone_ids = {str(item) for item in supplied_ids if str(item)}
    resolution = None
    if query and not zone_ids:
        resolution = resolve_facility_entities(
            state,
            query=query,
            entity_kinds=("zone",),
            maximum_results=20,
        )
        if resolution.get("resolutionStatus") == "unique":
            zone_ids.add(str((resolution.get("resolved") or {}).get("entityId")))
    zone_ids.discard("")
    return zone_ids, resolution


def analyze_facility_route_access(
    state: Mapping[str, Any],
    *,
    source_query: str = "",
    target_query: str = "",
    source_zone_ids: Sequence[str] = (),
    target_zone_ids: Sequence[str] = (),
    movement_class: str = "material",
) -> dict[str, Any]:
    """Build a centerline topology and find a geometry-derived route path."""

    if movement_class not in {"material", "pedestrian", "conveyor", "any"}:
        raise ValueError(
            "movementClass must be material, pedestrian, conveyor, or any"
        )
    source_ids, source_resolution = _resolve_zone_scope(
        state, query=source_query, supplied_ids=source_zone_ids
    )
    target_ids, target_resolution = _resolve_zone_scope(
        state, query=target_query, supplied_ids=target_zone_ids
    )
    resolution_status = "unique"
    for resolution in (source_resolution, target_resolution):
        if resolution and resolution.get("resolutionStatus") != "unique":
            resolution_status = str(resolution.get("resolutionStatus"))
    if not source_ids or not target_ids or resolution_status != "unique":
        return {
            "analysis": "route_access",
            "resolutionStatus": (
                resolution_status if resolution_status != "unique" else "unresolved"
            ),
            "sourceResolution": source_resolution,
            "targetResolution": target_resolution,
            "records": [],
            "evidenceStatus": "unknown",
        }
    semantic = build_facility_semantic_map(state)
    zone_shapes = {
        str(item.get("zoneId")): _shape_from_boundary(item.get("boundary"))
        for item in state.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    source_shape = _union_shapes([
        zone_shapes.get(zone_id) for zone_id in source_ids
    ])
    target_shape = _union_shapes([
        zone_shapes.get(zone_id) for zone_id in target_ids
    ])
    if source_shape is None or target_shape is None:
        return {
            "analysis": "route_access",
            "resolutionStatus": "geometry_unavailable",
            "sourceZoneIds": sorted(source_ids),
            "targetZoneIds": sorted(target_ids),
            "records": [],
            "evidenceStatus": "unknown",
        }
    routes = [
        item for item in semantic.get("routes", [])
        if isinstance(item, Mapping)
        and (
            movement_class == "any"
            or _ROUTE_MOVEMENT_CLASS.get(
                str(item.get("routeKind") or ""),
                str(item.get("routeKind") or ""),
            ) == movement_class
        )
    ]
    source_routes = {
        str(item.get("routeId")): item
        for item in state.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    topology_path = _route_path_search(
        routes,
        source_routes,
        source_shape,
        target_shape,
        excluded_route_ids=set(),
    )
    obstructed_ids = {
        str(item.get("routeId"))
        for item in routes
        if item.get("geometricObstructionStatus") == "obstructed"
    }
    usable_path = _route_path_search(
        routes,
        source_routes,
        source_shape,
        target_shape,
        excluded_route_ids=obstructed_ids,
    )
    chosen = usable_path or topology_path
    route_by_id = {
        str(item.get("routeId")): item for item in routes
    }
    chosen_ids = list((chosen or {}).get("routeIds") or [])
    unknown_obstruction_ids = [
        route_id for route_id in chosen_ids
        if route_by_id.get(route_id, {}).get("geometricObstructionStatus")
        == "unknown"
    ]
    widths = [
        float(route_by_id[route_id]["corridorWidthMeters"])
        for route_id in chosen_ids
        if isinstance(
            route_by_id.get(route_id, {}).get("corridorWidthMeters"),
            (int, float),
        )
    ]
    if topology_path is None:
        access_status = "disconnected"
    elif usable_path is None:
        access_status = "blocked"
    elif unknown_obstruction_ids:
        access_status = "connected_unverified"
    else:
        access_status = "connected"
    obstruction_records = [
        {
            "routeId": route_id,
            "placements": deepcopy(
                route_by_id.get(route_id, {}).get("geometricObstructions") or []
            ),
        }
        for route_id in sorted(obstructed_ids)
        if route_id in set((topology_path or {}).get("routeIds") or [])
    ]
    return {
        "analysis": "route_access",
        "resolutionStatus": "unique",
        "sourceZoneIds": sorted(source_ids),
        "targetZoneIds": sorted(target_ids),
        "sourceResolution": source_resolution,
        "targetResolution": target_resolution,
        "movementClass": movement_class,
        "accessStatus": access_status,
        "path": chosen,
        "topologyPath": topology_path,
        "minimumAuthoredCorridorWidthMeters": (
            _round(min(widths)) if widths else None
        ),
        "minimumAuthoredCorridorWidthFeet": (
            _round(min(widths) * 3.280839895013123) if widths else None
        ),
        "obstructedPathRoutes": obstruction_records,
        "unknownObstructionRouteIds": sorted(unknown_obstruction_ids),
        "evidenceStatus": (
            "derived" if access_status in {"connected", "blocked", "disconnected"}
            else "unknown"
        ),
        "qualification": (
            "Path length follows authored centerlines from their geometric "
            "intersection with the source zone to the target zone. Obstructed "
            "routes are conservatively excluded as whole segments. Nominal "
            "corridor width is not vehicle maneuvering or compliance proof."
        ),
    }


def _placement_position(record: Mapping[str, Any]) -> tuple[float, float] | None:
    transform = record.get("transform")
    transform = transform if isinstance(transform, Mapping) else {}
    position = transform.get("position")
    position = position if isinstance(position, Mapping) else {}
    try:
        return (float(position["x"]), float(position["z"]))
    except (KeyError, TypeError, ValueError):
        return None


def analyze_facility_operator_travel(
    state: Mapping[str, Any],
    *,
    scope_ids: Sequence[str] = (),
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Compare cells using authored sequence or an explicit geometric proxy."""

    maximum = max(1, min(int(maximum_results), 50))
    semantic = build_facility_semantic_map(state)
    requested_scope = {str(item) for item in scope_ids if str(item)}
    zones = [
        item for item in semantic.get("zones", [])
        if isinstance(item, Mapping)
        and item.get("zoneId")
        and (
            str(item.get("zoneId")) in requested_scope
            if requested_scope
            else item.get("scopeKind") == "subzone"
            and "cell" in _normalized_text(
                item.get("label"), item.get("semanticType")
            )
        )
    ]
    placement_semantics = {
        str(item.get("placementId")): item
        for item in semantic.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    raw_placements = {
        str(item.get("placementId")): item
        for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    relationships = semantic.get("processRelationships")
    relationships = relationships if isinstance(relationships, Mapping) else {}
    binding_by_id = {
        str(item.get("processBindingId")): item
        for item in relationships.get("bindings", [])
        if isinstance(item, Mapping) and item.get("processBindingId")
    }
    graph_edges = [
        item for item in relationships.get("relationshipEdges", [])
        if isinstance(item, Mapping)
    ]
    records = []
    for zone in zones:
        zone_id = str(zone.get("zoneId"))
        member_ids = [
            placement_id
            for placement_id, item in placement_semantics.items()
            if zone_id in set(item.get("zoneIds") or [])
            and _placement_position(raw_placements.get(placement_id, {}))
            is not None
        ]
        operator_ids = [
            placement_id for placement_id in member_ids
            if (
                placement_semantics[placement_id].get("semanticType")
                == "operator_reference"
                or "personnel_reference" in set(
                    placement_semantics[placement_id].get("operationalRoles") or []
                )
            )
        ]
        station_ids = [
            placement_id for placement_id in member_ids
            if placement_id not in operator_ids
        ]
        scoped_binding_ids = {
            binding_id for binding_id, binding in binding_by_id.items()
            if set(binding.get("placementIds") or []).intersection(station_ids)
        }
        indegree = {binding_id: 0 for binding_id in scoped_binding_ids}
        outgoing = {binding_id: set() for binding_id in scoped_binding_ids}
        for edge in graph_edges:
            left = str(edge.get("upstreamProcessBindingId") or "")
            right = str(edge.get("downstreamProcessBindingId") or "")
            if left in scoped_binding_ids and right in scoped_binding_ids:
                if right not in outgoing[left]:
                    outgoing[left].add(right)
                    indegree[right] += 1
        ready = sorted(
            binding_id for binding_id, degree in indegree.items() if degree == 0
        )
        binding_order = []
        while ready:
            binding_id = ready.pop(0)
            binding_order.append(binding_id)
            for neighbor in sorted(outgoing[binding_id]):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
                    ready.sort()
        authored_sequence = bool(
            len(binding_order) == len(scoped_binding_ids)
            and len(binding_order) >= 2
            and any(outgoing.values())
        )
        if authored_sequence:
            sequence = []
            for binding_id in binding_order:
                for placement_id in binding_by_id[binding_id].get(
                    "placementIds", []
                ):
                    if placement_id in station_ids and placement_id not in sequence:
                        sequence.append(placement_id)
            method = "authored_process_precedence_center_distance"
            evidence_status = "derived"
        else:
            remaining = set(station_ids)
            if operator_ids:
                current = _placement_position(raw_placements[operator_ids[0]])
            else:
                centroid = zone.get("centroid") or {}
                current = (
                    float(centroid.get("x") or 0.0),
                    float(centroid.get("z") or 0.0),
                )
            sequence = []
            while remaining and current is not None:
                next_id = min(
                    remaining,
                    key=lambda placement_id: (
                        math.dist(
                            current,
                            _placement_position(raw_placements[placement_id])
                            or current,
                        ),
                        placement_id,
                    ),
                )
                sequence.append(next_id)
                current = _placement_position(raw_placements[next_id])
                remaining.remove(next_id)
            method = "nearest_neighbor_station_center_proxy"
            evidence_status = "inferred"
        path_points = [
            _placement_position(raw_placements[placement_id])
            for placement_id in sequence
        ]
        path_points = [item for item in path_points if item is not None]
        travel = sum(
            math.dist(left, right)
            for left, right in zip(path_points, path_points[1:])
        )
        records.append({
            "zoneId": zone_id,
            "zoneLabel": zone.get("label"),
            "operatorPlacementIds": sorted(operator_ids),
            "stationPlacementIds": sorted(station_ids),
            "sequencePlacementIds": sequence,
            "travelDistanceMeters": _round(travel),
            "travelDistanceFeet": _round(travel * 3.280839895013123),
            "metricId": (
                "authored_sequence_station_center_distance"
                if authored_sequence
                else "geometric_station_center_proxy"
            ),
            "method": method,
            "evidenceStatus": evidence_status,
            "walkabilityValidated": False,
            "qualification": (
                "This measures center-to-center station travel for the authored "
                "process order. Walkable routing is not yet validated."
                if authored_sequence
                else "No complete authored process sequence was available. This "
                "is a deterministic nearest-neighbor center-distance proxy, not "
                "actual operator walking or an efficiency conclusion."
            ),
        })
    records.sort(key=lambda item: (
        item["travelDistanceMeters"], str(item["zoneId"])
    ))
    return {
        "analysis": "operator_travel",
        "scopeIds": sorted(requested_scope),
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "totalCount": len(records),
        "evidenceStatus": (
            "derived"
            if records and all(item["evidenceStatus"] == "derived" for item in records)
            else "inferred"
            if records else "unknown"
        ),
    }


_CELL_COMPARISON_STRATEGIES = CELL_FEASIBILITY_STRATEGIES


def _cell_strategy_samples(
    strategy: str,
    count: int,
    *,
    pitch: float,
    invert_u: bool,
) -> tuple[list[tuple[float, float]], dict[str, float]]:
    if count < 1:
        return [], {"usableWidth": 0.0, "usableDepth": 0.0}
    if strategy not in _CELL_COMPARISON_STRATEGIES:
        raise ValueError(
            "cell strategy must be one of "
            + ", ".join(_CELL_COMPARISON_STRATEGIES)
        )

    closed = False
    direct: list[tuple[float, float]] | None = None
    if strategy in {"line", "herringbone"}:
        usable_width = pitch * max(0, count - 1)
        usable_depth = pitch if strategy == "herringbone" and count > 1 else 0.0
        vertices = [
            (-usable_width / 2.0, 0.0),
            (usable_width / 2.0, 0.0),
        ]
        if strategy == "herringbone":
            direct = [
                (
                    -usable_width / 2.0 + pitch * index,
                    (-usable_depth / 2.0 if index % 2 == 0 else usable_depth / 2.0),
                )
                for index in range(count)
            ]
    elif strategy == "l":
        leg_segments = max(1, math.ceil((count - 1) / 2.0))
        usable_width = pitch * leg_segments
        usable_depth = pitch * leg_segments
        vertices = [
            (-usable_width / 2.0, -usable_depth / 2.0),
            (-usable_width / 2.0, usable_depth / 2.0),
            (usable_width / 2.0, usable_depth / 2.0),
        ]
    elif strategy == "u":
        leg_segments = max(1, math.ceil((count - 1) / 3.0))
        usable_width = pitch * leg_segments
        usable_depth = pitch * leg_segments
        vertices = [
            (-usable_width / 2.0, -usable_depth / 2.0),
            (-usable_width / 2.0, usable_depth / 2.0),
            (usable_width / 2.0, usable_depth / 2.0),
            (usable_width / 2.0, -usable_depth / 2.0),
        ]
        if invert_u:
            vertices = [(x_value, -z_value) for x_value, z_value in vertices]
    elif strategy == "loop":
        side_segments = max(1, math.ceil(count / 4.0))
        usable_width = pitch * side_segments
        usable_depth = pitch * side_segments
        vertices = [
            (-usable_width / 2.0, -usable_depth / 2.0),
            (-usable_width / 2.0, usable_depth / 2.0),
            (usable_width / 2.0, usable_depth / 2.0),
            (usable_width / 2.0, -usable_depth / 2.0),
        ]
        closed = True
    elif strategy == "cluster":
        if count < 3:
            usable_width = pitch * max(0, count - 1)
            usable_depth = 0.0
            direct = [
                (-usable_width / 2.0 + pitch * index, 0.0)
                for index in range(count)
            ]
        else:
            radius = pitch / (2.0 * math.sin(math.pi / count))
            usable_width = radius * 2.0
            usable_depth = radius * 2.0
            direct = [
                (
                    math.cos(index * 2.0 * math.pi / count) * radius,
                    math.sin(index * 2.0 * math.pi / count) * radius,
                )
                for index in range(count)
            ]
        vertices = []
    elif strategy == "spine":
        usable_width = pitch * max(0, count - 1)
        usable_depth = pitch if count > 1 else 0.0
        direct = [
            (
                -usable_width / 2.0 + pitch * index,
                (-usable_depth / 2.0 if index % 2 == 0 else usable_depth / 2.0),
            )
            for index in range(count)
        ]
        vertices = []
    else:
        row_count = (
            min(count, 2)
            if strategy == "parallel"
            else max(1, min(count, round(math.sqrt(count))))
        )
        column_count = math.ceil(count / row_count)
        usable_width = pitch * max(0, column_count - 1)
        usable_depth = pitch * max(0, row_count - 1)
        direct = []
        for row in range(row_count):
            z_value = usable_depth / 2.0 - pitch * row
            for column in range(column_count):
                logical_column = (
                    column_count - 1 - column
                    if strategy == "serpentine" and row % 2
                    else column
                )
                direct.append(
                    (
                        -usable_width / 2.0 + pitch * logical_column,
                        z_value,
                    )
                )
                if len(direct) == count:
                    break
            if len(direct) == count:
                break
        vertices = []

    if direct is not None:
        samples = direct
    elif count == 1:
        samples = [(0.0, 0.0)]
    else:
        path_points = list(vertices)
        if closed:
            path_points.append(vertices[0])
        path = LineString(path_points)
        divisor = count if closed else count - 1
        samples = [
            (
                float(path.interpolate(path.length * index / divisor).x),
                float(path.interpolate(path.length * index / divisor).y),
            )
            for index in range(count)
        ]
    return samples, {
        "usableWidth": _round(usable_width),
        "usableDepth": _round(usable_depth),
    }


def _shape_envelope_area(shapes: Sequence[BaseGeometry]) -> float:
    union = _union_shapes(list(shapes))
    if union is None:
        return 0.0
    minimum_x, minimum_z, maximum_x, maximum_z = union.bounds
    return max(0.0, (maximum_x - minimum_x) * (maximum_z - minimum_z))


def _minimum_shape_gap(shapes: Sequence[BaseGeometry]) -> float | None:
    distances = [
        float(left.distance(right))
        for index, left in enumerate(shapes)
        for right in shapes[index + 1:]
    ]
    return min(distances) if distances else None


def _travel_for_positions(
    sequence_ids: Sequence[str],
    positions: Mapping[str, tuple[float, float]],
) -> float:
    points = [positions[item] for item in sequence_ids if item in positions]
    return sum(math.dist(left, right) for left, right in zip(points, points[1:]))


def analyze_facility_cell_alternatives(
    state: Mapping[str, Any],
    *,
    query: str = "",
    scope_ids: Sequence[str] = (),
    strategies: Sequence[str] = _CELL_COMPARISON_STRATEGIES,
    preferred_gap_meters: float = 1.0,
    invert_u: bool = False,
) -> dict[str, Any]:
    """Compare bounded cell layouts without changing the authoritative state."""

    try:
        gap = float(preferred_gap_meters)
    except (TypeError, ValueError) as exc:
        raise ValueError("preferredGapMeters must be numeric") from exc
    if gap < 0 or gap > 20:
        raise ValueError("preferredGapMeters must be between 0 and 20")
    requested_strategies = []
    for raw in strategies:
        strategy = str(raw)
        if strategy not in _CELL_COMPARISON_STRATEGIES:
            raise ValueError(
                "cellStrategies supports "
                + ", ".join(_CELL_COMPARISON_STRATEGIES)
            )
        if strategy not in requested_strategies:
            requested_strategies.append(strategy)
    if (
        not requested_strategies
        or len(requested_strategies) > len(_CELL_COMPARISON_STRATEGIES)
    ):
        raise ValueError(
            "cellStrategies requires one to ten registered strategies"
        )

    zone_ids, resolution = _resolve_zone_scope(
        state,
        query=query,
        supplied_ids=scope_ids,
    )
    if resolution and resolution.get("resolutionStatus") != "unique":
        return {
            "analysis": "cell_alternatives",
            "resolutionStatus": resolution.get("resolutionStatus"),
            "resolution": resolution,
            "records": [],
            "evidenceStatus": "unknown",
        }
    if len(zone_ids) != 1:
        return {
            "analysis": "cell_alternatives",
            "resolutionStatus": "ambiguous" if zone_ids else "unresolved",
            "resolution": resolution,
            "records": [],
            "evidenceStatus": "unknown",
            "qualification": "Select or name exactly one authored cell zone.",
        }
    zone_id = next(iter(zone_ids))
    raw_zone = next((
        item for item in state.get("zones", [])
        if isinstance(item, Mapping) and str(item.get("zoneId") or "") == zone_id
    ), None)
    zone_shape = _shape_from_boundary(
        raw_zone.get("boundary") if isinstance(raw_zone, Mapping) else None
    )
    if zone_shape is None:
        return {
            "analysis": "cell_alternatives",
            "resolutionStatus": "geometry_unavailable",
            "zoneId": zone_id,
            "records": [],
            "evidenceStatus": "unknown",
        }

    semantic = build_facility_semantic_map(state)
    placement_semantics = {
        str(item.get("placementId")): item
        for item in semantic.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    placements = [
        item for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    ]
    geometry_index = _spatial_geometry_index(
        placements,
        floor_elevation=float(raw_zone.get("floorElevation") or 0.0),
    )
    geometry_by_id = {
        str(item.get("placementId")): item for item in geometry_index
    }
    members = []
    for placement in placements:
        placement_id = str(placement.get("placementId") or "")
        position = _placement_position(placement)
        explicitly_assigned = zone_id in {
            str(item) for item in placement.get("zoneIds", []) or []
        }
        geometrically_inside = bool(
            position is not None and zone_shape.covers(Point(position))
        )
        if explicitly_assigned or geometrically_inside:
            members.append(placement)
    members.sort(key=lambda item: str(item.get("placementId") or ""))
    member_ids = [str(item.get("placementId")) for item in members]
    if len(members) < 2:
        return {
            "analysis": "cell_alternatives",
            "resolutionStatus": "unique",
            "zoneId": zone_id,
            "zoneLabel": raw_zone.get("label"),
            "records": [],
            "blockerCodes": ["cell_requires_at_least_two_placements"],
            "evidenceStatus": "unknown",
        }
    locked_ids = sorted(
        str(item.get("placementId")) for item in members
        if item.get("positionMode") == "locked"
    )
    manual_ids = sorted(
        str(item.get("placementId")) for item in members
        if item.get("positionMode") == "manual"
    )
    missing_geometry_ids = sorted(
        placement_id for placement_id in member_ids
        if not geometry_by_id.get(placement_id, {}).get("floorPhysical")
    )
    if locked_ids or manual_ids or missing_geometry_ids:
        blockers = []
        if locked_ids:
            blockers.append("locked_cell_placements")
        if manual_ids:
            blockers.append("manual_cell_placements")
        if missing_geometry_ids:
            blockers.append("cell_physical_geometry_unavailable")
        return {
            "analysis": "cell_alternatives",
            "resolutionStatus": "unique",
            "zoneId": zone_id,
            "zoneLabel": raw_zone.get("label"),
            "records": [],
            "lockedPlacementIds": locked_ids,
            "manualPlacementIds": manual_ids,
            "missingGeometryPlacementIds": missing_geometry_ids,
            "blockerCodes": blockers,
            "evidenceStatus": "unknown",
        }

    operator_ids = sorted(
        placement_id for placement_id in member_ids
        if (
            placement_semantics.get(placement_id, {}).get("semanticType")
            == "operator_reference"
            or "personnel_reference" in set(
                placement_semantics.get(placement_id, {}).get(
                    "operationalRoles"
                ) or []
            )
        )
    )
    station_ids = [item for item in member_ids if item not in operator_ids]
    travel_analysis = analyze_facility_operator_travel(
        state,
        scope_ids=[zone_id],
        maximum_results=1,
    )
    travel_record = (
        travel_analysis.get("records", [{}])[0]
        if travel_analysis.get("records") else {}
    )
    sequence_ids = [
        item for item in travel_record.get("sequencePlacementIds", [])
        if item in station_ids
    ]
    sequence_ids.extend(
        item for item in station_ids if item not in sequence_ids
    )
    if len(station_ids) < 2:
        return {
            "analysis": "cell_alternatives",
            "resolutionStatus": "unique",
            "zoneId": zone_id,
            "zoneLabel": raw_zone.get("label"),
            "records": [],
            "blockerCodes": ["cell_requires_at_least_two_stations"],
            "evidenceStatus": "unknown",
        }

    current_positions = {
        str(item.get("placementId")): _placement_position(item)
        for item in members
    }
    current_positions = {
        key: value for key, value in current_positions.items()
        if value is not None
    }
    current_shapes = {
        placement_id: _union_shapes(
            geometry_by_id[placement_id].get("floorPhysical", [])
        )
        for placement_id in member_ids
    }
    current_clearances = {
        placement_id: _union_shapes(
            geometry_by_id[placement_id].get("floorClearance", [])
        )
        for placement_id in member_ids
    }
    clearance_complete = all(
        geometry_by_id[placement_id].get("clearanceRecordCount", 0) >= 1
        and geometry_by_id[placement_id].get("parsedClearanceRecordCount")
        == geometry_by_id[placement_id].get("clearanceRecordCount")
        and geometry_by_id[placement_id].get(
            "authoritativeClearanceRecordCount"
        ) == geometry_by_id[placement_id].get("clearanceRecordCount")
        for placement_id in member_ids
    )
    external_shapes = [
        shape
        for item in geometry_index
        if str(item.get("placementId")) not in set(member_ids)
        for shape in item.get("floorPhysical", [])
    ]
    external_union = _union_shapes(external_shapes)
    protected_shapes = []
    authored_route_ids = []
    for route in state.get("routes", []):
        if not isinstance(route, Mapping) or not route.get("routeId"):
            continue
        shape = _route_corridor_shape(route)
        if shape is not None and shape.intersects(zone_shape):
            protected_shapes.append((str(route["routeId"]), shape))
            authored_route_ids.append(str(route["routeId"]))
    protected_roles = {
        "pedestrian_lane", "forklift_lane", "material_flow", "keep_clear",
        "safety", "restricted",
    }
    for marking in state.get("floorMarkings", []):
        if not isinstance(marking, Mapping) or not marking.get("markingId"):
            continue
        if (
            str(marking.get("semanticRole") or "") not in protected_roles
            and str(marking.get("markingType") or "") not in {
                "keep_clear", "restricted_zone", "crosswalk",
            }
        ):
            continue
        shape = _oriented_rectangle_shape(marking)
        if shape is not None and shape.intersects(zone_shape):
            protected_shapes.append((str(marking["markingId"]), shape))

    minimum_x, minimum_z, maximum_x, maximum_z = zone_shape.bounds
    center_x = (minimum_x + maximum_x) / 2.0
    center_z = (minimum_z + maximum_z) / 2.0
    shape_radii = []
    for shape in current_shapes.values():
        low_x, low_z, high_x, high_z = shape.bounds
        shape_radii.append(math.hypot(high_x - low_x, high_z - low_z) / 2.0)
    maximum_radius = max(shape_radii)
    maximum_span = max(
        max(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1])
        for shape in current_shapes.values()
    )
    # A center pitch based only on the largest axis can satisfy a path interval
    # while still violating the requested edge gap at corners or on circular
    # strategies. The diagonal factor is conservative for heterogeneous,
    # axis-aligned source footprints and every strategy remains validated below.
    pitch = 1.5 * (maximum_span + gap)

    current_shape_values = [current_shapes[item] for item in member_ids]
    current_union = _union_shapes(current_shape_values)
    current_free = _shape_difference(
        zone_shape,
        _union_shapes([current_union, external_union]),
    )
    current_metrics = {
        "physicalFootprintUnionSquareMeters": _round(
            _shape_area(current_union)
        ),
        "cellEnvelopeAreaSquareMeters": _round(
            _shape_envelope_area(current_shape_values)
        ),
        "minimumPhysicalGapMeters": (
            _round(_minimum_shape_gap(current_shape_values))
            if _minimum_shape_gap(current_shape_values) is not None else None
        ),
        "geometricFreeAreaSquareMeters": _round(_shape_area(current_free)),
        "contiguousFreeRegions": _contiguous_region_summary(current_free),
        "operatorTravelDistanceMeters": _round(
            _travel_for_positions(sequence_ids, current_positions)
        ),
        "operatorTravelMetricId": travel_record.get(
            "metricId", "geometric_station_center_proxy"
        ),
        "operatorTravelEvidenceStatus": travel_record.get(
            "evidenceStatus", "inferred"
        ),
    }

    records = []
    for strategy in requested_strategies:
        offsets, guide = _cell_strategy_samples(
            strategy,
            len(station_ids),
            pitch=pitch,
            invert_u=invert_u,
        )
        required_width = guide["usableWidth"] + maximum_radius * 2.0
        required_depth = guide["usableDepth"] + maximum_radius * 2.0
        blocker_codes = []
        if required_width > maximum_x - minimum_x + GEOMETRY_EPSILON:
            blocker_codes.append("cell_width_insufficient")
        if required_depth > maximum_z - minimum_z + GEOMETRY_EPSILON:
            blocker_codes.append("cell_depth_insufficient")
        target_positions = {
            placement_id: (center_x + offset[0], center_z + offset[1])
            for placement_id, offset in zip(sequence_ids, offsets)
        }
        for index, placement_id in enumerate(operator_ids):
            if strategy == "line":
                operator_z = center_z - maximum_radius - gap
                operator_x = center_x + (
                    index - (len(operator_ids) - 1) / 2.0
                ) * pitch
                target_positions[placement_id] = (operator_x, operator_z)
            else:
                target_positions[placement_id] = (
                    center_x + (
                        index - (len(operator_ids) - 1) / 2.0
                    ) * pitch,
                    center_z,
                )
        candidate_shapes = {}
        candidate_clearances = {}
        proposed_transforms = []
        total_move = 0.0
        for placement in members:
            placement_id = str(placement.get("placementId"))
            current = current_positions[placement_id]
            target = target_positions[placement_id]
            x_offset = target[0] - current[0]
            z_offset = target[1] - current[1]
            candidate_shapes[placement_id] = shapely_affinity.translate(
                current_shapes[placement_id],
                xoff=x_offset,
                yoff=z_offset,
            )
            clearance = current_clearances.get(placement_id)
            candidate_clearances[placement_id] = (
                shapely_affinity.translate(
                    clearance,
                    xoff=x_offset,
                    yoff=z_offset,
                )
                if clearance is not None else None
            )
            total_move += math.dist(current, target)
            transform = placement.get("transform")
            transform = transform if isinstance(transform, Mapping) else {}
            current_position = transform.get("position")
            current_position = (
                current_position
                if isinstance(current_position, Mapping) else {}
            )
            proposed_transforms.append({
                "placementId": placement_id,
                "position": {
                    "x": _round(target[0]),
                    "y": _round(float(current_position.get("y") or 0.0)),
                    "z": _round(target[1]),
                },
                "quaternion": deepcopy(transform.get("quaternion")),
                "rotationPreserved": True,
            })
        shape_values = [candidate_shapes[item] for item in member_ids]
        boundary_violations = [
            placement_id for placement_id, shape in candidate_shapes.items()
            if not zone_shape.covers(shape)
        ]
        overlap_pairs = []
        insufficient_gap_pairs = []
        for left_index, left_id in enumerate(member_ids):
            left = candidate_shapes[left_id]
            for right_id in member_ids[left_index + 1:]:
                right = candidate_shapes[right_id]
                overlap = _shape_area(left.intersection(right))
                distance = float(left.distance(right))
                if overlap > GEOMETRY_EPSILON:
                    overlap_pairs.append([left_id, right_id])
                elif distance + GEOMETRY_EPSILON < gap:
                    insufficient_gap_pairs.append([left_id, right_id])
        external_collision_ids = sorted(
            placement_id for placement_id, shape in candidate_shapes.items()
            if external_union is not None
            and _shape_area(shape.intersection(external_union))
            > GEOMETRY_EPSILON
        )
        protected_hits = sorted({
            protected_id
            for shape in candidate_shapes.values()
            for protected_id, protected_shape in protected_shapes
            if _shape_area(shape.intersection(protected_shape))
            > GEOMETRY_EPSILON
        })
        clearance_conflicts = []
        if clearance_complete:
            for placement_id, clearance in candidate_clearances.items():
                if clearance is None or not zone_shape.covers(clearance):
                    clearance_conflicts.append(
                        "clearance_outside_cell:" + placement_id
                    )
                    continue
                if external_union is not None and clearance.intersects(
                    external_union
                ):
                    clearance_conflicts.append(
                        "clearance_external_conflict:" + placement_id
                    )
                for other_id, other_shape in candidate_shapes.items():
                    if other_id != placement_id and clearance.intersects(
                        other_shape
                    ):
                        clearance_conflicts.append(
                            "clearance_placement_conflict:"
                            + placement_id + ":" + other_id
                        )
        if boundary_violations:
            blocker_codes.append("candidate_outside_cell")
        if overlap_pairs:
            blocker_codes.append("candidate_physical_overlap")
        if insufficient_gap_pairs:
            blocker_codes.append("preferred_gap_not_met")
        if external_collision_ids:
            blocker_codes.append("external_placement_collision")
        if protected_hits:
            blocker_codes.append("protected_space_intrusion")
        if clearance_conflicts:
            blocker_codes.append("authored_clearance_conflict")
        blocker_codes = sorted(set(blocker_codes))
        geometry_valid = not blocker_codes
        candidate_union = _union_shapes(shape_values)
        candidate_free = _shape_difference(
            zone_shape,
            _union_shapes([candidate_union, external_union]),
        )
        candidate_travel = _travel_for_positions(
            sequence_ids,
            target_positions,
        )
        candidate_envelope = _shape_envelope_area(shape_values)
        records.append({
            "strategy": strategy,
            "strategyLabel": next(
                item["label"] for item in CELL_LAYOUT_STRATEGIES
                if item["strategyId"] == strategy
            ),
            "invertU": bool(strategy == "u" and invert_u),
            "validationStatus": (
                "clearance_validated"
                if geometry_valid and clearance_complete
                else "geometrically_valid_clearance_unverified"
                if geometry_valid else "rejected"
            ),
            "geometryValid": geometry_valid,
            "clearanceEvidenceComplete": clearance_complete,
            "blockerCodes": blocker_codes,
            "boundaryViolationPlacementIds": sorted(boundary_violations),
            "overlapPairs": overlap_pairs,
            "insufficientGapPairs": insufficient_gap_pairs,
            "externalCollisionPlacementIds": external_collision_ids,
            "protectedAreaIds": protected_hits,
            "clearanceConflicts": sorted(set(clearance_conflicts)),
            "guide": {
                **guide,
                "center": {"x": _round(center_x), "z": _round(center_z)},
                "requiredWidthMeters": _round(required_width),
                "requiredDepthMeters": _round(required_depth),
                "preferredGapMeters": _round(gap),
            },
            "metrics": {
                "requiredWidthMeters": _round(required_width),
                "requiredDepthMeters": _round(required_depth),
                "physicalFootprintUnionSquareMeters": _round(
                    _shape_area(candidate_union)
                ),
                "cellEnvelopeAreaSquareMeters": _round(candidate_envelope),
                "cellEnvelopeAreaDeltaSquareMeters": _round(
                    candidate_envelope
                    - current_metrics["cellEnvelopeAreaSquareMeters"]
                ),
                "minimumPhysicalGapMeters": (
                    _round(_minimum_shape_gap(shape_values))
                    if _minimum_shape_gap(shape_values) is not None else None
                ),
                "geometricFreeAreaSquareMeters": _round(
                    _shape_area(candidate_free)
                ),
                "contiguousFreeRegions": _contiguous_region_summary(
                    candidate_free
                ),
                "operatorTravelDistanceMeters": _round(candidate_travel),
                "operatorTravelDeltaMeters": _round(
                    candidate_travel
                    - current_metrics["operatorTravelDistanceMeters"]
                ),
                "operatorTravelMetricId": current_metrics[
                    "operatorTravelMetricId"
                ],
                "totalPlacementMovementMeters": _round(total_move),
                "routeConnectivityStatus": (
                    "authored_route_reaches_target_zone"
                    if authored_route_ids
                    else "unknown_no_authored_route_connection"
                ),
                "authoredRouteIds": sorted(set(authored_route_ids)),
                "accessStatus": (
                    "authoritative_clearances_validated"
                    if geometry_valid and clearance_complete
                    else "clearance_evidence_incomplete"
                    if geometry_valid
                    else "rejected"
                ),
                "clearanceEvidenceComplete": clearance_complete,
                "expansionReserveSquareMeters": _round(
                    _shape_area(candidate_free)
                ),
            },
            "proposedTransforms": sorted(
                proposed_transforms,
                key=lambda item: item["placementId"],
            ),
            "evidenceStatus": "derived",
            "qualification": (
                "This read-only geometric alternative preserves identities and "
                "rotations. Operator travel uses the stated sequence metric. "
                "It is not a throughput, ergonomic, or compliance conclusion."
            ),
        })
    records.sort(key=lambda item: (
        item["validationStatus"] == "rejected",
        item["validationStatus"] != "clearance_validated",
        float(item["metrics"]["operatorTravelDistanceMeters"]),
        float(item["metrics"]["cellEnvelopeAreaSquareMeters"]),
        _CELL_COMPARISON_STRATEGIES.index(item["strategy"]),
    ))
    selected = next(
        (item["strategy"] for item in records if item["geometryValid"]),
        None,
    )
    feasible_records = [
        deepcopy(item) for item in records if item["geometryValid"]
    ]
    rejected_records = [
        deepcopy(item) for item in records if not item["geometryValid"]
    ]
    return {
        "analysis": "cell_alternatives",
        "resolutionStatus": "unique",
        "resolution": resolution,
        "zoneId": zone_id,
        "zoneLabel": raw_zone.get("label"),
        "memberPlacementIds": member_ids,
        "stationPlacementIds": station_ids,
        "operatorPlacementIds": operator_ids,
        "sequencePlacementIds": sequence_ids,
        "currentMetrics": current_metrics,
        "preferredGapMeters": _round(gap),
        "selectedStrategy": selected,
        "records": records,
        "returnedCount": len(records),
        "rankedFeasibleRecords": feasible_records,
        "feasibleCount": len(feasible_records),
        "rejectedRecords": rejected_records,
        "rejectedCount": len(rejected_records),
        "evidenceStatus": "derived",
        "mutationPerformed": False,
        "qualification": (
            "Only rankedFeasibleRecords are recommendations. Rejected records "
            "are retained solely to explain deterministic blocker codes. "
            "Throughput, ergonomics, and compliance remain unknown."
        ),
    }


def _rotated_cardinal_side(side: str, angle_degrees: int) -> str:
    sides = ("north", "east", "south", "west")
    if side not in sides:
        return side
    steps = int(round(angle_degrees / 90.0)) % 4
    return sides[(sides.index(side) + steps) % 4]


def _interface_direction(
    record: Mapping[str, Any],
    side: str = "",
) -> tuple[float, float] | None:
    cardinal = _CARDINAL_VECTORS.get(side)
    if cardinal is not None:
        return cardinal
    facing = record.get("facing")
    if not isinstance(facing, Mapping):
        return None
    x_value = _finite_optional(facing.get("x"))
    z_value = _finite_optional(facing.get("z"))
    if x_value is None or z_value is None:
        return None
    magnitude = math.hypot(x_value, z_value)
    if magnitude <= GEOMETRY_EPSILON:
        return None
    return (x_value / magnitude, z_value / magnitude)


def _cardinal_side_for_direction(direction: tuple[float, float]) -> str:
    for side, vector in _CARDINAL_VECTORS.items():
        if (
            abs(direction[0] - vector[0]) <= 1e-7
            and abs(direction[1] - vector[1]) <= 1e-7
        ):
            return side
    return ""


def _rotate_floor_vector(
    direction: tuple[float, float],
    angle_degrees: float,
) -> tuple[float, float]:
    radians = math.radians(angle_degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        direction[0] * cosine + direction[1] * sine,
        -direction[0] * sine + direction[1] * cosine,
    )


def _transform_floor_point(
    x_value: float,
    z_value: float,
    *,
    source_center: Point,
    target_center: Point,
    angle_degrees: float,
) -> tuple[float, float]:
    rotated = _rotate_floor_vector(
        (x_value - source_center.x, z_value - source_center.y),
        angle_degrees,
    )
    return (
        target_center.x + rotated[0],
        target_center.y + rotated[1],
    )


def _transformed_module_interface(
    record: Mapping[str, Any],
    *,
    angle_degrees: int,
    source_center: Point,
    target_center: Point,
) -> dict[str, Any]:
    result = deepcopy(dict(record))
    side = str(result.get("side") or "").casefold()
    direction = _interface_direction(result, side)
    if direction is not None:
        transformed_direction = _rotate_floor_vector(
            direction, angle_degrees
        )
        cardinal = _cardinal_side_for_direction(transformed_direction)
        if cardinal:
            result["side"] = cardinal
            result.pop("facing", None)
        else:
            result.pop("side", None)
            result["facing"] = {
                "x": _round(transformed_direction[0]),
                "z": _round(transformed_direction[1]),
            }
    raw_position = result.get("position")
    if isinstance(raw_position, Mapping):
        x_value = _finite_optional(raw_position.get("x"))
        z_value = _finite_optional(raw_position.get("z"))
        if x_value is not None and z_value is not None:
            transformed = _transform_floor_point(
                x_value,
                z_value,
                source_center=source_center,
                target_center=target_center,
                angle_degrees=angle_degrees,
            )
            result["position"] = {
                "x": _round(transformed[0]),
                "z": _round(transformed[1]),
            }
    raw_envelope = result.get("accessEnvelope")
    if isinstance(raw_envelope, Sequence) and not isinstance(
        raw_envelope, (str, bytes)
    ):
        transformed_envelope = []
        for raw_point in raw_envelope:
            if not isinstance(raw_point, Mapping):
                continue
            x_value = _finite_optional(raw_point.get("x"))
            z_value = _finite_optional(raw_point.get("z"))
            if x_value is None or z_value is None:
                continue
            transformed = _transform_floor_point(
                x_value,
                z_value,
                source_center=source_center,
                target_center=target_center,
                angle_degrees=angle_degrees,
            )
            transformed_envelope.append({
                "x": _round(transformed[0]),
                "z": _round(transformed[1]),
            })
        if len(transformed_envelope) >= 3:
            result["accessEnvelope"] = transformed_envelope
    result["evidenceStatus"] = "derived"
    return result


def _module_interface_evidence(zone: Mapping[str, Any]) -> dict[str, Any]:
    semantics = _zone_semantics(zone)
    interfaces = semantics.get("functionalInterfaces")
    interfaces = interfaces if isinstance(interfaces, Mapping) else {}
    normalized = {}
    for role, raw in interfaces.items():
        record = raw if isinstance(raw, Mapping) else {"side": raw}
        side = str(record.get("side") or "").casefold()
        if _interface_direction(record, side) is None:
            continue
        status = str(record.get("evidenceStatus") or "authored")
        if status not in {"authored", "derived"}:
            continue
        normalized_record = deepcopy(dict(record))
        if side:
            normalized_record["side"] = side
        normalized_record["evidenceStatus"] = status
        normalized[str(role)] = normalized_record
    required_groups = (
        {"gate", "entrance"},
        {"loading", "material_input", "load_unload"},
        {"service", "maintenance"},
    )
    missing_groups = [
        sorted(group)
        for group in required_groups
        if not group.intersection(normalized)
    ]
    statuses = {
        str(item.get("evidenceStatus") or "unknown")
        for item in normalized.values()
    }
    return {
        "interfaces": dict(sorted(normalized.items())),
        "complete": not missing_groups,
        "missingRoleAlternatives": missing_groups,
        "evidenceStatus": (
            "authored" if "authored" in statuses
            else "derived" if "derived" in statuses
            else "unknown"
        ),
    }


def analyze_facility_module_fit(
    state: Mapping[str, Any],
    *,
    source_query: str = "",
    target_query: str = "",
    source_zone_ids: Sequence[str] = (),
    target_zone_ids: Sequence[str] = (),
    orientations_degrees: Sequence[int] = (0, 90),
    gap_meters: float = 1.0,
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Find bounded placements for a complete authored cell envelope."""

    maximum = max(1, min(int(maximum_results), 50))
    try:
        gap = float(gap_meters)
    except (TypeError, ValueError) as exc:
        raise ValueError("moduleGapMeters must be numeric") from exc
    if gap < 0 or gap > 100:
        raise ValueError("moduleGapMeters must be between 0 and 100")
    orientations = []
    for raw in orientations_degrees:
        if isinstance(raw, bool):
            raise ValueError("orientationsDegrees supports 0, 90, 180, 270")
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "orientationsDegrees supports 0, 90, 180, 270"
            ) from exc
        if value != raw or value not in {0, 90, 180, 270}:
            raise ValueError("orientationsDegrees supports 0, 90, 180, 270")
        if value not in orientations:
            orientations.append(value)
    if not orientations or len(orientations) > 4:
        raise ValueError("orientationsDegrees requires one to four values")

    source_ids, source_resolution = _resolve_zone_scope(
        state,
        query=source_query,
        supplied_ids=source_zone_ids,
    )
    target_ids, target_resolution = _resolve_zone_scope(
        state,
        query=target_query,
        supplied_ids=target_zone_ids,
    )
    if len(source_ids) != 1 or len(target_ids) != 1:
        return {
            "analysis": "module_fit",
            "resolutionStatus": "ambiguous" if source_ids or target_ids else "unresolved",
            "sourceResolution": source_resolution,
            "targetResolution": target_resolution,
            "records": [],
            "evidenceStatus": "unknown",
        }
    source_id = next(iter(source_ids))
    target_id = next(iter(target_ids))
    raw_zones = {
        str(item.get("zoneId")): item
        for item in state.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    source_zone = raw_zones.get(source_id)
    target_zone = raw_zones.get(target_id)
    source_shape = _shape_from_boundary(
        source_zone.get("boundary") if source_zone else None
    )
    target_shape = _shape_from_boundary(
        target_zone.get("boundary") if target_zone else None
    )
    if source_shape is None or target_shape is None:
        return {
            "analysis": "module_fit",
            "resolutionStatus": "geometry_unavailable",
            "sourceZoneId": source_id,
            "targetZoneId": target_id,
            "records": [],
            "evidenceStatus": "unknown",
        }
    source_center = source_shape.centroid
    placements = [
        item for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    ]
    members = []
    for placement in placements:
        position = _placement_position(placement)
        if (
            source_id in {
                str(item) for item in placement.get("zoneIds", []) or []
            }
            or position is not None and source_shape.covers(Point(position))
        ):
            members.append(placement)
    members.sort(key=lambda item: str(item.get("placementId") or ""))
    if not members:
        return {
            "analysis": "module_fit",
            "resolutionStatus": "unique",
            "sourceZoneId": source_id,
            "targetZoneId": target_id,
            "records": [],
            "blockerCodes": ["module_has_no_placement_members"],
            "evidenceStatus": "unknown",
        }

    floor_elevation = float(source_zone.get("floorElevation") or 0.0)
    geometry_index = _spatial_geometry_index(
        placements,
        floor_elevation=floor_elevation,
    )
    geometry_by_id = {
        str(item.get("placementId")): item for item in geometry_index
    }
    member_ids = [str(item.get("placementId")) for item in members]
    member_set = set(member_ids)
    missing_geometry_ids = sorted(
        placement_id for placement_id in member_ids
        if not geometry_by_id.get(placement_id, {}).get("floorPhysical")
    )
    clearance_complete = not missing_geometry_ids and all(
        geometry_by_id[placement_id].get("clearanceRecordCount", 0) >= 1
        and geometry_by_id[placement_id].get("parsedClearanceRecordCount")
        == geometry_by_id[placement_id].get("clearanceRecordCount")
        and geometry_by_id[placement_id].get(
            "authoritativeClearanceRecordCount"
        ) == geometry_by_id[placement_id].get("clearanceRecordCount")
        for placement_id in member_ids
    )
    clearance_shapes = [
        shape
        for placement_id in member_ids
        for shape in geometry_by_id.get(placement_id, {}).get(
            "floorClearance", []
        )
    ]
    clearance_within_envelope = bool(
        clearance_shapes
        and all(source_shape.covers(shape) for shape in clearance_shapes)
    )
    clearance_module_complete = bool(
        clearance_complete and clearance_within_envelope
    )
    interface_evidence = _module_interface_evidence(source_zone)

    external_shapes = [
        shape
        for item in geometry_index
        if str(item.get("placementId")) not in member_set
        for shape in item.get("floorPhysical", [])
    ]
    occupied_shapes = list(external_shapes)
    child_scope_shapes = []
    for zone_id, zone in raw_zones.items():
        if zone_id == target_id:
            continue
        shape = _shape_from_boundary(zone.get("boundary"))
        if shape is None or not shape.intersects(target_shape):
            continue
        extensions = zone.get("extensions")
        extensions = extensions if isinstance(extensions, Mapping) else {}
        cell_group = extensions.get("cellGroup")
        is_cell = (
            str(zone.get("zoneType") or "") == "workcell"
            or isinstance(cell_group, Mapping)
            and cell_group.get("groupKind") == "manufacturing_cell"
        )
        if is_cell:
            child_scope_shapes.append(shape)
    occupied_shapes.extend(child_scope_shapes)
    protected_shapes = []
    for route in state.get("routes", []):
        if not isinstance(route, Mapping):
            continue
        shape = _route_corridor_shape(route)
        if shape is not None and shape.intersects(target_shape):
            protected_shapes.append((str(route.get("routeId") or ""), shape))
    for marking in state.get("floorMarkings", []):
        if not isinstance(marking, Mapping):
            continue
        role = str(marking.get("semanticRole") or "")
        marking_type = str(marking.get("markingType") or "")
        if role not in {
            "pedestrian_lane", "forklift_lane", "material_flow", "keep_clear",
            "safety", "restricted",
        } and marking_type not in {"keep_clear", "restricted_zone", "crosswalk"}:
            continue
        shape = _oriented_rectangle_shape(marking)
        if shape is not None and shape.intersects(target_shape):
            protected_shapes.append((str(marking.get("markingId") or ""), shape))
    obstacle_union = _union_shapes(occupied_shapes)

    source_member_positions = {
        str(item.get("placementId")): _placement_position(item)
        for item in members
    }
    source_member_positions = {
        key: value for key, value in source_member_positions.items()
        if value is not None
    }
    source_markings = []
    for marking in state.get("floorMarkings", []):
        if not isinstance(marking, Mapping) or not marking.get("markingId"):
            continue
        transform = marking.get("transform")
        transform = transform if isinstance(transform, Mapping) else {}
        position = transform.get("position")
        position = position if isinstance(position, Mapping) else {}
        try:
            point = Point(float(position["x"]), float(position["z"]))
        except (KeyError, TypeError, ValueError):
            continue
        if source_shape.covers(point):
            source_markings.append(marking)

    target_min_x, target_min_z, target_max_x, target_max_z = target_shape.bounds
    configurations = []
    for orientation in orientations:
        rotated = shapely_affinity.rotate(
            source_shape,
            -orientation,
            origin=(source_center.x, source_center.y),
        )
        min_x, min_z, max_x, max_z = rotated.bounds
        width = max_x - min_x
        depth = max_z - min_z
        if width <= GEOMETRY_EPSILON or depth <= GEOMETRY_EPSILON:
            continue
        step_x = width + gap
        step_z = depth + gap
        anchors = []
        for phase_x in (0.0, step_x / 2.0):
            for phase_z in (0.0, step_z / 2.0):
                z_value = target_min_z + depth / 2.0 + phase_z
                while z_value <= target_max_z - depth / 2.0 + GEOMETRY_EPSILON:
                    x_value = target_min_x + width / 2.0 + phase_x
                    while x_value <= target_max_x - width / 2.0 + GEOMETRY_EPSILON:
                        anchors.append((_round(x_value), _round(z_value)))
                        x_value += step_x
                    z_value += step_z
        anchors.append((_round(target_shape.centroid.x), _round(target_shape.centroid.y)))
        unique_anchors = sorted(set(anchors), key=lambda item: (item[1], item[0]))
        accepted = []
        rejected_counts: Counter[str] = Counter()
        for center_x, center_z in unique_anchors[:1000]:
            candidate = shapely_affinity.translate(
                rotated,
                xoff=center_x - source_center.x,
                yoff=center_z - source_center.y,
            )
            codes = []
            if not target_shape.covers(candidate):
                codes.append("candidate_outside_target_zone")
            if obstacle_union is not None and _shape_area(
                candidate.intersection(obstacle_union)
            ) > GEOMETRY_EPSILON:
                codes.append("existing_layout_collision")
            protected_hits = sorted(
                protected_id for protected_id, shape in protected_shapes
                if _shape_area(candidate.intersection(shape))
                > GEOMETRY_EPSILON
            )
            if protected_hits:
                codes.append("protected_space_intrusion")
            if any(
                _shape_area(candidate.intersection(item["shape"]))
                > GEOMETRY_EPSILON
                for item in accepted
            ):
                codes.append("candidate_module_collision")
            if codes:
                rejected_counts.update(set(codes))
                continue
            accepted.append({
                "shape": candidate,
                "position": {"x": center_x, "z": center_z},
                "protectedAreaIds": protected_hits,
            })
            if len(accepted) >= maximum:
                break
        configurations.append({
            "orientationDegrees": orientation,
            "moduleWidthMeters": _round(width),
            "moduleDepthMeters": _round(depth),
            "probeCount": min(len(unique_anchors), 1000),
            "accepted": accepted,
            "rejectionCounts": dict(sorted(rejected_counts.items())),
        })
    configurations.sort(key=lambda item: (
        -len(item["accepted"]),
        item["orientationDegrees"],
    ))
    selected = configurations[0] if configurations else None
    candidates = []
    if selected:
        for index, accepted in enumerate(selected["accepted"], 1):
            center_x = float(accepted["position"]["x"])
            center_z = float(accepted["position"]["z"])
            angle = int(selected["orientationDegrees"])
            member_transforms = []
            for placement in members:
                placement_id = str(placement.get("placementId"))
                point = Point(source_member_positions[placement_id])
                rotated_point = shapely_affinity.rotate(
                    point,
                    -angle,
                    origin=(source_center.x, source_center.y),
                )
                transform = placement.get("transform")
                transform = transform if isinstance(transform, Mapping) else {}
                position = transform.get("position")
                position = position if isinstance(position, Mapping) else {}
                member_transforms.append({
                    "sourcePlacementId": placement_id,
                    "position": {
                        "x": _round(
                            rotated_point.x + center_x - source_center.x
                        ),
                        "y": _round(float(position.get("y") or 0.0)),
                        "z": _round(
                            rotated_point.y + center_z - source_center.y
                        ),
                    },
                    "rotationDeltaDegrees": angle,
                })
            marking_transforms = []
            for marking in source_markings:
                transform = marking.get("transform")
                transform = transform if isinstance(transform, Mapping) else {}
                position = transform.get("position")
                position = position if isinstance(position, Mapping) else {}
                point = Point(float(position["x"]), float(position["z"]))
                rotated_point = shapely_affinity.rotate(
                    point,
                    -angle,
                    origin=(source_center.x, source_center.y),
                )
                marking_transforms.append({
                    "sourceMarkingId": str(marking.get("markingId")),
                    "position": {
                        "x": _round(rotated_point.x + center_x - source_center.x),
                        "y": _round(float(position.get("y") or 0.0)),
                        "z": _round(rotated_point.y + center_z - source_center.y),
                    },
                    "rotationDeltaDegrees": angle,
                })
            target_center = Point(center_x, center_z)
            rotated_interfaces = {
                role: _transformed_module_interface(
                    record,
                    angle_degrees=angle,
                    source_center=source_center,
                    target_center=target_center,
                )
                for role, record in interface_evidence["interfaces"].items()
            }
            candidates.append({
                "candidateId": f"module-fit:{source_id}:{index:02d}",
                "moduleTransform": {
                    "position": {
                        "x": _round(center_x),
                        "z": _round(center_z),
                    },
                    "rotationDegrees": angle,
                },
                "memberTransforms": member_transforms,
                "floorMarkingTransforms": marking_transforms,
                "functionalInterfaces": rotated_interfaces,
                "geometricValid": True,
                "clearanceValidated": clearance_module_complete,
                "fullyValidated": False,
            })
    bounded_count = len(candidates)
    return {
        "analysis": "module_fit",
        "resolutionStatus": "unique",
        "sourceResolution": source_resolution,
        "targetResolution": target_resolution,
        "sourceZoneId": source_id,
        "sourceZoneLabel": source_zone.get("label"),
        "targetZoneId": target_id,
        "targetZoneLabel": target_zone.get("label"),
        "moduleMemberPlacementIds": member_ids,
        "moduleFloorMarkingIds": sorted(
            str(item.get("markingId")) for item in source_markings
        ),
        "modulePhysicalEnvelopeAreaSquareMeters": _round(source_shape.area),
        "moduleClearanceEvidenceComplete": clearance_module_complete,
        "functionalInterfaceEvidence": interface_evidence,
        "selectedOrientationDegrees": (
            selected["orientationDegrees"] if selected else None
        ),
        "boundedGeometricAdditionalCount": bounded_count,
        "boundedClearanceValidatedAdditionalCount": (
            bounded_count if clearance_module_complete else None
        ),
        "fullyValidatedAdditionalCapacity": None,
        "productionCapacity": None,
        "searchCompleteness": "bounded_grid_lower_bound_not_exhaustive",
        "orientationConfigurations": [
            {
                key: deepcopy(value)
                for key, value in item.items()
                if key != "accepted"
            } | {"acceptedCount": len(item["accepted"])}
            for item in configurations
        ],
        "candidates": candidates,
        "returnedCount": bounded_count,
        "evidenceStatus": "derived",
        "mutationPerformed": False,
        "qualification": (
            "The count is a bounded geometric lower bound for complete authored "
            "cell envelopes, not a proven maximum. Fully validated operational "
            "capacity remains unknown until gate/load/service interfaces, route "
            "access, clearance, and applicable policy evidence are complete."
        ),
    }


_CELL_INTERFACE_ROLE_GROUPS = (
    ("gate", frozenset({"gate", "entrance"})),
    (
        "loading",
        frozenset({"loading", "material_input", "load_unload"}),
    ),
    ("service", frozenset({"service", "maintenance"})),
)
_CARDINAL_VECTORS = {
    "north": (0.0, 1.0),
    "east": (1.0, 0.0),
    "south": (0.0, -1.0),
    "west": (-1.0, 0.0),
}


def _finite_optional(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _normalized_interface_role(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _interface_anchor(
    shape: BaseGeometry | None,
    record: Mapping[str, Any],
    side: str,
) -> Point | None:
    raw_point = (
        record.get("position")
        or record.get("point")
        or record.get("center")
    )
    if isinstance(raw_point, Mapping):
        x_value = _finite_optional(raw_point.get("x"))
        z_value = _finite_optional(raw_point.get("z"))
        if x_value is not None and z_value is not None:
            return Point(x_value, z_value)
    direction = _interface_direction(record, side)
    if shape is None or direction is None:
        return None
    minimum_x, minimum_z, maximum_x, maximum_z = shape.bounds
    center = shape.centroid
    reach = max(
        maximum_x - minimum_x,
        maximum_z - minimum_z,
        1.0,
    ) * 4.0
    target = Point(
        center.x + direction[0] * reach,
        center.y + direction[1] * reach,
    )
    if nearest_points is None:
        return target
    try:
        return nearest_points(shape.boundary, target)[0]
    except (TypeError, ValueError, GEOSException):
        return target


def _interface_access_shape(
    record: Mapping[str, Any],
    *,
    anchor: Point | None,
    side: str,
) -> tuple[BaseGeometry | None, str]:
    authored = (
        record.get("accessEnvelope")
        or record.get("approachEnvelope")
        or record.get("polygon")
    )
    if isinstance(authored, Mapping):
        authored = authored.get("polygon") or authored.get("boundary")
    shape = _shape_from_boundary(authored)
    if shape is not None:
        return shape, "authored_access_envelope"
    width = _finite_optional(
        record.get("openingWidthMeters", record.get("widthMeters"))
    )
    depth = _finite_optional(
        record.get("approachDepthMeters", record.get("depthMeters"))
    )
    if (
        anchor is None
        or _interface_direction(record, side) is None
        or width is None
        or depth is None
        or width <= GEOMETRY_EPSILON
        or depth <= GEOMETRY_EPSILON
    ):
        return None, "point_measurement_only"
    direction = _interface_direction(record, side)
    tangent = (-direction[1], direction[0])
    half_width = width / 2.0
    full_depth = depth
    return Polygon(tuple(
        (
            anchor.x + tangent[0] * width_sign * half_width
            + direction[0] * depth_fraction * full_depth,
            anchor.y + tangent[1] * width_sign * half_width
            + direction[1] * depth_fraction * full_depth,
        )
        for width_sign, depth_fraction in (
            (-1.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (-1.0, 1.0),
        )
    )), "derived_from_authored_width_depth_and_facing"


def _matching_route_kinds(interface_role: str) -> set[str]:
    if interface_role in {"loading", "material_input", "load_unload"}:
        return {"forklift", "material", "conveyor"}
    return {"forklift", "material", "conveyor", "pedestrian", "operator"}


def analyze_facility_cell_access(
    state: Mapping[str, Any],
    *,
    query: str = "",
    scope_ids: Sequence[str] = (),
    use_selection: bool = False,
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Measure authored cell interfaces against obstacles and route geometry."""

    maximum = max(1, min(int(maximum_results), 50))
    raw_zones = {
        str(item.get("zoneId")): item
        for item in state.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    semantic = build_facility_semantic_map(state)
    semantic_zones = {
        str(item.get("zoneId")): item
        for item in semantic.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    candidate_ids = {str(item) for item in scope_ids if str(item)}
    resolution = None
    if query:
        resolution = resolve_facility_entities(
            state,
            query=query,
            entity_kinds=("zone",),
            maximum_results=20,
        )
        if resolution.get("resolutionStatus") == "unique":
            candidate_ids.add(str(
                (resolution.get("resolved") or {}).get("entityId") or ""
            ))
    if use_selection:
        selection = state.get("selection")
        selection = selection if isinstance(selection, Mapping) else {}
        candidate_ids.update(
            str(item) for item in selection.get("zoneIds", []) if str(item)
        )
        selected_placements = {
            str(item)
            for item in selection.get("placementIds", [])
            if str(item)
        }
        for placement in state.get("placements", []):
            if (
                isinstance(placement, Mapping)
                and str(placement.get("placementId")) in selected_placements
            ):
                candidate_ids.update(
                    str(item)
                    for item in placement.get("zoneIds", [])
                    if str(item)
                )
    candidate_ids.discard("")
    cell_ids = {
        zone_id
        for zone_id, zone in raw_zones.items()
        if _is_authored_cell_zone(zone)
    }
    if candidate_ids:
        requested = set(candidate_ids)
        changed = True
        while changed:
            changed = False
            for zone_id, zone in semantic_zones.items():
                if (
                    zone_id in cell_ids
                    and zone.get("parentZoneId") in requested
                    and zone_id not in requested
                ):
                    requested.add(zone_id)
                    changed = True
        cell_ids &= requested

    shell = state.get("facilityShell")
    shell = shell if isinstance(shell, Mapping) else {}
    floor_surfaces = [
        item for item in shell.get("floorSurfaces", [])
        if isinstance(item, Mapping)
    ]
    floor_elevation = min(
        (_finite_optional(item.get("elevation")) or 0.0)
        for item in floor_surfaces
    ) if floor_surfaces else 0.0
    geometry_index = _spatial_geometry_index(
        [
            item for item in state.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        ],
        floor_elevation=floor_elevation,
    )
    source_routes = {
        str(item.get("routeId")): item
        for item in state.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    semantic_routes = {
        str(item.get("routeId")): item
        for item in semantic.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    route_shapes = {
        route_id: _route_corridor_shape(route)
        for route_id, route in source_routes.items()
    }
    records = []
    for zone_id in sorted(cell_ids):
        raw_zone = raw_zones[zone_id]
        zone_shape = _shape_from_boundary(raw_zone.get("boundary"))
        interface_evidence = _module_interface_evidence(raw_zone)
        raw_interfaces = _zone_semantics(raw_zone).get("functionalInterfaces")
        raw_interfaces = (
            raw_interfaces if isinstance(raw_interfaces, Mapping) else {}
        )
        interface_records = []
        for raw_role, raw_value in sorted(
            raw_interfaces.items(), key=lambda item: str(item[0])
        ):
            role = _normalized_interface_role(raw_role)
            value = raw_value if isinstance(raw_value, Mapping) else {
                "side": raw_value,
            }
            side = str(value.get("side") or "").casefold()
            anchor = _interface_anchor(zone_shape, value, side)
            access_shape, access_method = _interface_access_shape(
                value,
                anchor=anchor,
                side=side,
            )
            obstacle_records = []
            nearest_distance = None
            for geometry in geometry_index:
                placement_shape = _union_shapes(
                    geometry.get("floorPhysical", [])
                )
                if placement_shape is None or anchor is None:
                    continue
                distance = float(anchor.distance(placement_shape))
                nearest_distance = (
                    distance if nearest_distance is None
                    else min(nearest_distance, distance)
                )
                overlap = 0.0
                if (
                    access_shape is not None
                    and access_shape.intersects(placement_shape)
                ):
                    overlap = _shape_area(
                        access_shape.intersection(placement_shape)
                    )
                if overlap > GEOMETRY_EPSILON:
                    obstacle_records.append({
                        "placementId": geometry.get("placementId"),
                        "intersectionAreaSquareMeters": _round(overlap),
                    })
            obstacle_records.sort(
                key=lambda item: str(item.get("placementId") or "")
            )
            route_probe = access_shape or (
                anchor.buffer(GEOMETRY_EPSILON) if anchor is not None else None
            )
            matching_kinds = _matching_route_kinds(role)
            matching_route_ids = [
                route_id
                for route_id, route in source_routes.items()
                if str(route.get("routeKind") or "") in matching_kinds
            ]
            connected_route_ids = sorted(
                route_id for route_id in matching_route_ids
                if route_probe is not None
                and route_shapes.get(route_id) is not None
                and route_probe.intersects(route_shapes[route_id])
            )
            nearest_route_distance = None
            if anchor is not None:
                distances = [
                    float(anchor.distance(route_shapes[route_id]))
                    for route_id in matching_route_ids
                    if route_shapes.get(route_id) is not None
                ]
                if distances:
                    nearest_route_distance = min(distances)
            if obstacle_records:
                status = "obstructed"
            elif access_shape is None:
                status = "point_measured_access_envelope_unknown"
            elif connected_route_ids:
                status = "route_connected_no_static_footprint_intrusion"
            elif matching_route_ids:
                status = "not_connected_to_matching_route"
            else:
                status = "matching_route_evidence_unavailable"
            interface_records.append({
                "role": role,
                "side": side if side in _CARDINAL_VECTORS else None,
                "anchor": (
                    {"x": _round(anchor.x), "z": _round(anchor.y)}
                    if anchor is not None else None
                ),
                "openingWidthMeters": _finite_optional(
                    value.get("openingWidthMeters", value.get("widthMeters"))
                ),
                "approachDepthMeters": _finite_optional(
                    value.get("approachDepthMeters", value.get("depthMeters"))
                ),
                "accessEnvelopeAreaSquareMeters": (
                    _round(_shape_area(access_shape))
                    if access_shape is not None else None
                ),
                "accessEnvelopeMethod": access_method,
                "nearestPhysicalObstacleDistanceMeters": (
                    _round(nearest_distance)
                    if nearest_distance is not None else None
                ),
                "staticFootprintIntrusions": obstacle_records,
                "connectedMatchingRouteIds": connected_route_ids,
                "nearestMatchingRouteDistanceMeters": (
                    _round(nearest_route_distance)
                    if nearest_route_distance is not None else None
                ),
                "connectedRouteObstructionStatuses": [
                    {
                        "routeId": route_id,
                        "obstructionStatus": semantic_routes.get(
                            route_id, {}
                        ).get("obstructionStatus"),
                    }
                    for route_id in connected_route_ids
                ],
                "geometryStatus": status,
                "adequacyStatus": "unknown_without_applicable_policy",
                "evidenceStatus": (
                    str(value.get("evidenceStatus"))
                    if value.get("evidenceStatus") in EVIDENCE_STATUSES
                    else "authored"
                ),
            })
        role_names = {item["role"] for item in interface_records}
        missing = [
            sorted(aliases)
            for _group_name, aliases in _CELL_INTERFACE_ROLE_GROUPS
            if not aliases.intersection(role_names)
        ]
        records.append({
            "zoneId": zone_id,
            "zoneLabel": raw_zone.get("label"),
            "memberPlacementIds": sorted(
                str(item.get("placementId"))
                for item in state.get("placements", [])
                if isinstance(item, Mapping)
                and zone_id in set(item.get("zoneIds", []) or [])
            ),
            "functionalInterfaceEvidence": interface_evidence,
            "interfaces": interface_records,
            "missingRoleAlternatives": missing,
            "interfaceEvidenceComplete": not missing,
            "staticObstructedInterfaceCount": sum(
                item["geometryStatus"] == "obstructed"
                for item in interface_records
            ),
            "routeConnectedInterfaceCount": sum(
                bool(item["connectedMatchingRouteIds"])
                for item in interface_records
            ),
            "evidenceStatus": "derived" if interface_records else "unknown",
        })
    return {
        "analysis": "cell_access",
        "query": query,
        "scopeIds": sorted({str(item) for item in scope_ids if str(item)}),
        "resolution": resolution,
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "totalCount": len(records),
        "evidenceStatus": "derived" if records else "unknown",
        "mutationPerformed": False,
        "qualification": (
            "This measures authored interface points/envelopes against static "
            "floor footprints and route corridors. Missing interfaces remain "
            "unknown, and geometric access does not establish policy or safety "
            "adequacy."
        ),
    }


_ASSET_ACCESS_ROLE_ALIASES = {
    "service": ("service", "maintenance", "rear"),
    "operator": ("operator", "front"),
    "loading": ("loading", "material_input", "material_output"),
    "material_input": ("material_input", "loading"),
    "material_output": ("material_output", "loading"),
    "front": ("front", "operator"),
    "rear": ("rear", "service", "maintenance"),
}


def _access_probe_shape(
    shape: BaseGeometry,
    anchor: Point,
    direction: tuple[float, float],
    reach: float,
) -> tuple[BaseGeometry, LineString]:
    """Build a conservative outward corridor across one physical side."""

    tangent = (-direction[1], direction[0])
    minimum_x, minimum_z, maximum_x, maximum_z = shape.bounds
    corners = (
        (minimum_x, minimum_z),
        (minimum_x, maximum_z),
        (maximum_x, minimum_z),
        (maximum_x, maximum_z),
    )
    projections = [
        x_value * tangent[0] + z_value * tangent[1]
        for x_value, z_value in corners
    ]
    half_width = max(
        (max(projections) - min(projections)) / 2.0,
        GEOMETRY_EPSILON,
    )
    side_start = (
        anchor.x - tangent[0] * half_width,
        anchor.y - tangent[1] * half_width,
    )
    side_end = (
        anchor.x + tangent[0] * half_width,
        anchor.y + tangent[1] * half_width,
    )
    far_end = (
        side_end[0] + direction[0] * reach,
        side_end[1] + direction[1] * reach,
    )
    far_start = (
        side_start[0] + direction[0] * reach,
        side_start[1] + direction[1] * reach,
    )
    return Polygon((side_start, side_end, far_end, far_start)), LineString(
        (side_start, side_end)
    )


def analyze_facility_asset_access(
    state: Mapping[str, Any],
    *,
    interface_role: str = "service",
    query: str = "",
    scope_ids: Sequence[str] = (),
    use_selection: bool = False,
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Measure an authored asset side without inventing side requirements."""

    role = _normalized_interface_role(interface_role)
    aliases = _ASSET_ACCESS_ROLE_ALIASES.get(role)
    if aliases is None:
        raise ValueError("interfaceRole is unsupported")
    maximum = max(1, min(int(maximum_results), 50))
    semantic = build_facility_semantic_map(state)
    semantic_placements = {
        str(item.get("placementId")): item
        for item in semantic.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    placements = [
        item for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    ]
    raw_by_id = {
        str(item.get("placementId")): item for item in placements
    }
    requested_ids = {str(item) for item in scope_ids if str(item)}
    requested_asset_ids = {
        str(item.get("assetId"))
        for item in placements
        if str(item.get("assetId") or "") in requested_ids
    }
    requested_zone_ids = {
        str(item.get("zoneId"))
        for item in state.get("zones", [])
        if isinstance(item, Mapping)
        and str(item.get("zoneId") or "") in requested_ids
    }
    requested_placement_ids = set(raw_by_id).intersection(requested_ids)
    resolution = None
    if query:
        resolution = resolve_facility_entities(
            state,
            query=query,
            entity_kinds=("placement", "asset"),
            maximum_results=20,
        )
        matches = resolution.get("candidates") or []
        for resolved in matches:
            if resolved.get("entityKind") == "placement":
                requested_placement_ids.add(str(resolved.get("entityId")))
            elif resolved.get("entityKind") == "asset":
                requested_asset_ids.add(str(resolved.get("entityId")))
    if use_selection:
        selection = state.get("selection")
        selection = selection if isinstance(selection, Mapping) else {}
        requested_placement_ids.update(
            str(item) for item in selection.get("placementIds", []) if str(item)
        )
    has_scope = bool(
        query or requested_ids or use_selection
    )
    candidates = []
    for placement in placements:
        placement_id = str(placement.get("placementId"))
        if has_scope and not (
            placement_id in requested_placement_ids
            or str(placement.get("assetId") or "") in requested_asset_ids
            or requested_zone_ids.intersection(
                str(item) for item in placement.get("zoneIds", []) if str(item)
            )
        ):
            continue
        semantic_placement = semantic_placements.get(placement_id, {})
        functional_sides = semantic_placement.get("functionalSides")
        functional_sides = (
            functional_sides if isinstance(functional_sides, Mapping) else {}
        )
        access_needs = set(
            semantic_placement.get("genericAccessNeeds") or []
        )
        relevant_without_scope = bool(
            any(alias in functional_sides for alias in aliases)
            or (
                role in {"service", "rear"}
                and "maintenance_access" in access_needs
            )
            or (
                role in {"operator", "front"}
                and "operator_access" in access_needs
            )
            or (
                role in {
                    "loading", "material_input", "material_output",
                }
                and bool({
                    "material_transfer", "load_unload_access",
                    "handling_access",
                }.intersection(access_needs))
            )
        )
        if not has_scope and not relevant_without_scope:
            continue
        candidates.append(placement)

    shell = state.get("facilityShell")
    shell = shell if isinstance(shell, Mapping) else {}
    floor_surfaces = [
        item for item in shell.get("floorSurfaces", [])
        if isinstance(item, Mapping)
    ]
    floor_elevation = min(
        (_finite_optional(item.get("elevation")) or 0.0)
        for item in floor_surfaces
    ) if floor_surfaces else 0.0
    shell_shape = _union_shapes([
        _shape_from_boundary(item.get("boundary"))
        for item in floor_surfaces
    ])
    geometry_index = _spatial_geometry_index(
        placements,
        floor_elevation=floor_elevation,
    )
    geometry_by_id = {
        str(item.get("placementId")): item for item in geometry_index
    }
    all_shapes = [
        shape
        for item in geometry_index
        for shape in item.get("floorPhysical", [])
    ]
    world_shape = _union_shapes(all_shapes)
    if world_shape is None:
        world_shape = shell_shape
    if world_shape is not None:
        minimum_x, minimum_z, maximum_x, maximum_z = world_shape.bounds
        reach = max(
            math.hypot(maximum_x - minimum_x, maximum_z - minimum_z) + 1.0,
            1.0,
        )
    else:
        reach = 1.0
    source_routes = [
        item for item in state.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    ]
    route_shapes = {
        str(item.get("routeId")): _route_corridor_shape(item)
        for item in source_routes
    }

    records = []
    missing = []
    for placement in candidates:
        placement_id = str(placement.get("placementId"))
        semantic_placement = semantic_placements.get(placement_id, {})
        functional_sides = semantic_placement.get("functionalSides")
        functional_sides = (
            functional_sides if isinstance(functional_sides, Mapping) else {}
        )
        matched_role = next(
            (item for item in aliases if item in functional_sides),
            None,
        )
        if matched_role is None:
            missing.append({
                "placementId": placement_id,
                "placementLabel": semantic_placement.get("displayName"),
                "assetId": placement.get("assetId"),
                "requestedInterfaceRole": role,
                "reason": "functional_side_not_authored",
                "evidenceStatus": "unknown",
            })
            continue
        side_record = functional_sides.get(matched_role)
        side_record = (
            side_record if isinstance(side_record, Mapping)
            else {"side": side_record}
        )
        local_side = str(side_record.get("side") or "").casefold()
        local_direction = _interface_direction(side_record, local_side)
        geometry = geometry_by_id.get(placement_id, {})
        subject_shape = _union_shapes(geometry.get("floorPhysical", []))
        if local_direction is None or subject_shape is None:
            missing.append({
                "placementId": placement_id,
                "placementLabel": semantic_placement.get("displayName"),
                "assetId": placement.get("assetId"),
                "requestedInterfaceRole": role,
                "reason": (
                    "functional_side_direction_unsupported"
                    if local_direction is None else "floor_geometry_unavailable"
                ),
                "evidenceStatus": "unknown",
            })
            continue
        transform = placement.get("transform")
        transform = transform if isinstance(transform, Mapping) else {}
        rotation = _finite_optional(transform.get("rotationDegrees")) or 0.0
        world_direction = _rotate_floor_vector(local_direction, rotation)
        world_side = _cardinal_side_for_direction(world_direction) or None
        world_record = {
            "facing": {"x": world_direction[0], "z": world_direction[1]}
        }
        anchor = _interface_anchor(
            subject_shape,
            world_record,
            world_side or "",
        )
        if anchor is None:
            continue
        probe, side_line = _access_probe_shape(
            subject_shape,
            anchor,
            world_direction,
            reach,
        )
        nearest_obstacle = None
        for other in geometry_index:
            other_id = str(other.get("placementId") or "")
            if other_id == placement_id:
                continue
            other_shape = _union_shapes(other.get("floorPhysical", []))
            if other_shape is None or not probe.intersects(other_shape):
                continue
            distance = float(side_line.distance(other_shape))
            candidate = {
                "placementId": other_id,
                "placementLabel": semantic_placements.get(other_id, {}).get(
                    "displayName"
                ),
                "distanceMeters": distance,
            }
            if nearest_obstacle is None or (
                distance,
                other_id,
            ) < (
                nearest_obstacle["distanceMeters"],
                nearest_obstacle["placementId"],
            ):
                nearest_obstacle = candidate
        boundary_distance = None
        if shell_shape is not None:
            boundary_crossing = probe.intersection(shell_shape.boundary)
            if not boundary_crossing.is_empty:
                boundary_distance = float(side_line.distance(boundary_crossing))
        limiting = []
        if nearest_obstacle is not None:
            limiting.append((
                nearest_obstacle["distanceMeters"],
                "physical_obstacle",
            ))
        if boundary_distance is not None:
            limiting.append((boundary_distance, "facility_boundary"))
        actual_clearance = min(limiting)[0] if limiting else None
        matching_kinds = _matching_route_kinds(matched_role)
        matching_routes = [
            item for item in source_routes
            if str(item.get("routeKind") or "") in matching_kinds
        ]
        connected_route_ids = []
        for item in matching_routes:
            route_id = str(item.get("routeId"))
            route_shape = route_shapes.get(route_id)
            if route_shape is None or not probe.intersects(route_shape):
                continue
            route_distance = float(side_line.distance(route_shape))
            if (
                actual_clearance is None
                or route_distance <= actual_clearance + GEOMETRY_EPSILON
            ):
                connected_route_ids.append(route_id)
        connected_route_ids.sort()
        route_distances = [
            float(anchor.distance(route_shapes[str(item.get("routeId"))]))
            for item in matching_routes
            if route_shapes.get(str(item.get("routeId"))) is not None
        ]
        records.append({
            "placementId": placement_id,
            "placementLabel": semantic_placement.get("displayName"),
            "assetId": placement.get("assetId"),
            "requestedInterfaceRole": role,
            "matchedAuthoredRole": matched_role,
            "localSide": local_side or None,
            "worldSide": world_side,
            "worldFacing": {
                "x": _round(world_direction[0]),
                "z": _round(world_direction[1]),
            },
            "anchor": {"x": _round(anchor.x), "z": _round(anchor.y)},
            "actualOutwardClearanceMeters": (
                _round(actual_clearance)
                if actual_clearance is not None else None
            ),
            "actualOutwardClearanceFeet": (
                _round(actual_clearance * 3.280839895013123)
                if actual_clearance is not None else None
            ),
            "limitingGeometryKind": (
                min(limiting)[1] if limiting else None
            ),
            "nearestPhysicalObstacle": (
                {
                    **nearest_obstacle,
                    "distanceMeters": _round(
                        nearest_obstacle["distanceMeters"]
                    ),
                }
                if nearest_obstacle is not None else None
            ),
            "facilityBoundaryDistanceMeters": (
                _round(boundary_distance)
                if boundary_distance is not None else None
            ),
            "connectedMatchingRouteIds": connected_route_ids,
            "nearestMatchingRouteDistanceMeters": (
                _round(min(route_distances)) if route_distances else None
            ),
            "geometricAccessStatus": (
                "blocked_by_static_footprint"
                if actual_clearance is not None
                and actual_clearance <= GEOMETRY_EPSILON
                else "outward_clearance_measured"
                if actual_clearance is not None
                else "outward_limit_unknown"
            ),
            "adequacyStatus": "unknown_without_applicable_policy",
            "evidenceStatus": "derived",
        })
    records.sort(key=lambda item: (
        item["actualOutwardClearanceMeters"] is None,
        item["actualOutwardClearanceMeters"]
        if item["actualOutwardClearanceMeters"] is not None else math.inf,
        item["placementId"],
    ))
    missing.sort(key=lambda item: item["placementId"])
    return {
        "analysis": "asset_access",
        "requestedInterfaceRole": role,
        "query": query,
        "scopeIds": sorted(requested_ids),
        "resolution": resolution,
        "records": records[:maximum],
        "returnedCount": min(len(records), maximum),
        "measurablePlacementCount": len(records),
        "missingFunctionalSideCount": len(missing),
        "missingFunctionalSidePlacements": missing[:maximum],
        "evidenceStatus": "derived" if records else "unknown",
        "mutationPerformed": False,
        "qualification": (
            "Outward clearance and route proximity are measured only for "
            "authored functional sides. Missing sides remain unknown, and "
            "measured space does not establish access or policy adequacy."
        ),
    }


def _physical_volume_records(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for placement in state.get("placements", []):
        if not isinstance(placement, Mapping) or not placement.get("placementId"):
            continue
        for source in placement.get("physicalGeometry", []) or []:
            if not isinstance(source, Mapping):
                continue
            shape = _shape_from_boundary(source.get("polygon"))
            minimum_y = _finite_optional(source.get("minimumY"))
            maximum_y = _finite_optional(source.get("maximumY"))
            if (
                shape is None
                or minimum_y is None
                or maximum_y is None
                or maximum_y < minimum_y
            ):
                continue
            result.append({
                "placementId": str(placement.get("placementId")),
                "displayName": placement.get("displayName"),
                "recordId": str(source.get("recordId") or ""),
                "shape": shape,
                "minimumY": minimum_y,
                "maximumY": maximum_y,
                "authoritative": source.get("authoritative") is True,
            })
    return result


def _axis_aligned_passage_shape(
    left: BaseGeometry,
    right: BaseGeometry,
) -> tuple[BaseGeometry | None, str | None]:
    """Return the common between-obstacle strip for rack-like geometry."""

    left_min_x, left_min_z, left_max_x, left_max_z = left.bounds
    right_min_x, right_min_z, right_max_x, right_max_z = right.bounds
    overlap_min_z = max(left_min_z, right_min_z)
    overlap_max_z = min(left_max_z, right_max_z)
    overlap_min_x = max(left_min_x, right_min_x)
    overlap_max_x = min(left_max_x, right_max_x)
    if (
        left_max_x <= right_min_x
        and overlap_max_z - overlap_min_z > GEOMETRY_EPSILON
    ):
        return Polygon((
            (left_max_x, overlap_min_z),
            (right_min_x, overlap_min_z),
            (right_min_x, overlap_max_z),
            (left_max_x, overlap_max_z),
        )), "z"
    if (
        right_max_x <= left_min_x
        and overlap_max_z - overlap_min_z > GEOMETRY_EPSILON
    ):
        return Polygon((
            (right_max_x, overlap_min_z),
            (left_min_x, overlap_min_z),
            (left_min_x, overlap_max_z),
            (right_max_x, overlap_max_z),
        )), "z"
    if (
        left_max_z <= right_min_z
        and overlap_max_x - overlap_min_x > GEOMETRY_EPSILON
    ):
        return Polygon((
            (overlap_min_x, left_max_z),
            (overlap_max_x, left_max_z),
            (overlap_max_x, right_min_z),
            (overlap_min_x, right_min_z),
        )), "x"
    if (
        right_max_z <= left_min_z
        and overlap_max_x - overlap_min_x > GEOMETRY_EPSILON
    ):
        return Polygon((
            (overlap_min_x, right_max_z),
            (overlap_max_x, right_max_z),
            (overlap_max_x, left_min_z),
            (overlap_min_x, left_min_z),
        )), "x"
    return None, None


def analyze_facility_drone_clearance(
    state: Mapping[str, Any],
    *,
    query: str = "",
    scope_ids: Sequence[str] = (),
    use_selection: bool = False,
    altitude_meters: float | None = None,
    maximum_results: int = 20,
) -> dict[str, Any]:
    """Measure static 3D gaps using the mounted Drone spherical collider."""

    maximum = max(1, min(int(maximum_results), 50))
    editor = state.get("editor")
    editor = editor if isinstance(editor, Mapping) else {}
    navigation = editor.get("navigationCapabilities")
    navigation = navigation if isinstance(navigation, Mapping) else {}
    drone = navigation.get("drone")
    drone = drone if isinstance(drone, Mapping) else {}
    radius = _finite_optional(drone.get("colliderRadiusMeters"))
    if radius is not None and radius <= 0:
        radius = None
    altitude = _finite_optional(altitude_meters)
    if altitude is None:
        altitude = _finite_optional(drone.get("altitudeMeters"))
    shell = state.get("facilityShell")
    shell = shell if isinstance(shell, Mapping) else {}
    floor_elevations = [
        value
        for item in shell.get("floorSurfaces", []) or []
        if isinstance(item, Mapping)
        for value in [_finite_optional(item.get("elevation"))]
        if value is not None
    ]
    floor_elevation = min(floor_elevations) if floor_elevations else 0.0
    analysis_center_y = (
        floor_elevation + altitude if altitude is not None else None
    )
    placement_by_id = {
        str(item.get("placementId")): item
        for item in state.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    selected_ids = {str(item) for item in scope_ids if str(item)}
    zone_scope_ids = selected_ids - set(placement_by_id)
    if zone_scope_ids:
        selected_ids.update(
            placement_id
            for placement_id, placement in placement_by_id.items()
            if zone_scope_ids.intersection(
                str(item) for item in placement.get("zoneIds", []) if str(item)
            )
        )
    if use_selection:
        selection = state.get("selection")
        selection = selection if isinstance(selection, Mapping) else {}
        selected_ids.update(
            str(item)
            for item in selection.get("placementIds", [])
            if str(item)
        )
    resolution = None
    if query:
        resolution = resolve_facility_entities(
            state,
            query=query,
            entity_kinds=("placement",),
            maximum_results=50,
        )
        selected_ids.update(
            str(item.get("entityId"))
            for item in resolution.get("candidates", [])
            if isinstance(item, Mapping) and item.get("entityId")
        )
    selected_ids &= set(placement_by_id)
    volumes = _physical_volume_records(state)
    volumes_by_placement: dict[str, list[dict[str, Any]]] = {}
    for volume in volumes:
        volumes_by_placement.setdefault(volume["placementId"], []).append(
            volume
        )
    if len(selected_ids) == 1:
        pair_pool = set(placement_by_id)
    else:
        pair_pool = set(selected_ids)
    pairs = []
    ordered_ids = sorted(pair_pool)
    for left_index, left_id in enumerate(ordered_ids):
        if left_id not in selected_ids and len(selected_ids) == 1:
            continue
        right_candidates = ordered_ids[left_index + 1:]
        if len(selected_ids) == 1:
            right_candidates = [
                item for item in ordered_ids if item != left_id
            ]
        for right_id in right_candidates:
            if left_id == right_id:
                continue
            if len(selected_ids) >= 2 and right_id not in selected_ids:
                continue
            candidates = []
            for left in volumes_by_placement.get(left_id, []):
                for right in volumes_by_placement.get(right_id, []):
                    horizontal = float(left["shape"].distance(right["shape"]))
                    vertical = max(
                        0.0,
                        left["minimumY"] - right["maximumY"],
                        right["minimumY"] - left["maximumY"],
                    )
                    candidates.append((
                        math.hypot(horizontal, vertical),
                        horizontal,
                        vertical,
                        left,
                        right,
                    ))
            if not candidates:
                continue
            surface, horizontal, vertical, left, right = min(
                candidates, key=lambda item: (item[0], item[1], item[2])
            )
            try:
                left_point, right_point = nearest_points(
                    left["shape"], right["shape"]
                )
                nearest_midpoint = Point(
                    (left_point.x + right_point.x) / 2.0,
                    (left_point.y + right_point.y) / 2.0,
                )
            except (TypeError, ValueError, GEOSException):
                nearest_midpoint = None
            passage_shape, passage_axis = _axis_aligned_passage_shape(
                left["shape"], right["shape"]
            )
            passage_point = (
                passage_shape.centroid
                if passage_shape is not None else nearest_midpoint
            )
            constrains_at_altitude = None
            if analysis_center_y is not None and radius is not None:
                lower = analysis_center_y - radius
                upper = analysis_center_y + radius
                constrains_at_altitude = bool(
                    left["maximumY"] >= lower
                    and left["minimumY"] <= upper
                    and right["maximumY"] >= lower
                    and right["minimumY"] <= upper
                )
            overhead = []
            transverse_blocked = False
            if passage_point is not None and analysis_center_y is not None:
                horizontal_probe = (
                    passage_shape
                    if passage_shape is not None
                    else passage_point.buffer(radius or 0.0)
                )
                eroded_passage = (
                    passage_shape.buffer(
                        -(radius or 0.0),
                        join_style="mitre",
                    )
                    if passage_shape is not None else None
                )
                for volume in volumes:
                    if volume["placementId"] in {left_id, right_id}:
                        continue
                    if not horizontal_probe.intersects(volume["shape"]):
                        continue
                    if volume["minimumY"] >= analysis_center_y:
                        surface_margin = volume["minimumY"] - analysis_center_y
                    elif volume["maximumY"] <= analysis_center_y:
                        surface_margin = analysis_center_y - volume["maximumY"]
                    else:
                        surface_margin = 0.0
                    if radius is not None:
                        surface_margin -= radius
                    if surface_margin < -GEOMETRY_EPSILON:
                        buffered_obstacle = volume["shape"].buffer(
                            radius or 0.0,
                            join_style="mitre",
                        )
                        if (
                            eroded_passage is not None
                            and not eroded_passage.is_empty
                            and passage_axis in {"x", "z"}
                        ):
                            free_bounds = eroded_passage.bounds
                            obstacle_bounds = buffered_obstacle.bounds
                            spans_transverse = (
                                obstacle_bounds[1]
                                <= free_bounds[1] + GEOMETRY_EPSILON
                                and obstacle_bounds[3]
                                >= free_bounds[3] - GEOMETRY_EPSILON
                                if passage_axis == "x"
                                else obstacle_bounds[0]
                                <= free_bounds[0] + GEOMETRY_EPSILON
                                and obstacle_bounds[2]
                                >= free_bounds[2] - GEOMETRY_EPSILON
                            )
                            transverse_blocked = bool(
                                transverse_blocked or spans_transverse
                            )
                        overhead.append({
                            "placementId": volume["placementId"],
                            "recordId": volume["recordId"],
                            "undersideElevationMeters": _round(
                                volume["minimumY"]
                            ),
                            "verticalSurfaceClearanceMeters": _round(
                                surface_margin
                            ),
                        })
            overhead.sort(key=lambda item: (
                item["verticalSurfaceClearanceMeters"],
                item["placementId"],
            ))
            diameter = radius * 2.0 if radius is not None else None
            horizontal_margin = (
                horizontal - diameter if diameter is not None else None
            )
            if radius is None:
                status = "collider_radius_unknown"
            elif constrains_at_altitude is False:
                status = "not_jointly_constraining_at_altitude"
            elif horizontal_margin is not None and horizontal_margin < 0:
                status = "blocked_by_horizontal_gap"
            elif transverse_blocked:
                status = "blocked_by_overhead_geometry"
            elif overhead and overhead[0]["verticalSurfaceClearanceMeters"] < 0:
                status = "static_cross_section_constrained"
            elif constrains_at_altitude is True:
                status = "static_cross_section_passable"
            else:
                status = "potential_horizontal_passage_altitude_required"
            pairs.append({
                "placementIds": [left_id, right_id],
                "placementLabels": [
                    placement_by_id[left_id].get("displayName"),
                    placement_by_id[right_id].get("displayName"),
                ],
                "minimumActualSurfaceClearanceMeters": _round(surface),
                "horizontalGapMeters": _round(horizontal),
                "verticalSeparationMeters": _round(vertical),
                "droneColliderDiameterMeters": (
                    _round(diameter) if diameter is not None else None
                ),
                "horizontalColliderMarginMeters": (
                    _round(horizontal_margin)
                    if horizontal_margin is not None else None
                ),
                "analysisAltitudeMeters": (
                    _round(altitude) if altitude is not None else None
                ),
                "analysisWorldCenterYMeters": (
                    _round(analysis_center_y)
                    if analysis_center_y is not None else None
                ),
                "constrainsAtAnalysisAltitude": constrains_at_altitude,
                "passagePoint": (
                    {
                        "x": _round(passage_point.x),
                        "z": _round(passage_point.y),
                    }
                    if passage_point is not None else None
                ),
                "passageStripAreaSquareMeters": (
                    _round(_shape_area(passage_shape))
                    if passage_shape is not None else None
                ),
                "passageTravelAxis": passage_axis,
                "overheadConstraints": overhead[:5],
                "passageStatus": status,
                "geometryEvidenceAuthoritative": bool(
                    left["authoritative"] and right["authoritative"]
                ),
                "evidenceStatus": "derived",
            })
            if len(selected_ids) == 1:
                continue
    pairs.sort(key=lambda item: (
        item["minimumActualSurfaceClearanceMeters"],
        item["placementIds"],
    ))
    missing_geometry = sorted(
        selected_ids - set(volumes_by_placement)
    )
    return {
        "analysis": "drone_clearance",
        "query": query,
        "scopeIds": sorted({str(item) for item in scope_ids if str(item)}),
        "resolution": resolution,
        "resolvedPlacementIds": sorted(selected_ids),
        "droneCapability": {
            "supported": drone.get("supported") is True,
            "active": drone.get("active") is True,
            "assistedFlight": drone.get("assistedFlight") is True,
            "colliderRadiusMeters": _round(radius) if radius is not None else None,
            "colliderModel": "sphere_against_extruded_physical_prisms",
            "evidenceStatus": "browser_ephemeral",
        },
        "analysisAltitudeMeters": (
            _round(altitude) if altitude is not None else None
        ),
        "floorElevationMeters": _round(floor_elevation),
        "analysisWorldCenterYMeters": (
            _round(analysis_center_y)
            if analysis_center_y is not None else None
        ),
        "floorColliderMarginMeters": (
            _round(altitude - radius)
            if altitude is not None and radius is not None else None
        ),
        "records": pairs[:maximum],
        "returnedCount": min(len(pairs), maximum),
        "totalCount": len(pairs),
        "missingPhysicalGeometryPlacementIds": missing_geometry,
        "evidenceStatus": "derived" if pairs else "unknown",
        "mutationPerformed": False,
        "qualification": (
            "This is a static cross-section and overhead check using the "
            "mounted Drone spherical collider against authored 3D physical "
            "prisms. It does not prove a collision-free swept route, assisted-"
            "flight performance, or safety compliance."
        ),
    }


def analyze_facility_render_consistency(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile live 2D/3D adapter audits with authoritative placement count."""

    editor = state.get("editor")
    editor = editor if isinstance(editor, Mapping) else {}
    live = editor.get("renderConsistency")
    live = live if isinstance(live, Mapping) else {}
    expected_count = sum(
        isinstance(item, Mapping) and bool(item.get("placementId"))
        for item in state.get("placements", [])
    )
    records = []
    for adapter_key, label in (("topPlan", "2D plan"), ("three", "3D")):
        audit = live.get(adapter_key)
        audit = audit if isinstance(audit, Mapping) else {}
        status = str(audit.get("status") or "unavailable")
        reported_count = audit.get("expectedPlacementCount")
        count_matches = (
            isinstance(reported_count, (int, float))
            and int(reported_count) == expected_count
        )
        if status == "match" and not count_matches:
            status = "mismatch"
        records.append({
            "adapter": adapter_key,
            "label": label,
            "status": status,
            "authoritativeExpectedPlacementCount": expected_count,
            "rendererExpectedPlacementCount": reported_count,
            "expectedCountMatchesAuthority": count_matches,
            "auditedPlacementCount": audit.get("auditedPlacementCount"),
            "transformMismatchIds": deepcopy(
                audit.get("transformMismatchIds") or []
            ),
            "missingPlacementIds": deepcopy(
                audit.get("missingPlacementIds") or []
            ),
            "unavailablePlacementIds": deepcopy(
                audit.get("unavailablePlacementIds") or []
            ),
            "visibilityOrPendingPlacementIds": deepcopy(
                audit.get("visibilityOrPendingPlacementIds") or []
            ),
            "evidenceStatus": "browser_ephemeral",
        })
    statuses = {str(item["status"]) for item in records}
    if "mismatch" in statuses:
        overall = "mismatch"
    elif statuses == {"match"}:
        overall = "match"
    elif "incomplete" in statuses:
        overall = "incomplete"
    else:
        overall = "unavailable"
    return {
        "analysis": "render_consistency",
        "overallStatus": overall,
        "records": records,
        "evidenceStatus": "browser_ephemeral",
        "qualification": (
            "This checks actual mounted adapter diagnostics against the "
            "authoritative placement count. It does not assume consistency "
            "merely because both renderers consume shared state."
        ),
    }


def _complete_facility_semantic_map(
    *,
    state: Mapping[str, Any],
    departments: list[dict[str, Any]],
    department_polygons: Mapping[str, Sequence[tuple[float, float]]],
    source_markings: Sequence[Mapping[str, Any]],
    placement_zone_ids: Mapping[str, Sequence[str]],
    zone_shapes: Mapping[str, BaseGeometry | None],
    shell_union: BaseGeometry | None,
    geometry_index: Sequence[Mapping[str, Any]],
    source_routes: Sequence[Mapping[str, Any]],
    cell_envelopes: Sequence[tuple[str, BaseGeometry]],
    shell: Mapping[str, Any],
    policy: Mapping[str, Any],
    identity: Mapping[str, Any],
    facility_bounds: tuple[float, float, float, float] | None,
    semantic_zones: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    route_network_summary: Mapping[str, Any],
    route_crossings: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    placements: Sequence[Mapping[str, Any]],
    placement_semantics: list[dict[str, Any]],
    placement_role_totals: Counter[str],
    zones: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Finish the semantic projection after shared geometry preparation."""

    for department in departments:
        distances = []
        left = department_polygons.get(department["zoneId"])
        if left is None:
            department["nearestDepartments"] = []
            continue
        for other in departments:
            if other["zoneId"] == department["zoneId"]:
                continue
            right = department_polygons.get(other["zoneId"])
            if right is None:
                continue
            distance = 0.0 if polygons_intersect(left, right) else min(
                polygon_boundary_distance(left, right),
                polygon_boundary_distance(right, left),
            )
            distances.append({
                "zoneId": other["zoneId"],
                "label": other["label"],
                "boundaryDistanceMeters": _round(distance),
                "relationship": "touching" if distance <= GEOMETRY_EPSILON else "separated",
                "evidenceStatus": "derived",
            })
        department["nearestDepartments"] = sorted(
            distances,
            key=lambda item: (item["boundaryDistanceMeters"], item["zoneId"]),
        )[:3]

    markings = [
        _marking_semantics(item)
        for item in source_markings
    ]
    process_relationships = _process_relationship_semantics(
        [
            item for item in state.get("processBindings", [])
            if isinstance(item, Mapping) and item.get("processBindingId")
        ],
        [
            item for item in state.get("processMaps", [])
            if isinstance(item, Mapping)
        ],
        placement_zone_ids,
    )
    identity = state.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    editor = state.get("editor")
    editor = editor if isinstance(editor, Mapping) else {}
    runtime_navigation = editor.get("navigationCapabilities")
    runtime_navigation = (
        deepcopy(dict(runtime_navigation))
        if isinstance(runtime_navigation, Mapping)
        else {}
    )
    semantic_zone_by_id = {
        str(item.get("zoneId")): item
        for item in semantic_zones
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    placement_ids_by_zone: dict[str, set[str]] = {}
    for placement_id, zone_ids in placement_zone_ids.items():
        for zone_id in zone_ids:
            placement_ids_by_zone.setdefault(str(zone_id), set()).add(
                str(placement_id)
            )
    raw_zone_by_id = {
        str(item.get("zoneId")): item
        for item in zones
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    cell_zone_ids = {
        str(item.get("zoneId"))
        for item in semantic_zones
        if isinstance(item, Mapping)
        and item.get("zoneId")
        and _is_authored_cell_zone(
            raw_zone_by_id.get(str(item.get("zoneId")), {})
        )
    }
    for department in departments:
        department_id = str(department.get("zoneId") or "")
        member_ids = set(placement_ids_by_zone.get(department_id, set()))
        descendant_cells = sorted(
            zone_id
            for zone_id in cell_zone_ids
            if semantic_zone_by_id.get(zone_id, {}).get("parentZoneId")
            == department_id
        )
        grouped_ids = {
            placement_id
            for zone_id in descendant_cells
            for placement_id in placement_ids_by_zone.get(zone_id, set())
        }
        grouped_member_ids = member_ids.intersection(grouped_ids)
        ungrouped_ids = member_ids - grouped_member_ids
        department["componentPlacementCount"] = len(member_ids)
        department["cellModuleCount"] = len(descendant_cells)
        department["cellModuleZoneIds"] = descendant_cells
        department["cellComponentPlacementCount"] = len(
            grouped_member_ids
        )
        department["ungroupedOperationalPlacementCount"] = len(
            ungrouped_ids
        )
        department["operationalUnitCount"] = (
            len(descendant_cells) + len(ungrouped_ids)
        )
        department["operationalUnitDefinition"] = (
            "one authored child workcell plus each department placement not "
            "contained in an authored child workcell; component placement "
            "count remains a separate inventory metric"
        )
    department_shapes = [
        zone_shapes.get(item["zoneId"])
        for item in departments
    ]
    department_union = _union_shapes(department_shapes)
    department_area_sum = sum(
        float(item.get("areaSquareMeters") or 0.0)
        for item in departments
    )
    department_union_area = _shape_area(department_union)
    for department in departments:
        department_area = float(department.get("areaSquareMeters") or 0.0)
        department["departmentAreaShare"] = {
            "percentOfDepartmentAreaSum": _round(
                department_area / department_area_sum * 100.0
            ) if department_area_sum > GEOMETRY_EPSILON else None,
            "denominatorSquareMeters": _round(department_area_sum),
            "denominatorDefinition": (
                "sum of the six parent-department polygon areas; shared "
                "circulation outside those polygons is excluded"
            ),
            "evidenceStatus": "derived",
        }

    shell_area = _shape_area(shell_union)
    facility_scope_shape = (
        shell_union if shell_union is not None else department_union
    )
    if facility_scope_shape is not None:
        facility_scope_points = tuple(
            (float(x_value), float(z_value))
            for x_value, z_value in facility_scope_shape.convex_hull.exterior.coords[:-1]
        )
        facility_spatial_metrics = _scope_spatial_metrics(
            scope_id="facility",
            boundary=facility_scope_points,
            scope_shape=facility_scope_shape,
            geometry_index=geometry_index,
            routes=source_routes,
            markings=source_markings,
            shell=shell,
            policy=policy,
            cell_envelopes=cell_envelopes,
            include_all_placements=True,
        )
    else:
        facility_spatial_metrics = {
            "geometryEngineAvailable": _GEOMETRY_ENGINE_AVAILABLE,
            "evidenceStatus": "unknown",
            "blockers": [_blocker("facility_floor_polygon_unavailable", [
                str(identity.get("layoutId") or "facility")
            ])],
        }
    marking_roles = Counter(item["semanticRole"] for item in markings)
    route_roles = Counter(item["semanticRole"] for item in routes)
    bounds_record = (
        {
            "minimumX": _round(facility_bounds[0]),
            "minimumZ": _round(facility_bounds[1]),
            "maximumX": _round(facility_bounds[2]),
            "maximumZ": _round(facility_bounds[3]),
            "widthMeters": _round(facility_bounds[2] - facility_bounds[0]),
            "depthMeters": _round(facility_bounds[3] - facility_bounds[1]),
            "areaSquareMeters": _round(shell_area)
            if shell_union is not None else None,
        }
        if facility_bounds is not None else None
    )
    return {
        "semanticContractVersion": FACILITY_SEMANTIC_MODEL_VERSION,
        "source": {
            "layoutId": identity.get("layoutId"),
            "layoutRevision": identity.get("revision"),
            "origin": "revision_bound_facility_state",
        },
        "evidenceVocabulary": list(EVIDENCE_STATUSES),
        "facilitySummary": {
            "displayName": identity.get("displayName"),
            "bounds": bounds_record,
            "boundsEvidenceStatus": "derived" if bounds_record else "unknown",
            "boundsMethod": (
                "bounds_of_shell_floor_surface_union"
                if shell_union is not None
                else "union_bounds_of_authored_zones"
            ),
            "boundsQualification": (
                "Shell floor-surface bounds are preferred. Zone bounds are a "
                "descriptive fallback and are not an authoritative shell."
            ),
            "facilityFloorArea": {
                "areaSquareMeters": _round(shell_area) if shell_union is not None else None,
                "areaSquareFeet": _round(
                    shell_area * SQUARE_METERS_TO_SQUARE_FEET
                ) if shell_union is not None else None,
                "evidenceStatus": "derived" if shell_union is not None else "unknown",
                "method": "union_of_authoritative_shell_floor_surfaces",
                "shellStatus": shell.get("status"),
                "geometryAuthoritative": (
                    shell.get("floorGeometryAuthoritative") is True
                ),
                "qualification": (
                    "Area is geometrically derived from the loaded shell. Shell "
                    "review status and unresolved items remain separate evidence."
                ),
            },
            "departmentAreaReconciliation": {
                "departmentAreaSumSquareMeters": _round(department_area_sum),
                "departmentUnionAreaSquareMeters": _round(department_union_area),
                "overlapSquareMeters": _round(max(
                    0.0, department_area_sum - department_union_area
                )),
                "uncoveredShellAreaSquareMeters": _round(max(
                    0.0, shell_area - department_union_area
                )) if shell_union is not None else None,
                "departmentUnionExceedsShellSquareMeters": _round(max(
                    0.0, department_union_area - shell_area
                )) if shell_union is not None else None,
                "evidenceStatus": "derived" if department_union is not None else "unknown",
            },
            "spatialMetrics": facility_spatial_metrics,
            "departmentCount": len(departments),
            "zoneCount": len(semantic_zones),
            "placementCount": len([
                item for item in state.get("placements", []) if isinstance(item, Mapping)
            ]),
            "componentPlacementCount": len([
                item for item in state.get("placements", [])
                if isinstance(item, Mapping)
            ]),
            "cellModuleCount": len(cell_zone_ids),
            "operationalUnitCount": sum(
                int(item.get("operationalUnitCount") or 0)
                for item in departments
            ),
            "routeCount": len(routes),
            "floorMarkingCount": len(markings),
            "assetDefinitionCount": len(assets),
        },
        "departments": departments,
        "departmentMetricSummaries": [
            _department_metric_summary(item) for item in departments
        ],
        "zones": semantic_zones,
        "assets": assets,
        "placements": placement_semantics,
        "assetRoleSummary": dict(sorted(placement_role_totals.items())),
        "routes": routes,
        "routeRoleSummary": dict(sorted(route_roles.items())),
        "routeNetworkSummary": route_network_summary,
        "routeCrossings": route_crossings,
        "floorMarkings": markings,
        "processRelationships": process_relationships,
        "processRelationshipSummary": _process_relationship_summary(
            process_relationships
        ),
        "processBindings": deepcopy(process_relationships["bindings"]),
        "layoutPatternGroups": _layout_pattern_groups(
            placements,
            zones,
            source_markings,
        ),
        "floorMarkingRoleSummary": dict(sorted(marking_roles.items())),
        "cellLayoutStrategies": deepcopy(list(CELL_LAYOUT_STRATEGIES)),
        "commands": deepcopy(list(FACILITY_COMMAND_SEMANTICS)),
        "agentTools": deepcopy(list(AGENT_TOOL_SEMANTICS)),
        "derivedMetricDefinitions": deepcopy(list(DERIVED_METRIC_DEFINITIONS)),
        "analysisCapabilities": {
            "runtimeNavigation": runtime_navigation,
            "deterministicallyDerivable": [
                "facility floor area from shell floor-surface union",
                "zone area",
                "department area when a department boundary is authored",
                "department area sum, union, overlap, and shell coverage",
                "placement and asset-role counts",
                "gross assigned asset footprint coverage",
                "net physical floor-contact footprint without overlap double-counting",
                "geometric free area and connected free-space regions",
                "known planning free area when declared geometry is complete",
                "operationally usable free area only when all evidence gates pass",
                "zone hierarchy and cardinal location",
                "route centerline length and geometric zone connections",
                "static route-corridor connectivity and floor obstruction intersections",
                "authored and minimum known usable route width profiles",
                "geometric route crossings independently of movement connectivity",
                "route paths between authored zone geometry along matching centerlines",
                "actual edge-to-edge physical separation without policy adequacy",
                "physical-footprint intrusions into authored protected areas",
                "cell and pattern creation provenance plus current geometry drift",
                "read-only line, L-shaped, and U-shaped cell alternatives",
                "bounded complete-cell module fit lower bounds",
                "authored cell-interface access and static obstruction geometry",
                "authored asset-side approach clearance and route proximity",
                "static Drone collider passage and overhead clearance margins",
                "authored-sequence travel or an explicitly labelled geometric proxy",
                "zone-to-zone boundary distance",
            ],
            "requiresAuthoritativeEvidenceOrValidation": [
                "clearance compliance",
                "aisle capacity and code compliance",
                "maximum multi-instance spatial fit capacity",
                "throughput, utilization, or OEE",
                "floor loading and structural adequacy",
                "safe egress and regulatory compliance",
                "machine-specific sides that are not authored in the asset definition",
            ],
            "metricFidelityRules": [
                "Never replace requested area, distance, density, or capacity with placement count.",
                "State the denominator for every percentage.",
                "Separate geometric, planning, operational, and production capacity.",
                "Use null plus blocker codes rather than fabricating a gated metric.",
            ],
        },
    }


def facility_semantic_registry() -> dict[str, Any]:
    """Return stable semantic registries without requiring a layout."""

    return {
        "semanticContractVersion": FACILITY_SEMANTIC_MODEL_VERSION,
        "evidenceVocabulary": list(EVIDENCE_STATUSES),
        "cellLayoutStrategies": deepcopy(list(CELL_LAYOUT_STRATEGIES)),
        "commands": deepcopy(list(FACILITY_COMMAND_SEMANTICS)),
        "agentTools": deepcopy(list(AGENT_TOOL_SEMANTICS)),
        "derivedMetricDefinitions": deepcopy(list(DERIVED_METRIC_DEFINITIONS)),
    }


__all__ = [
    "AGENT_TOOL_SEMANTICS",
    "CELL_FEASIBILITY_STRATEGIES",
    "CELL_LAYOUT_STRATEGIES",
    "DERIVED_METRIC_DEFINITIONS",
    "EVIDENCE_STATUSES",
    "FACILITY_COMMAND_SEMANTICS",
    "FACILITY_SEMANTIC_MODEL_VERSION",
    "analyze_facility_asset_access",
    "analyze_facility_cell_access",
    "analyze_facility_clearances",
    "analyze_facility_cell_alternatives",
    "analyze_facility_drone_clearance",
    "analyze_facility_free_space",
    "analyze_facility_layout_provenance",
    "analyze_facility_module_fit",
    "analyze_facility_operator_travel",
    "analyze_facility_protected_intrusions",
    "analyze_facility_render_consistency",
    "analyze_facility_route_access",
    "analyze_facility_route_widths",
    "build_facility_semantic_map",
    "classify_facility_asset_semantics",
    "classify_facility_zone_semantics",
    "facility_semantic_registry",
    "resolve_facility_entities",
]
