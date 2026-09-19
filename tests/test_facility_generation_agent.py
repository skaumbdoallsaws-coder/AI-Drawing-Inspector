"""Synthetic-provider integration with real admission/kernel; no live qualification."""
from copy import deepcopy
from types import SimpleNamespace
import asyncio

import pytest
from starlette.requests import Request

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.generation_agent import (
    CONTEXT_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL, CANDIDATE_TOOL, GENERATION_TOOLS, generation_tool_specs, generation_turn_outcome,
)
from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
from tests.test_facility_generation_admission import case, assert_code


@pytest.fixture
def chat(case):
    service = case["host"].generation_agent_service
    reference = {"workspaceId": "chat-workspace", "sourceContextRef": case["request"]["sourceContextRef"],
                 "editorContext": case["options"]["editor_context"]}
    binding = service.bind(case["principal"], site_id=case["options"]["site_id"], layout_id=case["options"]["layout_id"],
                           base_revision=case["ledger"]["baseRevision"], reference=reference)
    message, items = "", []
    for index, req in enumerate(case["ledger"]["requirements"]):
        text = case["ledger"]["turns"][index]["text"]
        start = len(message)
        message += text + " "
        items.append({"requirementId": req["requirementId"], "start": start, "end": len(message) - 1,
            **{key: deepcopy(req[key]) for key in ("kind", "disposition", "predicate", "reason")}, "supersedes": []})
    return {**case, "agent": service, "binding": binding, "message": message, "turn": "chat-1",
            "record": {"expectedLedgerRevision": None, "requirements": items}, "reference": reference}


def execute(chat, tool, args):
    return chat["agent"].execute(chat["principal"], binding=chat["binding"], tool_name=tool, arguments=args,
                                 message=chat["message"], turn_id=chat["turn"])


def generate(chat):
    ledger = execute(chat, REQUIREMENTS_TOOL, chat["record"])
    args = {"requestKey": "candidate-a", "expectedLedgerRevision": ledger["ledgerRevision"],
            "proposal": chat["request"]["proposal"]}
    return execute(chat, PREVIEW_TOOL, args), args


def test_real_tool_chain_and_durable_retry(chat, monkeypatch):
    observed = execute(chat, CONTEXT_TOOL, {})
    assert observed["ledger"] is None and observed["userTurn"]["text"] == chat["message"]
    receipt, args = generate(chat)
    assert receipt["counts"]["placements"] == 2
    assert execute(chat, REQUIREMENTS_TOOL, chat["record"])["ledgerRevision"] == receipt["ledgerRevision"]
    monkeypatch.setattr(chat["host"].service, "preview_operations", lambda *a, **k: pytest.fail("Retry compiled twice"))
    assert execute(chat, PREVIEW_TOOL, dict(reversed(list(args.items())))) == receipt
    page = execute(chat, CANDIDATE_TOOL, {"previewId": receipt["previewId"], "previewRevision": receipt["previewRevision"],
                                        "collection": "placements", "offset": 0, "limit": 1})
    assert page["total"] == 2 and len(page["items"]) == 1 and page["nextOffset"] == 1
    saved = chat["host"].service.get_layout(chat["principal"], **{key: chat["options"][key] for key in ("site_id", "layout_id")})["layout"]
    assert layout_revision(saved) == chat["ledger"]["baseRevision"]
    assert not chat["service"].leases.inspect(chat["principal"].tenant_id, chat["options"]["site_id"], chat["options"]["layout_id"])["active"]


def test_preview_requires_current_actual_turn(chat):
    assert_code("generation_turn_not_recorded", lambda: execute(chat, PREVIEW_TOOL, {}))
    receipt, args = generate(chat)
    chat["message"] = "Use three benches instead."
    chat["turn"] = "chat-2"
    assert_code("generation_turn_not_recorded", lambda: execute(chat, PREVIEW_TOOL, args))
    prior = execute(chat, CONTEXT_TOOL, {})["ledger"]
    requirements = execute(chat, CONTEXT_TOOL, {"section": "requirements"})["items"]
    quantity = next(item for item in requirements if item["predicate"]["kind"] == "resource_quantity")
    record = {"expectedLedgerRevision": prior["ledgerRevision"], "requirements": [{
        "requirementId": "quantity", "start": 0, "end": len(chat["message"]), "kind": "hard_constraint",
        "disposition": "represented", "predicate": {"kind": "resource_quantity", "subjectId": quantity["predicate"]["subjectId"],
        "parameters": {"quantity": 3}}, "reason": None, "supersedes": [quantity["requirementId"]]}]}
    corrected = execute(chat, REQUIREMENTS_TOOL, record)
    assert_code("generation_ledger_revision_conflict", lambda: execute(chat, PREVIEW_TOOL, args))
    args = deepcopy(args)
    args["expectedLedgerRevision"] = corrected["ledgerRevision"]
    args["proposal"]["equipmentRequirements"][0]["quantity"] = 3
    replacement = execute(chat, PREVIEW_TOOL, args)
    assert replacement["counts"]["placements"] == 3
    assert replacement["candidateRevision"] != receipt["candidateRevision"]
    chat["message"] = "old result"
    chat["turn"] = "chat-1"
    assert_code("generation_turn_not_recorded", lambda: execute(chat, PREVIEW_TOOL, args))


