"""P9 trusted Facility Layout agent runtime tests."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.agent_runtime import (
    FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN,
    FacilityLayoutAgentRuntimeError,
)
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
)
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)


@pytest.fixture()
def host(tmp_path):
    value = LocalFacilityLayoutHost(
        tmp_path / "facility",
        private_assets=False,
    )
    value.ensure_bootstrap()
    try:
        yield value
    finally:
        value.close()


def _context(host: LocalFacilityLayoutHost):
    principal = host.principal()
    current = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    bundle = host.agent_runtime.resolve_context(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        live_facts={
            "dirty": False,
            "conflict": False,
            "editable": True,
            "viewportMode": "split",
            "navigationCapabilities": {
                "activeMode": "drone",
                "walkthrough": {"supported": True, "active": False},
                "drone": {
                    "supported": True,
                    "active": True,
                    "assistedFlight": True,
                    "colliderRadiusMeters": 0.35,
                    "obstacleCount": 17,
                    "altitudeMeters": 12.5,
                },
            },
            "selection": {},
            "layout": {"forged": True},
            "camera": {"forged": True},
        },
    )
    return principal, current, bundle


def _semantic_plan(bundle, asset):
    identity = bundle.state["identity"]
    dependencies = bundle.state["dependencyRevisions"]
    return {
        "schemaVersion": 1,
        "planId": "plan-p9-local-cnc",
        "scope": {
            "siteId": identity["siteId"],
            "layoutId": identity["layoutId"],
            "label": "Local CNC cell",
        },
        "objective": "place_asset_set",
        "sourceRevisions": {
            "layout": identity["revision"],
            "shell": dependencies["shellRevision"],
            "policy": dependencies["policySetRevision"],
        },
        "requiredCapabilities": [],
        "selectedAssets": [
            {
                "itemId": "cnc-machine",
                "assetId": asset["assetId"],
                "assetDefinitionRevision": asset[
                    "assetDefinitionRevision"
                ],
                "quantity": 1,
                "resourceRole": "machine",
                "stage": 1,
                "knowledgeStatus": "inferred",
                "evidenceIds": [],
                "assumptionIds": ["assumption-local-placement"],
            }
        ],
        "requiredZones": [],
        "placementRelationships": [],
        "processBindings": [],
        "flows": [],
        "evidence": [],
        "assumptions": [
            {
                "assumptionId": "assumption-local-placement",
                "text": "Review the proposed CNC placement.",
                "subjectRefs": ["cnc-machine"],
            }
        ],
        "unresolvedItems": [],
        "alternatives": [
            {
                "alternativeId": "balanced",
                "strategy": "balanced_grid",
                "label": "Balanced",
            }
        ],
        "layoutHints": {
            "density": "balanced",
            "preserveManual": True,
            "preserveLocked": True,
            "primaryFlow": "none",
        },
    }


def test_context_reloads_authorities_and_discards_browser_geometry(host):
    _, current, bundle = _context(host)

    assert bundle.state["identity"]["revision"] == current["revision"]
    assert bundle.state["editor"]["viewportMode"] == "split"
    assert bundle.state["editor"]["navigationCapabilities"]["drone"] == {
        "supported": True,
        "active": True,
        "assistedFlight": True,
        "colliderRadiusMeters": 0.35,
        "obstacleCount": 17.0,
        "altitudeMeters": 12.5,
        "nearestObstacleDistanceMeters": None,
    }
    assert "layout" not in bundle.state["editor"]
    assert "camera" not in bundle.state["editor"]
    assert bundle.state["coordinateContract"] == {
        "persisted": "facility_world",
        "upAxis": "+Y",
        "floorAxes": ["+X", "+Z"],
        "cameraIsNotGeometry": True,
        "screenPixelsAcceptedForWrites": False,
        "modelCoordinatesAcceptedForWrites": False,
        "positionModes": ["auto", "manual", "locked"],
    }
    assert bundle.digest["identity"]["layoutId"] == LOCAL_LAYOUT_ID
    assert bundle.digest["estimatedTokens"] <= 4500


def test_context_uses_active_plan_boundary_instead_of_starter_shell(host):
    principal = host.principal()
    current = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    updated = host.service.apply_operations(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        current["revision"],
        [{
            "op": "set_plan_settings",
            "planSettings": {
                "widthMeters": 300.0,
                "depthMeters": 200.0,
                "gridSpacingMeters": 1.0,
                "majorGridSpacingMeters": 5.0,
            },
        }],
    )

    bundle = host.agent_runtime.resolve_context(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=updated["revision"],
    )
    floor = next(
        feature
        for feature in bundle.shell_document["features"]
        if feature["featureKind"] in {"floor", "floor_surface"}
    )
    assert floor["geometry"]["boundary"] == [
        {"x": 0.0, "z": 0.0},
        {"x": 300.0, "z": 0.0},
        {"x": 300.0, "z": 200.0},
        {"x": 0.0, "z": 200.0},
    ]

    overview = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=updated["revision"],
        tool_name="inspect_facility_semantics",
        arguments={"view": "overview"},
        turn_id="turn-active-plan-boundary",
    )
    assert overview["facilitySummary"]["bounds"] == {
        "minimumX": 0.0,
        "minimumZ": 0.0,
        "maximumX": 300.0,
        "maximumZ": 200.0,
        "widthMeters": 300.0,
        "depthMeters": 200.0,
        "areaSquareMeters": 60000.0,
    }


def test_context_and_read_tools_use_owned_active_generation_draft(host):
    principal = host.principal()
    saved = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    started = host.generation_coordinator.start_g1_run(
        tenant_id=principal.tenant_id,
        site_id=LOCAL_SITE_ID,
        workspace_id="workspace-facility-layout",
        layout_id=LOCAL_LAYOUT_ID,
        user_id=principal.principal_id,
        session_id="session-active-generation-context",
        base_layout=saved["layout"],
        base_layout_revision=saved["revision"],
        envelope_request={
            "width": 100,
            "depth": 80,
            "sourceUnit": "m",
            "displayName": "Generated Context",
        },
        department_request={
            "count": 4,
            "labels": ["Receiving", "Machining", "Assembly", "Shipping"],
            "proportions": [1, 1, 1, 1],
            "arrangement": "columns",
            "orientation": "horizontal",
        },
        execution_mode="authorized_draft_run",
        prototype_mode=True,
    )
    completed = started
    for _ in FACILITY_GENERATION_STAGES:
        completed = host.generation_coordinator.continue_run(
            tenant_id=principal.tenant_id,
            site_id=LOCAL_SITE_ID,
            run_id=started["runId"],
            current_base_layout=saved["layout"],
            current_base_revision=saved["revision"],
        )
    live_facts = {
        "generationDraft": {
            "active": True,
            "runId": completed["runId"],
            "status": completed["status"],
            "baseLayoutRevision": completed["baseLayoutRevision"],
            "draftLayoutRevision": completed["draftLayoutRevision"],
            "writable": True,
        }
    }
    bundle = host.agent_runtime.resolve_context(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=saved["revision"],
        live_facts=live_facts,
    )
    assert bundle.base_layout_revision == saved["revision"]
    assert bundle.generation_run_id == completed["runId"]
    assert bundle.state["identity"]["revision"] == completed[
        "draftLayoutRevision"
    ]
    assert [zone["label"] for zone in bundle.layout_document["zones"]] == [
        "Receiving",
        "Machining",
        "Assembly",
        "Shipping",
    ]
    assert bundle.layout_document["placements"] == []
    assert bundle.layout_document != saved["layout"]

    observed = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=saved["revision"],
        tool_name="inspect_facility_entities",
        arguments={
            "entityKind": "zone",
            "ids": [zone["zoneId"] for zone in bundle.layout_document["zones"]],
            "pageSize": 10,
        },
        turn_id="turn-active-generation-read",
        live_facts=live_facts,
    )
    assert len(observed["records"]) == 4
    assert observed["revision"] == completed["draftLayoutRevision"]


def test_stale_revision_rejects_before_observation(host):
    principal = host.principal()
    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.resolve_context(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision="0" * 64,
        )
    assert caught.value.code == "facility_layout_revision_conflict"
    assert caught.value.status_code == 409
    assert caught.value.details["currentRevision"]


def test_asset_search_cursor_is_opaque_and_scope_bound(host):
    principal, current, bundle = _context(host)
    first = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="search_industrial_assets",
        arguments={"pageSize": 1},
        turn_id="turn-p9-search",
    )
    assert first["returnedCount"] == 1
    # This test checks pagination over the bootstrap catalog, not a fixed
    # inventory size. Compare against the independently loaded context.
    assert first["totalCount"] == len(bundle.state["assets"])
    assert first["totalCount"] > 1
    assert first["nextCursor"].startswith("flc1.")
    assert "assetId" not in first["nextCursor"]

    second = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="search_industrial_assets",
        arguments={
            "pageSize": 1,
            "cursor": first["nextCursor"],
        },
        turn_id="turn-p9-search",
    )
    assert second["records"][0]["assetId"] != first["records"][0]["assetId"]

    other = FacilityPrincipal(
        principal_id="another-user",
        tenant_id=principal.tenant_id,
        allowed_site_ids=principal.allowed_site_ids,
        roles=principal.roles,
    )
    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.execute_read_tool(
            other,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            tool_name="search_industrial_assets",
            arguments={
                "pageSize": 1,
                "cursor": first["nextCursor"],
            },
            turn_id="turn-p9-other",
        )
    assert caught.value.code == "facility_agent_cursor_scope_mismatch"


def test_read_tools_are_bounded_and_stable_id_driven(host):
    principal, current, bundle = _context(host)
    response = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="inspect_facility_region",
        arguments={
            "regionKind": "shell_feature",
            "regionId": "floor-main",
        },
        turn_id="turn-p9-region",
    )
    assert response["records"][0]["featureId"] == "floor-main"
    assert len(
        json.dumps(response, sort_keys=True).encode("ascii")
    ) <= 16_384
    assert bundle.state["selection"] == {
        "placementIds": [],
        "zoneIds": [],
        "floorMarkingIds": [],
        "routeIds": [],
        "utilityNetworkIds": [],
        "processBindingIds": [],
    }


def test_semantic_read_tool_returns_revision_bound_derived_knowledge(host):
    principal, current, _ = _context(host)
    overview = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="inspect_facility_semantics",
        arguments={"view": "overview"},
        turn_id="turn-p9-semantics-overview",
    )
    assert overview["revision"] == current["revision"]
    assert overview["authoritative"] is True
    assert overview["semanticContractVersion"] == 1
    assert "zone area" in overview["analysisCapabilities"][
        "deterministicallyDerivable"
    ]
    assert "department_metrics" in overview["availableViews"]
    assert "layout_patterns" in overview["availableViews"]
    assert "process_bindings" in overview["availableViews"]
    assert "processRelationships" not in overview
    assert overview["processRelationshipSummary"]["bindingCount"] == 0
    assert overview["processRelationshipSummary"][
        "flowSequenceStatus"
    ] == "unknown"

    department_metrics = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="inspect_facility_semantics",
        arguments={"view": "department_metrics", "pageSize": 50},
        turn_id="turn-p9-semantics-department-metrics",
    )
    assert department_metrics["view"] == "department_metrics"
    assert len(json.dumps(department_metrics).encode("ascii")) <= 16_384

    strategies = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="inspect_facility_semantics",
        arguments={
            "view": "cell_layout_strategies",
            "query": "operator travel",
            "pageSize": 10,
        },
        turn_id="turn-p9-semantics-strategies",
    )
    assert any(
        item["strategyId"] == "u" for item in strategies["records"]
    )
    assert len(json.dumps(strategies).encode("ascii")) <= 16_384


def test_explicit_provenance_readers_return_disjoint_authored_records(host):
    principal, current, bundle = _context(host)
    asset = bundle.state["assets"][0]

    def placement(
        placement_id: str,
        x_value: float,
        provenance: dict,
    ) -> dict:
        return {
            "op": "place_asset",
            "placement": {
                "placementId": placement_id,
                "assetId": asset["assetId"],
                "assetDefinitionRevision": asset[
                    "assetDefinitionRevision"
                ],
                "transform": {
                    "position": {"x": x_value, "y": 0.0, "z": 2.0},
                    "quaternion": {
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "w": 1.0,
                    },
                    "scale": 1,
                },
                "positionMode": "manual",
                "snapRelationship": None,
                "metadata": {
                    "instanceLabel": placement_id,
                    "layoutProvenance": provenance,
                },
            },
        }

    linear = {
        "schemaVersion": 1,
        "provenanceId": "layout-pattern:runtime-linear",
        "command": "linear_pattern",
        "authoredStrategy": None,
        "seedEntityIds": ["pl-runtime-linear"],
        "parameters": {"count": 2, "spacing": 4.0},
        "manuallyEditedSinceCreation": False,
    }
    cell = {
        "schemaVersion": 1,
        "provenanceId": "layout-pattern:runtime-cell",
        "command": "cell_layout",
        "authoredStrategy": "u",
        "seedEntityIds": ["pl-runtime-cell"],
        "parameters": {"gap": 1.5, "invertU": False},
        "manuallyEditedSinceCreation": False,
    }
    updated = host.service.apply_operations(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
        current["revision"],
        [
            placement("pl-runtime-linear", 2.0, linear),
            placement("pl-runtime-cell", 8.0, cell),
        ],
    )
    saved_before_reads = deepcopy(updated["layout"])

    pattern_result = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=updated["revision"],
        tool_name="inspect_pattern_provenance",
        arguments={"pageSize": 10},
        turn_id="turn-pattern-provenance",
    )
    cell_result = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=updated["revision"],
        tool_name="inspect_cell_layout_provenance",
        arguments={"pageSize": 10},
        turn_id="turn-cell-provenance",
    )

    assert [
        (item["provenanceId"], item["command"])
        for item in pattern_result["records"]
    ] == [("layout-pattern:runtime-linear", "linear_pattern")]
    assert [
        (
            item["provenanceId"],
            item["command"],
            item["authoredStrategy"],
        )
        for item in cell_result["records"]
    ] == [("layout-pattern:runtime-cell", "cell_layout", "u")]
    latest = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    assert latest["revision"] == updated["revision"]
    assert latest["layout"] == saved_before_reads


def test_focused_spatial_tool_resolves_human_names_and_selection(host):
    principal, current, _ = _context(host)
    by_name = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="analyze_facility_spatial",
        arguments={
            "analysis": "resolve_entities",
            "query": "CNC Milling Machine",
            "entityKinds": ["asset"],
        },
        turn_id="turn-human-entity-name",
    )
    assert by_name["resolutionStatus"] == "unique"
    assert by_name["resolved"]["assetDefinitionRevision"]

    placement = current["layout"].get("placements", [])
    if placement:
        selected = host.agent_runtime.execute_read_tool(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            tool_name="analyze_facility_spatial",
            arguments={
                "analysis": "resolve_entities",
                "entityKinds": ["placement"],
                "useCurrentSelection": True,
            },
            live_facts={
                "selection": {
                    "placementIds": [placement[0]["placementId"]],
                }
            },
            turn_id="turn-current-selection",
        )
        assert selected["resolved"]["entityId"] == placement[0]["placementId"]


def test_focused_spatial_tool_exposes_asset_access_without_mutation(host):
    principal, current, _ = _context(host)
    result = host.agent_runtime.execute_read_tool(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        tool_name="analyze_facility_spatial",
        arguments={
            "analysis": "asset_access",
            "interfaceRole": "service",
            "maximumResults": 5,
        },
        turn_id="turn-machine-service-access",
    )

    assert result["analysis"] == "asset_access"
    assert result["mutationPerformed"] is False
    assert result["requestedInterfaceRole"] == "service"
    assert result["returnedCount"] <= 5


def test_per_turn_read_budget_fails_closed(host):
    principal, current, _ = _context(host)
    for _ in range(FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN):
        host.agent_runtime.execute_read_tool(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            tool_name="search_industrial_assets",
            arguments={"query": "rack"},
            turn_id="turn-p9-budget",
        )
    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.execute_read_tool(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            tool_name="search_industrial_assets",
            arguments={"query": "rack"},
            turn_id="turn-p9-budget",
        )
    assert caught.value.code == "facility_agent_turn_budget_exceeded"
    assert caught.value.status_code == 429


def test_semantic_preview_delegates_to_p8_without_saving(host):
    principal, current, bundle = _context(host)
    asset = next(
        item
        for item in bundle.state["assets"]
        if item["assetId"] == "asset-cnc-mill"
    )
    original = deepcopy(current["layout"])
    result = host.agent_runtime.build_preview(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        semantic_plan=_semantic_plan(bundle, asset),
        live_facts={
            "dirty": False,
            "conflict": False,
            "editable": True,
            "viewportMode": "plan",
            "selection": {},
        },
    )

    assert result["ok"] is True
    assert result["previewOnly"] is True
    assert result["saved"] is False
    assert result["canonicalReceipt"] is None
    assert result["selectedProposalId"].startswith("flp-")
    assert result["proposal"]["previewPure"] is True
    assert result["semanticPlan"]["summary"]["requestedPlacementCount"] == 1
    workflow = result["workflowRun"]
    assert workflow["status"] == "preview_ready"
    assert workflow["sourceBinding"]["layoutRevision"] == current["revision"]
    assert workflow["counters"]["repairAttempts"] == 0
    assert [item["stepId"] for item in workflow["steps"]] == [
        "observe",
        "build-plan",
        "validate-plan",
        "simulate-1",
        "validate-result-1",
        "preview",
    ]
    stored = host.agent_runtime.get_workflow_run(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        run_id=workflow["runId"],
    )
    assert stored == workflow

    other = FacilityPrincipal(
        principal_id="another-user",
        tenant_id=principal.tenant_id,
        allowed_site_ids=principal.allowed_site_ids,
        roles=principal.roles,
    )
    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.get_workflow_run(
            other,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            run_id=workflow["runId"],
        )
    assert caught.value.code == "facility_workflow_run_not_found"

    app = FastAPI()
    app.include_router(host.create_router())
    with TestClient(app) as client:
        response = client.get(
            "/api/facility-layout-agent/"
            f"{LOCAL_SITE_ID}/{LOCAL_LAYOUT_ID}/runs/{workflow['runId']}"
        )
    assert response.status_code == 200
    assert response.json() == workflow
    latest = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    assert latest["revision"] == current["revision"]
    assert latest["layout"] == original


def test_semantic_preview_repairs_with_one_additional_strategy(
    host,
    monkeypatch,
):
    principal, current, bundle = _context(host)
    asset = bundle.state["assets"][0]
    original_create = host.service.create_layout_proposals
    strategy_calls = []

    def create_with_one_recoverable_failure(
        call_principal,
        site_id,
        layout_id,
        base_revision,
        request,
    ):
        strategy_calls.append(list(request["strategies"]))
        if len(strategy_calls) == 1:
            raise FacilityValidationError(
                "no_layout_alternative",
                "The first deterministic strategy could not be placed.",
                details={"rejectedAlternatives": []},
            )
        return original_create(
            call_principal,
            site_id,
            layout_id,
            base_revision,
            request,
        )

    monkeypatch.setattr(
        host.service,
        "create_layout_proposals",
        create_with_one_recoverable_failure,
    )
    result = host.agent_runtime.build_preview(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        semantic_plan=_semantic_plan(bundle, asset),
    )

    workflow = result["workflowRun"]
    assert strategy_calls == [
        ["balanced_grid"],
        ["balanced_grid", "compact_rows"],
    ]
    assert workflow["status"] == "preview_ready"
    assert workflow["counters"]["repairAttempts"] == 1
    assert workflow["attempts"][0]["status"] == "rejected"
    assert workflow["attempts"][1]["status"] == "succeeded"
    assert workflow["corrections"][0]["code"] == (
        "add_deterministic_layout_strategy"
    )
    assert workflow["corrections"][0]["details"]["strategy"] == (
        "compact_rows"
    )


def test_semantic_preview_fails_closed_after_bounded_repairs(
    host,
    monkeypatch,
):
    principal, current, bundle = _context(host)
    asset = bundle.state["assets"][0]
    strategy_calls = []

    def always_fail(
        _principal,
        _site_id,
        _layout_id,
        _base_revision,
        request,
    ):
        strategy_calls.append(list(request["strategies"]))
        raise FacilityValidationError(
            "no_layout_alternative",
            "No deterministic strategy satisfies the hard constraints.",
            details={"rejectedAlternatives": []},
        )

    monkeypatch.setattr(
        host.service,
        "create_layout_proposals",
        always_fail,
    )
    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.build_preview(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            semantic_plan=_semantic_plan(bundle, asset),
        )

    assert caught.value.code == "no_layout_alternative"
    workflow = caught.value.details["workflowRun"]
    assert workflow["status"] == "budget_exhausted"
    assert workflow["counters"]["repairAttempts"] == 2
    assert len(workflow["attempts"]) == 3
    assert all(item["status"] == "rejected" for item in workflow["attempts"])
    assert strategy_calls == [
        ["balanced_grid"],
        ["balanced_grid", "compact_rows"],
        ["balanced_grid", "compact_rows", "flow_lanes"],
    ]


def test_dirty_editor_cannot_build_preview(host):
    principal, current, bundle = _context(host)
    asset = bundle.state["assets"][0]
    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.build_preview(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            semantic_plan=_semantic_plan(bundle, asset),
            live_facts={
                "dirty": True,
                "conflict": False,
                "editable": True,
                "viewportMode": "plan",
                "selection": {},
            },
        )
    assert caught.value.code == "facility_layout_saved_state_required"


def test_dirty_editor_can_preview_explicit_revision_bound_replacement(host):
    principal, current, bundle = _context(host)
    asset = bundle.state["assets"][0]
    plan = _semantic_plan(bundle, asset)
    plan["objective"] = "place_and_cleanup"
    plan["layoutHints"]["replaceExistingContents"] = True

    result = host.agent_runtime.build_preview(
        principal,
        site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID,
        expected_revision=current["revision"],
        semantic_plan=plan,
        live_facts={
            "dirty": True,
            "conflict": False,
            "editable": True,
            "viewportMode": "plan",
            "selection": {},
        },
    )

    assert result["proposal"]["previewPure"] is True
    assert result["proposal"]["alternatives"]
    assert result["proposal"]["alternatives"][0]["operations"][0] == {
        "op": "clear_layout_contents"
    }
    assert {
        item["code"] for item in result["workflowRun"]["issues"]
    } >= {"facility_dirty_draft_excluded_from_replacement"}
    latest = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    assert latest["revision"] == current["revision"]


def test_model_authored_coordinates_are_rejected_before_p8(host):
    principal, current, bundle = _context(host)
    asset = bundle.state["assets"][0]
    plan = _semantic_plan(bundle, asset)
    plan["selectedAssets"][0]["position"] = {"x": 4, "z": 7}

    with pytest.raises(FacilityLayoutAgentRuntimeError) as caught:
        host.agent_runtime.build_preview(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            semantic_plan=plan,
        )
    assert getattr(caught.value, "code", "") == (
        "semantic_plan_contains_raw_geometry"
    )


def test_asset_search_ignores_plurals_and_finds_word_starts(host):
    # Matching only the exact phrase, "tooling shelf" missed "Tooling Shelves" and the
    # agent placed an office bookshelf in a CNC area (2026-10-18 demo dry run).
    principal, current, _bundle = _context(host)

    def names(query, turn):
        result = host.agent_runtime.execute_read_tool(
            principal,
            site_id=LOCAL_SITE_ID,
            layout_id=LOCAL_LAYOUT_ID,
            expected_revision=current["revision"],
            tool_name="search_industrial_assets",
            arguments={"query": query, "pageSize": 50},
            turn_id=f"turn-plural-search-{turn}",
        )
        return {record["displayName"] for record in result["records"]}

    assert names("pallet racks", 1) == {"Pallet Rack"}
    assert names("workbenches", 2) == {"Assembly Workbench"}
    assert names("mills", 3) == {"CNC Milling Machine"}
    assert names("forklifts electric", 4) == {"Electric Forklift"}
    assert names("cnc", 5) == {"CNC Milling Machine"}
    assert names("refrigerator", 6) == set()
