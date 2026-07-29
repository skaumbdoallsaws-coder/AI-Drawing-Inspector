"""P9 trusted Facility Layout agent runtime tests."""

from __future__ import annotations

from copy import deepcopy
import json

import pytest

from ai_inspector.facility_layout.agent_runtime import (
    FACILITY_LAYOUT_AGENT_MAXIMUM_CALLS_PER_TURN,
    FacilityLayoutAgentRuntimeError,
)
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)


@pytest.fixture()
def host(tmp_path):
    value = LocalFacilityLayoutHost(tmp_path / "facility")
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
    principal, current, _ = _context(host)
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
    assert first["totalCount"] == 4
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
        "routeIds": [],
        "utilityNetworkIds": [],
        "processBindingIds": [],
    }


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
    latest = host.service.get_layout(
        principal,
        LOCAL_SITE_ID,
        LOCAL_LAYOUT_ID,
    )
    assert latest["revision"] == current["revision"]
    assert latest["layout"] == original


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
