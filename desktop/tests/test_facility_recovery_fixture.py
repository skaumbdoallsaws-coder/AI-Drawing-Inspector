"""Bounded fixture preparation tests. No live application or provider execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools/prepare-facility-recovery-fixture.py"
spec = importlib.util.spec_from_file_location("facility_recovery_fixture", SCRIPT)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def glb(document=None):
    value = document or {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "type": "VEC3", "count": 3,
                       "min": [0, 0, 0], "max": [1, 1, 0]}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
        "buffers": [{"byteLength": 36}]}
    data = json.dumps(value).encode()
    data += b" " * (-len(data) % 4)
    binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    return (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(data) + 8 + len(binary))
            + struct.pack("<II", len(data), 0x4E4F534A) + data
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


class FacilityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="facility recovery fixture ")
        self.base = Path(self.temp.name)
        self.source = self.base / "live source"
        self.snapshot = self.base / "copied snapshot"
        self.data = self.snapshot / ".runtime/desktop-spike/new recovery fixture"
        for path in (self.source, *(self.snapshot / name for name in ("static", "generated", "ai_inspector"))):
            path.mkdir(parents=True)
        self.write(self.snapshot, "desktop-checkpoint.json", {"source": str(self.source)})
        self.layout_relative = f".runtime/facility-layout/layouts/local/site-local/layouts/{fixture.LAYOUT_ID}.json"
        self.layout = {"schemaVersion": 1, "layoutId": fixture.LAYOUT_ID, "displayName": "Manual layout",
            "status": "draft", "placements": [{"assetId": "asset-fixture", "assetDefinitionRevision": "a" * 64}],
            "zones": [{"id": "z1"}], "routes": [], "floorMarkings": [],
            "sourceShellRef": {"shellId": "shell-local", "shellRevision": self.authority("shells", "facility_shell", "shell-local")},
            "policySetRef": {"policySetId": "policy-local", "policySetRevision": self.authority("policies", "policy_set", "policy-local")}}
        self.write(self.source, self.layout_relative, self.layout)
        self.layout_revision = fixture.sha256(self.source / self.layout_relative)
        self.write(self.source, str(Path(self.layout_relative).parent / "registry.json"),
            {"schemaVersion": 1, "recordKind": "facility_layout_registry", "tenantId": "local", "siteId": "site-local",
             "defaultLayoutId": fixture.LAYOUT_ID, "layouts": [{"layoutId": fixture.LAYOUT_ID,
             "currentRevision": self.layout_revision, "status": "draft"}, {"layoutId": "fl-unrelated", "currentRevision": "c" * 64}]})
        self.artifact = "generated/industrial_assets/local_library/fixture with spaces/real model.glb"
        self.write(self.source, self.artifact, glb())
        self.write(self.source, str(Path(self.artifact).parent / "thumbnail.webp"), b"RIFF fixture thumbnail")
        self.write(self.source, fixture.CATALOG_PATH, {"schemaVersion": 1, "assets": [
            {"assetId": "asset-fixture", "artifact": self.artifact, "displayName": "Original asset metadata"},
            {"assetId": "asset-unrelated", "artifact": "generated/industrial_assets/missing.glb"}]})
        self.write(self.source, fixture.HOST_PATH,
                   "_PRIVATE_LOCAL_ASSET_SPECS: tuple = ({'asset_id': 'asset-built-in', 'artifact': 'generated/industrial_assets/built-in.glb'},)\n")
        self.write(self.source, ".env", "SECRET=do-not-copy")
        self.write(self.source, ".runtime/live-authority-marker.json", {"storeId": "live"})
        self.write(self.source, "library/unrelated.json", {"private": True})

    def tearDown(self):
        target = Path(self.temp.name).resolve()
        self.assertEqual(target, self.base.resolve())
        self.assertIn(Path(tempfile.gettempdir()).resolve(), target.parents)
        self.assertTrue(target.name.startswith("facility recovery fixture "))
        shutil.rmtree(fixture.native(target))
        self.temp.cleanup()

    def write(self, root, relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fixture.canonical(content) if isinstance(content, (dict, list))
                         else content.encode() if isinstance(content, str) else content)
        return path

    def authority(self, category, kind, identifier):
        document = {"schemaVersion": 1, "documentKind": kind, "status": "published"}
        revision = hashlib.sha256(fixture.canonical(document)).hexdigest()
        base = f".runtime/facility-layout/authorities/{category}/local/site-local/authority/{kind}"
        self.write(self.source, f"{base}/{identifier}/revisions/{revision}.json", document)
        self.write(self.source, f"{base}/registry.json", {"schemaVersion": 1, "documentKind": kind,
            "entries": [{"authorityId": identifier, "currentRevision": revision, "publishedRevision": revision,
                         "revisionHistory": ["b" * 64, revision], "status": "published"}, {"authorityId": "unrelated"}]})
        return revision

    def prepare(self, **kwargs):
        return fixture.prepare(self.snapshot, self.source, self.data, port=8199,
                               profile_id="facility-recovery-test", **kwargs)

    def test_exact_layout_assets_filtered_registries_and_new_identity(self):
        before = {p.relative_to(self.source).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.source.rglob("*") if p.is_file()}
        result = self.prepare()
        self.assertEqual(result["assetCount"], 1)
        self.assertEqual(result["layout"]["revision"], self.layout_revision)
        self.assertEqual((self.data / result["layout"]["relativePath"]).read_bytes(), before[self.layout_relative][0])
        saved = json.loads((self.data / fixture.MANIFEST_NAME).read_text())
        self.assertEqual(result, saved)
        self.assertEqual(result["source"]["layoutSha256Before"], result["source"]["layoutSha256After"])
        self.assertNotEqual(result["identity"]["storeId"], "live")
        self.assertNotEqual(result["identity"]["storeId"], result["identity"]["backendId"])
        self.assertFalse(result["verification"]["backendRoutesExercised"])
        self.assertEqual(result["backendRequirements"]["layoutRoute"], "/api/facility-layouts/site-local/" + fixture.LAYOUT_ID)
        self.assertIn("%20", result["assets"][0]["route"])
        catalog = json.loads((self.data / "asset-project" / fixture.CATALOG_PATH).read_text())
        self.assertEqual([x["assetId"] for x in catalog["assets"]], ["asset-fixture"])
        for record in result["files"]:
            self.assertEqual(fixture.sha256(self.data / record["relativePath"]), record["sha256"])
        self.assertEqual(list((self.data / "library").iterdir()), [])
        self.assertFalse((self.data / ".env").exists())
        self.assertFalse((self.data / ".runtime/live-authority-marker.json").exists())
        self.assertEqual(before, {p.relative_to(self.source).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                                 for p in self.source.rglob("*") if p.is_file()})
        for path in fixture.native(self.data / "facility/authorities").rglob("registry.json"):
            value = json.loads(path.read_bytes())
            self.assertEqual(len(value["entries"]), 1)
            self.assertEqual(len(value["entries"][0]["revisionHistory"]), 1)
            self.assertEqual(path.read_bytes(), fixture.canonical(value))

    def test_refuses_reused_or_nonempty_destination(self):
        self.data.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "must not already exist"):
            self.prepare()
        self.assertEqual(list(self.data.iterdir()), [])

    def test_rejects_source_overlap_or_mismatched_checkpoint(self):
        with self.assertRaises(ValueError):
            fixture.prepare(self.snapshot, self.source, self.source / "data", port=8199, profile_id="test")
        self.write(self.snapshot, "desktop-checkpoint.json", {"source": str(self.base / "different source")})
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.prepare()
        self.assertFalse(self.data.exists())

    def test_invalid_registry_revision_fails_before_writing(self):
        path = self.source / Path(self.layout_relative).parent / "registry.json"
        value = json.loads(path.read_text());value["layouts"][0]["currentRevision"] = "d" * 64
        path.write_bytes(fixture.canonical(value))
        with self.assertRaisesRegex(ValueError, "revision"):
            self.prepare()
        self.assertFalse(self.data.exists())

    def test_noncanonical_source_layout_fails_closed(self):
        path = self.source / self.layout_relative
        path.write_text(json.dumps(self.layout, indent=2))
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.prepare()
        self.assertFalse(self.data.exists())

    def test_missing_referenced_asset_fails_before_writing(self):
        (self.source / self.artifact).unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.prepare()
        self.assertFalse(self.data.exists())

    def test_missing_authority_revision_fails_before_writing(self):
        revision = self.layout["sourceShellRef"]["shellRevision"]
        path = next(self.source.rglob(revision + ".json"));path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.prepare()
        self.assertFalse(self.data.exists())

    def test_urls_traversal_and_ambiguous_windows_paths_are_rejected(self):
        for value in ("../secret", "/generated/a.glb", "https://example.com/a.glb", "//server/share/a",
                      "C:/secret", "generated/%2e%2e/secret", "generated/%252e%252e/secret", "a\\b", "a:stream",
                      "generated/a.glb?token=x", "generated/a.glb#fragment", "a//b", "./a", "a./file"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixture.safe_path(self.source, value, must_exist=False)

    def test_symlink_reference_is_rejected(self):
        path = self.source / "link.glb"
        try:
            path.symlink_to(self.source / self.artifact)
        except OSError:
            self.skipTest("Symlink creation unavailable for current user")
        with self.assertRaisesRegex(ValueError, "links"):
            fixture.safe_path(self.source, "link.glb")

    def test_literal_specs_do_not_execute_source_code(self):
        self.write(self.source, fixture.HOST_PATH,
            "raise RuntimeError('must not execute')\n_PRIVATE_LOCAL_ASSET_SPECS: tuple = ({'asset_id':'asset-b','artifact':'generated/b.glb'},)\n")
        self.assertEqual(fixture.builtin_specs(self.source)[0]["asset_id"], "asset-b")

    def test_real_glb_structure_reports_reachable_geometry(self):
        result = fixture.inspect_glb(self.source / self.artifact)
        self.assertEqual(result["reachableMeshCount"], 1)
        self.assertEqual(result["positionCount"], 3)
        self.assertEqual(result["externalDependencies"], [])

    def test_glb_invalid_header_truncation_and_external_dependencies_rejected(self):
        base = glb()
        for value in (b"not a GLB", b"BAD!" + base[4:], base[:-4]):
            self.write(self.source, self.artifact, value)
            with self.assertRaises(ValueError):
                fixture.inspect_glb(self.source / self.artifact)
        document = json.loads(base[20:20 + struct.unpack("<I", base[12:16])[0]])
        document["buffers"][0]["uri"] = "https://external.invalid/secret"
        self.write(self.source, self.artifact, glb(document))
        with self.assertRaisesRegex(ValueError, "dependencies"):
            fixture.inspect_glb(self.source / self.artifact)

    def test_glb_empty_scene_and_accessor_out_of_bounds_rejected(self):
        base = glb();document = json.loads(base[20:20 + struct.unpack("<I", base[12:16])[0]])
        document["scenes"][0]["nodes"] = []
        self.write(self.source, self.artifact, glb(document))
        with self.assertRaisesRegex(ValueError, "roots"):
            fixture.inspect_glb(self.source / self.artifact)
        document["scenes"][0]["nodes"] = [0];document["accessors"][0]["count"] = 400
        self.write(self.source, self.artifact, glb(document))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            fixture.inspect_glb(self.source / self.artifact)

    def test_source_asset_change_while_copying_fails(self):
        original = fixture.sha256
        calls = {"asset": 0}
        def changed(path):
            result = original(path)
            if Path(path) == self.source / self.artifact:
                calls["asset"] += 1
                if calls["asset"] > 1:
                    return "0" * 64
            return result
        with patch.object(fixture, "sha256", side_effect=changed), self.assertRaisesRegex(ValueError, "changed"):
            self.prepare()
        self.assertFalse((self.data / fixture.MANIFEST_NAME).exists())


if __name__ == "__main__":
    unittest.main()
