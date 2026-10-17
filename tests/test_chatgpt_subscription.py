import json
from pathlib import Path
import threading
import time

import httpx
import pytest
from cryptography.fernet import Fernet

from ai_inspector.codex_runtime.chatgpt_accounts import (
    AccountStore, accept_login, public_status, subscription_credential, sign_out,
    AUTH_MODE, SUBSCRIPTION_FLAG,
)
from ai_inspector.codex_runtime.chatgpt_protocol import DIRECT_SCOPE, ProtocolError
from ai_inspector.codex_runtime.policy import PilotError, child_environment, runtime_config, live_allowed
from ai_inspector.codex_runtime.app_server import failure_diagnostic, turn_failure
from tools.connect_chatgpt_account import AccountWindow

MODEL = "gpt-6.1-sol"


@pytest.mark.parametrize("provider_code,expected", [
    ("subscription_sharing_usage_limit_exceeded", "codex_subscription_usage_limit"),
    ("invalid_token", "chatgpt_sign_in_required"),
    ("unknown", "codex_turn_incomplete"),
])
def test_plan_failures_are_actionable_without_exposing_provider_body(provider_code, expected):
    error = {"message": json.dumps({"error": {"code": provider_code, "message": "private-token"}})}
    failure = turn_failure(error, {"INSPECTORPRO_CHATGPT_ACCESS_TOKEN": "private-token"})
    assert failure.code == expected and "fallback" in str(failure)
    assert "private-token" not in str(failure) + json.dumps(failure.diagnostic)


@pytest.fixture
def store(tmp_path):
    codec = Fernet(Fernet.generate_key())
    return AccountStore(tmp_path, "test-profile", protect=codec.encrypt, unprotect=codec.decrypt)


def login(store, identifier="one", *, lifetime=3600):
    accept_login(store, identifier, {"clientId": "oaiapp_" + identifier, "hostId": "urn:uuid:host"},
        {"access_token": "private-access-" + identifier, "refresh_token": "private-refresh-" + identifier,
         "id_token": "private-id-" + identifier, "scope": DIRECT_SCOPE, "token_type": "Bearer", "expires_in": lifetime},
        {"sub": "subject-" + identifier, "email": "test@example.invalid"}, [{"slug": MODEL, "displayName": "Test Model"}])


def test_credentials_are_encrypted_and_public_status_is_safe(store):
    login(store)
    status = public_status(store)
    assert status["signedIn"] and status["apiFallback"] is False
    assert "private-" not in json.dumps(status)
    assert b"private-" not in store.path.read_bytes()
    credential = subscription_credential(MODEL, store=store)
    assert credential.access_token == "private-access-one"
    assert "private-access" not in repr(credential)
    credential.check()


def test_account_switch_invalidates_active_turn_and_keeps_registrations(store):
    login(store)
    credential = subscription_credential(MODEL, store=store)
    login(store, "two")
    assert len(public_status(store)["accounts"]) == 2
    with pytest.raises(PilotError, match="account changed"):
        credential.check()
    other = subscription_credential(MODEL, store=store)
    assert credential.binding != other.binding


def test_refresh_is_serialized_and_rotated_token_persists(store):
    login(store, lifetime=1)
    seen = []
    def transport(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/token"):
            time.sleep(0.05)
            assert b"private-refresh-one" in request.content
            return httpx.Response(200, json={"access_token": "fresh-access", "refresh_token": "fresh-refresh",
                                            "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(200, json={"models": [{"slug": MODEL, "visibility": "list"}]})
    results, failures = [], []
    def obtain():
        try:
            results.append(subscription_credential(MODEL, store=store,
                client_factory=lambda: httpx.Client(transport=httpx.MockTransport(transport))).access_token)
        except Exception as exc:
            failures.append(type(exc).__name__)
    threads = [threading.Thread(target=obtain) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not failures and results == ["fresh-access", "fresh-access"]
    assert seen.count("/api/accounts/oauth/token") == 1
    assert store.read()["accounts"]["one"]["refreshToken"] == "fresh-refresh"


def test_refresh_failure_does_not_fall_back_to_api(store, monkeypatch):
    login(store, lifetime=1)
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "must-not-use")
    with pytest.raises(PilotError) as error:
        subscription_credential(MODEL, store=store, client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"error": "invalid_grant"}))))
    assert error.value.code == "chatgpt_sign_in_required"
    assert not public_status(store)["signedIn"]
    assert "must-not-use" not in store.path.read_bytes().decode(errors="ignore")


def test_missing_account_and_unlisted_model_fail_closed(store):
    with pytest.raises(PilotError) as error:
        subscription_credential(MODEL, store=store)
    assert error.value.code == "chatgpt_sign_in_required"
    login(store)
    with pytest.raises(PilotError) as error:
        subscription_credential("unlisted", store=store)
    assert error.value.code == "chatgpt_model_unavailable"


