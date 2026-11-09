"""Offline checks for the browser verifier's isolation and wire-format helpers.

These tests never import server, start a listener, or launch a browser. They are
also callable directly with stdlib Python where pytest is not installed.
"""
import ast
import json
import os
from pathlib import Path
import tempfile
from types import ModuleType
from unittest.mock import patch

from tools import verify_model_import_chat_browser as harness


def test_provider_and_chat_routes_cannot_reach_the_server():
    for method in ("GET", "POST", "PUT", "DELETE"):
        for path in (*harness.CHAT_PATHS, "/api/agent/suggestions", "/api/agent/summarize",
                     "/api/facility-site-geocode/site-local", "/api/bridge/status"):
            assert not harness.allowed_server_request(method, path), (method, path)
    assert not harness.allowed_server_request("POST", "/api/facility-layouts/site-local/fl-main/preview")


def test_real_import_and_required_read_paths_are_allowed():
    base = "/api/facility-layouts/site-local/fl-main/model-imports"
    for path in (base, base + "/mi-" + "a" * 24, base + "/mi-" + "a" * 24 + "/retry"):
        assert harness.allowed_server_request("POST", path)
    assert not harness.allowed_server_request("POST", base + "/other-command")
    for path in ("/", "/static/index.html", "/api/facility-layout-bootstrap", "/api/industrial-assets",
                 "/api/agent/chat/streaming-status", "/api/agent/conversations"):
        assert harness.allowed_server_request("GET", path)


def test_sse_success_has_valid_sequence_terminal_and_final_payload():
    content_type, body = harness.chat_reply("/api/agent/chat/v2/stream")
    assert content_type == "text/event-stream" and body.endswith("\n\n")
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert [event["event"] for event in events] == ["response_started", "text_delta", "response_completed"]
    assert [event["seq"] for event in events] == [1, 2, 3]
    assert {event["v"] for event in events} == {1}
    assert len({event["response_id"] for event in events}) == 1
    content_type, plain = harness.chat_reply("/api/agent/chat")
    assert content_type == "application/json"
    assert events[-1]["final"] == json.loads(plain)
    assert events[-1]["final"]["registeredAssets"] == []
    assert events[-1]["final"]["response"] == harness.SUCCESS_TEXT


def test_transition_check_rejects_missing_or_reversed_intermediate_state():
    rows = lambda *values: [{"state": value} for value in values]
    expected = ["uploading", "checking", "ready"]
    assert harness.ordered_states(rows("waiting", "uploading", "uploading", "checking", "ready"), expected)
    assert not harness.ordered_states(rows("uploading", "ready"), expected)
    assert not harness.ordered_states(rows("checking", "uploading", "ready"), expected)


def test_guard_blocks_live_writes_protected_reads_and_external_connections():
    # Call the callback directly: never install a permanent audit hook in pytest.
    root = Path(__file__).resolve().parent
    problems = []
    guard = harness.RuntimeGuard(root / "isolated", root / "evidence", problems)
    guard.file(root / "isolated" / "model.glb", writing=True)
    guard.file(harness.ROOT / "server.py")
    attempts = [
        lambda: guard.file(root / "live" / "catalog.json", writing=True),
        lambda: guard.file(root / ".env"),
        lambda: guard.file(root / "ui-data" / "example.json"),
        lambda: guard.file(root / ".runtime" / "example.json"),
        lambda: guard.file(root / "auth.json"),
        lambda: guard.audit("socket.connect", (None, ("example.invalid", 443))),
        lambda: guard.audit("socket.getaddrinfo", ("example.invalid", 443)),
    ]
    for port in harness.FORBIDDEN_PORTS:
        attempts.append(lambda port=port: guard.audit("socket.connect", (None, ("127.0.0.1", port))))
    for attempt in attempts:
        try:
            attempt()
        except PermissionError:
            pass
        else:
            raise AssertionError("Isolation guard unexpectedly accepted the operation")
    assert len(problems) == len(attempts)


def test_environment_drops_inherited_secrets_and_matches_desktop_flags():
    # Parse only the immutable flag tuples, avoiding optional backend imports.
    source = harness.ROOT / "ai_inspector/facility_layout/feature_flags.py"
    names = {"FACILITY_LAYOUT_FEATURE_FLAGS", "FACILITY_DESIGN_LOOP_FEATURE_FLAGS"}
    flags = ModuleType("ai_inspector.facility_layout.feature_flags")
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in names:
            setattr(flags, node.target.id, ast.literal_eval(node.value))
    dotenv = ModuleType("dotenv")
    previous_temp = tempfile.tempdir
    # tmpdir under the worktree, no live stores or package dependencies.
    try:
        with tempfile.TemporaryDirectory(dir=harness.ROOT, prefix="browser-helper-test-") as directory:
            with patch.dict(os.environ, {"UNRELATED_SECRET": "discard-me", "INSPECTORPRO_LIBRARY_DIR": "old"}), patch.dict(
                    "sys.modules", {"ai_inspector.facility_layout.feature_flags": flags, "dotenv": dotenv}):
                data = Path(directory)
                harness.configure_environment(data, "0")
                assert "UNRELATED_SECRET" not in os.environ
                for name in flags.FACILITY_LAYOUT_FEATURE_FLAGS:
                    assert os.environ[name] == "1"
                for name in flags.FACILITY_DESIGN_LOOP_FEATURE_FLAGS:
                    assert os.environ[name] == ("0" if name.endswith(("_LAB", "_SAGE")) else "1")
                for name in ("INSPECTORPRO_LIBRARY_DIR", "INSPECTORPRO_FACILITY_LAYOUT_ROOT", "INSPECTORPRO_METRICS_DB",
                             "INSPECTORPRO_MEMORY_DB_PATH", "INSPECTORPRO_CHAT_FEEDBACK_DB_PATH", "TEMP", "TMP"):
                    assert Path(os.environ[name]).is_relative_to(data)
                assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
                assert os.environ["INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE"] == "0"
                assert dotenv.load_dotenv() is False
    finally:
        tempfile.tempdir = previous_temp


def test_reserved_ports_are_closed_without_connecting_or_running_a_server():
    class Listener:
        def __init__(self, port):
            self.port, self.closed, self.bound = port, False, None
        def bind(self, address):
            self.bound = address
        def getsockname(self):
            return ("127.0.0.1", self.port)
        def close(self):
            self.closed = True
    listeners = [Listener(port) for port in sorted(harness.FORBIDDEN_PORTS)] + [Listener(55001)]
    with patch.object(harness.socket, "socket", side_effect=listeners):
        result = harness.reserve_listener()
    assert result is listeners[-1] and not result.closed
    assert all(item.closed for item in listeners[:-1])
    assert all(item.bound == ("127.0.0.1", 0) for item in listeners)


def test_baseline_errors_are_listed_but_new_errors_fail():
    from types import SimpleNamespace
    existing = {"kind": "console", "text": "existing diagnostic", "url": "http://127.0.0.1:55001/static/a.js"}
    evidence = SimpleNamespace(data={"baselineErrors": [existing], "browserErrors": [existing], "routeErrors": []})
    compared = harness.compare_errors(evidence, "http://127.0.0.1:55001")
    assert compared["baselineAllowlist"] and not compared["newErrors"]
    evidence.data["browserErrors"].append({"kind": "pageerror", "text": "new attachment failure"})
    try:
        harness.compare_errors(evidence, "http://127.0.0.1:55001")
    except AssertionError as error:
        assert "new attachment failure" in str(error)
    else:
        raise AssertionError("A new browser error was hidden by the baseline")
