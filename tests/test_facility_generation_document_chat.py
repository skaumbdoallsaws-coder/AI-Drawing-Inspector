"""Actual HTTP/chat orchestration with a synthetic provider and real readers/kernel."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL, CANDIDATE_TOOL, GENERATION_TOOLS
from ai_inspector.facility_layout.generation_exploration import DOCUMENT_TOOL, PREPARE_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from tests.test_equipment_documents import library
from tests.test_facility_generation_admission import case
from tests.test_facility_generation_agent import chat
from tests.test_facility_generation_exploration import brief, prepare
from tests.test_facility_generation_documents import documents, request, consultation_requirements


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("recovery", ["none", "policy", "document"])
def test_chat_reads_and_retains_local_documents_then_generates(documents, monkeypatch, stream, recovery):
    import anthropic
    import server
    from fastapi.testclient import TestClient
    brief, library = documents
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", brief["host"])
    monkeypatch.setattr(server, "_is_facility_layout_generation_request", lambda *a, **k: True)
    monkeypatch.setattr(server, "_sage_answer_provider_config", lambda *a, **k: SimpleNamespace(
        provider="anthropic", api_key="synthetic-no-network", model="synthetic", reasoning_effort=None))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: object())
    monkeypatch.setattr(brief["agent"].exploration.researcher, "run", lambda **kwargs: pytest.fail("No web needed"))
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    receipts, calls = [], 0
    stale_policy = recovery == "policy"
    steps = ["bad_policy", "context", "policy"] if stale_policy else ["policy"]
    steps += ["summary"] + (["bad_page"] if recovery == "document" else [])
    steps += ["page", "prepare", "requirements", "preview"]
    execute = brief["agent"].execute

    def observe(*args, **kwargs):
        result = execute(*args, **kwargs)
        receipts.append((kwargs["tool_name"], result))
        return result

    monkeypatch.setattr(brief["agent"], "execute", observe)

    async def invoke(*args, **kwargs):
        nonlocal calls
        calls += 1
        stage = steps[calls - 1] if calls <= len(steps) else "complete"
        if stage == "bad_policy":
            name, arguments = POLICY_TOOL, {"expectedPolicyRevision": brief["binding"]["baseRevision"], "decision": "inherit", "sourceText": None}
        elif stage == "context":
            name, arguments = CONTEXT_TOOL, {}
        elif stage == "policy":
            name, arguments = POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None}
        elif stage == "summary":
            name, arguments = DOCUMENT_TOOL, request(library)
        elif stage in {"bad_page", "page"}:
            name, arguments = DOCUMENT_TOOL, request(library, "page", pageNumber=1, textOffset=0)
            if stage == "bad_page":
                arguments["read"]["documentRevision"] = "0" * 64
            elif recovery == "document":
                returned = [result for message in kwargs["messages"]
                    if message["role"] == "user" and isinstance(message["content"], list)
                    for item in message["content"] if item.get("type") == "text"
                    and item.get("text", "").startswith("<trusted_facility_tool_results ")
                    for result in json.loads(item["text"].split("\n", 2)[1])["results"]]
                failure = next(item for item in returned if item.get("error", {}).get("code") == "equipment_document_revision_mismatch")
                repair = failure["error"]["details"]
                assert repair["failureKind"] == "reference_mismatch"
                assert repair["registeredReference"]["documentRevision"] == arguments["read"]["documentRevision"]
        elif stage == "prepare":
            name, arguments = PREPARE_TOOL, {**prepare(brief), "localDocumentRefs": [
                receipt["localDocumentRef"] for tool, receipt in receipts if tool == DOCUMENT_TOOL]}
        elif stage == "requirements":
            name, arguments = REQUIREMENTS_TOOL, deepcopy(brief["record"])
            proposed = next(result for tool, result in receipts if tool == PREPARE_TOOL)
            arguments["requirements"].extend(consultation_requirements(brief, proposed["localConsultations"]))
        elif stage == "preview":
            name, arguments = PREVIEW_TOOL, {"requestKey": "document-chat", "expectedLedgerRevision": receipts[-1][1]["ledgerRevision"],
                "proposal": deepcopy(brief["request"]["proposal"])}
        elif stage == "candidate":
            preview = receipts[-1][1]
            name, arguments = CANDIDATE_TOOL, {"previewId": preview["previewId"], "previewRevision": preview["previewRevision"],
                "collection": "placements", "offset": 0, "limit": 8}
        else:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Two placements, documented setup conditions still unresolved. Nothing applied or saved.")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        assert name in {tool["name"] for tool in kwargs["tools"]}
        if calls == 1 or (stale_policy and calls <= 3):
            assert len(kwargs["tools"]) == 1 and kwargs["required_tool_name"] == name
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=arguments, id=f"local-doc-{calls}")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(server, "_invoke_agent_model", invoke)
    with TestClient(server.app) as client:
        response = client.post("/api/agent/chat/v2/stream" if stream else "/api/agent/chat", json={
            "message": brief["message"], "history": [], "agent_type": "deviation-analyst", "session_id": "local-documents-chat",
            "client_turn_id": brief["turn"], "inspection_context": {"attachments": {"session": {"active_mode": "training"},
                "facility_layout": {"siteId": brief["options"]["site_id"], "layoutId": brief["options"]["layout_id"],
                    "revision": brief["ledger"]["baseRevision"], "generationPlanning": brief["reference"]}}}})
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        payload = next(item["final"] for item in events if item.get("event") == "response_completed")
    else:
        payload = response.json()
    assert payload["facility_generation_planning"]["status"] == "preview_ready", payload
    assert payload["facility_generation_planning"]["saved"] is False
    assert calls == len(steps), "Validated completion must not require another provider call"
    assert not payload.get("tool_calls") and not payload.get("ui_actions")
    sources = next(block for block in payload["content_blocks"] if block["type"] == "sources")["sources"]
    assert len(sources) == 1 and sources[0]["specifications"]["Retrieval"] == "Archived PDF page 1"
    preview = next(result for tool, result in receipts if tool == PREVIEW_TOOL)
    assert preview["counts"]["placements"] == 2
    assert [item["action"] for item in preview["planningNotes"]["localDocuments"]] == ["summary", "page"]
    assert sum(tool == CONTEXT_TOOL for tool, _ in receipts) == (2 if stale_policy else 1)
    saved = brief["host"].service.get_layout(brief["principal"], **{key: brief["options"][key] for key in ("site_id", "layout_id")})["layout"]
    assert layout_revision(saved) == brief["ledger"]["baseRevision"]


@pytest.mark.parametrize("stream", [False, True])
def test_bound_planning_manual_request_does_not_switch_to_document_authoring(documents, monkeypatch, stream):
    import anthropic
    import server
    from fastapi.testclient import TestClient
    brief, _ = documents
    message = "Read the Haas manual and specification sheet to develop an unsaved spatial concept. Preview only."
    assert server._required_parts_manual_workflow(message) == "documentation-publication"
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", brief["host"])
    monkeypatch.setattr(server, "_sage_answer_provider_config", lambda *a, **k: SimpleNamespace(
        provider="anthropic", api_key="synthetic-no-network", model="synthetic", reasoning_effort=None))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: object())
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    calls = []

    async def invoke(*args, **kwargs):
        names = {tool["name"] for tool in kwargs["tools"]}
        assert names and names <= GENERATION_TOOLS
        calls.append(kwargs.get("required_tool_name"))
        if len(calls) == 1:
            assert calls[-1] == POLICY_TOOL and names == {POLICY_TOOL}
            name, arguments = POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None}
        else:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="No preview has been generated yet.")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=arguments, id=f"routing-{len(calls)}")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(server, "_invoke_agent_model", invoke)
    with TestClient(server.app) as client:
        response = client.post("/api/agent/chat/v2/stream" if stream else "/api/agent/chat", json={
            "message": message, "history": [], "agent_type": "deviation-analyst", "session_id": "manual-planning-routing",
            "client_turn_id": brief["turn"], "inspection_context": {"attachments": {"session": {"active_mode": "training"},
                "facility_layout": {"siteId": brief["options"]["site_id"], "layoutId": brief["options"]["layout_id"],
                    "revision": brief["ledger"]["baseRevision"], "generationPlanning": brief["reference"]}}}})
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        payload = next(item["final"] for item in events if item.get("event") == "response_completed")
    else:
        payload = response.json()
    assert calls == [POLICY_TOOL, None]
    assert payload["facility_generation_planning"]["status"] == "incomplete"
    assert not payload.get("tool_calls") and not payload.get("ui_actions")