@pytest.mark.parametrize("field", ["authority", "userText", "sourceRefs", "reviewedBy"])
def test_model_cannot_replace_trusted_turn_or_source(chat, field):
    chat["record"][field] = "forged"
    assert_code("generation_admission_fields_invalid", lambda: execute(chat, REQUIREMENTS_TOOL, chat["record"]))


def test_uncovered_clause_and_retry_conflict(chat):
    chat["message"] += " Move A or B but not both."
    with pytest.raises(Exception) as failure:
        execute(chat, REQUIREMENTS_TOOL, chat["record"])
    assert failure.value.code == "generation_requirement_clause_unaccounted"
    chat["message"] = chat["message"].removesuffix(" Move A or B but not both.")
    execute(chat, REQUIREMENTS_TOOL, chat["record"])
    chat["record"]["requirements"][2]["predicate"]["parameters"]["quantity"] = 3
    assert_code("generation_ledger_idempotency_conflict", lambda: execute(chat, REQUIREMENTS_TOOL, chat["record"]))


def test_preview_feature_does_not_enable_sage(chat, monkeypatch):
    flags = FacilityLayoutFeatureFlags.from_environment({key: "1" for key, value in chat["host"].feature_flags.values
        if not key.endswith("GENERATION_PLANNING_SAGE")})
    monkeypatch.setattr(chat["service"], "require_capability", flags.require)
    with pytest.raises(Exception) as failure:
        execute(chat, CONTEXT_TOOL, {})
    assert failure.value.status_code == 403


