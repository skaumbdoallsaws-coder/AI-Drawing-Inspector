"""Read-only pilot tests. No credentials, model inference, or user documents."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from dataclasses import replace
from pathlib import Path
import time
import threading
import tomllib
from types import SimpleNamespace

import anyio
import httpx
import pytest

from ai_inspector.codex_runtime.app_server import AppServer, failure_diagnostic, toml_value
from ai_inspector.codex_runtime.facility_tools import FacilityReadGateway, tool_specs
from ai_inspector.codex_runtime.mcp_bridge import make_application
from ai_inspector.codex_runtime.pilot import Journal, inspect_facility
from ai_inspector.codex_runtime.policy import (
    FLAG, LIVE_FLAG, READONLY_PROFILE, PilotError, PilotSettings, child_environment, enabled, runtime_config,
)
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, LOCAL_SITE_ID, LOCAL_LAYOUT_ID


@pytest.fixture
def host(tmp_path):
    value = LocalFacilityLayoutHost(tmp_path / "facility", private_assets=False)
    value.ensure_bootstrap()
    yield value
    value.close()


def gateway(host, **kwargs):
    current = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    return FacilityReadGateway(host.agent_runtime, host.principal(), {
        "siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": current["revision"],
    }, turn_id="test-turn", **kwargs)


def test_disabled_by_default_and_environment_isolated(monkeypatch, tmp_path):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    monkeypatch.setenv("HTTP_PROXY", "must-not-inherit")
    assert not enabled()
    env = child_environment(tmp_path, "capability")
    assert "OPENAI_API_KEY" not in env and "HTTP_PROXY" not in env
    assert "INSPECTORPRO_CODEX_API_KEY" not in env
    assert env["CODEX_HOME"] == str(tmp_path / "home")
    assert env["INSPECTORPRO_CODEX_MCP_TOKEN"] == "capability"


def test_failure_diagnostic_redacts_credentials():
    result = failure_diagnostic({"message": "key secret-key token capability Bearer other-token sk-example"},
        {"INSPECTORPRO_CODEX_API_KEY": "secret-key", "INSPECTORPRO_CODEX_MCP_TOKEN": "capability"})
    assert all(secret not in result["message"] for secret in ("secret-key", "capability", "other-token", "sk-example"))
    assert len(failure_diagnostic({"message": "x" * 5000}, {})["message"]) == 1200


def test_protocol_timeout_reports_phase_not_request_content(tmp_path, monkeypatch):
    runtime = AppServer(tmp_path / "unused", tmp_path, {}, {})
    async def stalled_send(_message):
        pass
    monkeypatch.setattr(runtime, "send", stalled_send)
    with pytest.raises(PilotError) as caught:
        asyncio.run(runtime.request("thread/start", {"private": "must-not-log"}, timeout=0.01))
    assert caught.value.code == "codex_protocol_timeout"
    assert caught.value.diagnostic == {"phase": "thread/start", "timeoutSeconds": 0.01}
    assert not runtime.pending
    assert [row["phase"] for row in runtime.timeline] == ["thread/start:send", "thread/start:wait"]
    assert "must-not-log" not in json.dumps(runtime.timeline)


def test_runtime_timing_is_bounded(tmp_path):
    runtime = AppServer(tmp_path / "unused", tmp_path, {}, {})
    for _ in range(100):
        runtime.mark("initialize:wait")
    assert len(runtime.timeline) == 64
    assert all(set(row) == {"phase", "elapsedMs"} and row["elapsedMs"] >= 0 for row in runtime.timeline)


def test_protocol_deadline_includes_blocked_pipe_write(tmp_path, monkeypatch):
    runtime = AppServer(tmp_path / "unused", tmp_path, {}, {})
    async def blocked_send(_message):
        await asyncio.Event().wait()
    monkeypatch.setattr(runtime, "send", blocked_send)
    async def exercise():
        with pytest.raises(PilotError) as caught:
            await asyncio.wait_for(runtime.request("initialize", {}, timeout=0.01), 1)
        assert caught.value.code == "codex_protocol_timeout"
        assert caught.value.diagnostic["phase"] == "initialize"
        assert not runtime.pending
        assert [row["phase"] for row in runtime.timeline] == ["initialize:send"]
    asyncio.run(exercise())


def test_runtime_config_roundtrips_and_disables_general_tools():
    config = runtime_config("http://127.0.0.1:9999/mcp", "test-model", offline=True)
    parsed = tomllib.loads("\n".join(key + "=" + toml_value(value) for key, value in config.items()))
    assert parsed == config
    assert "sandbox_mode" not in config
    assert config["default_permissions"] == READONLY_PROFILE
    assert config["permissions"][READONLY_PROFILE] == {
        "filesystem": {":root": "deny", ":workspace_roots": {".": "read"}},
        "network": {"enabled": False},
    }
    assert config["approval_policy"] == "never"
    assert not any(config["features"].values())
    assert config["features"]["view_image"] is False
    assert config["web_search"] == "disabled"
    assert "env_key" not in config["model_providers"]["inspectorpro"]
    assert set(config["mcp_servers"]) == {"inspectorpro"}
    assert set(config["mcp_servers"]["inspectorpro"]["enabled_tools"]) == {
        "inspect_facility_context", "inspect_facility_entities", "inspect_facility_semantics",
        "inspect_facility_findings", "analyze_facility_spatial", "observe_navigation_context",
        "inspect_saved_process_bindings", "search_industrial_assets", "inspect_facility_region",
        "analyze_facility_fit", "inspect_pattern_provenance", "inspect_cell_layout_provenance",
        "inspect_facility_authoring", "inspect_facility_asset", "inspect_facility_components", "list_facility_library",
        "review_facility_parking", "review_facility_workstations", "suggest_facility_light_positions",
        "check_lighting_coverage", "plan_facility_pattern", "plan_facility_cell", "plan_facility_position",
        "plan_facility_stack", "show_facility_views",
        "search_public_sources", "read_public_source",
        "inspect_site_context", "analyze_site_fit", "look_at_site_photo", "trace_site_feature",
        "plan_warehouse_building", "plan_warehouse_zones", "plan_floor_markings", "plan_storage_layout",
        "plan_site_docks", "plan_site_parking", "plan_warehouse_contents", "plan_design_paint",
        "suggest_site_references", "check_site_references", "prepare_layout_pdf", "suggest_emergency_teams"}


def test_gateway_reads_real_backend_and_never_changes_revision(host):
    reader = gateway(host)
    before = reader.check()["revision"]
    async def exercise():
        context = await reader.call("inspect_facility_context", {})
        assert context["ok"] and context["data"]["readOnly"]
        details = await reader.call("inspect_facility_semantics", {"view": "overview"})
        assert details["ok"], details
        spatial = await reader.call("analyze_facility_spatial", {"analysis": "resolve_entities", "query": "CNC"})
        assert spatial["ok"], spatial
    asyncio.run(exercise())
    assert reader.check()["revision"] == before
    assert len(reader.receipts) == 3 and all(item["ok"] for item in reader.receipts)


@pytest.mark.parametrize("name,args,code", [
    ("delete_layout", {}, "codex_tool_denied"),
    ("inspect_facility_context", {"layoutId": "other"}, "codex_tool_arguments_invalid"),
    ("inspect_facility_entities", {"entityKind": "placement"}, "codex_tool_arguments_invalid"),
    ("inspect_facility_findings", {"pageSize": 100000}, "codex_tool_arguments_invalid"),
])
def test_gateway_rejects_unauthorized_tools_and_arguments(host, name, args, code):
    result = asyncio.run(gateway(host).call(name, args))
    assert result["ok"] is False and result["error"]["code"] == code
    expected = {"code", "message", "details"} if code == "codex_tool_arguments_invalid" else {"code", "message"}
    assert set(result["error"]) == expected
    if "details" in expected:
        findings = result["error"]["details"]["findings"]
        assert 1 <= len(findings) <= 6
        assert all(set(item) == {"path", "message"} for item in findings)


def test_gateway_budget_revocation_and_stale_revision(host):
    reader = gateway(host, max_calls=1)
    asyncio.run(reader.call("inspect_facility_context", {}))
    assert asyncio.run(reader.call("inspect_facility_context", {}))["error"]["code"] == "codex_tool_budget_exhausted"
    assert reader.closed
    reader = gateway(host)
    reader.closed = True
    assert asyncio.run(reader.call("inspect_facility_context", {}))["error"]["code"] == "codex_run_closed"
    reader = gateway(host)
    reader.reference["revision"] = "0" * 64
    assert asyncio.run(reader.call("inspect_facility_context", {}))["error"]["code"] == "codex_document_unavailable"


def test_gateway_rejects_cross_site_principal(host):
    reader = gateway(host)
    reader.principal = replace(reader.principal, allowed_site_ids=("different-site",))
    result = asyncio.run(reader.call("inspect_facility_context", {}))
    assert not result["ok"]


def test_revision_advanced_during_read_discards_old_result(host, monkeypatch):
    reader = gateway(host)
    original = reader.check()
    read = reader._read_data

    def concurrent_save(name, arguments):
        data = read(name, arguments)
        changed = dict(original["layout"])
        changed["displayName"] = "Concurrent revision"
        host.layout_repository.save_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID,
            changed, original["revision"])
        return data

    monkeypatch.setattr(reader, "_read_data", concurrent_save)
    result = asyncio.run(reader.call("inspect_facility_context", {}))
    assert result["ok"] is False and "data" not in result
    assert result["error"]["code"] == "codex_document_unavailable"
    assert reader.receipts[-1]["ok"] is False
    with pytest.raises(PilotError) as caught:
        reader.check()
    assert caught.value.code == "codex_document_unavailable"


def test_memory_binding_matches_domain_revisions_without_geometry_analysis(host, monkeypatch):
    import server
    from fastapi import HTTPException
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", host)
    current = host.service.get_layout(host.principal(), LOCAL_SITE_ID, LOCAL_LAYOUT_ID)
    reference = {"siteId": LOCAL_SITE_ID, "layoutId": LOCAL_LAYOUT_ID, "revision": current["revision"]}
    request = server.AgentChatRequest(message="Inspect this layout", agent_type="deviation-analyst",
        inspection_context={"attachments": {"session": {"active_mode": "facility_layout"},
            "facility_layout": {**reference, "state": {"dirty": False}}}})
    monkeypatch.setenv(FLAG, "0")
    expected = server._memory_trusted_turn_context(request, None)
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setattr(host.agent_runtime, "resolve_context", lambda *_a, **_k: pytest.fail("Geometry analysis is not an identity check"))
    assert server._memory_trusted_turn_context(request, None) == expected
    context, targets = server._memory_reconciliation_context(request, None)
    assert context["facility_layout_state"]["identity"]["revision"] == current["revision"]
    assert targets["facility_layout"] == [LOCAL_LAYOUT_ID]
    request.inspection_context["attachments"]["facility_layout"]["revision"] = "0" * 64
    with pytest.raises(HTTPException) as caught:
        server._memory_trusted_turn_context(request, None)
    assert caught.value.detail["error"]["code"] == "codex_document_unavailable"
    request.inspection_context["attachments"]["facility_layout"]["state"]["dirty"] = True
    with pytest.raises(HTTPException) as caught:
        server._memory_trusted_turn_context(request, None)
    assert caught.value.detail["error"]["code"] == "codex_saved_layout_required"


def test_read_worker_keeps_loop_responsive_and_joins_on_cancel(host, monkeypatch):
    reader = gateway(host)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_read(*_):
        entered.set()
        release.wait(3)
        finished.set()
        return {"readOnly": True}

    monkeypatch.setattr(reader, "_read_data", slow_read)

    async def exercise():
        task = asyncio.create_task(reader.call("inspect_facility_context", {}))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            assert not finished.is_set()
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and reader.closed
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and not reader.lock.locked()

    asyncio.run(exercise())


@pytest.mark.parametrize("direct_cancel", [False, True])
def test_read_worker_joins_anyio_cancel_without_busy_spin(host, monkeypatch, direct_cancel):
    reader = gateway(host)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_shield = asyncio.shield
    join_count = 0
    work = None

    def tracked_shield(task):
        nonlocal join_count, work
        join_count += 1
        work = task
        return original_shield(task)

    def slow_read(*_):
        entered.set()
        try:
            assert release.wait(3)
            return {"readOnly": True}
        finally:
            finished.set()

    monkeypatch.setattr(asyncio, "shield", tracked_shield)
    monkeypatch.setattr(reader, "_read_data", slow_read)

    async def exercise():
        call_task = None
        joined_at_exit = []

        async def read():
            nonlocal call_task
            call_task = asyncio.current_task()
            try:
                await reader.call("inspect_facility_context", {})
                pytest.fail("A cancelled read must not publish its result")
            finally:
                joined_at_exit.append(finished.is_set() and work.done())

        async with anyio.create_task_group() as group:
            group.start_soon(read)
            try:
                async with asyncio.timeout(2):
                    while not entered.is_set():
                        await asyncio.sleep(0.001)
                    group.cancel_scope.cancel()
                    with anyio.CancelScope(shield=True):
                        while not reader.closed:
                            await asyncio.sleep(0.001)
                        for _ in range(2):
                            if direct_cancel:
                                call_task.cancel()
                            await asyncio.sleep(0.01)
                            assert not call_task.done() and not finished.is_set()
                            assert reader.lock.locked()
                            assert join_count <= 5
            finally:
                release.set()

        assert call_task.cancelled() and joined_at_exit == [True]
        assert work.done() and not work.cancelled() and work.exception() is None
        assert reader.closed and not reader.lock.locked()
        assert reader.calls == 1 and reader.receipts == []
        assert join_count <= 5

    anyio.run(exercise, backend="asyncio")


def test_runtime_close_joins_repeated_cancellation_and_exit_race(tmp_path):
    async def exercise():
        runtime = AppServer(Path("unused"), tmp_path, {}, {})
        release = asyncio.Event()
        terminated = []
        closed = []
        def terminate():
            terminated.append(True)
            raise ProcessLookupError()
        async def wait():
            await release.wait()
            runtime.process.returncode = 0
        runtime.process = SimpleNamespace(returncode=None, terminate=terminate, wait=wait,
            stdin=SimpleNamespace(close=lambda: closed.append(True)))
        runtime.tasks = [asyncio.create_task(asyncio.sleep(30))]
        closing = asyncio.create_task(runtime.close())
        await asyncio.sleep(0.01)
        closing.cancel()
        await asyncio.sleep(0.01)
        closing.cancel()
        await asyncio.sleep(0.01)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        await runtime.close()
        assert terminated == closed == [True]
        assert all(task.done() for task in runtime.tasks)
        assert [row["phase"] for row in runtime.timeline] == ["closing", "closed"]
    asyncio.run(exercise())


@pytest.mark.parametrize("direct_cancel", [False, True])
def test_runtime_close_joins_anyio_cancel_without_busy_spin(tmp_path, monkeypatch, direct_cancel):
    original_shield = asyncio.shield
    join_count = 0

    def tracked_shield(task):
        nonlocal join_count
        join_count += 1
        return original_shield(task)

    monkeypatch.setattr(asyncio, "shield", tracked_shield)

    async def exercise():
        runtime = AppServer(Path("unused"), tmp_path, {}, {})
        process_waiting, release_process = asyncio.Event(), asyncio.Event()
        ready, release_children = asyncio.Event(), asyncio.Event()
        child_cleanup = [asyncio.Event(), asyncio.Event()]
        terminated, closed, finished, joined_at_exit = [], [], [], []
        closing = None

        async def wait():
            process_waiting.set()
            await release_process.wait()
            runtime.process.returncode = 0

        async def child(index):
            try:
                await asyncio.Event().wait()
            finally:
                child_cleanup[index].set()
                await release_children.wait()
                finished.append(index)

        async def use_runtime():
            nonlocal closing
            closing = asyncio.current_task()
            try:
                try:
                    ready.set()
                    await asyncio.Event().wait()
                finally:
                    await runtime.close()
            finally:
                joined_at_exit.append(runtime._closing.done() and all(task.done() for task in runtime.tasks))

        runtime.process = SimpleNamespace(returncode=None, terminate=lambda: terminated.append(True),
            wait=wait, stdin=SimpleNamespace(close=lambda: closed.append(True)))
        runtime.tasks = [asyncio.create_task(child(index)) for index in range(2)]
        async with anyio.create_task_group() as group:
            group.start_soon(use_runtime)
            try:
                async with asyncio.timeout(2):
                    await ready.wait()
                    group.cancel_scope.cancel()
                    with anyio.CancelScope(shield=True):
                        await process_waiting.wait()
                        if direct_cancel:
                            closing.cancel()
                        await asyncio.sleep(0.01)
                        assert not closing.done() and not runtime._closing.done()
                        assert not closed and join_count <= 5
                        release_process.set()
                        for event in child_cleanup:
                            await event.wait()
                        if direct_cancel:
                            closing.cancel()
                        await asyncio.sleep(0.01)
                        assert not closing.done() and not runtime._closing.done()
                        assert not finished and join_count <= 5
            finally:
                release_process.set()
                release_children.set()

        assert closing.cancelled() and joined_at_exit == [True]
        assert runtime.process.returncode == 0 and runtime._closing.done()
        assert all(task.done() for task in runtime.tasks) and sorted(finished) == [0, 1]
        await runtime.close()
        assert terminated == closed == [True]
        assert [row["phase"] for row in runtime.timeline] == ["closing", "closed"]
        assert join_count <= 5

    anyio.run(exercise, backend="asyncio")


def test_unverified_model_rejected_before_launch(monkeypatch, tmp_path):
    monkeypatch.setenv("INSPECTORPRO_CODEX_BINARY", str(tmp_path / "unused.exe"))
    monkeypatch.setenv("INSPECTORPRO_CODEX_PILOT_ROOT", str(tmp_path / "pilot"))
    monkeypatch.setenv("INSPECTORPRO_CODEX_MODEL", "gpt-6-astra")
    with pytest.raises(PilotError) as caught:
        PilotSettings.from_environment()
    assert caught.value.code == "codex_model_not_verified"


def test_journal_replay_conflicts_and_crash_recovery(tmp_path):
    journal = Journal(tmp_path)
    assert journal.begin("binding", "one", "hash") is None
    with pytest.raises(PilotError, match="already active"):
        journal.begin("binding", "two", "hash")
    with pytest.raises(PilotError, match="different request"):
        journal.begin("binding", "one", "different")
    journal.finish("binding", "one", "completed", {"response": "done"})
    assert journal.begin("binding", "one", "hash") == {"response": "done"}
    journal.begin("binding", "two", "hash")
    with journal.db() as db:
        db.execute("UPDATE turns SET updated=? WHERE turn_id='two'", (time.time() - 700,))
    assert journal.begin("binding", "three", "hash") is None
    with pytest.raises(PilotError, match="not be silently replayed"):
        journal.begin("binding", "two", "hash")
    journal.bind_thread("binding", "thread1")
    assert journal.thread("binding") == "thread1"
    assert journal.thread("another-document") is None


def test_paid_inference_requires_separate_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv(LIVE_FLAG, raising=False)
    with pytest.raises(PilotError, match="disabled pending approval"):
        asyncio.run(inspect_facility(None, None, None, {}, settings=PilotSettings(Path("unused"), tmp_path, "test")))


def test_unsaved_preview_rejected_before_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="turn")
    with pytest.raises(PilotError, match="saved layouts only"):
        asyncio.run(inspect_facility(request, None, None, {"facility_layout_live_state": {"dirty": True}},
            settings=PilotSettings(Path("unused"), tmp_path, "test")))


def test_mcp_auth_schemas_and_actual_tool_calls(host):
    pytest.importorskip("mcp")
    reader = gateway(host)
    app, manager = make_application(reader, "secret", "127.0.0.1:7654")
    async def exercise():
        async with manager.run():
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7654") as client:
                body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
                assert (await client.post("/mcp", json=body)).status_code == 403
                headers = {"Authorization": "Bearer secret", "Accept": "application/json, text/event-stream",
                           "MCP-Protocol-Version": "2025-11-25"}
                assert (await client.post("/mcp", json=body, headers={**headers, "Origin": "http://evil"})).status_code == 403
                assert (await client.post("/mcp", json=body, headers={**headers, "Host": "evil"})).status_code == 403
                result = await client.post("/mcp", json=body, headers=headers)
                assert result.status_code == 200, result.text
                assert {tool["name"] for tool in result.json()["result"]["tools"]} == {s["name"] for s in tool_specs()}
                body.update(method="tools/call", params={"name": "inspect_facility_context", "arguments": {}})
                result = await client.post("/mcp", json=body, headers=headers)
                assert result.json()["result"]["structuredContent"]["ok"], result.text
                reader.closed = True
                assert (await client.post("/mcp", json=body, headers=headers)).status_code == 403
    asyncio.run(exercise())


class ScriptedRuntime(AppServer):
    def __init__(self, tmp_path, events):
        super().__init__(Path("unused"), tmp_path, {}, runtime_config("http://127.0.0.1:9/mcp", "test", offline=True))
        self.requests = []
        for event in events:
            self.events.put_nowait(event)

    async def request(self, method, params, timeout=20):
        self.requests.append((method, params))
        if method.startswith("thread/"):
            return {"thread": {"id": "thread"}, "activePermissionProfile": {"id": READONLY_PROFILE}}
        if method == "turn/start":
            return {"turn": {"id": "turn"}}
        if method == "mcpServerStatus/list":
            return {"data": [{"name": "inspectorpro", "tools": {s["name"]: {"name": s["name"]} for s in tool_specs()}}]}
        return {}


def event(method, **params):
    return {"method": method, "params": {"threadId": "thread", "turnId": "turn", **params}}


def run_inspection(runtime):
    return runtime.inspect(message="inspect", thread_id=None, instructions="read only", on_thread=lambda _: None,
        text_sink=None, status_sink=None, check=lambda: None)


def test_protocol_ignores_other_threads_and_restricts_files(tmp_path):
    runtime = ScriptedRuntime(tmp_path, [event("item/agentMessage/delta", threadId="other", delta="wrong"),
        event("item/agentMessage/delta", delta="Inspected."),
        event("turn/completed", turn={"id": "turn", "status": "completed"})])
    assert asyncio.run(run_inspection(runtime)) == "Inspected."
    assert runtime.requests[0][1]["permissions"] == READONLY_PROFILE
    assert runtime.requests[0][1]["runtimeWorkspaceRoots"] == [str(tmp_path / "workspace")]
    assert "config" not in runtime.requests[0][1]
    turn = next(params for method, params in runtime.requests if method == "turn/start")
    assert turn["permissions"] == READONLY_PROFILE
    assert "sandboxPolicy" not in turn


def test_revision_rechecked_at_boundaries_not_each_text_delta(tmp_path):
    runtime = ScriptedRuntime(tmp_path, [event("item/agentMessage/delta", delta="Text.") for _ in range(20)] +
        [event("turn/completed", turn={"id": "turn", "status": "completed"})])
    checks = []
    asyncio.run(runtime.inspect(message="inspect", thread_id=None, instructions="read only", on_thread=lambda _: None,
        text_sink=None, status_sink=None, check=lambda: checks.append(1)))
    assert len(checks) == 2


def test_wrong_thread_permissions_rejected_before_inference(tmp_path):
    class WrongProfile(ScriptedRuntime):
        async def request(self, method, params, timeout=20):
            result = await super().request(method, params, timeout)
            if method == "thread/start":
                result["activePermissionProfile"] = {"id": ":read-only"}
            return result
    runtime = WrongProfile(tmp_path, [])
    with pytest.raises(PilotError) as caught:
        asyncio.run(run_inspection(runtime))
    assert caught.value.code == "codex_policy_mismatch"
    assert not any(method == "turn/start" for method, _ in runtime.requests)


def test_missing_mcp_tools_rejected_before_inference(tmp_path):
    class MissingTools(ScriptedRuntime):
        async def request(self, method, params, timeout=20):
            result = await super().request(method, params, timeout)
            if method == "mcpServerStatus/list":
                result["data"][0]["tools"] = {}
            return result
    runtime = MissingTools(tmp_path, [])
    with pytest.raises(PilotError) as caught:
        asyncio.run(run_inspection(runtime))
    assert caught.value.code == "codex_tools_unavailable"
    assert not any(method == "turn/start" for method, _ in runtime.requests)


@pytest.mark.parametrize("events,code", [
    ([event("turn/completed", turn={"id": "turn", "status": "failed"})], "codex_turn_incomplete"),
    ([event("turn/completed", turn={"id": "turn", "status": "completed"})], "codex_empty_response"),
    ([{"method": "inspectorpro/runtimeStopped"}], "codex_runtime_stopped"),
])
def test_protocol_failure_interrupts_without_replay(tmp_path, events, code):
    runtime = ScriptedRuntime(tmp_path, events)
    with pytest.raises(PilotError) as caught:
        asyncio.run(run_inspection(runtime))
    assert caught.value.code == code
    assert runtime.requests[-1][0] == "turn/interrupt"
    assert len([r for r in runtime.requests if r[0] == "turn/start"]) == 1


def test_protocol_cancellation_interrupts(tmp_path):
    runtime = ScriptedRuntime(tmp_path, [])
    async def exercise():
        task = asyncio.create_task(run_inspection(runtime))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    assert runtime.requests[-1][0] == "turn/interrupt"


def test_transport_denies_runtime_approval_and_handles_eof(tmp_path):
    async def exercise():
        runtime = AppServer(Path("unused"), tmp_path, {}, {})
        reader = asyncio.StreamReader()
        reader.feed_data((json.dumps({"id": "approval1", "method": "item/commandExecution/requestApproval",
            "params": {"command": "forbidden"}}) + "\n").encode())
        reader.feed_eof()
        runtime.process = SimpleNamespace(stdout=reader)
        sent = []
        async def send(value):
            sent.append(value)
        runtime.send = send
        future = asyncio.get_running_loop().create_future()
        runtime.pending[1] = future
        await runtime._read()
        assert sent[0]["id"] == "approval1" and "error" in sent[0]
        with pytest.raises(PilotError, match="connection ended"):
            await future
        assert (await runtime.events.get())["method"] == "inspectorpro/runtimeStopped"
    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["success", "no_evidence", "cancel", "timeout"])
def test_pilot_lifecycle_journals_results_without_replaying(host, tmp_path, monkeypatch, outcome):
    from ai_inspector.codex_runtime import pilot
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    state = {"starts": 0}

    @asynccontextmanager
    async def bridge(reader):
        state["gateway"] = reader
        try:
            yield "http://127.0.0.1:9/mcp", "test-capability"
        finally:
            reader.closed = True

    class Transport:
        def __init__(self, *_):
            state["starts"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            state["closed"] = True

        async def inspect(self, **kwargs):
            assert 'untrusted reference data' in kwargs['message']
            assert 'server memory context' in kwargs['message']
            assert request.message in kwargs['message']
            kwargs["on_thread"]("thread-test")
            if outcome == "cancel":
                raise asyncio.CancelledError
            if outcome == "timeout":
                raise TimeoutError
            if outcome == "success":
                invalid = await state["gateway"].call("inspect_facility_context", {"forged": True})
                assert not invalid["ok"]
                valid = await state["gateway"].call("inspect_facility_context", {})
                assert valid["ok"]
            return "Inspection complete."

    monkeypatch.setattr(pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="turn",
        conversation_id="conversation", message="Inspect the layout")
    context = {"facility_layout_ref": gateway(host).reference}
    settings = PilotSettings(Path("unused"), tmp_path / "pilot", "test-model")

    async def invoke():
        return await inspect_facility(request, host, None, context, settings=settings, transport_factory=Transport,
            memory_context="server memory context")

    if outcome in ("success", "no_evidence"):
        result = asyncio.run(invoke())
        assert result["facility_action_mode"] == "READ_ONLY" and result["tool_calls"] == []
        assert result["codex_inspection"]["engineeringChanges"] == 0
        # A reply without a successful check (a greeting) is kept but marked unchecked.
        assert result["codex_inspection"]["checkedLayout"] is (outcome == "success")
        assert result["response"] == "Inspection complete."
        assert asyncio.run(invoke()) == result
    elif outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(invoke())
    else:
        with pytest.raises(PilotError) as caught:
            asyncio.run(invoke())
        assert caught.value.code == "codex_time_budget_exhausted"
    if outcome in ("cancel", "timeout"):
        with pytest.raises(PilotError, match="not be silently replayed"):
            asyncio.run(invoke())
    assert state["starts"] == 1 and state["closed"] and state["gateway"].closed
    with Journal(settings.root).db() as db:
        assert db.execute("SELECT status FROM turns").fetchone()[0] == {
            "success": "completed", "cancel": "interrupted", "timeout": "failed", "no_evidence": "completed"}[outcome]


def test_viewport_selection_keeps_valid_ids_of_what_the_user_selected():
    from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS, MAX_SELECTION_IDS, viewport_selection
    live = {"selection": {"placementIds": ["pl-1", "pl 2", 7, "pl-3"], "zoneIds": [], "routeIds": ["rt-1"],
                          "utilityNetworkIds": ["un-1"]}}
    assert viewport_selection({"facility_layout_live_state": live}) == {"placementIds": ["pl-1", "pl-3"],
                                                                       "routeIds": ["rt-1"]}
    assert viewport_selection({}) == {} and viewport_selection({"facility_layout_live_state": {"selection": []}}) == {}
    many = {"selection": {"placementIds": [f"pl-{index}" for index in range(MAX_SELECTION_IDS + 5)]}}
    assert len(viewport_selection({"facility_layout_live_state": many})["placementIds"]) == MAX_SELECTION_IDS
    assert "viewportSelection" in EDIT_INSTRUCTIONS


@pytest.mark.parametrize("memory", ["", "server memory context"])
def test_facility_turn_carries_the_viewport_selection(host, tmp_path, monkeypatch, memory):
    from ai_inspector.codex_runtime import pilot
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    seen = {}

    @asynccontextmanager
    async def bridge(reader):
        try:
            yield "http://127.0.0.1:9/mcp", "test-capability"
        finally:
            reader.closed = True

    class Transport:
        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def inspect(self, **kwargs):
            seen["message"] = kwargs["message"]
            return "Done."

    monkeypatch.setattr(pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="turn",
        conversation_id="conversation", message="Make the selected guard panels black")
    context = {"facility_layout_ref": gateway(host).reference,
               "facility_layout_live_state": {"selection": {"placementIds": ["pl-guard-1", "pl-guard-2"]}}}
    settings = PilotSettings(Path("unused"), tmp_path / "pilot", "test-model")
    asyncio.run(inspect_facility(request, host, None, context, settings=settings, transport_factory=Transport,
                                 memory_context=memory))
    assert request.message in seen["message"] and "viewportSelection" in seen["message"]
    assert '"placementIds": ["pl-guard-1", "pl-guard-2"]' in seen["message"]
    if not memory:
        assert "not a limit on items the request names" in seen["message"]


def test_a_request_that_names_its_items_is_not_refused_over_the_selection():
    # The main session, 2026-11-01: with a stray item selected, "Robot cell R03 is down for maintenance: make its
    # stack light show red and blink." was refused ("The selected item is ..., not R03's stack light").
    from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS
    assert "A request that names its items" in EDIT_INSTRUCTIONS
    assert "Never refuse, ask or stop because the selection holds something else." in EDIT_INSTRUCTIONS


def test_edit_instructions_keep_answers_short_and_name_zone_types_that_reject_placements():
    from ai_inspector.codex_runtime.pilot import EDIT_INSTRUCTIONS
    from ai_inspector.facility_layout.g1_planner import G1_ZONE_TYPES
    from ai_inspector.facility_layout.spatial import _NON_PLACEMENT_ZONE_TYPES
    text = " ".join(EDIT_INSTRUCTIONS.split())
    # Sage echoed the old wording back to users as "The app will report whether it saved".
    assert "the app reports the actual save result" not in text
    for rule in ("Lead with the outcome in one sentence", "not raw coordinates",
                 "do not narrate routine checks", "Stay under 120 words",
                 # Repeated every turn in the 2026-10-18 demo dry run.
                 "Do not add Gaps, Open items, Unverified or Site review sections",
                 "state the direction as fact",
                 # A room wall along the outer wall sealed the staff entrance (2026-10-18).
                 "Never close an existing door or walkway with a wall",
                 # A band saw for cutting bar stock went into Receiving (2026-10-18).
                 "Place equipment where its step of the work happens",
                 "machines that cut, form or assemble do not go there",
                 # Forklift charging landed beside the toolroom, 21 m from the aisle (2026-10-18).
                 "Forklift charging and parking belong on the production side",
                 # Sage called z 8 of a z 4-26 zone "the north end" (2026-10-18), its third slip.
                 "not raw coordinates or compass words",
                 "larger z is north and larger x is east"):
        assert rule in text
    # Furniture placed in operator or service zones was rejected batch after batch.
    def names(phrase):
        return set(phrase.replace(" and ", ", ").replace(" or ", ", ").split(", "))
    rejecting = text.split("Zone types ", 1)[1].split(" reject every placement", 1)[0]
    accepting = text.split("maintenance, in ", 1)[1].split(" zones.", 1)[0]
    assert names(rejecting) == set(_NON_PLACEMENT_ZONE_TYPES)
    assert names(accepting) == set(G1_ZONE_TYPES) - set(_NON_PLACEMENT_ZONE_TYPES)
