"""MB5a: Sage recipe tools, bounded edits, and next-turn room checks."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway
from ai_inspector.codex_runtime.pilot import Journal, built_room_check_ids
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.model_builder_sources import DEFAULT_COOKBOOK, cookbook_index, cookbook_recipe
from ai_inspector.industrial_assets.model_builder.edits import apply_edits
from ai_inspector.industrial_assets.model_builder.errors import ModelBuildError
from tests.model_builder_test_support import recipe, shape
from tests.model_builder_draft_support import project
from tests.model_import_store_support import PNG
from tests.test_model_builder_registration import context


def gateway(c, *, timeout=240, edit=True):
    kind = FacilityEditGateway if edit else FacilityReadGateway
    return kind(c.host.agent_runtime, c.principal, c.reference, turn_id="builder-test",
                max_calls=24, timeout=timeout)


def test_bundled_cookbook_index_and_recipes_validate_against_the_catalog(tmp_path):
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True,
                                   private_asset_root=project(tmp_path))
    try:
        host.ensure_bootstrap()
        categories = sorted({row["category"] for row in host.list_assets()["assets"]})
        for entry in cookbook_index(DEFAULT_COOKBOOK):
            value = cookbook_recipe(DEFAULT_COOKBOOK, entry["id"], categories=categories,
                                    appearance_ids=[])
            assert value["name"] == entry["name"] and value["size"] == entry["size"]
    finally:
        host.close()


def test_edits_update_add_remove_material_top_and_refuse_unknown_id():
    source = recipe(shape(), {"id": "stand", "name": "stand", "material": "paint",
                              "shape": "box", "min": [-.1, 0, -.1], "max": [.1, .2, .1]})
    result = apply_edits(source, [
        {"op": "update", "id": "body", "set": {"name": "shell"}},
        {"op": "remove", "id": "stand"},
        {"op": "add", "after": "body", "entry": {"id": "foot", "name": "foot", "material": "paint",
                                                 "shape": "box", "min": [-.2, 0, -.2], "max": [.2, .1, .2]}},
        {"op": "material", "name": "paint", "set": {"color": "#334455"}},
        {"op": "top", "set": {"name": "Revised equipment"}},
    ], allowed_categories=["Material Handling"], allowed_appearance_ids=[])
    assert [entry["id"] for entry in result["entries"]] == ["body", "foot"]
    assert result["entries"][0]["name"] == "shell" and result["materials"]["paint"]["color"] == "#334455"
    assert result["name"] == "Revised equipment"
    with pytest.raises(ModelBuildError) as caught:
        apply_edits(source, [{"op": "update", "id": "absent", "set": {"name": "x"}}],
                    allowed_categories=["Material Handling"], allowed_appearance_ids=[])
    assert caught.value.path == "$.edits[0].id" and source["entries"][0]["name"] == "housing"


def test_gateway_build_revise_register_recipe_include_and_restart(context, tmp_path, monkeypatch):
    c = context
    cookbook = tmp_path / "cookbook"
    cookbook.mkdir()
    example = recipe()
    (cookbook / "index.json").write_text(json.dumps({"schemaVersion": 1, "recipes": [{
        "id": "equipment", "name": example["name"], "size": example["size"], "teaches": "Box shape"}]}))
    (cookbook / "equipment.json").write_text(json.dumps(example))
    c.host._model_import_hooks.cookbook_root = cookbook
    edit = gateway(c)
    built = asyncio.run(edit.call("build_model_draft", example))
    assert built["ok"], built
    draft_id = built["data"]["draftId"]
    assert built["turnRemaining"]["calls"] == 23
    assert built["data"]["parts"][0]["id"] == "p:housing#0"
    assert len(json.dumps(built["data"]).encode()) <= 48 * 1024
    assert edit.take_image()["mimeType"] == "image/png"
    before = c.host.list_assets()["catalogVersion"]
    revised = asyncio.run(edit.call("revise_model_draft", {"draftId": draft_id, "edits": [
        {"op": "top", "set": {"name": "Revised equipment"}}]}))
    assert revised["ok"], revised
    changed = revised["data"]["draftId"]
    assert changed != draft_id and c.host.list_assets()["catalogVersion"] == before
    assert edit.take_image()["mimeType"] == "image/png"
    focus_calls = []
    monkeypatch.setattr(c.store, "focus_build_view", lambda *args, **kwargs:
                        (focus_calls.append(args[2]), PNG)[1])
    focused = asyncio.run(edit.call("inspect_model_import", {"draftId": changed, "focus": "housing"}))
    assert focused["ok"] and "turnRemaining" in focused, focused
    assert focus_calls == ["housing"]
    assert edit.take_image()["mimeType"] == "image/png"
    listing = asyncio.run(edit.call("get_model_recipe", {}))
    assert listing["ok"] and listing["data"]["cookbook"][0]["id"] == "equipment"
    assert any(item["draftId"] == changed for item in listing["data"]["drafts"])
    assert len(json.dumps(listing["data"]).encode()) <= 48 * 1024
    assert asyncio.run(edit.call("get_model_recipe", {"cookbookId": "equipment"}))["data"]["recipe"]["name"] == example["name"]
    assert asyncio.run(edit.call("get_model_recipe", {"draftId": changed}))["data"]["recipe"]["name"] == "Revised equipment"
    registered = asyncio.run(edit.call("register_model_asset", {"draftId": changed}))
    assert registered["ok"], registered
    asset_id = registered["data"]["assetId"]
    assert registered["turnRemaining"]["calls"] == 17
    assert any(item["assetId"] == asset_id for item in asyncio.run(edit.call("get_model_recipe", {}))["data"]["registeredLast24Hours"])
    included = asyncio.run(edit.call("inspect_model_include", {"assetId": asset_id, "limit": 1}))
    assert included["ok"] and included["data"]["parts"][0]["key"].startswith("p:")
    from tests.test_model_import_catalog import placement
    proposed = asyncio.run(edit.call("preview_facility_operations", {"operations": [
        {"op": "place_asset", "placementId": "pl-new-built",
         "placement": placement(registered["data"], name="pl-new-built")}] }))
    assert proposed["ok"] and proposed["data"]["approvalRequired"] and not proposed["data"]["saved"], proposed
    assert c.host.service.get_layout(c.principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)["layout"]["placements"] == []
    restarted = LocalFacilityLayoutHost(c.host.root, private_assets=True,
                                        private_asset_root=c.host._component_visual_root)
    try:
        restarted.ensure_bootstrap()
        restarted.service._model_import_store = c.store
        restarted._model_import_hooks.cookbook_root = cookbook
        again = FacilityEditGateway(restarted.agent_runtime, c.principal, c.reference,
                                    turn_id="after-restart", timeout=240)
        asset_recipe = asyncio.run(again.call("get_model_recipe", {"assetId": asset_id}))
        assert asset_recipe["ok"], asset_recipe
        assert any(item["assetId"] == asset_id for item in
                   asyncio.run(again.call("get_model_recipe", {}))["data"]["registeredLast24Hours"])
        # The installed recipe remains authoritative once the source draft has expired and been swept.
        import shutil
        source_folder = c.store.root / c.scope.key / "drafts" / changed
        assert source_folder.resolve().is_relative_to(c.store.root.resolve())
        shutil.rmtree(source_folder)
        revision = asset_recipe["data"]["revision"]
        stale_asset = asyncio.run(again.call("revise_model_draft", {"assetId": asset_id,
            "revision": "0" * 64, "edits": [{"op": "top", "set": {"name": "Ignored"}}]}))
        assert stale_asset["error"]["code"] == "model_recipe_mismatch"
        cloned = asyncio.run(again.call("revise_model_draft", {"assetId": asset_id, "revision": revision,
            "edits": [{"op": "top", "set": {"name": "New revision"}}]}))
        assert cloned["ok"], cloned
        assert c.store.draft(c.scope, cloned["data"]["draftId"])["buildProvenance"]["derivedFrom"] == asset_id
    finally:
        restarted.close()


def test_budget_refusal_reports_no_draft_or_retained_draft(context):
    c = context
    edit = gateway(c, timeout=80)
    first = asyncio.run(edit.call("build_model_draft", recipe()))
    assert first["error"]["code"] == "turn_budget_low" and "No draft was built" in first["error"]["message"]
    assert first["turnRemaining"]["seconds"] <= 80
    ready, _ = c.host.build_model_draft(c.principal, c.reference, recipe())
    retained = asyncio.run(edit.call("revise_model_draft", {"draftId": ready["draftId"], "edits": [
        {"op": "top", "set": {"name": "Later"}}]}))
    assert retained["error"]["code"] == "turn_budget_low"
    assert retained["error"]["details"] == {"draftId": ready["draftId"]}
    assert c.store.draft(c.scope, ready["draftId"])["recipe"]["name"] == recipe()["name"]


def test_budget_refusal_after_a_build_in_the_same_turn_names_that_draft(context):
    c = context
    edit = gateway(c)
    built = asyncio.run(edit.call("build_model_draft", recipe()))
    assert built["ok"], built
    edit.deadline -= edit.deadline_remaining() - 50
    again = asyncio.run(edit.call("build_model_draft", recipe(name="Second equipment")))
    assert again["error"]["code"] == "turn_budget_low"
    assert "No draft was built" not in again["error"]["message"]
    assert again["error"]["details"] == {"draftId": built["data"]["draftId"]}


def test_request_limit_and_unknown_edit_are_bounded_without_mutation(context):
    c = context
    edit = gateway(c)
    too_large = asyncio.run(edit.call("build_model_draft", recipe(name="x" * 33000)))
    assert too_large["error"]["code"] == "codex_tool_arguments_too_large"
    assert "turnRemaining" in too_large
    ready, _ = c.host.build_model_draft(c.principal, c.reference, recipe())
    refused = asyncio.run(edit.call("revise_model_draft", {"draftId": ready["draftId"], "edits": [
        {"op": "update", "id": "unknown", "set": {"name": "Changed"}}]}))
    assert refused["error"]["code"] == "schema_invalid" and refused["error"]["details"]["path"] == "$.edits[0].id"
    assert c.store.draft(c.scope, ready["draftId"])["recipe"]["name"] == recipe()["name"]
    assert asyncio.run(gateway(c, edit=False).call("build_model_draft", recipe()))["error"]["code"] == "codex_tool_denied"


def test_stale_layout_binding_refuses_build_before_draft(context):
    c = context
    edit = gateway(c)
    edit.reference["revision"] = "0" * 64
    result = asyncio.run(edit.call("build_model_draft", recipe()))
    assert result["error"]["code"] == "codex_document_unavailable"
    assert "turnRemaining" in result and c.store.list_build_drafts(c.scope) == []


@pytest.mark.parametrize("mode", ["review", "direct"])
def test_room_check_accepts_new_review_or_direct_receipt_once(tmp_path, mode):
    journal = Journal(tmp_path)
    key, asset = "conversation", "asset-built-test-" + "a" * 24
    start = time.time() - 5
    journal.record_builder_turn(key, [asset], start)
    assert journal.builder_state(key) == ([asset], start)
    placement = {"placementId": "pl-new", "assetId": asset}
    receipt = {"createdAt": start + (6 if mode == "review" else 1),
               "payload": {"operationResult": {"createdIds": ["pl-new"]}}}
    service = SimpleNamespace(get_layout=lambda *_: {"layout": {"placements": [placement]}},
                              get_layout_receipt=lambda *_: receipt)
    reference = {"siteId": "site", "layoutId": "layout"}
    assert built_room_check_ids(service, None, reference, ["receipt"], {asset}, start) == ["pl-new"]
    # A direct save occurs before the previous turn finishes; the receipt must still count.
    next_start = start + (7 if mode == "review" else 2)
    journal.record_builder_turn(key, [], next_start)
    assert built_room_check_ids(service, None, reference, ["receipt"], {asset}, next_start) == []
    receipt["payload"] = {"operationResult": {"createdIds": ["pl-other"]}}
    assert built_room_check_ids(service, None, reference, ["receipt"], {asset}, start) == []


def test_playbook_and_room_check_exception_live_in_edit_instructions_only():
    from ai_inspector.codex_runtime import pilot
    edit, read = pilot.EDIT_INSTRUCTIONS + pilot.ENGINEERING_INSTRUCTIONS, pilot.INSTRUCTIONS
    assert "get_model_recipe" in edit and "build_model_draft" in edit and "turn_budget_low" in edit
    assert "Never part1 or box2" in edit and "NEXT turn with show_facility_views" in edit
    assert "with one exception" in edit and "earlier layout never verifies" in edit
    assert "build_model_draft" not in read and "with one exception" not in read
    assert "Never call it unasked." in read
