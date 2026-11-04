"""Basic shapes BS2 (docs/sage-basic-shapes-plan.md): live registration. A basic shape goes into the shared private
library (its model under generated/industrial_assets/authored/, its entry at the end of the catalog after a backup)
and into the running host: its revision is the one a fresh start computes, and a placement of it binds at once."""
from __future__ import annotations

import json

import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.host import (LOCAL_LAYOUT_ID, LOCAL_SITE_ID, LocalFacilityLayoutHost,
                                               build_private_local_asset_catalog)
from ai_inspector.facility_layout.operation_proposals import create
from ai_inspector.industrial_assets import authored_library as library
from ai_inspector.industrial_assets import shape_families as families
from tests.test_facility_operation_proposals import apply, approve

CRLF_CATALOG = (b'{\r\n  "assets": [\r\n    {\r\n      "assetId": "asset-old",\r\n      "artifact": "x.glb"\r\n'
                b'    }\r\n  ],\r\n  "schemaVersion": 1,\r\n  "summary": {\r\n    "failed": 0,\r\n    "total": 1\r\n'
                b'  }\r\n}\r\n')


def project(tmp_path, catalog=None):
    root = tmp_path / "project"
    manifest = root / library.CATALOG
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(catalog if catalog is not None else json.dumps(
        {"assets": [], "schemaVersion": 1, "summary": {"total": 0}}, separators=(",", ":")).encode("ascii"))
    return root


@pytest.fixture
def host(tmp_path):
    root = project(tmp_path)
    live = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=True, private_asset_root=root)
    live.ensure_bootstrap()
    try:
        yield live
    finally:
        live.close()


def saved(host):
    return host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)


def catalog_ids(host):
    return [item["assetId"] for item in host._agent_asset_catalog(host.principal(), LOCAL_SITE_ID)]


def test_the_entry_goes_on_the_end_of_the_catalog_in_the_file_s_own_style():
    entry = families.build_asset("bollard")["entry"]
    added = library.appended(CRLF_CATALOG, entry)
    assert added.startswith(CRLF_CATALOG[:CRLF_CATALOG.index(b"\r\n  ],")])     # the old asset byte for byte
    assert b"\n" not in added.replace(b"\r\n", b"")                             # still CRLF throughout
    assert b'\r\n    },\r\n    {\r\n      "artifact": "generated/industrial_assets/authored/' in added
    assert b'"total": 2\r\n' in added and b'"failed": 0,' in added
    parsed = json.loads(added)
    assert parsed["assets"][1] == entry and parsed["summary"] == {"failed": 0, "total": 2}
    compact = json.dumps({"assets": [{"assetId": "asset-old"}], "schemaVersion": 1, "summary": {"total": 1}},
                         separators=(",", ":")).encode()
    added = library.appended(compact, entry)
    assert added == compact.replace(b'"}],', b'"},' + json.dumps(entry, sort_keys=True, separators=(",", ":"))
                                    .encode() + b'],').replace(b'"total":1', b'"total":2')
    empty = library.appended(b'{"assets": [], "summary": {"total": 0}}', entry)
    assert json.loads(empty) == {"assets": [entry], "summary": {"total": 1}}
    with pytest.raises(ValueError, match="no assets array"):
        library.appended(b'{"assets": {}}', entry)


