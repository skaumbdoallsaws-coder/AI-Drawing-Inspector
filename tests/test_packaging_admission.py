"""Host admission over real SQLite/gateway, without network or running apps."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
import asyncio
import re
import socket

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from ai_inspector.codex_runtime.packaging_tools import create_packaging_gateway
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.admission import (
    EditorHeartbeat, EditorRevoke, EditorState, PackagingAdmission, packaging_scope,
)
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.models import Design, Edit
from ai_inspector.packaging_shipping.rating import EasyPostRating
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService


@pytest.fixture
def env(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Admission tests must not access network or carrier billing")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    service = PackagingService(tmp_path / "admission-store")
    monkeypatch.setattr(service, "save_quotes", forbidden)
    principal = FacilityPrincipal("engineer", "tenant", ("site",), ("editor",))
    scope = packaging_scope(principal)
    saved = service.create(scope, Design(name="First document"))
    other = service.create(scope, Design(name="Second document"))
    clock = [100.0]
    registry = PackagingAdmission(service, clock=lambda: clock[0])
    return SimpleNamespace(service=service, principal=principal, current=[principal], scope=scope,
                           saved=saved, other=other, clock=clock, registry=registry)


def editor_state(env, **changes):
    return {"document_id": env.saved["id"], "revision": 0, "session_id": "session-1",
            "conversation_id": "conversation-1", "active_mode": "packaging_shipping",
            "dirty": False, "conflict": False, "pending_operations": 0, **changes}


def publish(env, **changes):
    return env.registry.publish(env.principal, editor_state(env, **changes))


def begin(env, response, **changes):
    options = dict(session_id="session-1", conversation_id="conversation-1", turn_id="turn-1",
                   direct_edit_authorized=False, principal_resolver=lambda: env.current[0])
    options.update(changes)
    return env.registry.begin(env.principal, response["admission_id"], **options)


def heartbeat(env, response, **changes):
    return env.registry.heartbeat(env.principal, response["admission_id"],
                                  {**editor_state(env), "selection_id": response["selection_id"], **changes})


def gateway(env, turn):
    return create_packaging_gateway(env.service, current_context=turn.current_context,
                                    mutation_guard=turn.mutation_guard, turn_id=turn.turn_id)


def edit_args(name="Edited", revision=0, request_id="edit-1"):
    return {"expected_revision": revision, "request_id": request_id,
            "design": Design(name=name).model_dump(mode="json")}


def call(gw, name="inspect_packaging", args=None):
    return asyncio.run(gw.call(name, {"expected_revision": 0} if args is None else args))


def error(code, action, status=None):
    with pytest.raises(PackagingError) as caught:
        action()
    assert caught.value.code == code
    if status is not None:
        assert caught.value.status == status
    return caught.value


def client(env, *, admission=True, principal=None, sage_enabled=None):
    app = FastAPI()
    app.include_router(create_router(env.service, principal_resolver=lambda _: principal or env.current[0],
                                    static_root=Path(__file__).resolve().parents[1] / "static",
                                    rating=EasyPostRating(key=""), admission=env.registry if admission else None,
                                    sage_enabled=sage_enabled))
    return TestClient(app)


HEADERS = {"X-InspectorPro-Request": "packaging", "Origin": "http://testserver"}


@pytest.mark.parametrize("change", [
    {"revision": True}, {"revision": "0"}, {"revision": .0}, {"revision": -1}, {"revision": 9007199254740992},
    {"dirty": 0}, {"conflict": "false"}, {"pending_operations": False}, {"pending_operations": -1},
    {"pending_operations": 1001}, {"document_id": "../other"}, {"session_id": ""},
    {"conversation_id": "bad scope"}, {"principal": {}}, {"direct_edit_authorized": True}, {"scope": "other"},
])
def test_editor_state_strict_and_closed(env, change):
    with pytest.raises(ValidationError):
        EditorState.model_validate(editor_state(env, **change))


@pytest.mark.parametrize("field", ["dirty", "conflict", "pending_operations", "active_mode", "session_id", "conversation_id"])
def test_editor_state_requires_affirmative_fields(env, field):
    state = editor_state(env)
    del state[field]
    with pytest.raises(ValidationError):
        EditorState.model_validate(state)


def test_publish_response_is_opaque_bounded_and_reference_does_not_renew(env):
    response = publish(env)
    assert set(response) == {"admission_id", "selection_id", "expires_in"}
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", response["admission_id"])
    assert response["expires_in"] == 30
    env.clock[0] += 10
    reference = env.registry.reference(env.principal, response["admission_id"])
    assert reference == {"document_id": env.saved["id"], "revision": 0,
                         "selection_id": response["selection_id"], "session_id": "session-1", "conversation_id": "conversation-1"}
    env.clock[0] += 20
    error("editor_expired", lambda: env.registry.reference(env.principal, response["admission_id"]))


@pytest.mark.parametrize("changes,code", [
    ({"dirty": True}, "editor_not_saved"), ({"conflict": True}, "editor_not_saved"),
    ({"pending_operations": 1}, "editor_not_saved"), ({"active_mode": "facility_layout"}, "editor_not_saved"),
    ({"revision": 1}, "revision_conflict"), ({"document_id": "missing"}, "editor_document_unavailable"),
    ({"extra": "bad"}, "editor_state_invalid"),
])
def test_failed_replacement_invalidates_prior_first(env, changes, code):
    response = publish(env)
    turn = begin(env, response)
    error(code, lambda: publish(env, **changes))
    assert turn.cancel_event.is_set()
    error("editor_revoked", turn.current_context)
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 0


def test_away_and_back_rotates_both_tokens_and_old_turn_never_binds_new_document(env):
    first = publish(env)
    turn = begin(env, first, direct_edit_authorized=True)
    gw = gateway(env, turn)
    second = publish(env, document_id=env.other["id"])
    third = publish(env)
    assert len({first["selection_id"], second["selection_id"], third["selection_id"]}) == 3
    assert len({first["admission_id"], second["admission_id"], third["admission_id"]}) == 3
    result = call(gw, "edit_packaging", edit_args())
    assert result["ok"] is False
    assert result["mutation"]["outcome"] == "not_started"
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 0
    assert env.service.get(env.scope, env.other["id"])["revision"] == 0


@pytest.mark.parametrize("change", [{"principal_id": "other-user"}, {"tenant_id": "other-tenant"}])
def test_admission_is_principal_owned_even_when_scope_would_match(env, change):
    response = publish(env)
    other = replace(env.principal, **change)
    error("editor_not_found", lambda: env.registry.reference(other, response["admission_id"]), 404)
    error("editor_not_found", lambda: env.registry.revoke(other, response["admission_id"], {"selection_id": response["selection_id"]}), 404)
    assert env.registry.reference(env.principal, response["admission_id"])["document_id"] == env.saved["id"]


@pytest.mark.parametrize("change", [{"roles": ("viewer",)}, {"allowed_site_ids": ("other-site",)}, {"principal_id": "other"}])
def test_current_context_rechecks_authorization_and_cancels(env, change):
    response = publish(env)
    turn = begin(env, response)
    env.current[0] = replace(env.principal, **change)
    error("editor_identity_changed", turn.current_context)
    assert turn.cancel_event.is_set()


@pytest.mark.parametrize("field", ["session_id", "conversation_id"])
def test_begin_requires_actual_host_ids_to_match_published_editor(env, field):
    response = publish(env)
    error("editor_identity_changed", lambda: begin(env, response, **{field: "different"}))
    error("editor_revoked", lambda: env.registry.reference(env.principal, response["admission_id"]))


def test_role_scope_and_cross_scope_document_checks(env):
    foreign = env.service.create(packaging_scope(replace(env.principal, tenant_id="other")), Design())
    error("editor_document_unavailable", lambda: publish(env, document_id=foreign["id"]), 404)
    viewer = replace(env.principal, roles=("viewer",))
    response = env.registry.publish(viewer, editor_state(env))
    error("editor_edit_denied", lambda: env.registry.begin(viewer, response["admission_id"],
          session_id="session-1", conversation_id="conversation-1", turn_id="viewer-turn",
          direct_edit_authorized=True, principal_resolver=lambda: viewer), 403)
    with env.registry.begin(viewer, response["admission_id"], session_id="session-1", conversation_id="conversation-1",
                            turn_id="viewer-turn", principal_resolver=lambda: viewer) as turn:
        gw = gateway(env, turn)
        assert len(gw.specs) == 5
        assert call(gw)["ok"] is True
        error("editor_edit_denied", lambda: _enter_guard(turn), 403)


def _enter_guard(turn):
    with turn.mutation_guard():
        pass


def test_expired_admission_cannot_begin_or_heartbeat_and_active_turn_expires(env):
    response = publish(env)
    env.clock[0] += 30
    error("editor_expired", lambda: begin(env, response))
    error("editor_revoked", lambda: heartbeat(env, response))
    response = publish(env)
    turn = begin(env, response)
    env.clock[0] += 31
    error("editor_expired", turn.current_context)
    assert turn.cancel_event.is_set()


def test_heartbeat_renews_only_live_clean_state(env):
    response = publish(env)
    env.clock[0] += 29
    renewed = heartbeat(env, response)
    assert renewed == response
    env.clock[0] += 29
    assert env.registry.reference(env.principal, response["admission_id"])["revision"] == 0
    error("editor_not_saved", lambda: heartbeat(env, response, dirty=True))
    error("editor_revoked", lambda: begin(env, response))


@pytest.mark.parametrize("changes", [
    {"document_id": "another"}, {"selection_id": "s_" + "0" * 43},
    {"session_id": "another"}, {"conversation_id": "another"},
])
def test_heartbeat_cannot_transition_or_rebind(env, changes):
    response = publish(env)
    turn = begin(env, response)
    error("editor_selection_changed", lambda: heartbeat(env, response, **changes))
    assert turn.cancel_event.is_set()


def test_gateway_owned_revisions_are_not_inferred_editor_acknowledgements(env):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    gw = gateway(env, turn)
    args = edit_args()
    result = call(gw, "edit_packaging", args)
    assert result["ok"] is True, result
    assert result["data"]["document"]["revision"] == 1
    assert turn.current_context().revision == 0
    assert env.registry.reference(env.principal, response["admission_id"])["revision"] == 1
    replay = call(gw, "edit_packaging", args)
    assert replay["ok"] is True and replay["data"]["replayed"] is True
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 1
    heartbeat(env, response)
    assert turn.current_context().revision == 0
    heartbeat(env, response, revision=1)
    assert turn.current_context().revision == 1
    result = call(gw, "undo_packaging", {"expected_revision": 1, "request_id": "undo-1"})
    assert result["ok"] is True, result
    assert turn.current_context().revision == 1
    assert env.registry.reference(env.principal, response["admission_id"])["revision"] == 2
    error("revision_conflict", lambda: heartbeat(env, response, revision=0))
    assert turn.cancel_event.is_set()


@pytest.mark.parametrize("operation", ["context", "reference", "heartbeat"])
def test_external_revision_cannot_be_laundered_by_a_heartbeat(env, operation):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    env.service.change(env.scope, env.saved["id"], Edit.model_validate(edit_args("Manual edit")))
    actions = {"context": turn.current_context, "reference": lambda: env.registry.reference(env.principal, response["admission_id"]),
               "heartbeat": lambda: heartbeat(env, response, revision=1)}
    error("revision_conflict", actions[operation])
    assert turn.cancel_event.is_set()


def test_one_active_turn_and_finished_admission_cannot_be_reused(env):
    response = publish(env)
    with begin(env, response) as turn:
        error("editor_turn_active", lambda: begin(env, response, turn_id="turn-2"))
        assert turn.current_context().document_id == env.saved["id"]
    turn.close()
    error("editor_revoked", turn.current_context)
    error("editor_revoked", lambda: begin(env, response, turn_id="turn-3"))
    fresh = publish(env, document_id=env.other["id"])
    error("editor_turn_replayed", lambda: begin(env, fresh))
    with begin(env, fresh, turn_id="turn-4") as other:
        assert other.document_id == env.other["id"]


def test_context_manager_releases_on_exception_and_external_cancel_event_is_honored(env):
    response = publish(env)
    with pytest.raises(RuntimeError):
        with begin(env, response) as turn:
            raise RuntimeError("application failed")
    assert turn.cancel_event.is_set()
    fresh = publish(env)
    cancelled = Event()
    handle = begin(env, fresh, turn_id="next-turn", cancel_event=cancelled)
    cancelled.set()
    error("editor_turn_cancelled", handle.current_context)


def test_revoke_is_idempotent_and_cancel_prevents_mutations(env):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    gw = gateway(env, turn)
    body = {"selection_id": response["selection_id"]}
    for _ in range(2):
        assert env.registry.revoke(env.principal, response["admission_id"], body)["expires_in"] == 0
    result = call(gw, "edit_packaging", edit_args())
    assert result["ok"] is False and result["mutation"]["outcome"] == "not_started"
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 0


def test_principal_callback_failure_is_sanitized_and_fails_closed(env):
    response = publish(env)
    def unavailable():
        raise RuntimeError("private-token C:/private/database.sqlite3")
    failure = error("editor_identity_changed", lambda: begin(env, response, principal_resolver=unavailable))
    assert "private" not in failure.message
    error("editor_revoked", lambda: env.registry.reference(env.principal, response["admission_id"]))


def test_two_concurrent_begins_admit_only_one(env):
    response = publish(env)
    barrier = Barrier(2)
    def attempt(index):
        barrier.wait(timeout=3)
        try:
            return begin(env, response, turn_id=f"turn-{index}")
        except PackagingError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))
    assert sum(result == "editor_turn_active" for result in results) == 1
    for result in results:
        if result != "editor_turn_active":
            result.close()


def test_transition_waits_for_actual_gateway_commit_and_receipt_stays_on_old_document(env, monkeypatch):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    gw = gateway(env, turn)
    entered, release, transition_started = Event(), Event(), Event()
    original = env.service.change
    def blocking_change(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(env.service, "change", blocking_change)
    def transition():
        transition_started.set()
        return publish(env, document_id=env.other["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(call, gw, "edit_packaging", edit_args())
        assert entered.wait(3)
        switch = pool.submit(transition)
        try:
            assert transition_started.wait(3)
            assert not switch.done()
        finally:
            release.set()
        result, replacement = work.result(timeout=5), switch.result(timeout=5)
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 1
    assert env.service.get(env.scope, env.other["id"])["revision"] == 0
    assert any(r["mutation"] and r["mutation"]["outcome"] == "committed" for r in gw.receipts), result
    assert env.registry.reference(env.principal, replacement["admission_id"])["document_id"] == env.other["id"]
    denied = call(gw, "edit_packaging", edit_args("Wrong document replay"))
    assert denied["ok"] is False
    assert env.service.get(env.scope, env.other["id"])["revision"] == 0


def test_transition_before_guard_prevents_the_old_write(env):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    gw = gateway(env, turn)
    publish(env, document_id=env.other["id"])
    result = call(gw, "edit_packaging", edit_args())
    assert result["ok"] is False
    assert result["mutation"]["outcome"] == "not_started"
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 0


def test_real_rlock_is_reentrant_and_contended_acquisition_is_bounded(env):
    env.registry = PackagingAdmission(env.service, lock_timeout=.05, clock=lambda: env.clock[0])
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    entered, release = Event(), Event()
    def hold():
        with turn.mutation_guard():
            assert turn.current_context().revision == 0
            entered.set()
            assert release.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(hold)
        try:
            assert entered.wait(3)
            error("editor_busy", lambda: publish(env, document_id=env.other["id"]))
            error("editor_busy", turn.cancel)
            assert turn.cancel_event.is_set()
        finally:
            release.set()
        with pytest.raises(PackagingError):
            work.result(timeout=3)
    error("editor_revoked", turn.current_context)


def test_lost_mutation_response_preserves_unknown_receipt_and_blocks_fresh_context(env, monkeypatch):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    gw = gateway(env, turn)
    original = env.service.change
    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("lost response containing private data")
    monkeypatch.setattr(env.service, "change", lost_response)
    result = call(gw, "edit_packaging", edit_args())
    assert result["ok"] is False and result["mutation"]["outcome"] == "unknown"
    assert env.service.get(env.scope, env.saved["id"])["revision"] == 1
    error("editor_revoked", turn.current_context)
    assert "private" not in str(result)


def test_old_durable_receipt_cannot_be_replayed_in_a_new_document_admission(env):
    old = publish(env)
    turn = begin(env, old, direct_edit_authorized=True)
    gw = gateway(env, turn)
    assert call(gw, "edit_packaging", edit_args())["ok"] is True
    new = publish(env, document_id=env.other["id"])
    error("editor_turn_replayed", lambda: begin(env, new))
    assert call(gw, "edit_packaging", edit_args())["ok"] is False
    with begin(env, new, turn_id="new-turn", direct_edit_authorized=True) as admitted:
        new_gateway = gateway(env, admitted)
        wrong = {**edit_args(), "document_id": env.saved["id"]}
        assert call(new_gateway, "edit_packaging", wrong)["ok"] is False
    assert env.service.get(env.scope, env.other["id"])["revision"] == 0


def test_capacity_does_not_evict_active_admissions_or_reenable_consumed_turns(env):
    env.registry = PackagingAdmission(env.service, max_editors=1, max_turns=1, clock=lambda: env.clock[0])
    response = publish(env)
    other = replace(env.principal, principal_id="second-user")
    error("editor_capacity", lambda: env.registry.publish(other, editor_state(env)), 503)
    begin(env, response).close()
    new = publish(env)
    error("editor_turn_replayed", lambda: begin(env, new))
    error("editor_capacity", lambda: begin(env, new, turn_id="another"), 503)


def test_optional_router_endpoints_and_read_only_principal_are_backwards_compatible(env):
    with client(env, admission=False) as http:
        assert http.post("/api/packaging/editor", json=editor_state(env), headers=HEADERS).status_code == 404
        assert http.get("/api/packaging/documents").status_code == 200
    viewer = replace(env.principal, roles=("viewer",))
    with client(env, principal=viewer) as http:
        response = http.post("/api/packaging/editor", json=editor_state(env), headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        result = response.json()
        assert set(result) == {"admission_id", "selection_id", "expires_in"}
        body = {**editor_state(env), "selection_id": result["selection_id"]}
        assert http.post(f'/api/packaging/editor/{result["admission_id"]}/heartbeat', json=body, headers=HEADERS).status_code == 200
        assert http.put(f'/api/packaging/documents/{env.saved["id"]}', json=edit_args(), headers=HEADERS).status_code == 403
        revoked = http.post(f'/api/packaging/editor/{result["admission_id"]}/revoke', json={"selection_id": result["selection_id"]}, headers=HEADERS)
        assert revoked.status_code == 200
        denied = http.post(f'/api/packaging/editor/{result["admission_id"]}/heartbeat', json=body, headers=HEADERS)
        assert denied.status_code == 409 and denied.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("headers", [{}, {"X-InspectorPro-Request": "wrong"},
    {**HEADERS, "Origin": "https://evil.example"}, {**HEADERS, "Host": "evil.example"}])
def test_editor_api_rejects_missing_marker_cross_origin_and_wrong_host(env, headers):
    with client(env) as http:
        assert http.post("/api/packaging/editor", json=editor_state(env), headers=headers).status_code == 403


@pytest.mark.parametrize("extra", [{"direct_edit_authorized": True}, {"principal": "admin"}, {"scope": "other"}, {"turn_id": "injected"}])
def test_editor_api_never_accepts_renderer_authority(env, extra):
    with client(env) as http:
        rejected = http.post("/api/packaging/editor", json=editor_state(env, **extra), headers=HEADERS)
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "editor_state_invalid"


def test_api_manual_edit_keeps_revision_cas_and_invalidates_admission_on_next_check(env):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    with client(env) as http:
        path = f'/api/packaging/documents/{env.saved["id"]}'
        assert http.put(path, json=edit_args("Manual change"), headers=HEADERS).status_code == 200
        stale = http.put(path, json=edit_args("Stale", request_id="another"), headers=HEADERS)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    error("revision_conflict", turn.current_context)


def test_router_requires_the_exact_same_service_for_admission(env, tmp_path):
    other = PackagingService(tmp_path / "different-store")
    with pytest.raises(ValueError, match="service instance"):
        create_router(other, principal_resolver=lambda _: env.principal, static_root=tmp_path, admission=env.registry)


@pytest.mark.parametrize("kwargs", [{"lock_timeout": 0}, {"lock_timeout": 11}, {"ttl_seconds": float("inf")},
    {"ttl_seconds": True}, {"max_editors": 0}, {"max_turns": False}])
def test_invalid_registry_limits_are_rejected(env, kwargs):
    with pytest.raises(ValueError):
        PackagingAdmission(env.service, **kwargs)


def test_heartbeat_and_revoke_schemas_are_closed_and_tokens_are_bounded(env):
    response = publish(env)
    EditorHeartbeat.model_validate({**editor_state(env), "selection_id": response["selection_id"]})
    with pytest.raises(ValidationError):
        EditorHeartbeat.model_validate({**editor_state(env), "selection_id": "short"})
    with pytest.raises(ValidationError):
        EditorRevoke.model_validate({"selection_id": response["selection_id"], "cancel_other_principal": True})


def test_completed_turn_preserves_only_terminal_reference_without_ack_or_renewal(env):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    gw = gateway(env, turn)
    assert call(gw, "edit_packaging", edit_args())["ok"] is True
    env.clock[0] += 15
    turn.finish(keep_reference=True)
    turn.close()
    assert not turn.cancel_event.is_set()
    reference = env.registry.reference(env.principal, response["admission_id"])
    assert reference["revision"] == 1
    assert turn._editor.revision == 0
    error("editor_turn_finished", turn.current_context)
    error("editor_turn_finished", lambda: _enter_guard(turn))
    error("editor_turn_active", lambda: begin(env, response, turn_id="another"))
    error("editor_turn_finished", lambda: heartbeat(env, response, revision=1))
    assert not turn.cancel_event.is_set()
    assert env.registry.reference(env.principal, response["admission_id"])["revision"] == 1
    env.clock[0] += 15
    error("editor_expired", lambda: env.registry.reference(env.principal, response["admission_id"]))


@pytest.mark.parametrize("transition", ["cancel", "revoke", "publish", "external_write", "identity"])
def test_terminal_binding_fails_after_lifecycle_or_authority_change(env, transition):
    response = publish(env)
    turn = begin(env, response)
    turn.finish(keep_reference=True)
    if transition == "cancel":
        turn.cancel()
    elif transition == "revoke":
        env.registry.revoke(env.principal, response["admission_id"], {"selection_id": response["selection_id"]})
    elif transition == "publish":
        publish(env, document_id=env.other["id"])
    elif transition == "external_write":
        env.service.change(env.scope, env.saved["id"], Edit.model_validate(edit_args()))
    else:
        env.current[0] = replace(env.principal, roles=("viewer",))
    with pytest.raises(PackagingError):
        env.registry.reference(env.principal, response["admission_id"])
    assert turn.cancel_event.is_set()


def test_cancelled_or_failed_turn_cannot_request_a_terminal_reference(env):
    response = publish(env)
    turn = begin(env, response)
    turn.cancel_event.set()
    error("editor_turn_cancelled", lambda: turn.finish(keep_reference=True))
    error("editor_revoked", lambda: env.registry.reference(env.principal, response["admission_id"]))
    response = publish(env)
    with pytest.raises(RuntimeError):
        with begin(env, response, turn_id="second") as turn:
            turn.finish(keep_reference=True)
            raise RuntimeError("Failed terminal delivery")
    error("editor_revoked", lambda: env.registry.reference(env.principal, response["admission_id"]))


def test_current_host_flag_controls_sage_status_only_with_admission(env):
    flag = [False]
    with client(env, sage_enabled=lambda: flag[0]) as http:
        assert "sage_chat_execution" in http.get("/api/packaging/status").json()["unsupported"]
        flag[0] = True
        live = http.get("/api/packaging/status").json()
        assert "sage_chat_execution" in live["capabilities"]
        assert "sage_chat_execution" not in live["unsupported"]
        flag[0] = False
        assert "sage_chat_execution" not in http.get("/api/packaging/status").json()["capabilities"]
    with client(env, admission=False, sage_enabled=lambda: True) as http:
        assert "sage_chat_execution" in http.get("/api/packaging/status").json()["unsupported"]
    with client(env) as http:
        assert "sage_chat_execution" in http.get("/api/packaging/status").json()["unsupported"]


def test_status_callback_failure_does_not_disclose_host_details(env):
    def unavailable():
        raise RuntimeError("private environment details")
    with client(env, sage_enabled=unavailable) as http:
        response = http.get("/api/packaging/status")
        assert response.status_code == 200 and "private" not in response.text
        assert "sage_chat_execution" in response.json()["unsupported"]


def test_host_identity_transition_uses_the_same_mutation_lease(env):
    response = publish(env)
    turn = begin(env, response, direct_edit_authorized=True)
    entered, release, attempted = Event(), Event(), Event()
    def mutation():
        with turn.mutation_guard():
            entered.set()
            assert release.wait(3)
            assert turn.current_context().principal == env.principal
    def role_change():
        attempted.set()
        with env.registry.transition_guard():
            env.current[0] = replace(env.principal, roles=("viewer",))
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(mutation)
        assert entered.wait(3)
        transition = pool.submit(role_change)
        try:
            assert attempted.wait(3)
            assert not transition.done()
        finally:
            release.set()
        work.result(timeout=3)
        transition.result(timeout=3)
    error("editor_identity_changed", turn.current_context)
