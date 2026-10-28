import asyncio

import pytest
from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway, edit_tool_specs
from ai_inspector.codex_runtime.facility_tools import OUTPUT_SCHEMA
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID


@pytest.fixture
def setup(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    host.ensure_bootstrap()
    saved = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    gateway = FacilityEditGateway(host.agent_runtime, host.principal(), {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="edit-check")
    yield host, gateway, saved
    host.close()


def test_contract_has_no_commit_approval_or_shell_capability(setup):
    _, gateway, _ = setup
    assert {s["name"] for s in edit_tool_specs()} == {"preview_facility_operations", "preview_facility_undo",
                                                      "preview_planned_design"}
    for spec in gateway.specs:
        Draft202012Validator.check_schema(spec["input_schema"])


def test_model_creates_only_preview_and_unknown_fields_are_rejected(setup):
    host, gateway, saved = setup
    async def run():
        invalid = await gateway.call("preview_facility_operations", {"operations": [
            {"op": "rename_layout", "displayName": "New name", "approve": True}]})
        assert invalid["error"]["code"] == "codex_tool_arguments_invalid"
        denied = await gateway.call("apply_layout_proposal", {"approved": True})
        assert denied["error"]["code"] == "codex_tool_denied"
        result = await gateway.call("preview_facility_operations", {"operations": [
            {"op": "rename_layout", "displayName": "New name"}]})
        Draft202012Validator(OUTPUT_SCHEMA).validate(result)
        assert result["ok"] and result["data"]["approvalRequired"] and not result["data"]["saved"]
        assert gateway.proposal["proposalId"] == result["data"]["proposalId"]
    asyncio.run(run())
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved


@pytest.mark.parametrize("schema_invalid", [False, True])
def test_failed_latest_preview_does_not_offer_an_old_preview(setup, schema_invalid):
    host, gateway, saved = setup
    async def run():
        assert (await gateway.call("preview_facility_operations", {"operations": [{"op": "rename_layout", "displayName": "Preview"}]}))["ok"]
        arguments = {"operations": [{"op": "move_placement",
            "placementId": "pl-missing", "position": {"x": 1, "y": 0, "z": 1}}]}
        if schema_invalid:
            arguments["approved"] = True
        result = await gateway.call("preview_facility_operations", arguments)
        assert not result["ok"] and gateway.proposal is None
    asyncio.run(run())
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved


def test_oversized_preview_result_is_not_exposed_as_ready(setup, monkeypatch):
    host, gateway, saved = setup
    original = gateway._read_data
    def oversized(name, arguments):
        result = original(name, arguments)
        result["unexpectedLargeData"] = "x" * 70000
        return result
    monkeypatch.setattr(gateway, "_read_data", oversized)
    result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [
        {"op": "rename_layout", "displayName": "Preview"}]}))
    assert result["error"]["code"] == "codex_result_too_large" and gateway.proposal is None
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved


def test_missing_discriminator_returns_exact_contract_without_accepting_aliases(setup):
    _, gateway, _ = setup
    result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [{
        "type": "add_floor_marking", "marking": {"kind": "line", "width": .05}}]}))
    details = result["error"]["details"]
    assert details["findings"][0]["path"] == "/operations/0/op"
    assert "required 'op'" in details["findings"][0]["message"]
    contract = details["operationContract"]
    Draft202012Validator.check_schema(contract)
    operation = contract["properties"]["operations"]["items"]["oneOf"][0]
    assert operation["required"] == ["op", "floorMarking"]
    assert gateway.proposal is None


def test_required_fields_are_reported_together_not_six_at_a_time(setup):
    _, gateway, _ = setup
    result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [{
        "op": "add_floor_marking", "floorMarking": {}}]}))
    findings = result["error"]["details"]["findings"]
    required = [f for f in findings if f["message"].startswith("Required properties missing:")]
    assert len(required) == 1
    for key in ("markingType", "label", "semanticRole", "transform", "width", "depth",
                "fillColor", "strokeColor", "opacity", "text", "positionMode", "metadata", "evidence"):
        assert key in required[0]["message"]


