"""Independent offline review regressions; no provider or running host access."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime import gateway_turn, packaging_pilot
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.memory.envelope import _scope
from ai_inspector.packaging_shipping.admission import PackagingAdmission
from tests.test_codex_packaging_pilot import arrange, execute, setup


def test_cancellation_revokes_tools_before_transport_shutdown(setup, monkeypatch):
    started = asyncio.Event()
    captured = {}

    @asynccontextmanager
    async def bridge(gateway):
        captured["gateway"] = gateway
        try:
            yield "http://127.0.0.1:9/mcp", "test-token"
        finally:
            gateway.closed = True

    class Transport:
        timeline = []

        def __init__(self, *_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            # An MCP request can still reach the listener while AppServer.close
            # is awaiting its process/tasks. This edit starts after cancellation.
            captured["late_edit"] = await captured["gateway"].call("edit_packaging", {
                "expected_revision": 0, "request_id": "after-cancel",
                "design": {**setup.doc["design"], "name": "Should not be saved"}})

        async def inspect(self, **kwargs):
            started.set()
            await asyncio.Future()

    monkeypatch.setattr(gateway_turn, "serve_gateway", bridge)

    async def exercise():
        task = asyncio.create_task(execute(setup, transport_factory=Transport))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)

    asyncio.run(exercise())
    assert setup.service.get(setup.scope, setup.doc["id"])["revision"] == 0, captured["late_edit"]
    assert not captured["late_edit"]["ok"]


def test_terminal_reference_failure_cannot_hide_saved_edits(setup, monkeypatch):
    async def runtime(**kwargs):
        await arrange(kwargs["gateway"])
        kwargs["gateway"].closed = True
        return "Packed six", SimpleNamespace(timeline=[])

    finish = packaging_pilot.Journal.finish

    def finish_then_revoke(journal, binding, turn_id, status, result):
        finish(journal, binding, turn_id, status, result)
        if status == "completed":
            setup.admission.revoke(setup.principal, setup.editor["admission_id"],
                                   {"selection_id": setup.editor["selection_id"]})

    monkeypatch.setattr(packaging_pilot, "run_gateway_turn", runtime)
    monkeypatch.setattr(packaging_pilot.Journal, "finish", finish_then_revoke)
    try:
        result = asyncio.run(execute(setup))
    except Exception as error:
        assert isinstance(error, PilotError), "Bare cleanup errors bypass the server's packaging evidence wrapper"
        evidence = error.packaging_result
    else:
        evidence = result["codex_packaging"]
    assert evidence["mutationOutcome"] == "committed" and evidence["revision"] == 1
    assert setup.service.get(setup.scope, setup.doc["id"])["revision"] == 1


def test_packaging_scope_is_accepted_by_memory_envelope():
    assert _scope({"kind": "packaging_shipping", "ids": {"documentId": "package-test"},
                   "revisionVector": {"packagingRevision": "1"}})["revisionVector"] == {"packagingRevision": "1"}


def test_journal_blocks_same_turn_after_revision_change_and_admission_restart(setup, monkeypatch):
    starts = []

    async def runtime(**kwargs):
        starts.append(True)
        await arrange(kwargs["gateway"])
        kwargs["gateway"].closed = True
        return "Packed six", SimpleNamespace(timeline=[])

    monkeypatch.setattr(packaging_pilot, "run_gateway_turn", runtime)
    asyncio.run(execute(setup))
    # Drop the in-memory admission ledger, retaining the actual on-disk journal.
    setup.admission = PackagingAdmission(setup.service)
    setup.editor = setup.admission.publish(setup.principal, {**setup.state, "revision": 1})
    with pytest.raises(PilotError) as caught:
        asyncio.run(execute(setup))
    assert caught.value.code == "codex_duplicate_conflict"
    assert starts == [True]
    assert setup.service.get(setup.scope, setup.doc["id"])["revision"] == 1
