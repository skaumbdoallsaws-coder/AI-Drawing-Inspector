"""MB5c anchored replacement uses only installed, current catalog artifacts."""
from copy import deepcopy
import asyncio
import math

import pytest

from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from tests.model_builder_test_support import recipe, shape
from tests.test_model_builder_registration import context, include, register
from tests.test_model_import_catalog import placement


def pair(c):
    first, _ = c.host.build_model_draft(c.principal, c.reference, recipe())
    old = register(c, first)
    raw = recipe(include(c, old["assetId"], position=[.25, 0, .1]),
                 shape("box", id="tag", name="tag", min=[-.5, 0, .51], max=[.5, .1, .53]))
    made, _ = c.host.build_model_draft(c.principal, c.reference, raw)
    new = register(c, made)
    c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.reference["revision"],
        [{"op": "place_asset", "placementId": "pl-old", "placement": placement(old, name="pl-old", x=4, z=4)}])
    saved = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    operation = {"op": "replace_asset", "placementId": "pl-old", "assetId": new["assetId"],
                 "assetDefinitionRevision": new["assetDefinitionRevision"], "anchorInclude": "host"}
    return old, new, saved, operation


def test_anchor_preview_and_apply_after_restart_keep_the_old_host_pose(context):
    c = context
    old, new, saved, operation = pair(c)
    assert new["includeFrames"][0]["anchorable"] is True
    frame = new["includeFrames"][0]["frame"]
    assert frame is not None
    preview = c.host.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                 saved["revision"], [operation])
    report = preview["operationResults"][0]["replacement"]
    assert report == {"anchorInclude": "host", "carriedFinishes": [], "droppedFinishes": [], "droppedDecals": []}
    from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
    gateway = FacilityEditGateway(c.host.agent_runtime, c.principal,
        {**c.reference, "revision": saved["revision"]}, turn_id="anchor-preview")
    staged = asyncio.run(gateway.call("preview_facility_operations", {"operations": [operation]}))
    assert staged["ok"] and staged["data"]["replacements"] == [{"operationIndex": 0, **report}], staged
    assert c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved
    restarted = LocalFacilityLayoutHost(c.host.root, private_assets=True,
                                        private_asset_root=c.host._component_visual_root)
    try:
        restarted.ensure_bootstrap()
        applied = restarted.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                     saved["revision"], [operation])
        actual = applied["layout"]["placements"][0]
        assert actual["assetId"] == new["assetId"]
        assert applied["operationResult"]["operationResults"][0]["replacement"] == report
        tx = actual["transform"]
        fx, fy, fz = frame["translation"]
        yaw = math.radians(frame["yaw"])
        assert tx["position"]["x"] == pytest.approx(4 + math.cos(yaw)*fx - math.sin(yaw)*fz, abs=1e-6)
        assert tx["position"]["y"] == pytest.approx(-fy, abs=1e-6)
        assert tx["position"]["z"] == pytest.approx(4 - math.sin(yaw)*fx - math.cos(yaw)*fz, abs=1e-6)
    finally:
        restarted.close()


def test_anchor_refuses_wrong_include_and_stale_placed_revision(context):
    c = context
    old, new, saved, operation = pair(c)
    bad = dict(operation, anchorInclude="unknown")
    with pytest.raises(Exception) as caught:
        c.host.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [bad])
    assert getattr(caught.value, "code", None) == "anchor_include_missing"
    stale = deepcopy(saved["layout"])
    stale["placements"][0]["assetDefinitionRevision"] = "0" * 64
    from ai_inspector.facility_layout.model_builder_anchor import resolve_anchor_replacement
    with pytest.raises(Exception) as caught:
        resolve_anchor_replacement(c.host, c.principal, c.reference, stale, operation)
    assert getattr(caught.value, "code", None) == "anchor_include_mismatch"


def test_rotated_old_placement_uses_mirrored_include_frame(context):
    c = context
    old, new, saved, operation = pair(c)
    layout = deepcopy(saved["layout"])
    yaw = math.radians(35)
    layout["placements"][0]["transform"]["quaternion"] = {
        "w": math.cos(yaw/2), "x": 0, "y": math.sin(yaw/2), "z": 0}
    from ai_inspector.facility_layout.model_builder_anchor import resolve_anchor_replacement
    resolved, _ = resolve_anchor_replacement(c.host, c.principal, c.reference, layout, operation)
    frame = new["includeFrames"][0]["frame"]
    new_yaw = yaw + math.radians(frame["yaw"])
    pose = resolved["_anchorResolved"]["transform"]
    assert pose["quaternion"]["y"] == pytest.approx(math.sin(new_yaw/2))
    fx, fy, fz = frame["translation"]
    assert pose["position"]["x"] == pytest.approx(4 + math.cos(new_yaw)*fx - math.sin(new_yaw)*fz)
    assert pose["position"]["z"] == pytest.approx(4 - math.sin(new_yaw)*fx - math.cos(new_yaw)*fz)