def test_contract_read_is_scoped_closed_and_resolves_all_local_definitions(setup):
    host, gateway, saved = setup
    result = asyncio.run(gateway.call("inspect_facility_operation_contracts", {
        "operations": ["place_asset", "add_floor_marking", "upsert_floor_surface"]}))
    assert result["ok"]
    schema = result["data"]["schema"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({"operations": [{"op": "rename_layout", "displayName": "No"}]})
    placement = schema["properties"]["operations"]["items"]["oneOf"][0]["properties"]["placement"]
    transform = placement["properties"]["transform"]
    if "$ref" in transform:
        transform = schema["$defs"][transform["$ref"].split("/")[-1]]
    assert transform["properties"]["scale"]["const"] == 1
    assert gateway.proposal is None
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved


def test_focused_contract_matches_every_full_operation_schema(setup):
    from ai_inspector.codex_runtime.operation_contracts import contracts
    _, gateway, _ = setup
    for variant in gateway.operation_schema["properties"]["operations"]["items"]["oneOf"]:
        focused = contracts(gateway.operation_schema, [variant["properties"]["op"]["const"]])
        assert focused["properties"]["operations"]["items"]["oneOf"] == [variant]
        Draft202012Validator.check_schema(focused)
        def check_refs(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    assert value["$ref"].startswith("#/$defs/")
                    assert value["$ref"][8:] in focused["$defs"]
                for item in value.values():
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)
        check_refs(focused)


def test_curved_paint_preview_uses_real_entities_and_requires_review_for_large_expansion(setup):
    _, gateway, _ = setup
    gateway.edit_mode = "direct"
    result = asyncio.run(gateway.call("preview_facility_operations", {"operations": [{
        "op": "add_floor_path", "path": {"label": "Circle", "color": "#FFFFFF", "lineWidth": .05,
            "elevation": .015, "shape": {"kind": "arc", "center": {"x": 10, "z": 10}, "radius": 1.8,
                "startDegrees": 0, "sweepDegrees": 360}}}]}))
    assert result["ok"], result
    assert result["data"]["metrics"]["affectedCount"] == 128
    assert result["data"]["approvalRequired"] and not result["data"]["directApplyPolicy"]["eligible"]


def test_authoring_plan_reports_corner_origin_bounds_from_saved_document(setup):
    host, _, saved = setup
    from copy import deepcopy
    layout = deepcopy(saved["layout"])
    layout.setdefault("extensions", {})["facilityPlan"] = {
        "widthMeters": 82, "depthMeters": 36.5, "gridSpacingMeters": .5, "majorGridSpacingMeters": 5}
    saved = host.layout_repository.save_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, layout, saved["revision"])
    gateway = FacilityEditGateway(host.agent_runtime, host.principal(), {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved["revision"]}, turn_id="plan-bounds")
    for view in ("plan", "overview"):
        result = asyncio.run(gateway.call("inspect_facility_authoring", {"view": view}))
        assert result["ok"]
        assert result["data"]["floorAuthority"] == "plan"
        assert result["data"]["planWorldBounds"] == {
            "minX": 0, "minZ": 0, "maxX": 82, "maxZ": 36.5, "floorY": layout["coordinateFrame"]["floorElevation"]}


def test_a_planned_build_step_is_staged_whole_as_one_review(setup, monkeypatch):
    host, gateway, saved = setup
    from ai_inspector.codex_runtime import site_tools

    def marking(number):
        return {"op": "add_floor_marking", "floorMarking": {
            "markingId": f"fm-stall-{number:03}", "markingType": "parking_box", "label": f"Stall {number}",
            "semanticRole": "parking", "transform": {"position": {"x": 1 + number % 10 * 3, "y": 0.008, "z": 1 + number // 10 * 6},
                                                     "rotationDegrees": 0},
            "width": 2.7, "depth": 5.4, "fillColor": "#ffffff", "strokeColor": "#ffffff", "opacity": 1, "text": "",
            "positionMode": "manual", "metadata": {}, "evidence": []}}
    plan = {"available": True, "step": "markings", "operations": [marking(n) for n in range(60)], "summary": {}}
    monkeypatch.setattr(site_tools, "read_site", lambda *args, **kwargs: dict(plan))
    read = gateway._read_data("plan_floor_markings", {"stagingLanes": 6})
    assert read["package"] == {"packageId": "markings-1", "operations": 60} and "operations" not in read
    async def run():
        unknown = await gateway.call("preview_planned_design", {"packageId": "markings-9"})
        assert unknown["error"]["code"] == "codex_design_package_unknown"
        staged = await gateway.call("preview_planned_design", {"packageId": "markings-1"})
        assert staged["ok"], staged
        assert staged["data"]["approvalRequired"] and gateway.proposal["proposalId"] == staged["data"]["proposalId"]
    asyncio.run(run())  # 60 operations: more than one model-written batch may hold
    assert host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved
    # Opening the review and approving it rebuild the proposal from its stored request, under the package's limits.
    principal, proposal_id = host.principal(), gateway.proposal["proposalId"]
    preview = host.service.get_layout_proposal_preview(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id)
    binding = preview["alternative"]["transactionBinding"]
    assert len(preview["alternative"]["operations"]) == 60
    approval = host.service.approve_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, proposal_id, binding,
                                                    session_id="test-approver", idempotency_key="test-package",
                                                    explicit_approval=True)
    committed = host.service.apply_layout_proposal(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, approval["approvalToken"],
                                                   binding, session_id="test-approver", idempotency_key="test-package")
    added = {m["markingId"] for m in committed["layout"]["floorMarkings"]} - \
        {m["markingId"] for m in saved["layout"]["floorMarkings"]}
    assert len(added) == 60
