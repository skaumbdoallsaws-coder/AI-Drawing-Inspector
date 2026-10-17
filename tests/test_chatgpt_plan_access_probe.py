import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from tools.check_chatgpt_plan_access import (
    AUTH, DIRECT_SCOPE, EXPECTED, Probe, ProbeError, provider_json,
    select_model, stream_check, validate_callback, verify_identity,
)


def test_callback_requires_state_and_issued_client():
    query = {"state": ["good"], "code": ["temporary"], "client_id": ["oaiapp_probe"]}
    assert validate_callback(query, "good", None) == ("temporary", "oaiapp_probe")
    with pytest.raises(ProbeError, match="oauth_state_mismatch"):
        validate_callback(query, "bad", None)
    with pytest.raises(ProbeError, match="oauth_client_mismatch"):
        validate_callback(query, "good", "oaiapp_other")
    query["state"].append("duplicate")
    with pytest.raises(ProbeError, match="invalid_callback"):
        validate_callback(query, "good", None)


def test_denial_never_treated_as_login():
    with pytest.raises(ProbeError, match="oauth_access_denied"):
        validate_callback({"state": ["good"], "error": ["access_denied"]}, "good", None)


def test_registration_metadata_and_real_app_name(tmp_path):
    probe = Probe(tmp_path, "gpt-5.5")
    probe.origin = "http://127.0.0.1:12345"
    query = parse_qs(urlsplit(probe.auth_url()).query)
    assert query["agent_name_hint"] == ["InspectorPro"]
    assert query["client_id"] == ["dynamic_agent_client"]
    assert query["redirect_uri"] == [probe.origin + "/auth/callback"]
    assert DIRECT_SCOPE in query["scope"][0]
    assert query["code_challenge_method"] == ["S256"]
    saved = json.loads((tmp_path / "registration.json").read_text())
    assert set(saved) == {"hostId"}
    assert Probe(tmp_path, "gpt-5.5").registration == saved
    probe.registration["clientId"] = "oaiapp_saved"
    query = parse_qs(urlsplit(probe.auth_url()).query)
    assert query["client_id"] == ["oaiapp_saved"]
    assert "agent_name_hint" not in query


def test_provider_diagnostics_do_not_echo_body():
    response = httpx.Response(403, json={"error": {"code": "subscription_sharing_user_not_eligible",
                                                  "message": "secret details"}})
    with pytest.raises(ProbeError) as error:
        provider_json(response)
    assert error.value.code == "subscription_sharing_user_not_eligible"
    assert error.value.status == 403
    assert "secret" not in str(error.value)


def test_models_follow_visible_server_catalog():
    payload = {"models": [{"slug": "hidden", "visibility": "hidden"},
                          {"slug": "gpt-5.5", "visibility": "list"}]}
    assert select_model(payload, "gpt-5.5") == ("gpt-5.5", 1)
    assert select_model(payload, "unavailable") == ("gpt-5.5", 1)
    with pytest.raises(ProbeError, match="no_visible_models"):
        select_model({"models": []}, "gpt-5.5")


def test_one_subscription_request_no_key_fallback():
    seen = []

    def transport(request):
        seen.append(request)
        body = json.loads(request.content)
        assert body["stream"] is True and body["store"] is False
        assert "max_output_tokens" not in body and "max_tool_calls" not in body
        assert body["input"][0]["content"] == "Reply with exactly: " + EXPECTED
        assert request.headers["Authorization"] == "Bearer temporary-oauth-token"
        event = {"type": "response.completed", "response": {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": EXPECTED}]}]}}
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        assert stream_check(client, "temporary-oauth-token", "gpt-5.5")["answer"] == EXPECTED
    assert len(seen) == 1


@pytest.mark.parametrize("event", ["response.failed", "response.incomplete", "error"])
def test_stream_rejects_failures(event):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, text="data: " + json.dumps({"type": event}) + "\n\n"))) as client:
        with pytest.raises(ProbeError):
            stream_check(client, "temporary", "gpt-5.5")


def test_empty_stream_is_not_success():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=""))) as client:
        with pytest.raises(ProbeError, match="incomplete_stream"):
            stream_check(client, "temporary", "gpt-5.5")


def check_events(events):
    stream = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=stream))) as client:
        return stream_check(client, "temporary", "gpt-5.5")


def completed_event(output=None, status="completed"):
    return {"type": "response.completed", "response": {"status": status, "output": output or []}}


