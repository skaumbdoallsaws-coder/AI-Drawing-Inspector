"""Actual saved-gym transactions; no model, geometry mocks, or user-layout writes."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.check_codex_facility_authoring import (
    CASES, LAYOUT_RELATIVE, SOURCE_ROOT, SavedGym, case_operations, prepare_output, round_trip,
)


@pytest.fixture(scope="module")
def gym(tmp_path_factory):
    if not (SOURCE_ROOT / LAYOUT_RELATIVE).is_file():
        pytest.skip("Actual local saved Private Gym fixture is unavailable; use the explicit offline harness")
    root = tmp_path_factory.mktemp("codex-authoring") / "isolated"
    copied = SavedGym(root)
    try:
        yield copied
    finally:
        copied.close()


@pytest.mark.parametrize("name", CASES)
def test_saved_gym_gateway_preview_approve_commit_and_receipt_undo(gym, name):
    result = round_trip(gym, name)
    assert result["sourceUnchanged"] and result["restoredExactExceptUpdatedAt"]


@pytest.mark.parametrize("name", CASES)
def test_real_authoring_arguments_have_closed_published_schema(gym, name):
    gateway = gym.gateway(gym.current()["revision"])
    spec = next(spec for spec in gateway.specs if spec["name"] == "preview_facility_operations")
    schema = spec["input_schema"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    arguments = {"operations": case_operations(gym, name)}
    assert validator.is_valid(arguments), name
    assert not validator.is_valid({**arguments, "approve": True})
    invalid = deepcopy(arguments)
    invalid["operations"][0]["arbitraryFilePath"] = "C:/not-authorized"
    assert not validator.is_valid(invalid)


def test_saved_gym_viewer_and_stale_gateway_cannot_propose(gym):
    before = gym.current()
    gateway = gym.gateway(before["revision"])
    gateway.principal = replace(gym.principal, roles=("viewer",))
    arguments = {"operations": case_operations(gym, "floor_marking_generated_id")}
    result = asyncio.run(gateway.call("preview_facility_operations", arguments))
    assert not result["ok"] and result["error"]["code"] != "codex_tool_arguments_invalid"
    from ai_inspector.codex_runtime.policy import PilotError
    with pytest.raises(PilotError) as stale:
        gym.gateway("0" * 64)
    assert stale.value.code == "codex_document_unavailable"
    assert gym.current() == before
    gym.assert_source()


def test_invalid_batch_does_not_partially_save_or_leave_ready_preview(gym):
    before = gym.current()
    gateway = gym.gateway(before["revision"])
    operations = case_operations(gym, "floor_marking_generated_id") + [{
        "op": "move_placement", "placementId": "pl-missing-authoring-check",
        "position": {"x": 1, "y": 0, "z": 1}}]
    result = asyncio.run(gateway.call("preview_facility_operations", {"operations": operations}))
    assert not result["ok"] and result["error"]["code"] != "codex_tool_arguments_invalid"
    assert gateway.proposal is None and gym.current() == before


def test_existing_cell_group_engine_contract_has_exact_approved_undo(gym):
    # The engine supports geometric cell metadata even before the MCP schema exposes it.
    result = round_trip(gym, "cell_group", layer="engine")
    assert result["restoredExactExceptUpdatedAt"]


def test_floor_finish_outside_plan_is_supported_on_existing_ground(gym):
    from ai_inspector.facility_layout.operation_proposals import create

    before = gym.current()
    ground = before["layout"]["extensions"]["facilityGround"]["surfaces"]
    assert any(row["minX"] <= 1 and row["maxX"] >= 2 and row["minZ"] <= -5 and
               row["maxZ"] >= -4 and row["startElevation"] == row["endElevation"] == 0 for row in ground)
    operations = case_operations(gym, "floor_surface_color")
    operations[0]["surfaces"]["surfaces"][-1]["boundary"] = [
        {"x": x, "z": z} for x, z in ((1, -5), (2, -5), (2, -4), (1, -4))]
    preview = create(gym.host.service, gym.principal, gym.site_id, gym.layout_id,
                     before["revision"], operations=operations)
    assert preview["approvalRequired"]
    assert preview["alternative"]["ghostPreview"]["layout"]["extensions"]["facilityFloorSurfaces"] == operations[0]["surfaces"]
    assert gym.current() == before


@pytest.mark.parametrize("relationship", ["same", "child", "parent", "existing"])
def test_harness_rejects_source_overlap_or_existing_output(tmp_path, relationship):
    source = tmp_path / "source"
    source.mkdir()
    output = {"same": source, "child": source / "child", "parent": tmp_path,
              "existing": tmp_path / "existing"}[relationship]
    if relationship == "existing":
        output.mkdir()
    with pytest.raises(AssertionError):
        prepare_output(output, source)
    assert source.is_dir()


def test_fit_check_takes_an_asset_id_alone_when_it_has_one_revision(gym):
    saved = gym.current()
    revisions = {}
    for item in gym.host.agent_runtime.asset_catalog_provider(gym.principal, gym.site_id):
        revisions.setdefault(item["assetId"], set()).add(item["assetDefinitionRevision"])
    asset_id = "asset-keyboard" if len(revisions.get("asset-keyboard", ())) == 1 else next(
        key for key, value in sorted(revisions.items()) if len(value) == 1)
    zone_id = saved["layout"]["zones"][0]["zoneId"]
    result = asyncio.run(gym.gateway(saved["revision"]).call(
        "analyze_facility_fit", {"assetId": asset_id, "zoneId": zone_id, "maximumResults": 2}))
    assert result["ok"], result
    assert result["data"]["assetDefinitionRevision"] == next(iter(revisions[asset_id]))
    assert gym.current() == saved


def test_harness_has_no_native_or_inference_entry_point():
    source = (Path(__file__).resolve().parents[1] / "tools/check_codex_facility_authoring.py").read_text()
    assert "import server" not in source
    assert "subprocess" not in source
    assert "turn/start" not in source
