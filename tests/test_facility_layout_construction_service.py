"""Construction pilot uses real catalog parsing, validators and durable artifacts."""
import json

import pytest

from ai_inspector.facility_layout.construction_compiler import compile_construction_command, construction_tool_specs
from ai_inspector.facility_layout.construction_service import FacilityConstructionService
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.design_repository import FacilityDesignRepository
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID


@pytest.fixture()
def construction_host(tmp_path):
    root = tmp_path / "catalog"
    manifest = root / "generated/industrial_assets/local_library/catalog.json"
    manifest.parent.mkdir(parents=True)
    surface = {"surfaceId": "worktop", "label": "Worktop",
               "localFrame": {"origin": {"x": 0, "y": 1, "z": 0}, "xAxis": {"x": 1, "y": 0, "z": 0},
                              "zAxis": {"x": 0, "y": 0, "z": 1}, "normal": {"x": 0, "y": 1, "z": 0}},
               "bounds": {"minimumX": -0.9, "maximumX": 0.9, "minimumZ": -0.4, "maximumZ": 0.4},
               "allowedSides": ["above"], "evidenceStatus": "derived"}
    entries = []
    for name, width, depth, height in [("table", 1.8, 0.8, 1), ("device", 0.3, 0.3, 0.2)]:
        artifact = manifest.parent / (name + ".glb")
        artifact.write_bytes(b"test-catalog-artifact")
        entry = {"artifact": artifact.relative_to(root).as_posix(), "assetId": "asset-pilot-" + name,
                 "displayName": "Pilot " + name, "category": "Workstations", "description": "Isolated contract fixture",
                 "dimensions": {"width": width, "depth": depth, "height": height},
                 "sourceToCanonical": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
        if name == "table":
            entry["supportSurfaces"] = [surface]
        entries.append(entry)
    manifest.write_text(json.dumps({"schemaVersion": 1, "assets": entries}), encoding="utf-8")
    host = LocalFacilityLayoutHost(tmp_path / "store", private_assets=True, private_asset_root=root)
    host.ensure_bootstrap()
    principal = host.principal()
    current = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    catalog = host._catalog
    operations = []
    for index, name in enumerate(("table", "table", "device")):
        asset = catalog["asset-pilot-" + name]
        operations.append({"op": "place_asset", "placement": {"placementId": "pl-pilot-" + str(index),
            "assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": 8 + index * 5, "y": 0, "z": 5},
                          "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
            "positionMode": "manual", "snapRelationship": None, "metadata": {"instanceLabel": name + str(index)}}})
    seeded = host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, current["revision"], operations)
    try:
        yield host, seeded
    finally:
        host.close()


def _request(command, args, revision, key, parent=""):
    return dict(command_id=command, request={"requestId": key, "parentProposalId": parent,
                                           "expectedDraftRevision": revision, "arguments": args})


def _run(host, base_revision, command, args, previous=None, key=None):
    return host.construction_service.preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
        base_revision=base_revision, **_request(command, args,
        previous["candidateRevision"] if previous else base_revision,
        key or command, previous["proposalId"] if previous else ""))


ARRANGE = {"selectionIds": ["pl-pilot-0", "pl-pilot-1"], "strategyId": "line",
           "targetBounds": {"width": 10, "depth": 6}, "sourceUnit": "m", "gap": 0.5, "rows": 1,
           "orientation": "preserve", "angleDegrees": 0, "invertU": False}