def test_a_shape_binds_with_the_revision_a_fresh_start_gives_it(host, tmp_path):
    assert "asset-authored" not in json.dumps(catalog_ids(host))
    result = host.register_authored_asset("pedestrian_barrier", {"lengthMeters": 12})
    built = families.build_asset("pedestrian_barrier", {"lengthMeters": 12})
    assert result["assetId"] == built["assetId"] and result["added"] is True
    assert result["dimensions"] == {"width": 12.0, "height": 1.1, "depth": 0.24}
    assert result["category"] == "Safety" and result["tags"][-2:] == ["authored", "unverified"]
    root = tmp_path / "project"
    assert (root / built["entry"]["artifact"]).read_bytes() == built["payload"]
    backups = list((root / library.BACKUPS).glob("catalog-*.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_bytes())["assets"] == []
    # What the running host now has is what a fresh start reads from the files.
    fresh = {item["assetId"]: item for item in build_private_local_asset_catalog(root)}
    assert result["assetDefinitionRevision"] == fresh[result["assetId"]]["assetDefinitionRevision"]
    restarted = LocalFacilityLayoutHost(tmp_path / "facility-2", private_assets=True, private_asset_root=root)
    try:
        assert restarted._catalog[result["assetId"]] == host._catalog[result["assetId"]]
        assert restarted.authoritative_asset_catalog() == host.authoritative_asset_catalog()
    finally:
        restarted.close()
    assert result["assetId"] in catalog_ids(host)
    assert json.loads((root / library.CATALOG).read_bytes())["summary"]["total"] == 1


def test_asking_again_changes_nothing(host, tmp_path):
    first = host.register_authored_asset("bollard")
    catalog = (tmp_path / "project" / library.CATALOG).read_bytes()
    again = host.register_authored_asset("bollard", {"heightMeters": 1.2, "color": "#F5C400"})
    assert again == {**first, "added": False}
    assert (tmp_path / "project" / library.CATALOG).read_bytes() == catalog
    assert len(list((tmp_path / "project" / library.BACKUPS).glob("*.json"))) == 1
    assert catalog_ids(host).count(first["assetId"]) == 1


def test_a_placement_of_the_new_shape_binds_at_once(host):
    asset = host.register_authored_asset("steel_column", {"heightMeters": 8})
    before = saved(host)
    placement = {"placementId": "pl-column-1", "assetId": asset["assetId"],
                 "assetDefinitionRevision": asset["assetDefinitionRevision"],
                 "transform": {"position": {"x": 4, "y": 0, "z": 4}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                               "scale": 1},
                 "positionMode": "locked", "snapRelationship": None, "metadata": {"instanceLabel": "Column A1"}}
    proposal = create(host.service, host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID, before["revision"],
                      operations=[{"op": "place_asset", "placementId": "pl-column-1", "placement": placement}])
    context = (host.service, host.principal())
    after = apply(context, proposal, approve(context, proposal))["layout"]
    placed = next(item for item in after["placements"] if item["placementId"] == "pl-column-1")
    assert placed["assetId"] == asset["assetId"]
    assert placed["assetDefinitionRevision"] == asset["assetDefinitionRevision"]


def test_bad_shapes_and_a_host_without_the_private_library_are_refused(host, tmp_path):
    with pytest.raises(FacilityLayoutError, match="lengthMeters: 0.1 is less than the minimum") as caught:
        host.register_authored_asset("i_beam", {"lengthMeters": 0.1})
    assert caught.value.code == "authored_asset_invalid"
    with pytest.raises(FacilityLayoutError, match="Unknown shape family 'crane'"):
        host.register_authored_asset("crane")
    assert not (tmp_path / "project" / families.FOLDER).exists()
    plain = LocalFacilityLayoutHost(tmp_path / "facility-plain", private_assets=False)
    try:
        with pytest.raises(FacilityLayoutError) as caught:
            plain.register_authored_asset("bollard")
        assert caught.value.code == "authored_assets_unavailable" and caught.value.status_code == 409
    finally:
        plain.close()


def test_a_catalog_changed_by_someone_else_meanwhile_is_left_alone(host, tmp_path, monkeypatch):
    manifest = tmp_path / "project" / library.CATALOG
    real_write = library._write

    def meddle(path, data):
        if path == manifest:
            raise AssertionError("the catalog was written after it changed")
        real_write(path, data)
    monkeypatch.setattr(library, "_write", meddle)
    real_read = type(manifest).read_bytes
    reads = []

    def read_bytes(path):
        data = real_read(path)
        if path == manifest:
            reads.append(path)
            if len(reads) == 2:      # the check just before writing: another tool got there first
                return data.replace(b'"total":0', b'"total":5')
        return data
    monkeypatch.setattr(type(manifest), "read_bytes", read_bytes)
    with pytest.raises(FacilityLayoutError, match="The catalog changed while the asset was being added") as caught:
        host.register_authored_asset("bin")
    assert caught.value.code == "authored_asset_not_added"
    assert "asset-authored-bin" not in json.dumps(catalog_ids(host))
