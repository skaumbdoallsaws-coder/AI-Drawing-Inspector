"""MB4a build-specific install validator; all data is generated in temporary roots."""
from copy import deepcopy
from hashlib import sha256
import json
import threading
import time

import pytest

from ai_inspector.industrial_assets import authored_library as library, model_builder_bundle as bundle
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.industrial_assets.model_builder.errors import json_bytes
from tests.model_builder_draft_support import project, write_build
from tests.model_builder_test_support import recipe
from tests.model_builder_composition_support import CatalogFixture, cube_payload, credit


def staged(tmp_path, *, includes=False):
    root = project(tmp_path)
    catalog = None
    raw = recipe()
    if includes:
        fixture = CatalogFixture(root)
        asset_id = fixture.add("source", cube_payload(), attribution=credit())
        leaf, _ = fixture.include(asset_id)
        raw = recipe(leaf)
        catalog = fixture.catalog
    destination = tmp_path / "draft"
    value = write_build(raw, destination, threading.Event(), dependency_root=tmp_path,
                        categories=[raw["category"]], appearance_ids=[], include_catalog=catalog,
                        scope="a"*24, created=time.time())
    return root, value, bundle.catalog_entry(value), bundle.bundle_files(destination, destination, value)


@pytest.mark.parametrize("tamper", ["unknown-kind", "missing-kind", "asset-id", "folder", "frame", "provenance",
                                   "recipe", "hash", "missing-thumbnail", "extra-file", "unexpected-credit", "identity"])
def test_malformed_build_bundle_refused_before_any_install(tmp_path, tamper):
    root, _, entry, files = staged(tmp_path)
    before = (root / library.CATALOG).read_bytes()
    manifest = json.loads(files["bundle.json"])
    if tamper == "unknown-kind":
        manifest["kind"] = "other"
    elif tamper == "missing-kind":
        manifest.pop("kind")
    elif tamper == "asset-id":
        entry["assetId"] = "asset-built-fake-"+"0"*24
    elif tamper == "folder":
        entry["artifact"] = "generated/industrial_assets/authored/imports/fake/model.glb"
    elif tamper == "frame":
        entry["sourceToCanonical"][12] = 1
    elif tamper == "provenance":
        entry["buildProvenance"]["triangles"] = 13
    elif tamper == "recipe":
        portable = json.loads(files["recipe.json"])
        portable["references"] = ["rf-"+"a"*24]
        files["recipe.json"] = json_bytes(portable)
        manifest["files"]["recipe.json"] = {"bytes": len(files["recipe.json"]), "sha256": sha256(files["recipe.json"]).hexdigest()}
    elif tamper == "hash":
        manifest["files"]["model.glb"]["sha256"] = "0"*64
    elif tamper == "missing-thumbnail":
        files.pop("thumbnail.webp")
    elif tamper == "extra-file":
        files["source.glb"] = files["model.glb"]
    elif tamper == "unexpected-credit":
        files["CREDITS.txt"] = b"Unrequested credit"
    elif tamper == "identity":
        manifest["identity"]["recipe"] = "0"*64
    files["bundle.json"] = json_bytes(manifest)
    with pytest.raises(FacilityLayoutError) as caught:
        library.install_bundle(root, entry, files)
    assert caught.value.code == "asset_bundle_invalid"
    assert (root / library.CATALOG).read_bytes() == before
    assert not (root / bundle.FOLDER).exists()


@pytest.mark.parametrize("tamper", ["frame", "partMap", "anchorable", "revision", "credit", "missing-credit"])
def test_persisted_composition_metadata_is_verified_against_frozen_glb(tmp_path, tamper):
    root, _, entry, files = staged(tmp_path, includes=True)
    manifest = json.loads(files["bundle.json"])
    if tamper == "frame":
        manifest["includes"][0]["frame"]["translation"][0] += 1
    elif tamper == "partMap":
        manifest["includes"][0]["partMap"] = {"p:fake#0": "p:missing#0"}
    elif tamper == "anchorable":
        manifest["includes"][0]["anchorable"] = False
        manifest["includes"][0]["frame"] = None
    elif tamper == "revision":
        manifest["includes"][0]["revision"] = "0"*64
    elif tamper == "credit":
        entry["attribution"]["author"] = "Changed credit"
        files["CREDITS.txt"] = bundle.module("credit").credits_text(entry["attribution"]).encode()
        manifest["files"]["CREDITS.txt"] = {"bytes": len(files["CREDITS.txt"]), "sha256": sha256(files["CREDITS.txt"]).hexdigest()}
    elif tamper == "missing-credit":
        files.pop("CREDITS.txt")
    files["bundle.json"] = json_bytes(manifest)
    with pytest.raises(FacilityLayoutError) as caught:
        library.install_bundle(root, entry, files)
    assert caught.value.code == "asset_bundle_invalid"


def test_legacy_and_explicit_import_kind_dispatch_keep_existing_validator(tmp_path):
    from tests.test_model_import_catalog import bundle as imported_bundle
    root = project(tmp_path)
    entry, files = imported_bundle()
    legacy = library.install_bundle(root, entry, files)
    original = (root / library.BUNDLE_FOLDER / legacy["assetId"] / "bundle.json").read_bytes()
    assert library.install_bundle(root, entry, files)["added"] is False
    assert (root / library.BUNDLE_FOLDER / legacy["assetId"] / "bundle.json").read_bytes() == original
    other = tmp_path / "other"
    other.mkdir()
    other_root = project(other)
    manifest = json.loads(files["bundle.json"])
    manifest["kind"] = "import"
    files["bundle.json"] = json_bytes(manifest)
    assert library.install_bundle(other_root, entry, files)["assetId"] == legacy["assetId"]
