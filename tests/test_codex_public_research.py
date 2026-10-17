"""Provider contracts and real gateway tests; no paid calls or user-layout writes."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import httpx
import pytest

from ai_inspector.codex_runtime import pilot
from ai_inspector.codex_runtime.policy import LIVE_FLAG, PilotError, PilotSettings
from ai_inspector.codex_runtime.research_tools import FLAG, PROVIDER, SEARCH, READ, PublicResearchSession
from ai_inspector.research.openai_web import OpenAIWebResearch, normalize_response
from ai_inspector.research.web import ResearchError
from tests.test_codex_readonly_pilot import host, gateway

URL = "https://www.access-board.gov/ada/"


def provider_response(read=False):
    return {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed", "action":
            {"type": "open_page", "url": URL} if read else
            {"type": "search", "sources": [{"type": "url", "url": URL}]}},
        {"type": "message", "content": [{"type": "output_text", "text": "Confirm applicable requirements before design.",
            "annotations": [{"type": "url_citation", "url": URL, "title": "Accessibility standards",
                "start_index": 0, "end_index": 15}]}]}],
        "usage": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50}}


def test_subscription_research_stream_preserves_sources_without_api_key():
    raw = provider_response(True)
    events = [{"type": "response.output_item.done", "output_index": i, "item": item}
              for i, item in enumerate(raw["output"])]
    events.append({"type": "response.completed", "response": {**raw, "output": []}})
    def transport(request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer plan-only"
        assert body["stream"] is True and body["store"] is False
        assert isinstance(body["input"], list)
        assert not {"max_tool_calls", "max_output_tokens"} & body.keys()
        return httpx.Response(200, content="".join("data: " + json.dumps(event) + "\n\n" for event in events))
    provider = OpenAIWebResearch(api_key="", model="gpt-6.1-sol", credential_provider=lambda: "plan-only",
                                transport=httpx.MockTransport(transport))
    result = provider.run(operation="read", query="Parking requirements", url=URL)
    assert result["complete"] and result["sources"][0]["retrieval"] == "fetched_document"


@pytest.mark.parametrize("status,code", [(401, "research_authentication_failed"), (429, "research_quota_or_rate_limit")])
def test_subscription_research_never_retries_or_falls_back(status, code):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(status)
    provider = OpenAIWebResearch(api_key="", model="gpt-6.1-sol", credential_provider=lambda: "plan-only",
                                transport=httpx.MockTransport(transport))
    with pytest.raises(ResearchError) as failure:
        provider.run(operation="search", query="Parking requirements")
    assert failure.value.code == code and len(calls) == 1


def test_subscription_research_requires_terminal_completion():
    provider = OpenAIWebResearch(api_key="", model="gpt-6.1-sol", credential_provider=lambda: "plan-only",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content='data: [DONE]\n\n')))
    with pytest.raises(ResearchError):
        provider.run(operation="search", query="Parking requirements")


def normalized(read=False, raw=None, allowed=None):
    return normalize_response(raw or provider_response(read), operation="read" if read else "search",
        query="Accessible parking requirements", url=URL if read else None, model="gpt-5.5", allowed=allowed or [])


class Researcher:
    def __init__(self, callback=None):
        self.requests, self.callback = [], callback

    def available(self):
        return True

    def run(self, **request):
        self.requests.append(request)
        if self.callback:
            self.callback()
        return normalized(request["operation"] == "read")


@pytest.fixture(autouse=True)
def research_environment(monkeypatch):
    import ai_inspector.telemetry
    monkeypatch.setattr(ai_inspector.telemetry, "record_openai_call", lambda **_: None)
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv(PROVIDER, "openai")
    monkeypatch.setenv("INSPECTORPRO_CODEX_MODEL", "gpt-5.5")
    monkeypatch.delenv("INSPECTORPRO_CODEX_API_KEY", raising=False)


def test_provider_source_provenance_and_read_evidence():
    search = normalized()
    read = normalized(True)
    assert search["sources"][0]["retrieval"] == "search_result"
    assert read["sources"][0]["retrieval"] == "fetched_document"
    assert read["complete"] and read["reviewStatus"] == "pending" and not read["productionEligible"]
    assert read["citations"][0]["text"] == ""
    with pytest.raises(ResearchError, match="did not confirm opening"):
        normalized(True, raw=provider_response())


def test_model_only_urls_are_not_source_provenance():
    raw = provider_response()
    raw["output"] = raw["output"][1:]
    with pytest.raises(ResearchError, match="No provider-observed"):
        normalized(raw=raw)
    raw = provider_response()
    raw["output"][1]["content"][0]["annotations"].append({"type": "url_citation", "url": "https://invented.org/"})
    assert len(normalized(raw=raw)["citations"]) == 1


@pytest.mark.parametrize("failure", ["no_citation", "incomplete"])
def test_open_attempt_without_complete_cited_read_is_not_evidence(failure):
    raw = provider_response(True)
    if failure == "no_citation":
        raw["output"][1]["content"][0]["annotations"] = []
    else:
        raw["status"] = "incomplete"
    with pytest.raises(ResearchError) as error:
        normalized(True, raw=raw)
    assert error.value.code == "research_read_unconfirmed"


@pytest.mark.parametrize("address", ["http://127.0.0.1/", "http://localhost/", "file:///C:/secret", "https://user:pass@example.org/", "https://service.internal/"])
def test_nonpublic_sources_are_not_retained(address):
    raw = provider_response()
    raw["output"][0]["action"]["sources"][0]["url"] = address
    with pytest.raises(ResearchError):
        normalized(raw=raw)


def test_domain_filters_are_enforced_on_results_and_partial_is_explicit():
    assert normalized(allowed=["access-board.gov"])["complete"]
    with pytest.raises(ResearchError):
        normalized(allowed=["other.gov"])
    raw = provider_response()
    raw["status"] = "incomplete"
    assert not normalized(raw=raw)["complete"]


def test_provider_request_is_bounded_and_only_sends_public_question(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://do-not-use.invalid")
    requests = []
    def respond(request):
        requests.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-secret"
        assert "cookie" not in request.headers
        body = json.loads(request.content)
        assert body["store"] is False and body["max_tool_calls"] == 3
        assert body["tool_choice"] == "required" and body["include"] == ["web_search_call.action.sources"]
        assert body["tools"][0]["external_web_access"] is True
        assert body["tools"][0]["filters"] == {"allowed_domains": ["access-board.gov"]}
        assert json.loads(body["input"]) == {"operation": "search", "question": "Accessible parking requirements", "url": None}
        assert not any(key in body for key in ("files", "previous_response_id", "conversation"))
        return httpx.Response(200, json=provider_response())
    researcher = OpenAIWebResearch(api_key="test-secret", model="gpt-5.5", transport=httpx.MockTransport(respond))
    result = researcher.run(operation="search", query="Accessible parking requirements", preferred_domains=["access-board.gov"])
    assert result["sources"] and len(requests) == 1 and "test-secret" not in json.dumps(result)


@pytest.mark.parametrize("status,code", [(401,"research_authentication_failed"), (429,"research_quota_or_rate_limit"), (503,"research_provider_failed")])
def test_provider_failure_is_controlled_without_retry_or_body_leak(status, code):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="secret-provider-body")
    researcher = OpenAIWebResearch(api_key="test-secret", model="gpt-5.5", transport=httpx.MockTransport(respond))
    with pytest.raises(ResearchError) as error:
        researcher.run(operation="search", query="Public question")
    assert error.value.code == code and "secret" not in str(error.value) and len(calls) == 1


def test_oversized_provider_response_rejected():
    researcher = OpenAIWebResearch(api_key="test", model="gpt-5.5", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=b"x" * 512001)))
    with pytest.raises(ResearchError) as error:
        researcher.run(operation="search", query="Public question")
    assert error.value.code == "research_response_limit"


@pytest.mark.parametrize("query", ["C:\\Users\\private.pdf", "file:///tmp/private", "Bearer hidden", "sk-hidden-key", "person@example.com", "zn-private-123", "https://private.internal/"])
def test_obvious_private_query_data_is_rejected_before_dispatch(query):
    researcher = Researcher()
    session = PublicResearchSession(turn_id="one", check=lambda: None, researcher=researcher)
    with pytest.raises(PilotError) as error:
        session.run(SEARCH, {"query": query})
    assert error.value.code == "research_public_terms_required" and not researcher.requests


def test_cache_budget_scope_and_source_selection():
    researcher = Researcher()
    session = PublicResearchSession(turn_id="one", check=lambda: None, researcher=researcher)
    found = session.run(SEARCH, {"query": "Accessible parking requirements"})
    assert session.run(SEARCH, {"query": "Accessible parking requirements"}) == found
    assert len(researcher.requests) == 1
    read = session.run(READ, {"researchId": found["researchId"], "sourceIndex": 0, "question": "Explain applicability"})
    assert researcher.requests[-1]["url"] == URL and read["complete"]
    other = PublicResearchSession(turn_id="two", check=lambda: None, researcher=researcher)
    with pytest.raises(PilotError, match="this turn"):
        other.run(READ, {"researchId": found["researchId"], "sourceIndex": 0, "question": "Explain applicability"})
    session.run(SEARCH, {"query": "Another public query"})
    session.run(SEARCH, {"query": "One more public query"})
    with pytest.raises(PilotError, match="budget"):
        session.run(SEARCH, {"query": "Fifth public query"})
    card = session.source_block()["sources"][0]
    assert card["url"] == URL and card["sourceType"] == "technical-document"
    assert card["publisher"] == "" and card["specifications"]["Review"] == "Pending"


def test_policy_revocation_drops_inflight_result(monkeypatch):
    researcher = Researcher(lambda: monkeypatch.setenv(FLAG, "0"))
    session = PublicResearchSession(turn_id="one", check=lambda: None, researcher=researcher)
    with pytest.raises(PilotError, match="disabled"):
        session.run(SEARCH, {"query": "Public question"})
    assert not session.results and session.source_block() is None


def test_quota_failure_prevents_repeated_paid_requests():
    def fail():
        raise ResearchError("research_quota_or_rate_limit", "Quota unavailable.")
    researcher = Researcher(fail)
    session = PublicResearchSession(turn_id="one", check=lambda: None, researcher=researcher)
    for query in ("Public question", "Another public question"):
        with pytest.raises(PilotError, match="Quota"):
            session.run(SEARCH, {"query": query})
    assert len(researcher.requests) == 1 and not session.results


def test_provider_usage_telemetry_has_no_question_credentials_or_source_body(monkeypatch):
    import ai_inspector.telemetry
    calls = []
    monkeypatch.setattr(ai_inspector.telemetry, "record_openai_call", lambda **row: calls.append(row))
    researcher = OpenAIWebResearch(api_key="test-secret", model="gpt-5.5", transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=provider_response())))
    researcher.run(operation="search", query="Public equipment dimensions")
    assert calls[0]["status"] == "success" and calls[0]["response"].usage.input_tokens == 20
    assert all(value not in str(calls) for value in ("test-secret", "Public equipment dimensions", URL))


def test_real_gateway_preserves_document_and_limits_schema_and_stale_reads(host):
    researcher = Researcher()
    reader = gateway(host, researcher=researcher)
    revision = reader.check()["revision"]
    async def exercise():
        context = await reader.call("inspect_facility_context", {})
        assert context["data"]["publicResearch"]["configured"]
        invalid = await reader.call(READ, {"url": URL, "question": "Read this"})
        assert invalid["error"]["code"] == "codex_tool_arguments_invalid"
        found = await reader.call(SEARCH, {"query": "Public question"})
        assert found["ok"]
        reader.reference["revision"] = "0" * 64
        stale = await reader.call(SEARCH, {"query": "Different question"})
        assert stale["error"]["code"] == "codex_document_unavailable"
    asyncio.run(exercise())
    reader.reference["revision"] = revision
    assert reader.check()["revision"] == revision and len(researcher.requests) == 1


def test_real_gateway_rejects_result_when_document_changes_during_research(host):
    researcher = Researcher()
    reader = gateway(host, researcher=researcher)
    researcher.callback = lambda: reader.reference.update(revision="0" * 64)
    reply = asyncio.run(reader.call(SEARCH, {"query": "Public question"}))
    assert reply["error"]["code"] == "codex_document_unavailable" and not reader.research.results


def test_cancelled_research_is_joined_and_does_not_retain_late_sources(host):
    started, release = threading.Event(), threading.Event()
    def callback():
        started.set()
        assert release.wait(5)
    reader = gateway(host, researcher=Researcher(callback))
    async def exercise():
        task = asyncio.create_task(reader.call(SEARCH, {"query": "Public question"}))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(exercise())
    finally:
        release.set()
    assert reader.closed and not reader.research.results


def test_missing_credential_and_disabled_policy_are_explicit(host, monkeypatch):
    reader = gateway(host)
    result = asyncio.run(reader.call(SEARCH, {"query": "Public question"}))
    assert result["error"]["code"] == "research_provider_unavailable"
    monkeypatch.setenv(FLAG, "0")
    result = asyncio.run(reader.call(SEARCH, {"query": "Public question"}))
    assert result["error"]["code"] == "research_disabled"
    assert not reader.research.results


def test_pilot_returns_receipt_derived_source_cards_and_replays_without_research(host, tmp_path, monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    monkeypatch.setenv("INSPECTORPRO_CODEX_EDIT_PREVIEWS", "0")
    researcher, state = Researcher(), {}
    @asynccontextmanager
    async def bridge(reader):
        reader.research.researcher = researcher
        state["gateway"] = reader
        yield "http://127.0.0.1:9/mcp", "test-capability"
    class Transport:
        def __init__(self, *_):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def inspect(self, **kwargs):
            assert "current user restrictions" in kwargs["instructions"]
            assert (await state["gateway"].call("inspect_facility_context", {}))["ok"]
            found = await state["gateway"].call(SEARCH, {"query": "Accessible parking requirements"})
            assert found["ok"]
            read = await state["gateway"].call(READ, {"researchId": found["data"]["researchId"],
                "sourceIndex": 0, "question": "Explain applicability"})
            assert read["ok"]
            return "Review the applicable requirements. [Source](" + URL + ")"
    monkeypatch.setattr(pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="research-turn",
        conversation_id="conversation", message="Research public parking requirements, without changing my layout.")
    context = {"facility_layout_ref": gateway(host).reference}
    settings = PilotSettings(Path("unused"), tmp_path / "pilot", "gpt-5.5")
    async def invoke():
        return await pilot.inspect_facility(request, host, None, context, settings=settings, transport_factory=Transport)
    result = asyncio.run(invoke())
    assert result["content_blocks"][0]["sources"][0]["url"] == URL
    assert len(result["codex_inspection"]["researchReceipts"]) == 2
    assert result["codex_inspection"]["engineeringChanges"] == 0
    assert asyncio.run(invoke()) == result and len(researcher.requests) == 2
