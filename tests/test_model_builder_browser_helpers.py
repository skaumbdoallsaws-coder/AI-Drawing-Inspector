"""Offline MB7 verifier helpers. No browser, listener or server is started."""
from pathlib import Path

from PIL import Image

from tools import verify_model_builder_browser as harness
from tools import verify_model_import_chat_browser as base


def test_three_cookbook_inputs_are_portable_and_have_prints():
    for identifier in harness.RECIPE_IDS:
        recipe = harness.recipe(identifier)
        assert recipe["name"] and recipe["entries"]
        assert any(entry.get("shape") == "panel" for entry in recipe["entries"])
    try:
        harness.recipe("../another")
    except AssertionError:
        pass
    else:
        raise AssertionError("Verifier accepted an unlisted recipe")


def test_placement_and_non_print_finish_target():
    asset = {"assetId": "asset-built-example", "assetDefinitionRevision": "a" * 64}
    value = harness.placement(asset, "pl-mb7-1", 4, 8)
    assert value["transform"]["position"] == {"x": 4, "y": 0, "z": 8}
    assert value["transform"]["scale"] == 1
    assert harness.non_print_part([
        {"key": "p:label#0", "name": "flammable label"},
        {"key": "p:body#0", "name": "cabinet body"},
    ]) == "p:body#0"


def test_reference_fixtures_and_scoped_route_allowlist(tmp_path: Path):
    files = harness.reference_fixtures(tmp_path)
    with Image.open(files["photo"]) as image:
        assert image.size == (900, 600) and image.format == "PNG"
    assert files["gif"].read_bytes().startswith(b"GIF89a")
    assert files["pdf"].read_bytes().startswith(b"%PDF-")
    route = "/api/facility-layouts/site-local/fl-main/reference-files"
    assert base.allowed_server_request("POST", route)
    assert not base.allowed_server_request("POST", route + "/rf-" + "a" * 24)
    assert base.allowed_server_request("GET", route + "/rf-" + "a" * 24)
    assert not base.allowed_server_request("POST", "/api/agent/chat")


def test_build_and_place_helper_uses_host_operations_without_a_browser(tmp_path: Path):
    project = tmp_path / "project"
    class Service:
        revision = 0
        operations = []
        def get_layout(self, *_):
            return {"revision": str(self.revision)}
        def preview_operations(self, *args):
            assert args[-1][0]["op"] == "place_asset"
        def apply_operations(self, *args):
            self.operations.extend(args[-1])
            self.revision += 1
    class Host:
        service = Service()
        _component_visual_root = project
        count = 0
        def principal(self):
            return object()
        def build_model_draft(self, principal, reference, source):
            self.count += 1
            assert source["name"] and reference["revision"] == str(self.service.revision)
            return {"draftId": "md-" + str(self.count).zfill(24), "lints": [],
                    "dimensions": {"height": 1.8},
                    "parts": [{"key": "p:body#0", "name": "cabinet body"}]}, b"preview"
        def register_imported_asset(self, principal, site, layout, draft_id):
            asset_id = "asset-built-" + str(self.count)
            folder = project / "generated/industrial_assets/authored/built" / asset_id
            folder.mkdir(parents=True)
            (folder / "model.glb").write_bytes(b"synthetic GLB fixture")
            return {"assetId": asset_id, "assetDefinitionRevision": "a" * 64}
    host = Host()
    models = harness.build_and_place(host, {"siteId": "site", "layoutId": "layout"}, tmp_path)
    assert len(models) == 3 and (tmp_path / "chat-model.glb").is_file()
    assert [row["op"] for row in host.service.operations] == [
        "place_asset", "place_asset", "set_component_materials", "place_asset"]
    assert models[1]["finishKey"] == "p:body#0"


def test_verifier_requires_all_browser_gates_without_running_them():
    assert {"reference_menu", "reference_ready", "gif_refused", "pdf_refused", "mixed_send",
            "three_models_3d", "part_finish_3d", "baseline_navigation", "browser_errors"} <= set(harness.EXPECTED_CHECKS)
    assert base.FORBIDDEN_PORTS == {8181, 8480, 8491, 8493}


def test_verifier_refusal_texts_are_the_servers_own():
    from pathlib import Path
    from tools.verify_model_builder_browser import SERVER_REFUSALS
    source = (Path(__file__).resolve().parents[1] / "ai_inspector/facility_layout/reference_files.py").read_text(
        encoding="utf-8")
    for code, text in SERVER_REFUSALS.items():
        assert '"' + code + '", "' + text + '"' in source
