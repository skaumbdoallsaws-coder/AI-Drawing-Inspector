"""Source-bound deterministic evaluation for Facility Layout intelligence.

This gate proves the semantic, geometry, tool, context, and action-boundary
contracts without making a paid model call. It deliberately does not claim to
measure the quality of arbitrary provider prose; that remains a shadow/pilot
evaluation over the same frozen cases and deterministic oracles.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

import yaml

from ai_inspector.chat_content import (
    CHAT_TABLE_TOOL,
    CHAT_VISUALIZATION_TOOL,
    VISUALIZATION_TYPES,
    requested_visualization_type,
)

from .canonical import layout_revision
from .chat_context import build_facility_analysis_digest
from .chat_intent import (
    classify_facility_layout_request,
    classify_facility_request_kind,
    facility_layout_action_mode,
    facility_layout_tool_authorization,
    is_precise_facility_translation_request,
    requested_facility_metric,
    requested_facility_spatial_analyses,
    resolve_facility_pending_follow_up,
    resolve_facility_layout_turn,
)
from .orchestration import (
    FacilityPendingOperationStore,
    build_facility_orchestration_plan,
    facility_orchestration_trace,
)
from .fit_analysis import analyze_facility_asset_fit
from .feature_flags import FacilityLayoutFeatureFlags
from .generation_coordinator import (
    FacilityGenerationCoordinator,
    g1_facility_generation_tool_spec,
)
from .generation_run_repository import FacilityGenerationRunRepository
from .host import build_private_local_asset_catalog
from .knowledge_foundation import FACILITY_GENERATION_STAGES
from .knowledge_traces import (
    FACILITY_GOLD_TRACE_FIXTURE,
    FACILITY_HELD_OUT_FIXTURE,
    compile_facility_trace_context,
    evaluate_held_out_command_families,
    load_facility_trace_evidence,
)
from .observation import facility_layout_read_tool_specs
from .operations import create_layout_document
from .provider_config import resolve_facility_provider_config
from .semantic_model import (
    analyze_facility_asset_access,
    analyze_facility_cell_access,
    analyze_facility_clearances,
    analyze_facility_drone_clearance,
    analyze_facility_module_fit,
    analyze_facility_render_consistency,
    build_facility_semantic_map,
    facility_semantic_registry,
    resolve_facility_entities,
)
from .semantic_plan import facility_layout_preview_tool_spec
from .semantic_plan import facility_layout_move_tool_spec
from .spatial import canonical_spatial_bytes


EVALUATION_CONTRACT_VERSION = 1
DEFAULT_FIXTURE = Path(
    "tests/fixtures/facility_layout/semantic_intelligence/"
    "golden-facility-a.json"
)
DEFAULT_CASES = Path(
    "tests/fixtures/facility_layout/semantic_intelligence/"
    "evaluation-cases-v1.json"
)
SPATIAL_FIXTURE = Path(
    "tests/fixtures/facility_layout/spatial/golden_scenarios.json"
)
MACHINE_REVISION = "a" * 64


GATE_THRESHOLDS = {
    "deterministic_geometry": 100.0,
    "read_only_safety": 100.0,
    "unit_fidelity": 100.0,
    "semantic_understanding": 90.0,
    "process_and_route": 100.0,
    "provenance": 100.0,
    "bounded_fit": 100.0,
    "tool_contracts": 95.0,
    "intent_continuity": 95.0,
    "context_compilation": 100.0,
    "catalog_coverage": 100.0,
    "rich_presentation": 95.0,
    "knowledge_traces": 100.0,
    "held_out_intent": 95.0,
    "provider_identity": 100.0,
    "g1_generation": 100.0,
}


SOURCE_PATHS = (
    "server.py",
    "ai_inspector/facility_layout/semantic_model.py",
    "ai_inspector/facility_layout/fit_analysis.py",
    "ai_inspector/facility_layout/observation.py",
    "ai_inspector/facility_layout/agent_runtime.py",
    "ai_inspector/facility_layout/chat_context.py",
    "ai_inspector/facility_layout/chat_intent.py",
    "ai_inspector/facility_layout/orchestration.py",
    "ai_inspector/facility_layout/operations.py",
    "ai_inspector/facility_layout/host.py",
    "ai_inspector/facility_layout/semantic_plan.py",
    "ai_inspector/facility_layout/validate.py",
    "ai_inspector/facility_layout/canonical.py",
    "ai_inspector/facility_layout/intelligence_evaluation.py",
    "ai_inspector/facility_layout/g1_planner.py",
    "ai_inspector/facility_layout/generation_coordinator.py",
    "ai_inspector/facility_layout/generation_run_repository.py",
    "ai_inspector/facility_layout/knowledge_foundation.py",
    "ai_inspector/facility_layout/knowledge_traces.py",
    "ai_inspector/facility_layout/tool_knowledge.py",
    "ai_inspector/facility_layout/provider_config.py",
    "ai_inspector/chat_content.py",
    "ai_inspector/agent_skills/analyze-facility-layout/SKILL.md",
    "ai_inspector/agent_skills/analyze-facility-layout/manifest.yaml",
    "ai_inspector/agent_skills/analyze-facility-layout/contract.yaml",
    "ai_inspector/agent_skills/generate-facility-layout/SKILL.md",
    "ai_inspector/agent_skills/generate-facility-layout/manifest.yaml",
    "ai_inspector/agent_skills/generate-facility-layout/contract.yaml",
    "static/facility_layout_session.js",
    "static/facility_layout_app.js",
    "static/facility_layout_transport.js",
    "static/facility_layout_editor.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_workspace.js",
    "static/chat_rich_content.js",
    "static/index.html",
    "requirements.txt",
    "tools/evaluate_sage_facility_layout_intelligence.py",
    "tools/smoke_sage_facility_layout_intelligence.py",
    "tools/smoke_sage_facility_layout_provider_shadow.py",
    "tests/test_facility_layout_intelligence_evaluation.py",
    "tests/test_facility_layout_schema_v1.py",
    "tests/test_facility_layout_semantic_model.py",
    "tests/test_facility_layout_agent_integration.py",
    "tests/test_facility_layout_session.js",
    "tests/test_facility_layout_workspace.js",
    "tests/test_sage_openai_provider.py",
    str(DEFAULT_FIXTURE).replace("\\", "/"),
    str(DEFAULT_CASES).replace("\\", "/"),
    str(FACILITY_GOLD_TRACE_FIXTURE).replace("\\", "/"),
    str(FACILITY_HELD_OUT_FIXTURE).replace("\\", "/"),
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if any(byte > 127 for byte in raw):
        raise ValueError(f"evaluation fixture must be ASCII: {path}")
    value = json.loads(raw.decode("ascii"))
    if not isinstance(value, dict):
        raise ValueError(f"evaluation fixture must be an object: {path}")
    return value


def _git_commit(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    return str(value)


class _Recorder:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def check(
        self,
        check_id: str,
        gate: str,
        description: str,
        *,
        passed: bool,
        observed: Any,
        expected: Any,
        severity: str = "critical",
    ) -> None:
        self.records.append({
            "id": check_id,
            "gate": gate,
            "description": description,
            "severity": severity,
            "passed": bool(passed),
            "observed": _json_safe(observed),
            "expected": _json_safe(expected),
        })

    def equal(
        self,
        check_id: str,
        gate: str,
        description: str,
        observed: Any,
        expected: Any,
        *,
        severity: str = "critical",
    ) -> None:
        self.check(
            check_id,
            gate,
            description,
            passed=observed == expected,
            observed=observed,
            expected=expected,
            severity=severity,
        )

    def close(
        self,
        check_id: str,
        gate: str,
        description: str,
        observed: Any,
        expected: Any,
        *,
        tolerance: float = 1e-6,
        severity: str = "critical",
    ) -> None:
        valid = (
            isinstance(observed, (int, float))
            and not isinstance(observed, bool)
            and abs(float(observed) - float(expected)) <= tolerance
        )
        self.check(
            check_id,
            gate,
            description,
            passed=valid,
            observed=observed,
            expected={"value": expected, "tolerance": tolerance},
            severity=severity,
        )


def _by_id(values: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    return {
        str(value.get(key)): value
        for value in values
        if isinstance(value, Mapping) and value.get(key)
    }


def _collect_schema_property_names(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            result.update(str(key) for key in properties)
        for child in value.values():
            result.update(_collect_schema_property_names(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            result.update(_collect_schema_property_names(child))
    return result


def _ribbon_commands(index_text: str) -> set[str]:
    match = re.search(
        r"const FACILITY_LAYOUT_RIBBON_CONFIG = Object\.freeze\(\["
        r"(.*?)\n\s*\]\);",
        index_text,
        re.DOTALL,
    )
    if match is None:
        return set()
    result: set[str] = set()
    for body in re.findall(r"commands:\s*\[(.*?)\]", match.group(1), re.DOTALL):
        result.update(re.findall(r"['\"]([a-z0-9-]+)['\"]", body))
    return result


def _semantic_fixture_checks(
    recorder: _Recorder,
    fixture: Mapping[str, Any],
    semantic: Mapping[str, Any],
) -> None:
    expected = fixture["expected"]
    summary = semantic["facilitySummary"]
    bounds = summary["bounds"]
    floor_area = summary["facilityFloorArea"]
    reconciliation = summary["departmentAreaReconciliation"]
    metrics = summary["spatialMetrics"]

    recorder.equal(
        "A1",
        "semantic_understanding",
        "The parent hierarchy exposes exactly six departments.",
        summary["departmentCount"],
        expected["departmentCount"],
    )
    recorder.equal(
        "A2",
        "semantic_understanding",
        "The hierarchy retains the authored child workcell.",
        summary["zoneCount"],
        expected["zoneCount"],
    )
    department_labels = [
        item["label"] for item in semantic["departments"]
    ]
    recorder.equal(
        "A3",
        "semantic_understanding",
        "Department-level summaries preserve the six authored names.",
        department_labels,
        [
            "Receiving + Raw Material",
            "Machining Hall",
            "Automation + Robot Cells",
            "Material Handling + Maintenance",
            "Assembly + Kitting",
            "Inspection + Packing + Finished Goods",
        ],
    )
    zones = _by_id(semantic["zones"], "zoneId")
    recorder.equal(
        "A4",
        "semantic_understanding",
        "Assembly Cell A01 resolves beneath the Assembly department.",
        {
            "scopeKind": zones["cell-assembly-a01"]["scopeKind"],
            "parentZoneId": zones["cell-assembly-a01"]["parentZoneId"],
        },
        {
            "scopeKind": "subzone",
            "parentZoneId": "dept-assembly",
        },
    )
    cardinal = {
        item["zoneId"]: item["cardinalLocation"]
        for item in semantic["departments"]
    }
    recorder.equal(
        "A5",
        "semantic_understanding",
        "World coordinates derive the expected six-part mental map.",
        cardinal,
        {
            "dept-receiving": "northwest",
            "dept-machining": "north",
            "dept-automation": "northeast",
            "dept-material-maintenance": "southwest",
            "dept-assembly": "south",
            "dept-inspection-finished": "southeast",
        },
    )
    recorder.equal(
        "A6",
        "semantic_understanding",
        "Facility dimensions come from the authoritative shell bounds.",
        [bounds["widthMeters"], bounds["depthMeters"]],
        [
            expected["facilityWidthMeters"],
            expected["facilityDepthMeters"],
        ],
    )

    recorder.close(
        "B1",
        "deterministic_geometry",
        "Facility area is derived from the shell-surface union.",
        floor_area["areaSquareMeters"],
        expected["facilityAreaSquareMeters"],
    )
    recorder.close(
        "B2",
        "unit_fidelity",
        "Square-meter area converts exactly to square feet.",
        floor_area["areaSquareFeet"],
        expected["facilityAreaSquareFeet"],
    )
    recorder.equal(
        "B3",
        "deterministic_geometry",
        "Each department polygon has the frozen exact area.",
        sorted({item["areaSquareMeters"] for item in semantic["departments"]}),
        [expected["departmentAreaSquareMeters"]],
    )
    recorder.close(
        "B4",
        "deterministic_geometry",
        "Department area sum is exact.",
        reconciliation["departmentAreaSumSquareMeters"],
        expected["departmentAreaSumSquareMeters"],
    )
    recorder.close(
        "B5",
        "deterministic_geometry",
        "Department union removes overlap before reconciliation.",
        reconciliation["departmentUnionAreaSquareMeters"],
        expected["departmentUnionAreaSquareMeters"],
    )
    recorder.close(
        "B6",
        "deterministic_geometry",
        "Shared circulation outside departments remains explicit.",
        reconciliation["uncoveredShellAreaSquareMeters"],
        expected["uncoveredShellAreaSquareMeters"],
    )
    physical = metrics["physicalFloorContact"]
    recorder.equal(
        "B7",
        "deterministic_geometry",
        "Only actual floor-contact placements enter footprint occupancy.",
        physical["placementCount"],
        expected["floorPlacementCount"],
    )
    recorder.close(
        "B8",
        "deterministic_geometry",
        "Net physical footprint is a clipped polygon union.",
        physical["netUnionAreaSquareMeters"],
        expected["netPhysicalFootprintSquareMeters"],
    )
    recorder.close(
        "B9",
        "deterministic_geometry",
        "Geometric free area subtracts physical floor contact only.",
        metrics["geometricFreeArea"]["areaSquareMeters"],
        expected["geometricFreeAreaSquareMeters"],
    )
    recorder.close(
        "B10",
        "deterministic_geometry",
        "Clearance-reserved area is an overlap-safe union.",
        metrics["clearanceReservedArea"][
            "authoritativeUnionAreaSquareMeters"
        ],
        expected["clearanceUnionSquareMeters"],
    )
    recorder.close(
        "B11",
        "deterministic_geometry",
        "Route reservation uses the semantic corridor polygon.",
        metrics["routeReservedArea"][
            "authoritativeCorridorUnionAreaSquareMeters"
        ],
        expected["routeUnionSquareMeters"],
    )
    recorder.close(
        "B12",
        "deterministic_geometry",
        "Floor-marking reservation retains its own metric.",
        metrics["floorMarkingReservation"][
            "communicatedUnionAreaSquareMeters"
        ],
        expected["markingUnionSquareMeters"],
    )
    recorder.close(
        "B13",
        "deterministic_geometry",
        "Operational free area is emitted only after all evidence gates pass.",
        metrics["operationallyUsableFreeArea"]["areaSquareMeters"],
        expected["operationalFreeAreaSquareMeters"],
    )
    breakdown = metrics["reconciledPlanningAreaBreakdown"]
    recorder.equal(
        "B14",
        "deterministic_geometry",
        "The non-overlapping area breakdown reconciles to gross area.",
        {
            "physical": breakdown["physicalFootprintSquareMeters"],
            "clearanceOnly": breakdown["clearanceOnlySquareMeters"],
            "cellEnvelopeOnly": breakdown[
                "cellEnvelopeOnlySquareMeters"
            ],
            "routeOnly": breakdown["routeOnlySquareMeters"],
            "markingOnly": breakdown["markingOnlySquareMeters"],
            "remaining": breakdown["remainingSquareMeters"],
            "sum": breakdown["sumSquareMeters"],
        },
        {
            "physical": expected["netPhysicalFootprintSquareMeters"],
            "clearanceOnly": expected[
                "reconciledClearanceOnlySquareMeters"
            ],
            "cellEnvelopeOnly": expected[
                "reconciledCellEnvelopeOnlySquareMeters"
            ],
            "routeOnly": expected["reconciledRouteOnlySquareMeters"],
            "markingOnly": expected["reconciledMarkingOnlySquareMeters"],
            "remaining": expected["operationalFreeAreaSquareMeters"],
            "sum": expected["facilityAreaSquareMeters"],
        },
    )
    recorder.equal(
        "B15",
        "deterministic_geometry",
        "The free-space result includes connected-region evidence.",
        metrics["operationallyUsableFreeArea"]["contiguousRegions"][
            "regionCount"
        ],
        1,
    )
    department_metrics = _by_id(
        semantic["departmentMetricSummaries"],
        "zoneId",
    )
    recorder.close(
        "B16",
        "deterministic_geometry",
        "Receiving operational free area includes its route reservation.",
        department_metrics["dept-receiving"][
            "operationallyUsableFreeAreaSquareMeters"
        ],
        expected["receivingOperationalFreeAreaSquareMeters"],
    )
    recorder.close(
        "B17",
        "deterministic_geometry",
        "An ordinary department retains the expected operational free area.",
        department_metrics["dept-machining"][
            "operationallyUsableFreeAreaSquareMeters"
        ],
        expected["ordinaryDepartmentOperationalFreeAreaSquareMeters"],
    )
    shares = {
        item["departmentAreaShare"]["percentOfDepartmentAreaSum"]
        for item in semantic["departments"]
    }
    denominators = {
        item["departmentAreaShare"]["denominatorSquareMeters"]
        for item in semantic["departments"]
    }
    recorder.equal(
        "J1",
        "unit_fidelity",
        "Department area percentages declare one exact denominator.",
        {
            "shares": sorted(shares),
            "denominators": sorted(denominators),
        },
        {
            "shares": [expected["departmentAreaSharePercent"]],
            "denominators": [expected["departmentAreaSumSquareMeters"]],
        },
    )


def _route_process_checks(
    recorder: _Recorder,
    fixture: Mapping[str, Any],
    semantic: Mapping[str, Any],
) -> None:
    expected = fixture["expected"]
    route = semantic["routes"][0]
    route_summary = semantic["routeNetworkSummary"]
    recorder.close(
        "F1",
        "process_and_route",
        "Route length is derived from the authored world centerline.",
        route["lengthMeters"],
        expected["routeLengthMeters"],
    )
    recorder.close(
        "F2",
        "process_and_route",
        "Route width remains distinct from rendered line thickness.",
        route["corridorWidthMeters"],
        expected["routeWidthMeters"],
    )
    recorder.equal(
        "F3",
        "process_and_route",
        "Route endpoints resolve to their exact connected departments.",
        [item["zoneIds"] for item in route["endpointConnections"]],
        [
            ["dept-material-maintenance"],
            ["dept-receiving"],
        ],
    )
    recorder.equal(
        "F4",
        "process_and_route",
        "Static route obstruction analysis reports the golden corridor clear.",
        {
            "status": route["geometricObstructionStatus"],
            "obstructionCount": len(route["geometricObstructions"]),
            "unknownCount": route_summary["unknownObstructionRouteCount"],
        },
        {"status": "clear", "obstructionCount": 0, "unknownCount": 0},
    )
    recorder.equal(
        "F5",
        "process_and_route",
        "A valid standalone route is not mislabeled disconnected.",
        {
            "componentCount": route_summary[
                "geometricEndpointComponentCount"
            ],
            "standaloneRouteCount": route_summary["standaloneRouteCount"],
            "terminalCount": route_summary["unresolvedTerminalCount"],
        },
        {"componentCount": 1, "standaloneRouteCount": 1, "terminalCount": 0},
    )

    process = semantic["processRelationshipSummary"]
    recorder.equal(
        "H1",
        "process_and_route",
        "All frozen process bindings remain revision-bound and resolved.",
        {
            "bindings": process["bindingCount"],
            "boundZones": process["boundDepartmentOrZoneCount"],
            "unresolved": process["unresolvedBindingCount"],
        },
        {
            "bindings": expected["processBindingCount"],
            "boundZones": expected["processBoundZoneCount"],
            "unresolved": 0,
        },
    )
    recorder.equal(
        "H2",
        "process_and_route",
        "The authored five-step graph derives four facility relationships.",
        {
            "status": process["flowSequenceStatus"],
            "evidence": process["flowSequenceEvidenceStatus"],
            "edges": process["relationshipEdgeCount"],
        },
        {
            "status": "available",
            "evidence": "derived",
            "edges": expected["processRelationshipEdgeCount"],
        },
    )
    edges = semantic["processRelationships"]["relationshipEdges"]
    chain = sorted(
        (
            item["upstreamProcessBindingId"],
            item["downstreamProcessBindingId"],
        )
        for item in edges
    )
    recorder.equal(
        "H3",
        "process_and_route",
        "Process direction comes from authored graph endpoints, not proximity.",
        chain,
        sorted([
            ("pb-golden-receiving", "pb-golden-machining"),
            ("pb-golden-machining", "pb-golden-automation"),
            ("pb-golden-automation", "pb-golden-assembly"),
            ("pb-golden-assembly", "pb-golden-inspection"),
        ]),
    )
    recorder.equal(
        "H4",
        "process_and_route",
        "Every relationship retains the exact product, map, and revision.",
        sorted({
            (
                item["productId"],
                item["processMapId"],
                item["processMapRevision"],
            )
            for item in edges
        }),
        [
            (
                "product-golden",
                "pm-golden",
                "7" * 64,
            )
        ],
    )


def _synthetic_edge_checks(
    recorder: _Recorder,
    source_state: Mapping[str, Any],
) -> None:
    overlapping = deepcopy(source_state)
    machining = next(
        item for item in overlapping["zones"]
        if item["zoneId"] == "dept-machining"
    )
    machining["boundary"] = [
        {"x": 90.0, "z": 110.0},
        {"x": 190.0, "z": 110.0},
        {"x": 190.0, "z": 200.0},
        {"x": 90.0, "z": 200.0},
    ]
    overlap_semantic = build_facility_semantic_map(overlapping)
    recorder.close(
        "B18",
        "deterministic_geometry",
        "Overlapping department polygons are unioned rather than double-counted.",
        overlap_semantic["facilitySummary"]["departmentAreaReconciliation"][
            "overlapSquareMeters"
        ],
        900.0,
    )

    incomplete = deepcopy(source_state)
    incomplete["facilityPolicy"]["rulesAuthoritative"] = False
    incomplete_semantic = build_facility_semantic_map(incomplete)
    operational = incomplete_semantic["facilitySummary"]["spatialMetrics"][
        "operationallyUsableFreeArea"
    ]
    blockers = incomplete_semantic["facilitySummary"]["spatialMetrics"][
        "completeness"
    ]["blockers"]
    recorder.check(
        "N1",
        "deterministic_geometry",
        "Operational free area fails closed when policy authority is incomplete.",
        passed=operational["areaSquareMeters"] is None and bool(blockers),
        observed={"operational": operational, "blockers": blockers},
        expected={"areaSquareMeters": None, "hasBlockers": True},
    )

    obstruction = deepcopy(source_state)
    obstruction["placements"].append({
        "placementId": "pl-route-obstruction",
        "assetId": "asset-cnc",
        "assetDefinitionRevision": "c" * 64,
        "displayName": "Route obstruction fixture",
        "category": "Machines",
        "planningReady": True,
        "planningReadinessEvidenceComplete": True,
        "physicalGeometry": [{
            "recordId": "physical:pl-route-obstruction",
            "polygon": [
                {"x": 48.0, "z": 95.0},
                {"x": 52.0, "z": 95.0},
                {"x": 52.0, "z": 105.0},
                {"x": 48.0, "z": 105.0},
            ],
            "minimumY": 0.0,
            "maximumY": 2.0,
            "authoritative": True,
        }],
        "transform": {"position": {"x": 50.0, "y": 0.0, "z": 100.0}},
        "zoneIds": [],
    })
    obstructed_semantic = build_facility_semantic_map(obstruction)
    obstructed_route = obstructed_semantic["routes"][0]
    recorder.check(
        "F6",
        "process_and_route",
        "Positive-area floor geometry crossing a route is reported as obstruction.",
        passed=(
            obstructed_route["geometricObstructionStatus"] == "obstructed"
            and any(
                item["placementId"] == "pl-route-obstruction"
                for item in obstructed_route["geometricObstructions"]
            )
        ),
        observed={
            "status": obstructed_route["geometricObstructionStatus"],
            "obstructions": obstructed_route["geometricObstructions"],
        },
        expected={
            "status": "obstructed",
            "placementId": "pl-route-obstruction",
        },
    )

    no_topology = deepcopy(source_state)
    for process_map in no_topology["processMaps"]:
        process_map.pop("graphTopologyLoaded", None)
        process_map.pop("precedenceEdges", None)
    unknown_flow = build_facility_semantic_map(no_topology)[
        "processRelationshipSummary"
    ]
    recorder.equal(
        "N2",
        "process_and_route",
        "ID-only process catalogs do not invent upstream/downstream order.",
        {
            "status": unknown_flow["flowSequenceStatus"],
            "edges": unknown_flow["relationshipEdgeCount"],
        },
        {"status": "unknown", "edges": 0},
    )


def _advanced_semantic_checks(
    recorder: _Recorder,
    source_state: Mapping[str, Any],
    semantic: Mapping[str, Any],
) -> None:
    """Exercise the operational semantics added after the first frozen gate."""

    summary = semantic["facilitySummary"]
    recorder.equal(
        "SEM1",
        "semantic_understanding",
        "Cell components aggregate into one module without becoming extra operational units.",
        {
            "placements": summary["placementCount"],
            "components": summary["componentPlacementCount"],
            "cellModules": summary["cellModuleCount"],
            "operationalUnits": summary["operationalUnitCount"],
        },
        {
            "placements": 7,
            "components": 7,
            "cellModules": 1,
            "operationalUnits": 7,
        },
    )

    missing_clearance = deepcopy(source_state)
    assembly_bench = next(
        item for item in missing_clearance["placements"]
        if item["placementId"] == "pl-assembly-bench"
    )
    for field in (
        "clearanceGeometry",
        "clearanceRecordCount",
        "parsedClearanceRecordCount",
        "authoritativeClearanceRecordCount",
    ):
        assembly_bench.pop(field, None)
    missing_map = build_facility_semantic_map(missing_clearance)
    cell_metrics = next(
        item for item in missing_map["zones"]
        if item["zoneId"] == "cell-assembly-a01"
    )["spatialMetrics"]
    recorder.equal(
        "SEM2",
        "deterministic_geometry",
        "Missing clearance evidence remains unknown while known geometric free area is still derived.",
        {
            "clearanceEvidence": cell_metrics["clearanceReservedArea"][
                "evidenceStatus"
            ],
            "missingModels": cell_metrics["clearanceReservedArea"][
                "missingModelPlacementCount"
            ],
            "knownPlanningFree": cell_metrics["knownPlanningFreeArea"][
                "areaSquareMeters"
            ],
            "operationalFree": cell_metrics[
                "operationallyUsableFreeArea"
            ]["areaSquareMeters"],
            "blockers": [
                item["code"]
                for item in cell_metrics["completeness"]["blockers"]
            ],
        },
        {
            "clearanceEvidence": "unknown",
            "missingModels": 1,
            "knownPlanningFree": 1500.0,
            "operationalFree": None,
            "blockers": ["clearance_model_absent"],
        },
    )

    resolved = resolve_facility_entities(
        source_state,
        query="CNC-01",
        entity_kinds=("placement",),
    )
    recorder.equal(
        "SEM3",
        "semantic_understanding",
        "A human equipment label resolves internally to its stable revision-bound placement.",
        {
            "status": resolved["resolutionStatus"],
            "entityId": resolved.get("resolved", {}).get("entityId"),
            "revision": resolved.get("resolved", {}).get(
                "assetDefinitionRevision"
            ),
        },
        {
            "status": "unique",
            "entityId": "pl-machining-cnc",
            "revision": "c" * 64,
        },
    )

    actual_clearances = analyze_facility_clearances(
        source_state,
        maximum_results=5,
    )
    recorder.check(
        "SEM4",
        "deterministic_geometry",
        "Actual edge separations remain measurable when required-clearance adequacy is unknown.",
        passed=(
            actual_clearances["returnedCount"] == 5
            and actual_clearances["records"][0][
                "actualEdgeToEdgeDistanceMeters"
            ] == 90.0
            and all(
                item["requirementStatus"] == "unknown"
                for item in actual_clearances["records"]
            )
        ),
        observed={
            "returnedCount": actual_clearances["returnedCount"],
            "firstRecord": actual_clearances["records"][0]
            if actual_clearances["records"] else None,
        },
        expected={
            "returnedCount": 5,
            "firstActualDistanceMeters": 90.0,
            "allRequirementStatuses": "unknown",
        },
    )

    cell_state = deepcopy(source_state)
    cell_zone = next(
        item for item in cell_state["zones"]
        if item["zoneId"] == "cell-assembly-a01"
    )
    cell_zone["extensions"] = {
        "cellGroup": {
            "schemaVersion": 1,
            "groupKind": "manufacturing_cell",
            "membership": "geometric",
            "envelopePadding": 0,
            "autoNumber": {
                "seriesId": "cell-series-a",
                "baseName": "Assembly Cell",
                "prefix": "A",
                "start": 1,
                "padding": 2,
                "sequence": 1,
            },
            "functionalInterfaces": {
                "gate": {
                    "side": "west",
                    "openingWidthMeters": 2,
                    "approachDepthMeters": 4,
                    "evidenceStatus": "authored",
                },
                "loading": {
                    "side": "north",
                    "evidenceStatus": "authored",
                },
                "service": {
                    "side": "east",
                    "evidenceStatus": "authored",
                },
            },
        },
    }
    cell_state["routes"].append({
        "routeId": "rt-cell-a01-approach",
        "label": "Assembly Cell A01 approach",
        "routeKind": "pedestrian",
        "corridorWidth": 2.0,
        "centerline": [
            {"x": 100.0, "z": 40.0},
            {"x": 110.0, "z": 40.0},
        ],
    })
    cell_before = _sha256(_canonical_bytes(cell_state))
    cell_access = analyze_facility_cell_access(
        cell_state,
        scope_ids=("cell-assembly-a01",),
    )
    cell_record = cell_access["records"][0]
    gate = next(
        item for item in cell_record["interfaces"]
        if item["role"] == "gate"
    )
    recorder.equal(
        "SEM5",
        "semantic_understanding",
        "Authored gate, loading, and service interfaces drive exact cell-access analysis.",
        {
            "complete": cell_record["interfaceEvidenceComplete"],
            "gateAnchor": gate["anchor"],
            "gateEnvelopeArea": gate[
                "accessEnvelopeAreaSquareMeters"
            ],
            "connectedRoutes": gate["connectedMatchingRouteIds"],
            "geometryStatus": gate["geometryStatus"],
            "adequacy": gate["adequacyStatus"],
            "mutation": cell_access["mutationPerformed"],
        },
        {
            "complete": True,
            "gateAnchor": {"x": 110.0, "z": 40.0},
            "gateEnvelopeArea": 8.0,
            "connectedRoutes": ["rt-cell-a01-approach"],
            "geometryStatus": (
                "route_connected_no_static_footprint_intrusion"
            ),
            "adequacy": "unknown_without_applicable_policy",
            "mutation": False,
        },
    )
    recorder.equal(
        "SEM6",
        "read_only_safety",
        "Cell-access inspection leaves the source state byte-identical.",
        _sha256(_canonical_bytes(cell_state)),
        cell_before,
    )

    module_fit = analyze_facility_module_fit(
        cell_state,
        source_zone_ids=("cell-assembly-a01",),
        target_zone_ids=("dept-automation",),
        orientations_degrees=(90,),
        maximum_results=1,
    )
    module_interfaces = module_fit["candidates"][0][
        "functionalInterfaces"
    ]
    recorder.equal(
        "SEM7",
        "bounded_fit",
        "A rotated complete cell transforms functional sides and remains a preview candidate, not proven capacity.",
        {
            "candidateCount": module_fit[
                "boundedGeometricAdditionalCount"
            ],
            "gate": module_interfaces["gate"]["side"],
            "loading": module_interfaces["loading"]["side"],
            "service": module_interfaces["service"]["side"],
            "fullyValidated": module_fit["candidates"][0][
                "fullyValidated"
            ],
            "productionCapacity": module_fit["productionCapacity"],
        },
        {
            "candidateCount": 1,
            "gate": "north",
            "loading": "east",
            "service": "south",
            "fullyValidated": False,
            "productionCapacity": None,
        },
    )

    crossing_state = deepcopy(source_state)
    crossing_state["routes"].append({
        "routeId": "rt-pedestrian-crossing",
        "label": "Pedestrian crossing probe",
        "routeKind": "pedestrian",
        "corridorWidth": 2.0,
        "centerline": [
            {"x": 40.0, "z": 100.0},
            {"x": 60.0, "z": 100.0},
        ],
    })
    crossing_map = build_facility_semantic_map(crossing_state)
    crossing = crossing_map["routeCrossings"][0]
    recorder.equal(
        "SEM8",
        "process_and_route",
        "Geometric pedestrian/material crossings remain visible even when movement graphs stay separate.",
        {
            "components": crossing_map["routeNetworkSummary"][
                "geometricMovementComponentCount"
            ],
            "crossings": crossing_map["routeNetworkSummary"][
                "geometricCrossingCount"
            ],
            "mixed": crossing["mixedPedestrianMaterialTraffic"],
            "coverage": crossing["crosswalkCoverageStatus"],
        },
        {
            "components": 2,
            "crossings": 1,
            "mixed": True,
            "coverage": "protected",
        },
    )

    render_state = deepcopy(source_state)
    render_state["editor"] = {
        "renderConsistency": {
            "topPlan": {
                "status": "match",
                "expectedPlacementCount": 7,
                "auditedPlacementCount": 7,
            },
            "three": {
                "status": "mismatch",
                "expectedPlacementCount": 7,
                "auditedPlacementCount": 7,
                "transformMismatchIds": ["pl-automation-robot"],
            },
        },
    }
    render_audit = analyze_facility_render_consistency(render_state)
    recorder.equal(
        "SEM9",
        "deterministic_geometry",
        "2D/3D agreement is audited from mounted transforms rather than assumed from shared state.",
        {
            "overall": render_audit["overallStatus"],
            "plan": render_audit["records"][0]["status"],
            "three": render_audit["records"][1]["status"],
            "mismatchIds": render_audit["records"][1][
                "transformMismatchIds"
            ],
        },
        {
            "overall": "mismatch",
            "plan": "match",
            "three": "mismatch",
            "mismatchIds": ["pl-automation-robot"],
        },
    )

    drone_state = {
        "facilityShell": {
            "floorSurfaces": [{"surfaceId": "floor", "elevation": 0}]
        },
        "editor": {
            "navigationCapabilities": {
                "activeMode": "drone",
                "drone": {
                    "supported": True,
                    "active": True,
                    "assistedFlight": True,
                    "colliderRadiusMeters": 0.35,
                    "altitudeMeters": 1.0,
                },
            },
        },
        "placements": [
            {
                "placementId": "rack-left",
                "displayName": "Rack left",
                "physicalGeometry": [{
                    "recordId": "physical:rack-left",
                    "polygon": [
                        {"x": 0, "z": 0}, {"x": 1, "z": 0},
                        {"x": 1, "z": 4}, {"x": 0, "z": 4},
                    ],
                    "minimumY": 0,
                    "maximumY": 2.5,
                    "authoritative": True,
                }],
            },
            {
                "placementId": "rack-right",
                "displayName": "Rack right",
                "physicalGeometry": [{
                    "recordId": "physical:rack-right",
                    "polygon": [
                        {"x": 2, "z": 0}, {"x": 3, "z": 0},
                        {"x": 3, "z": 4}, {"x": 2, "z": 4},
                    ],
                    "minimumY": 0,
                    "maximumY": 2.5,
                    "authoritative": True,
                }],
            },
            {
                "placementId": "overhead",
                "displayName": "Overhead obstruction",
                "physicalGeometry": [{
                    "recordId": "physical:overhead",
                    "polygon": [
                        {"x": 1, "z": 0}, {"x": 2, "z": 0},
                        {"x": 2, "z": 4}, {"x": 1, "z": 4},
                    ],
                    "minimumY": 1.2,
                    "maximumY": 1.8,
                    "authoritative": True,
                }],
            },
        ],
    }
    drone_before = _sha256(_canonical_bytes(drone_state))
    drone_clearance = analyze_facility_drone_clearance(
        drone_state,
        scope_ids=("rack-left", "rack-right"),
    )
    passage = drone_clearance["records"][0]
    recorder.equal(
        "SEM10",
        "deterministic_geometry",
        "Drone clearance uses the live collider and detects a full passage-strip overhead blocker.",
        {
            "supported": drone_clearance["droneCapability"]["supported"],
            "diameter": passage["droneColliderDiameterMeters"],
            "horizontalGap": passage["horizontalGapMeters"],
            "horizontalMargin": passage["horizontalColliderMarginMeters"],
            "status": passage["passageStatus"],
            "overheadMargin": passage["overheadConstraints"][0][
                "verticalSurfaceClearanceMeters"
            ],
            "mutation": drone_clearance["mutationPerformed"],
        },
        {
            "supported": True,
            "diameter": 0.7,
            "horizontalGap": 1.0,
            "horizontalMargin": 0.3,
            "status": "blocked_by_overhead_geometry",
            "overheadMargin": -0.15,
            "mutation": False,
        },
    )
    recorder.equal(
        "SEM11",
        "read_only_safety",
        "Drone-clearance analysis leaves mounted capability and geometry state unchanged.",
        _sha256(_canonical_bytes(drone_state)),
        drone_before,
    )

    asset_access_state = deepcopy(source_state)
    cnc_asset = next(
        item for item in asset_access_state["assets"]
        if item["assetId"] == "asset-cnc"
    )
    cnc_asset["facilitySemantics"] = {
        "semanticType": "cnc_machining_center",
        "operationalRoles": ["production_equipment", "machining"],
        "functionalSides": {
            "service": {
                "side": "east",
                "evidenceStatus": "authored",
            }
        },
        "evidenceStatus": "authored",
    }
    access_before = _sha256(_canonical_bytes(asset_access_state))
    asset_access = analyze_facility_asset_access(
        asset_access_state,
        interface_role="service",
        query="CNC-01",
    )
    service_record = asset_access["records"][0]
    recorder.equal(
        "SEM12",
        "deterministic_geometry",
        "Authored machine service sides produce measured outward clearance without an adequacy claim.",
        {
            "placement": service_record["placementId"],
            "localSide": service_record["localSide"],
            "worldSide": service_record["worldSide"],
            "anchor": service_record["anchor"],
            "boundaryDistance": service_record[
                "facilityBoundaryDistanceMeters"
            ],
            "adequacy": service_record["adequacyStatus"],
            "mutation": asset_access["mutationPerformed"],
        },
        {
            "placement": "pl-machining-cnc",
            "localSide": "east",
            "worldSide": "east",
            "anchor": {"x": 125.0, "z": 150.0},
            "boundaryDistance": 175.0,
            "adequacy": "unknown_without_applicable_policy",
            "mutation": False,
        },
    )
    recorder.equal(
        "SEM13",
        "read_only_safety",
        "Asset-side access analysis leaves the frozen source state unchanged.",
        _sha256(_canonical_bytes(asset_access_state)),
        access_before,
    )


def _action_and_continuity_checks(
    recorder: _Recorder,
    available_read_tools: set[str],
) -> None:
    presentation_tools = {CHAT_TABLE_TOOL, CHAT_VISUALIZATION_TOOL}
    review = facility_layout_tool_authorization(
        "Review the current facility layout without changing it.",
        read_tool_names=available_read_tools,
        presentation_tool_names=presentation_tools,
        preview_tool_name="build_facility_layout_preview",
        move_tool_name="preview_facility_move",
    )
    recorder.equal(
        "SAFE4",
        "read_only_safety",
        "A read-only Facility request exposes analysis and presentation tools only.",
        {
            "mode": review["mode"],
            "preview": "build_facility_layout_preview" in review[
                "allowedToolNames"
            ],
            "move": "preview_facility_move" in review[
                "allowedToolNames"
            ],
            "viewport": review["viewportNavigationAuthorized"],
            "commit": review["chatCommitToolAvailable"],
        },
        {
            "mode": "READ_ONLY",
            "preview": False,
            "move": False,
            "viewport": False,
            "commit": False,
        },
    )

    move_message = (
        "Move the selected machine 10 ft east and preserve its rotation."
    )
    move = facility_layout_tool_authorization(
        move_message,
        read_tool_names=available_read_tools,
        presentation_tool_names=presentation_tools,
        preview_tool_name="build_facility_layout_preview",
        move_tool_name="preview_facility_move",
    )
    recorder.equal(
        "SAFE5",
        "read_only_safety",
        "An exact translation authorizes only the narrow move preview and never viewport rotation.",
        {
            "mode": move["mode"],
            "precise": move["preciseTranslation"],
            "move": "preview_facility_move" in move[
                "allowedToolNames"
            ],
            "wholeLayoutPreview": "build_facility_layout_preview" in move[
                "allowedToolNames"
            ],
            "viewport": move["viewportNavigationAuthorized"],
        },
        {
            "mode": "PREVIEW",
            "precise": True,
            "move": True,
            "wholeLayoutPreview": False,
            "viewport": False,
        },
    )
    recorder.equal(
        "SAFE6",
        "read_only_safety",
        "An approval request is recognized but chat still exposes no commit tool.",
        facility_layout_tool_authorization(
            "Apply that preview.",
            read_tool_names=available_read_tools,
            presentation_tool_names=presentation_tools,
            preview_tool_name="build_facility_layout_preview",
            move_tool_name="preview_facility_move",
        )["chatCommitToolAvailable"],
        False,
    )

    recorder.equal(
        "M4",
        "intent_continuity",
        "Operation kind and exact requested metric remain independent.",
        {
            "inspect": classify_facility_request_kind(
                "Review this facility without changing anything."
            ),
            "move": classify_facility_request_kind(move_message),
            "chart": classify_facility_request_kind(
                "Chart operational utilization by department."
            ),
            "metric": requested_facility_metric(
                "Chart operational utilization by department."
            ),
            "areaMetric": requested_facility_metric(
                "Show a pie chart by floor area for the six departments."
            ),
            "countMetric": requested_facility_metric(
                "How many assets are in each department?"
            ),
        },
        {
            "inspect": "inspect",
            "move": "exact_transform",
            "chart": "render",
            "metric": "department_operational_utilization",
            "areaMetric": "department_gross_area",
            "countMetric": "placement_count",
        },
    )
    recorder.equal(
        "M5",
        "intent_continuity",
        "A short yes resolves the exact pending read-only analysis rather than losing the question.",
        resolve_facility_pending_follow_up(
            "yes",
            recent_turns=(
                {
                    "role": "user",
                    "content": (
                        "Which assembly cell has the least operator walking?"
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "I can retrieve the four assembly-cell coordinates "
                        "and calculate the walking-distance comparison. "
                        "Should I do that?"
                    ),
                },
            ),
        ),
        {
            "priorUserRequest": (
                "Which assembly cell has the least operator walking?"
            ),
            "assistantOffer": (
                "I can retrieve the four assembly-cell coordinates and "
                "calculate the walking-distance comparison. Should I do that?"
            ),
            "ambiguous": False,
            "actionMode": "READ_ONLY",
        },
    )
    recorder.equal(
        "M6",
        "intent_continuity",
        "Social conversation does not masquerade as a Facility action.",
        {
            "intent": classify_facility_layout_request("hi"),
            "mode": facility_layout_action_mode("hi"),
            "preciseMove": is_precise_facility_translation_request("hi"),
        },
        {
            "intent": "unrelated",
            "mode": "READ_ONLY",
            "preciseMove": False,
        },
    )
    recorder.equal(
        "M7",
        "intent_continuity",
        "Spatial question classes map to deterministic analyses without granting write authority.",
        {
            "routeCrossing": requested_facility_spatial_analyses(
                "Where do pedestrian and forklift paths intersect?"
            ),
            "robotCell": requested_facility_spatial_analyses(
                "Inspect robot-cell gates and keep-clear intrusions."
            ),
            "service": requested_facility_spatial_analyses(
                "Which machines are hardest to service?"
            ),
            "drone": requested_facility_spatial_analyses(
                "Can the drone pass between these racks at this altitude?"
            ),
        },
        {
            "routeCrossing": ("route_crossings",),
            "robotCell": ("cell_access", "protected_intrusions"),
            "service": ("asset_access",),
            "drone": ("drone_clearance",),
        },
    )


def _orchestration_policy_checks(
    recorder: _Recorder,
    available_read_tools: set[str],
) -> None:
    preview_tool = "build_facility_layout_preview"
    move_tool = "preview_facility_move"
    presentation_tools = {CHAT_TABLE_TOOL, CHAT_VISUALIZATION_TOOL}
    expected_read_tools = {
        "inspect": {
            "search_industrial_assets",
            "inspect_facility_entities",
            "inspect_facility_region",
            "inspect_facility_findings",
            "inspect_process_bindings",
            "inspect_facility_semantics",
            "inspect_pattern_provenance",
            "inspect_cell_layout_provenance",
        },
        "measure": {
            "inspect_facility_entities",
            "inspect_facility_region",
            "inspect_facility_semantics",
            "analyze_facility_spatial",
            "analyze_facility_fit",
        },
        "compare": {
            "inspect_facility_entities",
            "inspect_facility_region",
            "inspect_process_bindings",
            "inspect_facility_semantics",
            "inspect_pattern_provenance",
            "inspect_cell_layout_provenance",
            "analyze_facility_spatial",
            "analyze_facility_fit",
        },
        "recommend": {
            "search_industrial_assets",
            "inspect_facility_entities",
            "inspect_facility_region",
            "inspect_facility_findings",
            "inspect_process_bindings",
            "inspect_facility_semantics",
            "analyze_facility_spatial",
            "analyze_facility_fit",
        },
        "render": {
            "inspect_facility_entities",
            "inspect_facility_region",
            "inspect_facility_semantics",
            "analyze_facility_spatial",
            "analyze_facility_fit",
        },
    }
    read_plans = {
        intent: build_facility_orchestration_plan(
            operation_intent=intent,
            action_mode="READ_ONLY",
            available_read_tools=available_read_tools,
            presentation_tools=presentation_tools,
            preview_tool_name=preview_tool,
            move_tool_name=move_tool,
        )
        for intent in expected_read_tools
    }
    recorder.check(
        "ORCH1",
        "read_only_safety",
        "Every read intent has an exact allowlist and no preview or viewport authority.",
        passed=all(
            set(read_plans[intent]["allowedToolNames"]) == expected
            and preview_tool not in read_plans[intent]["allowedToolNames"]
            and move_tool not in read_plans[intent]["allowedToolNames"]
            and read_plans[intent]["viewportNavigationAuthorized"] is False
            and all(
                contract["mutates"] is False
                for contract in read_plans[intent]["toolContracts"].values()
            )
            for intent, expected in expected_read_tools.items()
        ),
        observed={
            intent: sorted(plan["allowedToolNames"])
            for intent, plan in read_plans.items()
        },
        expected={
            intent: sorted(tools)
            for intent, tools in expected_read_tools.items()
        },
    )

    prompts = {
        "What pattern created these rows?": ("inspect", "READ_ONLY"),
        "Measure these rack aisles.": ("measure", "READ_ONLY"),
        "Compare Machining Hall and Automation.": (
            "compare",
            "READ_ONLY",
        ),
        "What three changes would you recommend?": (
            "recommend",
            "READ_ONLY",
        ),
        "Show a compact alternative in a ghost preview.": (
            "simulate",
            "PREVIEW",
        ),
        "Move the selected machine 10 ft east.": (
            "exact_transform",
            "PREVIEW",
        ),
        "Rearrange this department.": ("modify", "PREVIEW"),
        "Fly to CNC-04.": ("navigate", "READ_ONLY"),
        "Chart usable area by department.": ("render", "READ_ONLY"),
    }
    recorder.equal(
        "ORCH2",
        "intent_continuity",
        "The complete Facility operation-intent space is classified before tools are exposed.",
        {
            prompt: (
                classify_facility_request_kind(prompt),
                facility_layout_action_mode(prompt),
            )
            for prompt in prompts
        },
        prompts,
    )

    simulate = build_facility_orchestration_plan(
        operation_intent="simulate",
        action_mode="PREVIEW",
        available_read_tools=available_read_tools,
        presentation_tools=presentation_tools,
        preview_tool_name=preview_tool,
        move_tool_name=move_tool,
    )
    exact = build_facility_orchestration_plan(
        operation_intent="exact_transform",
        action_mode="PREVIEW",
        available_read_tools=available_read_tools,
        presentation_tools=presentation_tools,
        preview_tool_name=preview_tool,
        move_tool_name=move_tool,
        spatial_analyses=("clearances",),
    )
    recorder.equal(
        "ORCH3",
        "read_only_safety",
        "Simulation and exact transforms expose distinct, narrow preview paths.",
        {
            "simulatePermission": simulate["permission"],
            "simulatePreview": preview_tool in simulate["allowedToolNames"],
            "simulateMove": move_tool in simulate["allowedToolNames"],
            "exactPermission": exact["permission"],
            "exactPreview": preview_tool in exact["allowedToolNames"],
            "exactMove": move_tool in exact["allowedToolNames"],
            "exactMoveMutatesDraft": exact["toolContracts"][move_tool][
                "mutates"
            ],
            "exactCandidateValidation": any(
                item["id"] == "candidate_validation"
                for item in exact["requiredEvidence"]
            ),
        },
        {
            "simulatePermission": "simulate",
            "simulatePreview": True,
            "simulateMove": False,
            "exactPermission": "draft_write",
            "exactPreview": False,
            "exactMove": True,
            "exactMoveMutatesDraft": True,
            "exactCandidateValidation": True,
        },
    )

    commit = build_facility_orchestration_plan(
        operation_intent="modify",
        action_mode="COMMIT",
        available_read_tools=available_read_tools,
        presentation_tools=presentation_tools,
        preview_tool_name=preview_tool,
        move_tool_name=move_tool,
    )
    recorder.equal(
        "ORCH4",
        "read_only_safety",
        "Chat approval cannot expose or synthesize a commit capability.",
        {
            "permission": commit["permission"],
            "allowed": sorted(commit["allowedToolNames"]),
            "chatCommit": commit["chatCommitToolAvailable"],
        },
        {
            "permission": "commit_request",
            "allowed": [],
            "chatCommit": False,
        },
    )

    pattern_analyses = requested_facility_spatial_analyses(
        "What pattern created these rows?"
    )
    cell_analyses = requested_facility_spatial_analyses(
        "What strategy created Assembly Cell A01?"
    )
    pattern = build_facility_orchestration_plan(
        operation_intent="inspect",
        action_mode="READ_ONLY",
        available_read_tools=available_read_tools,
        presentation_tools=presentation_tools,
        preview_tool_name=preview_tool,
        move_tool_name=move_tool,
        spatial_analyses=pattern_analyses,
    )
    cell = build_facility_orchestration_plan(
        operation_intent="inspect",
        action_mode="READ_ONLY",
        available_read_tools=available_read_tools,
        presentation_tools=presentation_tools,
        preview_tool_name=preview_tool,
        move_tool_name=move_tool,
        spatial_analyses=cell_analyses,
    )
    recorder.equal(
        "ORCH5",
        "provenance",
        "Pattern and cell-layout provenance require distinct read-only evidence tools.",
        {
            "patternAnalyses": pattern_analyses,
            "patternTool": pattern["requiredObservationTool"],
            "cellAnalyses": cell_analyses,
            "cellTool": cell["requiredObservationTool"],
        },
        {
            "patternAnalyses": (
                "pattern_provenance",
                "layout_provenance",
            ),
            "patternTool": "inspect_pattern_provenance",
            "cellAnalyses": (
                "cell_layout_provenance",
                "layout_provenance",
            ),
            "cellTool": "inspect_cell_layout_provenance",
        },
    )

    measured = build_facility_orchestration_plan(
        operation_intent="measure",
        action_mode="READ_ONLY",
        available_read_tools=available_read_tools,
        presentation_tools=presentation_tools,
        preview_tool_name=preview_tool,
        move_tool_name=move_tool,
        requested_metric="route_usable_width",
        spatial_analyses=("route_widths",),
    )
    recorder.equal(
        "ORCH6",
        "tool_contracts",
        "Requested metrics carry an explicit observation and evidence-completeness contract.",
        {
            "tool": measured["requiredObservationTool"],
            "requirements": measured["requiredEvidence"],
        },
        {
            "tool": "analyze_facility_spatial",
            "requirements": [
                {
                    "id": "revision_bound_context",
                    "satisfiedBy": "trusted_facility_context",
                },
                {
                    "id": "requested_metric_evidence",
                    "satisfiedByAnyTool": [
                        "analyze_facility_spatial"
                    ],
                    "metricId": "route_usable_width",
                },
            ],
        },
    )

    trace = facility_orchestration_trace(
        measured,
        resolved_entity_ids=("route-main",),
        tool_calls=(
            {"name": "analyze_facility_spatial"},
            {"name": preview_tool},
        ),
        evidence_completeness={"complete": True},
    )
    recorder.equal(
        "ORCH7",
        "tool_contracts",
        "Operational traces expose policy decisions without chain-of-thought.",
        {
            "intent": trace["operationIntent"],
            "entities": trace["resolvedEntityIds"],
            "calls": trace["toolCalls"],
            "containsReasoning": "reasoning" in json.dumps(trace).lower(),
        },
        {
            "intent": "measure",
            "entities": ["route-main"],
            "calls": [
                {"name": "analyze_facility_spatial", "allowed": True},
                {"name": preview_tool, "allowed": False},
            ],
            "containsReasoning": False,
        },
    )

    now = [100.0]
    pending_store = FacilityPendingOperationStore(
        ttl_seconds=30.0,
        max_sessions=2,
        clock=lambda: now[0],
    )
    stored = pending_store.put(
        "evaluation-session",
        {
            "goal": "Which assembly cell has the least operator walking?",
            "operationIntent": "measure",
            "referencedEntityIds": ["cell-a01", "cell-a02"],
            "awaiting": "confirmation",
        },
    )
    resumed = pending_store.get("evaluation-session")
    now[0] = 131.0
    expired = pending_store.get("evaluation-session")
    recorder.equal(
        "ORCH8",
        "intent_continuity",
        "Pending Facility operations are server-authoritative, read-only, bounded, and expiring.",
        {
            "stored": stored,
            "intent": resumed.get("operationIntent") if resumed else None,
            "mode": resumed.get("actionMode") if resumed else None,
            "entities": (
                resumed.get("referencedEntityIds") if resumed else None
            ),
            "expired": expired,
        },
        {
            "stored": True,
            "intent": "measure",
            "mode": "READ_ONLY",
            "entities": ["cell-a01", "cell-a02"],
            "expired": None,
        },
    )


def _provenance_checks(
    recorder: _Recorder,
    source_state: Mapping[str, Any],
    semantic: Mapping[str, Any],
) -> None:
    group = semantic["layoutPatternGroups"][0]
    recorder.equal(
        "C1",
        "provenance",
        "Authored U-cell strategy takes precedence over visual inference.",
        {
            "command": group["command"],
            "strategy": group["authoredStrategy"],
            "status": group["currentClassification"]["status"],
            "confidence": group["currentClassification"]["confidence"],
        },
        {
            "command": "cell_layout",
            "strategy": "u",
            "status": "consistent",
            "confidence": 1.0,
        },
    )
    modified = deepcopy(source_state)
    bench = next(
        item for item in modified["placements"]
        if item["placementId"] == "pl-assembly-bench"
    )
    bench["transform"]["position"]["x"] += 1.0
    provenance = bench["metadata"]["layoutProvenance"]
    provenance["geometryEditedSinceCreation"] = True
    provenance["manuallyEditedSinceCreation"] = True
    modified_group = build_facility_semantic_map(modified)[
        "layoutPatternGroups"
    ][0]
    recorder.equal(
        "C2",
        "provenance",
        "Manual geometry drift is not mislabeled as the authored shape.",
        {
            "status": modified_group["currentClassification"]["status"],
            "modifiedMemberCount": modified_group["modifiedMemberCount"],
            "manual": modified_group["members"][0][
                "manuallyEditedSinceCreation"
            ],
        },
        {"status": "modified", "modifiedMemberCount": 1, "manual": True},
    )
    strategies = {
        item["strategyId"]: item
        for item in semantic["cellLayoutStrategies"]
    }
    recorder.equal(
        "C3",
        "semantic_understanding",
        "The cell-strategy vocabulary is closed and complete.",
        sorted(strategies),
        sorted([
            "line",
            "l",
            "u",
            "grid",
            "parallel",
            "serpentine",
            "loop",
            "spine",
            "herringbone",
            "cluster",
        ]),
    )
    recorder.check(
        "C4",
        "semantic_understanding",
        "Every strategy carries use, tradeoff, avoidance, and validator knowledge.",
        passed=all(
            item.get("bestFor")
            and item.get("advantages")
            and item.get("tradeoffs")
            and item.get("avoidWhen")
            and item.get("validators")
            for item in strategies.values()
        ),
        observed={
            key: {
                "bestFor": len(value.get("bestFor", [])),
                "tradeoffs": len(value.get("tradeoffs", [])),
                "validators": len(value.get("validators", [])),
            }
            for key, value in strategies.items()
        },
        expected="all strategy knowledge fields non-empty",
    )
    recorder.equal(
        "C5",
        "semantic_understanding",
        "The U strategy exposes an explicit inverted-opening variant.",
        strategies["u"]["variants"][0]["parameter"],
        "invertU",
    )


def _fit_checks(recorder: _Recorder, repo_root: Path) -> None:
    golden = _read_json(repo_root / SPATIAL_FIXTURE)
    layout = deepcopy(golden["baseLayout"])
    assets = deepcopy(golden["assetDefinitions"])
    machine = next(
        item for item in assets
        if item["assetId"] == "asset-machine-golden"
    )
    machine["assetDefinitionRevision"] = MACHINE_REVISION
    before = canonical_spatial_bytes(layout)
    result = analyze_facility_asset_fit(
        layout,
        assets,
        asset_id="asset-machine-golden",
        asset_definition_revision=MACHINE_REVISION,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        orientations_degrees=[0, 90],
        maximum_results=4,
    )
    recorder.equal(
        "D1",
        "read_only_safety",
        "Bounded fit analysis leaves the source layout byte-identical.",
        canonical_spatial_bytes(layout),
        before,
    )
    recorder.equal(
        "D2",
        "bounded_fit",
        "The exact revisioned machine has a fully validated candidate.",
        {
            "status": result["status"],
            "probeCount": result["probeCount"],
            "evaluated": result["engineEvaluatedCount"],
            "geometric": result["geometricFitFound"],
            "clearance": result["clearanceValidatedFitFound"],
            "full": result["fullyValidatedFitFound"],
        },
        {
            "status": "complete",
            "probeCount": 25,
            "evaluated": 50,
            "geometric": True,
            "clearance": True,
            "full": True,
        },
    )
    recorder.equal(
        "D3",
        "bounded_fit",
        "A positive bounded fit never upgrades maximum or production capacity.",
        result["evidenceClassification"],
        {
            "assetAndZoneIdentity": "authored",
            "candidateGeometry": "derived",
            "fitSearchCompleteness": "bounded_not_exhaustive",
            "maximumAdditionalCapacity": "unknown",
            "productionCapacity": "unknown",
        },
    )

    no_clearance = deepcopy(assets)
    next(
        item for item in no_clearance
        if item["assetId"] == "asset-machine-golden"
    )["clearances"] = []
    incomplete = analyze_facility_asset_fit(
        deepcopy(golden["baseLayout"]),
        no_clearance,
        asset_id="asset-machine-golden",
        asset_definition_revision=MACHINE_REVISION,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        orientations_degrees=[0],
        maximum_results=4,
    )
    recorder.equal(
        "D4",
        "bounded_fit",
        "Geometric fit remains separate from missing clearance evidence.",
        {
            "geometric": incomplete["geometricFitFound"],
            "clearance": incomplete["clearanceValidatedFitFound"],
            "full": incomplete["fullyValidatedFitFound"],
        },
        {"geometric": True, "clearance": False, "full": False},
    )

    stale = analyze_facility_asset_fit(
        golden["baseLayout"],
        assets,
        asset_id="asset-machine-golden",
        asset_definition_revision="f" * 64,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
    )
    recorder.equal(
        "D5",
        "bounded_fit",
        "A missing exact asset revision fails closed.",
        {
            "status": stale["status"],
            "blockers": stale["blockerCodes"],
            "candidates": stale["candidates"],
        },
        {
            "status": "blocked",
            "blockers": ["exact_asset_revision_unavailable"],
            "candidates": [],
        },
    )

    protected_layout = deepcopy(golden["baseLayout"])
    protected_layout["routes"] = [{
        "routeId": "rt-protected-entire-cell",
        "routeKind": "forklift",
        "corridorWidth": 20.0,
        "centerline": [
            {"x": 0.0, "z": 10.0},
            {"x": 20.0, "z": 10.0},
        ],
    }]
    protected = analyze_facility_asset_fit(
        protected_layout,
        assets,
        asset_id="asset-machine-golden",
        asset_definition_revision=MACHINE_REVISION,
        zone_id="zn-golden-cell",
        shell=golden["shell"],
        policy_set=golden["policySet"],
        evidence_authority=golden["authority"],
        orientations_degrees=[0],
        maximum_results=4,
    )
    recorder.check(
        "D6",
        "bounded_fit",
        "Protected route reservations reject every intersecting candidate.",
        passed=(
            protected["geometricFitFound"] is False
            and protected["candidates"] == []
            and protected["rejectionCounts"].get(
                "protected_space_intrusion"
            ) == 24
        ),
        observed={
            "geometric": protected["geometricFitFound"],
            "candidates": len(protected["candidates"]),
            "rejections": protected["rejectionCounts"],
        },
        expected={
            "geometric": False,
            "candidates": 0,
            "protected_space_intrusion": 24,
        },
    )


def _tool_skill_checks(recorder: _Recorder, repo_root: Path) -> None:
    registry = facility_semantic_registry()
    registry_commands = {
        item["commandId"] for item in registry["commands"]
    }
    read_specs = facility_layout_read_tool_specs()
    read_names = {item["name"] for item in read_specs}
    preview_spec = facility_layout_preview_tool_spec()
    move_spec = facility_layout_move_tool_spec()
    g1_spec = g1_facility_generation_tool_spec()
    runtime_tool_names = {
        *read_names,
        preview_spec["name"],
        move_spec["name"],
        g1_spec["name"],
        CHAT_VISUALIZATION_TOOL,
        CHAT_TABLE_TOOL,
    }
    registry_tools = {
        item["commandId"] for item in registry["agentTools"]
    }

    index_text = (repo_root / "static/index.html").read_text(
        encoding="utf-8"
    )
    ui_commands = _ribbon_commands(index_text)
    recorder.check(
        "K1",
        "tool_contracts",
        "Every visible Facility ribbon command has semantic meaning.",
        passed=bool(ui_commands) and ui_commands <= registry_commands,
        observed={
            "uiCommandCount": len(ui_commands),
            "missingSemanticCommands": sorted(
                ui_commands - registry_commands
            ),
        },
        expected={"missingSemanticCommands": []},
    )
    recorder.equal(
        "K2",
        "tool_contracts",
        "Agent semantic registry and exposed runtime tools are closed.",
        sorted(registry_tools),
        sorted(runtime_tool_names),
    )
    recorder.check(
        "K3",
        "tool_contracts",
        "Every read tool schema rejects unknown fields.",
        passed=all(
            spec["input_schema"].get("additionalProperties") is False
            for spec in read_specs
        ),
        observed={
            spec["name"]: spec["input_schema"].get(
                "additionalProperties"
            )
            for spec in read_specs
        },
        expected="all false",
    )
    fit_spec = next(
        item for item in read_specs
        if item["name"] == "analyze_facility_fit"
    )
    fit_fields = set(fit_spec["input_schema"]["properties"])
    forbidden_fit_fields = {
        "x", "y", "z", "position", "transform", "quaternion", "matrix",
        "coordinates", "probePoints",
    }
    recorder.check(
        "K4",
        "tool_contracts",
        "Fit accepts human/current selectors but no model-authored coordinates.",
        passed=(
            not (fit_fields & forbidden_fit_fields)
            and {"assetQuery", "sourcePlacementId", "useSelectedPlacement"}
            <= fit_fields
            and {"zoneId", "zoneQuery"} <= fit_fields
        ),
        observed=sorted(fit_fields),
        expected={
            "humanAndCurrentSelectors": True,
            "modelAuthoredCoordinates": False,
        },
    )
    forbidden_preview_fields = {
        "x",
        "y",
        "z",
        "position",
        "transform",
        "quaternion",
        "matrix",
        "camera",
        "waypoints",
        "operations",
    }
    preview_fields = _collect_schema_property_names(
        preview_spec["input_schema"]
    )
    recorder.equal(
        "K5",
        "tool_contracts",
        "The preview schema contains no model-authored low-level geometry fields.",
        sorted(preview_fields & forbidden_preview_fields),
        [],
    )

    analysis_manifest = yaml.safe_load(
        (
            repo_root
            / "ai_inspector/agent_skills/analyze-facility-layout/manifest.yaml"
        ).read_text(encoding="ascii")
    )
    generation_manifest = yaml.safe_load(
        (
            repo_root
            / "ai_inspector/agent_skills/generate-facility-layout/manifest.yaml"
        ).read_text(encoding="ascii")
    )
    analysis_contract = yaml.safe_load(
        (
            repo_root
            / "ai_inspector/agent_skills/analyze-facility-layout/contract.yaml"
        ).read_text(encoding="ascii")
    )
    generation_contract = yaml.safe_load(
        (
            repo_root
            / "ai_inspector/agent_skills/generate-facility-layout/contract.yaml"
        ).read_text(encoding="ascii")
    )
    analysis_tools = set(analysis_manifest["allowed_tools"])
    generation_tools = set(generation_manifest["allowed_tools"])
    recorder.check(
        "K6",
        "read_only_safety",
        "The analysis skill can present results but cannot build a preview.",
        passed=(
            preview_spec["name"] not in analysis_tools
            and {CHAT_VISUALIZATION_TOOL, CHAT_TABLE_TOOL} <= analysis_tools
            and analysis_manifest["side_effects"] == []
            and analysis_contract["side_effect_policy"]["default"]
            == "prohibited"
        ),
        observed={
            "allowedTools": sorted(analysis_tools),
            "sideEffects": analysis_manifest["side_effects"],
            "defaultPolicy": analysis_contract["side_effect_policy"][
                "default"
            ],
        },
        expected="presentation allowed; preview and side effects prohibited",
    )
    recorder.check(
        "K7",
        "read_only_safety",
        "Generation exposes draft tools only under explicit request.",
        passed=(
            preview_spec["name"] in generation_tools
            and move_spec["name"] in generation_tools
            and generation_manifest["side_effects"] == []
            and generation_contract["side_effect_policy"]["default"]
            == "prohibited"
            and set(generation_contract["side_effect_policy"][
                "require_explicit_user_request"
            ]) == {
                move_spec["name"],
                preview_spec["name"],
                "generate_full_factory_draft",
                "generate_facility_planning_prototype_draft",
                "amend_facility_program_resource_batch_draft",
            }
        ),
        observed={
            "previewAvailable": preview_spec["name"] in generation_tools,
            "sideEffects": generation_manifest["side_effects"],
            "explicit": generation_contract["side_effect_policy"][
                "require_explicit_user_request"
            ],
        },
        expected="explicit draft tools; no commit side effect",
    )
    recorder.check(
        "K8",
        "tool_contracts",
        "The browser has concrete handlers and bounded timeouts for both new tools.",
        passed=all(
            token in index_text
            for token in (
                "inspect_facility_semantics:",
                "analyze_facility_spatial:",
                "analyze_facility_fit:",
                "inspect_facility_semantics: 12000",
                "analyze_facility_spatial: 30000",
                "analyze_facility_fit: 30000",
            )
        ),
        observed={
            token: token in index_text
            for token in (
                "inspect_facility_semantics:",
                "analyze_facility_spatial:",
                "analyze_facility_fit:",
                "inspect_facility_semantics: 12000",
                "analyze_facility_spatial: 30000",
                "analyze_facility_fit: 30000",
            )
        },
        expected="all handlers and timeouts present",
    )

    analysis_skill = (
        repo_root
        / "ai_inspector/agent_skills/analyze-facility-layout/SKILL.md"
    ).read_text(encoding="ascii")
    generation_skill = (
        repo_root
        / "ai_inspector/agent_skills/generate-facility-layout/SKILL.md"
    ).read_text(encoding="ascii")
    recorder.check(
        "K9",
        "tool_contracts",
        "Analysis policy freezes metric fidelity and evidence separation.",
        passed=all(
            phrase in analysis_skill
            for phrase in (
                "Never call a placement count floor area",
                "Do not silently substitute another metric",
                "geometricFreeAreaSquareMeters",
                "operationallyUsableFreeAreaSquareMeters",
                "A Pareto chart is not a plain",
                "`asset_access` measures an authored operator",
                "`drone_clearance` uses the mounted Drone collider",
            )
        ),
        observed="analysis skill policy phrases",
        expected="all required policy phrases present",
    )
    recorder.check(
        "K10",
        "tool_contracts",
        "Generation policy separates strategy ranking from deterministic execution.",
        passed=all(
            phrase in generation_skill
            for phrase in (
                "rank strategies against the authored manufacturing situation",
                "request deterministic geometry for the preferred strategy",
                "validate the result",
                "Preserve manual and locked positions",
            )
        ),
        observed="generation skill strategy policy phrases",
        expected="all required policy phrases present",
    )


def _case_matrix_checks(
    recorder: _Recorder,
    repo_root: Path,
    available_tools: set[str],
) -> dict[str, Any]:
    matrix = _read_json(repo_root / DEFAULT_CASES)
    command_registry = {
        item["commandId"]: item
        for item in facility_semantic_registry()["commands"]
    }
    cases = matrix.get("cases")
    if not isinstance(cases, list):
        raise ValueError("evaluation case matrix requires a cases array")
    case_results = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        history = case.get("recentTurns")
        history = history if isinstance(history, list) else []
        workflow_state = (
            {"workflow_id": "facility-layout-analysis"}
            if case.get("activeFacilityWorkflow") is True
            else None
        )
        actual = (
            resolve_facility_layout_turn(
                str(case.get("prompt") or ""),
                recent_turns=history,
                workflow_state=workflow_state,
            )
            if history or workflow_state is not None
            else classify_facility_layout_request(
                str(case.get("prompt") or "")
            )
        )
        required_tools = {
            str(item) for item in case.get("requiredTools", [])
        }
        forbidden_tools = {
            str(item) for item in case.get("forbiddenTools", [])
        }
        mode = str(case.get("mode") or "read_only")
        expected_intent = str(case.get("expectedIntent") or "analysis")
        expected_capability = str(
            case.get("expectedCapability") or "available_agent_tool"
        )
        command_id = str(case.get("commandId") or "")
        command_semantics = command_registry.get(command_id)
        capability_passed = True
        if expected_capability == "gated_ui_only":
            capability_passed = bool(
                command_semantics
                and command_semantics.get("agentAvailability") == "ui_only"
                and "build_facility_layout_preview" not in required_tools
            )
        passed = (
            actual == expected_intent
            and required_tools <= available_tools
            and not (required_tools & forbidden_tools)
            and capability_passed
            and (
                mode != "read_only"
                or "build_facility_layout_preview" not in required_tools
            )
        )
        case_results.append({
            "id": case.get("id"),
            "suite": case.get("suite"),
            "prompt": case.get("prompt"),
            "mode": mode,
            "expectedIntent": expected_intent,
            "actualIntent": actual,
            "requiredTools": sorted(required_tools),
            "missingTools": sorted(required_tools - available_tools),
            "forbiddenTools": sorted(forbidden_tools),
            "expectedCapability": expected_capability,
            "commandId": command_id or None,
            "commandAvailability": (
                command_semantics.get("agentAvailability")
                if command_semantics
                else None
            ),
            "capabilityPassed": capability_passed,
            "passed": passed,
        })
    recorder.check(
        "MATRIX-1",
        "intent_continuity",
        "The structural intent/tool matrix passes every frozen prompt variant.",
        passed=bool(case_results) and all(
            item["passed"] for item in case_results
        ),
        observed={
            "caseCount": len(case_results),
            "failedCaseIds": [
                item["id"] for item in case_results if not item["passed"]
            ],
        },
        expected={"failedCaseIds": []},
    )
    direct_cases = [
        ("How much free space remains in Machining Hall?", "analysis"),
        ("Can we add another CNC to Machining Hall?", "analysis"),
        ("Can you add another CNC to Machining Hall?", "generation"),
        ("Build a new facility layout preview.", "generation"),
        ("Create a pie chart of facility department area.", "analysis"),
        ("hi", "unrelated"),
    ]
    recorder.equal(
        "M1",
        "intent_continuity",
        "The authorization classifier separates analysis, preview, and unrelated turns.",
        [
            classify_facility_layout_request(prompt)
            for prompt, _expected in direct_cases
        ],
        [expected for _prompt, expected in direct_cases],
    )
    recorder.equal(
        "M2",
        "intent_continuity",
        "A bare follow-up inherits only read-only Facility scope.",
        resolve_facility_layout_turn(
            "yes",
            recent_turns=[{
                "role": "user",
                "content": "Compare the Machining Hall and Automation zone.",
            }],
        ),
        "analysis",
    )
    recorder.equal(
        "M3",
        "intent_continuity",
        "A social turn remains conversational in an active Facility workflow.",
        resolve_facility_layout_turn(
            "hi",
            workflow_state={"workflow_id": "facility-layout-analysis"},
        ),
        "analysis",
    )
    return {"contractVersion": matrix.get("contractVersion"), "cases": case_results}


def _knowledge_trace_checks(
    recorder: _Recorder,
    repo_root: Path,
) -> dict[str, Any]:
    evidence = load_facility_trace_evidence(repo_root)
    traces = evidence["goldTraces"]["traces"]
    held_out = evidence["heldOut"]
    held_out_result = evaluate_held_out_command_families(held_out)
    contexts = {
        stage["stageId"]: compile_facility_trace_context(
            repo_root,
            stage["stageId"],
            g1_only=False,
        )
        for stage in FACILITY_GENERATION_STAGES
    }
    g1_contexts = {
        stage_id: compile_facility_trace_context(
            repo_root,
            stage_id,
            g1_only=True,
        )
        for stage_id in ("facility_envelope", "macro_departments", "review_and_save")
    }
    provider = resolve_facility_provider_config(os.environ)
    provider_metadata = provider.public_metadata()

    recorder.equal(
        "KF6-REGRESSION-1",
        "knowledge_traces",
        "All established cases remain regression-visible and are not relabeled as held out.",
        evidence["regressionVisible"]["caseCount"],
        71,
    )
    recorder.equal(
        "KF6-REGRESSION-2",
        "knowledge_traces",
        "The established case inventory is explicitly classified as non-held-out regression evidence.",
        {
            "classification": evidence["regressionVisible"]["classification"],
            "heldOut": evidence["regressionVisible"]["heldOut"],
        },
        {
            "classification": "regression_visible_not_held_out",
            "heldOut": False,
        },
    )
    recorder.equal(
        "KF6-TRACE-1",
        "knowledge_traces",
        "Generalized traces cover positive, negative, correction, and live modification behavior.",
        sorted({item["traceKind"] for item in traces}),
        ["correction", "live_modification", "negative", "positive"],
    )
    recorder.check(
        "KF6-TRACE-2",
        "knowledge_traces",
        "No gold trace carries production evidence authority or copied reference coordinates.",
        passed=(
            all(
                item["illustrative"] is True
                and item["productionEvidence"] is False
                for item in traces
            )
            and evidence["goldTraces"]["sourceReference"][
                "coordinateContentCopied"
            ]
            is False
        ),
        observed={
            "traceCount": len(traces),
            "coordinateContentCopied": evidence["goldTraces"][
                "sourceReference"
            ]["coordinateContentCopied"],
        },
        expected={"allIllustrative": True, "coordinateContentCopied": False},
    )
    recorder.check(
        "KF6-CONTEXT-1",
        "knowledge_traces",
        "Every stage-specific trace context remains within the authoritative 8192-byte limit.",
        passed=all(
            item["measurement"]["canonicalBytes"] <= 8_192
            for item in contexts.values()
        ),
        observed={
            key: value["measurement"] for key, value in contexts.items()
        },
        expected={"maximumBytes": 8_192},
    )
    recorder.check(
        "KF6-CONTEXT-2",
        "knowledge_traces",
        "The G1 retrieval slice contains only G1-eligible traces and no full reference layout.",
        passed=all(
            all(trace["g1Eligible"] is True for trace in item["traces"])
            and "placements" not in item
            for item in g1_contexts.values()
        ),
        observed={
            key: [trace["traceId"] for trace in value["traces"]]
            for key, value in g1_contexts.items()
        },
        expected="only G1-eligible generalized traces",
    )
    recorder.check(
        "KF6-HELDOUT-1",
        "held_out_intent",
        "The post-contract held-out set meets the 95 percent command-family gate.",
        passed=held_out_result["passPercent"] >= 95.0,
        observed={
            "caseCount": held_out_result["caseCount"],
            "passPercent": held_out_result["passPercent"],
            "failedIds": [
                item["id"]
                for item in held_out_result["records"]
                if not item["passed"]
            ],
        },
        expected={"minimumPercent": 95.0},
    )
    recorder.check(
        "KF6-HELDOUT-2",
        "held_out_intent",
        "The held-out set is versioned, frozen, hashed, and includes a G1 qualification subset.",
        passed=(
            held_out["classification"] == "held_out_post_contract"
            and bool(held_out["frozenAtUtc"])
            and len(held_out["caseContentSha256"]) == 64
            and sum(item["scope"] == "g1" for item in held_out["cases"]) >= 12
        ),
        observed={
            "setId": held_out["setId"],
            "setVersion": held_out["setVersion"],
            "frozenAtUtc": held_out["frozenAtUtc"],
            "caseContentSha256": held_out["caseContentSha256"],
            "g1CaseCount": sum(
                item["scope"] == "g1" for item in held_out["cases"]
            ),
        },
        expected="versioned, frozen, SHA-256 bound, and at least 12 G1 cases",
    )
    recorder.equal(
        "KF6-PROVIDER-1",
        "provider_identity",
        "The deterministic baseline records the exact frozen Facility provider configuration.",
        {
            "provider": provider_metadata["provider"],
            "model": provider_metadata["model"],
            "reasoningEffort": provider_metadata["reasoningEffort"],
        },
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5-20250929",
            "reasoningEffort": None,
        },
    )
    return {
        "regressionVisible": deepcopy(evidence["regressionVisible"]),
        "goldTraceSet": {
            "traceSetId": evidence["goldTraces"]["traceSetId"],
            "traceSetVersion": evidence["goldTraces"]["traceSetVersion"],
            "traceContentSha256": evidence["goldTraces"]["traceContentSha256"],
            "traceCount": len(traces),
        },
        "heldOut": held_out_result,
        "providerConfiguration": provider_metadata,
        "stageContextMeasurements": {
            key: value["measurement"] for key, value in contexts.items()
        },
    }


def _g1_generation_checks(recorder: _Recorder, repo_root: Path) -> dict[str, Any]:
    """Qualify the first executable facility-and-departments capability."""

    tool_spec = g1_facility_generation_tool_spec()

    def schema_properties(value: Any) -> set[str]:
        result: set[str] = set()
        if isinstance(value, Mapping):
            properties = value.get("properties")
            if isinstance(properties, Mapping):
                result.update(str(key) for key in properties)
            for nested in value.values():
                result.update(schema_properties(nested))
        elif isinstance(value, list):
            for nested in value:
                result.update(schema_properties(nested))
        return result

    property_names = schema_properties(tool_spec["input_schema"])
    forbidden_geometry = {
        "x",
        "y",
        "z",
        "vertices",
        "boundary",
        "coordinates",
        "worldX",
        "worldZ",
        "transform",
        "routePoints",
    }
    recorder.check(
        "G1-1",
        "g1_generation",
        "The G1 Sage tool is closed and contains intent rather than geometry.",
        passed=(
            tool_spec["input_schema"].get("additionalProperties") is False
            and not (property_names & forbidden_geometry)
        ),
        observed={
            "toolName": tool_spec["name"],
            "forbiddenGeometryFields": sorted(property_names & forbidden_geometry),
        },
        expected={"forbiddenGeometryFields": []},
    )

    base_layout = create_layout_document(
        layout_id="fl-kf7-g1",
        display_name="Empty Qualification Facility",
        association={"siteId": "site-kf7", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "origin-kf7",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-kf7",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-kf7",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-26T00:00:00Z",
    )
    expected_labels = ["Receiving", "Machining", "Assembly", "Inspection"]
    runtime_root = repo_root / ".runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    fixed_clock = lambda: datetime(2026, 8, 26, 20, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(
        prefix="facility-kf7-g1-", dir=runtime_root
    ) as temporary_root:
        generation_root = Path(temporary_root) / "runs"

        def coordinator() -> FacilityGenerationCoordinator:
            return FacilityGenerationCoordinator(
                FacilityGenerationRunRepository(
                    generation_root, clock=fixed_clock
                ),
                feature_flags=FacilityLayoutFeatureFlags.all_enabled(),
                environ_provider=lambda: {},
                clock=fixed_clock,
            )

        started = coordinator().start_g1_run(
            tenant_id="tenant-kf7",
            site_id="site-kf7",
            workspace_id="workspace-kf7",
            layout_id=base_layout["layoutId"],
            user_id="reviewer-kf7",
            session_id="session-kf7",
            base_layout=base_layout,
            base_layout_revision=layout_revision(base_layout),
            envelope_request={
                "width": 100,
                "depth": 80,
                "sourceUnit": "m",
                "displayName": "Qualification Plant",
            },
            department_request={
                "count": 4,
                "labels": expected_labels,
                "proportions": [1, 2, 3, 4],
                "arrangement": "rows",
                "orientation": "horizontal",
            },
            execution_mode="authorized_draft_run",
            prototype_mode=True,
        )
        responses = [started]
        completed_stages = []
        response = started
        for expected_stage in FACILITY_GENERATION_STAGES:
            response = coordinator().continue_run(
                tenant_id="tenant-kf7",
                site_id="site-kf7",
                run_id=started["runId"],
                current_base_layout=base_layout,
                current_base_revision=layout_revision(base_layout),
            )
            responses.append(response)
            completed_stages.append(response.get("completedStageId"))
            if response.get("completedStageId") != expected_stage["stageId"]:
                break

        draft = response.get("draftLayout", {})
        plan = draft.get("extensions", {}).get("facilityPlan", {})
        labels = [item.get("label") for item in draft.get("zones", [])]
        non_department_counts = {
            "placements": len(draft.get("placements", [])),
            "routes": len(draft.get("routes", [])),
            "markings": len(draft.get("floorMarkings", [])),
            "utilities": len(draft.get("utilityNetworks", [])),
        }
        recorder.check(
            "G1-2",
            "g1_generation",
            "A restarted coordinator completes the frozen ten-stage graph once.",
            passed=(
                completed_stages
                == [item["stageId"] for item in FACILITY_GENERATION_STAGES]
                and response.get("status") == "complete"
                and len(response.get("receiptChain", [])) == 10
                and response.get("saveEligibility") == "eligible"
            ),
            observed={
                "completedStages": completed_stages,
                "receiptCount": len(response.get("receiptChain", [])),
                "status": response.get("status"),
                "saveEligibility": response.get("saveEligibility"),
            },
            expected={
                "completedStages": [
                    item["stageId"] for item in FACILITY_GENERATION_STAGES
                ],
                "receiptCount": 10,
                "status": "complete",
                "saveEligibility": "eligible",
            },
        )
        recorder.check(
            "G1-3",
            "g1_generation",
            "G1 preserves exact dimensions and labels without extra factory content.",
            passed=(
                plan.get("widthMeters") == 100.0
                and plan.get("depthMeters") == 80.0
                and labels == expected_labels
                and all(value == 0 for value in non_department_counts.values())
            ),
            observed={
                "widthMeters": plan.get("widthMeters"),
                "depthMeters": plan.get("depthMeters"),
                "labels": labels,
                "nonDepartmentCounts": non_department_counts,
            },
            expected={
                "widthMeters": 100.0,
                "depthMeters": 80.0,
                "labels": expected_labels,
                "nonDepartmentCounts": {
                    "placements": 0,
                    "routes": 0,
                    "markings": 0,
                    "utilities": 0,
                },
            },
        )
        validation = response.get("stageReceipt", {}).get("validation", {})
        proposal_validation = response.get("cumulativeProposal", {}).get(
            "validation", {}
        )
        recorder.check(
            "G1-4",
            "g1_generation",
            "Deterministic validation closes before Save becomes eligible.",
            passed=(
                validation.get("status") == "valid"
                and validation.get("findingIds") == []
                and proposal_validation.get("status") == "valid"
            ),
            observed={
                "stageValidation": validation,
                "proposalValidation": proposal_validation,
            },
            expected={"status": "valid", "findingIds": []},
        )
        response_sizes = [len(_canonical_bytes(item)) for item in responses]
        recorder.check(
            "G1-5",
            "g1_generation",
            "Every G1 response stays within the 16,384-byte runtime limit.",
            passed=max(response_sizes) <= 16_384,
            observed={"maximumResponseBytes": max(response_sizes)},
            expected={"maximumResponseBytesAtMost": 16_384},
        )
        restored = coordinator().undo_to_base(
            tenant_id="tenant-kf7",
            site_id="site-kf7",
            run_id=started["runId"],
        )
        recorder.check(
            "G1-6",
            "g1_generation",
            "Undo restores the byte-identical empty base and supersedes the chain.",
            passed=(
                _canonical_bytes(restored["restoredLayout"])
                == _canonical_bytes(base_layout)
                and len(restored["supersededReceiptIds"]) == 10
                and restored["run"]["status"] == "cancelled"
            ),
            observed={
                "restoredRevision": restored["restoredLayoutRevision"],
                "baseRevision": layout_revision(base_layout),
                "supersededReceiptCount": len(
                    restored["supersededReceiptIds"]
                ),
                "status": restored["run"]["status"],
            },
            expected={
                "restoredRevision": layout_revision(base_layout),
                "supersededReceiptCount": 10,
                "status": "cancelled",
            },
        )

    index_text = (repo_root / "static/index.html").read_text(encoding="utf-8")
    session_text = (repo_root / "static/facility_layout_session.js").read_text(
        encoding="utf-8"
    )
    transport_text = (repo_root / "static/facility_layout_transport.js").read_text(
        encoding="utf-8"
    )
    browser_markers = {
        "stagedGeneration": "_trainGenerateFacilityDepartmentsDraft" in index_text,
        "publicBridge": "__facilityLayoutAgentV1" in index_text,
        "draftInstall": "installGenerationDraft" in session_text,
        "explicitSave": "explicitApproval" in transport_text,
        "exactDiffBinding": "cumulativeDiffHash" in transport_text,
    }
    recorder.check(
        "G1-7",
        "g1_generation",
        "The browser uses the shared staged draft, explicit Save, and exact-diff path.",
        passed=all(browser_markers.values()),
        observed=browser_markers,
        expected={key: True for key in browser_markers},
    )
    return {
        "completedStageCount": len(completed_stages),
        "maximumResponseBytes": max(response_sizes),
        "departmentCount": len(labels),
        "browserMarkers": browser_markers,
    }


def _context_catalog_presentation_checks(
    recorder: _Recorder,
    repo_root: Path,
    fixture: Mapping[str, Any],
    semantic: Mapping[str, Any],
) -> None:
    digest = build_facility_analysis_digest(
        {"counts": {}},
        fixture["state"],
    )
    digest_bytes = _canonical_bytes(digest)
    recorder.equal(
        "CTX1",
        "context_compilation",
        "The analysis projection preserves all six department summaries.",
        len(digest["departmentSummaries"]),
        fixture["expected"]["departmentCount"],
    )
    recorder.check(
        "CTX2",
        "context_compilation",
        "The bounded prompt projection includes semantic, route, and process summaries without raw placements.",
        passed=(
            digest.get("requestProjection") == "facility_layout_analysis"
            and "facilitySemanticSummary" in digest
            and "routeNetworkSummary" in digest
            and "processRelationshipSummary" in digest
            and "placements" not in digest
            and len(digest_bytes) <= 32_768
        ),
        observed={
            "requestProjection": digest.get("requestProjection"),
            "keys": sorted(digest),
            "bytes": len(digest_bytes),
        },
        expected={"maximumBytes": 32_768, "rawPlacements": False},
    )

    catalog = build_private_local_asset_catalog(repo_root)
    catalog_state = {
        "identity": {
            "layoutId": "fl-semantic-catalog-audit",
            "displayName": "Semantic catalog audit",
            "revision": "8" * 64,
        },
        "assets": list(catalog),
        "zones": [],
        "placements": [],
        "routes": [],
        "floorMarkings": [],
        "processMaps": [],
        "processBindings": [],
    }
    semantic_catalog = build_facility_semantic_map(catalog_state)["assets"]
    unknown = [
        item["assetId"] for item in semantic_catalog
        if item["semanticType"] == "unknown"
        or item["semanticTypeEvidenceStatus"] == "unknown"
    ]
    recorder.check(
        "I1",
        "catalog_coverage",
        "Every current private Facility asset has at least inferred semantic meaning.",
        passed=len(catalog) >= 148 and len(semantic_catalog) == len(catalog)
        and not unknown,
        observed={
            "catalogAssets": len(catalog),
            "semanticAssets": len(semantic_catalog),
            "unknownAssetIds": unknown,
        },
        expected={"minimumAssets": 148, "unknownAssetIds": []},
    )
    evidence_statuses = Counter(
        item["semanticTypeEvidenceStatus"] for item in semantic_catalog
    )
    recorder.equal(
        "I2",
        "catalog_coverage",
        "Catalog priors remain inferred/authored rather than silently validated.",
        sorted(evidence_statuses),
        ["inferred"],
    )
    fixture_types = {
        item["assetId"]: item["semanticType"]
        for item in semantic["assets"]
    }
    recorder.equal(
        "I3",
        "semantic_understanding",
        "Golden assets resolve to operationally distinct semantic types.",
        fixture_types,
        {
            "asset-rack": "pallet_rack",
            "asset-monitor": "computer_or_peripheral",
            "asset-cnc": "cnc_machining_center",
            "asset-robot": "industrial_robot",
            "asset-forklift": "forklift_or_lift_truck",
            "asset-bench": "workbench_or_table",
            "asset-inspection": "inspection_equipment",
        },
    )
    recorder.equal(
        "I4",
        "deterministic_geometry",
        "The stacked monitor is retained semantically but excluded from floor occupancy.",
        {
            "semanticPlacementCount": len(semantic["placements"]),
            "floorContactCount": semantic["facilitySummary"]["spatialMetrics"][
                "physicalFloorContact"
            ]["placementCount"],
        },
        {
            "semanticPlacementCount": fixture["expected"][
                "totalPlacementCount"
            ],
            "floorContactCount": fixture["expected"]["floorPlacementCount"],
        },
    )

    chart_expectations = {
        "Show a Pareto chart, not a bar chart.": "pareto",
        "Show a heatmap of asset categories by department.": "heatmap",
        "Give me a pie chart by department area.": "pie",
        "Show a histogram of aisle widths.": "histogram",
        "Create a scatter plot of area versus footprint.": "scatter",
    }
    recorder.equal(
        "J2",
        "rich_presentation",
        "Explicit chart types survive natural-language corrections.",
        {
            prompt: requested_visualization_type(prompt)
            for prompt in chart_expectations
        },
        chart_expectations,
    )
    recorder.check(
        "J3",
        "rich_presentation",
        "The trusted chart renderer supports the required Facility chart family.",
        passed={
            "bar",
            "pie",
            "donut",
            "heatmap",
            "histogram",
            "pareto",
            "scatter",
            "line",
            "kpi",
        } <= VISUALIZATION_TYPES,
        observed=sorted(VISUALIZATION_TYPES),
        expected="all required chart types",
    )


def _source_bindings(repo_root: Path) -> list[dict[str, Any]]:
    result = []
    for relative_text in SOURCE_PATHS:
        path = repo_root / relative_text
        if not path.is_file():
            result.append({
                "path": relative_text,
                "available": False,
                "sha256": None,
                "byteSize": None,
            })
            continue
        raw = path.read_bytes()
        result.append({
            "path": relative_text,
            "available": True,
            "sha256": _sha256(raw),
            "byteSize": len(raw),
        })
    return result


def evaluate_sage_facility_layout_intelligence(
    repo_root: str | Path,
    *,
    fixture_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate the frozen deterministic Facility intelligence contract."""

    root = Path(repo_root).resolve()
    fixture_file = (
        Path(fixture_path).resolve()
        if fixture_path is not None
        else root / DEFAULT_FIXTURE
    )
    fixture_raw_before = fixture_file.read_bytes()
    fixture = _read_json(fixture_file)
    source_state = fixture.get("state")
    if not isinstance(source_state, Mapping):
        raise ValueError("golden facility fixture requires a state object")
    state_before = _canonical_bytes(source_state)
    recorder = _Recorder()

    semantic_one = build_facility_semantic_map(source_state)
    semantic_two = build_facility_semantic_map(deepcopy(source_state))
    semantic_bytes = _canonical_bytes(semantic_one)
    state_sha256_before = _sha256(state_before)
    state_sha256_after = _sha256(_canonical_bytes(source_state))
    semantic_sha256_one = _sha256(semantic_bytes)
    semantic_sha256_two = _sha256(_canonical_bytes(semantic_two))
    fixture_sha256_before = _sha256(fixture_raw_before)
    fixture_sha256_after = _sha256(fixture_file.read_bytes())
    recorder.equal(
        "SAFE1",
        "read_only_safety",
        "Semantic projection does not mutate the frozen source state.",
        state_sha256_after,
        state_sha256_before,
    )
    recorder.equal(
        "SAFE2",
        "read_only_safety",
        "Semantic projection is deterministic for identical revision-bound input.",
        semantic_sha256_two,
        semantic_sha256_one,
    )
    recorder.equal(
        "SAFE3",
        "read_only_safety",
        "Evaluation leaves the checked-in fixture byte-identical.",
        fixture_sha256_after,
        fixture_sha256_before,
    )

    _semantic_fixture_checks(recorder, fixture, semantic_one)
    _route_process_checks(recorder, fixture, semantic_one)
    _synthetic_edge_checks(recorder, source_state)
    _advanced_semantic_checks(recorder, source_state, semantic_one)
    _provenance_checks(recorder, source_state, semantic_one)
    _fit_checks(recorder, root)
    _tool_skill_checks(recorder, root)
    available_tools = {
        item["name"] for item in facility_layout_read_tool_specs()
    } | {
        facility_layout_preview_tool_spec()["name"],
        facility_layout_move_tool_spec()["name"],
        g1_facility_generation_tool_spec()["name"],
        CHAT_VISUALIZATION_TOOL,
        CHAT_TABLE_TOOL,
    }
    _action_and_continuity_checks(
        recorder,
        {
            item["name"] for item in facility_layout_read_tool_specs()
        },
    )
    _orchestration_policy_checks(
        recorder,
        {
            item["name"] for item in facility_layout_read_tool_specs()
        },
    )
    case_matrix = _case_matrix_checks(
        recorder,
        root,
        available_tools,
    )
    knowledge_trace_evaluation = _knowledge_trace_checks(recorder, root)
    g1_generation_evaluation = _g1_generation_checks(recorder, root)
    _context_catalog_presentation_checks(
        recorder,
        root,
        fixture,
        semantic_one,
    )

    ids = [item["id"] for item in recorder.records]
    duplicate_ids = sorted(
        check_id for check_id, count in Counter(ids).items() if count > 1
    )
    recorder.equal(
        "META1",
        "tool_contracts",
        "Every evaluation assertion has a stable unique ID.",
        duplicate_ids,
        [],
    )

    gate_results = []
    for gate, threshold in GATE_THRESHOLDS.items():
        records = [
            item for item in recorder.records if item["gate"] == gate
        ]
        passed_count = sum(1 for item in records if item["passed"])
        percent = (
            round(passed_count / len(records) * 100.0, 6)
            if records else 0.0
        )
        gate_results.append({
            "gate": gate,
            "thresholdPercent": threshold,
            "checkCount": len(records),
            "passedCount": passed_count,
            "failedCount": len(records) - passed_count,
            "passPercent": percent,
            "status": "passed" if percent >= threshold else "failed",
        })
    total = len(recorder.records)
    passed_total = sum(1 for item in recorder.records if item["passed"])
    overall_percent = round(passed_total / total * 100.0, 6) if total else 0.0
    critical_failures = [
        item["id"]
        for item in recorder.records
        if item["severity"] == "critical" and not item["passed"]
    ]
    failed_gates = [
        item["gate"] for item in gate_results if item["status"] != "passed"
    ]
    source_bindings = _source_bindings(root)
    missing_sources = [
        item["path"] for item in source_bindings if not item["available"]
    ]
    status = (
        "passed"
        if not critical_failures
        and not failed_gates
        and not missing_sources
        and overall_percent >= 95.0
        else "failed"
    )
    return {
        "evaluationContractVersion": EVALUATION_CONTRACT_VERSION,
        "status": status,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "gitCommit": _git_commit(root),
        "providerCalls": 0,
        "networkCalls": 0,
        "evaluationLevel": "deterministic_contract_and_oracle",
        "claimBoundary": {
            "proved": [
                "revision-bound semantic projection",
                "exact deterministic geometry and units",
                "route and authored process relationship derivation",
                "layout provenance and bounded fit behavior",
                "read-only and preview tool boundaries",
                "intent and follow-up routing contracts",
                "current private asset semantic coverage",
                "bounded prompt-context compilation",
                "chart-type request and renderer contracts",
            ],
            "notProved": [
                "quality of arbitrary future provider prose",
                (
                    "real-provider tool choice across every paraphrase; one "
                    "source-bound shadow case is verified separately"
                ),
                (
                    "direct Sage execution of ribbon commands marked ui_only; "
                    "those remain semantically described and fail closed"
                ),
                "regulatory compliance",
                "production capacity without operational data",
                "elapsed-duration soak behavior",
            ],
            "providerShadowEvaluationRequiredFor": (
                "Natural-language answer quality and real-provider tool-use "
                "rates during pilot shadow mode."
            ),
        },
        "snapshot": {
            "snapshotId": fixture.get("snapshotId"),
            "fixturePath": str(fixture_file.relative_to(root)).replace(
                "\\", "/"
            ),
            "fixtureSha256": fixture_sha256_before,
            "sourceStateSha256": state_sha256_before,
            "semanticProjectionSha256": semantic_sha256_one,
            "sourceMutationDetected": (
                state_sha256_after != state_sha256_before
            ),
        },
        "summary": {
            "checkCount": total,
            "passedCount": passed_total,
            "failedCount": total - passed_total,
            "passPercent": overall_percent,
            "criticalFailureCount": len(critical_failures),
            "criticalFailureIds": critical_failures,
            "failedGates": failed_gates,
            "missingSourceBindings": missing_sources,
            "structuralConversationCaseCount": len(
                case_matrix["cases"]
            ),
        },
        "gates": gate_results,
        "checks": recorder.records,
        "conversationMatrix": case_matrix,
        "knowledgeTraceEvaluation": knowledge_trace_evaluation,
        "g1GenerationEvaluation": g1_generation_evaluation,
        "sourceBindings": source_bindings,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


__all__ = [
    "DEFAULT_CASES",
    "DEFAULT_FIXTURE",
    "EVALUATION_CONTRACT_VERSION",
    "GATE_THRESHOLDS",
    "evaluate_sage_facility_layout_intelligence",
]
