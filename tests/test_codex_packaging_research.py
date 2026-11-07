"""Sage public research with stored evidence (P5 item 5b). MOCK ONLY: the researcher below replays canned raw
provider replies through the real Anthropic and OpenAI normalizers, with TEST pages on example.com. No research
provider, web page or carrier is contacted, so nothing here shows that a live research turn works."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from ai_inspector.codex_runtime import packaging_tools as tools, research_tools
from ai_inspector.codex_runtime.chatgpt_accounts import AUTH_MODE
from ai_inspector.codex_runtime.packaging_pilot import INSTRUCTIONS, NO_QUOTES, RESEARCH, _evidence, instructions_for
from ai_inspector.codex_runtime.policy import LIVE_FLAG
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping import evidence as evidence_rules
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.quoting import QuoteDesk
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.research import openai_web, web
from tests.test_packaging_comparison import two_boxes

HEADERS = {"x-inspectorpro-request": "packaging"}
DATASHEET = "https://plastics.example.com/cast-acrylic-datasheet"
CARTONS = "https://boxes.example.com/rsc-cartons"
TITLES = {DATASHEET: "TEST cast acrylic sheet datasheet", CARTONS: "TEST regular slotted carton sizes"}
# What each TEST page "says": a passage the provider quotes from it and the provider's summary of it.
PAGES = {
    DATASHEET: ("Density (ASTM D792): 1.19 g/cm" + chr(0xB3),
                "The datasheet, revised 2025-01-15, lists a density of 1.19 g/cm3 for cast acrylic sheet."),
    CARTONS: ("RSC carton 12 x 10 x 8 in, 32 ECT, SKU S-4127",
              "The catalog lists a 12 x 10 x 8 in regular slotted carton rated 32 ECT as SKU S-4127."),
}


def anthropic_raw(operation, url):
    if operation == "search":
        return {"stop_reason": "end_turn", "content": [
            {"type": "web_search_tool_result", "content": [
                {"type": "web_search_result", "url": DATASHEET, "title": TITLES[DATASHEET], "page_age": "March 3, 2025"},
                {"type": "web_search_result", "url": CARTONS, "title": TITLES[CARTONS], "page_age": None}]},
            {"type": "text", "text": "Two public pages describe cast acrylic sheet and corrugated cartons.", "citations": []}]}
    quote, summary = PAGES[url]
    return {"stop_reason": "end_turn", "usage": {"input_tokens": 9}, "content": [
        {"type": "web_fetch_tool_result", "content": {"type": "web_fetch_result", "url": url,
                                                      "retrieved_at": "2026-11-06T15:00:00Z", "content": {"title": TITLES[url]}}},
        {"type": "text", "text": summary, "citations": [
            {"type": "char_location", "cited_text": quote, "start_char_index": 0, "end_char_index": len(quote)}]}]}


def openai_raw(operation, url):
    if operation == "search":
        return {"status": "completed", "output": [
            {"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [
                {"type": "url", "url": DATASHEET}, {"type": "url", "url": CARTONS}]}},
            {"type": "message", "content": [{"type": "output_text", "text": "Found a datasheet and a carton catalog.",
                "annotations": [{"type": "url_citation", "url": DATASHEET, "title": TITLES[DATASHEET],
                                 "start_index": 0, "end_index": 10}]}]}]}
    _quote, summary = PAGES[url]
    return {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed", "action": {"type": "open_page", "url": url}},
        {"type": "message", "content": [{"type": "output_text", "text": summary, "annotations": [
            {"type": "url_citation", "url": url, "title": TITLES[url], "start_index": 0, "end_index": len(summary)}]}]}]}


class Researcher:
    """Stands in for the research provider. Canned raw replies go through the real normalizers; no network."""

    def __init__(self, shape="anthropic"):
        self.shape, self.requests = shape, []

    def available(self):
        return True

    def run(self, *, operation, query, preferred_domains=None, url=None):
        self.requests.append({"operation": operation, "query": query, "url": url})
        if self.shape == "anthropic":
            return web.normalize_response(anthropic_raw(operation, url), operation=operation, query=query, url=url,
                                          model="TEST-research-model")
        return openai_web.normalize_response(openai_raw(operation, url), operation=operation, query=query, url=url,
                                             model="TEST-research-model", allowed=list(preferred_domains or []))


EDITOR = FacilityPrincipal("engineer", "tenant-a", ("site-a",), ("editor",))
VIEWER = FacilityPrincipal("reader", "tenant-a", ("site-a",), ("viewer",))


@pytest.fixture
def env(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Research tests must not open network connections")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setenv(research_tools.FLAG, "1")
    monkeypatch.setenv(LIVE_FLAG, "1")  # The session's policy gate; the researcher is a local stand-in.
    monkeypatch.delenv(AUTH_MODE, raising=False)
    service = PackagingService(tmp_path / "packaging")
    scope = tools.packaging_scope(EDITOR)
    saved = service.create(scope, two_boxes())
    return SimpleNamespace(service=service, scope=scope, doc=saved["id"], design=saved["design"])


def gateway(env, principal=EDITOR, researcher=None, **kwargs):
    context = tools.PackagingContext(principal, "session-1", "conversation-1", "selection-1",
                                     env.doc, 0, "packaging_shipping", False, False)
    return tools.create_packaging_gateway(env.service, current_context=lambda: context, turn_id="turn-1",
                                          **({"max_calls": 16, "research": researcher} | kwargs))


def invoke(gw, name, args):
    result = asyncio.run(gw.call(name, args))
    TypeAdapter(tools._TOOLS[name][1] | tools.Failure).validate_python(result)
    return result


def assert_error(result, code):
    assert result["ok"] is False and result["error"]["code"] == code, result


def item(research_id, **changes):
    return {"kind": "material_density", "research_id": research_id, "subject": "Cast acrylic (PMMA) sheet",
            "claim": "Density (ASTM D792): 1.19 g/cm3", "value": 1.19, "unit": "g/cm3", "confidence": "high", **changes}


def search_and_read(gw, index=0):
    found = invoke(gw, research_tools.SEARCH, {"query": "cast acrylic sheet density datasheet"})
    assert found["ok"], found
    read = invoke(gw, research_tools.READ, {"researchId": found["data"]["researchId"], "sourceIndex": index,
                                            "question": "What density does this datasheet state?"})
    assert read["ok"], read
    return found["data"]["researchId"], read["data"]["researchId"]


def research_result(shape, operation, url=None):
    return {**Researcher(shape).run(operation=operation, query="TEST question", url=url), "researchId": "a" * 64}


def test_evidence_rules_bind_claims_to_what_the_page_read_returned():
    quoted, summarized = research_result("anthropic", "read", DATASHEET), research_result("openai", "read", DATASHEET)
    check = lambda read, **changes: evidence_rules.refusal(read, tools.EvidenceItem.model_validate(item("a" * 64, **changes)))
    assert check(quoted) is None and evidence_rules.claim_basis(quoted, "density (astm d792):  1.19 G/CM3") == "source_quote"
    assert check(summarized, claim="lists a density of 1.19 g/cm3") is None
    assert evidence_rules.claim_basis(summarized, "lists a density of 1.19 g/cm3") == "provider_summary"
    assert check(summarized) == "the page as read does not state this claim"  # OpenAI citations quote nothing.
    assert check(research_result("anthropic", "search")) == "research_id is not a page read in this turn"
    assert check(None) == "research_id is not a page read in this turn"
    assert check(quoted, value=1190.0, unit="kg/m3") == "the claim does not state this value"
    assert check(quoted, unit="kg/m3") == "the claim does not state this unit"
    assert check(quoted, sku_or_grade="Grade 99") == "the claim does not name this SKU or grade"
    assert check(quoted, claim="lists a density of 1.19 g/cm3", effective_date="2025-01-15") is None
    assert check(quoted, effective_date="2024-06-01") == "the page as read does not state this date"
    assert check(quoted, claim="RSC carton 12 x 10 x 8 in, 32 ECT", value=None, unit=None) == \
        "the page as read does not state this claim"  # Another page's passage.
    assert evidence_rules.claim_basis(quoted, "1.19 g/cm3") is None  # Too short to be a claim.
    assert evidence_rules.numbers("1,190 kg/m3 and .5 in or 12 x 10") == [1190.0, 3.0, 0.5, 12.0, 10.0]


def test_service_stores_reviews_and_removes_evidence_without_touching_the_design(env, monkeypatch):
    read = research_result("anthropic", "read", DATASHEET)
    record = evidence_rules.record(read, tools.EvidenceItem.model_validate(item("a" * 64)))
    assert record["source"] == {"url": DATASHEET, "title": TITLES[DATASHEET], "page_age": "2026-11-06T15:00:00Z",
                                "retrieved_at": read["retrievedAt"]}
    assert record["claim_basis"] == "source_quote" and record["research"]["provider"] == "anthropic"
    first, again = env.service.add_evidence(env.scope, env.doc, [record, dict(record)])
    assert first["review_status"] == "unreviewed" and first["id"].startswith("ev_") and again is None
    assert env.service.add_evidence(env.scope, env.doc, [record]) == [None]
    assert [r["id"] for r in env.service.evidence(env.scope, env.doc)] == [first["id"]]
    accepted = env.service.review_evidence(env.scope, env.doc, first["id"], "accepted", "engineer")
    assert accepted["review_status"] == "accepted" and accepted["reviewed_by"] == "engineer" and accepted["reviewed_at"]
    reopened = env.service.review_evidence(env.scope, env.doc, first["id"], "unreviewed", "engineer")
    assert reopened["reviewed_at"] is None and reopened["reviewed_by"] is None
    current = env.service.get(env.scope, env.doc)
    assert current["revision"] == 0 and current["design"] == env.design
    with pytest.raises(PackagingError) as missing:
        env.service.review_evidence(env.scope, env.doc, "ev_" + "0" * 32, "accepted", "engineer")
    assert missing.value.code == "evidence_not_found"
    monkeypatch.setattr(evidence_rules, "MAX_PER_DOCUMENT", 1)
    with pytest.raises(PackagingError) as full:
        env.service.add_evidence(env.scope, env.doc, [{**record, "claim": "lists a density of 1.19 g/cm3"}])
    assert full.value.code == "evidence_limit"
    assert env.service.remove_evidence(env.scope, env.doc, first["id"]) == {"removed": first["id"]}
    assert env.service.evidence(env.scope, env.doc) == []
    with pytest.raises(PackagingError) as foreign:
        env.service.evidence("other-scope", env.doc)
    assert foreign.value.code == "document_not_found"


def test_evidence_routes_list_review_and_remove_for_the_document(env):
    record = evidence_rules.record(research_result("anthropic", "read", DATASHEET),
                                   tools.EvidenceItem.model_validate(item("a" * 64)))
    stored = env.service.add_evidence(env.scope, env.doc, [record])[0]
    current = {"principal": EDITOR}
    app = FastAPI()
    app.include_router(create_router(env.service, principal_resolver=lambda r: current["principal"], static_root=Path("static")))
    path = f"/api/packaging/documents/{env.doc}/evidence"
    with TestClient(app) as client:
        listed = client.get(path).json()
        assert [r["id"] for r in listed["evidence"]] == [stored["id"]] and "never edits the design" in listed["notice"]
        assert client.put(f"{path}/{stored['id']}/review", json={"status": "approved"}, headers=HEADERS).status_code == 422
        reviewed = client.put(f"{path}/{stored['id']}/review", json={"status": "accepted"}, headers=HEADERS).json()
        assert reviewed["review_status"] == "accepted" and reviewed["reviewed_by"] == "engineer"
        current["principal"] = VIEWER
        assert client.get(path).status_code == 200
        assert client.put(f"{path}/{stored['id']}/review", json={"status": "rejected"}, headers=HEADERS).status_code == 403
        assert client.delete(f"{path}/{stored['id']}", headers=HEADERS).status_code == 403
        current["principal"] = EDITOR
        assert client.delete(f"{path}/{stored['id']}", headers=HEADERS).json() == {"removed": stored["id"]}
        assert client.delete(f"{path}/{stored['id']}", headers=HEADERS).status_code == 404
        assert client.get("/api/packaging/status").json()["capabilities"].count("research_evidence") == 1
        assert client.get(f"/api/packaging/documents/{env.doc}").json()["revision"] == 0


def test_research_tools_need_the_host_flag_and_packaging_edit(env):
    plain, viewer, researching = gateway(env), gateway(env, VIEWER, Researcher()), gateway(env, researcher=Researcher())
    names = lambda gw: {spec["name"] for spec in gw.specs}
    research = {research_tools.SEARCH, research_tools.READ, "record_packaging_evidence"}
    assert not names(plain) & research and not names(viewer) & research and research <= names(researching)
    assert {spec["name"]: spec["read_only"] for spec in researching.specs if spec["name"] in research} == {
        research_tools.SEARCH: True, research_tools.READ: True, "record_packaging_evidence": False}
    assert instructions_for(plain) == INSTRUCTIONS and NO_QUOTES in INSTRUCTIONS
    text = instructions_for(researching)
    assert NO_QUOTES not in text and RESEARCH in text and research_tools.INSTRUCTIONS in text
    assert ("arbitrary rotations, label purchase and carrier quotes are not available through these tools. "
            "Rate requests use the manual Rates panel.") in text
    both = gateway(env, researcher=Researcher(), quotes=QuoteDesk(env.service))
    assert "quote_packaging prices the saved design" in instructions_for(both) and RESEARCH in instructions_for(both)
    assert "arbitrary rotations and label purchase are not available" in instructions_for(both)
    assert "provider tools" in plain.server_instructions and "provider tools" not in researching.server_instructions
    assert "generic public terms" in researching.server_instructions


def test_sage_researches_and_records_evidence_without_editing(env):
    researcher = Researcher("anthropic")
    gw = gateway(env, researcher=researcher)
    search_id, read_id = search_and_read(gw)
    read = gw.research.results[read_id]
    assert read["requestedUrl"] == DATASHEET and researcher.requests[1]["url"] == DATASHEET
    recorded = invoke(gw, "record_packaging_evidence", {"expected_revision": 0, "items": [
        item(read_id, effective_date="2025-01-15", note="Cast, not extruded, sheet."),
        item(read_id, value=1190.0, unit="kg/m3"),
        item(search_id),
        item("b" * 64)]})
    assert recorded["ok"], recorded
    data = recorded["data"]
    assert [r["subject"] for r in data["recorded"]] == ["Cast acrylic (PMMA) sheet"]
    assert data["recorded"][0]["source"]["url"] == DATASHEET and data["recorded"][0]["claim_basis"] == "source_quote"
    assert [(r["index"], r["reason"]) for r in data["refused"]] == [
        (1, "the claim does not state this value"), (2, "research_id is not a page read in this turn"),
        (3, "research_id is not a page read in this turn")]
    duplicate = invoke(gw, "record_packaging_evidence", {"expected_revision": 0, "items": [item(read_id)]})
    assert duplicate["data"]["recorded"] == [] and duplicate["data"]["refused"][0]["reason"] == "already recorded for this document"
    stored = env.service.evidence(env.scope, env.doc)
    assert len(stored) == 1 and stored[0]["research"] == {"provider": "anthropic", "model": "TEST-research-model",
        "research_id": read_id, "result_revision": read["resultRevision"]}
    assert stored[0]["effective_date"] == "2025-01-15" and stored[0]["note"] == "Cast, not extruded, sheet."
    listed = invoke(gw, "packaging_resources", {"expected_revision": 0, "resource": "evidence"})
    assert listed["data"]["evidence"][0]["id"] == stored[0]["id"] and "unreviewed" in listed["data"]["notice"]
    current = env.service.get(env.scope, env.doc)
    assert current["revision"] == 0 and current["design"] == env.design
    externals = [row.get("external") for row in gw.receipts]
    assert [e and (e["kind"], e["operation"], e["provider_requests"], e["outcome"]) for e in externals] == [
        ("public_research", "search", 1, "completed"), ("public_research", "read", 1, "completed"), None, None, None]
    assert _evidence(gw, settings=SimpleNamespace(auth_mode="api_key"), effort="low")["externalRequests"] == externals[:2]
    assert "usage" not in json.dumps(invoke(gw, research_tools.SEARCH, {"query": "cast acrylic sheet density datasheet"}))
    assert gw.receipts[-1]["external"]["outcome"] == "reused" and len(researcher.requests) == 2


def test_openai_reads_are_recorded_as_provider_summaries(env):
    gw = gateway(env, researcher=Researcher("openai"))
    _search_id, read_id = search_and_read(gw, index=1)
    claim = "lists a 12 x 10 x 8 in regular slotted carton rated 32 ECT as SKU S-4127"
    recorded = invoke(gw, "record_packaging_evidence", {"expected_revision": 0, "items": [
        item(read_id, kind="carton_sku", subject="RSC carton 12 x 10 x 8 in", claim=claim, value=12.0, unit="in",
             sku_or_grade="S-4127", confidence="medium"),
        item(read_id, kind="carton_sku", subject="RSC carton", claim=claim, value=None, unit=None, sku_or_grade="S-9999")]})
    view = recorded["data"]["recorded"][0]
    assert view["claim_basis"] == "provider_summary" and view["source"]["url"] == CARTONS
    assert recorded["data"]["refused"] == [{"index": 1, "reason": "the claim does not name this SKU or grade"}]


def test_research_refuses_private_terms_before_any_provider_request(env):
    researcher = Researcher()
    gw = gateway(env, researcher=researcher)
    for query in ("TEST product carton size", f"density for {env.doc}", "carton for alt_0123456789abcdef",
                  "see https://plastics.example.com/x"):
        assert_error(invoke(gw, research_tools.SEARCH, {"query": query}), "research_public_terms_required")
    assert researcher.requests == []
    assert all(not row.get("external") or row["external"]["provider_requests"] == 0 for row in gw.receipts)


def test_research_is_bounded_and_needs_the_live_research_policy(env, monkeypatch):
    researcher = Researcher()
    gw = gateway(env, researcher=researcher)
    for n in range(research_tools.MAX_CALLS):
        assert invoke(gw, research_tools.SEARCH, {"query": f"corrugated carton size chart {n}"})["ok"]
    assert_error(invoke(gw, research_tools.SEARCH, {"query": "corrugated carton size chart extra"}), "research_budget_exhausted")
    assert len(researcher.requests) == research_tools.MAX_CALLS
    monkeypatch.setenv(LIVE_FLAG, "0")
    blocked = gateway(env, researcher=researcher)
    assert_error(invoke(blocked, research_tools.SEARCH, {"query": "corrugated carton size chart"}), "research_disabled")
    assert len(researcher.requests) == research_tools.MAX_CALLS