def test_real_four_command_chain_durable_retry_and_explicit_unsaved_approval(construction_host):
    host, initial = construction_host
    revision = initial["revision"]
    first = _run(host, revision, "cell-layout", ARRANGE)
    assert first["candidateRevision"] != revision
    service = FacilityConstructionService(service=host.service, agent_runtime=host.agent_runtime,
                repository=host.design_repository, capability_gate=host.feature_flags.require)
    retried = service.preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
        base_revision=revision, **_request("cell-layout", dict(reversed(list(ARRANGE.items()))), revision, "cell-layout"))
    assert retried == first
    attached = _run(host, revision, "surface-stack", {"supportId": "pl-pilot-0", "childIds": ["pl-pilot-2"],
        "surfaceId": "worktop", "itemGap": 0.05, "inset": 0.05}, first)
    grouped = _run(host, revision, "create-cell-group", {"selectionIds": ["pl-pilot-0", "pl-pilot-1", "pl-pilot-2"],
        "label": "Pilot Cell", "envelopePadding": 0.2}, attached)
    cell_id = grouped["cells"][0]["cellId"]
    with pytest.raises(FacilityLayoutError) as missing_envelope:
        _run(host, revision, "linear-pattern", {"seedIds": grouped["cells"][0]["memberIds"],
            "count": 3, "direction": "north", "spacing": 8, "sourceUnit": "m"}, grouped, key="members-not-cell")
    assert missing_envelope.value.code == "facility_construction_cell_seed_required"
    assert missing_envelope.value.details["cellId"] == cell_id
    repeated = _run(host, revision, "linear-pattern", {"seedIds": [cell_id], "count": 3,
        "direction": "north", "spacing": 8, "sourceUnit": "m"}, grouped)
    assert repeated["commandCount"] == 4
    assert repeated["completedCommandIds"] == ["cell-layout", "surface-stack", "create-cell-group", "linear-pattern"]
    assert repeated["candidateCounts"] == {"placements": 9, "zones": 3, "cells": 3}
    assert len(repeated["cells"]) == 2
    assert all(len(cell["memberIds"]) == 3 for cell in repeated["cells"])
    preview = service.get_preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
                                  proposal_id=repeated["proposalId"])
    assert len(preview["candidateLayout"]["placements"]) == 9
    for cell in repeated["cells"]:
        child = next(p for p in preview["candidateLayout"]["placements"]
                     if p["placementId"] in cell["memberIds"] and p["assetId"] == "asset-pilot-device")
        assert child["snapRelationship"]["supportPlacementId"] in cell["memberIds"]
    approval_request = {"requestId": "apply-1", "sessionId": "session-pilot", "expectedDraftRevision": revision,
                        "editorGenerationId": "editor-pilot", "candidateRevision": repeated["candidateRevision"]}
    approval = service.approve_unsaved(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
                                       proposal_id=repeated["proposalId"], request=approval_request)
    assert approval == service.approve_unsaved(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
                                              proposal_id=repeated["proposalId"], request=approval_request)
    assert approval["saved"] is False
    saved = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    assert saved["revision"] == revision
    assert len(saved["layout"]["placements"]) == 3


def test_invalid_request_can_recover_without_changing_saved_layout(construction_host):
    host, initial = construction_host
    with pytest.raises(FacilityLayoutError):
        _run(host, initial["revision"], "cell-layout", {**ARRANGE, "targetBounds": {"width": 0.1, "depth": 0.1}}, key="bad-fit")
    result = _run(host, initial["revision"], "cell-layout", ARRANGE, key="recovered-fit")
    assert result["commandCount"] == 1
    with pytest.raises(FacilityLayoutError) as conflict:
        _run(host, initial["revision"], "cell-layout", {**ARRANGE, "gap": 1}, key="recovered-fit")
    assert conflict.value.code == "facility_command_idempotency_conflict"
    with pytest.raises(FacilityLayoutError) as stale:
        host.construction_service.preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
            base_revision=initial["revision"], **_request("cell-layout", ARRANGE, initial["revision"], "stale-child", result["proposalId"]))
    assert stale.value.code == "facility_command_stale"


def test_write_disabled_allows_preview_but_refuses_approval(construction_host):
    host, initial = construction_host
    def gate(capability):
        if capability == "agent_write":
            raise FacilityLayoutError("feature_disabled", "Write disabled", status_code=403)
        host.feature_flags.require(capability)
    service = FacilityConstructionService(service=host.service, agent_runtime=host.agent_runtime,
                                          repository=host.design_repository, capability_gate=gate)
    preview = service.preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
        base_revision=initial["revision"], **_request("cell-layout", ARRANGE, initial["revision"], "read-only-preview"))
    with pytest.raises(FacilityLayoutError) as refused:
        service.approve_unsaved(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
                                proposal_id=preview["proposalId"], request={})
    assert refused.value.code == "feature_disabled"


def test_compiler_is_deterministic_and_specs_share_hardened_schema(construction_host):
    host, initial = construction_host
    bundle = host.agent_runtime.resolve_context(host.principal(), site_id=LOCAL_SITE_ID,
                                               layout_id=LOCAL_LAYOUT_ID, expected_revision=initial["revision"])
    request = dict(layout=bundle.layout_document, catalog=bundle.asset_documents, command_id="cell-layout",
                   arguments=ARRANGE, request_id="determinism", namespace="a" * 40)
    assert compile_construction_command(**request) == compile_construction_command(**request)
    schemas = construction_tool_specs()
    assert len(schemas) == 4
    linear = next(s for s in schemas if s["name"] == "preview_facility_linear_pattern")
    assert linear["input_schema"]["properties"]["arguments"]["properties"]["count"]["maximum"] == 50


