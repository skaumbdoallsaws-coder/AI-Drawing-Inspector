"""Snapshot copy policy exercised against disposable real Git repositories."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "prepare-snapshot.py"
spec = importlib.util.spec_from_file_location("prepare_snapshot", SCRIPT)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


@unittest.skipUnless(shutil.which("git"), "Git required for snapshot integration tests")
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desktop snapshot test ")
        self.base = Path(self.temp.name)
        self.source = self.base / "source project"
        self.source.mkdir()
        self.destination = self.base / "new snapshot with spaces"
        self.write("server.py", "original server\n")
        self.write("static/index.html", "<html>Original</html>")
        self.write("ai_inspector/__init__.py", "")
        self.write("generated/fixture.json", '{"fixture":true}')
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Snapshot tests", "-c", "user.email=snapshot@example.invalid", "commit", "-qm", "fixture")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, content):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def git(self, *arguments):
        return subprocess.run(["git", "-c", f"safe.directory={self.source}", "-C", str(self.source), *arguments],
                              check=True, capture_output=True).stdout.decode().strip()

    def test_current_dirty_and_untracked_source_are_copied_and_hashed(self):
        self.write("server.py", "changed current server\n")
        self.write("desktop/package.json", '{"name":"desktop"}')
        self.write("desktop/src/main.js", "// untracked current implementation\n")
        self.write("docs/current-plan.md", "current plan")
        self.write("tests/current_test.py", "assert True")
        checkpoint = snapshot.prepare_snapshot(self.source, self.destination)
        self.assertEqual((self.destination / "server.py").read_text(), "changed current server\n")
        self.assertTrue((self.destination / "desktop/src/main.js").is_file())
        self.assertEqual(checkpoint["head"], self.git("rev-parse", "HEAD"))
        manifest = (self.destination / "desktop-source-manifest.json").read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), checkpoint["sourceManifestSha256"])
        for item in json.loads(manifest):
            self.assertEqual(hashlib.sha256((self.destination / item["path"]).read_bytes()).hexdigest(), item["sha256"])
        self.assertFalse((self.source / "desktop-checkpoint.json").exists())

    def test_secret_runtime_dependency_and_live_library_exclusions_even_if_tracked(self):
        excluded = [".env", ".env.local", "secrets/passwords.json", "static/credentials.json", "desktop/.npmrc",
                    ".runtime/layout.json", "runtime_metrics/metrics.json", "desktop/node_modules/pkg/index.js",
                    "400S_Sorted_Library/profile.json", "demo_library/profile.json",
                    "generated/industrial_assets/local_library/catalog.json", "logs.log"]
        for name in excluded:
            self.write(name, "do not copy")
        self.git("add", "-f", *excluded)
        self.write("generated/untracked-output.json", "do not copy")
        self.write("facility_layout_unsaved_probe.json", "do not copy")
        snapshot.prepare_snapshot(self.source, self.destination)
        for name in [*excluded, "generated/untracked-output.json", "facility_layout_unsaved_probe.json"]:
            self.assertFalse((self.destination / name).exists(), name)
        self.assertTrue((self.destination / "generated/fixture.json").exists())
        self.assertFalse((self.destination / ".git").exists())

    def test_deleted_tracked_file_remains_deleted(self):
        (self.source / "generated/fixture.json").unlink()
        checkpoint = snapshot.prepare_snapshot(self.source, self.destination)
        self.assertFalse((self.destination / "generated/fixture.json").exists())
        self.assertEqual(checkpoint["skipped"]["missingTracked"], 1)

    def test_desktop_runtime_python_source_is_not_mistaken_for_runtime_data(self):
        included = ['desktop/runtime/create_profile.py', 'desktop/runtime/managed_backend.py']
        excluded = ['desktop/runtime/profile.json', 'desktop/runtime/.env', 'desktop/runtime/data.db',
                    'desktop/runtime/__pycache__/module.py', 'runtime/private.py']
        for name in included + excluded:
            self.write(name, 'fixture')
        snapshot.prepare_snapshot(self.source, self.destination)
        for name in included:
            self.assertTrue((self.destination / name).is_file(), name)
        for name in excluded:
            self.assertFalse((self.destination / name).exists(), name)

    def test_static_vendor_dist_and_build_assets_survive(self):
        self.write("static/vendor/package/dist/runtime.js", "// tracked browser dependency")
        self.write("static/vendor/package/build/styles.css", "/* tracked styles */")
        self.git("add", "static/vendor")
        self.write("static/vendor/new-package/dist/runtime.js", "// untracked current browser dependency")
        self.write("desktop/dist/app.js", "// generated desktop bundle excluded")
        self.write("static/vendor/package/dist/native.dll", "native binary excluded")
        snapshot.prepare_snapshot(self.source, self.destination)
        for name in ["static/vendor/package/dist/runtime.js", "static/vendor/package/build/styles.css",
                     "static/vendor/new-package/dist/runtime.js"]:
            self.assertTrue((self.destination / name).is_file(), name)
        self.assertFalse((self.destination / "desktop/dist/app.js").exists())
        self.assertFalse((self.destination / "static/vendor/package/dist/native.dll").exists())

    def test_overlap_and_nonempty_destination_are_rejected_without_overwrite(self):
        for destination in [self.source / "snapshot", self.source, self.base]:
            with self.assertRaises(ValueError):
                snapshot.prepare_snapshot(self.source, destination)
        self.destination.mkdir()
        sentinel = self.destination / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaises(ValueError):
            snapshot.prepare_snapshot(self.source, self.destination)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_existing_empty_explicit_destination_is_supported(self):
        self.destination.mkdir()
        snapshot.prepare_snapshot(self.source, self.destination)
        self.assertTrue((self.destination / "desktop-checkpoint.json").is_file())

    def test_secret_literal_blocks_completion_without_exposing_secret(self):
        self.write("desktop/src/config.js", 'const key = "' + 'sk-proj-' + 'a' * 40 + '";')
        with self.assertRaisesRegex(ValueError, "Potential embedded secret") as result:
            snapshot.prepare_snapshot(self.source, self.destination)
        self.assertNotIn("a" * 40, str(result.exception))
        self.assertFalse((self.destination / "desktop/src/config.js").exists())
        self.assertFalse((self.destination / "desktop-checkpoint.json").exists())

    def test_synthetic_token_exception_requires_exact_path_and_digest(self):
        literal = b"sk-ant-" + b"z" * 32
        digest = hashlib.sha256(literal).hexdigest()
        path = Path("tests/test_known_redaction.py")
        with patch.dict(snapshot.SYNTHETIC_REDACTION_FIXTURES, {path.as_posix(): frozenset({digest})}):
            self.assertFalse(snapshot.has_potential_secret(path, literal))
            self.assertTrue(snapshot.has_potential_secret(Path("tests/test_other.py"), literal))
            self.assertTrue(snapshot.has_potential_secret(path, literal + b"x"))

    def test_linked_candidates_are_skipped_and_linked_root_rejected(self):
        self.write("static/link.js", "placeholder")
        original = snapshot.is_link
        def simulated_link(path):
            return path == self.source / "static/link.js" or original(path)
        with patch.object(snapshot, "is_link", side_effect=simulated_link):
            snapshot.prepare_snapshot(self.source, self.destination)
        self.assertFalse((self.destination / "static/link.js").exists())
        with patch.object(snapshot, "is_link", side_effect=lambda path: path == self.source):
            with self.assertRaisesRegex(ValueError, "symlinks or junctions"):
                snapshot.checked_local_path(self.source)

    def test_git_trust_is_per_command_and_source_config_unchanged(self):
        before = (self.source / ".git/config").read_bytes()
        snapshot.prepare_snapshot(self.source, self.destination)
        self.assertEqual((self.source / ".git/config").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
