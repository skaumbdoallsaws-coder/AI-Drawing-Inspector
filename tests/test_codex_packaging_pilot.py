"""Packaging runtime boundary over real service/admission, without model inference."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_inspector.codex_runtime import packaging_pilot as pilot
from ai_inspector.codex_runtime.policy import PilotError, PilotSettings
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.admission import PackagingAdmission
from ai_inspector.packaging_shipping.models import Design, Edit
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService


@pytest.fixture
def setup(tmp_path, monkeypatch):
    service = PackagingService(tmp_path / "packages")
    principal = FacilityPrincipal("engineer", "tenant", ("site",), ("editor",))
    scope = pilot.packaging_scope(principal)
    design = Design.model_validate({"name": "TEST packing", "quantity": 6,
        "product": {"name": "Test block", "dimensions_m": [.1, .06, .04]},
        "constraints": {"clearance_m": .02, "gap_m": .01, "allowed_orientations": [0]}})
    doc = service.create(scope, design)
    admission = PackagingAdmission(service)
    state = {"document_id": doc["id"], "revision": 0, "session_id": "session-1",
        "conversation_id": "conversation-1", "active_mode": "packaging_shipping",
        "dirty": False, "conflict": False, "pending_operations": 0}
    editor = admission.publish(principal, state)
    request = SimpleNamespace(agent_session_id="session-1", session_id="session-1",
        conversation_id="conversation-1", client_turn_id="turn-1", reasoning_effort="medium",
        message="Arrange six blocks in the existing carton. Keep unknown weights unknown.")
    settings = PilotSettings(tmp_path / "codex.exe", tmp_path / "runtime", "gpt-5.5", 20, 8)
    async def credentials(_settings):
        return "test-key", None
    monkeypatch.setattr(pilot, "prepare_credentials", credentials)
    monkeypatch.setenv("INSPECTORPRO_CODEX_EDIT_PREVIEWS", "1")
    return SimpleNamespace(service=service, principal=principal, scope=scope, doc=doc,
        admission=admission, state=state, editor=editor, request=request, settings=settings)


async def execute(setup, **kwargs):
    return await pilot.inspect_packaging(setup.request, setup.service, setup.admission,
        principal_resolver=lambda: setup.principal,
        normalized={"packaging_admission_id": setup.editor["admission_id"]}, settings=setup.settings, **kwargs)


async def arrange(gateway):
    read = await gateway.call("inspect_packaging", {"expected_revision": 0})
    assert read["ok"]
    proposed = await gateway.call("propose_packaging", {"expected_revision": 0,
        "cartons": [{"name": "Test carton", "inner_m": [.4, .3, .25], "outer_m": [.41, .31, .26]}],
        "max_packages": 1, "limit": 1})
    assert proposed["ok"] and proposed["data"]["candidates"]
    changed = await gateway.call("edit_packaging", {"expected_revision": 0, "request_id": "edit-1",
        "design": proposed["data"]["candidates"][0]["design"]})
    assert changed["ok"]
    checked = await gateway.call("validate_packaging", {"expected_revision": 1})
    assert checked["ok"]


def test_real_solver_save_validation_receipts_and_terminal_reference(setup, monkeypatch):
    async def runtime(**kw):
        assert kw["api_key"] == "test-key"
        assert "TEST packing" not in kw["message"]  # Geometry is read via tools, not copied into the prompt.
        assert kw["effort"] == "medium"
        await arrange(kw["gateway"])
        kw["gateway"].closed = True
        return "Packed six; weight still needed.", SimpleNamespace(timeline=[])
    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    result = asyncio.run(execute(setup))
    evidence = result["codex_packaging"]
    assert evidence["revision"] == 1 and evidence["mutationOutcome"] == "committed"
    assert evidence["checkedPackaging"] and evidence["apiFallback"] is False
    assert len(result["tool_receipts"]) == 1
    assert result["tool_receipts"][0]["resultingRevisionVector"] == {"packagingRevision": "1"}
    saved = setup.service.get(setup.scope, setup.doc["id"])
    assert sum(len(p["placements"]) for p in saved["design"]["packages"]) == 6
    assert saved["design"]["product"]["mass_kg"] is None
    assert setup.admission.reference(setup.principal, setup.editor["admission_id"])["revision"] == 1
    with pytest.raises(PilotError, match="already"):
        asyncio.run(execute(setup))


def test_stale_document_stops_before_credentials(setup, monkeypatch):
    async def forbidden(*args):
        pytest.fail("Credentials must not be loaded for invalid admission")
    monkeypatch.setattr(pilot, "prepare_credentials", forbidden)
    setup.service.change(setup.scope, setup.doc["id"], Edit(expected_revision=0, request_id="manual",
        design=Design.model_validate(setup.doc["design"])))
    with pytest.raises(PilotError):
        asyncio.run(execute(setup))


def test_partial_failure_preserves_commit_evidence_and_undo(setup, monkeypatch):
    async def runtime(**kw):
        await arrange(kw["gateway"])
        raise PilotError("codex_runtime_failed", "The model stopped.")
    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    with pytest.raises(PilotError) as caught:
        asyncio.run(execute(setup))
    assert caught.value.packaging_result["mutationOutcome"] == "committed"
    assert caught.value.packaging_result["revision"] == 1
    assert "edits may remain" in str(caught.value)
    assert setup.service.get(setup.scope, setup.doc["id"])["can_undo"]


def test_revoke_cancels_and_drains_runtime(setup, monkeypatch):
    events = []
    async def runtime(**kw):
        try:
            setup.admission.revoke(setup.principal, setup.editor["admission_id"],
                {"selection_id": setup.editor["selection_id"]})
            await asyncio.sleep(10)
        finally:
            events.append("closed")
    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    async def test():
        with pytest.raises(PilotError):
            await asyncio.wait_for(execute(setup), 3)
    asyncio.run(test())
    assert events == ["closed"]
    assert setup.service.get(setup.scope, setup.doc["id"])["revision"] == 0


def test_cancel_after_commit_does_not_claim_no_changes(setup, monkeypatch):
    async def runtime(**kw):
        await arrange(kw["gateway"])
        raise asyncio.CancelledError()
    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(execute(setup))
    assert setup.service.get(setup.scope, setup.doc["id"])["revision"] == 1
    with pilot.Journal(setup.settings.root).db() as db:
        row = db.execute("SELECT status,result FROM turns").fetchone()
    assert row[0] == "interrupted" and '"mutationOutcome": "committed"' in row[1]


def test_runtime_without_inspection_is_not_verified(setup, monkeypatch):
    async def runtime(**kw):
        return "Done", SimpleNamespace(timeline=[])
    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    with pytest.raises(PilotError) as caught:
        asyncio.run(execute(setup))
    assert caught.value.code == "codex_packaging_unverified"


def test_readonly_host_grant_excludes_writes(setup, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_EDIT_PREVIEWS", "0")
    async def runtime(**kw):
        assert len(kw["gateway"].specs) == 5
        assert (await kw["gateway"].call("inspect_packaging", {"expected_revision": 0}))["ok"]
        return "Missing mass", SimpleNamespace(timeline=[])
    monkeypatch.setattr(pilot, "run_gateway_turn", runtime)
    assert asyncio.run(execute(setup))["codex_packaging"]["mutationOutcome"] == "not_started"


@pytest.mark.parametrize("field,value", [("conversation_id", None), ("client_turn_id", "../other")])
def test_invalid_turn_identity_rejected(setup, field, value):
    setattr(setup.request, field, value)
    with pytest.raises(PilotError) as caught:
        asyncio.run(execute(setup))
    assert caught.value.code == "codex_identity_required"


def test_packaging_memory_scope_and_revision_barrier():
    from ai_inspector.memory.policy import _normalize_asset_scope
    from ai_inspector.memory.turn_lifecycle import evaluate_revision_barrier
    scope = {"kind": "packaging_shipping", "ids": {"documentId": "pkg_test"},
             "expectedRevisionVector": {"packagingRevision": "0"}}
    assert _normalize_asset_scope(scope) == scope
    with pytest.raises(ValueError):
        _normalize_asset_scope({**scope, "ids": {"layoutId": "layout"}})
    barrier = evaluate_revision_barrier(classification="action_write",
        source_revision_vector={"packagingRevision": "0"}, pre_effect_revision_vector={"packagingRevision": "0"},
        current_revision_vector={"packagingRevision": "1"},
        receipts=[{"casOutcome": "applied", "resultingRevisionVector": {"packagingRevision": "1"}}])
    assert barrier["terminalStatus"] == "committed" and not barrier["postEffectRevisionDrift"]
