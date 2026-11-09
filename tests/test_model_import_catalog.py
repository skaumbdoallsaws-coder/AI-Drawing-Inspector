"""MI2a publishes verified import bundles and recovers their live catalog binding.

Every model and catalog lives in pytest's temporary roots. Synthetic geometry
runs through the model_import writer, never through private downloads or server.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.codex_runtime.authoring_reads import read_authoring
from ai_inspector.facility_layout import host as host_module
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost
from ai_inspector.facility_layout.placement_intents import resolve_placement_intents
from ai_inspector.facility_layout.private_catalog import private_asset_spec, validate_attribution
from ai_inspector.facility_layout.spatial import (placement_spatial_records, _record_pair_intersects, diagnose_layout)
from ai_inspector.industrial_assets import authored_library as library
from ai_inspector.industrial_assets.shape_families import build_asset
from tests.model_import_recipe_support import add_spec, solids, recipe, prepare_fixture
from tests.model_import_test_support import module, textured_box, image_bytes

FRAME = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
CREDIT = {"title": "Fixture model", "author": "Fixture artist", "authorUrl": "https://example.org/artist",
          "sourceUrl": "https://example.org/model", "license": "CC BY 4.0",
          "licenseUrl": "https://creativecommons.org/licenses/by/4.0/", "licenseClass": "cc-by",
          "statedBy": "user"}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def project(tmp_path):
    root = tmp_path / "project"
    catalog = root / library.CATALOG
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(encoded({"schemaVersion": 1, "assets": [], "summary": {"total": 0}}))
    return root


def bundle(fixture=None, **fields):
    draft, payload, _model = prepare_fixture(fixture or textured_box(), recipe(attribution=CREDIT, **fields))
    identity = module("identity").asset_identity(draft)
    entry = dict(module("identity").catalog_semantics(draft), assetId=identity["assetId"],
                 artifact=(library.BUNDLE_FOLDER / identity["assetId"] / "model.glb").as_posix(),
                 sourceToCanonical=FRAME)
    files = {"model.glb": payload, "thumbnail.webp": image_bytes(format="WEBP"),
             "CREDITS.txt": module("credit").credits_text(entry["attribution"]).encode()}
    files["bundle.json"] = encoded({"schemaVersion": 1, "assetId": entry["assetId"],
                                    "identity": identity["identity"], "files": digests(files)})
    return entry, files


def digests(files):
    return {name: {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in files.items() if name != "bundle.json"}


def rehash(files):
    files = dict(files)
    manifest = json.loads(files["bundle.json"])
    manifest["files"] = digests(files)
    files["bundle.json"] = encoded(manifest)
    return files


@pytest.fixture
def built():
    return bundle()


@pytest.fixture
def host(tmp_path):
    live = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=project(tmp_path))
    live.ensure_bootstrap()
    try:
        yield live
    finally:
        live.close()


def placement(asset, name="pl-import", x=4, y=0, z=4):
    return {"placementId": name, "assetId": asset["assetId"],
            "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "transform": {"position": {"x": x, "y": y, "z": z},
                          "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1}, "scale": 1},
            "positionMode": "locked", "snapRelationship": None, "metadata": {}}


@pytest.mark.parametrize("field,value", [
    ("sourceUrl", "not a URL"), ("sourceUrl", "http://example.org/model"), ("authorUrl", "https://"),
    ("authorUrl", "javascript:alert(1)"), ("licenseUrl", "https://example.org:bad/path"),
    ("authorUrl", "https://user:password@example.org"), ("sourceUrl", "https://bad host/path"),
    ("title", "x" * 301), ("changes", "x" * 601), ("author", "a\nb"), ("author", "a\x00b"),
    ("author", "a\x85b"), ("author", "a\u202eb"), ("licenseClass", "public-domain-ish"),
    ("statedBy", "model"), ("license", 42), ("extra", "not a D7 field"),
])
def test_invalid_attribution_is_rejected_by_binder_and_installer(tmp_path, built, field, value):
    entry, files = built
    entry["attribution"][field] = value
    with pytest.raises(ValueError, match="attribution"):
        private_asset_spec(entry)
    root = project(tmp_path)
    manifest = root / library.CATALOG
    original = manifest.read_bytes()
    with pytest.raises(FacilityLayoutError) as caught:
        library.install_bundle(root, entry, files)
    assert caught.value.code == "asset_bundle_invalid"
    assert manifest.read_bytes() == original
    assert not (root / library.BUNDLE_FOLDER).exists()
    assert not manifest.with_suffix(".json.lock").exists()


def test_attribution_bounds_and_empty_source_urls():
    value = dict(CREDIT, title="x" * 300, changes="y" * 600, sourceUrl="", authorUrl="", licenseUrl="")
    assert validate_attribution(value) == value
    for license_class in ("cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nd", "cc-by-nc-sa",
                          "cc-by-nc-nd", "other", "unknown"):
        assert validate_attribution({"licenseClass": license_class}) == {"licenseClass": license_class}
    for value in (None, [], "credit"):
        with pytest.raises(ValueError):
            validate_attribution(value)


def test_legacy_entry_keeps_its_bound_definition_and_revision(tmp_path):
    root = project(tmp_path)
    built = build_asset("bollard")
    library.install(root, built)
    before = next(a for a in host_module.build_private_local_asset_catalog(root) if a["assetId"] == built["assetId"])
    assert "attribution" not in before and "attribution" not in before["definition"]
    # The old binding recipe, before this optional field existed, gives exactly this revision.
    assert before["assetDefinitionRevision"] == host_module._revision(before["definition"])
    entry = deepcopy(built["entry"])
    entry["attribution"] = CREDIT
    catalog = root / library.CATALOG
    catalog.write_bytes(encoded({"schemaVersion": 1, "assets": [entry]}))
    after = next(a for a in host_module.build_private_local_asset_catalog(root) if a["assetId"] == built["assetId"])
    assert after["attribution"] == CREDIT == after["definition"]["attribution"]
    assert after["assetDefinitionRevision"] != before["assetDefinitionRevision"]
    without_credit = deepcopy(after["definition"])
    without_credit.pop("attribution")
    assert without_credit == before["definition"]


def test_duplicate_and_reserved_ids_still_fail_manifest_binding(tmp_path):
    root = project(tmp_path)
    entry = build_asset("bollard")["entry"]
    manifest = root / library.CATALOG
    manifest.write_bytes(encoded({"schemaVersion": 1, "assets": [entry, entry]}))
    with pytest.raises(ValueError, match="assetId"):
        host_module.build_private_local_asset_catalog(root)
    manifest.write_bytes(encoded({"schemaVersion": 1, "assets": [dict(entry, assetId="asset-forklift")]}))
    with pytest.raises(ValueError, match="assetId"):
        host_module.build_private_local_asset_catalog(root)


def test_install_bundle_adds_then_identical_reuse_changes_no_bytes(tmp_path, built):
    root = project(tmp_path)
    entry, files = built
    before = (root / library.CATALOG).read_bytes()
    first = library.install_bundle(root, entry, files)
    folder = (root / entry["artifact"]).parent
    assert first["added"] and first["modelWritten"]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == files
    assert (root / first["backup"]).read_bytes() == before
    assert json.loads((root / library.CATALOG).read_bytes())["summary"]["total"] == 1
    bound = next(a for a in host_module.build_private_local_asset_catalog(root) if a["assetId"] == entry["assetId"])
    assert bound["thumbnail"]["path"] == "/" + (Path(entry["artifact"]).parent / "thumbnail.webp").as_posix()
    assert bound["privateLocalVisual"]["available"]
    snapshot = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in [root / library.CATALOG, *folder.iterdir()]}
    second = library.install_bundle(root, entry, files)
    assert second == dict(first, added=False, modelWritten=False, backup=None)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in snapshot.items())
    assert len(list((root / library.BACKUPS).iterdir())) == 1
    # Manifest whitespace is not a new identity, and reuse never rewrites it.
    pretty = json.dumps(json.loads(files["bundle.json"]), indent=2).encode()
    (folder / "bundle.json").write_bytes(pretty)
    assert not library.install_bundle(root, entry, files)["added"]
    assert (folder / "bundle.json").read_bytes() == pretty


@pytest.mark.parametrize("change", ["thumbnail", "existing-bytes", "missing-file", "catalog-entry"])
def test_identity_conflicts_never_overwrite(tmp_path, built, change):
    root = project(tmp_path)
    entry, files = built
    library.install_bundle(root, entry, files)
    folder = (root / entry["artifact"]).parent
    if change == "thumbnail":
        files = rehash(dict(files, **{"thumbnail.webp": image_bytes(format="WEBP", color=(200, 30, 10, 255))}))
    elif change == "existing-bytes":
        (folder / "CREDITS.txt").write_bytes(b"x" * len(files["CREDITS.txt"]))
    elif change == "missing-file":
        (folder / "thumbnail.webp").unlink()
    else:
        entry["source"] = {"note": "different full entry"}
    snapshot = {p: p.read_bytes() for p in [root / library.CATALOG, *folder.iterdir()]}
    with pytest.raises(FacilityLayoutError) as caught:
        library.install_bundle(root, entry, files)
    assert caught.value.code == "asset_identity_conflict"
    assert all(p.read_bytes() == data for p, data in snapshot.items())


@pytest.mark.parametrize("corrupt", ["model", "dimensions", "hash", "credit", "path", "identity", "extra-file", "thumbnail"])
def test_invalid_bundle_is_rejected_before_publication(tmp_path, built, corrupt):
    root = project(tmp_path)
    entry, files = built
    if corrupt == "model":
        files["model.glb"] = b"not a glb"
    elif corrupt == "dimensions":
        entry["dimensions"]["width"] = 99
    elif corrupt == "hash":
        files["bundle.json"] = files["bundle.json"].replace(b'"bytes":', b'"bytes":1', 1)
    elif corrupt == "credit":
        files = rehash(dict(files, **{"CREDITS.txt": b"Credit removed\n"}))
    elif corrupt == "path":
        entry["artifact"] = "generated/industrial_assets/authored/imports/../outside.glb"
    elif corrupt == "identity":
        manifest = json.loads(files["bundle.json"])
        manifest["identity"]["source"] = "f" * 64
        files["bundle.json"] = encoded(manifest)
    elif corrupt == "extra-file":
        files["extra"] = b"unexpected"
    else:
        files = rehash(dict(files, **{"thumbnail.webp": b"not webp"}))
    original = (root / library.CATALOG).read_bytes()
    with pytest.raises(FacilityLayoutError) as caught:
        library.install_bundle(root, entry, files)
    assert caught.value.code == "asset_bundle_invalid"
    assert (root / library.CATALOG).read_bytes() == original
    assert not (root / library.BUNDLE_FOLDER).exists()


def test_orphan_folder_is_reused_only_if_complete_and_identical(tmp_path, built):
    root = project(tmp_path)
    entry, files = built
    original = (root / library.CATALOG).read_bytes()
    library.install_bundle(root, entry, files)
    folder = (root / entry["artifact"]).parent
    (root / library.CATALOG).write_bytes(original)
    made = library.install_bundle(root, entry, files)
    assert made["added"] and not made["modelWritten"]
    (root / library.CATALOG).write_bytes(original)
    (folder / "model.glb").write_bytes(b"broken")
    with pytest.raises(FacilityLayoutError) as caught:
        library.install_bundle(root, entry, files)
    assert caught.value.code == "asset_identity_conflict"
    assert (root / library.CATALOG).read_bytes() == original


def test_interrupted_catalog_publication_leaves_reusable_folder(tmp_path, built, monkeypatch):
    root = project(tmp_path)
    entry, files = built
    original = (root / library.CATALOG).read_bytes()
    real_replace = library.replace_file
    def fail_catalog(path, *args, **kwargs):
        if path == root / library.CATALOG:
            assert (root / entry["artifact"]).read_bytes() == files["model.glb"]
            raise OSError("injected publication failure")
        return real_replace(path, *args, **kwargs)
    monkeypatch.setattr(library, "replace_file", fail_catalog)
    with pytest.raises(OSError, match="injected"):
        library.install_bundle(root, entry, files)
    assert (root / library.CATALOG).read_bytes() == original
    assert not list((root / library.BUNDLE_FOLDER).glob(".*"))
    monkeypatch.setattr(library, "replace_file", real_replace)
    result = library.install_bundle(root, entry, files)
    assert result["added"] and not result["modelWritten"]


def test_concurrent_install_of_same_bundle_publishes_once(tmp_path, built):
    root = project(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: library.install_bundle(root, *built), range(4)))
    assert sum(result["added"] for result in results) == 1
    assert len(json.loads((root / library.CATALOG).read_bytes())["assets"]) == 1


def test_live_bind_inspection_restart_and_placed_revision_are_stable(host, built, tmp_path):
    entry, files = built
    version = host.list_assets()["catalogVersion"]
    original_catalog, original_versions = host._catalog, host._asset_versions
    library.install_bundle(host._component_visual_root, entry, files)
    bound = host.bind_installed_asset(entry["assetId"])
    assert bound["attribution"] == entry["attribution"]
    assert host._catalog is not original_catalog and host._asset_versions is not original_versions
    assert entry["assetId"] not in original_catalog
    assert host.list_assets()["catalogVersion"] != version
    principal = host.principal()
    saved = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    host.service.apply_operations(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID, saved["revision"],
        [{"op": "place_asset", "placementId": "pl-import", "placement": placement(bound)}])
    saved_after = host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    ref = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": saved_after["revision"]}
    inspected = read_authoring(host.agent_runtime, principal, ref, "inspect_facility_asset", {"assetId": entry["assetId"]})
    assert inspected["definition"]["attribution"] == entry["attribution"]
    # Another asset must not rewrite the placed definition or its model bytes.
    other = bundle(name="Another import", size={"scale": .5})
    library.install_bundle(host._component_visual_root, *other)
    host.bind_installed_asset(other[0]["assetId"])
    assert host._asset_versions[(bound["assetId"], bound["assetDefinitionRevision"])]["definition"] == bound["definition"]
    assert (host._component_visual_root / entry["artifact"]).read_bytes() == files["model.glb"]
    assert host.service.get_layout(principal, LOCAL_SITE_ID, LOCAL_LAYOUT_ID) == saved_after
    restarted = LocalFacilityLayoutHost(tmp_path / "restarted", private_assets=True,
                                       private_asset_root=host._component_visual_root)
    try:
        assert restarted._catalog[entry["assetId"]] == host._catalog[entry["assetId"]]
    finally:
        restarted.close()


def test_list_assets_reconciles_publication_followed_by_failed_live_swap(host, built, monkeypatch):
    app = FastAPI()
    app.include_router(host.create_router())
    with TestClient(app) as client:
        before = client.get("/api/industrial-assets").json()
        entry, files = built
        library.install_bundle(host._component_visual_root, entry, files)
        original_swap = host._swap_catalog_entries
        with monkeypatch.context() as patch:
            patch.setattr(host, "_swap_catalog_entries", lambda *a, **k: (_ for _ in ()).throw(ValueError("injected swap failure")))
            with pytest.raises(FacilityLayoutError, match="injected"):
                host.bind_installed_asset(entry["assetId"])
            response = client.get("/api/industrial-assets")
            assert response.status_code == 503
            assert entry["assetId"] not in host._catalog
        response = client.get("/api/industrial-assets")
        assert response.status_code == 200
        body = response.json()
        assert body["catalogVersion"] != before["catalogVersion"]
        assert entry["assetId"] in {a["assetId"] for a in body["assets"]}
        assert host._swap_catalog_entries == original_swap
        # The same disk marker is cheap: no rebind on an unchanged GET.
        monkeypatch.setattr(host_module, "build_private_local_asset_catalog", lambda *a: pytest.fail("unneeded rebind"))
        assert client.get("/api/industrial-assets").json()["catalogVersion"] == body["catalogVersion"]


def test_reconciliation_covers_other_published_assets_and_retains_old_revisions(host, built):
    first, second = built, bundle(name="Other publisher", size={"scale": .5})
    library.install_bundle(host._component_visual_root, *first)
    library.install_bundle(host._component_visual_root, *second)
    bound = host.bind_installed_asset(second[0]["assetId"])
    assert first[0]["assetId"] not in host._catalog
    host.list_assets()
    assert first[0]["assetId"] in host._catalog
    # A disk catalog no longer advertising one asset must still resolve its placed revision.
    catalog = host._component_visual_root / library.CATALOG
    current = json.loads(catalog.read_bytes())
    current["assets"] = [first[0]]
    catalog.write_bytes(encoded(current))
    host.list_assets()
    assert second[0]["assetId"] not in host._catalog
    resolved = host._resolve_asset_definition(host.principal(), LOCAL_SITE_ID, bound["assetId"], bound["assetDefinitionRevision"])
    assert resolved["definition"] == bound["definition"]


@pytest.mark.parametrize("kind", ["tabletop", "canopy", "elevated"])
def test_whole_model_hull_drives_collision_and_surface_fit(host, kind):
    low = (add_spec("frustum", "pot", radiusBottom=.1, radiusTop=.15, height=.3) if kind == "canopy"
           else add_spec(name="pedestal", size=[.2, 1, .2]))
    wide = add_spec(name=kind, size=[2, .2 if kind != "canopy" else .8, 1.2],
                    position=[.3 if kind == "elevated" else 0, 1, 0])
    entry, files = bundle(solids([low, wide]), name=kind)
    library.install_bundle(host._component_visual_root, entry, files)
    asset = host.bind_installed_asset(entry["assetId"])
    polygons = asset["definition"]["geometry"]["footprintPolygons"]
    assert min(p["x"] for p in polygons[0]) == pytest.approx(-1)
    assert max(p["x"] for p in polygons[0]) == pytest.approx(1)
    item = placement(asset, x=0, z=0)
    blocker = host_module._asset(asset_id="asset-blocker", display_name="Blocker", category="Test",
                                width=.12, depth=.12, height=2, description="Synthetic collision obstacle")
    obstacle = placement(blocker, name="pl-obstacle", x=.9, z=0)
    assert _record_pair_intersects(placement_spatial_records(item, asset)[0], placement_spatial_records(obstacle, blocker)[0])
    findings = diagnose_layout({"placements": [item, obstacle]}, [asset, blocker])["findings"]
    assert any(f["code"] == "placement_collision" for f in findings)
    # Only the base would fit this surface; the high/wide part must make attachTo fail.
    support = host_module._asset(asset_id="asset-support", display_name="Support", category="Test",
                                 width=4, depth=4, height=2, description="Synthetic support surface")
    support["definition"]["supportSurfaces"] = [{"surfaceId": "top", "label": "Top",
        "localFrame": {"origin": {"x": 0, "y": 2, "z": 0}, "xAxis": {"x": 1, "y": 0, "z": 0},
                       "zAxis": {"x": 0, "y": 0, "z": 1}, "normal": {"x": 0, "y": 1, "z": 0}},
        "bounds": {"minimumX": -.3, "maximumX": .3, "minimumZ": -.3, "maximumZ": .3},
        "allowedSides": ["above"], "evidenceStatus": "authored"}]
    holder = placement(support, name="pl-support", x=0, z=0)
    operation = {"op": "place_asset", "placement": dict(item, transform={"scale": 1}),
                 "attachTo": {"supportPlacementId": "pl-support", "surfaceId": "top"}}
    with pytest.raises(FacilityLayoutError) as caught:
        resolve_placement_intents([operation], catalog=[asset, support], layout={"placements": [holder]})
    assert caught.value.code == "attachment_does_not_fit"
    for axis in ("X", "Z"):
        support["definition"]["supportSurfaces"][0]["bounds"].update({"minimum" + axis: -2, "maximum" + axis: 2})
    resolved = resolve_placement_intents([operation], catalog=[asset, support], layout={"placements": [holder]})
    assert resolved[0]["placement"]["snapRelationship"]["surfaceId"] == "top"