def test_provider_policy_and_real_compiler_loop(chat, monkeypatch):
    import server
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    bundle = chat["host"].agent_runtime.resolve_context(chat["principal"], site_id=chat["options"]["site_id"],
        layout_id=chat["options"]["layout_id"], expected_revision=chat["ledger"]["baseRevision"])
    bundle.state["generationPlanning"] = {"previewOnly": True}
    ctx = {"facility_layout_state": bundle.state, "_facility_generation_binding": chat["binding"]}
    policy = server._apply_facility_layout_request_tool_policy(None, chat["message"], facility_state=bundle.state)
    assert set(policy["allowed_tools"]) == GENERATION_TOOLS

    def response(name=None, args=None):
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=args, id="tool-a")]
                               if name else [SimpleNamespace(type="text", text="Isolated preview ready; not applied or saved.")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    count = 0

    async def model(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return response(REQUIREMENTS_TOOL, chat["record"])
        if count == 2:
            ledger = execute(chat, CONTEXT_TOOL, {})["ledger"]
            return response(PREVIEW_TOOL, {"requestKey": "from-provider", "expectedLedgerRevision": ledger["ledgerRevision"],
                                           "proposal": chat["request"]["proposal"]})
        if count == 3:
            preview = ctx["_facility_generation_preview"]
            return response(CANDIDATE_TOOL, {"previewId": preview["previewId"], "previewRevision": preview["previewRevision"],
                                            "collection": "placements", "offset": 0, "limit": 20})
        return response()

    monkeypatch.setattr(server, "_invoke_agent_model", model)
    phases = []
    async def status(phase):
        phases.append(phase)
    token = server._AGENT_CHAT_STATUS_SINK.set(status)
    try:
        _, trace, usage, actions = asyncio.run(server._resolve_facility_layout_provider_reads(response(CONTEXT_TOOL, {}),
            client=object(), request=server.AgentChatRequest(message=chat["message"], agent_type="deviation-analyst", client_turn_id=chat["turn"]),
            http_request=Request({"type": "http", "headers": []}), ctx=ctx, skill_prompt_plan=policy,
            system_prompt=policy["prompt"], messages=[], provider_tools=generation_tool_specs(), provider="anthropic", model="synthetic",
            reasoning_effort=None, terminal_required_tool=None))
    finally:
        server._AGENT_CHAT_STATUS_SINK.reset(token)
    assert len(trace) == 4 and all(item["status"] == "succeeded" for item in trace)
    assert usage["calls"] == 5 and not actions
    assert ctx["_facility_generation_preview"]["counts"]["placements"] == 2
    assert phases == ["generation_context", "generation_plan", "generation_requirements", "generation_plan",
                      "generation_geometry", "generation_plan", "generation_inspect", "generation_plan"]


def test_dispatch_rejects_unadvertised_legacy_tool(chat, monkeypatch):
    import server
    from fastapi import HTTPException
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    ctx = {"facility_layout_state": {"identity": {"siteId": chat["options"]["site_id"], "layoutId": chat["options"]["layout_id"],
        "revision": chat["ledger"]["baseRevision"]}}, "_facility_generation_binding": chat["binding"]}
    with pytest.raises(HTTPException) as failure:
        asyncio.run(server._execute_facility_layout_provider_reads([{"name": "preview_facility_linear_pattern", "args": {}}],
            request=server.AgentChatRequest(message=chat["message"], agent_type="deviation-analyst"),
            http_request=Request({"type": "http", "headers": []}), ctx=ctx, round_index=1, turn_id=chat["turn"],
            remaining_calls=4, remaining_bytes=64000))
    assert failure.value.status_code == 403


@pytest.mark.parametrize("invalid_first", [False, True])
def test_actual_chat_endpoint_uses_selected_mode_and_returns_exact_preview(chat, monkeypatch, invalid_first):
    import server
    import anthropic
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    monkeypatch.setattr(server, "_is_facility_layout_generation_request", lambda *a, **k: True)
    monkeypatch.setattr(server, "_sage_answer_provider_config", lambda *a, **k: SimpleNamespace(
        provider="anthropic", api_key="synthetic-no-network", model="synthetic", reasoning_effort=None))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: object())
    monkeypatch.setattr(server, "_run_skill_route_production", lambda *a, **k: pytest.fail("Explicit planning mode called router provider"))
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    results = []
    failures = []
    original = chat["agent"].execute

    def observe(*args, **kwargs):
        try:
            value = original(*args, **kwargs)
        except Exception as exc:
            failures.append(exc.code)
            raise
        results.append(value)
        return value

    monkeypatch.setattr(chat["agent"], "execute", observe)

    async def invoke(*args, **kwargs):
        assert {item["name"] for item in kwargs["tools"]} == GENERATION_TOOLS
        if len(results) == 0:
            name, arguments = CONTEXT_TOOL, {}
        elif len(results) == 1:
            name, arguments = REQUIREMENTS_TOOL, chat["record"]
        elif len(results) == 2:
            name, arguments = PREVIEW_TOOL, {"requestKey": "http-candidate", "expectedLedgerRevision": results[-1]["ledgerRevision"],
                                             "proposal": deepcopy(chat["request"]["proposal"])}
            if invalid_first and not failures:
                arguments["requestKey"] = "invalid-quantity"
                arguments["proposal"]["equipmentRequirements"][0]["quantity"] = 3
        elif len(results) == 3:
            name, arguments = CANDIDATE_TOOL, {"previewId": results[-1]["previewId"], "previewRevision": results[-1]["previewRevision"],
                                              "collection": "placements", "offset": 0, "limit": 20}
        else:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="The isolated prototype has two benches. Nothing applied or saved.")],
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=arguments, id="call-" + str(len(results)))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(server, "_invoke_agent_model", invoke)
    with TestClient(server.app) as client:
        response = client.post("/api/agent/chat", json={"message": chat["message"], "history": [],
            "agent_type": "deviation-analyst", "session_id": "generation-chat-test", "client_turn_id": chat["turn"],
            "inspection_context": {"attachments": {"session": {"active_mode": "training"}, "facility_layout": {
                "siteId": chat["options"]["site_id"], "layoutId": chat["options"]["layout_id"],
                "revision": chat["ledger"]["baseRevision"], "generationPlanning": chat["reference"]}}}})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["facility_generation_planning"]["status"] == "preview_ready", payload
    assert "two benches" in payload["response"]
    assert payload["facility_generation_planning"]["preview"]["previewId"] == results[2]["previewId"]
    assert payload["facility_generation_planning"]["preview"]["clientTurnId"] == chat["turn"]
    assert payload.get("tool_calls", []) == [] and payload.get("tool_call_count", 0) == 0
    assert payload["facility_generation_planning"]["saved"] is False
    assert len(results) == 4
    assert failures == (["generation_requirements_not_satisfied"] if invalid_first else [])


def test_tool_exposure_requires_selected_mode_and_feature(chat, monkeypatch):
    import server
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    assert not GENERATION_TOOLS & {item["name"] for item in server.build_native_tool_specs("deviation-analyst")}
    assert not any(name in server.build_tool_appendix("deviation-analyst") for name in GENERATION_TOOLS)
    assert {item["name"] for item in server.build_native_tool_specs("deviation-analyst", GENERATION_TOOLS)} == GENERATION_TOOLS
    monkeypatch.setattr(chat["host"], "feature_flags", FacilityLayoutFeatureFlags.from_environment({}))
    assert server.build_native_tool_specs("deviation-analyst", GENERATION_TOOLS) == []


