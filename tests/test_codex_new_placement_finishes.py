"""Part finishes on a new item in one request (the user's go, 2026-11-01, relayed by the main session).

inspect_facility_components reads a model's part keys by assetId before it is placed, and one preview places it and
gives it its part finishes (place_asset, then set_component_materials for the new placementId), proven against that
asset's catalog visual: the same bytes and keys a saved placement of it has. On a host with the real light fittings
(tools/factory02_light_models.py)."""
import json

import pytest

from ai_inspector.codex_runtime.component_inventory import inspect_components, tool_specs
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.operation_proposals import create
from tests.test_facility_operation_proposals import apply, approve
from tools import factory02_light_models as models

LENS = "p:rotating-beacon/beacon%20lens#0"


@pytest.fixture
def lit(tmp_path):
    root = tmp_path / "project"
    manifest = root / models.CATALOG
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(json.dumps({"assets": [], "schemaVersion": 1, "summary": {"total": 0}}).encode("ascii"))
    models.install(root)
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=root)
    host.ensure_bootstrap()
    try:
        yield host
    finally:
        host.close()


def saved(host):
    return host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)


def reference(host):
    return {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved(host)["revision"]}


def parts_of(host, **arguments):
    return inspect_components(host.agent_runtime, host.principal(), reference(host), arguments)


def propose(host, operations, **kwargs):
    return create(host.service, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved(host)["revision"],
                  operations=operations, **kwargs)


def beacon(host, placement_id="pl-beacon", named="both"):
    """A place_asset for a beacon, its placementId on the op and the placement (as Sage sends it), on one of them,
    or on "none" (the engine then makes one up)."""
    asset = next(item for item in host._agent_asset_catalog(host.principal(), LOCAL_SITE_ID)
                 if item["assetId"] == models.BEACON)
    placement = {"placementId": placement_id, "assetId": asset["assetId"],
        "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "transform": {"position": {"x": 5, "y": 0, "z": 5}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
        "positionMode": "locked", "snapRelationship": None, "metadata": {"instanceLabel": "Beacon 1"}}
    op = {"op": "place_asset", "placementId": placement_id, "placement": placement}
    if named in ("op", "none"):
        del placement["placementId"]
    if named in ("placement", "none"):
        del op["placementId"]
    return op


def alarm_red(parts, placement_id="pl-beacon", key=LENS, **changed):
    return {"op": "set_component_materials", "placementId": placement_id, "visualSha256": parts["visualSha256"],
            "materials": {"representation": "overview", "overrides": [
                {"key": key, "appearanceId": "light-alarm-red", "pattern": "strobe", "periodSeconds": 0.5}]},
            **changed}


def test_the_parts_of_an_item_before_it_is_placed(lit):
    parts = parts_of(lit, assetId=models.BEACON)
    assert parts["placementId"] is None and parts["assetId"] == models.BEACON
    assert parts["assetDefinitionRevision"] == beacon(lit)["placement"]["assetDefinitionRevision"]
    lens = next(slot for slot in parts["slots"] if slot["key"] == LENS)
    assert lens["defaultFinish"] == "light-beacon-amber"
    assert lens["shown"]["source"] == "the model's default finish: Beacon amber"
    assert "place_asset" in parts["forNewPlacement"]
    # With the placementId Sage will give it (not saved yet) beside the assetId, as the desktop's beacon turn first
    # asked (2026-11-01): the same parts, not a failed step.
    planned = parts_of(lit, assetId=models.BEACON, placementId="pl-beacon")
    assert planned["placementId"] is None and planned["visualSha256"] == parts["visualSha256"]
    assert [slot["key"] for slot in planned["slots"]] == [slot["key"] for slot in parts["slots"]]
    # The same bytes and keys as a saved placement of it.
    context = lit.service, lit.principal()
    placed = propose(lit, [beacon(lit)])
    apply(context, placed, approve(context, placed))
    again = parts_of(lit, placementId="pl-beacon")
    assert again["visualSha256"] == parts["visualSha256"] and again["placementId"] == "pl-beacon"
    assert [slot["key"] for slot in again["slots"]] == [slot["key"] for slot in parts["slots"]]
    for arguments in ({}, {"assetId": models.BEACON, "placementId": "pl-beacon"}):
        with pytest.raises(PilotError) as error:
            parts_of(lit, **arguments)
        assert error.value.code == "codex_component_target_required"
    with pytest.raises(PilotError) as error:
        parts_of(lit, assetId="asset-not-in-the-library")
    assert error.value.code == "codex_asset_unavailable"
    schema = tool_specs()[0]["input_schema"]
    assert schema["required"] == [] and {"placementId", "assetId"} <= set(schema["properties"])


@pytest.mark.parametrize("named", ["both", "placement", "op"])
def test_a_new_beacon_is_placed_with_its_part_finish_in_one_proposal(lit, named):
    """The user's example: a rotating beacon with the alarm red finish, strobing. One preview, Apply directly."""
    context = lit.service, lit.principal()
    parts = parts_of(lit, assetId=models.BEACON)
    result = propose(lit, [beacon(lit, named=named), alarm_red(parts)], edit_mode="direct")
    alternative = result["alternative"]
    assert alternative["directApplyPolicy"]["eligible"] is True, alternative["directApplyPolicy"]
    finished = next(item for item in alternative["ghostPreview"]["layout"]["placements"]
                    if item["placementId"] == "pl-beacon")["componentMaterials"]
    assert finished["representation"] == "overview"
    assert [(row["key"], row["appearanceId"], row["pattern"], row["periodSeconds"]) for row in finished["overrides"]] == [
        (LENS, "light-alarm-red", "strobe", 0.5)]
    saved_now = apply(context, result, approve(context, result))["layout"]
    assert next(item for item in saved_now["placements"]
                if item["placementId"] == "pl-beacon")["componentMaterials"] == finished
    shown = next(slot for slot in parts_of(lit, placementId="pl-beacon")["slots"] if slot["key"] == LENS)["shown"]
    assert shown["source"] == "part override: Alarm red"


@pytest.mark.parametrize("case", ["changed visual", "unknown key", "finish before its place_asset",
                                  "nobody places it", "its place_asset names no placementId",
                                  "inline componentMaterials"])
def test_a_new_placements_finish_is_proven_like_a_saved_ones(lit, case):
    parts = parts_of(lit, assetId=models.BEACON)
    placed = beacon(lit)
    operations = {
        "changed visual": [placed, alarm_red(parts, visualSha256="0" * 64)],
        "unknown key": [placed, alarm_red(parts, key="p:rotating-beacon/no%20such%20part#0")],
        "finish before its place_asset": [alarm_red(parts), placed],
        "nobody places it": [placed, alarm_red(parts, placement_id="pl-other")],
        "its place_asset names no placementId": [beacon(lit, named="none"), alarm_red(parts)],
        "inline componentMaterials": [dict(placed, placement=dict(placed["placement"],
                                           componentMaterials=alarm_red(parts)["materials"]))],
    }[case]
    expected = {"changed visual": "component_visual_revision_conflict",
                "unknown key": "component_material_key_unavailable"}.get(case, "component_target_requires_saved_visual")
    before = saved(lit)
    with pytest.raises(FacilityLayoutError) as error:
        propose(lit, operations)
    assert error.value.code == expected
    assert saved(lit) == before