@pytest.mark.parametrize("pause_after_failure", [False, True])
@pytest.mark.parametrize("pause_after_group", [False, True])
def test_provider_loop_chains_real_commands_and_recovers_from_invalid_fit(construction_host, monkeypatch, pause_after_failure, pause_after_group):
    import asyncio
    from types import SimpleNamespace
    from starlette.requests import Request
    import server

    host, initial = construction_host
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", host)
    bundle = host.agent_runtime.resolve_context(host.principal(), site_id=LOCAL_SITE_ID,
                                               layout_id=LOCAL_LAYOUT_ID, expected_revision=initial["revision"])
    ctx = {"facility_layout_state": bundle.state}
    message = "Arrange these two tables into a cell, attach the device to the worktop, group them and make three total cells. Do not save."
    assert server.classify_facility_layout_request(message) == "generation"
    sequence = [
        ("cell-layout", {**ARRANGE, "targetBounds": {"width": 0.1, "depth": 0.1}}),
        ("cell-layout", ARRANGE),
        ("surface-stack", {"supportId": "pl-pilot-0", "childIds": ["pl-pilot-2"], "surfaceId": "worktop", "itemGap": 0.05, "inset": 0.05}),
        ("create-cell-group", {"selectionIds": ["pl-pilot-0", "pl-pilot-1", "pl-pilot-2"], "label": "Pilot Cell", "envelopePadding": 0.2}),
        ("linear-pattern", {"count": 3, "direction": "north", "spacing": 8, "sourceUnit": "m"}),
    ]
    if pause_after_group:
        sequence.insert(4, ("text", "The three-cell preview is complete. Ready to repeat the seed next."))
    if pause_after_failure:
        sequence.insert(1, ("text", "Now proceeding with the authorized larger envelope."))
    def response(index):
        if index >= len(sequence):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Three cells are ready for preview; not applied or saved.")], usage=None)
        command, arguments = sequence[index]
        if command == "text":
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=arguments)], usage=None)
        previous = ctx.get("_facility_construction_preview")
        if command == "linear-pattern":
            arguments = {**arguments, "seedIds": [previous["cells"][0]["cellId"]]}
        payload = _request(command, arguments, previous["candidateRevision"] if previous else initial["revision"],
                           "provider-" + str(index), previous["proposalId"] if previous else "")["request"]
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="preview_facility_" + command.replace("-", "_"), input=payload)], usage=None)
    index = 0
    async def provider(*_args, **kwargs):
        nonlocal index
        index += 1
        assert kwargs["messages"][-1]["role"] == "user"
        return response(index)
    monkeypatch.setattr(server, "_invoke_agent_model", provider)
    result, trace, _, _ = asyncio.run(server._resolve_facility_layout_provider_reads(response(0),
        client=object(), request=server.AgentChatRequest(message=message, agent_type="deviation-analyst"),
        http_request=Request({"type": "http", "method": "POST", "path": "/api/agent/chat", "headers": []}),
        ctx=ctx, skill_prompt_plan={"workflow": {"id": "facility-layout-generation"}, "runtime_tool_policy": {"mode": "construction_preview"}},
        system_prompt="Use bounded construction previews.", messages=[{"role": "user", "content": message}],
        provider_tools=server._FACILITY_CONSTRUCTION_TOOL_SPECS, provider="anthropic", model="test",
        reasoning_effort=None, terminal_required_tool=None))
    assert index == 6 + int(pause_after_failure)
    assert ctx["_facility_construction_preview"]["commandCount"] == 4
    assert "Three cells" in server._accumulate_response_text(result)
    assert len(trace) == 5
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["revision"] == initial["revision"]