@pytest.mark.parametrize("include_done", [False, True])
def test_streamed_text_with_empty_completion_snapshot(include_done):
    events = [{"type": "response.output_text.delta", "output_index": 1, "content_index": 0, "delta": text}
              for text in [EXPECTED[:12], EXPECTED[12:]]]
    if include_done:
        events.append({"type": "response.output_text.done", "output_index": 1, "content_index": 0, "text": EXPECTED})
    result = check_events(events + [completed_event()])
    assert result["answer"] == EXPECTED
    assert result["inferenceCompleted"] and result["expectedReplyMatched"]
    assert result["responseTextSource"] == "streamed_text"
    assert result["responseTextCharacters"] == len(EXPECTED)
    assert result["textDeltaCount"] == 2


def test_stream_parts_follow_indices_without_duplicate_done_text():
    result = check_events([
        {"type": "response.output_text.done", "output_index": 1, "content_index": 1, "text": EXPECTED[12:]},
        {"type": "response.output_text.delta", "output_index": 1, "content_index": 0, "delta": EXPECTED[:12]},
        {"type": "response.output_text.done", "output_index": 1, "content_index": 0, "text": EXPECTED[:12]},
        completed_event(),
    ])
    assert result["answer"] == EXPECTED


@pytest.mark.parametrize("ending", [[], [{"type": "response.failed"}],
                                    [completed_event(status="incomplete")]])
def test_streamed_phrase_alone_cannot_pass(ending):
    with pytest.raises(ProbeError):
        check_events([{"type": "response.output_text.delta", "delta": EXPECTED}] + ending)


def test_wrong_answer_records_completion_but_not_response_content():
    with pytest.raises(ProbeError) as error:
        check_events([{"type": "response.output_text.delta", "delta": "private-test-content"}, completed_event()])
    assert error.value.code == "unexpected_probe_answer"
    assert error.value.diagnostics["inferenceCompleted"] is True
    assert error.value.diagnostics["expectedReplyMatched"] is False
    assert "private-test-content" not in json.dumps(error.value.diagnostics)


def test_completion_snapshot_takes_precedence_over_deltas():
    with pytest.raises(ProbeError, match="unexpected_probe_answer"):
        check_events([
            {"type": "response.output_text.delta", "delta": EXPECTED},
            completed_event([{"type": "message", "content": [{"type": "output_text", "text": "Wrong answer"}]}]),
        ])


def test_reasoning_text_cannot_satisfy_probe():
    with pytest.raises(ProbeError, match="unexpected_probe_answer"):
        check_events([{"type": "response.reasoning_text.delta", "delta": EXPECTED}, completed_event()])


def test_id_token_signature_nonce_and_audience():
    sys.path.insert(0, str(Path(".runtime/siwc-probe-deps").resolve()))
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public["kid"] = "test"
    claims = {"iss": AUTH, "aud": "oaiapp_test", "sub": "subject", "nonce": "nonce",
              "iat": int(time.time()), "exp": int(time.time()) + 60}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
    assert verify_identity(token, "oaiapp_test", "nonce", {"keys": [public]})["sub"] == "subject"
    with pytest.raises(ProbeError, match="id_token_nonce_mismatch"):
        verify_identity(token, "oaiapp_test", "wrong", {"keys": [public]})
    with pytest.raises(jwt.InvalidAudienceError):
        verify_identity(token, "oaiapp_other", "nonce", {"keys": [public]})


def test_missing_plan_permission_stops_before_inference(tmp_path, monkeypatch):
    import tools.check_chatgpt_plan_access as module

    seen = []
    real_client = httpx.Client

    def transport(request):
        seen.append(str(request.url))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"id_token": "test-identity-token", "scope": "openid",
                                            "access_token": "private-test-token", "token_type": "Bearer"})
        return httpx.Response(200, json={"keys": []})

    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(module, "verify_identity", lambda *args: {"sub": "test"})
    probe = Probe(tmp_path, "gpt-5.5")
    probe.origin = "http://127.0.0.1:12345"
    probe.started = True
    probe.finish_callback({"state": [probe.state], "code": ["temporary-code"], "client_id": ["oaiapp_test"]})
    assert probe.result["errorCode"] == "chatgpt_plan_permission_not_granted"
    assert probe.result["inferenceRequests"] == 0
    assert len(seen) == 2
    assert all("api.openai.com" not in url for url in seen)
    saved = (tmp_path / "evidence.json").read_text() + (tmp_path / "registration.json").read_text()
    assert "private-test-token" not in saved and "temporary-code" not in saved
