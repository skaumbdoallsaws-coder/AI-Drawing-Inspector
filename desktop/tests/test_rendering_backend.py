"""Boundary tests for the isolated rendering launcher; no application import."""
import asyncio
import builtins
from contextlib import asynccontextmanager, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "run-rendering-backend.py"
spec = importlib.util.spec_from_file_location("rendering_backend", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class StartupCheckpointTests(unittest.TestCase):
    def test_bootstrap_is_flushed_before_bulk_imports(self):
        output = io.StringIO()
        flush = Mock(wraps=output.flush)
        output.flush = flush
        real_import = builtins.__import__
        def stop_at_bulk_import(name, *args, **kwargs):
            if name == "argparse":
                self.assertTrue(output.getvalue().startswith("INSPECTORPRO_DESKTOP_BACKEND_BOOTSTRAP_ENTERED\n"))
                self.assertGreaterEqual(flush.call_count, 3)
                raise RuntimeError("test stopped before launcher bulk imports")
            return real_import(name, *args, **kwargs)
        # Execute only the import prelude and deliberately stop before argparse.
        # No argument parsing, fixture preparation, application import or socket.
        with patch.object(sys, "argv", [str(SCRIPT), "--serve"]), patch.object(sys, "stderr", output), \
             patch.object(builtins, "__import__", side_effect=stop_at_bulk_import):
            with self.assertRaisesRegex(RuntimeError, "test stopped"):
                exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), {"__name__": "__main__"})
        records = [json.loads(line.removeprefix(launcher.STARTUP_CHECKPOINT_PREFIX))
                   for line in output.getvalue().splitlines() if line.startswith(launcher.STARTUP_CHECKPOINT_PREFIX)]
        self.assertEqual([record["phase"] for record in records], ["child-file-entered", "stdlib-imports-starting"])

    def test_checkpoint_schema_flush_and_instance_validation_do_not_expose_environment(self):
        output = io.StringIO()
        output.flush = Mock(wraps=output.flush)
        instance = "18D6CD63-07C9-4FB1-AD2A-6835C7342ED9"
        with patch.object(launcher, "_STARTUP_CHECKPOINTS_ENABLED", True), \
             patch.object(launcher, "_STARTUP_SEQUENCE", 0), patch.object(launcher, "_STARTUP_STARTED", 10), \
             patch.object(launcher.time, "monotonic", return_value=10.25), \
             patch.object(launcher.time, "time", return_value=100.125), patch.object(launcher.os, "getpid", return_value=321), \
             patch.object(launcher.sys, "stderr", output), \
             patch.dict(launcher.os.environ, {"INSPECTORPRO_DESKTOP_INSTANCE_ID": instance, "OPENAI_API_KEY": "test-secret"}, clear=True):
            launcher.startup_checkpoint("server-import-starting")
            launcher.os.environ["INSPECTORPRO_DESKTOP_INSTANCE_ID"] = "not-a-uuid-test-secret"
            launcher.startup_checkpoint("server-import-completed")
        records = [json.loads(line.removeprefix(launcher.STARTUP_CHECKPOINT_PREFIX)) for line in output.getvalue().splitlines()]
        self.assertEqual(records[0], {"schemaVersion": 1, "pid": 321, "timeUnixMs": 100125,
            "phase": "server-import-starting", "sequence": 1, "elapsedMs": 250, "instanceId": instance.lower()})
        self.assertEqual(records[1]["sequence"], 2)
        self.assertNotIn("instanceId", records[1])
        self.assertNotIn("test-secret", output.getvalue())
        self.assertEqual(output.flush.call_count, 2)

    def test_checkpoint_io_failure_cannot_interrupt_existing_cleanup(self):
        with patch.object(launcher, "_STARTUP_CHECKPOINTS_ENABLED", True), \
             patch.object(launcher.sys, "stderr", Mock(write=Mock(side_effect=OSError("controlled log failure")))):
            launcher.startup_checkpoint("facility-host-close-starting")


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "snapshot"
        self.root.mkdir()
        for folder in ("static", "generated", "ai_inspector"):
            (self.root / folder).mkdir()
        (self.root / "desktop-checkpoint.json").write_text(json.dumps({"source": str(self.base / "live")}))
        self.data = self.root / ".runtime" / "desktop-spike" / "one"

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, **kwargs):
        return launcher.prepare_fixture(self.root, kwargs.pop("data_root", self.data),
                                        kwargs.pop("profile_id", "one"), kwargs.pop("port", 8191), **kwargs)

    def test_identity_survives_restart_and_isolates_two_stores(self):
        library, first = self.prepare()
        self.assertTrue(library.is_dir())
        self.assertEqual(first, self.prepare()[1])
        _, second = self.prepare(data_root=self.data.parent / "two")
        self.assertNotEqual(first["storeId"], second["storeId"])
        self.assertFalse(first["interactive"])
        self.assertFalse(first["researchBrowsing"])

    def test_changed_origin_or_profile_fails_closed(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.prepare(port=8192)
        with self.assertRaises(ValueError):
            self.prepare(profile_id="other")

    def test_nonempty_unmarked_or_source_data_is_rejected(self):
        self.data.mkdir(parents=True)
        (self.data / "existing.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.prepare()
        with self.assertRaises(ValueError):
            self.prepare(data_root=self.base / "live" / "data")

    def test_invalid_library_never_falls_back(self):
        with self.assertRaises(ValueError):
            self.prepare(library_root=self.data / "missing")
        with self.assertRaises(ValueError):
            self.prepare(library_root=self.root / "static")

    def test_child_environment_has_no_parent_credentials_or_bridge(self):
        parent = {"ANTHROPIC_API_KEY": "secret", "OPENAI_API_KEY": "secret", "CUSTOM_PROVIDER_TOKEN": "secret",
                  "INSPECTORPRO_LIBRARY_DIR": "live", "LOCALAPPDATA": "live", "PYTHONPATH": "live", "SystemRoot": r"C:\Windows"}
        before = dict(parent)
        env = launcher.child_environment(parent, self.data, self.data / "library")
        self.assertEqual(parent, before)
        self.assertFalse(any("secret" in value for value in env.values()))
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["LOCALAPPDATA"], str(self.data / "localappdata"))
        self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")
        self.assertEqual(env["INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE"], "0")

    def test_supervisor_uses_unbuffered_child_and_preserves_default_deadline(self):
        process = Mock(pid=123)
        with patch.object(launcher, "ROOT", self.root), patch.object(launcher.signal, "signal"), \
             patch.object(launcher.subprocess, "Popen", return_value=process) as spawn, \
             patch.object(launcher, "wait_ready") as ready, \
             patch.object(launcher, "check_http_boundary", return_value={}), \
             patch.object(launcher, "stop_child") as stop, redirect_stdout(io.StringIO()):
            result = launcher.main(["--port", "8191", "--data-root", str(self.data), "--check"])
        self.assertEqual(result, 0)
        self.assertEqual(spawn.call_args.args[0][:2], [sys.executable, "-u"])
        self.assertEqual(spawn.call_args.kwargs["env"]["PYTHONUNBUFFERED"], "1")
        self.assertEqual(ready.call_args.args[2], 45)
        stop.assert_called_once_with(process)

    def test_checkpoints_preserve_original_lifespan_and_success_only_receipt(self):
        for fail_startup in (False, True):
            with self.subTest(fail_startup=fail_startup):
                data = self.data / ("failed-startup" if fail_startup else "normal")
                library = data / "library"
                library.mkdir(parents=True)
                trace = []
                instance = "18d6cd63-07c9-4fb1-ad2a-6835c7342ed9"
                @asynccontextmanager
                async def original_lifespan(app):
                    trace.append("original-startup")
                    if fail_startup:
                        raise RuntimeError("controlled original startup failure")
                    yield
                    trace.append("original-shutdown")
                app = SimpleNamespace(router=SimpleNamespace(lifespan_context=original_lifespan))
                server = SimpleNamespace(app=app, LIBRARY_DIR=library,
                    _FACILITY_LAYOUT_HOST=SimpleNamespace(close=lambda: trace.append("facility-closed")),
                    _reset_agent_memory_runtime_for_tests=lambda: trace.append("memory-closed"),
                    _SKILL_ROUTE_SHADOW_EXECUTOR=SimpleNamespace(shutdown=lambda **kw: trace.append("skill-closed")),
                    _VIEWPORT_INTENT_EXECUTOR=SimpleNamespace(shutdown=lambda **kw: trace.append("viewport-closed")))
                async def simulated_uvicorn(boundary):
                    self.assertIs(boundary.app, app)
                    async with boundary.app.router.lifespan_context(app):
                        trace.append("simulated-request-loop")
                def run(boundary, **options):
                    self.assertEqual(options, {"host": "127.0.0.1", "port": 8191, "lifespan": "on",
                        "log_level": "warning", "access_log": False, "timeout_graceful_shutdown": 10})
                    asyncio.run(simulated_uvicorn(boundary))
                env = {"PYTHON_DOTENV_DISABLED": "1", "INSPECTORPRO_LIBRARY_DIR": str(library),
                       "INSPECTORPRO_DESKTOP_PYTHON_SITES": "[]", "INSPECTORPRO_DESKTOP_INSTANCE_ID": instance}
                with patch.dict(sys.modules, {"uvicorn": SimpleNamespace(run=run), "server": server}), \
                     patch.dict(launcher.os.environ, env, clear=True), patch.object(launcher.os, "chdir"), \
                     patch.object(launcher.sys, "path", list(sys.path)), patch.object(launcher, "install_fixture_write_guard") as guard, \
                     patch.object(launcher, "startup_checkpoint", side_effect=trace.append):
                    if fail_startup:
                        with self.assertRaisesRegex(RuntimeError, "controlled original startup failure"):
                            launcher.serve(SimpleNamespace(data_root=data, port=8191), library, {})
                    else:
                        launcher.serve(SimpleNamespace(data_root=data, port=8191), library, {})
                guard.assert_called_once_with(launcher.ROOT, data)
                for before, after in (("uvicorn-import-starting", "uvicorn-import-completed"),
                                      ("server-import-starting", "server-import-completed"),
                                      ("application-lifespan-entering", "original-startup"),
                                      ("facility-host-close-starting", "facility-closed"),
                                      ("viewport-closed", "viewport-intent-executor-close-completed")):
                    self.assertLess(trace.index(before), trace.index(after))
                receipt = launcher.shutdown_receipt_path(data, instance)
                if fail_startup:
                    self.assertNotIn("application-lifespan-startup-completed", trace)
                    self.assertNotIn("shutdown-receipt-written", trace)
                    self.assertFalse(receipt.exists())
                else:
                    for before, after in (("original-startup", "application-lifespan-startup-completed"),
                                          ("application-lifespan-shutdown-starting", "original-shutdown"),
                                          ("original-shutdown", "application-lifespan-stopped"),
                                          ("viewport-closed", "shutdown-receipt-written"),
                                          ("shutdown-receipt-written", "uvicorn-run-returned")):
                        self.assertLess(trace.index(before), trace.index(after))
                    self.assertTrue(json.loads(receipt.read_text())["resourcesClosed"])

    def test_write_guard_denies_other_roots_and_native_helpers(self):
        script = f'''import importlib.util, pathlib, subprocess
s=importlib.util.spec_from_file_location("r", {str(SCRIPT)!r}); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
m.install_fixture_write_guard(pathlib.Path({str(self.root)!r}), pathlib.Path({str(self.data)!r}))
try:
 pathlib.Path({str(self.base / "forbidden.txt")!r}).write_text("forbidden")
 raise AssertionError("write was permitted")
except PermissionError: pass
try:
 subprocess.Popen(["never-execute"])
 raise AssertionError("helper was permitted")
except PermissionError: pass
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "forbidden.txt").exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows repository path representation")
    def test_windows_extended_length_paths_resolve_to_same_fixture(self):
        self.assertEqual(launcher.no_links(Path("\\\\?\\" + str(self.root))), self.root.resolve())


class BoundaryTests(unittest.TestCase):
    identity = {"schemaVersion": 1, "product": "InspectorPro", "mode": "rendering-spike",
                "backendId": "b", "storeId": "s", "profileId": "one", "interactive": False,
                "researchBrowsing": False, "origin": "http://127.0.0.1:8191"}

    def request(self, path, method="GET", *, host=b"127.0.0.1:8191", origin=None, kind="http"):
        called, messages = [], []
        async def app(scope, receive, send):
            called.append(scope)
        async def receive():
            return {"type": "http.request", "body": b""}
        async def send(value):
            messages.append(value)
        headers = [(b"host", host)]
        if origin is not None:
            headers.append((b"origin", origin))
        asyncio.run(launcher.RenderingBoundary(app, self.identity)(
            {"type": kind, "path": path, "method": method, "headers": headers}, receive, send))
        return called, messages

    def test_only_enumerated_reads_reach_real_application(self):
        for path in ["/", "/static/index.html", "/generated/fixture.glb", "/api/profiles", "/api/facility-layout-bootstrap"]:
            self.assertTrue(self.request(path)[0], path)
        for path in ["/api/bridge/status", "/api/training/blender/status", "/api/metrics", "/api/admin/memory/health",
                     "/api/agent/chat", "/api/new-future-action", "/static/../.env", "/static\\secret"]:
            called, messages = self.request(path)
            self.assertFalse(called, path)
            self.assertEqual(messages[0]["status"], 403, path)

    def test_mutations_and_sockets_never_reach_application(self):
        for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]:
            self.assertEqual(self.request("/api/profiles", method)[1][0]["status"], 403)
        self.assertEqual(self.request("/", kind="websocket")[1][0]["type"], "websocket.close")

    def test_identity_is_narrow_and_unsafe_hosts_origins_rejected(self):
        called, messages = self.request(launcher.IDENTITY_PATH)
        self.assertFalse(called)
        body = json.loads(messages[1]["body"])
        self.assertEqual(body, launcher.public_identity(self.identity))
        self.assertNotIn("origin", body)
        for host in [b"localhost:8191", b"127.0.0.1:8192", b"evil.example:8191"]:
            self.assertEqual(self.request("/", host=host)[1][0]["status"], 403)
        for origin in [b"null", b"http://127.0.0.1:9000", b"https://evil.example"]:
            self.assertEqual(self.request("/", origin=origin)[1][0]["status"], 403)

    def test_stop_never_terminates_unrelated_or_already_exited_process(self):
        process = Mock()
        process.poll.return_value = 0
        launcher.stop_child(process)
        process.send_signal.assert_not_called()
        process.terminate.assert_not_called()

    def test_readiness_rejects_same_profile_from_another_process(self):
        process = Mock()
        process.poll.return_value = None
        response = Mock()
        response.headers = {"X-InspectorPro-Rendering-Instance": "previous-launch"}
        response.read.return_value = json.dumps(launcher.public_identity(self.identity)).encode()
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        with patch.object(launcher.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "Occupied port"):
                launcher.wait_ready(process, self.identity, 1, "current-launch")

    def test_readiness_rejects_exited_child(self):
        process = Mock()
        process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "exited before readiness"):
            launcher.wait_ready(process, self.identity, 1, "instance")

    def test_shutdown_timeout_only_terminates_owned_child(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("child", 15), 0]
        launcher.stop_child(process)
        process.send_signal.assert_called_once()
        process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