def test_expiry_dirty_base_and_foreign_scope_fail_closed(construction_host):
    host, initial = construction_host
    result = _run(host, initial["revision"], "cell-layout", ARRANGE)
    with pytest.raises(FacilityLayoutError) as dirty:
        host.construction_service.preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
            base_revision=initial["revision"], live_facts={"dirty": True},
            **_request("cell-layout", ARRANGE, initial["revision"], "dirty"))
    assert dirty.value.code == "facility_construction_clean_base_required"
    with pytest.raises(FacilityLayoutError) as foreign:
        host.construction_service.get_preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id="another-layout",
                                              proposal_id=result["proposalId"])
    assert foreign.value.code == "facility_construction_proposal_not_found"
    host.construction_service.now = lambda: float("inf")
    with pytest.raises(FacilityLayoutError) as expired:
        _run(host, initial["revision"], "cell-layout", ARRANGE)
    assert expired.value.code == "facility_construction_expired"


def test_retry_survives_repository_reopen_and_is_scoped_to_trusted_turn(construction_host):
    host, initial = construction_host
    arguments = dict(site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID, base_revision=initial["revision"],
        **_request("cell-layout", ARRANGE, initial["revision"], "step-1"))
    first = host.construction_service.preview(host.principal(), request_scope="turn-a", **arguments)
    reopened = FacilityConstructionService(service=host.service, agent_runtime=host.agent_runtime,
        repository=FacilityDesignRepository(host.design_repository.root), capability_gate=host.feature_flags.require)
    assert reopened.preview(host.principal(), request_scope="turn-a", **arguments) == first
    other = reopened.preview(host.principal(), request_scope="turn-b", **arguments)
    assert other["proposalId"] != first["proposalId"]
    assert len(reopened.get_preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
                                   proposal_id=other["proposalId"])["candidateLayout"]["placements"]) == 3


def test_editor_preview_reports_result_revision_not_base(construction_host):
    host, initial = construction_host
    bundle = host.agent_runtime.resolve_context(host.principal(), site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID, expected_revision=initial["revision"])
    operations = compile_construction_command(layout=bundle.layout_document, catalog=bundle.asset_documents,
        command_id="cell-layout", arguments=ARRANGE, request_id="revision-check", namespace="b" * 40)
    result = host.service.preview_operations(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                            initial["revision"], operations)
    assert result["revision"] == layout_revision(result["document"])
    assert result["revision"] != result["baseRevision"]


def test_construction_does_not_displace_explicit_resource_batch_or_active_generation(construction_host, monkeypatch):
    import server
    host, initial = construction_host
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", host)
    message = "Group these tables and make three total cells in a linear pattern north."
    assert server._use_bounded_construction_provider(message, {})
    assert not server._use_bounded_construction_provider("Reduce the raw material rack batch to 89.", {})
    assert not server._use_bounded_construction_provider(message, {"facility_layout_state": {"generationDraft": {"runId": "active"}}})
    with pytest.raises(FacilityLayoutError, match="Geometry was not evaluated"):
        host.construction_service.preview(host.principal(), site_id=LOCAL_SITE_ID, layout_id=LOCAL_LAYOUT_ID,
            base_revision=initial["revision"], **_request("cell-layout", json.dumps(ARRANGE), initial["revision"], "invalid-object"))
    import asyncio
    bundle = host.agent_runtime.resolve_context(host.principal(), site_id=LOCAL_SITE_ID,
        layout_id=LOCAL_LAYOUT_ID, expected_revision=initial["revision"])
    request = server.AgentChatRequest(agent_type="deviation-analyst", message=
        "Use the Cell Layout preview tool to arrange the existing tables in a 1 m by 1 m envelope. Do not save.")
    result = asyncio.run(server._deterministic_semantic_chat_result(request, {
        "_facility_layout_document": bundle.layout_document, "facility_layout_state": bundle.state}))
    assert result is None, "Existing-placement construction must not ask for a legacy target department"
    prompt = "Arrange these two tables into a cell, attach the device to the worktop, group them and make three total cells. Do not save."
    plan = server._apply_facility_layout_request_tool_policy(
        {"workflow": {"id": "facility-layout-generation"}, "prompt": "", "allowed_tools": []},
        prompt, facility_state=bundle.state)
    assert plan["runtime_tool_policy"]["mode"] == "construction_preview"
    assert set(server.CONSTRUCTION_TOOLS) <= set(plan["allowed_tools"])
    assert server.SEMANTIC_FACILITY_PREVIEW_TOOL not in plan["allowed_tools"]
    assert server.FULL_FACTORY_TOOL not in plan["allowed_tools"]
    assert server.ensure_facility_layout_preview_tool_call([], plan, {}, prompt, "deviation-analyst") == ([], [], False)
