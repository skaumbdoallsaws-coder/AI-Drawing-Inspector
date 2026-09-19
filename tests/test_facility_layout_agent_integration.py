"""Production integration guards for P9 Facility Layout agent planning."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import server
from ai_inspector.facility_layout.asset_placement import (
    compile_asset_placement_program,
)
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import (
    LOCAL_ASSET_CATALOG,
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.chat_context import (
    build_facility_analysis_digest,
    build_zone_inventory_digest,
    build_zone_inventory_markdown,
    is_complete_zone_table_request,
    is_zone_inventory_request,
)
from ai_inspector.facility_layout.chat_intent import (
    classify_facility_request_kind,
    is_precise_facility_translation_request,
    parse_complete_facility_generation_request,
    parse_facility_department_repartition_request,
    parse_precise_facility_translation,
    requested_facility_metric,
    requested_facility_spatial_analyses,
    resolve_facility_pending_follow_up,
    resolve_facility_layout_turn,
)
from ai_inspector.facility_layout.circulation import (
    compile_primary_circulation_operations,
    parse_circulation_turn,
)
from ai_inspector.facility_layout.design_intent import (
    FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
)
from ai_inspector.facility_layout.cell_composition import (
    compile_cell_composition_program,
)
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.semantic_plan import (
    SEMANTIC_FACILITY_MOVE_TOOL,
    SEMANTIC_FACILITY_PREVIEW_TOOL,
    compile_semantic_facility_plan,
)
from ai_inspector.facility_layout.semantic_model import (
    build_facility_semantic_map,
)
from ai_inspector.facility_layout.orchestration import (
    FacilityPendingOperationStore,
    build_facility_orchestration_plan,
    facility_orchestration_trace,
)


READ_TOOLS = {
    "search_industrial_assets",
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_findings",
    "inspect_process_bindings",
    "inspect_facility_semantics",
    "inspect_pattern_provenance",
    "inspect_cell_layout_provenance",
    "analyze_facility_spatial",
    "analyze_facility_fit",
}
PRESENTATION_TOOLS = {
    server.CHAT_VISUALIZATION_TOOL,
    server.CHAT_TABLE_TOOL,
}
INSPECT_TOOLS = {
    "search_industrial_assets",
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_findings",
    "inspect_process_bindings",
    "inspect_facility_semantics",
    "inspect_pattern_provenance",
    "inspect_cell_layout_provenance",
}
MEASURE_TOOLS = {
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_semantics",
    "analyze_facility_spatial",
    "analyze_facility_fit",
}
COMPARE_TOOLS = {
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_process_bindings",
    "inspect_facility_semantics",
    "inspect_pattern_provenance",
    "inspect_cell_layout_provenance",
    "analyze_facility_spatial",
    "analyze_facility_fit",
}
RECOMMEND_TOOLS = {
    "search_industrial_assets",
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_findings",
    "inspect_process_bindings",
    "inspect_facility_semantics",
    "analyze_facility_spatial",
    "analyze_facility_fit",
}
RENDER_TOOLS = {
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_semantics",
    "analyze_facility_spatial",
    "analyze_facility_fit",
}
EXACT_TRANSFORM_TOOLS = {
    "inspect_facility_entities",
    "inspect_facility_semantics",
    "analyze_facility_spatial",
}
ANALYSIS_TOOLS = READ_TOOLS | PRESENTATION_TOOLS
TABLE_INSPECT_TOOLS = INSPECT_TOOLS | {server.CHAT_TABLE_TOOL}
TABLE_COMPARE_TOOLS = COMPARE_TOOLS | {server.CHAT_TABLE_TOOL}
CHART_RENDER_TOOLS = RENDER_TOOLS | {server.CHAT_VISUALIZATION_TOOL}


@pytest.fixture()
def facility_host(tmp_path, monkeypatch):
    host = LocalFacilityLayoutHost(tmp_path / "facility")
    host.ensure_bootstrap()
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", host)
    try:
        yield host
    finally:
        host.close()


def _current(host: LocalFacilityLayoutHost):
    return host.service.get_layout(
        host.principal(),
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )


def _provider_response(*blocks):
    return SimpleNamespace(
        content=list(blocks),
        usage=SimpleNamespace(
            input_tokens=20,
            output_tokens=12,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _provider_text(text):
    return SimpleNamespace(type="text", text=text)


def _provider_tool(name, args):
    return SimpleNamespace(type="tool_use", name=name, input=args)


def _facility_http_request():
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/agent/chat",
        "raw_path": b"/api/agent/chat",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    })


def _facility_analysis_provider_tools():
    return server.build_native_tool_specs(
        "deviation-analyst",
        allowed_tools=ANALYSIS_TOOLS,
    )


def _facility_generation_provider_tools():
    return server.build_native_tool_specs(
        "deviation-analyst",
        allowed_tools=ANALYSIS_TOOLS | {
            server.G1_FACILITY_GENERATION_TOOL,
            SEMANTIC_FACILITY_PREVIEW_TOOL,
        },
    )


def _g1_provider_args(*, width=100, depth=80, labels=None):
    names = labels or [
        "Receiving and Stores",
        "Machining",
        "Assembly",
        "Inspection and Shipping",
    ]
    return {
        "facility_envelope": {
            "width": width,
            "depth": depth,
            "source_unit": "m",
            "display_name": "Facility",
            "grid_size": None,
        },
        "departments": {
            "count": len(names),
            "labels": names,
            "proportions": None,
            "arrangement": "deterministic_grid",
            "orientation": "auto",
        },
        "execution_mode": "authorized_draft_run",
    }


def _circulation_department_layout():
    layout = create_layout_document(
        layout_id="fl-circulation-agent",
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
        created_at="2026-08-27T00:00:00Z",
    )
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "Circulation Plant",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {
            "count": 4,
            "labels": ["Receiving", "Machining", "Assembly", "Shipping"],
            "proportions": [0.25, 0.25, 0.25, 0.25],
            "arrangement": "columns",
            "orientation": "horizontal",
        },
    )
    return apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _circulation_point_crossing_layout():
    layout = create_layout_document(
        layout_id="fl-circulation-g23-agent",
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
        created_at="2026-08-28T00:00:00Z",
    )
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "G2.3 Circulation Plant",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
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
    departments = compile_g1_department_operations(
        layout,
        {
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
    )
    layout = apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    for prompt in (
        "Add a 4 m material aisle from Inbound to Dispatch.",
        "Add a 2 m pedestrian walkway from North Center to South Center.",
    ):
        parsed = parse_circulation_turn(prompt, layout)
        compiled = compile_primary_circulation_operations(
            layout,
            parsed["request"],
        )
        layout = apply_facility_layout_operations(
            layout,
            compiled["operations"],
            base_revision=layout_revision(layout),
        )["document"]
    return layout


def _circulation_chat_context(layout, obstacle_context=None):
    context = {
        "facility_layout_state": {"identity": {"layoutId": layout["layoutId"]}},
        "facility_layout_evidence": {},
        "facility_layout_digest": {},
        "_facility_layout_document": copy.deepcopy(layout),
        "_facility_layout_department_program": {
            "source": "active_generation_run",
            "run_id": "fgr-circulation-agent",
        },
    }
    if obstacle_context is not None:
        context["_facility_layout_obstacle_context"] = copy.deepcopy(
            obstacle_context
        )
    return context


def _semantic_zone_observation(
    *,
    zone_id="zone-a",
    label="Assembly Cell A01",
    area=62.31562,
    footprint_status="unknown",
):
    return {
        "tool": "inspect_facility_semantics",
        "arguments": {"view": "zones", "ids": [zone_id]},
        "status": "succeeded",
        "result": {
            "authoritative": True,
            "records": [{
                "zoneId": zone_id,
                "label": label,
                "areaSquareMeters": area,
                "areaSquareFeet": area * 10.76391041671,
                "areaEvidenceStatus": "derived",
                "placementCount": 8,
                "childZoneCount": 0,
                "hierarchyDepth": 1,
                "assetCategories": {},
                "assetOperationalRoles": {},
                "grossAssetFootprintAreaSquareMeters": 0.0,
                "grossFootprintCoveragePercent": 0.0,
                "grossFootprintMetricEvidenceStatus": footprint_status,
                "spatialMetrics": {
                    "grossAreaSquareMeters": area,
                    "grossAreaSquareFeet": area * 10.76391041671,
                    "physicalFloorContact": {
                        "netUnionAreaSquareMeters": 0.0,
                        "coveragePercent": 0.0,
                        "evidenceStatus": footprint_status,
                    },
                    "clearanceReservedArea": {
                        "authoritativeUnionAreaSquareMeters": 0.0,
                        "evidenceStatus": "derived",
                    },
                    "routeReservedArea": {
                        "authoritativeCorridorUnionAreaSquareMeters": 0.0,
                        "evidenceStatus": "derived",
                    },
                },
            }],
        },
    }


def _semantic_table_response(
    *,
    zone_id="zone-a",
    area="62.316",
    footprint="UNKNOWN",
):
    return _provider_response(_provider_tool(
        server.CHAT_TABLE_TOOL,
        {
            "title": "Cell evidence",
            "subtitle": None,
            "columns": [
                {"label": "Cell", "unit": None},
                {"label": "Gross area", "unit": "m2"},
                {"label": "Physical footprint evidence", "unit": None},
            ],
            "rows": [{
                "cells": ["Assembly Cell A01", area, footprint],
                "entity_id": zone_id,
            }],
        },
    ))


def test_facility_table_grounding_rejects_unknown_metric_upgrade():
    issues = server._facility_table_grounding_issues(
        _semantic_table_response(footprint="15.913 derived"),
        [_semantic_zone_observation()],
    )

    assert [item["code"] for item in issues] == [
        "facility_unknown_footprint_upgraded"
    ]


def test_facility_table_grounding_accepts_rounded_derived_area_and_unknown():
    assert server._facility_table_grounding_issues(
        _semantic_table_response(),
        [_semantic_zone_observation()],
    ) == []


def test_facility_table_grounding_validates_derived_footprint_number():
    response = _semantic_table_response(footprint="15.913 derived")
    observation = _semantic_zone_observation(footprint_status="derived")
    record = observation["result"]["records"][0]
    record["grossAssetFootprintAreaSquareMeters"] = 15.912736
    record["grossFootprintCoveragePercent"] = 25.53571
    record["spatialMetrics"]["physicalFloorContact"].update({
        "netUnionAreaSquareMeters": 15.912736,
        "coveragePercent": 25.53571,
    })

    assert server._facility_table_grounding_issues(
        response,
        [observation],
    ) == []

    response.content[0].input["rows"][0]["cells"][2] = "19.750 derived"
    assert [
        item["code"]
        for item in server._facility_table_grounding_issues(
            response,
            [observation],
        )
    ] == ["facility_numeric_claim_not_observed"]


def test_facility_table_grounding_rejects_derived_evidence_downgrade():
    observation = _semantic_zone_observation(footprint_status="derived")
    observation["result"]["records"][0]["areaEvidenceStatus"] = "derived"
    response = _provider_response(_provider_tool(
        server.CHAT_TABLE_TOOL,
        {
            "title": "Cell evidence",
            "subtitle": None,
            "columns": [
                {"label": "Cell", "unit": None},
                {"label": "Gross area", "unit": "m2"},
                {"label": "Area evidence class", "unit": None},
                {"label": "Physical footprint evidence", "unit": None},
            ],
            "rows": [{
                "cells": [
                    "Assembly Cell A01",
                    "62.316",
                    "UNKNOWN",
                    "UNKNOWN",
                ],
                "entity_id": "zone-a",
            }],
        },
    ))

    assert [
        item["code"]
        for item in server._facility_table_grounding_issues(
            response,
            [observation],
        )
    ] == [
        "facility_area_evidence_status_mismatch",
        "facility_footprint_evidence_status_mismatch",
    ]


def test_facility_table_grounding_preserves_authored_layout_provenance():
    observation = _semantic_zone_observation(footprint_status="derived")
    observation["result"]["records"][0]["layoutProvenance"] = {
        "command": "create_cell_group",
        "authoredStrategy": None,
        "evidenceStatus": "authored",
    }

    def response(provenance):
        return _provider_response(_provider_tool(
            server.CHAT_TABLE_TOOL,
            {
                "title": "Cell provenance",
                "subtitle": None,
                "columns": [
                    {"label": "Cell", "unit": None},
                    {"label": "Layout strategy provenance", "unit": None},
                ],
                "rows": [{
                    "cells": ["Assembly Cell A01", provenance],
                    "entity_id": "zone-a",
                }],
            },
        ))

    assert [
        item["code"]
        for item in server._facility_table_grounding_issues(
            response("authored (strategy not persisted)"),
            [observation],
        )
    ] == ["facility_layout_provenance_command_mismatch"]
    assert server._facility_table_grounding_issues(
        response(
            "authored command: create_cell_group; strategy not persisted"
        ),
        [observation],
    ) == []


def test_facility_table_grounding_rejects_unobserved_numeric_claim():
    issues = server._facility_table_grounding_issues(
        _semantic_table_response(area="91.25"),
        [_semantic_zone_observation()],
    )

    assert [item["code"] for item in issues] == [
        "facility_numeric_claim_not_observed"
    ]


def test_facility_provider_corrects_unsupported_table_before_return(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(_provider_tool(
        "inspect_facility_semantics",
        {"view": "zones", "query": "Assembly Cell A01"},
    ))
    invoked = []

    async def fake_read(*_args, **kwargs):
        observation = _semantic_zone_observation()
        encoded = server._canonical_facility_tool_result(observation)
        return (
            [observation],
            [{
                "round": kwargs["round_index"],
                "tool": "inspect_facility_semantics",
                "status": "succeeded",
                "revision": current["revision"],
                "resultBytes": len(encoded),
                "resultSha256": "a" * 64,
                "latencyMs": 0.1,
            }],
            kwargs["remaining_calls"] - 1,
            kwargs["remaining_bytes"] - len(encoded),
            False,
        )

    async def fake_invoke(_client, **kwargs):
        invoked.append(copy.deepcopy(kwargs))
        if len(invoked) == 1:
            return _semantic_table_response(footprint="15.913 derived")
        return _semantic_table_response(footprint="UNKNOWN")

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setattr(
        server,
        "_execute_facility_layout_provider_reads",
        fake_read,
    )
    response, trace, usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Show exact cell evidence in a table.",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {"mode": "read_only_analysis"},
            },
            system_prompt="Use only authoritative observations.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Show evidence."}],
            }],
            provider_tools=_facility_analysis_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=server.CHAT_TABLE_TOOL,
        )
    )

    assert len(invoked) == 2
    assert "facility_presentation_validation" in json.dumps(
        invoked[1]["messages"]
    )
    assert trace[0]["presentationCorrectionCount"] == 1
    assert trace[0]["presentationGroundingStatus"] == "passed"
    assert server._facility_table_grounding_issues(
        response,
        [_semantic_zone_observation()],
    ) == []
    assert usage["calls"] == 3
    assert _current(facility_host)["revision"] == current["revision"]


def test_facility_provider_fails_closed_after_repeated_unsupported_table(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(_provider_tool(
        "inspect_facility_semantics",
        {"view": "zones", "query": "Assembly Cell A01"},
    ))

    async def fake_read(*_args, **kwargs):
        observation = _semantic_zone_observation()
        encoded = server._canonical_facility_tool_result(observation)
        return (
            [observation],
            [{
                "round": kwargs["round_index"],
                "tool": "inspect_facility_semantics",
                "status": "succeeded",
                "revision": current["revision"],
                "resultBytes": len(encoded),
                "resultSha256": "a" * 64,
                "latencyMs": 0.1,
            }],
            kwargs["remaining_calls"] - 1,
            kwargs["remaining_bytes"] - len(encoded),
            False,
        )

    async def fake_invoke(_client, **_kwargs):
        return _semantic_table_response(footprint="15.913 derived")

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setattr(
        server,
        "_execute_facility_layout_provider_reads",
        fake_read,
    )
    response, trace, _usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Show exact cell evidence in a table.",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {"mode": "read_only_analysis"},
            },
            system_prompt="Use only authoritative observations.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Show evidence."}],
            }],
            provider_tools=_facility_analysis_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=server.CHAT_TABLE_TOOL,
        )
    )

    assert trace[0]["presentationGroundingStatus"] == "failed_closed"
    assert server.extract_provider_tool_calls(
        response, "deviation-analyst"
    ) == []
    assert "could not be grounded" in server._accumulate_response_text(
        response
    )
    assert _current(facility_host)["revision"] == current["revision"]


def test_server_executes_facility_read_before_provider_synthesizes_answer(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    before_revision = current["revision"]
    messages = [{
        "role": "user",
        "content": [{"type": "text", "text": "Analyze departments."}],
    }]
    initial = _provider_response(_provider_tool(
        "inspect_facility_semantics",
        {"view": "overview"},
    ))
    captured = []

    async def fake_invoke(_client, **kwargs):
        captured.append(copy.deepcopy(kwargs))
        return _provider_response(_provider_text(
            "The answer uses the authoritative semantic overview."
        ))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    request = server.AgentChatRequest(
        message="Analyze the six departments without changing anything.",
        agent_type="deviation-analyst",
        session_id="facility-read-loop-test",
    )
    ctx = {
        "facility_layout_state": facility_host.agent_runtime.resolve_context(
            facility_host.principal(),
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=before_revision,
        ).state,
    }

    response, trace, usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=request,
            http_request=_facility_http_request(),
            ctx=ctx,
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {"mode": "read_only_analysis"},
            },
            system_prompt="Analyze trusted Facility data.",
            messages=messages,
            provider_tools=_facility_analysis_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=None,
        )
    )

    assert server._accumulate_response_text(response).startswith("The answer")
    assert [item["tool"] for item in trace] == [
        "inspect_facility_semantics"
    ]
    assert trace[0]["status"] == "succeeded"
    assert trace[0]["revision"] == before_revision
    assert len(trace[0]["resultSha256"]) == 64
    assert len(captured) == 1
    sent = json.dumps(captured[0]["messages"])
    assert "trusted_facility_tool_results" in sent
    trusted_text = captured[0]["messages"][-1]["content"][-1]["text"]
    assert '"authoritative":true' in trusted_text
    assert usage == {
        "calls": 2,
        "input": 40,
        "output": 24,
        "cache_read": 0,
        "cache_write": 0,
    }
    assert _current(facility_host)["revision"] == before_revision


def test_facility_read_loop_reissues_deferred_generation_action(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(
        _provider_tool(
            server.G1_FACILITY_GENERATION_TOOL,
            _g1_provider_args(),
        ),
        _provider_tool("inspect_facility_semantics", {"view": "overview"}),
    )
    observation = {
        "tool": "inspect_facility_semantics",
        "arguments": {"view": "overview"},
        "status": "succeeded",
        "authoritative": True,
        "revision": current["revision"],
        "result": {"view": "overview", "records": []},
    }
    invoked = []
    responses = [
        _provider_response(_provider_text(
            "The current state has been inspected."
        )),
        _provider_response(_provider_tool(
            server.G1_FACILITY_GENERATION_TOOL,
            _g1_provider_args(width=100, depth=100),
        )),
    ]

    async def fake_read(*_args, **kwargs):
        encoded = server._canonical_facility_tool_result(observation)
        return (
            [copy.deepcopy(observation)],
            [{
                "round": kwargs["round_index"],
                "tool": "inspect_facility_semantics",
                "status": "succeeded",
                "revision": current["revision"],
                "resultBytes": len(encoded),
                "resultSha256": "a" * 64,
                "latencyMs": 0.1,
            }],
            kwargs["remaining_calls"] - 1,
            kwargs["remaining_bytes"] - len(encoded),
            False,
        )

    async def fake_invoke(_client, **kwargs):
        invoked.append(copy.deepcopy(kwargs))
        return responses.pop(0)

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setattr(
        server,
        "_execute_facility_layout_provider_reads",
        fake_read,
    )
    response, trace, usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message=(
                    "Create a new 100 m by 100 m facility and divide it into "
                    "four equal departments."
                ),
                agent_type="deviation-analyst",
                session_id="facility-deferred-action-test",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-generation"},
                "runtime_tool_policy": {
                    "mode": "semantic_generation",
                    "orchestration": {},
                },
            },
            system_prompt="Use deterministic Facility tools.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Create the facility."}],
            }],
            provider_tools=_facility_generation_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=None,
        )
    )

    calls = server.extract_provider_tool_calls(response, "deviation-analyst")
    assert [call["name"] for call in calls] == [
        server.G1_FACILITY_GENERATION_TOOL
    ]
    assert calls[0]["args"]["facility_envelope"]["depth"] == 100
    assert len(invoked) == 2
    assert invoked[1]["required_tool_name"] == (
        server.G1_FACILITY_GENERATION_TOOL
    )
    assert [tool["name"] for tool in invoked[1]["tools"]] == [
        server.G1_FACILITY_GENERATION_TOOL
    ]
    assert "deferred_for_authoritative_reads" in json.dumps(
        invoked[1]["messages"]
    )
    assert trace[-1]["deferredActionReissued"] == (
        server.G1_FACILITY_GENERATION_TOOL
    )
    assert usage["calls"] == 3
    assert _current(facility_host)["revision"] == current["revision"]


def test_facility_design_read_loop_preserves_exact_deferred_update(
    monkeypatch,
):
    design_ctx = _facility_design_context()
    update_args = {
        "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
        "operation": "add_geometry_locks",
        "target_labels": ["Main Boulevard"],
    }
    initial = _provider_response(
        _provider_tool(
            server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
            update_args,
        ),
        _provider_tool(
            server.INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
            {
                "brief_id": "fdbf-active",
                "brief_revision": "a" * 64,
            },
        ),
    )
    observation = {
        "tool": server.INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
        "arguments": {},
        "status": "succeeded",
        "authoritative": True,
        "revision": "a" * 64,
        "result": {
            "briefId": "fdbf-active",
            "briefRevision": "a" * 64,
        },
    }
    invoked = []

    async def fake_read(*_args, **kwargs):
        encoded = server._canonical_facility_tool_result(observation)
        return (
            [copy.deepcopy(observation)],
            [{
                "round": kwargs["round_index"],
                "tool": server.INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
                "status": "succeeded",
                "revision": "a" * 64,
                "resultBytes": len(encoded),
                "resultSha256": "c" * 64,
                "latencyMs": 0.1,
            }],
            kwargs["remaining_calls"] - 1,
            kwargs["remaining_bytes"] - len(encoded),
            False,
        )

    async def fake_invoke(_client, **kwargs):
        invoked.append(copy.deepcopy(kwargs))
        return _provider_response(_provider_text("The brief is ready."))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setattr(
        server,
        "_execute_facility_layout_provider_reads",
        fake_read,
    )
    response, trace, usage, deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Keep the current Main Boulevard fixed too.",
                agent_type="deviation-analyst",
                session_id="facility-design-deferred-update-test",
            ),
            http_request=_facility_http_request(),
            ctx=design_ctx,
            skill_prompt_plan=_facility_design_prompt_plan(
                "update_and_preview"
            ),
            system_prompt="Use deterministic Facility design tools.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Keep it fixed."}],
            }],
            provider_tools=server.facility_design_agent_tool_specs(
                apply_enabled=True
            ),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=None,
        )
    )

    assert server._accumulate_response_text(response) == "The brief is ready."
    assert deferred == [{
        "name": server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        "args": update_args,
    }]
    assert trace[-1]["deferredActionPreserved"] == [
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL
    ]
    assert len(invoked) == 1
    assert usage["calls"] == 2


def test_facility_provider_read_loop_is_bounded_to_two_rounds(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(_provider_tool(
        "inspect_facility_semantics",
        {"view": "overview"},
    ))
    provider_rounds = []

    async def fake_invoke(_client, **kwargs):
        provider_rounds.append(kwargs)
        if len(provider_rounds) == 1:
            return _provider_response(_provider_tool(
                "inspect_facility_semantics",
                {"view": "departments", "pageSize": 6},
            ))
        return _provider_response(_provider_text("Two bounded reads used."))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    response, trace, _usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Compare the departments.",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {"mode": "read_only_analysis"},
            },
            system_prompt="Analyze.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Compare."}],
            }],
            provider_tools=_facility_analysis_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=None,
        )
    )

    assert server._accumulate_response_text(response) == (
        "Two bounded reads used."
    )
    assert [item["round"] for item in trace] == [1, 2]
    assert len(provider_rounds) == 2
    assert all(item["status"] == "succeeded" for item in trace)


def test_facility_required_evidence_fails_closed_before_synthesis(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(_provider_text(
        "The narrowest aisle is definitely 3.7 m."
    ))
    calls = []

    async def fake_invoke(_client, **kwargs):
        calls.append(kwargs)
        return _provider_response(_provider_text(
            "I still did not call the required observation."
        ))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    plan = build_facility_orchestration_plan(
        operation_intent="measure",
        action_mode="READ_ONLY",
        available_read_tools=READ_TOOLS,
        presentation_tools=PRESENTATION_TOOLS,
        preview_tool_name=SEMANTIC_FACILITY_PREVIEW_TOOL,
        move_tool_name=SEMANTIC_FACILITY_MOVE_TOOL,
        spatial_analyses=("route_widths",),
    )
    response, trace, _usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Which rack aisle is narrowest?",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {
                    "mode": "read_only_analysis",
                    "orchestration": plan,
                },
            },
            system_prompt="Measure from authoritative observations.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Measure it."}],
            }],
            provider_tools=server.build_native_tool_specs(
                "deviation-analyst",
                allowed_tools=MEASURE_TOOLS,
            ),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=None,
        )
    )

    text_result = server._accumulate_response_text(response)
    assert "could not obtain the required authoritative" in text_result
    assert "3.7" not in text_result
    assert trace == []
    assert calls[0]["required_tool_name"] == "analyze_facility_spatial"
    assert _current(facility_host)["revision"] == current["revision"]


def test_facility_oversized_read_is_narrowed_without_user_confirmation(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    calls = []

    def fake_read_tool(
        _principal,
        *,
        tool_name,
        arguments,
        **_kwargs,
    ):
        calls.append((tool_name, copy.deepcopy(arguments)))
        if len(calls) == 1:
            raise server.FacilityLayoutAgentRuntimeError(
                "facility_agent_response_budget_exceeded",
                "The Facility Layout read response exceeded its bound.",
            )
        return {
            "authoritative": True,
            "records": [{"zoneId": "zone-a", "label": "Zone A"}],
            "returnedCount": 1,
            "totalCount": 1,
            "nextCursor": None,
        }

    monkeypatch.setattr(
        facility_host.agent_runtime,
        "execute_read_tool",
        fake_read_tool,
    )
    results, trace, remaining_calls, _remaining_bytes, exhausted = asyncio.run(
        server._execute_facility_layout_provider_reads(
            [{
                "name": "inspect_facility_semantics",
                "args": {"view": "zones", "pageSize": 25},
            }],
            request=server.AgentChatRequest(
                message="Inspect the relevant zones.",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            round_index=1,
            turn_id="automatic-narrowing-test",
            remaining_calls=10,
            remaining_bytes=65_536,
        )
    )

    assert calls == [
        ("inspect_facility_semantics", {"view": "zones", "pageSize": 25}),
        ("inspect_facility_semantics", {"view": "zones", "pageSize": 10}),
    ]
    assert results[0]["status"] == "succeeded"
    assert results[0]["automaticNarrowing"]["retryArguments"] == {
        "view": "zones",
        "pageSize": 10,
    }
    assert trace[0]["automaticNarrowing"] is True
    assert remaining_calls == 8
    assert exhausted is False
    assert _current(facility_host)["revision"] == current["revision"]


def test_facility_presentation_is_required_after_authoritative_read(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(_provider_tool(
        "inspect_facility_semantics",
        {"view": "department_metrics", "pageSize": 6},
    ))
    required_names = []

    async def fake_invoke(_client, **kwargs):
        required_names.append(kwargs.get("required_tool_name"))
        if len(required_names) == 1:
            return _provider_response(_provider_text(
                "The six exact department areas are ready."
            ))
        return _provider_response(_provider_tool(
            server.CHAT_VISUALIZATION_TOOL,
            {
                "chart_type": "pie",
                "title": "Department floor area",
                "subtitle": None,
                "unit": "m2",
                "show_values": True,
                "show_percentages": False,
                "show_legend": True,
                "data": [{
                    "label": "Machining",
                    "value": 100.0,
                    "entity_id": None,
                    "series": None,
                }],
            },
        ))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    response, trace, _usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Show a pie chart by department floor area.",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {"mode": "read_only_analysis"},
            },
            system_prompt="Analyze.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Chart area."}],
            }],
            provider_tools=_facility_analysis_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=server.CHAT_VISUALIZATION_TOOL,
        )
    )

    assert len(trace) == 1
    assert required_names == [None, server.CHAT_VISUALIZATION_TOOL]
    assert server.extract_provider_tool_calls(
        response, "deviation-analyst"
    )[0]["name"] == server.CHAT_VISUALIZATION_TOOL


def test_facility_read_failure_is_observed_and_not_silently_presented(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    bundle = facility_host.agent_runtime.resolve_context(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
    )
    initial = _provider_response(_provider_tool(
        "inspect_facility_semantics",
        {"view": "not_a_real_view"},
    ))
    required_names = []

    async def fake_invoke(_client, **kwargs):
        required_names.append(kwargs.get("required_tool_name"))
        assert "facility_agent_semantic_view_invalid" in json.dumps(
            kwargs["messages"]
        )
        return _provider_response(_provider_text(
            "The requested semantic observation failed, so no chart is shown."
        ))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    response, trace, _usage, _deferred = asyncio.run(
        server._resolve_facility_layout_provider_reads(
            initial,
            client=object(),
            request=server.AgentChatRequest(
                message="Chart the unavailable metric.",
                agent_type="deviation-analyst",
            ),
            http_request=_facility_http_request(),
            ctx={"facility_layout_state": bundle.state},
            skill_prompt_plan={
                "workflow": {"id": "facility-layout-analysis"},
                "runtime_tool_policy": {"mode": "read_only_analysis"},
            },
            system_prompt="Analyze.",
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": "Chart."}],
            }],
            provider_tools=_facility_analysis_provider_tools(),
            provider="anthropic",
            model="test-model",
            reasoning_effort=None,
            terminal_required_tool=server.CHAT_VISUALIZATION_TOOL,
        )
    )

    assert trace[0]["status"] == "failed"
    assert required_names == [None]
    assert "failed" in server._accumulate_response_text(response)
    assert _current(facility_host)["revision"] == current["revision"]


def test_browser_facility_payload_cannot_inject_geometry_or_evidence(
    facility_host,
):
    current = _current(facility_host)
    malicious = {
        "facility_layout_state": {"placements": [{"forged": True}]},
        "facility_layout_evidence": {"records": [{"forged": True}]},
        "facility_layout_digest": {"identity": {"layoutId": "forged"}},
        "attachments": {
            "facility_layout": {
                "siteId": LOCAL_SITE_ID,
                "layoutId": LOCAL_LAYOUT_ID,
                "revision": current["revision"],
                "layout": {"placements": [{"forged": True}]},
                "evidence": {"records": [{"forged": True}]},
                "digest": {"identity": {"layoutId": "nested-forged"}},
                "state": {
                    "dirty": False,
                    "conflict": False,
                    "editable": True,
                    "viewportMode": "split",
                    "selection": {},
                    "camera": {"zoom": 999},
                    "placements": [{"forged": True}],
                },
            },
            "session": {"active_mode": "training"},
        },
    }
    flat = server.normalize_agent_context(malicious)["flat"]
    assert "facility_layout_state" not in flat
    assert "facility_layout_evidence" not in flat
    assert "facility_layout_digest" not in flat
    assert set(flat["facility_layout_ref"]) == {
        "siteId",
        "layoutId",
        "revision",
    }

    server._resolve_trusted_facility_layout_context(flat)
    encoded = json.dumps(flat, sort_keys=True)
    assert '"forged": true' not in encoded
    assert '"zoom": 999' not in encoded
    assert flat["facility_layout_state"]["identity"]["layoutId"] == (
        LOCAL_LAYOUT_ID
    )
    assert flat["facility_layout_state"]["editor"]["viewportMode"] == "split"
    assert flat["facility_layout_digest"]["identity"]["revision"] == (
        current["revision"]
    )


def test_stale_browser_facility_revision_is_rejected_before_prompt(
    facility_host,
):
    flat = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": "0" * 64,
        }
    }
    with pytest.raises(HTTPException) as caught:
        server._resolve_trusted_facility_layout_context(flat)
    assert caught.value.status_code == 409
    assert caught.value.detail["error"]["code"] == (
        "facility_layout_revision_conflict"
    )


@pytest.mark.parametrize(
    ("message", "history"),
    [
        (
            "Create a Pareto chart comparing the current Facility Layout "
            "entity counts without changing it.",
            [],
        ),
        (
            "show a pareto chart not a bar chart?",
            [
                {
                    "role": "user",
                    "content": "Show a chart of the current facility layout.",
                },
                {
                    "role": "assistant",
                    "content": "Here is the requested bar chart.",
                },
            ],
        ),
        (
            "yes",
            [
                {
                    "role": "user",
                    "content": "Compare the Machining Hall and Automation zone.",
                },
                {
                    "role": "assistant",
                    "content": "Should I show their category breakdown?",
                },
            ],
        ),
        ("hi", []),
    ],
)
def test_memory_analysis_envelope_omits_full_facility_state(
    facility_host,
    message,
    history,
):
    current = _current(facility_host)
    request = server.AgentChatRequest(
        message=message,
        history=history,
        inspection_context={
            "attachments": {
                "facility_layout": {
                    "siteId": LOCAL_SITE_ID,
                    "layoutId": LOCAL_LAYOUT_ID,
                    "revision": current["revision"],
                },
                "session": {"active_mode": "training"},
            }
        },
        agent_type="deviation-analyst",
        session_id="memory-analysis-envelope-test",
    )
    http_request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/agent/chat/v2/stream",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "scheme": "http",
    })
    trusted = server.TrustedTurnContext(
        asset_scope={
            "kind": "facility_layout",
            "ids": {
                "siteId": LOCAL_SITE_ID,
                "layoutId": LOCAL_LAYOUT_ID,
            },
            "expectedRevisionVector": {
                "facilityLayoutRevision": current["revision"],
            },
        },
        scope_fingerprint="scope-v1:facility-analysis",
        revision_vector={
            "facilityLayoutRevision": current["revision"],
        },
        workflow_mode="facility_layout",
    )

    rows = server._memory_fallback_provider_inputs(
        request,
        http_request,
        trusted,
    )
    by_key = {row["contextKey"]: row for row in rows}

    assert "facility_layout.state" not in by_key
    assert "facility_layout.digest" in by_key
    digest = by_key["facility_layout.digest"]["payload"][
        "facility_layout_digest"
    ]
    assert digest["requestProjection"] == "facility_layout_analysis"
    assert digest["truncation"]["zoneIndex"]["omittedCount"] == 0
    assert digest["truncation"]["zoneSummaries"]["returnedCount"] == 0
    assert "zoneSummaries" not in digest


@pytest.mark.parametrize("construction_enabled", [False, True])
def test_facility_request_policy_separates_read_and_preview_tools(monkeypatch, construction_enabled):
    from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags

    flags = FacilityLayoutFeatureFlags.all_enabled()
    flags = FacilityLayoutFeatureFlags(tuple(
        (name, construction_enabled if name == "INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE" else value)
        for name, value in flags.values
    ))
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", SimpleNamespace(feature_flags=flags))
    base = {
        "workflow": {"id": "facility-layout-generation"},
        "prompt": "base",
        "allowed_tools": [],
    }
    read_only = server._apply_facility_layout_request_tool_policy(
        base,
        "Which racks are available in this facility?",
    )
    assert set(read_only["allowed_tools"]) == INSPECT_TOOLS
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in (
        read_only["allowed_tools"]
    )
    assert read_only["runtime_tool_policy"]["mode"] == (
        "read_only_analysis"
    )

    generation = server._apply_facility_layout_request_tool_policy(
        base,
        "Build a warehouse layout proposal with rack lanes.",
    )
    assert set(generation["allowed_tools"]) == (
        READ_TOOLS | {SEMANTIC_FACILITY_PREVIEW_TOOL}
        | {server.G1_FACILITY_GENERATION_TOOL}
        | {server.FULL_FACTORY_TOOL}
        | {server.FACILITY_PLANNING_PROTOTYPE_TOOL}
        | {server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL}
        | (set(server.CONSTRUCTION_TOOLS) if construction_enabled else set())
    )
    assert not set(generation["allowed_tools"]) & server.GENERATION_TOOLS
    assert generation["runtime_tool_policy"]["mode"] == (
        "semantic_generation"
    )

    exact_move = server._apply_facility_layout_request_tool_policy(
        base,
        "Move the selected machine 10 ft east and preserve its rotation.",
    )
    assert set(exact_move["allowed_tools"]) == (
        EXACT_TRANSFORM_TOOLS | {SEMANTIC_FACILITY_MOVE_TOOL}
    )
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in exact_move["allowed_tools"]
    assert exact_move["runtime_tool_policy"]["mode"] == (
        "precise_translation"
    )
    assert "Never emit a coordinate" in exact_move["prompt"]


def test_facility_review_request_is_read_only_even_when_it_names_layout():
    message = (
        "Review the current facility layout without changing it. Use a "
        "heading, a table listing each zone and its purpose, and a numbered "
        "list of the three highest-priority layout checks."
    )
    base = {
        "workflow": {"id": "facility-layout-generation"},
        "prompt": "base",
        "allowed_tools": [],
    }

    assert server._is_facility_layout_generation_request(message) is False
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        message,
    )
    assert set(constrained["allowed_tools"]) == TABLE_INSPECT_TOOLS
    assert constrained["runtime_tool_policy"]["mode"] == (
        "read_only_analysis"
    )
    route = server._safe_facility_layout_route(message)
    assert route["speech_act"] == "analyze"
    assert route["intents"][0]["kind"] == "analyze_facility_layout"
    assert route["primary_workflow"] == "facility-layout-analysis"
    assert route["skill_candidates"][0]["id"] == (
        "analyze-facility-layout"
    )


def test_facility_inspection_phrases_do_not_grant_preview_authority():
    assert server._is_facility_layout_generation_request(
        "Inspect the gates, loading sides, service access, and keep-clear "
        "intrusions for every robot cell."
    ) is False


def test_facility_spatial_analysis_taxonomy_maps_semantics_not_exact_prompts():
    assert requested_facility_spatial_analyses(
        "Where do pedestrian and forklift paths intersect?"
    ) == ("route_crossings",)
    assert requested_facility_spatial_analyses(
        "Which machines are hardest to service?"
    ) == ("asset_access",)
    assert requested_facility_spatial_analyses(
        "Inspect robot-cell gates and keep-clear intrusions."
    ) == ("cell_access", "protected_intrusions")
    assert requested_facility_spatial_analyses(
        "Audit the 2D and 3D placement transforms for mismatches."
    ) == ("render_consistency",)
    assert requested_facility_spatial_analyses(
        "Can the drone pass between the selected racks at this altitude?"
    ) == ("drone_clearance",)


def test_forklift_route_feasibility_is_analysis_not_a_move_request():
    message = (
        "Can a forklift move from Receiving to Finished Goods along the "
        "authored routes?"
    )
    assert server._is_facility_layout_generation_request(message) is False
    constrained = server._apply_facility_layout_request_tool_policy(
        {
            "workflow": {"id": "facility-layout-analysis"},
            "prompt": "base",
            "allowed_tools": [],
        },
        message,
    )
    assert constrained["runtime_tool_policy"]["spatialAnalyses"] == [
        "route_access"
    ]
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in (
        constrained["allowed_tools"]
    )
    assert server._is_facility_layout_generation_request(
        "Audit actual 2D and 3D placement transforms and report any "
        "mismatches."
    ) is False


def test_facility_runtime_boundary_blocks_read_only_viewport_and_preview_actions():
    result = {
        "response": "Started viewport rotation. Analysis follows.",
        "ui_actions": {
            "workspace": "assembly",
            "actions": [{"type": "rotate_view"}],
        },
        "viewport_intent": {"intent_kind": "rotate_view"},
    }
    trusted = {
        "facility_layout_state": {},
        "facility_layout_evidence": {},
        "facility_layout_digest": {},
    }
    calls, warnings = server._enforce_facility_action_runtime_boundary(
        result,
        message=(
            "Review the current facility layout without changing it and "
            "list the three highest-priority checks."
        ),
        context=trusted,
        tool_calls=[
            {"name": "ui_actions", "args": {"actions": [{"type": "rotate_view"}]}},
            {"name": SEMANTIC_FACILITY_PREVIEW_TOOL, "args": {}},
            {"name": "inspect_facility_semantics", "args": {}},
            {"name": "present_chat_table", "args": {}},
        ],
    )

    assert result["facility_action_mode"] == "READ_ONLY"
    assert [call["name"] for call in calls] == [
        "inspect_facility_semantics",
        "present_chat_table",
    ]
    assert "ui_actions" not in result
    assert "viewport_intent" not in result
    assert "Started viewport rotation" not in result["response"]
    assert any("removed_tools" in warning for warning in warnings)


def test_facility_runtime_boundary_treats_move_as_preview_without_camera_rotation():
    result = {
        "response": "Started viewport rotation.",
        "camera_view": "right",
    }
    trusted = {
        "facility_layout_state": {},
        "facility_layout_evidence": {},
        "facility_layout_digest": {},
    }
    calls, _warnings = server._enforce_facility_action_runtime_boundary(
        result,
        message=(
            "Move the selected machine 10 ft east and preserve its rotation."
        ),
        context=trusted,
        tool_calls=[
            {
                "name": SEMANTIC_FACILITY_MOVE_TOOL,
                "args": {
                    "use_current_selection": True,
                    "direction": "east",
                    "distance": 10,
                    "unit": "ft",
                    "preserve_rotation": True,
                },
            },
            {"name": SEMANTIC_FACILITY_PREVIEW_TOOL, "args": {}},
            {"name": "ui_actions", "args": {"actions": [{"type": "rotate_view"}]}},
        ],
    )

    assert result["facility_action_mode"] == "PREVIEW"
    assert [call["name"] for call in calls] == [
        SEMANTIC_FACILITY_MOVE_TOOL
    ]
    assert result["facility_runtime_policy"][
        "preciseTranslationAuthorized"
    ] is True
    assert "camera_view" not in result
    assert "viewport rotation" not in result["response"]


def test_exact_translation_classifier_is_narrow_and_does_not_authorize_other_edits():
    assert is_precise_facility_translation_request(
        "Move the selected machine 10 ft east and preserve its rotation."
    ) is True
    assert is_precise_facility_translation_request(
        "Shift CNC-04 250 mm north."
    ) is True
    assert is_precise_facility_translation_request(
        "Move the machine east."
    ) is False
    assert is_precise_facility_translation_request(
        "Move and rotate the machine 10 ft east."
    ) is False
    assert is_precise_facility_translation_request(
        "Could another machine fit 10 ft east of this one?"
    ) is False


def test_full_preview_backstop_never_rewrites_an_exact_move_as_layout_generation():
    calls, warnings, added = server.ensure_facility_layout_preview_tool_call(
        [{"name": SEMANTIC_FACILITY_PREVIEW_TOOL, "args": {}}],
        {"workflow": {"id": "facility-layout-generation"}},
        {},
        "Move the selected machine 10 ft east and preserve its rotation.",
        "deviation-analyst",
    )

    assert calls == []
    assert warnings == ["facility_full_preview_dropped_precise_translation"]
    assert added is False


def test_complete_facility_request_parser_preserves_authored_program():
    parsed = parse_complete_facility_generation_request(
        "Create a new 100 m by 100 m facility and divide it into four "
        "equal departments named Receiving and Stores, Machining, "
        "Assembly, and Inspection and Shipping."
    )

    assert parsed == {
        "facility_envelope": {
            "width": 100.0,
            "depth": 100.0,
            "source_unit": "m",
            "display_name": "Facility Layout",
            "grid_size": None,
        },
        "departments": {
            "count": 4,
            "labels": [
                "Receiving and Stores",
                "Machining",
                "Assembly",
                "Inspection and Shipping",
            ],
                "proportions": [0.25, 0.25, 0.25, 0.25],
                "arrangement": "deterministic_grid",
                "orientation": "auto",
                "rows": None,
            },
        "execution_mode": "authorized_draft_run",
    }


def test_complete_facility_request_parser_is_dynamic_and_fail_closed():
    parsed = parse_complete_facility_generation_request(
        "Build a new 120 ft by 90 ft factory and split it into five equal "
        "departments named Receiving, Fabrication, Paint, Assembly, and "
        "Shipping in a single row."
    )

    assert parsed is not None
    assert parsed["facility_envelope"] == {
        "width": 120.0,
        "depth": 90.0,
        "source_unit": "ft",
        "display_name": "Facility Layout",
        "grid_size": None,
    }
    assert parsed["departments"]["count"] == 5
    assert parsed["departments"]["labels"] == [
        "Receiving",
        "Fabrication",
        "Paint",
        "Assembly",
        "Shipping",
    ]
    assert parsed["departments"]["arrangement"] == "rows"
    assert parse_complete_facility_generation_request(
        "Create a 100 m by 80 m facility with four departments."
    ) is None
    assert parse_complete_facility_generation_request(
        "Create a 100 m by 80 m facility divided into four departments "
        "named Receiving, Machining, and Assembly."
    ) is None
    assert parse_complete_facility_generation_request(
        "Do not create a 100 m by 80 m facility divided into four "
        "departments named A, B, C, and D."
    ) is None
    assert parse_complete_facility_generation_request(
        "Create a report about a proposed 100 m by 80 m facility divided "
        "into four departments named A, B, C, and D."
    ) is None


def test_complete_facility_parser_preserves_authored_rows_and_unequal_areas():
    parsed = parse_complete_facility_generation_request(
        "Create a new 100 m by 80 m facility and divide it into five "
        "departments named Receiving, Machining, Assembly, Inspection, "
        "and Shipping. Put Receiving and Machining in the top row and "
        "Assembly, Inspection, and Shipping in the bottom row. Use area "
        "percentages of 10%, 20%, 30%, 15%, and 25%, respectively."
    )

    assert parsed is not None
    assert parsed["departments"]["arrangement"] == "row_stack"
    assert parsed["departments"]["rows"] == [
        {
            "labels": ["Receiving", "Machining"],
            "proportion": None,
        },
        {
            "labels": ["Assembly", "Inspection", "Shipping"],
            "proportion": None,
        },
    ]
    assert parsed["departments"]["proportions"] == [
        10.0,
        20.0,
        30.0,
        15.0,
        25.0,
    ]


def test_complete_facility_parser_balances_any_authored_row_count():
    parsed = parse_complete_facility_generation_request(
        "Build a 120 m by 90 m factory with six equal departments named "
        "Receiving, Stores, Machining, Assembly, Inspection, and Shipping "
        "arranged in three rows."
    )

    assert parsed is not None
    assert parsed["departments"]["arrangement"] == "row_stack"
    assert [len(row["labels"]) for row in parsed["departments"]["rows"]] == [
        2,
        2,
        2,
    ]


def test_complete_facility_parser_accepts_equal_area_hyphenation():
    parsed = parse_complete_facility_generation_request(
        "Create a new 150 m by 100 m facility with six equal-area "
        "departments named Inbound, Raw Materials, Fabrication, "
        "Subassembly, Final Inspection, and Dispatch. Arrange them in "
        "three rows: Inbound and Raw Materials in row 1; Fabrication and "
        "Subassembly in row 2; Final Inspection and Dispatch in row 3."
    )

    assert parsed is not None
    assert parsed["departments"]["proportions"] == [1.0 / 6.0] * 6
    assert parsed["departments"]["rows"] == [
        {"labels": ["Inbound", "Raw Materials"], "proportion": None},
        {"labels": ["Fabrication", "Subassembly"], "proportion": None},
        {
            "labels": ["Final Inspection", "Dispatch"],
            "proportion": None,
        },
    ]


def test_complete_facility_parser_preserves_label_first_numbered_rows():
    parsed = parse_complete_facility_generation_request(
        "Create a new 120 m by 90 m facility with eight departments named "
        "Receiving, Stores, Machining, Automation, Assembly, Inspection, "
        "Packing, and Shipping. Arrange them in four rows: Receiving in "
        "row 1; Stores, Machining, and Automation in row 2; Assembly and "
        "Inspection in row 3; Packing and Shipping in row 4. Keep all "
        "departments equal in area."
    )

    assert parsed is not None
    assert parsed["departments"]["rows"] == [
        {"labels": ["Receiving"], "proportion": None},
        {
            "labels": ["Stores", "Machining", "Automation"],
            "proportion": None,
        },
        {"labels": ["Assembly", "Inspection"], "proportion": None},
        {"labels": ["Packing", "Shipping"], "proportion": None},
    ]


def test_complete_facility_parser_does_not_ignore_unresolved_row_or_area_intent():
    assert parse_complete_facility_generation_request(
        "Create a 100 m by 80 m facility with five departments named "
        "Receiving, Machining, Assembly, Inspection, and Shipping. Put "
        "some departments above the others."
    ) is None
    assert parse_complete_facility_generation_request(
        "Create a 100 m by 80 m facility with five departments named "
        "Receiving, Machining, Assembly, Inspection, and Shipping. Make "
        "Assembly twice the area of Inspection."
    ) is None


def _five_department_program():
    return {
        "source": "active_generation_run",
        "run_id": "fgr-demo",
        "facility_envelope": {
            "width": 100.0,
            "depth": 80.0,
            "source_unit": "m",
            "display_name": "Facility Layout",
            "grid_size": 1.0,
        },
        "departments": {
            "count": 5,
            "labels": [
                "Receiving",
                "Machining",
                "Assembly",
                "Inspection",
                "Shipping",
            ],
            "proportions": [0.2] * 5,
            "arrangement": "deterministic_grid",
            "orientation": "auto",
            "rows": None,
        },
    }


@pytest.mark.parametrize(
    ("message", "expected_counts"),
    [
        ("Put two departments above and three below.", [2, 3]),
        ("Arrange these departments in three rows.", [2, 2, 1]),
        (
            "Top row: Receiving and Machining; bottom row: Assembly, "
            "Inspection, and Shipping.",
            [2, 3],
        ),
        (
            "Use row 1: Receiving and Machining; row 2: Assembly and "
            "Inspection; row 3: Shipping.",
            [2, 2, 1],
        ),
        (
            "Receiving in row 1; Machining and Assembly in row 2; "
            "Inspection and Shipping in row 3.",
            [1, 2, 2],
        ),
    ],
)
def test_department_repartition_parser_supports_flexible_rows(
    message,
    expected_counts,
):
    parsed = parse_facility_department_repartition_request(
        message,
        _five_department_program(),
    )

    assert parsed is not None
    assert parsed["departments"]["arrangement"] == "row_stack"
    assert [
        len(row["labels"]) for row in parsed["departments"]["rows"]
    ] == expected_counts
    assert parsed["facility_envelope"]["width"] == 100.0
    assert parsed["facility_envelope"]["depth"] == 80.0


def test_department_repartition_parser_supports_unequal_department_or_row_area():
    current = _five_department_program()
    current["departments"]["arrangement"] = "row_stack"
    current["departments"]["rows"] = [
        {
            "labels": ["Receiving", "Machining"],
            "proportion": 0.4,
        },
        {
            "labels": ["Assembly", "Inspection", "Shipping"],
            "proportion": 0.6,
        },
    ]
    department_areas = parse_facility_department_repartition_request(
        "Make Receiving 10%, Machining 20%, Assembly 30%, Inspection "
        "15%, and Shipping 25%.",
        current,
    )
    row_areas = parse_facility_department_repartition_request(
        "Put Receiving and Machining in the top row at 40% and Assembly, "
        "Inspection, and Shipping in the bottom row at 60%.",
        _five_department_program(),
    )

    assert department_areas["departments"]["proportions"] == [
        10.0,
        20.0,
        30.0,
        15.0,
        25.0,
    ]
    assert [
        row["proportion"]
        for row in department_areas["departments"]["rows"]
    ] == [None, None]
    assert row_areas["departments"]["proportions"] is None
    assert [
        row["proportion"] for row in row_areas["departments"]["rows"]
    ] == [40.0, 60.0]


def test_department_repartition_parser_fails_closed_on_partial_intent():
    program = _five_department_program()

    assert parse_facility_department_repartition_request(
        "Put some departments above the others.",
        program,
    ) is None
    assert parse_facility_department_repartition_request(
        "Make Assembly twice the area of Inspection.",
        program,
    ) is None
    assert parse_facility_department_repartition_request(
        "How would these departments look in three rows?",
        program,
    ) is None


def test_complete_facility_request_replaces_generic_preview_selection():
    message = (
        "Create a new 100 m by 100 m facility and divide it into four "
        "equal departments named Receiving and Stores, Machining, "
        "Assembly, and Inspection and Shipping."
    )
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [{"name": SEMANTIC_FACILITY_PREVIEW_TOOL, "args": {}}],
            {
                "workflow": {"id": "facility-layout-generation"},
                "runtime_tool_policy": {"mode": "semantic_generation"},
                "allowed_tools": [
                    server.G1_FACILITY_GENERATION_TOOL,
                    SEMANTIC_FACILITY_PREVIEW_TOOL,
                ],
            },
            {
                "facility_layout_state": {"dirty": True},
                "facility_layout_evidence": {},
            },
            message,
            "deviation-analyst",
        )
    )

    assert changed is True
    assert warnings == [
        "g1_generation_intent_compiled_from_user_request"
    ]
    assert [call["name"] for call in calls] == [
        server.G1_FACILITY_GENERATION_TOOL
    ]
    assert calls[0]["args"]["facility_envelope"]["width"] == 100.0
    assert calls[0]["args"]["departments"]["labels"][-1] == (
        "Inspection and Shipping"
    )


def test_g1_generation_tool_canonicalizes_only_coordinate_free_intent():
    prompt_plan = {
        "workflow": {"id": "facility-layout-generation"},
        "runtime_tool_policy": {"mode": "semantic_generation"},
        "allowed_tools": [server.G1_FACILITY_GENERATION_TOOL],
    }
    call = {
        "name": server.G1_FACILITY_GENERATION_TOOL,
        "args": {
            "facility_envelope": {
                "width": 100,
                "depth": 80,
                "source_unit": "m",
                "display_name": "North Plant",
                "grid_size": None,
            },
            "departments": {
                "count": 4,
                "labels": [
                    "Receiving",
                    "Machining",
                    "Assembly",
                    "Inspection",
                ],
                "proportions": None,
                "arrangement": "deterministic_grid",
                "orientation": "auto",
            },
            "execution_mode": "authorized_draft_run",
        },
    }
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [call],
            prompt_plan,
            {},
            (
                "Create an empty 100 m by 80 m facility with Receiving, "
                "Machining, Assembly, and Inspection departments."
            ),
            "deviation-analyst",
        )
    )
    assert warnings == []
    assert changed is False
    assert calls == [call]
    assert "coordinates" not in str(calls).lower()


def test_g1_generation_tool_rejects_model_authored_geometry():
    prompt_plan = {
        "workflow": {"id": "facility-layout-generation"},
        "runtime_tool_policy": {"mode": "semantic_generation"},
        "allowed_tools": [server.G1_FACILITY_GENERATION_TOOL],
    }
    call = {
        "name": server.G1_FACILITY_GENERATION_TOOL,
        "args": {
            "facility_envelope": {
                "width": 100,
                "depth": 80,
                "source_unit": "m",
                "display_name": "North Plant",
                "grid_size": None,
            },
            "departments": {
                "count": 1,
                "labels": ["Assembly"],
                "proportions": None,
                "arrangement": "columns",
                "orientation": "auto",
                "coordinates": [{"x": 0, "z": 0}],
            },
            "execution_mode": "authorized_draft_run",
        },
    }
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [call],
            prompt_plan,
            {},
            "Build a 100 m by 80 m facility layout proposal with an Assembly department.",
            "deviation-analyst",
        )
    )
    assert calls == []
    assert warnings == [
        "g1_generation_rejected:"
        "g1_model_authored_geometry_or_unknown_field"
    ]
    assert changed is False


def _full_factory_tool_call():
    return {
        "name": server.FULL_FACTORY_TOOL,
        "args": {
            "facility_envelope": {
                "width": 120,
                "depth": 90,
                "source_unit": "m",
                "display_name": "Integrated Factory",
                "grid_size": 1,
            },
            "departments": {
                "count": 3,
                "labels": ["Inbound", "Assembly", "Dispatch"],
                "proportions": None,
                "arrangement": "columns",
                "orientation": "horizontal",
                "rows": None,
            },
            "circulation": {
                "routes": [{
                    "route_kind": "material",
                    "width": 4,
                    "source_unit": "m",
                    "source_department": "Inbound",
                    "target_department": "Dispatch",
                    "via_departments": ["Assembly"],
                    "direction": "two_way",
                    "label": "Primary material aisle",
                }],
                "crossings": [],
            },
            "subdivisions": [{
                "parent_department": "Assembly",
                "count": 2,
                "labels": ["Electrical Build", "Test"],
                "proportions": None,
                "arrangement": "columns",
                "orientation": "horizontal",
                "rows": None,
            }],
            "asset_placements": [],
            "seed_cell": None,
            "cell_replication": None,
            "execution_mode": "authorized_draft_run",
        },
    }


def test_full_factory_tool_is_canonicalized_without_degrading_to_g1():
    call = _full_factory_tool_call()
    message = (
        "Create a 120 m by 90 m facility with Inbound, Assembly, and Dispatch. "
        "Add a 4 m material aisle from Inbound through Assembly to Dispatch, "
        "then divide Assembly into Electrical Build and Test."
    )
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [server.FULL_FACTORY_TOOL],
        },
        {},
        message,
        "deviation-analyst",
    )
    assert warnings == []
    assert changed is True
    assert calls[0]["name"] == server.FULL_FACTORY_TOOL
    assert calls[0]["args"]["departments"]["labels"] == [
        "Inbound", "Assembly", "Dispatch"
    ]
    assert calls[0]["args"]["circulation"]["routes"][0]["label"] == (
        "Primary material aisle"
    )


def test_full_factory_execution_mode_is_owned_by_the_generation_boundary():
    call = _full_factory_tool_call()
    call["args"]["execution_mode"] = "preview_only"
    message = (
        "Create a 120 m by 90 m facility with Inbound, Assembly, and Dispatch. "
        "Add a 4 m material aisle from Inbound through Assembly to Dispatch, "
        "then divide Assembly into Electrical Build and Test. Keep it unsaved."
    )
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [server.FULL_FACTORY_TOOL],
        },
        {},
        message,
        "deviation-analyst",
    )
    assert warnings == []
    assert changed is True
    assert calls[0]["args"]["execution_mode"] == "authorized_draft_run"


def test_mmle_planning_prototype_is_synthesized_from_explicit_package_intent():
    message = (
        "Build the trusted MMLE-50D factory prototype from its Facility "
        "Planning package and keep it unsaved."
    )
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [server.FACILITY_PLANNING_PROTOTYPE_TOOL],
        },
        {},
        message,
        "deviation-analyst",
    )
    assert warnings == []
    assert changed is True
    assert calls == [
        {
            "name": server.FACILITY_PLANNING_PROTOTYPE_TOOL,
            "args": {
                "planning_package_id": (
                    server.MMLE_FACILITY_PLANNING_PACKAGE_ID
                ),
                "execution_mode": "authorized_draft_run",
            },
        }
    ]


def test_facility_program_resource_amendment_is_canonicalized_to_one_patch():
    message = (
        "Reduce the raw material rack batch to 89 and keep every other "
        "resource, route, marking, and area unchanged. Keep it unsaved."
    )
    call = {
        "name": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "args": {
            "resource_batch_id": "raw-material-racks",
            "quantity": 89,
            "placement_pattern": None,
            "semantic_orientation": None,
            "authored_spacing_meters": None,
            "execution_mode": "authorized_draft_run",
        },
    }
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [
                server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL
            ],
        },
        {},
        message,
        "deviation-analyst",
    )
    assert warnings == []
    assert changed is True
    assert calls == [{
        "name": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "args": {
            "resource_batch_id": "raw-material-racks",
            "patch": {"quantity": 89},
            "execution_mode": "authorized_draft_run",
        },
    }]


def test_facility_program_resource_followups_are_generation_intent():
    for message in (
        "Reduce the raw material rack batch to 89.",
        "Set the machine batch quantity to 12.",
        "Increase the workstation count to 8.",
        "Reorient the equipment batch east-west.",
        "Space the rack batch at exactly 1.5 m.",
    ):
        assert server._is_facility_layout_generation_request(message) is True


def test_facility_program_resource_alias_resolves_to_unique_trusted_batch():
    call = {
        "name": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "args": {
            "resource_batch_id": "raw_material_pallet_racks",
            "quantity": 89,
            "placement_pattern": None,
            "semantic_orientation": None,
            "authored_spacing_meters": None,
            "execution_mode": "authorized_draft_run",
        },
    }
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [
                server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL
            ],
        },
        {
            "facility_layout_state": {
                "generationDraft": {
                    "facilityProgram": {
                        "resourceBatches": [
                            {
                                "batchId": "raw-material-racks",
                                "targetArea": "Raw Material Rack Bank",
                                "quantity": 90,
                            },
                            {
                                "batchId": "finished-goods-racks",
                                "targetArea": "Finished Goods Rack Row R01",
                                "quantity": 12,
                            },
                        ],
                    },
                },
            },
        },
        "Reduce the raw material rack batch to 89 and keep it unsaved.",
        "deviation-analyst",
    )
    assert warnings == []
    assert changed is True
    assert calls[0]["args"]["resource_batch_id"] == "raw-material-racks"


def test_facility_program_resource_amendment_is_dropped_without_user_intent():
    call = {
        "name": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "args": {
            "resource_batch_id": "raw-material-racks",
            "quantity": 89,
            "placement_pattern": None,
            "semantic_orientation": None,
            "authored_spacing_meters": None,
            "execution_mode": "authorized_draft_run",
        },
    }
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [
                server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL
            ],
        },
        {},
        "What resources are present in Raw Material Storage?",
        "deviation-analyst",
    )
    assert calls == []
    assert warnings == [
        "facility_program_resource_amendment_dropped_unrequested"
    ]
    assert changed is True


def test_facility_program_resource_amendment_rejects_model_coordinates():
    call = {
        "name": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "args": {
            "resource_batch_id": "raw-material-racks",
            "quantity": 89,
            "placement_pattern": None,
            "semantic_orientation": None,
            "authored_spacing_meters": None,
            "execution_mode": "authorized_draft_run",
            "x": 40,
            "z": 25,
        },
    }
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [
                server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL
            ],
        },
        {},
        "Reduce the raw material rack batch to 89 and keep it unsaved.",
        "deviation-analyst",
    )
    assert calls == []
    assert warnings == [
        "facility_program_resource_amendment_rejected:"
        "facility_program_local_amendment_invalid"
    ]
    assert changed is False


def test_full_factory_restores_explicit_equal_row_and_replication_intent():
    call = _full_factory_tool_call()
    call["args"]["subdivisions"][0].update({
        "proportions": [0.499, 0.501],
        "arrangement": "rows",
        "orientation": "horizontal",
        "rows": None,
    })
    call["args"]["asset_placements"] = [{
        "asset_name": "Assembly Workbench",
        "quantity": 2,
        "target_area": "Electrical Build",
        "orientation_mode": "long_side_east_west",
        "facing_direction": None,
        "resource_role": "production",
        "access_requirement": "physical_only",
    }]
    call["args"]["seed_cell"] = {
        "target_area": "Electrical Build",
        "candidate_strategies": ["line", "l", "u"],
        "selected_strategy": None,
        "objective": "smallest_envelope",
        "preferred_gap_meters": 1.0,
        "invert_u": False,
    }
    call["args"]["cell_replication"] = None
    message = (
        "Create a 120 m by 90 m facility with Inbound, Assembly, and Dispatch; "
        "add a material aisle. Divide Assembly into two equal child areas "
        "named Electrical Build and Test in one row. Place two Assembly "
        "Workbenches in Electrical Build, arrange that cell, and replicate "
        "Electrical Build into the empty Test area. Keep it unsaved."
    )
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [server.FULL_FACTORY_TOOL],
        },
        {},
        message,
        "deviation-analyst",
    )
    assert warnings == []
    assert changed is True
    subdivision = calls[0]["args"]["subdivisions"][0]
    assert subdivision["proportions"] == [0.5, 0.5]
    assert subdivision["arrangement"] == "row_stack"
    assert subdivision["rows"] == [{
        "labels": ["Electrical Build", "Test"],
        "proportion": 1.0,
    }]
    assert calls[0]["args"]["cell_replication"] == {
        "source_cell": "Electrical Build",
        "target_areas": ["Test"],
        "copy_current_edited_state": False,
    }


def test_full_factory_tool_is_dropped_without_matching_user_generation_intent():
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [_full_factory_tool_call()],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [server.FULL_FACTORY_TOOL],
        },
        {},
        "What does the current layout contain?",
        "deviation-analyst",
    )
    assert calls == []
    assert warnings == [
        "full_factory_generation_tool_dropped_unrequested"
    ]
    assert changed is True


def test_full_factory_tool_rejects_model_authored_coordinates():
    call = _full_factory_tool_call()
    call["args"]["circulation"]["routes"][0]["centerline"] = [
        {"x": 10, "z": 20}
    ]
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [call],
        {
            "workflow": {"id": "facility-layout-generation"},
            "runtime_tool_policy": {"mode": "semantic_generation"},
            "allowed_tools": [server.FULL_FACTORY_TOOL],
        },
        {},
        (
            "Create a 120 m by 90 m facility, add a material aisle, and divide "
            "Assembly into Electrical Build and Test."
        ),
        "deviation-analyst",
    )
    assert calls == []
    assert warnings == [
        "full_factory_generation_rejected:"
        "full_factory_model_geometry_or_unknown_field"
    ]
    assert changed is False


def test_full_factory_request_bypasses_narrow_deterministic_gate_parsers():
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Create a 120 m by 90 m facility with Inbound, Assembly, and "
                "Dispatch; add a material aisle, divide Assembly into two "
                "support areas, and place machines in the build area."
            ),
            agent_type="deviation-analyst",
        ),
        {
            "facility_layout_state": {},
            "facility_layout_evidence": {},
            "facility_layout_digest": {},
            "_facility_layout_document": {
                "zones": [],
                "routes": [],
                "placements": [],
            },
        },
    ))
    assert result is None


def test_program_resource_amendment_bypasses_route_parser_preservation_words():
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Reduce the raw material rack batch to 89. Keep every other "
                "area, route, marking, and resource unchanged. Keep the "
                "complete result unsaved."
            ),
            agent_type="deviation-analyst",
        ),
        {
            "facility_layout_state": {},
            "facility_layout_evidence": {},
            "facility_layout_digest": {},
            "_facility_layout_document": {
                "zones": [],
                "routes": [],
                "placements": [],
            },
        },
    ))
    assert result is None


def test_full_factory_provider_uses_one_closed_required_tool(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    invoked = []

    async def fake_invoke(_client, **kwargs):
        invoked.append({
            "required": kwargs.get("required_tool_name"),
            "tools": [
                str(item.get("name") or "")
                for item in kwargs.get("tools") or []
            ],
        })
        return _provider_response(_provider_tool(
            server.FULL_FACTORY_TOOL,
            _full_factory_tool_call()["args"],
        ))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    response = TestClient(server.app).post(
        "/api/agent/chat",
        json={
            "message": (
                "Create a 120 m by 90 m facility with Inbound, Assembly, and "
                "Dispatch. Add a 4 m material aisle from Inbound through "
                "Assembly to Dispatch, then divide Assembly into Electrical "
                "Build and Test. Place two Assembly Workbenches in Electrical "
                "Build and arrange that cell. Keep it as an unsaved draft."
            ),
            "history": [],
            "inspection_context": {
                "attachments": {
                    "facility_layout": {
                        "siteId": LOCAL_SITE_ID,
                        "layoutId": LOCAL_LAYOUT_ID,
                        "revision": current["revision"],
                    },
                    "session": {"active_mode": "training"},
                }
            },
            "agent_type": "deviation-analyst",
            "session_id": "full-factory-closed-provider-test",
        },
    )

    assert response.status_code == 200, response.text
    assert invoked == [{
        "required": server.FULL_FACTORY_TOOL,
        "tools": [server.FULL_FACTORY_TOOL],
    }]
    payload = response.json()
    assert payload["tool_call_count"] == 1
    assert payload["tool_calls"][0]["name"] == server.FULL_FACTORY_TOOL


def test_program_resource_amendment_provider_uses_one_closed_required_tool(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    invoked = []
    provider_args = {
        "resource_batch_id": "raw-material-racks",
        "quantity": 89,
        "placement_pattern": None,
        "semantic_orientation": None,
        "authored_spacing_meters": None,
        "execution_mode": "authorized_draft_run",
    }

    async def fake_invoke(_client, **kwargs):
        invoked.append({
            "required": kwargs.get("required_tool_name"),
            "tools": [
                str(item.get("name") or "")
                for item in kwargs.get("tools") or []
            ],
        })
        return _provider_response(_provider_tool(
            server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
            provider_args,
        ))

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    response = TestClient(server.app).post(
        "/api/agent/chat",
        json={
            "message": (
                "Reduce the raw material rack batch to 89. Keep every other "
                "area, route, marking, and resource unchanged. Keep the "
                "complete result unsaved."
            ),
            "history": [],
            "inspection_context": {
                "attachments": {
                    "facility_layout": {
                        "siteId": LOCAL_SITE_ID,
                        "layoutId": LOCAL_LAYOUT_ID,
                        "revision": current["revision"],
                    },
                    "session": {"active_mode": "training"},
                }
            },
            "agent_type": "deviation-analyst",
            "session_id": "program-resource-amendment-provider-test",
        },
    )

    assert response.status_code == 200, response.text
    assert invoked == [{
        "required": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "tools": [server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL],
    }]
    payload = response.json()
    assert payload["tool_call_count"] == 1
    assert payload["tool_calls"] == [{
        "name": server.FACILITY_PROGRAM_RESOURCE_AMENDMENT_TOOL,
        "args": {
            "resource_batch_id": "raw-material-racks",
            "patch": {"quantity": 89},
            "execution_mode": "authorized_draft_run",
        },
    }]


def test_facility_program_resource_context_is_exact_and_bounded():
    projection = server._facility_program_resource_context({
        "programRevision": "a" * 64,
        "baseProgramRevision": "b" * 64,
        "amendments": [],
        "program": {
            "resource_batches": [{
                "batch_id": "raw-material-racks",
                "target_area": "Raw Material Rack Bank",
                "quantity": 90,
            }],
        },
    })
    assert projection["resourceBatches"] == [{
        "batchId": "raw-material-racks",
        "targetArea": "Raw Material Rack Bank",
        "quantity": 90,
    }]
    assert projection["evidenceStatus"] == "server_resolved"
    payload = json.dumps(
        projection,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    assert len(payload) <= 8_192


def test_exact_move_fast_path_bypasses_model_and_never_rotates_viewport():
    state = {
        "selection": {"placementIds": ["placement-cnc-04"]},
    }
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Move the selected machine 10 ft east and preserve its rotation."
            ),
            agent_type="deviation-analyst",
        ),
        {
            "facility_layout_state": state,
            "facility_layout_evidence": {},
            "facility_layout_digest": {},
        },
    ))

    assert result["tool_source"] == "facility_exact_transform_fast_path"
    assert result["tool_calls"] == [{
        "name": SEMANTIC_FACILITY_MOVE_TOOL,
        "args": {
            "use_current_selection": True,
            "direction": "east",
            "distance": 10.0,
            "unit": "ft",
            "preserve_rotation": True,
        },
    }]
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["facility_runtime_policy"]["requestKind"] == (
        "exact_transform"
    )
    assert "camera_view" not in result
    assert "viewport_intent" not in result
    assert "ui_actions" not in result


def test_complete_facility_fast_path_bypasses_model_on_populated_layout():
    populated_layout = _circulation_department_layout()
    context = _circulation_chat_context(populated_layout)
    context["facility_layout_state"].update({
        "dirty": True,
        "placements": [{"placementId": "existing-machine"}],
        "zones": [{"zoneId": "existing-department"}],
    })
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Create a new 100 m by 100 m facility and divide it into "
                "four equal departments named Receiving and Stores, "
                "Machining, Assembly, and Inspection and Shipping."
            ),
            agent_type="deviation-analyst",
        ),
        context,
    ))

    assert result is not None
    assert result["tool_source"] == "facility_g1_intent_fast_path"
    assert result["tool_call_count"] == 1
    assert result["tool_calls"][0]["name"] == (
        server.G1_FACILITY_GENERATION_TOOL
    )
    args = result["tool_calls"][0]["args"]
    assert args["facility_envelope"] == {
        "width": 100.0,
        "depth": 100.0,
        "source_unit": "m",
        "display_name": "Facility Layout",
        "grid_size": None,
    }
    assert args["departments"]["labels"] == [
        "Receiving and Stores",
        "Machining",
        "Assembly",
        "Inspection and Shipping",
    ]
    assert result["facility_action_mode"] == "PREVIEW"


def test_circulation_fast_path_builds_coordinate_free_tool_call():
    layout = _circulation_department_layout()
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Add a 6 m material aisle from Receiving to Shipping "
                "through Machining and Assembly."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_circulation_intent_fast_path"
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["tool_call_count"] == 1
    call = result["tool_calls"][0]
    assert call == {
        "name": server.G2_FACILITY_CIRCULATION_TOOL,
        "args": {
            "action": "create",
            "route_kind": "material",
            "width": 6.0,
            "source_unit": "m",
            "source_department": "Receiving",
            "target_department": "Shipping",
            "via_departments": ["Machining", "Assembly"],
            "direction": "two_way",
            "label": None,
            "execution_mode": "authorized_draft_run",
        },
    }
    assert "coordinates" not in repr(call).casefold()
    assert "overlay" in result["response"].casefold()
    assert "two-way" in result["response"].casefold()


def test_motion_fast_path_builds_read_only_identity_only_tool_call():
    layout = _circulation_department_layout()
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    revision = "d" * 64
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Replay a forklift on Main Forklift Boulevard using vehicle "
                f"profile forklift-standard revision {revision}."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_motion_intent_fast_path"
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["facility_runtime_policy"]["readOnly"] is True
    assert result["tool_calls"] == [{
        "name": server.FACILITY_MOTION_PLAYBACK_TOOL,
        "args": {
            "route_id": "rt-main-forklift",
            "vehicle_profile_id": "forklift-standard",
            "vehicle_profile_revision": revision,
            "travel_direction": "forward",
        },
    }]
    call_text = repr(result["tool_calls"]).casefold()
    for forbidden in ("coordinate", "pose", "speed", "duration"):
        assert forbidden not in call_text


def test_legacy_activity_fast_path_is_unreachable_from_sage():
    layout = _circulation_department_layout()
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Play a prototype factory activity view with vehicles on authored "
                "material lanes and operators on authored pedestrian routes. Keep "
                "machines without revision-bound kinematic evidence stationary."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_activity_legacy_unavailable"
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["tool_calls"] == []
    assert result["facility_generation_error"] == (
        "facility_legacy_navigation_fixture_only"
    )


def test_complete_reference_activity_fast_path_is_read_only_and_bounded():
    layout = _circulation_department_layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Show the prototype movement candidate map for all moving "
                "objects in this reference factory. Use the existing operators "
                "and forklifts, display the pending handoff links, keep fixed "
                "machines stationary, and do not save."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == (
        "facility_reference_complete_activity_intent_fast_path"
    )
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["facility_runtime_policy"]["readOnly"] is True
    assert result["tool_calls"] == [{
        "name": server.FACILITY_ACTIVITY_PLAYBACK_TOOL,
        "args": {
            "preset": "reference_complete_navigation",
            "prototype_mode": True,
            "maximum_actors": 23,
            "scenario_label": "Complete reference movement",
        },
    }]
    assert "23 unique existing actor placements" in result["response"]
    assert "Nothing will be saved" in result["response"]


def test_reference_downstream_activity_fast_path_routes_existing_operators():
    layout = _circulation_department_layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Play a prototype activity view for the existing operators in "
                "the Inspection, Packaging, and Finished Goods area. Use "
                "deterministic obstruction-free candidate journeys, loop each "
                "operator back to its existing start, do not duplicate placements, "
                "and do not save."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == (
        "facility_reference_downstream_activity_intent_fast_path"
    )
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["facility_runtime_policy"]["readOnly"] is True
    assert result["tool_calls"] == [{
        "name": server.FACILITY_ACTIVITY_PLAYBACK_TOOL,
        "args": {
            "preset": "reference_downstream_navigation",
            "prototype_mode": True,
            "maximum_actors": 8,
            "scenario_label": "Downstream operator movement candidates",
        },
    }]
    assert "eight existing downstream operators" in result["response"]
    assert "Nothing will be saved" in result["response"]


def test_packaging_cycle_activity_precedes_general_navigation_provider_route():
    layout = _circulation_department_layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    message = (
        "Play a prototype Packaging activity. Each existing Packaging "
        "operator picks from the left pallet, works at their current "
        "table, walks around the table's right side to place the finished "
        "product on the existing cart, then returns empty to the input "
        "pallet and repeats. Reuse existing operators and carts; do not "
        "duplicate placements and do not save."
    )
    activity_turn = server.parse_activity_playback_turn(message, layout)
    assert activity_turn["kind"] == "build"
    assert activity_turn["request"]["preset"] == (
        "reference_downstream_navigation"
    )
    context = _circulation_chat_context(layout)
    assert server._has_trusted_facility_layout_context(context)
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=message,
            agent_type="deviation-analyst",
        ),
        context,
    ))

    assert result["tool_source"] == (
        "facility_reference_downstream_activity_intent_fast_path"
    )
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["tool_calls"] == [{
        "name": server.FACILITY_ACTIVITY_PLAYBACK_TOOL,
        "args": {
            "preset": "reference_downstream_navigation",
            "prototype_mode": True,
            "maximum_actors": 8,
            "scenario_label": "Downstream operator movement candidates",
        },
    }]
    assert "Packaging follows the reviewed" in result["response"]
    assert "Nothing will be saved" in result["response"]


def test_inspection_cycle_activity_uses_deterministic_fast_path():
    layout = _circulation_department_layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    message = (
        "Play the prototype Quality Inspection activity. Each existing "
        "Inspection operator picks from the left input table, loads and "
        "inspects the part at the current laboratory workstation, records "
        "and unloads the result, places the inspected part in the right "
        "container, then returns empty to the input table and repeats. Reuse "
        "existing operators and equipment; do not duplicate placements and "
        "do not save."
    )
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=message,
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == (
        "facility_reference_downstream_activity_intent_fast_path"
    )
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["tool_calls"] == [{
        "name": server.FACILITY_ACTIVITY_PLAYBACK_TOOL,
        "args": {
            "preset": "reference_downstream_navigation",
            "prototype_mode": True,
            "maximum_actors": 8,
            "scenario_label": "Downstream operator movement candidates",
        },
    }]
    assert "Quality Inspection follows the reviewed" in result["response"]
    assert "Nothing will be saved" in result["response"]


def test_legacy_activity_refusal_precedes_broad_resource_amendment_classifier():
    layout = _circulation_department_layout()
    layout["routes"].append({
        "routeId": "rt-main-forklift",
        "label": "Main Forklift Boulevard",
        "routeKind": "forklift",
    })
    prompt = (
        "Play a prototype factory activity view using only operators, forklifts, "
        "and vehicles that are already placed in this layout. Move the selected "
        "existing operators around their assigned assembly and kitting cells, "
        "including each complete outbound walk to its FIFO point, the material "
        "handoff between the paired FIFO points, and the return walk to the "
        "operator's original station. Move the existing forklifts only on their "
        "authored direction-marked material lanes, changing to the opposite lane "
        "before each return trip. Do not add or duplicate any operator, vehicle, "
        "asset, route, or placement. Keep machines without revision-bound "
        "kinematic evidence stationary. Show the operator paths, FIFO access "
        "paths, handoff lines, and FIFO points, loop every moving actor "
        "continuously, use up to 20 actors, and keep the layout unsaved."
    )
    assert server.is_facility_program_resource_amendment_request(prompt)

    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=prompt,
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_activity_legacy_unavailable"
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["tool_calls"] == []
    assert result["facility_generation_error"] == (
        "facility_legacy_navigation_fixture_only"
    )


def test_motion_fast_path_refuses_safety_question_without_tool_call():
    layout = _circulation_department_layout()
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Does motion playback prove this forklift traffic pattern is safe?"
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_motion_refuse"
    assert result["tool_calls"] == []
    assert result["facility_generation_error"] == (
        "facility_motion_safety_authority_missing"
    )


def test_subdivision_fast_path_builds_coordinate_free_tool_call():
    layout = _circulation_department_layout()
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Divide Assembly into four equal child areas named Kitting, "
                "Mechanical Build, Electrical Build, and Test."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_subdivision_intent_fast_path"
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["tool_call_count"] == 1
    assert result["tool_calls"] == [
        {
            "name": server.G3_FACILITY_SUBDIVISION_TOOL,
            "args": {
                "parent_department": "Assembly",
                "count": 4,
                "labels": [
                    "Kitting",
                    "Mechanical Build",
                    "Electrical Build",
                    "Test",
                ],
                "proportions": [0.25, 0.25, 0.25, 0.25],
                "arrangement": "deterministic_grid",
                "orientation": "auto",
                "rows": None,
                "preserve_parent": True,
                "execution_mode": "authorized_draft_run",
            },
        }
    ]
    assert "coordinates" not in repr(result["tool_calls"]).casefold()
    assert "unsaved draft" in result["response"].casefold()


def test_g4_asset_fast_path_binds_exact_revision_without_geometry():
    layout = _circulation_department_layout()
    context = _circulation_chat_context(layout)
    context["facility_layout_state"]["assets"] = copy.deepcopy(
        list(LOCAL_ASSET_CATALOG)
    )
    machine = next(
        item for item in LOCAL_ASSET_CATALOG
        if item["assetId"] == "asset-cnc-mill"
    )
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Place two CNC Milling Machines in Assembly with their long "
                "side east-west for production."
            ),
            agent_type="deviation-analyst",
        ),
        context,
    ))

    assert result["tool_source"] == "facility_asset_intent_fast_path"
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["tool_calls"] == [
        {
            "name": server.G4_FACILITY_ASSET_PLACEMENT_TOOL,
            "args": {
                "asset_id": "asset-cnc-mill",
                "asset_definition_revision": machine[
                    "assetDefinitionRevision"
                ],
                "quantity": 2,
                "target_area": "Assembly",
                "orientation_mode": "long_side_east_west",
                "facing_direction": None,
                "resource_role": "production",
                "access_requirement": "physical_only",
                "preserve_hierarchy": True,
                "execution_mode": "authorized_draft_run",
            },
        }
    ]
    serialized = repr(result["tool_calls"]).casefold()
    assert "coordinate" not in serialized
    assert "transform" not in serialized
    assert "clearance" not in serialized
    assert "access remains unverified" in result["response"].casefold()


def test_g5_cell_fast_path_uses_authoritative_geometry_not_browser_summaries(
    facility_host,
):
    layout = _circulation_department_layout()
    machine = next(
        item for item in LOCAL_ASSET_CATALOG
        if item["assetId"] == "asset-cnc-mill"
    )
    compiled = compile_asset_placement_program(
        layout,
        [{
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
        }],
        list(LOCAL_ASSET_CATALOG),
    )
    layout = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    context = _circulation_chat_context(layout)
    context["facility_layout_state"]["assets"] = [
        {
            "assetId": item["assetId"],
            "assetDefinitionRevision": item["assetDefinitionRevision"],
            "displayName": item["displayName"],
        }
        for item in LOCAL_ASSET_CATALOG
    ]
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Arrange Assembly using the shortest feasible of line, L, "
                "and U layouts with 1 m spacing."
            ),
            agent_type="deviation-analyst",
        ),
        context,
    ))

    assert result["tool_source"] == "facility_cell_intent_fast_path"
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["tool_call_count"] == 1
    call = result["tool_calls"][0]
    assert call["name"] == server.G5_FACILITY_CELL_COMPOSITION_TOOL
    assert call["args"]["target_area"] == "Assembly"
    assert call["args"]["candidate_strategies"] == ["line", "l", "u"]
    assert call["args"]["selected_strategy"] is None
    assert call["args"]["objective"] == "shortest_travel"
    assert call["args"]["preferred_gap_meters"] == 1.0
    assert call["args"]["process_sequence_placement_ids"] == []
    serialized = repr(call).casefold()
    assert "coordinate" not in serialized
    assert "transform" not in serialized
    assert "unsaved draft" in result["response"].casefold()


def test_g6_replication_fast_path_uses_named_qualified_source_and_targets(
    facility_host,
):
    layout = _circulation_department_layout()
    machine = next(
        item for item in LOCAL_ASSET_CATALOG
        if item["assetId"] == "asset-cnc-mill"
    )
    placed = compile_asset_placement_program(
        layout,
        [{
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
        }],
        list(LOCAL_ASSET_CATALOG),
    )
    layout = apply_facility_layout_operations(
        layout,
        placed["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    composed = compile_cell_composition_program(
        layout,
        {
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
        list(LOCAL_ASSET_CATALOG),
    )
    layout = apply_facility_layout_operations(
        layout,
        composed["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Replicate Assembly into Machining and Shipping.",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_cell_module_intent_fast_path"
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["tool_call_count"] == 1
    call = result["tool_calls"][0]
    assert call["name"] == server.G6_FACILITY_CELL_REPLICATION_TOOL
    assert call["args"] == {
        "source_cell": "Assembly",
        "target_areas": ["Machining", "Shipping"],
        "copy_current_edited_state": False,
        "preserve_departments": True,
        "preserve_routes": True,
        "preserve_markings": True,
        "preserve_source_cell": True,
        "preserve_manual_and_locked": True,
        "execution_mode": "authorized_draft_run",
    }
    serialized = repr(call).casefold()
    assert "coordinate" not in serialized
    assert "transform" not in serialized
    assert "unsaved draft" in result["response"].casefold()


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            "Place one CNC Milling Machine at x=20 z=10 in Assembly.",
            "facility_asset_coordinate_ownership",
        ),
        (
            "Place one CNC Milling Machine in Assembly with whatever OSHA "
            "clearance applies.",
            "facility_asset_unsupported_compliance_claim",
        ),
    ],
)
def test_g4_asset_fast_path_refuses_geometry_and_unsupported_authority(
    message,
    code,
):
    layout = _circulation_department_layout()
    context = _circulation_chat_context(layout)
    context["facility_layout_state"]["assets"] = copy.deepcopy(
        list(LOCAL_ASSET_CATALOG)
    )
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=message,
            agent_type="deviation-analyst",
        ),
        context,
    ))

    assert result["facility_generation_error"] == code
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["tool_calls"] == []


def test_g23_network_reachability_is_answered_without_provider_or_mutation():
    layout = _circulation_point_crossing_layout()
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Can material travel from Inbound to Dispatch?",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))

    assert result["tool_source"] == "facility_circulation_network_direct"
    assert result["tool_calls"] == []
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["facility_circulation_network_analysis"]["query"][
        "reachable"
    ] is True
    assert result["response"].startswith("**Yes, Dispatch is reachable")
    assert "reachability only" in result["response"]


def test_g23_crossing_coverage_and_marking_use_exact_semantic_contract():
    layout = _circulation_point_crossing_layout()
    coverage = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Which mixed-traffic crossings are unmarked?",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))
    assert coverage["tool_source"] == "facility_circulation_network_direct"
    assert coverage["tool_calls"] == []
    assert coverage["response"].startswith("**1 of 1 mixed-traffic")

    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Add a 4 m by 3 m pedestrian crossing at the route "
                "intersection."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout),
    ))
    assert result["tool_source"] == "facility_circulation_intent_fast_path"
    assert result["tool_call_count"] == 1
    args = result["tool_calls"][0]["args"]
    assert args["action"] == "add_crossing"
    assert args["network_scope"] == "route_network"
    assert len(args["crossing_route_ids"]) == 2
    assert args["crossing_width"] == 4.0
    assert args["crossing_depth"] == 3.0
    assert args["crossing_width_unit"] == "m"
    assert args["crossing_depth_unit"] == "m"
    assert args["preserve_departments"] is True
    assert args["preserve_routes"] is True
    assert "centerline" not in repr(args).casefold()
    assert "coordinates" not in repr(args).casefold()
    assert "does not claim traffic safety" in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        "Make this a safe crossing.",
        "Is this network safe?",
        "Is this crossing safe for pedestrians?",
        "Is this aisle layout adequate?",
        "Is this route network compliant with fire code?",
        "Does this layout meet OSHA egress requirements?",
    ],
)
def test_g23_refuses_unsupported_crossing_safety_claim_without_tool_call(message):
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=message,
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(_circulation_point_crossing_layout()),
    ))

    assert result["tool_source"] == "facility_circulation_refuse"
    assert result["tool_calls"] == []
    assert result["facility_generation_error"] == (
        "facility_circulation_operational_authority_missing"
    )
    assert "cannot claim" in result["response"].casefold()
    assert "compliant" in result["response"].casefold()


def _circulation_mixed_conflict_layout():
    layout = _circulation_department_layout()
    for prompt in (
        "Add a 5 m forklift lane from Receiving to Shipping through Machining and Assembly.",
        "Add a 2 m pedestrian walkway from Machining to Assembly.",
    ):
        parsed = parse_circulation_turn(prompt, layout)
        compiled = compile_primary_circulation_operations(
            layout,
            parsed["request"],
        )
        layout = apply_facility_layout_operations(
            layout,
            compiled["operations"],
            base_revision=layout_revision(layout),
        )["document"]
    return layout


def _circulation_obstacle_layout_and_context():
    layout = _circulation_department_layout()
    parsed = parse_circulation_turn(
        "Add a 4 m material aisle from Receiving to Shipping.",
        layout,
    )
    compiled = compile_primary_circulation_operations(
        layout,
        parsed["request"],
    )
    layout = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    obstacle_context = {
        "schemaVersion": 1,
        "obstacles": [
            {
                "obstacleId": "placement:machine-agent",
                "obstacleKind": "placement_footprint",
                "boundary": [
                    {"x": 55.0, "z": 38.0},
                    {"x": 65.0, "z": 38.0},
                    {"x": 65.0, "z": 52.0},
                    {"x": 55.0, "z": 52.0},
                ],
                "evidenceStatus": "derived",
                "sourceRef": "machine-agent",
            }
        ],
        "sourceRevisions": {
            "layout": layout_revision(layout),
            "asset:machine-agent": "8" * 64,
        },
    }
    return layout, obstacle_context


def test_circulation_conflict_question_is_answered_from_exact_active_geometry():
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Where do the pedestrian and forklift routes conflict?",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(_circulation_mixed_conflict_layout()),
    ))

    assert result["tool_source"] == "facility_circulation_conflicts_direct"
    assert result["tool_calls"] == []
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["facility_circulation_analysis"][
        "mixedTrafficConflictCount"
    ] >= 1
    assert result["response"].startswith("**The active draft has")
    assert "static geometry" in result["response"]
    assert "code compliance" in result["response"]


def test_circulation_conflict_resolution_call_contains_intent_not_geometry():
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Resolve the mixed-traffic conflict with 1.5 m separation "
                "without changing the departments."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(_circulation_mixed_conflict_layout()),
    ))

    assert result["tool_source"] == "facility_circulation_intent_fast_path"
    call = result["tool_calls"][0]
    assert call == {
        "name": server.G2_FACILITY_CIRCULATION_TOOL,
        "args": {
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
            "minimum_separation": 1.5,
            "separation_unit": "m",
            "preserve_departments": True,
            "adjust_route_kind": "auto_shortest",
            "execution_mode": "authorized_draft_run",
        },
    }
    assert "centerline" not in repr(call).casefold()
    assert "coordinates" not in repr(call).casefold()
    assert "preserved" in result["response"].casefold()


def test_circulation_obstacle_question_is_answered_from_revision_bound_geometry():
    layout, obstacle_context = _circulation_obstacle_layout_and_context()
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Does this aisle intersect any machines or restricted regions?",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout, obstacle_context),
    ))

    assert result["tool_source"] == "facility_circulation_obstacles_direct"
    assert result["tool_calls"] == []
    assert result["facility_action_mode"] == "READ_ONLY"
    assert result["facility_circulation_obstacle_analysis"][
        "routeObstacleConflictCount"
    ] == 1
    assert result["response"].startswith("**The active draft has 1 route-to-obstacle")
    assert "machine-agent" in result["response"]
    assert "exact static geometry" in result["response"]
    assert "vehicle-turning approval" in result["response"]


def test_circulation_obstacle_reroute_call_contains_intent_not_geometry():
    layout, obstacle_context = _circulation_obstacle_layout_and_context()
    route_id = layout["routes"][0]["routeId"]
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=(
                "Reroute that aisle around the machine with 1 m clearance and "
                "keep the departments unchanged."
            ),
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(layout, obstacle_context),
    ))

    assert result["tool_source"] == "facility_circulation_intent_fast_path"
    assert result["tool_call_count"] == 1
    assert result["tool_calls"][0] == {
        "name": server.G2_FACILITY_CIRCULATION_TOOL,
        "args": {
            "action": "avoid_obstacles",
            "route_kind": None,
            "width": None,
            "source_unit": None,
            "source_department": None,
            "target_department": None,
            "via_departments": [],
            "direction": None,
            "label": None,
            "conflict_scope": None,
            "minimum_separation": None,
            "separation_unit": None,
            "preserve_departments": True,
            "adjust_route_kind": None,
            "obstacle_scope": "static_geometry",
            "minimum_clearance": 1.0,
            "clearance_unit": "m",
            "preserve_route_identity": True,
            "route_id": route_id,
            "vehicle_profile_id": None,
            "vehicle_profile_revision": None,
            "allow_reverse": None,
            "execution_mode": "authorized_draft_run",
        },
    }
    assert "centerline" not in repr(result["tool_calls"]).casefold()
    assert "boundary" not in repr(result["tool_calls"]).casefold()
    assert "obstacle-aware" in result["response"].casefold()


@pytest.mark.parametrize(
    ("message", "tool_source", "error_code"),
    [
        (
            "Add some aisles.",
            "facility_circulation_ask",
            "facility_circulation_width_required",
        ),
        (
            "Add whatever fire aisles the code requires.",
            "facility_circulation_refuse",
            "facility_circulation_policy_authority_missing",
        ),
        (
            "Place a 5 m material aisle at x=40, z=25.",
            "facility_circulation_refuse",
            "facility_circulation_model_geometry_refused",
        ),
        (
            "Make this aisle safe for any forklift.",
            "facility_circulation_refuse",
            "facility_circulation_vehicle_profile_required",
        ),
        (
            "Validate the turning radius using a typical warehouse forklift.",
            "facility_circulation_refuse",
            "facility_circulation_vehicle_profile_required",
        ),
        (
            "Reroute using whatever OSHA clearance applies.",
            "facility_circulation_refuse",
            "facility_circulation_policy_authority_missing",
        ),
        (
            "Put the detour at x=40 m and z=25 m.",
            "facility_circulation_refuse",
            "facility_circulation_model_geometry_refused",
        ),
    ],
)
def test_circulation_fast_path_asks_or_refuses_without_provider_call(
    message,
    tool_source,
    error_code,
):
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=message,
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(_circulation_department_layout()),
    ))

    assert result["tool_source"] == tool_source
    assert result["facility_generation_error"] == error_code
    assert result["tool_calls"] == []
    assert result["facility_action_mode"] == "READ_ONLY"


def test_circulation_follow_up_and_connectivity_use_active_draft():
    layout = _circulation_department_layout()
    create = parse_circulation_turn(
        "Add a 6 m material aisle from Receiving to Shipping through Machining.",
        layout,
    )
    compiled = compile_primary_circulation_operations(
        layout,
        create["request"],
    )
    with_route = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]

    follow_up = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Make that aisle 5 m wide and keep the same endpoints.",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(with_route),
    ))
    assert follow_up["tool_calls"][0]["args"]["action"] == "edit_recent"
    assert follow_up["tool_calls"][0]["args"]["width"] == 5.0

    connectivity = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Which departments are not connected by circulation yet?",
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(with_route),
    ))
    assert connectivity["tool_source"] == (
        "facility_circulation_connectivity_direct"
    )
    assert "Assembly" in connectivity["response"]
    assert connectivity["tool_calls"] == []


@pytest.mark.parametrize(
    "message",
    [
        (
            "What if we added a direct material route from Receiving to "
            "Shipping? Would it reduce travel by 20 percent?"
        ),
        "What would happen if we added a central aisle?",
    ],
)
def test_circulation_hypothetical_does_not_invent_a_benefit_or_change_layout(
    message,
):
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message=message,
            agent_type="deviation-analyst",
        ),
        _circulation_chat_context(_circulation_department_layout()),
    ))

    assert result["tool_source"] == "facility_circulation_read_only"
    assert result["tool_calls"] == []
    assert "no travel benefit is claimed" in result["response"].casefold()
    assert "20" not in result["response"]


def test_department_repartition_fast_path_reuses_trusted_active_program():
    result = asyncio.run(server._deterministic_semantic_chat_result(
        server.AgentChatRequest(
            message="Put two departments above and three below.",
            agent_type="deviation-analyst",
        ),
        {
            "facility_layout_state": {"identity": {"layoutId": "fl-main"}},
            "facility_layout_evidence": {},
            "facility_layout_digest": {},
            "_facility_layout_department_program": _five_department_program(),
        },
    ))

    assert result["tool_source"] == "facility_g1_repartition_fast_path"
    assert result["facility_action_mode"] == "PREVIEW"
    assert result["facility_repartition"] == {
        "source": "active_generation_run",
        "supersededRunId": "fgr-demo",
    }
    call = result["tool_calls"][0]
    assert call["name"] == server.G1_FACILITY_GENERATION_TOOL
    assert [
        row["labels"] for row in call["args"]["departments"]["rows"]
    ] == [
        ["Receiving", "Machining"],
        ["Assembly", "Inspection", "Shipping"],
    ]
    assert call["args"]["facility_envelope"]["width"] == 100.0


def test_trusted_context_binds_active_generation_run_for_follow_up(
    facility_host,
    monkeypatch,
):
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
    principal = facility_host.principal()
    current = _current(facility_host)
    run = facility_host.generation_coordinator.start_g1_run(
        tenant_id=principal.tenant_id,
        site_id=LOCAL_SITE_ID,
        workspace_id="workspace-facility-layout",
        layout_id=LOCAL_LAYOUT_ID,
        user_id=principal.principal_id,
        session_id="session-g11-follow-up",
        base_layout=current["layout"],
        base_layout_revision=current["revision"],
        envelope_request={
            "width": 100,
            "depth": 80,
            "sourceUnit": "m",
            "displayName": "Flexible Factory",
        },
        department_request={
            "count": 5,
            "labels": [
                "Receiving",
                "Machining",
                "Assembly",
                "Inspection",
                "Shipping",
            ],
            "proportions": [1, 1, 1, 1, 1],
            "arrangement": "row_stack",
            "rows": [
                {"labels": ["Receiving", "Machining"]},
                {"labels": ["Assembly", "Inspection", "Shipping"]},
            ],
        },
        execution_mode="authorized_draft_run",
        prototype_mode=True,
    )
    while run["currentStageId"]:
        run = facility_host.generation_coordinator.continue_run(
            tenant_id=principal.tenant_id,
            site_id=LOCAL_SITE_ID,
            run_id=run["runId"],
            current_base_layout=current["layout"],
            current_base_revision=current["revision"],
            explicit_stage_acceptance=False,
        )

    ctx = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": current["revision"],
        },
        "facility_layout_live_state": {
            "dirty": True,
            "editable": True,
            "generationDraft": {
                "active": True,
                "runId": run["runId"],
                "status": "complete",
                "saveEligibility": "eligible",
                "writable": True,
            },
        },
    }
    server._resolve_trusted_facility_layout_context(
        ctx,
        _facility_http_request(),
    )

    assert ctx["facility_layout_ref"]["revision"] == (
        run["draftLayoutRevision"]
    )
    assert ctx["facility_layout_state"]["identity"]["revision"] == (
        run["draftLayoutRevision"]
    )
    assert layout_revision(ctx["_facility_layout_document"]) == (
        run["draftLayoutRevision"]
    )
    program = ctx["_facility_layout_department_program"]
    assert program["source"] == "active_generation_run"
    assert program["run_id"] == run["runId"]
    assert program["facility_envelope"]["width"] == 100.0
    assert program["departments"]["labels"] == [
        "Receiving",
        "Machining",
        "Assembly",
        "Inspection",
        "Shipping",
    ]
    assert [
        row["labels"] for row in program["departments"]["rows"]
    ] == [
        ["Receiving", "Machining"],
        ["Assembly", "Inspection", "Shipping"],
    ]


def test_facility_read_only_policy_honors_requested_markdown_structure():
    base = {
        "workflow": {"id": "facility-layout-generation"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {
            "output": {
                "format": "concise_facility_layout_proposal",
                "maximum_sentences": 6,
            }
        },
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        "Review every zone in the current facility layout as a table.",
    )
    assert constrained["resolved_policy"]["output"] == {
        "format": "complete_zone_inventory_review",
        "maximum_sentences": 24,
    }
    assert "requested Markdown heading" in constrained["prompt"]
    assert "one Markdown table row for every object" in constrained["prompt"]
    assert "Never group, merge, collapse" in constrained["prompt"]


def test_facility_markdown_review_preserves_heading_and_numbered_list():
    plan = {
        "resolved_policy": {
            "output": {
                "format": "complete_zone_inventory_review",
                "maximum_sentences": 24,
            }
        }
    }
    raw = "# Review\n\n| Zone | Purpose |\n|---|---|\n| A | Work |\n\n1. First\n2. Second\n3. Third"
    assert server._skill_response_preserves_markdown(plan) is True
    assert server._clean_agent_answer(
        raw,
        {},
        "review zones",
        preserve_markdown=True,
    ) == raw


def test_complete_zone_inventory_receives_larger_output_budget():
    plan = {
        "runtime_tool_policy": {"mode": "read_only_analysis"},
    }
    assert server._agent_response_max_tokens(
        plan,
        "Review the current facility layout and list every zone.",
    ) == 4096
    assert server._agent_response_max_tokens(
        plan,
        "Where is the receiving zone?",
    ) == 4096


def test_facility_context_renderer_includes_trusted_compiled_fields():
    rendered = server._build_context_message({
        "facility_layout_digest": {"counts": {"zones": 2}},
        "facility_layout_state": {"zones": [{"zoneId": "zone-a"}]},
        "facility_layout_evidence": {"records": [{"id": "evidence-a"}]},
    })
    assert "[FACILITY LAYOUT DIGEST - TRUSTED SAVED REVISION]" in rendered
    assert "[FACILITY LAYOUT STATE - TRUSTED SAVED GEOMETRY]" in rendered
    assert (
        "[FACILITY LAYOUT EVIDENCE - TRUSTED VALIDATION SOURCES]"
        in rendered
    )


def test_zone_inventory_projection_returns_every_zone_with_contents():
    message = (
        "Review the current facility layout and list each zone and its purpose."
    )
    assert is_zone_inventory_request(message) is True
    digest = {
        "identity": {"layoutId": "layout-a"},
        "counts": {"zones": 3, "placements": 2},
        "zoneSummaries": [{"zoneId": "zone-a"}],
        "assetUsage": [{"assetId": "asset-a"}],
    }
    state = {
        "zones": [
            {"zoneId": "zone-c", "label": "Shipping", "zoneType": "workcell"},
            {"zoneId": "zone-a", "label": "Assembly", "zoneType": "workcell"},
            {"zoneId": "zone-b", "label": "Machining", "zoneType": "workcell"},
        ],
        "placements": [
            {"category": "Machines", "zoneIds": ["zone-b"]},
            {"category": "Storage", "zoneIds": ["zone-c"]},
        ],
    }
    projected = build_zone_inventory_digest(digest, state)
    assert [item["label"] for item in projected["zoneSummaries"]] == [
        "Assembly",
        "Machining",
        "Shipping",
    ]
    assert projected["zoneSummaries"][1]["placementCount"] == 1
    assert projected["zoneSummaries"][1]["assetCategories"] == {
        "Machines": 1
    }
    assert projected["truncation"]["zoneSummaries"] == {
        "returnedCount": 3,
        "omittedCount": 0,
    }


def test_facility_analysis_digest_separates_departments_from_subzones():
    state = {
        "zones": [
            {
                "zoneId": "dept-machining",
                "label": "Machining Hall",
                "boundary": [
                    {"x": 0, "z": 0},
                    {"x": 20, "z": 0},
                    {"x": 20, "z": 20},
                    {"x": 0, "z": 20},
                ],
            },
            {
                "zoneId": "cell-a",
                "label": "Manufacturing Cell A01",
                "boundary": [
                    {"x": 2, "z": 2},
                    {"x": 8, "z": 2},
                    {"x": 8, "z": 8},
                    {"x": 2, "z": 8},
                ],
            },
            {
                "zoneId": "dept-automation",
                "label": "Automation + Robot cells",
                "boundary": [
                    {"x": 30, "z": 0},
                    {"x": 50, "z": 0},
                    {"x": 50, "z": 20},
                    {"x": 30, "z": 20},
                ],
            },
        ],
        "placements": [
            {
                "category": "Machines",
                "zoneIds": ["dept-machining", "cell-a"],
            },
            {
                "category": "Automation",
                "zoneIds": ["dept-automation"],
            },
        ],
    }
    projected = build_facility_analysis_digest(
        {"counts": {"zones": 3, "placements": 2}},
        state,
    )

    assert projected["counts"]["departments"] == 2
    assert [item["label"] for item in projected["departmentSummaries"]] == [
        "Machining Hall",
        "Automation + Robot cells",
    ]
    cell = next(
        item
        for item in projected["zoneIndex"]
        if item["zoneId"] == "cell-a"
    )
    assert cell["scopeKind"] == "subzone"
    assert cell["parentZoneId"] == "dept-machining"
    assert projected["canonicalUtf8Bytes"] <= 32_768


def test_facility_follow_up_resolver_carries_only_read_only_scope():
    history = [
        {
            "role": "user",
            "content": "Compare the Machining Hall and Automation zone in a table.",
        },
        {
            "role": "assistant",
            "content": "Would you like the category breakdown?",
        },
    ]
    assert resolve_facility_layout_turn(
        "yes",
        recent_turns=history,
    ) == "analysis"
    assert resolve_facility_layout_turn(
        "show a pareto chart not a bar chart?",
        recent_turns=history,
    ) == "analysis"
    assert resolve_facility_layout_turn(
        "Show percentage labels and hide the value labels.",
        recent_turns=history,
    ) == "analysis"
    assert resolve_facility_layout_turn(
        "Keep the legend, sort descending, and regenerate it.",
        recent_turns=history,
    ) == "analysis"
    assert resolve_facility_layout_turn("hi") == "unrelated"

    generation_history = [
        {
            "role": "user",
            "content": "Build a new facility layout preview.",
        }
    ]
    assert resolve_facility_layout_turn(
        "yes",
        recent_turns=generation_history,
    ) == "analysis"


def test_facility_request_kind_and_metric_are_exact_and_independent():
    assert classify_facility_request_kind(
        "Review this facility without changing anything."
    ) == "inspect"
    assert classify_facility_request_kind(
        "Measure the five smallest edge-to-edge clearances."
    ) == "measure"
    assert classify_facility_request_kind(
        "Compare Assembly Cell A01 with an L-shaped alternative."
    ) == "simulate"
    assert classify_facility_request_kind(
        "Move the selected machine 10 ft east and preserve its rotation."
    ) == "exact_transform"
    assert classify_facility_request_kind("Take me to Cell A08.") == "navigate"
    assert classify_facility_request_kind(
        "Chart operational utilization by department."
    ) == "render"
    assert requested_facility_metric(
        "Chart operational utilization by department."
    ) == "department_operational_utilization"
    assert requested_facility_metric(
        "Show equipment footprint occupancy by department."
    ) == "department_physical_occupancy"
    assert requested_facility_metric(
        "Show a pie chart by floor area for the six departments."
    ) == "department_gross_area"
    assert requested_facility_metric(
        "How many assets are in each department?"
    ) == "placement_count"


def test_intent_scoped_orchestration_never_leaks_preview_or_viewport_tools():
    cases = {
        "inspect": INSPECT_TOOLS,
        "measure": MEASURE_TOOLS,
        "compare": COMPARE_TOOLS,
        "recommend": RECOMMEND_TOOLS,
        "render": RENDER_TOOLS,
    }
    for intent, expected in cases.items():
        plan = build_facility_orchestration_plan(
            operation_intent=intent,
            action_mode="READ_ONLY",
            available_read_tools=READ_TOOLS,
            presentation_tools=PRESENTATION_TOOLS,
            preview_tool_name=SEMANTIC_FACILITY_PREVIEW_TOOL,
            move_tool_name=SEMANTIC_FACILITY_MOVE_TOOL,
        )
        assert set(plan["allowedToolNames"]) == expected
        assert SEMANTIC_FACILITY_PREVIEW_TOOL not in plan["allowedToolNames"]
        assert SEMANTIC_FACILITY_MOVE_TOOL not in plan["allowedToolNames"]
        assert plan["viewportNavigationAuthorized"] is False
        assert all(
            contract["mutates"] is False
            for contract in plan["toolContracts"].values()
        )


def test_recommendation_mode_requires_explicit_simulation_transition():
    recommend = server._apply_facility_layout_request_tool_policy(
        {
            "workflow": {"id": "facility-layout-generation"},
            "prompt": "base",
            "allowed_tools": [],
        },
        "What three changes would you recommend for Machining?",
    )
    simulate = server._apply_facility_layout_request_tool_policy(
        {
            "workflow": {"id": "facility-layout-generation"},
            "prompt": "base",
            "allowed_tools": [],
        },
        "Show me what the first alternative would look like in a ghost preview.",
    )

    assert recommend["runtime_tool_policy"]["requestKind"] == "recommend"
    assert set(recommend["allowed_tools"]) == RECOMMEND_TOOLS
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in recommend["allowed_tools"]
    assert simulate["runtime_tool_policy"]["requestKind"] == "simulate"
    assert SEMANTIC_FACILITY_PREVIEW_TOOL in simulate["allowed_tools"]


def test_exact_translation_parser_produces_only_bounded_semantic_delta():
    assert parse_precise_facility_translation(
        "Move the selected machine 10 ft east and preserve its rotation."
    ) == {
        "use_current_selection": True,
        "direction": "east",
        "distance": 10.0,
        "unit": "ft",
        "preserve_rotation": True,
    }
    assert parse_precise_facility_translation(
        "Move and rotate the selected machine 10 ft east."
    ) is None


def test_orchestration_trace_reports_policy_without_internal_reasoning():
    plan = build_facility_orchestration_plan(
        operation_intent="measure",
        action_mode="READ_ONLY",
        available_read_tools=READ_TOOLS,
        presentation_tools=PRESENTATION_TOOLS,
        preview_tool_name=SEMANTIC_FACILITY_PREVIEW_TOOL,
        move_tool_name=SEMANTIC_FACILITY_MOVE_TOOL,
        spatial_analyses=("route_widths",),
    )
    trace = facility_orchestration_trace(
        plan,
        resolved_entity_ids=("route-main",),
        tool_calls=(
            {"name": "analyze_facility_spatial"},
            {"name": SEMANTIC_FACILITY_PREVIEW_TOOL},
        ),
        evidence_completeness={"complete": True},
    )

    assert trace["operationIntent"] == "measure"
    assert trace["resolvedEntityIds"] == ["route-main"]
    assert trace["toolCalls"] == [
        {"name": "analyze_facility_spatial", "allowed": True},
        {"name": SEMANTIC_FACILITY_PREVIEW_TOOL, "allowed": False},
    ]
    assert "reasoning" not in json.dumps(trace).casefold()


def test_affirmative_resolves_one_pending_read_only_facility_task():
    history = [
        {
            "role": "user",
            "content": (
                "Which assembly cell has the least operator walking?"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "I can retrieve the four assembly-cell coordinates and "
                "calculate the walking-distance comparison. Should I do that?"
            ),
        },
    ]
    pending = resolve_facility_pending_follow_up(
        "yes",
        recent_turns=history,
    )
    assert pending == {
        "priorUserRequest": (
            "Which assembly cell has the least operator walking?"
        ),
        "assistantOffer": (
            "I can retrieve the four assembly-cell coordinates and calculate "
            "the walking-distance comparison. Should I do that?"
        ),
        "ambiguous": False,
        "actionMode": "READ_ONLY",
    }
    assert resolve_facility_pending_follow_up(
        "yes",
        recent_turns=[history[0]],
    ) is None


def test_pending_operation_store_resumes_and_expires_server_side():
    now = [100.0]
    store = FacilityPendingOperationStore(
        ttl_seconds=30,
        max_sessions=2,
        clock=lambda: now[0],
    )
    assert store.put(
        "session-a",
        {
            "goal": "Which assembly cell has the least operator walking?",
            "operationIntent": "measure",
            "referencedEntityIds": ["cell-a01", "cell-a02"],
            "awaiting": "confirmation",
        },
    ) is True
    assert store.get("session-a") == {
        "goal": "Which assembly cell has the least operator walking?",
        "operationIntent": "measure",
        "actionMode": "READ_ONLY",
        "referencedEntityIds": ["cell-a01", "cell-a02"],
        "requiredEvidence": [],
        "awaiting": "confirmation",
    }
    now[0] = 131.0
    assert store.get("session-a") is None


def test_structured_pending_yes_restores_intent_and_never_write_access(
    monkeypatch,
):
    server._FACILITY_PENDING_OPERATION_STORE.reset()
    assert server._FACILITY_PENDING_OPERATION_STORE.put(
        "facility-pending-session",
        {
            "goal": "Which assembly cell has the least operator walking?",
            "operationIntent": "measure",
            "awaiting": "confirmation",
        },
    ) is True
    constrained = server._apply_facility_layout_request_tool_policy(
        {
            "workflow": {"id": "facility-layout-analysis"},
            "prompt": "base",
            "allowed_tools": [],
        },
        "yes",
        session_id="facility-pending-session",
    )

    assert constrained["runtime_tool_policy"]["requestKind"] == "measure"
    assert set(constrained["allowed_tools"]) == MEASURE_TOOLS
    assert constrained["runtime_tool_policy"]["orchestration"][
        "pendingOperation"
    ]["goal"].startswith("Which assembly cell")
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in constrained["allowed_tools"]
    assert SEMANTIC_FACILITY_MOVE_TOOL not in constrained["allowed_tools"]
    server._FACILITY_PENDING_OPERATION_STORE.reset()


def test_complete_zone_inventory_markdown_has_one_row_per_zone():
    message = (
        "Review the facility layout in a table listing each zone and its "
        "purpose, then give three checks."
    )
    assert is_complete_zone_table_request(message) is True
    digest = {
        "counts": {
            "zones": 3,
            "placements": 2,
            "floorMarkings": 4,
            "routes": 1,
        },
        "unresolvedAuthorityGaps": [
            {"code": "policy_missing", "message": "Policy is missing."},
            {"code": "shell_unverified", "message": "Shell is unverified."},
        ],
    }
    state = {
        "zones": [
            {"zoneId": "c", "label": "Shipping"},
            {"zoneId": "a", "label": "Assembly Cell A01"},
            {"zoneId": "b", "label": "Machining Hall"},
        ],
        "placements": [
            {"category": "Machines", "zoneIds": ["b"]},
            {"category": "Storage", "zoneIds": ["c"]},
        ],
    }
    rendered = build_zone_inventory_markdown(
        digest,
        state,
        {"records": []},
    )
    lines = rendered.splitlines()
    table_lines = [line for line in lines if line.startswith("|")]
    numbered = [line for line in lines if re.match(r"^[1-3]\. ", line)]
    assert lines[0] == "# Facility Layout Review"
    assert len(table_lines) - 2 == 3
    assert "| Assembly Cell A01 |" in rendered
    assert "| Machining Hall |" in rendered
    assert "| Shipping |" in rendered
    assert len(numbered) == 3


@pytest.mark.parametrize(
    "message",
    [
        (
            "Compare Assembly Cell A01 and Assembly Cell A02 in a table "
            "with each cell's exact gross area."
        ),
        "Show all six departments and their floor areas in a table.",
        (
            "Create a complete area table for Machining Hall and state each "
            "metric's evidence class."
        ),
    ],
)
def test_targeted_semantic_tables_do_not_use_complete_zone_inventory_fast_path(
    message,
):
    assert is_complete_zone_table_request(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "List all zones and their purposes in a table.",
        "Show a complete zone inventory table.",
        "Create a full list of the authored zones in a table.",
    ],
)
def test_explicit_all_zone_tables_keep_the_inventory_fast_path(message):
    assert is_complete_zone_table_request(message) is True


def test_complete_zone_table_uses_read_only_deterministic_chat_path():
    request = server.AgentChatRequest(
        message=(
            "Review the current facility layout without changing it. Use a "
            "heading, a table listing each zone and its purpose, and a "
            "numbered list of the three highest-priority layout checks."
        ),
        agent_type="deviation-analyst",
    )
    digest = {"counts": {"zones": 1}}
    state = {"zones": [{"zoneId": "zone-a", "label": "Machining Hall"}]}
    result = asyncio.run(
        server._deterministic_semantic_chat_result(
            request,
            {
                "facility_layout_digest": digest,
                "facility_layout_state": state,
                "facility_layout_evidence": {
                    "records": [],
                    "unresolvedFacts": [],
                },
            },
        )
    )
    assert result is not None
    assert result["tool_source"] == "facility_layout_read_only_direct"
    assert result["tool_call_count"] == 0
    assert result["facility_layout_review"] == {
        "mode": "complete_zone_inventory",
        "zone_count": 1,
        "saved_layout_unchanged": True,
    }
    assert result["response"].startswith("# Facility Layout Review\n")


def test_facility_design_objective_bypasses_legacy_semantic_fast_paths():
    request = server.AgentChatRequest(
        message=(
            "Reduce loaded material travel from Machining Output FIFO to "
            "Inspection Input FIFO. Keep CNC Mill 03 and Inspection Station "
            "02 fixed. You may move Output Buffer A and Input Buffer B, and "
            "you may reroute Material Transfer Aisle and Main Boulevard. Use "
            "the reviewed 24 loaded trips per Day Shift."
        ),
        agent_type="deviation-analyst",
    )
    ctx = {
        "facility_layout_digest": {"counts": {"routes": 2}},
        "facility_layout_state": {
            "routes": [
                {"routeId": "route-material-transfer"},
                {"routeId": "route-main-boulevard"},
            ],
        },
    }

    result = asyncio.run(
        server._deterministic_semantic_chat_result(request, ctx)
    )

    assert result is None
    assert "facility_layout_state" in ctx


def _facility_design_semantic_layout() -> dict:
    return {
        "placements": [
            {
                "placementId": "pl-source",
                "metadata": {
                    "instanceLabel": "Output Buffer A",
                    "semanticAliases": ["Machining Output FIFO"],
                },
            },
            {
                "placementId": "pl-target",
                "metadata": {
                    "instanceLabel": "Input Buffer B",
                    "semanticAliases": ["Inspection Input FIFO"],
                },
            },
            {
                "placementId": "pl-cnc",
                "metadata": {"instanceLabel": "CNC Mill 03"},
            },
            {
                "placementId": "pl-inspection",
                "metadata": {"instanceLabel": "Inspection Station 02"},
            },
        ],
        "routes": [
            {"routeId": "rt-transfer", "label": "Material Transfer Aisle"},
            {"routeId": "rt-main", "label": "Main Boulevard"},
            {"routeId": "rt-input", "label": "Input Approach Aisle"},
        ],
        "zones": [],
    }


def test_facility_design_exact_create_bypasses_provider_round_trip():
    layout = _facility_design_semantic_layout()
    request = server.AgentChatRequest(
        message=(
            "Reduce loaded material travel from Machining Output FIFO to "
            "Inspection Input FIFO. Keep CNC Mill 03 and Inspection Station "
            "02 fixed. You may move Output Buffer A and Input Buffer B, and "
            "you may reroute Material Transfer Aisle, Main Boulevard, and "
            "Input Approach Aisle. Use the reviewed 24 loaded trips per Day "
            "Shift."
        ),
        agent_type="deviation-analyst",
    )

    result = asyncio.run(server._deterministic_semantic_chat_result(
        request,
        {"_facility_layout_document": layout},
    ))

    assert result["tool_source"] == "facility_design_deterministic_create"
    assert [call["name"] for call in result["tool_calls"]] == [
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
    ]
    intent = result["tool_calls"][0]["args"]
    assert intent["source_label"] == "Machining Output FIFO"
    assert intent["target_label"] == "Inspection Input FIFO"
    assert intent["locked_entity_labels"] == [
        "CNC Mill 03",
        "Inspection Station 02",
    ]
    assert intent["movable_placement_labels"] == [
        "Output Buffer A",
        "Input Buffer B",
    ]
    assert intent["mutable_route_labels"] == [
        "Material Transfer Aisle",
        "Main Boulevard",
        "Input Approach Aisle",
    ]
    assert intent["loaded_trips_per_shift"] == 24
    assert intent["shift_name"] == "Day Shift"
    assert result["facility_runtime_policy"]["allowedToolNames"] == [
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
    ]


@pytest.mark.parametrize(
    "constraint_text",
    [
        (
            "Keep CNC Mill 03 and Inspection Station 02 fixed. You may move "
            "Output Buffer A or Input Buffer B, but not both."
        ),
        (
            "Keep CNC Mill 03 and Inspection Station 02 fixed. You may move "
            "Output Buffer A by at most 1 meter."
        ),
        (
            "Keep CNC Mill 03 and Unknown Press fixed. You may move Output "
            "Buffer A and Input Buffer B."
        ),
    ],
)
def test_facility_design_partial_initial_meaning_falls_back_to_provider(
    constraint_text,
):
    request = server.AgentChatRequest(
        message=(
            "Reduce loaded material travel from Machining Output FIFO to "
            "Inspection Input FIFO. "
            + constraint_text
            + " You may reroute Material Transfer Aisle, Main Boulevard, and "
            "Input Approach Aisle. Use the reviewed 24 loaded trips per Day "
            "Shift."
        ),
        agent_type="deviation-analyst",
    )

    result = asyncio.run(server._deterministic_semantic_chat_result(
        request,
        {"_facility_layout_document": _facility_design_semantic_layout()},
    ))

    assert result is None


def test_facility_design_mixed_lock_correction_falls_back_to_provider():
    state = _facility_design_context()["facility_design_state"]
    state["referents"] = [
        {"phrase": "Output Buffer A", "status": "active"},
        {"phrase": "Input Buffer B", "status": "active"},
    ]
    request = server.AgentChatRequest(
        message=(
            "Keep Output Buffer A fixed, but Input Buffer B can move."
        ),
        agent_type="deviation-analyst",
    )

    result = asyncio.run(server._deterministic_semantic_chat_result(
        request,
        {"facility_design_state": state},
    ))

    assert result is None


def test_facility_design_exact_correction_bypasses_provider_round_trip():
    state = _facility_design_context()["facility_design_state"]
    state["referents"] = [{
        "phrase": "Main Boulevard",
        "status": "active",
    }]
    request = server.AgentChatRequest(
        message="Keep the current Main Boulevard fixed too.",
        agent_type="deviation-analyst",
    )

    result = asyncio.run(server._deterministic_semantic_chat_result(
        request,
        {"facility_design_state": state},
    ))

    assert result["tool_source"] == "facility_design_deterministic_correction"
    assert [call["name"] for call in result["tool_calls"]] == [
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
    ]
    assert result["tool_calls"][0]["args"]["target_labels"] == [
        "Main Boulevard"
    ]
    assert result["tool_calls"][0]["args"]["brief_id"] == "fdbf-active"
    assert result["tool_calls"][0]["args"][
        "expected_brief_revision"
    ] == "a" * 64
    assert result["facility_runtime_policy"]["mode"] == "PREVIEW"
    assert result["facility_runtime_policy"]["allowedToolNames"] == [
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
    ]


def test_facility_design_rather_than_preference_keeps_intended_priority():
    request = server.AgentChatRequest(
        message=(
            "Rather than the shortest route, prefer fewer equipment moves."
        ),
        agent_type="deviation-analyst",
    )

    result = asyncio.run(server._deterministic_semantic_chat_result(
        request,
        _facility_design_context(),
    ))

    assert result["tool_source"] == "facility_design_deterministic_correction"
    assert result["tool_calls"][0]["args"]["preference_metric_ids"] == [
        "movedPlacementCount",
        "loadedRouteDistanceMeters",
    ]


def test_facility_design_exact_apply_bypasses_provider_round_trip():
    request = server.AgentChatRequest(
        message="Apply the corrected proposal. Do not save it.",
        agent_type="deviation-analyst",
    )

    result = asyncio.run(server._deterministic_semantic_chat_result(
        request,
        _facility_design_context(),
    ))

    assert result["tool_source"] == "facility_design_deterministic_apply"
    assert result["tool_calls"] == [{
        "name": server.APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL,
        "args": {
            "proposal_id": "fdlp-selected",
            "proposal_revision": "b" * 64,
        },
    }]
    assert result["facility_runtime_policy"]["mode"] == "PREVIEW"
    assert result["facility_runtime_policy"]["allowedToolNames"] == [
        server.APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL,
    ]


def test_facility_design_brief_is_an_executable_trusted_provider_read():
    state = {
        "briefId": "fdbf-provider-read",
        "briefRevision": "a" * 64,
        "status": "active",
        "objective": {"objectiveKind": "reduce_loaded_material_travel"},
        "hardConstraints": [{"constraintId": "lock-main-boulevard"}],
        "preferences": [],
        "permittedChanges": [],
        "unknowns": [],
        "referents": [],
        "proposals": [{"proposalId": "fdlp-a"}],
        "selectedProposal": {"proposalId": "fdlp-a"},
    }

    result = server._trusted_facility_design_brief_observation(
        {"facility_design_state": state},
        {
            "brief_id": state["briefId"],
            "brief_revision": state["briefRevision"],
        },
    )

    assert (
        server.INSPECT_FACILITY_DESIGN_BRIEF_TOOL
        in server._FACILITY_LAYOUT_READ_TOOL_NAMES
    )
    assert result["authoritative"] is True
    assert result["briefRevision"] == state["briefRevision"]
    assert result["hardConstraints"] == state["hardConstraints"]
    assert result["proposalCount"] == 1
    assert result["savedLayoutChanged"] is False


def _facility_design_prompt_plan(action: str) -> dict:
    return {
        "workflow": {"id": "facility-layout-generation"},
        "runtime_tool_policy": {
            "mode": "facility_design_loop",
            "designAction": action,
        },
        "allowed_tools": sorted(
            server.facility_design_allowed_tools(
                action,
                apply_enabled=True,
            )
        ),
    }


def _facility_design_context() -> dict:
    return {
        "facility_design_state": {
            "briefId": "fdbf-active",
            "briefRevision": "a" * 64,
            "runId": "fdlr-active",
            "selectedProposal": {
                "proposalId": "fdlp-selected",
                "proposalRevision": "b" * 64,
            },
        }
    }


def test_facility_design_update_is_paired_with_preview_in_execution_order():
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [{
            "name": server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
            "args": {
                "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                "operation": "add_geometry_locks",
                "target_labels": ["Main Boulevard"],
            },
        }],
        _facility_design_prompt_plan("update_and_preview"),
        _facility_design_context(),
        "Keep the current Main Boulevard fixed too.",
        "deviation-analyst",
    )

    assert [call["name"] for call in calls] == [
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
    ]
    assert calls[0]["args"]["brief_id"] == "fdbf-active"
    assert calls[0]["args"]["expected_brief_revision"] == "a" * 64
    assert calls[1]["args"] == {"mode": "production_sage"}
    assert "facility_design_preview_paired_with_update" in warnings
    assert changed is True


def test_facility_design_initial_split_calls_recover_from_exact_user_labels():
    layout = {
        "placements": [
            {
                "placementId": "pl-source",
                "metadata": {
                    "instanceLabel": "Output Buffer A",
                    "semanticAliases": ["Machining Output FIFO"],
                },
            },
            {
                "placementId": "pl-target",
                "metadata": {
                    "instanceLabel": "Input Buffer B",
                    "semanticAliases": ["Inspection Input FIFO"],
                },
            },
            {
                "placementId": "pl-cnc",
                "metadata": {"instanceLabel": "CNC Mill 03"},
            },
            {
                "placementId": "pl-inspection",
                "metadata": {"instanceLabel": "Inspection Station 02"},
            },
        ],
        "routes": [
            {"routeId": "rt-transfer", "label": "Material Transfer Aisle"},
            {"routeId": "rt-main", "label": "Main Boulevard"},
        ],
        "zones": [],
    }
    message = (
        "Reduce loaded material travel from Machining Output FIFO to "
        "Inspection Input FIFO. Keep CNC Mill 03 and Inspection Station 02 "
        "fixed. You may move Output Buffer A and Input Buffer B, and you may "
        "reroute Material Transfer Aisle and Main Boulevard. Use 24 loaded "
        "trips per Day Shift. Show alternatives, but do not apply anything."
    )
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [
            {
                "name": server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
                "args": {
                    "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                    "operation": "create_material_travel_brief",
                    "source_label": "Machining Output FIFO",
                },
            },
            {
                "name": server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
                "args": {"mode": "production_sage"},
            },
        ],
        _facility_design_prompt_plan("create_and_preview"),
        {"_facility_layout_document": layout},
        message,
        "deviation-analyst",
    )

    assert [call["name"] for call in calls] == [
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
    ]
    recovered = calls[0]["args"]
    assert recovered["source_label"] == "Machining Output FIFO"
    assert recovered["target_label"] == "Inspection Input FIFO"
    assert recovered["locked_entity_labels"] == [
        "CNC Mill 03",
        "Inspection Station 02",
    ]
    assert recovered["movable_placement_labels"] == [
        "Output Buffer A",
        "Input Buffer B",
    ]
    assert recovered["mutable_route_labels"] == [
        "Material Transfer Aisle",
        "Main Boulevard",
    ]
    assert recovered["loaded_trips_per_shift"] == 24
    assert recovered["shift_name"] == "Day Shift"
    assert "facility_design_create_grounded_from_user_turn" in warnings
    assert changed is True


def test_facility_design_split_lock_updates_merge_before_one_preview():
    raw_calls = [
        {
            "name": server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
            "args": {"mode": "production_sage"},
        },
        *[
            {
                "name": server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
                "args": {
                    "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                    "operation": "add_geometry_locks",
                    "target_labels": [label],
                },
            }
            for label in ("Main Boulevard", "Output Buffer A")
        ],
    ]
    calls, warnings, _changed = (
        server.ensure_facility_layout_preview_tool_call(
            raw_calls,
            _facility_design_prompt_plan("update_and_preview"),
            _facility_design_context(),
            "Keep Main Boulevard and Output Buffer A fixed.",
            "deviation-analyst",
        )
    )

    assert [call["name"] for call in calls] == [
        server.UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
    ]
    assert calls[0]["args"]["target_labels"] == [
        "Main Boulevard",
        "Output Buffer A",
    ]
    assert "facility_design_split_update_merged" in warnings


def test_facility_design_correction_understands_plural_locks_and_loaded_route():
    context = _facility_design_context()
    context["facility_design_state"]["referents"] = [
        {"phrase": "Output Buffer A", "status": "active"},
        {"phrase": "Input Buffer B", "status": "active"},
    ]
    lock = server.recover_facility_design_update_intent(
        "Keep both Output Buffer A and Input Buffer B exactly where they are.",
        active_design=context["facility_design_state"],
    )
    preference = server.recover_facility_design_update_intent(
        "Prefer the shortest loaded route over fewer equipment moves.",
        active_design=context["facility_design_state"],
    )

    assert lock["target_labels"] == ["Output Buffer A", "Input Buffer B"]
    assert preference["preference_metric_ids"] == [
        "loadedRouteDistanceMeters",
        "movedPlacementCount",
    ]


def test_facility_design_preview_does_not_run_without_valid_correction():
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [{
            "name": server.RUN_FACILITY_DESIGN_PREVIEW_TOOL,
            "args": {"mode": "production_sage"},
        }],
        _facility_design_prompt_plan("update_and_preview"),
        _facility_design_context(),
        "Keep Output Buffer A fixed.",
        "deviation-analyst",
    )

    assert calls == []
    assert "facility_design_update_required_before_preview" in warnings
    assert changed is False


def test_facility_design_apply_uses_repository_selected_proposal():
    calls, warnings, changed = server.ensure_facility_layout_preview_tool_call(
        [],
        _facility_design_prompt_plan("apply"),
        _facility_design_context(),
        "Apply the corrected proposal. Do not save it.",
        "deviation-analyst",
    )

    assert calls == [{
        "name": server.APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL,
        "args": {
            "proposal_id": "fdlp-selected",
            "proposal_revision": "b" * 64,
        },
    }]
    assert warnings == []
    assert changed is True


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Review the current facility design.", False),
        ("Do not add machines; list the current layout zones.", False),
        ("Design a new factory layout.", True),
        ("Lay out these machines in two rows.", True),
        ("Review and improve the current Facility Layout.", True),
        ("Review the layout and show a ghost preview.", True),
        ("Build a Facility Layout preview and do not commit it.", True),
    ],
)
def test_facility_generation_intent_distinguishes_review_from_editing(
    message,
    expected,
):
    assert server._is_facility_layout_generation_request(message) is expected


@pytest.mark.parametrize(
    "message",
    [
        "Can we add another CNC to Machining Hall?",
        "Could we add one more station to this cell?",
        "Can Cell A03 increase capacity?",
        "Can this department accommodate another rack?",
    ],
)
def test_facility_fit_questions_remain_read_only(message):
    assert server._required_facility_layout_workflow(message) == (
        "facility-layout-analysis"
    )
    assert server._is_facility_layout_generation_request(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "Add another CNC to Machining Hall.",
        "Can you add another CNC to Machining Hall?",
        "Could you place one more station in this cell?",
    ],
)
def test_explicit_facility_change_requests_retain_preview_authority(message):
    assert server._required_facility_layout_workflow(message) == (
        "facility-layout-generation"
    )
    assert server._is_facility_layout_generation_request(message) is True


def test_facility_preview_backstop_drops_provider_call_for_read_only_turn():
    message = "Review the current facility layout without changing it."
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [{
                "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
                "args": {"semantic_plan": {}},
            }],
            {
                "workflow": {"id": "facility-layout-generation"},
                "runtime_tool_policy": {"mode": "read_only_observation"},
            },
            {},
            message,
            "deviation-analyst",
        )
    )
    assert calls == []
    assert warnings == ["facility_preview_dropped_read_only"]
    assert changed is False


def test_compiled_facility_policy_drops_low_level_writes_and_extra_previews():
    plan = {
        "workflow": {"id": "facility-layout-generation"},
        "runtime_tool_policy": {"mode": "semantic_generation"},
        "allowed_tools": [
            "search_industrial_assets",
            SEMANTIC_FACILITY_PREVIEW_TOOL,
        ],
    }
    calls = [
        {"name": "search_industrial_assets", "args": {"query": "rack"}},
        {"name": "move_placement", "args": {"x": 9, "z": 4}},
        {
            "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
            "args": {"semantic_plan": {}},
        },
        {
            "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
            "args": {"semantic_plan": {"duplicate": True}},
        },
    ]
    guarded, warnings = server.apply_compiled_skill_tool_policy(calls, plan)
    assert [item["name"] for item in guarded] == [
        "search_industrial_assets",
        SEMANTIC_FACILITY_PREVIEW_TOOL,
    ]
    assert any("move_placement" in item for item in warnings)
    assert len(
        [
            item
            for item in guarded
            if item["name"] == SEMANTIC_FACILITY_PREVIEW_TOOL
        ]
    ) == 1


def test_openai_enforces_the_closed_facility_preview_schema():
    native = server.build_native_tool_specs(
        "deviation-analyst",
        allowed_tools={SEMANTIC_FACILITY_PREVIEW_TOOL},
    )
    translated = server._openai_native_tool_specs(native)
    assert len(translated) == 1
    assert translated[0]["name"] == SEMANTIC_FACILITY_PREVIEW_TOOL
    assert translated[0]["strict"] is True
    parameters = translated[0]["parameters"]
    assert parameters["additionalProperties"] is False
    semantic = parameters["properties"]["semantic_plan"]
    assert semantic["additionalProperties"] is False
    assert set(semantic["properties"]) == set(semantic["required"])


def test_chat_visualization_tool_is_strict_and_presentation_only():
    native = server.build_native_tool_specs(
        "deviation-analyst",
        allowed_tools={server.CHAT_VISUALIZATION_TOOL},
    )
    translated = server._openai_native_tool_specs(native)
    assert len(translated) == 1
    assert translated[0]["name"] == server.CHAT_VISUALIZATION_TOOL
    assert translated[0]["strict"] is True
    assert translated[0]["parameters"]["additionalProperties"] is False

    remaining, blocks, warnings = server.extract_chat_presentation_blocks([
        {
            "name": server.CHAT_VISUALIZATION_TOOL,
            "args": {
                "chart_type": "bar",
                "title": "Placed assets by department",
                "subtitle": "Trusted saved layout",
                "unit": "placements",
                "data": [
                    {
                        "label": "Machining Hall",
                        "value": 42,
                        "entity_id": "zone-machining",
                        "series": None,
                    },
                    {
                        "label": "Assembly + Kitting",
                        "value": 31,
                        "entity_id": "zone-assembly",
                        "series": None,
                    },
                ],
            },
        },
        {"name": "inspect_facility_findings", "args": {}},
    ])

    assert remaining == [{"name": "inspect_facility_findings", "args": {}}]
    assert warnings == []
    assert len(blocks) == 1
    assert blocks[0]["type"] == "visualization"
    assert blocks[0]["spec"]["type"] == "bar"
    assert blocks[0]["spec"]["data"][0] == {
        "label": "Machining Hall",
        "value": 42.0,
        "entityId": "zone-machining",
        "series": None,
    }


def test_chat_table_tool_is_strict_structured_and_presentation_only():
    native = server.build_native_tool_specs(
        "deviation-analyst",
        allowed_tools={server.CHAT_TABLE_TOOL},
    )
    translated = server._openai_native_tool_specs(native)
    assert len(translated) == 1
    assert translated[0]["name"] == server.CHAT_TABLE_TOOL
    assert translated[0]["strict"] is True
    assert translated[0]["parameters"]["additionalProperties"] is False

    remaining, blocks, warnings = server.extract_chat_presentation_blocks([
        {
            "name": server.CHAT_TABLE_TOOL,
            "args": {
                "title": "Department comparison",
                "subtitle": "Trusted saved layout",
                "columns": [
                    {"label": "Department", "unit": None},
                    {"label": "Placements", "unit": "count"},
                ],
                "rows": [
                    {
                        "cells": ["Machining Hall", "32"],
                        "entity_id": "zone-machining",
                    },
                    {
                        "cells": ["Automation + Robot cells", "492"],
                        "entity_id": "zone-automation",
                    },
                ],
            },
        }
    ])
    assert remaining == []
    assert warnings == []
    assert blocks[0]["type"] == "table"
    assert blocks[0]["table"]["rows"][0]["entityId"] == "zone-machining"


def test_facility_table_request_forces_table_while_rich_tools_remain_available():
    base = {
        "workflow": {"id": "facility-layout-analysis"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {"output": {}},
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        "Compare the Machining Hall and Automation zone in a table.",
    )
    assert set(constrained["allowed_tools"]) == TABLE_COMPARE_TOOLS
    assert server._required_facility_presentation_tool(constrained) == (
        server.CHAT_TABLE_TOOL
    )
    assert "EXPLICIT TABLE CONTRACT" in constrained["prompt"]


def test_affirmative_follow_up_inherits_prior_table_presentation_only():
    base = {
        "workflow": {"id": "facility-layout-analysis"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {"output": {}},
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        "yes",
        recent_turns=[
            {
                "role": "user",
                "content": (
                    "Compare the Machining Hall and Automation zone in a table."
                ),
            },
            {
                "role": "assistant",
                "content": "Would you like the asset category breakdown?",
            },
        ],
    )
    assert set(constrained["allowed_tools"]) == TABLE_COMPARE_TOOLS
    presentation = constrained["runtime_tool_policy"]["presentation"]
    assert presentation == {
        "chartType": None,
        "table": True,
        "inherited": True,
        "options": {},
    }
    assert "do not merely repeat the old table" in constrained["prompt"]


def test_affirmative_follow_up_compiles_pending_analysis_without_write_access():
    base = {
        "workflow": {"id": "facility-layout-analysis"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {"output": {}},
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        "yes",
        recent_turns=[
            {
                "role": "user",
                "content": (
                    "Which assembly cell has the least operator walking?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "I can retrieve all cell coordinates and calculate the "
                    "walking comparison. Should I continue?"
                ),
            },
        ],
    )
    assert set(constrained["allowed_tools"]) == COMPARE_TOOLS
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in constrained["allowed_tools"]
    policy = constrained["runtime_tool_policy"]
    assert policy["mode"] == "read_only_analysis"
    assert policy["pendingFollowUp"]["actionMode"] == "READ_ONLY"
    assert "FACILITY FOLLOW-UP CONTINUATION" in constrained["prompt"]
    assert "Complete that analysis now" in constrained["prompt"]


def test_operational_utilization_chart_policy_forbids_gross_area_substitution():
    base = {
        "workflow": {"id": "facility-layout-analysis"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {"output": {}},
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        (
            "Chart operational space utilization by department. Do not use "
            "asset counts or gross department area."
        ),
    )
    policy = constrained["runtime_tool_policy"]
    assert policy["requestKind"] == "render"
    assert policy["metricId"] == "department_operational_utilization"
    assert "EXACT FACILITY METRIC CONTRACT" in constrained["prompt"]
    assert "Never replace it with gross area" in constrained["prompt"]


def test_chart_grounding_rejects_metric_substitution():
    fixture = json.loads((
        server.REPO_ROOT
        / "tests/fixtures/facility_layout/semantic_intelligence/"
        "golden-facility-a.json"
    ).read_text(encoding="ascii"))
    state = fixture["state"]
    semantic_map = build_facility_semantic_map(state)
    rows = [
        {
            "label": item["label"],
            "value": item["areaSquareMeters"],
            "entity_id": item["zoneId"],
            "series": None,
        }
        for item in semantic_map["departmentMetricSummaries"]
    ]
    substituted = _provider_response(_provider_tool(
        server.CHAT_VISUALIZATION_TOOL,
        {
            "chart_type": "bar",
            "metric_id": "department_gross_area",
            "title": "Operational utilization",
            "subtitle": None,
            "unit": "m2",
            "show_values": True,
            "show_percentages": False,
            "show_legend": False,
            "data": rows,
        },
    ))
    codes = {
        item["code"]
        for item in server._facility_chart_grounding_issues(
            substituted,
            state=state,
            requested_metric="department_operational_utilization",
            required_chart_type="bar",
        )
    }
    assert "facility_chart_metric_substitution" in codes
    assert "facility_chart_unit_mismatch" in codes
    assert "facility_chart_numeric_claim_not_observed" in codes


def test_chart_grounding_fails_closed_when_operational_metric_is_unknown():
    fixture = json.loads((
        server.REPO_ROOT
        / "tests/fixtures/facility_layout/semantic_intelligence/"
        "golden-facility-a.json"
    ).read_text(encoding="ascii"))
    state = fixture["state"]
    state["facilityPolicy"]["status"] = "draft"
    semantic_map = build_facility_semantic_map(state)
    response = _provider_response(_provider_tool(
        server.CHAT_VISUALIZATION_TOOL,
        {
            "chart_type": "bar",
            "metric_id": "department_operational_utilization",
            "title": "Operational utilization",
            "subtitle": None,
            "unit": "percent",
            "show_values": True,
            "show_percentages": False,
            "show_legend": False,
            "data": [
                {
                    "label": item["label"],
                    "value": item["physicalCoveragePercent"],
                    "entity_id": item["zoneId"],
                    "series": None,
                }
                for item in semantic_map["departmentMetricSummaries"]
            ],
        },
    ))
    codes = {
        item["code"]
        for item in server._facility_chart_grounding_issues(
            response,
            state=state,
            requested_metric="department_operational_utilization",
            required_chart_type="bar",
        )
    }
    assert "facility_chart_requested_metric_unknown" in codes
    assert server._facility_chart_metric_available(
        state,
        "department_operational_utilization",
    ) is False


def test_chart_grounding_accepts_exact_revision_bound_department_area():
    fixture = json.loads((
        server.REPO_ROOT
        / "tests/fixtures/facility_layout/semantic_intelligence/"
        "golden-facility-a.json"
    ).read_text(encoding="ascii"))
    state = fixture["state"]
    semantic_map = build_facility_semantic_map(state)
    response = _provider_response(_provider_tool(
        server.CHAT_VISUALIZATION_TOOL,
        {
            "chart_type": "pie",
            "metric_id": "department_gross_area",
            "title": "Department floor area",
            "subtitle": None,
            "unit": "m2",
            "show_values": True,
            "show_percentages": False,
            "show_legend": True,
            "data": [
                {
                    "label": item["label"],
                    "value": item["areaSquareMeters"],
                    "entity_id": item["zoneId"],
                    "series": None,
                }
                for item in semantic_map["departmentMetricSummaries"]
            ],
        },
    ))
    assert server._facility_chart_grounding_issues(
        response,
        state=state,
        requested_metric="department_gross_area",
        required_chart_type="pie",
    ) == []


@pytest.mark.parametrize(
    ("message", "chart_type"),
    [
        ("Show a heatmap of asset categories by department.", "heatmap"),
        ("Show a pie chart of placements by department.", "pie"),
    ],
)
def test_facility_extended_chart_types_are_required_native_tools(
    message,
    chart_type,
):
    base = {
        "workflow": {"id": "facility-layout-analysis"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {"output": {}},
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        message,
    )
    assert set(constrained["allowed_tools"]) == CHART_RENDER_TOOLS
    assert constrained["runtime_tool_policy"]["presentation"][
        "chartType"
    ] == chart_type
    assert server._required_facility_presentation_tool(constrained) == (
        server.CHAT_VISUALIZATION_TOOL
    )
    assert f"chart_type={chart_type}" in constrained["prompt"]


def test_pie_display_correction_inherits_chart_and_forces_preferences():
    base = {
        "workflow": {"id": "facility-layout-analysis"},
        "prompt": "base",
        "allowed_tools": [],
        "resolved_policy": {"output": {}},
    }
    constrained = server._apply_facility_layout_request_tool_policy(
        base,
        "Use placement-count labels only, with no percentage labels.",
        recent_turns=[
            {
                "role": "user",
                "content": "Show a pie chart of placements by department.",
            },
            {
                "role": "assistant",
                "content": "Would you like percentage labels?",
            },
        ],
    )
    presentation = constrained["runtime_tool_policy"]["presentation"]
    assert presentation == {
        "chartType": "pie",
        "table": False,
        "inherited": True,
        "options": {
            "showPercentages": False,
            "showValues": True,
        },
    }
    assert server._required_facility_presentation_tool(constrained) == (
        server.CHAT_VISUALIZATION_TOOL
    )


def test_requested_facility_presentation_is_a_required_native_tool():
    chart_plan = {
        "workflow": {"id": "facility-layout-analysis"},
        "allowed_tools": [server.CHAT_VISUALIZATION_TOOL],
        "runtime_tool_policy": {
            "mode": "read_only_analysis",
            "presentation": {"chartType": "pareto", "table": False},
        },
    }
    table_plan = {
        "workflow": {"id": "facility-layout-analysis"},
        "allowed_tools": [server.CHAT_TABLE_TOOL],
        "runtime_tool_policy": {
            "mode": "read_only_analysis",
            "presentation": {"chartType": None, "table": True},
        },
    }

    assert server._required_facility_presentation_tool(chart_plan) == (
        server.CHAT_VISUALIZATION_TOOL
    )
    assert server._required_facility_presentation_tool(table_plan) == (
        server.CHAT_TABLE_TOOL
    )
    table_plan["runtime_tool_policy"]["presentation"]["chartType"] = "bar"
    assert server._required_facility_presentation_tool(table_plan) is None


def test_chat_visualization_correction_forces_pareto_type():
    remaining, blocks, warnings = server.extract_chat_presentation_blocks(
        [
            {
                "name": server.CHAT_VISUALIZATION_TOOL,
                "args": {
                    "chart_type": "bar",
                    "title": "Facility Layout Entity Distribution",
                    "subtitle": None,
                    "unit": "entities",
                    "data": [
                        {
                            "label": "Placements",
                            "value": 827,
                            "entity_id": None,
                            "series": None,
                        },
                        {
                            "label": "Zones",
                            "value": 45,
                            "entity_id": None,
                            "series": None,
                        },
                    ],
                },
            }
        ],
        required_chart_type="pareto",
    )

    assert remaining == []
    assert blocks[0]["spec"]["type"] == "pareto"
    assert warnings == ["chat_visualization_type_corrected:bar_to_pareto"]


def test_facility_request_has_deterministic_workflow_fallback():
    assert server._required_facility_layout_workflow(
        "Build a complete manufacturing cell layout."
    ) == "facility-layout-generation"
    assert server._required_facility_layout_workflow(
        "Which aisle is blocked in this warehouse?"
    ) == "facility-layout-analysis"
    assert server._required_facility_layout_workflow(
        "What is the bore tolerance?"
    ) is None
    route = server._safe_facility_layout_route(
        "Build a warehouse layout proposal."
    )
    assert route["primary_workflow"] == "facility-layout-generation"
    assert route["skill_candidates"][0]["id"] == (
        "generate-facility-layout"
    )
    assert route["requested_side_effects"] == {
        "viewport_write": False,
        "asset_write": False,
        "system_write": False,
    }


def test_facility_follow_ups_select_analysis_workflow():
    history = [
        {
            "role": "user",
            "content": "Compare the Machining Hall and Automation zone.",
        },
        {
            "role": "assistant",
            "content": "Should I show the asset category breakdown?",
        },
    ]
    assert server._required_facility_layout_workflow(
        "yes",
        recent_turns=history,
    ) == "facility-layout-analysis"
    assert server._required_facility_layout_workflow(
        "show a pareto chart not a bar chart?",
        recent_turns=history,
    ) == "facility-layout-analysis"
    assert server._required_facility_layout_workflow(
        "Show percentage labels and hide the value labels.",
        recent_turns=history,
    ) == "facility-layout-analysis"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Create a bar chart comparing machine counts by department.",
            "facility-layout-analysis",
        ),
        (
            "Generate a Pareto graph of asset categories in this plant.",
            "facility-layout-analysis",
        ),
        (
            "Build a table summarizing every zone.",
            "facility-layout-analysis",
        ),
        (
            "Audit clearances without changing anything.",
            "facility-layout-analysis",
        ),
        (
            "Plot placements by zone.",
            "facility-layout-analysis",
        ),
        (
            "Create a complete factory layout.",
            "facility-layout-generation",
        ),
        (
            "Add three CNC machines to Machining.",
            "facility-layout-generation",
        ),
        (
            "Arrange these racks in two rows.",
            "facility-layout-generation",
        ),
        (
            "Improve the current layout and show a preview.",
            "facility-layout-generation",
        ),
        (
            "Move CNC-04 five feet east.",
            "facility-layout-generation",
        ),
        (
            "Build a layout and include a chart.",
            "facility-layout-generation",
        ),
        (
            "Create a facility chart; do not create a ghost preview.",
            "facility-layout-analysis",
        ),
        (
            "Build a ghost preview; do not commit it.",
            "facility-layout-generation",
        ),
    ],
)
def test_facility_intent_routes_by_requested_object(message, expected):
    assert server._required_facility_layout_workflow(message) == expected


def test_facility_analysis_fallback_loads_read_only_chart_skill():
    server._reset_agent_skill_runtime_cache_for_tests()
    route = server._safe_facility_layout_route(
        "Create a bar chart comparing placed assets by facility zone."
    )

    plan, reason = server._compose_production_skill_prompt(
        route,
        mode="training",
    )
    plan = server._apply_facility_layout_request_tool_policy(
        plan,
        "Create a bar chart comparing placed assets by facility zone.",
    )

    assert reason == ""
    assert plan is not None
    assert plan["workflow"]["id"] == "facility-layout-analysis"
    assert plan["selection"][0]["id"] == "analyze-facility-layout"
    assert set(plan["allowed_tools"]) == CHART_RENDER_TOOLS
    assert plan["runtime_tool_policy"]["mode"] == "read_only_analysis"
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in plan["allowed_tools"]


def test_facility_analysis_clarification_stays_in_read_only_semantic_workflow():
    server._reset_agent_skill_runtime_cache_for_tests()
    route = server._safe_facility_layout_route(
        "Compare Assembly Cell A01 and Assembly Cell A02."
    )
    route["needs_clarification"] = True
    route["clarification_question"] = (
        "Which comparison metric should I prioritize?"
    )

    plan, reason = server._compose_production_skill_prompt(
        route,
        mode="training",
    )
    plan = server._apply_facility_layout_request_tool_policy(
        plan,
        "Compare Assembly Cell A01 and Assembly Cell A02.",
    )

    assert reason == ""
    assert plan is not None
    assert plan["workflow"]["id"] == "facility-layout-analysis"
    assert plan["runtime_tool_policy"]["mode"] == "read_only_analysis"
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in plan["allowed_tools"]
    assert SEMANTIC_FACILITY_MOVE_TOOL not in plan["allowed_tools"]
    assert "ask exactly one concise clarifying question" in plan["prompt"]


def test_facility_generation_clarification_remains_fail_closed():
    route = server._safe_facility_layout_route(
        "Build a complete manufacturing cell layout."
    )
    route["needs_clarification"] = True

    plan, reason = server._compose_production_skill_prompt(
        route,
        mode="training",
    )

    assert plan is None
    assert reason == "route_needs_clarification"


def test_facility_chart_call_becomes_rich_content_without_preview(
    facility_host,
    monkeypatch,
):
    current = _current(facility_host)
    department_metrics = [{
        "label": "Current layout",
        "placementCount": len(current.get("placements", [])),
        "zoneId": current.get("layoutId", LOCAL_LAYOUT_ID),
    }]
    chart_rows = [
        {
            "label": item["label"],
            "value": item["placementCount"],
            "entity_id": item["zoneId"],
            "series": None,
        }
        for item in department_metrics
    ]

    invocation_count = [0]

    async def fake_invoke(_client, **kwargs):
        invocation_count[0] += 1
        required = kwargs.get("required_tool_name")
        if (
            required == "inspect_facility_semantics"
            or invocation_count[0] == 1
        ):
            return _provider_response(_provider_tool(
                "inspect_facility_semantics",
                {"view": "department_metrics", "pageSize": 6},
            ))
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text="Machining has the larger observed placement count.",
                ),
                SimpleNamespace(
                    type="tool_use",
                    name=server.CHAT_VISUALIZATION_TOOL,
                        input={
                            "chart_type": "bar",
                            "title": "Placed assets by department",
                            "subtitle": "Trusted saved layout",
                            "metric_id": "placement_count",
                            "unit": "placements",
                            "show_values": True,
                            "show_percentages": False,
                            "show_legend": True,
                            "data": chart_rows,
                        },
                ),
            ],
            usage=SimpleNamespace(
                input_tokens=20,
                output_tokens=12,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    monkeypatch.setattr(server, "_invoke_agent_model", fake_invoke)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    response = TestClient(server.app).post(
        "/api/agent/chat",
        json={
            "message": (
                "Create a bar chart comparing placed assets by facility "
                "department without changing the layout."
            ),
            "history": [],
            "inspection_context": {
                "attachments": {
                    "facility_layout": {
                        "siteId": LOCAL_SITE_ID,
                        "layoutId": LOCAL_LAYOUT_ID,
                        "revision": current["revision"],
                    },
                    "session": {"active_mode": "training"},
                }
            },
            "agent_type": "deviation-analyst",
            "session_id": "facility-chart-test",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["skill_runtime"]["workflow"]["id"] == (
        "facility-layout-analysis"
    )
    assert payload["tool_call_count"] == 0
    assert payload.get("tool_calls") in (None, [])
    assert payload.get("content_blocks")
    assert payload["content_blocks"][0]["type"] == "visualization"
    assert payload["content_blocks"][0]["spec"]["type"] == "bar"
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in json.dumps(payload)
    assert _current(facility_host)["revision"] == current["revision"]


def test_facility_fallback_loads_the_hierarchical_skill_in_production():
    server._reset_agent_skill_runtime_cache_for_tests()
    route = server._safe_facility_layout_route(
        "Build a factory layout from zones through production cells."
    )

    plan, reason = server._compose_production_skill_prompt(
        route,
        mode="training",
    )

    assert reason == ""
    assert plan is not None
    assert plan["workflow"]["id"] == "facility-layout-generation"
    assert len(plan["selection"]) == 1
    selected = plan["selection"][0]
    assert selected["id"] == "generate-facility-layout"
    assert selected["version"] == "1.10.0"
    assert selected["role"] == "primary"
    assert selected["contract_version"] == "1.10.0"
    assert len(selected["contract_sha256"]) == 64
    assert "Hierarchical Factory Procedure" in plan["prompt"]
    assert "build_facility_layout_preview" in plan["allowed_tools"]


def test_facility_scope_stays_stable_while_saved_revision_advances(
    facility_host,
):
    current = _current(facility_host)
    first_scope, first_revisions = server._workflow_scope_and_revision(
        {
            "facility_layout_state": {
                "identity": {
                    "siteId": LOCAL_SITE_ID,
                    "layoutId": LOCAL_LAYOUT_ID,
                    "revision": current["revision"],
                },
                "dependencyRevisions": {
                    "shellRevision": "a" * 64,
                    "policySetRevision": "b" * 64,
                },
            }
        }
    )
    second_scope, second_revisions = server._workflow_scope_and_revision(
        {
            "facility_layout_state": {
                "identity": {
                    "siteId": LOCAL_SITE_ID,
                    "layoutId": LOCAL_LAYOUT_ID,
                    "revision": "f" * 64,
                },
                "dependencyRevisions": {
                    "shellRevision": "a" * 64,
                    "policySetRevision": "b" * 64,
                },
            }
        }
    )
    assert first_scope == second_scope
    assert first_revisions["facilityLayoutRevision"] == current["revision"]
    assert second_revisions["facilityLayoutRevision"] == "f" * 64
    assert first_revisions != second_revisions


def test_facility_preview_backstop_canonicalizes_loose_model_intent(
    facility_host,
):
    current = _current(facility_host)
    flat = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": current["revision"],
        }
    }
    server._resolve_trusted_facility_layout_context(flat)
    prompt_plan = {
        "workflow": {"id": "facility-layout-generation"},
        "runtime_tool_policy": {"mode": "semantic_generation"},
        "allowed_tools": [SEMANTIC_FACILITY_PREVIEW_TOOL],
    }
    loose_call = {
        "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
        "args": {
            "semantic_plan": {
                "version": "1.0",
                "intent": "CNC to assembly workbench cell",
                "assets": [
                    {"asset_type": "cnc_milling_machine", "quantity": 1},
                    {"asset_type": "assembly_workbench", "quantity": 1},
                ],
                "assumptions": ["Review operating clearances."],
            }
        },
    }
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [loose_call],
            prompt_plan,
            flat,
            (
                "Build one review-only manufacturing cell with one CNC "
                "machine and one assembly workbench."
            ),
            "deviation-analyst",
        )
    )
    assert changed is True
    assert "facility_semantic_plan_canonicalized" in warnings
    assert len(calls) == 1
    plan = calls[0]["args"]["semantic_plan"]
    assert plan["objective"] == "place_and_cleanup"
    assert plan["layoutHints"]["replaceExistingContents"] is True
    assert plan["schemaVersion"] == 1
    assert plan["sourceRevisions"]["layout"] == current["revision"]
    assert {
        item["assetId"] for item in plan["selectedAssets"]
    } == {"asset-cnc-mill", "asset-workbench"}
    assert sum(item["quantity"] for item in plan["selectedAssets"]) == 2
    preview = facility_host.agent_runtime.build_preview(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        semantic_plan=plan,
        live_facts={
            "dirty": False,
            "conflict": False,
            "editable": True,
            "viewportMode": "split",
            "selection": {},
        },
    )
    assert preview["ok"] is True
    assert preview["previewOnly"] is True
    assert preview["saved"] is False
    assert preview["semanticPlan"]["summary"][
        "requestedPlacementCount"
    ] == 2


def test_facility_preview_backstop_builds_bounded_blank_factory_program(
    facility_host,
):
    current = _current(facility_host)
    flat = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": current["revision"],
        }
    }
    server._resolve_trusted_facility_layout_context(flat)
    prompt = (
        "Build a complete facility layout from scratch for this 984.3 ft x "
        "656.3 ft factory using the facility-layout planning procedure and "
        "available asset library. Create appropriate departments, aisles, "
        "floor markings, manufacturing cells, storage, material flow, safety "
        "clearances, and support areas. Validate the complete design and show "
        "one synchronized 2D/3D ghost preview. Report unresolved issues and "
        "do not commit anything until I approve."
    )
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [{
                "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
                "args": {
                    "semantic_plan": {
                        "intent": "complete factory layout",
                        "assets": [
                            {"asset_type": "machine", "quantity": 500},
                            {"asset_type": "storage", "quantity": 500},
                        ],
                    }
                },
            }],
                {
                    "workflow": {"id": "facility-layout-generation"},
                    "runtime_tool_policy": {"mode": "semantic_generation"},
                    "allowed_tools": [SEMANTIC_FACILITY_PREVIEW_TOOL],
                },
            flat,
            prompt,
            "deviation-analyst",
        )
    )

    assert changed is True
    assert "facility_semantic_plan_canonicalized" in warnings
    assert len(calls) == 1
    plan = calls[0]["args"]["semantic_plan"]
    requested_count = sum(
        item["quantity"] for item in plan["selectedAssets"]
    )
    assert 1 <= requested_count <= 120
    assert len(plan["requiredZones"]) == 6
    assert {
        item["label"] for item in plan["requiredZones"]
    } == {
        "Receiving + Raw Material",
        "Machining Hall",
        "Automation + Robot Cells",
        "Material Handling + Maintenance",
        "Assembly + Kitting",
        "Inspection + Packing + Finished Goods",
    }
    zone_refs = {
        item["zoneRequestId"] for item in plan["requiredZones"]
    }
    assert all(
        item["targetZoneRef"] in zone_refs
        for item in plan["selectedAssets"]
    )
    compiled = compile_semantic_facility_plan(
        plan,
        state=flat["facility_layout_state"],
        evidence=flat["facility_layout_evidence"],
    )
    assert sum(
        item["quantity"]
        for item in compiled["plannerRequest"]["assetSet"]
    ) == requested_count
    assert compiled["plannerRequest"]["cleanup"][
        "replaceExistingContents"
    ] is True
    assert len(compiled["plannerRequest"]["zoneSizing"]) == 6
    assert all(
        isinstance(item["newZone"]["allowedAssetCategories"], list)
        for item in compiled["plannerRequest"]["zoneSizing"]
    )
    latest = _current(facility_host)
    assert latest["revision"] == current["revision"]
    assert latest["layout"]["placements"] == []
    assert latest["layout"]["zones"] == []


def test_facility_preview_backstop_supports_existing_layout_review(
    facility_host,
):
    current = _current(facility_host)
    flat = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": current["revision"],
        }
    }
    server._resolve_trusted_facility_layout_context(flat)
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [{"name": "inspect_facility_findings", "args": {}}],
                {
                    "workflow": {"id": "facility-layout-generation"},
                    "runtime_tool_policy": {"mode": "semantic_generation"},
                    "allowed_tools": [SEMANTIC_FACILITY_PREVIEW_TOOL],
                },
            flat,
            (
                "Review and improve the current Facility Layout. Preserve "
                "existing authored zones and manual placements, validate "
                "clearances, and show one ghost preview."
            ),
            "deviation-analyst",
        )
    )

    assert changed is True
    assert "facility_semantic_plan_canonicalized" in warnings
    assert len(calls) == 1
    assert calls[0]["name"] == SEMANTIC_FACILITY_PREVIEW_TOOL
    plan = calls[0]["args"]["semantic_plan"]
    assert plan["objective"] == "cleanup_layout"
    assert plan["selectedAssets"] == []
    assert plan["layoutHints"]["preserveManual"] is True
    assert plan["layoutHints"]["preserveLocked"] is True
    preview = facility_host.agent_runtime.build_preview(
        facility_host.principal(),
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        semantic_plan=plan,
        live_facts={
            "dirty": False,
            "conflict": False,
            "editable": True,
            "viewportMode": "split",
            "selection": {},
        },
    )
    assert preview["ok"] is True
    assert preview["previewOnly"] is True
    assert preview["saved"] is False


def test_existing_layout_review_does_not_infer_new_assets_from_generic_nouns(
    facility_host,
):
    current = _current(facility_host)
    flat = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": current["revision"],
        }
    }
    server._resolve_trusted_facility_layout_context(flat)
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [{
                "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
                "args": {
                    "semantic_plan": {
                        "intent": "Review machines and manufacturing cells",
                        "assets": [
                            {"asset_type": "machine", "quantity": 1},
                            {"asset_type": "cell", "quantity": 1},
                        ],
                    }
                },
            }],
                {
                    "workflow": {"id": "facility-layout-generation"},
                    "runtime_tool_policy": {"mode": "semantic_generation"},
                    "allowed_tools": [SEMANTIC_FACILITY_PREVIEW_TOOL],
                },
            flat,
            (
                "Review and improve the current Facility Layout. Preserve "
                "all existing zones, aisles, floor markings, machines, "
                "cells, and manual placements. Identify missing or "
                "problematic areas and show one ghost preview."
            ),
            "deviation-analyst",
        )
    )

    assert changed is True
    assert "facility_semantic_plan_canonicalized" in warnings
    assert len(calls) == 1
    plan = calls[0]["args"]["semantic_plan"]
    assert plan["objective"] == "cleanup_layout"
    assert plan["selectedAssets"] == []


def test_facility_preview_backstop_rejects_model_coordinates(
    facility_host,
):
    current = _current(facility_host)
    flat = {
        "facility_layout_ref": {
            "siteId": LOCAL_SITE_ID,
            "layoutId": LOCAL_LAYOUT_ID,
            "revision": current["revision"],
        }
    }
    server._resolve_trusted_facility_layout_context(flat)
    calls, warnings, changed = (
        server.ensure_facility_layout_preview_tool_call(
            [{
                "name": SEMANTIC_FACILITY_PREVIEW_TOOL,
                "args": {
                    "semantic_plan": {
                        "assets": [{"asset_type": "cnc", "quantity": 1}],
                        "position": {"x": 8, "z": 4},
                    }
                },
            }],
            {
                "workflow": {"id": "facility-layout-generation"},
                "runtime_tool_policy": {"mode": "semantic_generation"},
                "allowed_tools": [SEMANTIC_FACILITY_PREVIEW_TOOL],
            },
            flat,
            "Build one CNC machine layout proposal.",
            "deviation-analyst",
        )
    )
    assert calls == []
    assert changed is False
    assert warnings == [
        "facility_semantic_plan_rejected:"
        "semantic_plan_contains_raw_geometry"
    ]