def test_source_listing_and_trusted_context_binding(chat, monkeypatch):
    import server
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    listing = chat["agent"].list_sources(chat["principal"], site_id=chat["options"]["site_id"])
    assert listing["sources"][0]["sourceContextRef"] == chat["reference"]["sourceContextRef"]
    raw = {"_facility_generation_binding": {"forged": True}, "_facility_generation_preview": {"forged": True},
        "_facility_generation_outcome": {"status": "preview_ready"},
        "attachments": {"facility_layout": {"siteId": chat["options"]["site_id"], "layoutId": chat["options"]["layout_id"],
            "revision": chat["ledger"]["baseRevision"], "generationPlanning": chat["reference"]}}}
    ctx = server.normalize_agent_context(raw)["flat"]
    assert "_facility_generation_binding" not in ctx and "_facility_generation_preview" not in ctx
    assert "_facility_generation_outcome" not in ctx
    server._resolve_trusted_facility_layout_context(ctx)
    assert ctx["_facility_generation_binding"]["ledgerId"] == chat["binding"]["ledgerId"]
    raw["attachments"]["facility_layout"]["generationPlanning"]["editorContext"]["dirty"] = True
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        server._resolve_trusted_facility_layout_context(server.normalize_agent_context(raw)["flat"])
    assert failure.value.detail["error"]["code"] == "generation_editor_not_clean"


def test_generation_outcome_is_receipt_backed_and_replacement_failure_is_incomplete():
    good = {"tool": PREVIEW_TOOL, "status": "succeeded", "result": {}}
    bad = {"tool": PREVIEW_TOOL, "status": "failed",
           "error": {"code": "generation_spatial_failure", "message": "Two placements overlap."}}
    assert generation_turn_outcome([bad, good], preview_available=True)["status"] == "preview_ready"
    result = generation_turn_outcome([good, bad], preview_available=True)
    assert result["status"] == "incomplete" and "overlap" in result["response"]
    assert result["blockers"][0]["code"] == "generation_spatial_failure"
    assert generation_turn_outcome([good], preview_available=False)["status"] == "incomplete"
    assert generation_turn_outcome([], preview_available=True)["status"] == "incomplete"
    assert "not proof" in generation_turn_outcome([], preview_available=False, budget_exhausted=True)["response"]


@pytest.mark.parametrize("disposition", ["needs_clarification", "unsupported"])
def test_actual_chat_preserves_recorded_blocker_without_fabricated_completion(chat, monkeypatch, disposition):
    import server
    import anthropic
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    monkeypatch.setattr(server, "_is_facility_layout_generation_request", lambda *a, **k: True)
    monkeypatch.setattr(server, "_sage_answer_provider_config", lambda *a, **k: SimpleNamespace(
        provider="anthropic", api_key="synthetic-no-network", model="synthetic", reasoning_effort=None))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: object())
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    reason = "Which inspection station should the assembly transfer serve?"
    record = {"expectedLedgerRevision": None, "requirements": [{"requirementId": "open-question",
        "sourceText": chat["message"], "kind": "unknown", "disposition": disposition,
        "predicate": None, "reason": reason, "supersedes": []}]}
    calls = 0

    async def invoke(*args, **kwargs):
        nonlocal calls
        calls += 1
        content = [SimpleNamespace(type="tool_use", name=REQUIREMENTS_TOOL, input=record, id="record-question")] if calls == 1 else [
            SimpleNamespace(type="text", text="I completed and saved the whole factory.")]
        return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    monkeypatch.setattr(server, "_invoke_agent_model", invoke)
    with TestClient(server.app) as client:
        response = client.post("/api/agent/chat", json={"message": chat["message"], "history": [],
            "agent_type": "deviation-analyst", "session_id": "generation-question-test", "client_turn_id": chat["turn"],
            "inspection_context": {"attachments": {"session": {"active_mode": "training"}, "facility_layout": {
                "siteId": chat["options"]["site_id"], "layoutId": chat["options"]["layout_id"],
                "revision": chat["ledger"]["baseRevision"], "generationPlanning": chat["reference"]}}}})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert reason in payload["response"] and "completed and saved" not in payload["response"]
    assert payload["facility_generation_planning"]["status"] == "incomplete"
    assert payload["facility_generation_planning"]["blockers"][0]["code"] == disposition
    assert payload["facility_generation_planning"]["preview"] is None
    assert not payload.get("tool_calls") and not payload.get("ui_actions")
