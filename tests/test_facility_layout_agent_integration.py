"""Production integration guards for P9 Facility Layout agent planning."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import server
from ai_inspector.facility_layout.host import (
    LOCAL_LAYOUT_ID,
    LOCAL_SITE_ID,
    LocalFacilityLayoutHost,
)
from ai_inspector.facility_layout.semantic_plan import (
    SEMANTIC_FACILITY_PREVIEW_TOOL,
)


READ_TOOLS = {
    "search_industrial_assets",
    "inspect_facility_entities",
    "inspect_facility_region",
    "inspect_facility_findings",
    "inspect_process_bindings",
}


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


def test_facility_request_policy_separates_read_and_preview_tools():
    base = {
        "workflow": {"id": "facility-layout-generation"},
        "prompt": "base",
        "allowed_tools": [],
    }
    read_only = server._apply_facility_layout_request_tool_policy(
        base,
        "Which racks are available in this facility?",
    )
    assert set(read_only["allowed_tools"]) == READ_TOOLS
    assert SEMANTIC_FACILITY_PREVIEW_TOOL not in (
        read_only["allowed_tools"]
    )
    assert read_only["runtime_tool_policy"]["mode"] == (
        "read_only_observation"
    )

    generation = server._apply_facility_layout_request_tool_policy(
        base,
        "Build a warehouse layout proposal with rack lanes.",
    )
    assert set(generation["allowed_tools"]) == (
        READ_TOOLS | {SEMANTIC_FACILITY_PREVIEW_TOOL}
    )
    assert generation["runtime_tool_policy"]["mode"] == (
        "semantic_generation"
    )


def test_compiled_facility_policy_drops_low_level_writes_and_extra_previews():
    plan = {
        "workflow": {"id": "facility-layout-generation"},
        "runtime_tool_policy": {"mode": "semantic_generation"},
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


def test_facility_request_has_deterministic_workflow_fallback():
    assert server._required_facility_layout_workflow(
        "Build a complete manufacturing cell layout."
    ) == "facility-layout-generation"
    assert server._required_facility_layout_workflow(
        "Which aisle is blocked in this warehouse?"
    ) == "facility-layout-generation"
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


def test_facility_asset_fingerprint_changes_with_saved_revision(
    facility_host,
):
    current = _current(facility_host)
    first = server._workflow_asset_fingerprint(
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
    second = server._workflow_asset_fingerprint(
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
    assert first != second


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
