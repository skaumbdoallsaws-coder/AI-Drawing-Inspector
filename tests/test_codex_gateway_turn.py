"""Offline shared lifecycle tests; scripted transports are not live Sage proof."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import inspect
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime import gateway_turn
from ai_inspector.codex_runtime.app_server import AppServer
from ai_inspector.codex_runtime.packaging_tools import tool_specs
from ai_inspector.codex_runtime.pilot import Journal
from ai_inspector.codex_runtime.policy import DISABLED_FEATURES, PilotError, PilotSettings, READONLY_PROFILE


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Shared execution tests must not start processes or contact providers")

    connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            forbidden()
        return connect(sock, address)

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-key")


@pytest.fixture
def settings(tmp_path):
    return PilotSettings(Path("unused-codex"), tmp_path / "pilot", "gpt-5.5", timeout_seconds=5)


@pytest.mark.parametrize("auth_mode", ["api_key", "chatgpt_plan"])
def test_live_gate_precedes_all_credential_access(settings, monkeypatch, auth_mode):
    from ai_inspector.codex_runtime import chatgpt_accounts

    def forbidden(*args):
        raise AssertionError("Credential read before approval")

    monkeypatch.setattr(gateway_turn, "live_allowed", lambda: False)
    monkeypatch.setattr(gateway_turn, "os", SimpleNamespace(environ=SimpleNamespace(get=forbidden)))
    monkeypatch.setattr(chatgpt_accounts, "subscription_credential", forbidden)
    with pytest.raises(PilotError) as caught:
        asyncio.run(gateway_turn.prepare_credentials(replace(settings, auth_mode=auth_mode)))
    assert caught.value.code == "codex_paid_testing_disabled"


@pytest.mark.parametrize("key", ["  dedicated-test-key  ", "", "   "])
def test_api_credential_preparation(settings, monkeypatch, key):
    monkeypatch.setattr(gateway_turn, "live_allowed", lambda: True)
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", key)
    if key.strip():
        assert asyncio.run(gateway_turn.prepare_credentials(settings)) == (key.strip(), None)
    else:
        with pytest.raises(PilotError) as caught:
            asyncio.run(gateway_turn.prepare_credentials(settings))
        assert caught.value.code == "codex_api_key_required"


@pytest.mark.parametrize("fails", [False, True])
def test_subscription_credential_has_no_api_fallback(settings, monkeypatch, fails):
    from ai_inspector.codex_runtime import chatgpt_accounts
    import threading

    thread = threading.get_ident()
    subscription = SimpleNamespace(access_token="synthetic-access-token", binding="account-test")
    error = PilotError("subscription_unavailable", "Synthetic credential failure")

    def credential(model):
        assert threading.get_ident() != thread
        assert model == settings.model
        if fails:
            raise error
        return subscription

    monkeypatch.setattr(gateway_turn, "live_allowed", lambda: True)
    monkeypatch.setattr(chatgpt_accounts, "subscription_credential", credential)
    call = gateway_turn.prepare_credentials(replace(settings, auth_mode="chatgpt_plan"))
    if fails:
        with pytest.raises(PilotError) as caught:
            asyncio.run(call)
        assert caught.value is error
    else:
        assert asyncio.run(call) == ("", subscription)


class Harness:
    def __init__(self, settings, monkeypatch):
        self.settings = settings
        self.events, self.phases = [], []
        self.runtime = None
        self.fail_at = self.hang_at = None
        self.error = RuntimeError("synthetic transport failure")
        self.reached = asyncio.Event()
        self.after_inspect = None
        self.gateway = SimpleNamespace(specs=tool_specs(), closed=False, check=self.check)
        self.journal = Journal(settings.root)
        self.journal.begin("bound-session", "turn-test", "request-test")
        monkeypatch.setattr(gateway_turn, "serve_gateway", self.bridge)

    def check(self):
        assert not self.gateway.closed
        self.events.append("check")
        if self.fail_at == "check":
            raise self.error

    async def stage(self, name):
        self.events.append(name)
        if self.fail_at == name:
            raise self.error
        if self.hang_at == name:
            self.reached.set()
            await asyncio.Future()

    @asynccontextmanager
    async def bridge(self, gateway):
        assert gateway is self.gateway
        try:
            await self.stage("listener")
            yield "http://127.0.0.1:9/mcp", "synthetic-mcp-token"
        finally:
            self.events.append("listener_closed")
            gateway.closed = True

    def transport(self, binary, root, environment, config):
        owner = self
        self.launch = (binary, root, environment, config)

        class Transport:
            timeline = [{"phase": "scripted_test_transport"}]

            async def __aenter__(self):
                try:
                    await owner.stage("startup")
                    return self
                except BaseException:
                    # Like AppServer, partially entered transports clean themselves up.
                    owner.events.append("runtime_closed")
                    raise

            async def __aexit__(self, *_args):
                assert owner.gateway.closed, "Tool access must be revoked before runtime shutdown"
                owner.events.append("runtime_closed")

            async def inspect(self, **kwargs):
                owner.invocation = kwargs
                await owner.stage("inspection")
                kwargs["check"]()
                kwargs["on_thread"]("thread-new")
                if kwargs["text_sink"]:
                    await kwargs["text_sink"]("Scripted answer")
                if kwargs["status_sink"]:
                    await kwargs["status_sink"]("codex_inspecting")
                if owner.after_inspect:
                    owner.after_inspect()
                return "Scripted answer"

        self.runtime = Transport()
        return self.runtime

    def arguments(self, **overrides):
        return dict(settings=self.settings, gateway=self.gateway, journal=self.journal,
                    binding="bound-session", message="Inspect the bound document", instructions="Caller instructions",
                    effort="high", api_key="synthetic-key", transport_factory=self.transport,
                    on_phase=lambda phase, runtime: self.phases.append((phase, runtime)), **overrides)

    def assert_caller_owns_journal(self):
        with self.journal.db() as db:
            assert db.execute("SELECT status, result FROM turns").fetchall() == [("running", None)]


@pytest.fixture
def harness(settings, monkeypatch):
    return Harness(settings, monkeypatch)


@pytest.mark.parametrize("inventory", ["read_only", "direct_edit", "other_gateway", "empty"])
@pytest.mark.parametrize("auth_mode", ["api_key", "chatgpt_plan"])
def test_exact_allowlist_restricted_environment_and_thread_lifecycle(harness, monkeypatch, inventory, auth_mode):
    h = harness
    h.gateway.specs = {"read_only": tool_specs(), "direct_edit": tool_specs(direct_edit=True),
                       "other_gateway": [{"name": "inspect_documentation_context"}], "empty": []}[inventory]
    h.settings = replace(h.settings, auth_mode=auth_mode)
    h.journal.bind_thread("bound-session", "thread-old")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    monkeypatch.setenv("HTTP_PROXY", "must-not-inherit")
    monkeypatch.setenv("CODEX_HOME", "must-not-inherit")
    texts, statuses = [], []

    async def text(value):
        texts.append(value)

    async def status(value):
        statuses.append(value)

    args = h.arguments(text_sink=text, status_sink=status)
    if auth_mode == "chatgpt_plan":
        args.update(api_key="", subscription=SimpleNamespace(access_token="synthetic-access-token"))
    answer, runtime = asyncio.run(gateway_turn.run_gateway_turn(**args))
    assert answer == "Scripted answer" and runtime is h.runtime
    binary, root, env, config = h.launch
    assert binary == h.settings.binary and root == h.settings.root / "sessions" / "bound-session"
    assert all((root / name).is_dir() for name in ("home", "workspace", "temp", "appdata", "localappdata"))
    assert env["CODEX_HOME"] == str(root / "home")
    assert not {"OPENAI_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}.intersection(env)
    assert env["INSPECTORPRO_CODEX_MCP_TOKEN"] == "synthetic-mcp-token"
    credential_key = "INSPECTORPRO_CHATGPT_ACCESS_TOKEN" if auth_mode == "chatgpt_plan" else "INSPECTORPRO_CODEX_API_KEY"
    other_key = "INSPECTORPRO_CODEX_API_KEY" if auth_mode == "chatgpt_plan" else "INSPECTORPRO_CHATGPT_ACCESS_TOKEN"
    assert credential_key in env and other_key not in env
    assert config["model_providers"]["inspectorpro"]["env_key"] == credential_key
    assert list(config["mcp_servers"]) == ["inspectorpro"]
    assert config["mcp_servers"]["inspectorpro"]["enabled_tools"] == [s["name"] for s in h.gateway.specs]
    assert config["mcp_servers"]["inspectorpro"]["url"] == "http://127.0.0.1:9/mcp"
    assert config["features"] == dict.fromkeys(DISABLED_FEATURES, False)
    assert config["approval_policy"] == "never" and config["web_search"] == "disabled"
    assert config["default_permissions"] == READONLY_PROFILE
    assert config["permissions"] == {READONLY_PROFILE: {
        "filesystem": {":root": "deny", ":workspace_roots": {".": "read"}}, "network": {"enabled": False}}}
    assert set(h.invocation) == {"message", "thread_id", "instructions", "on_thread", "text_sink", "status_sink", "check", "effort"}
    assert h.invocation["instructions"] == args["instructions"] and h.invocation["message"] == args["message"]
    assert h.invocation["effort"] == "high" and h.invocation["thread_id"] == "thread-old"
    assert h.invocation["check"] is h.gateway.check
    assert h.journal.thread("bound-session") == "thread-new"
    assert texts == [answer] and statuses == ["codex_inspecting"]
    assert h.phases == [("mcp_listener_start", None), ("child_environment", None),
                        ("runtime_startup", runtime), ("inspection", runtime)]
    assert h.events[-3:] == ["check", "runtime_closed", "listener_closed"]
    assert h.gateway.closed
    h.assert_caller_owns_journal()


@pytest.mark.parametrize("stage, phase", [("listener", "mcp_listener_start"), ("startup", "runtime_startup"),
                                         ("inspection", "inspection"), ("check", "inspection")])
def test_failure_retains_actual_runtime_diagnostics_and_closes(harness, stage, phase):
    h = harness
    h.fail_at = stage
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(gateway_turn.run_gateway_turn(**h.arguments()))
    assert caught.value is h.error
    assert caught.value.gateway_phase == phase
    assert caught.value.gateway_runtime is h.runtime
    if stage != "listener":
        assert h.runtime.timeline and "runtime_closed" in h.events
    assert h.events[-1] == "listener_closed" and h.gateway.closed
    h.assert_caller_owns_journal()


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
@pytest.mark.parametrize("stage", ["listener", "startup", "inspection"])
def test_timeout_and_cancellation_close_resources_without_success(harness, mode, stage):
    h = harness
    h.hang_at = stage
    if mode == "timeout":
        h.settings = replace(h.settings, timeout_seconds=0.03)

    async def exercise():
        task = asyncio.create_task(gateway_turn.run_gateway_turn(**h.arguments()))
        if mode == "cancel":
            await asyncio.wait_for(h.reached.wait(), 2)
            task.cancel()
        with pytest.raises(TimeoutError if mode == "timeout" else asyncio.CancelledError) as caught:
            await task
        assert caught.value.gateway_runtime is h.runtime
        assert caught.value.gateway_phase == {"listener": "mcp_listener_start", "startup": "runtime_startup",
                                               "inspection": "inspection"}[stage]

    asyncio.run(exercise())
    assert h.gateway.closed and h.events[-1] == "listener_closed"
    assert ("runtime_closed" in h.events) == (stage != "listener")
    h.assert_caller_owns_journal()


def test_conflicting_credentials_fail_before_transport_and_close_listener(harness):
    args = harness.arguments(subscription=SimpleNamespace(access_token="synthetic-access-token"))
    with pytest.raises(PilotError) as caught:
        asyncio.run(gateway_turn.run_gateway_turn(**args))
    assert caught.value.code == "codex_auth_mode_conflict"
    assert caught.value.gateway_phase == "child_environment" and caught.value.gateway_runtime is None
    assert harness.runtime is None and harness.gateway.closed
    assert harness.events == ["listener", "listener_closed"]


def test_final_context_check_discards_answer_after_revocation(harness):
    harness.after_inspect = lambda: setattr(harness, "fail_at", "check")
    harness.error = PilotError("codex_document_unavailable", "Synthetic context switch")
    with pytest.raises(PilotError) as caught:
        asyncio.run(gateway_turn.run_gateway_turn(**harness.arguments()))
    assert caught.value is harness.error
    assert harness.gateway.closed
    harness.assert_caller_owns_journal()


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_documentation_finalization_stays_inside_check_timeout_and_cleanup(harness, outcome):
    h = harness
    if outcome == "timeout":
        h.settings = replace(h.settings, timeout_seconds=0.03)

    async def finish(answer):
        assert not h.gateway.closed and "runtime_closed" not in h.events
        h.events.append("finish")
        if outcome == "failure":
            raise h.error
        if outcome == "timeout":
            await asyncio.Future()
        return answer + " finalized"

    call = gateway_turn._run_gateway_turn(**h.arguments(), bridge_factory=h.bridge, finish_answer=finish)
    if outcome == "success":
        answer, runtime = asyncio.run(call)
        assert answer == "Scripted answer finalized" and runtime is h.runtime
        assert h.events[-4:] == ["finish", "check", "runtime_closed", "listener_closed"]
    else:
        with pytest.raises(TimeoutError if outcome == "timeout" else RuntimeError) as caught:
            asyncio.run(call)
        assert caught.value.gateway_runtime is h.runtime
        assert h.events[-3:] == ["finish", "runtime_closed", "listener_closed"]
    assert h.gateway.closed
    assert "finish_answer" not in h.invocation and "bridge_factory" not in h.invocation
    h.assert_caller_owns_journal()


def test_public_transport_default_remains_real_app_server():
    parameters = inspect.signature(gateway_turn.run_gateway_turn).parameters
    assert parameters["transport_factory"].default is AppServer
    assert list(parameters) == ["settings", "gateway", "journal", "binding", "message", "instructions", "effort",
                                "api_key", "subscription", "text_sink", "status_sink", "transport_factory", "on_phase"]


@pytest.mark.parametrize("outcome", ["startup", "inspection", "group", "timeout", "cancel"])
def test_documentation_keeps_failure_journal_and_actual_runtime(harness, monkeypatch, outcome):
    from ai_inspector.codex_runtime import documentation_pilot
    from tests.test_codex_documentation_tools import Host, PRINCIPAL

    h = harness
    host = Host()
    host.resolve_principal = lambda _: PRINCIPAL
    monkeypatch.setattr(documentation_pilot, "live_allowed", lambda: True)
    monkeypatch.setattr(gateway_turn, "live_allowed", lambda: True)
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")
    if outcome in {"timeout", "cancel"}:
        h.hang_at = "inspection"
        if outcome == "timeout":
            h.settings = replace(h.settings, timeout_seconds=0.05)
    else:
        h.fail_at = "startup" if outcome == "startup" else "inspection"
        if outcome == "group":
            h.error = ExceptionGroup("transport group", [PilotError("synthetic_policy_error", "Denied")])

    @asynccontextmanager
    async def bridge(gateway):
        h.gateway = gateway
        async with h.bridge(gateway) as address:
            yield address

    monkeypatch.setattr(documentation_pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="doc-turn",
                              conversation_id="conversation", message="Inspect the manual", context=None,
                              inspection_context=None)

    async def exercise():
        task = asyncio.create_task(documentation_pilot.inspect_documentation(
            request, host, None, {"assembly_number": "tricycle"}, settings=h.settings,
            transport_factory=h.transport))
        if outcome == "cancel":
            await asyncio.wait_for(h.reached.wait(), 2)
            task.cancel()
        with pytest.raises(asyncio.CancelledError if outcome == "cancel" else PilotError) as caught:
            await task
        if outcome != "cancel":
            assert caught.value.code == {"group": "synthetic_policy_error", "timeout": "codex_time_budget_exhausted"}.get(
                outcome, "codex_runtime_failed")

    asyncio.run(exercise())
    with h.journal.db() as db:
        status, raw = db.execute("SELECT status, result FROM turns WHERE turn_id='doc-turn'").fetchone()
    result = json.loads(raw)
    assert status == ("interrupted" if outcome == "cancel" else "failed")
    assert result["receipts"] == h.gateway.receipts
    if outcome == "cancel":
        assert result["code"] == "codex_interrupted"
    else:
        assert result["diagnostic"]["runtimeTimeline"] == h.runtime.timeline
        assert result["diagnostic"]["phase"] == ("runtime_startup" if outcome == "startup" else "inspection")
    assert h.gateway.closed and h.events[-2:] == ["runtime_closed", "listener_closed"]
