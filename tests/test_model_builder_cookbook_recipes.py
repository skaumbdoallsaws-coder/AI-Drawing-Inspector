"""MB6 cookbook v1 (Claude): every recipe builds clean, the index matches, E1 parity holds, and the
roll-cage-tag include values are what registering the cookbook's plain cage gives. Temporary roots only."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.model_builder_test_support import module

ROOT = Path(__file__).resolve().parents[1]
COOKBOOK = ROOT / "ai_inspector" / "industrial_assets" / "model_builder" / "cookbook"
STATS = json.loads((ROOT / "docs" / "sage-model-builder-reference" / "baseline-stats.json").read_text(encoding="utf-8"))
ITEMS = ROOT / "docs" / "sage-model-builder-eval" / "items.json"
INDEX = json.loads((COOKBOOK / "index.json").read_text(encoding="utf-8"))
IDS = [r["id"] for r in INDEX["recipes"]]
STANDALONE = [i for i in IDS if i != "roll-cage-tag"]


def raw(recipe_id):
    return json.loads((COOKBOOK / (recipe_id + ".json")).read_text(encoding="utf-8"))


def build(value, **options):
    categories = [value["category"]]
    return module("build").build_model(value, allowed_categories=categories, allowed_appearance_ids=[], **options)


def parts(built):
    model = module("imports").module("reader").read_model(built.glb, extended_materials=True)
    counts = {}
    for part in model.parts:
        counts[part.name] = counts.get(part.name, 0) + int(part.triangles if hasattr(part, "triangles") else 0)
    return model, counts


def test_index_lists_every_recipe_file_once_with_matching_name_size_and_short_teaches():
    assert INDEX["schemaVersion"] == 1
    assert len(IDS) == len(set(IDS)) == 11
    assert sorted(IDS) == sorted(p.stem for p in COOKBOOK.glob("*.json") if p.stem != "index")
    for entry in INDEX["recipes"]:
        value = raw(entry["id"])
        assert value["name"] == entry["name"]
        assert value["size"] == entry["size"]
        assert 0 < len(entry["teaches"]) <= 120


@pytest.mark.parametrize("path", sorted(COOKBOOK.glob("*.json")), ids=lambda p: p.stem)
def test_cookbook_files_are_ascii_lf_and_inside_the_recipe_byte_limit(path):
    data = path.read_bytes()
    assert data.isascii() and b"\r" not in data and len(data) <= 24 * 1024


@pytest.mark.parametrize("recipe_id", STANDALONE)
def test_standalone_recipe_normalizes_builds_with_no_lints_at_its_stated_size(recipe_id):
    value = raw(recipe_id)
    module("recipe").normalize_recipe(value, allowed_categories=[value["category"]], allowed_appearance_ids=[])
    built = build(value)
    assert built.lints == []
    for key in ("width", "depth", "height"):
        assert built.dimensions[key] == pytest.approx(value["size"][key], abs=1e-3)
    assert module("protocol").make_result(built, {"categories": [value["category"]], "appearanceIds": []})["triangles"] <= 20000


@pytest.mark.parametrize("recipe_id,stats,tolerance", [
    ("baler-vertical-42", "baler", .25), ("pack-station-printer", "pack-station", .25)])
def test_e1_parity_bounds_names_and_triangles(recipe_id, stats, tolerance):
    reference = STATS[stats]
    built = build(raw(recipe_id))
    for key in ("width", "depth", "height"):
        assert abs(built.dimensions[key] - reference["size"][key]) <= .01
    model, _ = parts(built)
    assert {p.name for p in model.parts} == set(reference["parts"])
    triangles = module("protocol").make_result(built, {"categories": [built.recipe["category"]], "appearanceIds": []})["triangles"]
    assert abs(triangles - reference["triangles"]) <= tolerance * reference["triangles"]


def test_e1_gaylord_body_parity_and_pallet_names():
    reference = STATS["gaylord"]
    built = build(raw("gaylord-on-pallet"))
    for key in ("width", "depth", "height"):
        assert abs(built.dimensions[key] - reference["size"][key]) <= .01
    model, _ = parts(built)
    names = {p.name for p in model.parts}
    body = {"gaylord carton", "gaylord inside", "gaylord edge", "flattened cartons", "gaylord label"}
    assert body <= names and names - body == {"pallet boards", "pallet blocks"}


def test_roll_cage_tag_include_matches_a_fresh_registration_of_the_plain_cage_and_builds_clean(tmp_path):
    from ai_inspector.facility_layout.host import LOCAL_SITE_ID, LOCAL_LAYOUT_ID, LocalFacilityLayoutHost
    from ai_inspector.facility_layout.model_import_store import ModelImportScope, ModelImportStore
    from ai_inspector.industrial_assets.model_builder.recipe import normalize_recipe
    from ai_inspector.industrial_assets.model_builder.build import build_model
    from ai_inspector.industrial_assets.model_builder_host import IncludeCatalog, inspect_model_include
    from tests.model_builder_draft_support import project, write_build
    from tests.model_import_store_support import inspect_worker

    cage = raw("roll-cage-plain")
    host = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=project(tmp_path))
    host.ensure_bootstrap()
    try:
        store = ModelImportStore(host.layout_repository.root, layout_reader=host.service.get_layout,
                                 runtime=lambda: SimpleNamespace(dependency_root=tmp_path), build_worker=write_build,
                                 inspect_worker=inspect_worker)
        host.service._model_import_store = store
        principal = host.principal()
        draft = store.build(ModelImportScope(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID), cage, None,
                            categories=[cage["category"]], appearance_ids=[])
        registered = host.register_imported_asset(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, draft["draftId"])
        catalog = IncludeCatalog(host._component_visual_root)
        info = inspect_model_include({"assetId": registered["assetId"]}, catalog=catalog)
        tag = raw("roll-cage-tag")
        include = tag["entries"][0]
        top = next(p["key"] for p in info["parts"] if p["name"] == "cage top rail")
        assert (include["include"], include["revision"], include["artifactSha256"]) == (
            registered["assetId"], info["revision"], info["artifactSha256"])
        assert include["recolor"] == [{"select": top, "material": "tag"}]
        normalized = normalize_recipe(tag, allowed_categories=[tag["category"]], allowed_appearance_ids=[])
        built = build_model(normalized, allowed_categories=[tag["category"]], allowed_appearance_ids=[],
                            include_sources=catalog.resolve_recipe(normalized))
        assert built.lints == []
        names = {p.name for p in module("imports").module("reader").read_model(built.glb, extended_materials=True).parts}
        assert {"carrier tag", "tag clips", "cage: cage top rail"} <= names
    finally:
        host.close()


def test_evaluation_items_are_frozen_with_18_items_and_24_initial_runs():
    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    e2 = items["e2"]
    assert items["schemaVersion"] == 1 and items["frozen"]
    assert len(e2) == 18 and sum(i["runs"] for i in e2) == 24
    assert [sum(1 for i in e2 if i["tier"] == t) for t in range(1, 6)] == [3, 5, 4, 3, 3]
    assert all(i["runs"] == 3 for i in e2 if i["tier"] == 1)
    assert {i["cookbookId"] for i in items["e1"]} <= set(IDS)
    # Tier 2 is a holdout: none of its items is in the cookbook.
    holdout = " ".join(i["prompt"] for i in e2 if i["tier"] == 2).lower()
    assert not any(word in holdout for word in ("baler", "gaylord", "pack station", "eyewash", "bumper"))


def test_a_category_refusal_names_the_categories_this_site_offers():
    value = raw("eyewash-station")
    value["category"] = "Safety"
    with pytest.raises(module("errors").ModelBuildError) as caught:
        module("recipe").normalize_recipe(value, allowed_categories=["Workstations", "Storage"], allowed_appearance_ids=[])
    assert caught.value.to_dict()["details"]["problem"].endswith("choose one of: Storage, Workstations")