def test_sign_out_clears_tokens_and_retains_registration(store):
    login(store)
    credential = subscription_credential(MODEL, store=store)
    seen = []
    def transport(request):
        seen.append(request)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"revocation_endpoint": "https://auth.openai.com/api/accounts/oauth/revoke"})
        assert b"private-refresh-one" in request.content
        return httpx.Response(200)
    assert sign_out(store, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(transport)))
    account = store.read()["accounts"]["one"]
    assert account["clientId"] == "oaiapp_one"
    assert not any(name in account for name in ("accessToken", "refreshToken", "idToken"))
    assert len(seen) == 2
    with pytest.raises(PilotError):
        credential.check()


def test_registration_identity_cannot_be_overwritten(store):
    login(store)
    with pytest.raises(ProtocolError):
        accept_login(store, "one", {"clientId": "oaiapp_wrong", "hostId": "host"},
            {"access_token": "new", "refresh_token": "new", "id_token": "new", "scope": DIRECT_SCOPE,
             "token_type": "Bearer", "expires_in": 3600}, {"sub": "wrong"}, [{"slug": MODEL}])
    assert subscription_credential(MODEL, store=store).access_token == "private-access-one"


def test_subscription_runtime_has_no_api_key_or_native_web_access(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    env = child_environment(tmp_path, "mcp-capability", access_token="subscription-token")
    assert env["INSPECTORPRO_CHATGPT_ACCESS_TOKEN"] == "subscription-token"
    assert "OPENAI_API_KEY" not in env and "INSPECTORPRO_CODEX_API_KEY" not in env
    with pytest.raises(PilotError):
        child_environment(tmp_path, "mcp", api_key="key", access_token="token")
    config = runtime_config("http://127.0.0.1:8888/mcp", MODEL, auth_mode="chatgpt_plan")
    provider = config["model_providers"]["inspectorpro"]
    assert provider["env_key"] == "INSPECTORPRO_CHATGPT_ACCESS_TOKEN"
    assert provider["base_url"] == "https://api.openai.com/v1"
    assert provider["supports_websockets"] is False
    assert config["web_search"] == "disabled"
    assert not any(config["features"].values())
    redacted = failure_diagnostic({"message": "failed subscription-token"}, env)
    assert "subscription-token" not in json.dumps(redacted)


def test_subscription_and_paid_gates_are_independent(monkeypatch):
    monkeypatch.setenv(AUTH_MODE, "chatgpt_plan")
    monkeypatch.setenv("INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE", "1")
    monkeypatch.delenv(SUBSCRIPTION_FLAG, raising=False)
    assert not live_allowed()
    monkeypatch.setenv(SUBSCRIPTION_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE", "0")
    assert live_allowed()


def test_account_window_never_renders_saved_tokens_and_rejects_bad_callback(store):
    login(store)
    window = AccountWindow(store)
    window.origin = "http://127.0.0.1:12345"
    assert b"private-" not in window.page()
    location = window.start("one")
    assert location.startswith("https://auth.openai.com/api/accounts/authorize?")
    assert "client_id=oaiapp_one" in location
    assert "agent_name_hint" not in location
    with pytest.raises(ProtocolError):
        window.callback({"state": ["wrong"], "code": ["code"]})
    assert window.pending is not None
    assert public_status(store)["signedIn"]


def test_oauth_denial_allows_retry_without_losing_existing_account(store):
    login(store)
    window = AccountWindow(store)
    window.origin = "http://127.0.0.1:12345"
    window.start("one")
    with pytest.raises(ProtocolError):
        window.callback({"state": [window.pending["state"]], "error": ["access_denied"]})
    assert window.pending is None
    assert public_status(store)["signedIn"]
    assert window.start("one")


def test_windows_dpapi_roundtrip_contains_no_plaintext(tmp_path):
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows DPAPI integration")
    store = AccountStore(tmp_path, "dpapi-test")
    login(store)
    assert b"private-access" not in store.path.read_bytes()
    assert subscription_credential(MODEL, store=AccountStore(tmp_path, "dpapi-test")).access_token == "private-access-one"


def test_subscription_blocks_legacy_sage_before_memory_or_provider(monkeypatch):
    import ast
    from types import SimpleNamespace
    from fastapi import HTTPException
    source = Path("server.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    namespace = {"HTTPException": HTTPException, "_chat_stream_active_mode": lambda request: request.mode}
    exec(compile(ast.Module(body=[functions["_require_subscription_chat_route"]], type_ignores=[]), "route", "exec"), namespace)
    guard = namespace["_require_subscription_chat_route"]
    monkeypatch.setenv(AUTH_MODE, "chatgpt_plan")
    monkeypatch.setenv("INSPECTORPRO_CODEX_READONLY_PILOT", "1")
    guard(SimpleNamespace(agent_type="deviation-analyst", mode="facility_layout"))
    for agent, mode in [("deviation-analyst", "assembly"), ("inspector", "facility_layout")]:
        with pytest.raises(HTTPException):
            guard(SimpleNamespace(agent_type=agent, mode=mode))
    for name in ("agent_chat", "_execute_agent_chat_with_memory"):
        segment = ast.get_source_segment(source, functions[name])
        assert "_require_subscription_chat_route(" in segment
    summary = ast.get_source_segment(source, functions["agent_summarize"])
    assert summary.index("subscription_mode()") < summary.index("import anthropic")