def test_stale_artifact_bytes_and_nonanchorable_include_are_refused(context):
    c = context
    old, new, saved, operation = pair(c)
    grouped = recipe({"id": "assembly", "group": [include(c, old["assetId"])],
                      "repeat": {"count": 2, "step": [1.2, 0, 0]}})
    draft, _ = c.host.build_model_draft(c.principal, {**c.reference, "revision": saved["revision"]}, grouped)
    alternate = register(c, draft)
    assert alternate["includeFrames"][0]["anchorable"] is False
    bad = dict(operation, assetId=alternate["assetId"],
               assetDefinitionRevision=alternate["assetDefinitionRevision"])
    with pytest.raises(Exception) as caught:
        c.host.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [bad])
    assert getattr(caught.value, "code", None) == "anchor_include_pose_invalid"
    target = c.host._component_visual_root / "generated/industrial_assets/authored/built" / old["assetId"] / "model.glb"
    assert target.resolve().is_relative_to(c.host._component_visual_root.resolve())
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(Exception) as caught:
        c.host.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"], [operation])
    assert getattr(caught.value, "code", None) == "anchor_include_mismatch"


def test_part_finish_is_carried_and_equipment_decal_is_reported(context):
    c = context
    old, new, saved, operation = pair(c)
    finish = {"representation": "overview", "overrides": [{"key": "p:housing#0", "color": "#ff0000",
              "roughness": .3, "metalness": 0}]}
    changed = c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
        [{"op": "set_component_materials", "placementId": "pl-old", "materials": finish}])
    current = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    preview = c.host.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                 current["revision"], [operation])
    report = preview["operationResults"][0]["replacement"]
    assert report["carriedFinishes"][0]["from"] == "p:housing#0"
    output = preview["document"]["placements"][0]["componentMaterials"]["overrides"][0]
    assert output["key"] == report["carriedFinishes"][0]["to"] and output["color"] == "#ff0000"
    decal = {"decalId": "edecal-example", "label": "Test", "placementId": "pl-old",
             "imagePath": "/api/facility-decal-images/site-local/" + "b"*64 + ".png",
             "anchor": {"position": {"x": 0, "y": .5, "z": .5},
                        "normal": {"x": 0, "y": 0, "z": 1}, "rotationDegrees": 0},
             "widthMeters": .2, "heightMeters": .1}
    c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, current["revision"],
        [{"op": "set_equipment_decals", "decals": {"version": 1, "decals": [decal]}}])
    with_decal = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    preview = c.host.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                 with_decal["revision"], [operation])
    assert preview["operationResults"][0]["replacement"]["droppedDecals"] == ["edecal-example"]
    assert not preview["document"].get("extensions", {}).get("facilityEquipmentDecals", {}).get("decals")


def test_overview_with_different_hierarchy_drops_recorded_part_finish(context):
    c = context
    old, new, saved, operation = pair(c)
    from ai_inspector.industrial_assets.model_builder.build import build_model
    alternate = build_model(recipe(shape(name="overview only")),
                            allowed_categories=["Material Handling"], allowed_appearance_ids=[]).glb
    folder = c.host._component_visual_root / "generated/industrial_assets/authored/built" / old["assetId"]
    assert folder.resolve().is_relative_to(c.host._component_visual_root.resolve())
    (folder / "model.overview.glb").write_bytes(alternate)
    restarted = LocalFacilityLayoutHost(c.host.root, private_assets=True,
                                        private_asset_root=c.host._component_visual_root)
    try:
        restarted.ensure_bootstrap()
        ref = {**c.reference, "revision": saved["revision"]}
        inventory = restarted._resolve_component_inventory(c.principal, ref, "pl-old", "overview")
        key = inventory["slots"][0]["key"]
        assert key != "p:housing#0"
        applied = restarted.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
            [{"op": "set_component_materials", "placementId": "pl-old", "materials": {
                "representation": "overview", "overrides": [{"key": key, "color": "#ff0000",
                                                       "roughness": .3, "metalness": 0}]}}])
        result = restarted.service.preview_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
                                                      applied["revision"], [operation])
        report = result["operationResults"][0]["replacement"]
        assert report["carriedFinishes"] == [] and report["droppedFinishes"] == [key]
        assert "componentMaterials" not in result["document"]["placements"][0]
    finally:
        restarted.close()


def test_two_distinct_finishes_cannot_merge_onto_one_output_part(context):
    c = context
    raw = recipe(shape(), shape(id="leg", name="leg", min=[-.2, 0, -.2], max=[.2, .2, .2]))
    made, _ = c.host.build_model_draft(c.principal, c.reference, raw)
    old = register(c, made)
    c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, c.reference["revision"],
        [{"op": "place_asset", "placementId": "pl-old", "placement": placement(old, name="pl-old")}])
    saved = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    ref = {**c.reference, "revision": saved["revision"]}
    inventory = c.host._resolve_component_inventory(c.principal, ref, "pl-old", "overview")
    keys = [slot["key"] for slot in inventory["slots"]]
    assert len(keys) == 2
    finishes = {"representation": "overview", "overrides": [
        {"key": keys[0], "color": "#ff0000", "roughness": .2, "metalness": 0},
        {"key": keys[1], "color": "#0000ff", "roughness": .2, "metalness": 0}]}
    c.host.service.apply_operations(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
        [{"op": "set_component_materials", "placementId": "pl-old", "materials": finishes}])
    current = c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    from ai_inspector.facility_layout.model_builder_anchor import _finishes
    from ai_inspector.industrial_assets.model_builder_host import IncludeCatalog
    artifact = IncludeCatalog(c.host._component_visual_root).resolve(old["assetId"], for_build=False)["payload"]
    with pytest.raises(Exception) as caught:
        _finishes(c.host, c.principal, {**ref, "revision": current["revision"]},
                  current["layout"]["placements"][0],
                  {"partMap": {key: "p:merged#0" for key in keys}}, artifact)
    assert getattr(caught.value, "code", None) == "anchor_finish_conflict"
