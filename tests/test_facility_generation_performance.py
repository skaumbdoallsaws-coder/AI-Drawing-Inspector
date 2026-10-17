"""Performance adapters preserve real admission, retries and authority checks."""
from copy import deepcopy
import asyncio
import json
from types import SimpleNamespace

import jsonschema
import pytest
from starlette.requests import Request

from ai_inspector.facility_layout.generation_agent import (
    CONTEXT_TOOL, TURN_TOOL, PREVIEW_TOOL, REQUIREMENTS_TOOL, generation_tool_specs, generation_initial_tools,
    generation_source_segments, generation_preflight_tool, POLICY_TOOL,
    generation_stage_tools, REVISE_TOOL, generation_repair_tool,
)
from ai_inspector.facility_layout.generation_presentation import generation_preview_summary
from ai_inspector.facility_layout.errors import FacilityLayoutError
from tests.test_facility_generation_admission import case, assert_code
from tests.test_facility_generation_agent import chat, execute


def turn_args(chat):
    return {"researchPolicy": {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None},
            "requirementRecord": deepcopy(chat["record"]),
            "preview": {"mode": "new", "requestKey": "composed", "proposal": deepcopy(chat["request"]["proposal"])}}


def test_mandatory_coverage_guidance_reaches_every_provider_entry_path(chat):
    context = execute(chat, CONTEXT_TOOL, {})
    guidance = context["requirementContract"]
    for predicate in ("envelope_dimensions", "unsaved_preview", "resource_quantity"):
        assert predicate in guidance
    assert "not guessed dimensions" in guidance
    registry = generation_tool_specs()
    initial, _ = generation_initial_tools(registry, context)
    staged = generation_stage_tools(registry, source_ready=True, message=chat["message"],
        results=[{"tool": CONTEXT_TOOL, "status": "succeeded", "result": context}])
    for tools in (registry, initial, staged):
        for spec in tools:
            if spec["name"] in {REQUIREMENTS_TOOL, TURN_TOOL}:
                assert guidance in spec["description"]
    # Guidance never creates requirements or grants preview authority itself.
    assert context["ledger"] is None
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None


def test_recorded_research_policy_is_not_reoffered_in_compound_stage():
    registry = generation_tool_specs()
    original = deepcopy(registry)
    policy = {"tool": POLICY_TOOL, "status": "succeeded", "result": {"mode": "deny"}}
    tools = generation_stage_tools(registry, source_ready=True, results=[policy])
    schema = next(item["input_schema"] for item in tools if item["name"] == TURN_TOOL)
    validator = jsonschema.Draft202012Validator(schema["properties"]["researchPolicy"])
    validator.validate(None)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"expectedPolicyRevision": "a" * 64, "decision": "inherit", "sourceText": None})
    assert registry == original
    # No successful receipt means policy interpretation remains available.
    tools = generation_stage_tools(registry, source_ready=True,
        results=[{**policy, "status": "failed"}])
    schema = next(item["input_schema"] for item in tools if item["name"] == TURN_TOOL)
    assert "anyOf" in schema["properties"]["researchPolicy"]


def test_context_mapping_schema_pairs_observed_catalog_ids_and_revisions():
    from ai_inspector.facility_layout.generation_exploration import CATALOG_TOOL, PREPARE_TOOL
    registry = generation_tool_specs()
    original = deepcopy(registry)
    def page(items, status="succeeded"):
        return {"tool": CATALOG_TOOL, "status": status, "result": {"items": items}}
    def asset(identity, revision):
        return {"assetId": identity, "assetDefinitionRevision": revision * 64}
    results = [page([asset("bench", "a")]), page([asset("lift", "b")]),
               page([asset("bench", "c")]), page([asset("untrusted", "d")], "failed")]
    tools = generation_stage_tools(registry, source_ready=False, results=results)
    schema = next(item["input_schema"] for item in tools if item["name"] == PREPARE_TOOL)
    validator = jsonschema.Draft202012Validator(schema["properties"]["equipmentMappings"]["items"])
    for value in (asset("bench", "c"), asset("lift", "b")):
        validator.validate({**value, "processStepRefs": ["prepare"]})
    for value in (asset("bench", "a"), asset("bench", "b"), asset("untrusted", "d"),
                  {"assetId": "bench", "assetDefinitionRevision": "c" * 63}):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({**value, "processStepRefs": ["prepare"]})
    assert registry == original
    assert CATALOG_TOOL in {tool["name"] for tool in tools}


def test_combined_schema_and_real_retry(chat, monkeypatch):
    args = turn_args(chat)
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == TURN_TOOL)
    jsonschema.Draft202012Validator(schema).validate(args)
    result = execute(chat, TURN_TOOL, args)
    assert result["counts"]["placements"] == 2 and not result["editorChanged"] and not result["saved"]
    monkeypatch.setattr(chat["host"].service, "preview_operations", lambda *a, **k: pytest.fail("Repeated compilation"))
    assert execute(chat, TURN_TOOL, dict(reversed(list(args.items())))) == result
    args["requirementRecord"]["requirements"][2]["predicate"]["parameters"]["quantity"] = 3
    assert_code("generation_ledger_idempotency_conflict", lambda: execute(chat, TURN_TOOL, args))


def test_compact_requirements_have_identical_revision_and_retry_identity(chat):
    args = turn_args(chat)
    compact = deepcopy(args)
    for item in compact["requirementRecord"]["requirements"]:
        if item["disposition"] == "represented":
            item.pop("disposition")
        if item.get("reason") is None:
            item.pop("reason")
        if not item["supersedes"]:
            item.pop("supersedes")
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == TURN_TOOL)
    jsonschema.Draft202012Validator(schema).validate(compact)
    result = execute(chat, TURN_TOOL, compact)
    assert execute(chat, TURN_TOOL, args) == result


def test_compact_assumption_cannot_omit_its_reason(chat):
    args = turn_args(chat)
    item = args["requirementRecord"]["requirements"][2]
    item["kind"] = "assumption"
    item.pop("reason")
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == TURN_TOOL)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(args)
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert "assumption" in str(caught.value).lower()


def test_revision_provider_schema_requires_each_current_source_segment(chat):
    execute(chat, TURN_TOOL, turn_args(chat))
    chat["message"] = "Change the count. Keep the other requirements. Still no Save."
    chat["turn"] = "schema-follow-up"
    context = execute(chat, CONTEXT_TOOL, {})
    tools, _ = generation_initial_tools(generation_tool_specs(), context)
    shape = next(item["input_schema"] for item in tools if item["name"] == TURN_TOOL)
    grouped = shape["properties"]["requirementRecord"]["properties"]["requirementsBySegment"]
    coverage = {key: grouped[key] for key in ("type", "properties", "required", "additionalProperties")}
    validator = jsonschema.Draft202012Validator(coverage)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({"s0": [], "s1": []})
    validator.validate({"s0": [], "s1": [], "s2": []})


def test_new_plan_stage_uses_known_mode_and_full_segment_coverage(chat):
    registry = generation_tool_specs()
    original = deepcopy(registry)
    context = execute(chat, CONTEXT_TOOL, {})
    tools = generation_stage_tools(registry, source_ready=True,
        results=[{"tool": CONTEXT_TOOL, "status": "succeeded", "result": context}],
        remaining_calls=10, message=chat["message"])
    shape = next(item["input_schema"] for item in tools if item["name"] == TURN_TOOL)
    assert shape["properties"]["preview"]["properties"]["mode"] == {"const": "new"}
    coverage = shape["properties"]["requirementRecord"]["properties"]["requirementsBySegment"]
    assert coverage["required"] == [part["id"] for part in generation_source_segments(chat["message"])]
    assert registry == original


@pytest.mark.parametrize("committed", [False, True])
def test_failed_compound_exposes_only_the_needed_repair_schema(committed):
    results = [{"tool": TURN_TOOL, "status": "failed", "error": {"details": {
        "planningTurn": {"requirementsRecorded": committed}}}}]
    tools = generation_stage_tools(generation_tool_specs(), source_ready=True, results=results, remaining_calls=10)
    names = {item["name"] for item in tools}
    assert TURN_TOOL not in names and CONTEXT_TOOL in names
    assert (REQUIREMENTS_TOOL in names) is (not committed)
    assert (PREVIEW_TOOL in names) is committed
    assert (REVISE_TOOL in names) is committed
    if not committed:
        results.append({"tool": REQUIREMENTS_TOOL, "status": "succeeded", "result": {"ledgerRevision": "a" * 64}})
        names = {item["name"] for item in generation_stage_tools(generation_tool_specs(), source_ready=True,
            results=results, remaining_calls=2)}
        assert PREVIEW_TOOL in names and REQUIREMENTS_TOOL not in names and TURN_TOOL not in names


def test_budget_filter_does_not_offer_a_compound_that_cannot_execute():
    registry = generation_tool_specs()
    names = {item["name"] for item in generation_stage_tools(registry, source_ready=True, remaining_calls=2)}
    assert TURN_TOOL not in names and {REQUIREMENTS_TOOL, PREVIEW_TOOL} <= names
    assert not generation_stage_tools(registry, source_ready=True, remaining_calls=0)
    names = {item["name"] for item in generation_stage_tools(registry, source_ready=False, remaining_calls=10)}
    assert not names & {TURN_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL, REVISE_TOOL}


def test_factored_predicate_schema_preserves_closed_kind_parameter_pairings():
    from ai_inspector.facility_layout.generation_agent import _predicate_schema
    validator = jsonschema.Draft202012Validator(_predicate_schema())
    valid = {"kind": "resource_quantity", "subjectId": "batch-a", "parameters": {"quantity": 3}}
    validator.validate(valid)
    invalid = [None, {**valid, "kind": "invented"}, {**valid, "parameters": {"width": 3}},
               {**valid, "parameters": {"quantity": 3, "extra": 1}}, {**valid, "authority": "approved"},
               {key: value for key, value in valid.items() if key != "subjectId"}]
    for item in invalid:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(item)


def test_malformed_compound_preview_requires_small_ledger_repair_not_a_full_rewrite(chat):
    args = turn_args(chat)
    args["preview"] = json.dumps(args["preview"])
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert caught.value.code == "generation_turn_preview_invalid"
    assert caught.value.details["receivedType"] == "str"
    result = {"tool": TURN_TOOL, "status": "failed", "error": caught.value.to_dict()}
    assert generation_repair_tool([result]) == REQUIREMENTS_TOOL
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None
    for code in ["generation_requirement_mapping_unbound", "generation_source_catalog_stale", "placement_outside_floor"]:
        result["error"]["code"] = code
        assert generation_repair_tool([result]) is None
    assert generation_repair_tool([{"tool": REQUIREMENTS_TOOL, "status": "succeeded"}]) is None


def test_disjoint_segments_report_exact_groups_without_covering_the_gap(chat):
    args = turn_args(chat)
    chat["message"] = "Preview this layout. Keep A fixed. Do not save."
    args["requirementRecord"]["requirements"] = [{"requirementId": "unsaved", "kind": "permission",
        "sourceSegmentIds": ["s0", "s2"], "predicate": {"kind": "unsaved_preview",
            "subjectId": chat["binding"]["layoutId"], "parameters": {"saveAllowed": False}}}]
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert caught.value.code == "generation_requirement_segment_invalid"
    assert caught.value.details["inputRequirementId"] == "unsaved"
    assert caught.value.details["contiguousGroups"] == [["s0"], ["s2"]]
    assert caught.value.details["knownSegmentIds"] == ["s0", "s1", "s2"]
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None


def test_partial_failure_retains_repairable_requirements_not_geometry(chat):
    args = turn_args(chat)
    args["preview"]["proposal"]["equipmentRequirements"][0]["quantity"] = 3
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert caught.value.code == "generation_requirements_not_satisfied"
    recovery = caught.value.details["planningTurn"]
    assert recovery["researchPolicyRecorded"] and recovery["requirementsRecorded"]
    assert recovery["nextTool"] == PREVIEW_TOOL
    violations = caught.value.details["violations"]
    assert any(item["predicate"]["kind"] == "resource_quantity" for item in violations)
    assert all(item["sourceText"] in chat["message"] for item in violations)
    assert {item["requirementId"] for item in violations} == {
        item["requirementId"] for item in caught.value.details["checks"] if not item["passed"]}
    context = execute(chat, CONTEXT_TOOL, {})
    assert context["ledger"] and context["compactContext"]["previousProposal"] is None
    assert context["researchPolicy"]["currentTurnRecorded"]
    assert recovery["ledgerRevision"] == context["ledger"]["ledgerRevision"]
    args["preview"]["proposal"]["equipmentRequirements"][0]["quantity"] = 2
    args["preview"]["requestKey"] = "repaired"
    assert execute(chat, TURN_TOOL, args)["counts"]["placements"] == 2


def test_compound_real_compiler_refusal_keeps_exact_repair_state(chat):
    args = turn_args(chat)
    proposal = args["preview"]["proposal"]
    self_route = deepcopy(proposal["routes"][0])
    self_route.update(routeId="extra-self-route", sourceArea="Assembly", targetArea="Assembly", viaAreas=[])
    proposal["routes"].append(self_route)
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert caught.value.code == "facility_circulation_repeated_department"
    recovery = caught.value.details["planningTurn"]
    assert recovery["researchPolicyRecorded"] and recovery["requirementsRecorded"]
    assert recovery["nextTool"] == PREVIEW_TOOL
    context = execute(chat, CONTEXT_TOOL, {})
    assert recovery["ledgerRevision"] == context["ledger"]["ledgerRevision"]
    assert context["compactContext"]["previousProposal"] is None
    proposal["routes"].pop()
    result = execute(chat, PREVIEW_TOOL, {"requestKey": "compiler-repair",
        "expectedLedgerRevision": recovery["ledgerRevision"], "proposal": proposal})
    assert result["counts"]["placements"] == 2
    assert result["saved"] is result["editorChanged"] is False


def test_compound_does_not_drop_uncovered_clause(chat):
    args = turn_args(chat)
    chat["message"] += " And move either A or B but not both."
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert caught.value.code == "generation_requirement_clause_unaccounted"
    recovery = caught.value.details["planningTurn"]
    assert recovery["researchPolicyRecorded"] and not recovery["requirementsRecorded"]
    assert recovery["nextTool"] == REQUIREMENTS_TOOL and recovery["ledgerRevision"] is None
    results = [{"tool": CONTEXT_TOOL, "status": "succeeded", "result": {}},
               {"tool": TURN_TOOL, "status": "failed", "error": caught.value.to_dict()}]
    assert generation_preflight_tool(results) is None
    assert generation_preflight_tool([*results, {"tool": POLICY_TOOL, "status": "failed"}]) == CONTEXT_TOOL
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None


@pytest.mark.parametrize("section", ["requirements", "previousPackage", "previousEquipment",
    "previousDepartments", "previousRoutes", "previousAreas", "previousCells", "previousModules", "buildMethod"])
def test_paged_context_does_not_reset_research_policy(section):
    policy = {"tool": POLICY_TOOL, "status": "succeeded", "result": {"mode": "deny"}}
    page = {"tool": CONTEXT_TOOL, "status": "succeeded", "result": {"section": section, "items": []}}
    assert generation_preflight_tool([policy, page]) is None
    assert generation_preflight_tool([page]) == CONTEXT_TOOL
    assert generation_preflight_tool([policy, {**policy, "status": "failed"}, page]) == CONTEXT_TOOL
    overview = {"tool": CONTEXT_TOOL, "status": "succeeded", "result": {
        "researchPolicy": {"currentTurnRecorded": False}}}
    assert generation_preflight_tool([policy, overview, page]) == POLICY_TOOL
    tools = generation_stage_tools(generation_tool_specs(), source_ready=True, results=[policy, page])
    compound = next(item for item in tools if item["name"] == TURN_TOOL)
    assert compound["input_schema"]["properties"]["researchPolicy"]["type"] == "null"


def test_compound_budget_charges_internal_actions_before_execution(chat, monkeypatch):
    import server
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    monkeypatch.setattr(chat["agent"], "execute", lambda *a, **k: pytest.fail("Insufficient budget executed"))
    ctx = {"facility_layout_state": {"identity": {"siteId": chat["options"]["site_id"],
        "layoutId": chat["options"]["layout_id"], "revision": chat["ledger"]["baseRevision"]}},
        "_facility_generation_binding": chat["binding"]}
    results, trace, remaining, _, exhausted = asyncio.run(server._execute_facility_layout_provider_reads(
        [{"name": TURN_TOOL, "args": turn_args(chat)}],
        request=server.AgentChatRequest(message=chat["message"], agent_type="deviation-analyst"),
        http_request=Request({"type": "http", "headers": []}), ctx=ctx, round_index=1, turn_id=chat["turn"],
        remaining_calls=2, remaining_bytes=64000))
    assert not results and not trace and exhausted and remaining == 2


def test_exhausted_generation_does_not_pay_for_unused_provider_synthesis(monkeypatch):
    import server
    response = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=PREVIEW_TOOL, input={}, id="attempt")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    failure = {"tool": PREVIEW_TOOL, "status": "failed",
               "error": {"code": "generation_requirements_not_satisfied", "message": "Repair the quantity."}}
    async def execute_reads(*args, **kwargs):
        return [failure], [deepcopy(failure)], 0, 64000, True
    async def unexpected_model(*args, **kwargs):
        pytest.fail("Exhaustion triggered an unused provider synthesis")
    monkeypatch.setattr(server, "_execute_facility_layout_provider_reads", execute_reads)
    monkeypatch.setattr(server, "_invoke_planning_model", unexpected_model)
    monkeypatch.setattr(server, "_invoke_agent_model", unexpected_model)
    ctx = {"_facility_generation_binding": {"bound": True}}
    _, trace, usage, _ = asyncio.run(server._resolve_facility_layout_provider_reads(
        response=response, client=object(), request=server.AgentChatRequest(message="Preview only.",
            agent_type="deviation-analyst", client_turn_id="exhaustion-case"),
        http_request=Request({"type": "http", "headers": []}), ctx=ctx, skill_prompt_plan={},
        system_prompt="", messages=[], provider_tools=generation_tool_specs(), provider="anthropic", model="synthetic",
        reasoning_effort=None, terminal_required_tool=None))
    assert usage["calls"] == 1 and trace[0]["status"] == "failed"
    assert ctx["_facility_generation_outcome"]["status"] == "incomplete"


def test_unbound_resource_requirement_fails_before_ledger_commit_and_can_be_repaired(chat):
    args = turn_args(chat)
    mapping = chat["binding"]["source"]["equipmentMappings"][0]
    resource = args["preview"]["proposal"]["equipmentRequirements"][0]
    parameters = {key: deepcopy(mapping[key]) for key in ("assetId", "assetDefinitionRevision", "processStepRefs")}
    parameters["targetArea"] = resource["targetArea"]
    parameters["processStepRefs"].append("invented-instance-step")
    extra = next(item for item in args["requirementRecord"]["requirements"] if item["predicate"]["kind"] == "resource_mapping")
    extra["predicate"]["parameters"] = parameters
    assert_code("generation_requirement_mapping_unbound", lambda: execute(chat, TURN_TOOL, args))
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None
    parameters["processStepRefs"] = deepcopy(mapping["processStepRefs"])
    assert execute(chat, TURN_TOOL, args)["counts"]["placements"] == 2


def test_generation_failure_trace_retains_actionable_diagnostics(chat, monkeypatch):
    import server
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    ctx = {"facility_layout_state": {"identity": {"siteId": chat["options"]["site_id"],
        "layoutId": chat["options"]["layout_id"], "revision": chat["ledger"]["baseRevision"]}},
        "_facility_generation_binding": chat["binding"]}
    results, trace, _, _, _ = asyncio.run(server._execute_facility_layout_provider_reads(
        [{"name": CONTEXT_TOOL, "args": {"section": "unsupported-section"}}],
        request=server.AgentChatRequest(message=chat["message"], agent_type="deviation-analyst"),
        http_request=Request({"type": "http", "headers": []}), ctx=ctx, round_index=1, turn_id=chat["turn"],
        remaining_calls=20, remaining_bytes=131072))
    assert results[0]["status"] == "failed"
    assert trace[0]["error"] == results[0]["error"]
    assert trace[0]["error"]["code"] == "generation_context_page_invalid"
    assert trace[0]["arguments"] == {"section": "unsupported-section"}


def test_receipt_summary_does_not_repeat_unvalidated_clearance_claims(chat):
    result = execute(chat, TURN_TOOL, turn_args(chat))
    result["planningNotes"]["assumptions"] = ["OSHA approved clearance all around each machine."]
    summary = generation_preview_summary(result)
    assert "2 items" in summary and "Planning" in summary
    assert "OSHA approved" not in summary and "Nothing has been applied or saved" in summary
    assert len(summary.split()) <= 45
    with pytest.raises(ValueError):
        generation_preview_summary({"validationStatus": "unknown"})


def test_provider_timing_records_failure_and_preserves_exception(monkeypatch):
    import server
    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(server, "_invoke_agent_model", fail)
    ctx = {"_facility_generation_binding": {"bound": True}}
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(server._invoke_planning_model(ctx, object(), model="test", provider="synthetic"))
    assert ctx["_facility_generation_timings"][0]["status"] == "failed"
    assert ctx["_facility_generation_timings"][0]["latencyMs"] >= 0


def test_gateway_failure_timing_keeps_only_sanitized_classification(monkeypatch):
    import server
    from ai_inspector.model_gateway import GatewayError
    failure = GatewayError("model_gateway_provider_failed", "sensitive provider text", details={
        "status": 429, "errorType": "RateLimitError", "request": "private prompt", "api_key": "secret"})
    async def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(server, "_invoke_agent_model", fail)
    ctx = {"_facility_generation_binding": {"bound": True}}
    with pytest.raises(GatewayError) as caught:
        asyncio.run(server._invoke_planning_model(ctx, object(), model="test", provider="openai"))
    assert caught.value is failure
    sample = ctx["_facility_generation_timings"][0]
    assert sample["failure"] == {"code": "model_gateway_provider_failed", "status": 429, "errorType": "RateLimitError"}
    assert all(text not in json.dumps(sample) for text in ("sensitive", "private prompt", "secret"))


def test_failed_stream_diagnostics_are_bounded_without_losing_failure_identity():
    import server
    assert server._generation_failure_diagnostics({}) is None
    calls = [{"tool": PREVIEW_TOOL, "status": "failed", "arguments": {"large": "x" * 9000},
              "error": {"code": "real_constraint", "message": "Actual finding", "details": {"large": "y" * 8000}}}
             for _ in range(30)]
    meta = {"generation_diagnostics": {"toolCalls": calls, "providerCalls": [], "binding": {"layoutId": "isolated"}}}
    original = deepcopy(meta)
    result = server._generation_failure_diagnostics(meta)
    assert result["status"] == "interrupted" and result["toolCallCount"] == 30 and result["truncated"]
    assert len(server._canonical_facility_tool_result(result)) <= 65536
    assert result["toolCalls"][-1]["error"]["code"] == "real_constraint"
    assert result["toolCalls"][-1]["argumentsOmitted"]["bytes"] > 8192
    assert not result["saved"] and not result["editorChanged"]
    assert meta == original


@pytest.mark.parametrize("fail_first", [False, True])
def test_sse_provider_failure_retains_timings_tool_errors_and_does_not_claim_completion(chat, monkeypatch, fail_first):
    import anthropic
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "_FACILITY_LAYOUT_HOST", chat["host"])
    monkeypatch.setattr(server, "_is_facility_layout_generation_request", lambda *a, **k: True)
    monkeypatch.setattr(server, "_sage_answer_provider_config", lambda *a, **k: SimpleNamespace(
        provider="anthropic", api_key="synthetic-no-network", model="synthetic", reasoning_effort=None))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kwargs: object())
    monkeypatch.setenv("INSPECTORPRO_SKILLS_ENABLED", "1")
    monkeypatch.setenv("INSPECTORPRO_MEMORY_V1_MODE", "off")
    server._reset_agent_skill_runtime_cache_for_tests()
    calls = 0
    async def invoke(*args, **kwargs):
        nonlocal calls
        calls += 1
        if fail_first or calls == 3:
            raise RuntimeError("credit balance is too low; secret-provider-detail")
        name, arguments = (POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None}) if calls == 1 else (
            CONTEXT_TOOL, {"section": "invalid-section"})
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=arguments, id=f"failure-{calls}")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    monkeypatch.setattr(server, "_invoke_agent_model", invoke)
    with TestClient(server.app) as client:
        response = client.post("/api/agent/chat/v2/stream", json={
            "message": chat["message"], "history": [], "agent_type": "deviation-analyst", "session_id": "failure-diagnostics",
            "client_turn_id": chat["turn"], "inspection_context": {"attachments": {"session": {"active_mode": "training"},
                "facility_layout": {"siteId": chat["options"]["site_id"], "layoutId": chat["options"]["layout_id"],
                    "revision": chat["ledger"]["baseRevision"], "generationPlanning": chat["reference"]}}}})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert not any(item["event"] == "response_completed" for item in events)
    error = next(item for item in events if item["event"] == "response_error")
    assert error["code"] == "provider_credit_unavailable" and not error["retryable"]
    assert "secret-provider-detail" not in response.text
    diagnostics = error["generationDiagnostics"]
    assert diagnostics["status"] == "interrupted" and not diagnostics["truncated"]
    assert len(diagnostics["providerCalls"]) == calls == (1 if fail_first else 3)
    assert diagnostics["providerCalls"][-1]["status"] == "failed"
    assert len(diagnostics["toolCalls"]) == (1 if fail_first else 3)
    if not fail_first:
        assert diagnostics["toolCalls"][-1]["error"]["code"] == "generation_context_page_invalid"
        assert diagnostics["toolCalls"][-1]["arguments"] == {"section": "invalid-section"}
    assert not diagnostics["saved"] and not diagnostics["editorChanged"]
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None


def test_grounded_context_exposes_compound_without_research_bypass(chat):
    specs, required = generation_initial_tools(generation_tool_specs(), execute(chat, CONTEXT_TOOL, {}))
    assert required is None and TURN_TOOL in {spec["name"] for spec in specs}
    assert "search_generation_sources" not in {spec["name"] for spec in specs}


def test_correction_schema_omits_new_factory_parameters_without_mutating_registry(chat):
    execute(chat, TURN_TOOL, turn_args(chat))
    registry = generation_tool_specs()
    original = deepcopy(registry)
    selected, required = generation_initial_tools(registry, execute(chat, CONTEXT_TOOL, {}))
    compound = next(item for item in selected if item["name"] == TURN_TOOL)
    full = next(item for item in registry if item["name"] == TURN_TOOL)
    preview_schema = compound["input_schema"]["properties"]["preview"]
    assert preview_schema["properties"]["mode"] == {"const": "revise"}
    assert "proposal" not in preview_schema["properties"]
    assert len(json.dumps(compound)) < len(json.dumps(full))
    assert required is None and registry == original
    assert CONTEXT_TOOL in {item["name"] for item in selected}


def test_overflowing_full_context_retains_complete_revision_projection(chat, monkeypatch):
    from ai_inspector.facility_layout import generation_agent
    from ai_inspector.facility_layout.design_brief import canonical_design_bytes
    execute(chat, TURN_TOOL, turn_args(chat))
    full = execute(chat, CONTEXT_TOOL, {})
    assert full["compactContextComplete"]
    monkeypatch.setattr(generation_agent, "MAX_RESPONSE_BYTES", len(canonical_design_bytes(full)))
    bounded = execute(chat, CONTEXT_TOOL, {})
    assert not bounded["compactContextComplete"] and bounded["revisionContextComplete"]
    assert bounded["revisionContext"] == {key: full["compactContext"][key]
                                          for key in ("activeRequirements", "previousProposal")}
    assert "compactContext" not in bounded
    specs, required = generation_initial_tools(generation_tool_specs(), bounded)
    assert required is None and TURN_TOOL in {item["name"] for item in specs}


def test_segment_references_retain_exact_source_and_original_validation(chat):
    args = turn_args(chat)
    segments = generation_source_segments(chat["message"])
    for item in args["requirementRecord"]["requirements"]:
        start, end = item.pop("start"), item.pop("end")
        item["sourceSegmentIds"] = [part["id"] for part in segments if part["start"] < end and part["end"] > start]
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == TURN_TOOL)
    jsonschema.Draft202012Validator(schema).validate(args)
    result = execute(chat, TURN_TOOL, args)
    assert result["counts"]["placements"] == 2
    ledger = chat["agent"]._ledger(chat["principal"], chat["binding"])
    assert all(chat["message"][item["source"]["start"]:item["source"]["end"]].strip() for item in ledger["requirements"])


@pytest.mark.parametrize("ids", [[], ["s999"], ["s0", "s0"], ["s1", "s0"], ["s0", "s2"], [None]])
def test_bad_segment_references_fail_closed(chat, ids):
    args = deepcopy(chat["record"])
    first = args["requirements"][0]
    first.pop("start")
    first.pop("end")
    first["sourceSegmentIds"] = ids
    assert_code("generation_requirement_segment_invalid", lambda: execute(chat, REQUIREMENTS_TOOL, args))


def test_prototype_claim_is_checked_against_server_owned_package_authority(chat):
    from ai_inspector.facility_layout.generation_requirements import evaluate_generation_requirements
    args = turn_args(chat)
    clause = "This is only a spatial prototype, not manufacturing or throughput approval."
    chat["message"] += clause
    args["requirementRecord"]["requirements"].append({
        "requirementId": "claim-scope", "sourceText": clause, "kind": "hard_constraint", "disposition": "represented",
        "predicate": {"kind": "planning_claim_scope", "subjectId": chat["binding"]["layoutId"],
                      "parameters": {"planningClaim": "illustrative_prototype"}}, "reason": None, "supersedes": []})
    result = execute(chat, TURN_TOOL, args)
    assert result["productionEligible"] is False
    ledger = chat["agent"]._ledger(chat["principal"], chat["binding"])
    claim = next(item for item in ledger["requirements"] if item["predicate"]["kind"] == "planning_claim_scope")
    def claim_passes(package):
        return next(item["passed"] for item in evaluate_generation_requirements(ledger, package)["checks"]
                    if item["requirementId"] == claim["requirementId"])
    assert not claim_passes({})
    package = {"authority": {"planningClaim": "illustrative_prototype", "productionEligible": False}}
    assert claim_passes(package)
    package["authority"]["productionEligible"] = True
    assert not claim_passes(package)


@pytest.mark.parametrize("message", ["Move it 1.5 m. Keep the aisle.", "First; second\nthird.", "e.g. a small cell", "no punctuation", "\n\nYes!  No?\n"])
def test_source_segment_partition_does_not_drop_text(message):
    parts = generation_source_segments(message)
    assert "".join(part["text"] for part in parts).strip() == message.strip()
    assert all(message[part["start"]:part["end"]] == part["text"] for part in parts)


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_provider_cache_is_scoped_to_tool_prefix_and_does_not_mutate_contracts(monkeypatch, provider):
    import server
    specs = [{"name": "first"}, {"name": "last"}]
    observed = []
    async def model(*args, **kwargs):
        observed.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=2, output_tokens=3, cache_read_input_tokens=4))
    monkeypatch.setattr(server, "_invoke_agent_model", model)
    ctx = {"_facility_generation_binding": {"bound": True}}
    asyncio.run(server._invoke_planning_model(ctx, object(), model="test", provider=provider,
                                             tools=specs, messages=[{"role": "user", "content": "private"}]))
    assert specs == [{"name": "first"}, {"name": "last"}]
    assert (observed[0]["tools"][-1].get("cache_control") is not None) == (provider == "anthropic")
    assert "cache_control" not in observed[0] and "cache_control" not in observed[0]["messages"][0]
    assert ctx["_facility_generation_timings"][0]["outputTokens"] == 3


def test_provider_cancellation_is_not_retried_or_relabelled_success(monkeypatch):
    import server
    async def model(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(server, "_invoke_agent_model", model)
    ctx = {"_facility_generation_binding": {"bound": True}}
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server._invoke_planning_model(ctx, object(), provider="anthropic"))
    assert [item["status"] for item in ctx["_facility_generation_timings"]] == ["cancelled"]


def test_compound_revision_preserves_package_and_rejects_superseded_retry(chat):
    initial_args = turn_args(chat)
    initial = execute(chat, TURN_TOOL, initial_args)
    context = execute(chat, CONTEXT_TOOL, {})
    old = next(item for item in context["compactContext"]["activeRequirements"] if item["predicate"]["kind"] == "resource_quantity")
    original = deepcopy(chat["service"].prior_package(chat["principal"], chat["binding"])["package"])
    chat.update(message="Use three benches instead and preserve the other requirements.", turn="second-compound")
    common = {"sourceSegmentIds": ["s0"], "kind": "hard_constraint", "disposition": "represented", "reason": None}
    args = {"researchPolicy": {"expectedPolicyRevision": context["researchPolicy"]["policyRevision"], "decision": "inherit", "sourceText": None},
        "requirementRecord": {"expectedLedgerRevision": initial["ledgerRevision"], "requirements": [
            {**common, "requirementId": "quantity", "supersedes": [old["requirementId"]],
             "predicate": {**old["predicate"], "parameters": {"quantity": 3}}},
            {**common, "requirementId": "preservation", "supersedes": [],
             "predicate": {"kind": "preserve_prior_requirements", "subjectId": chat["binding"]["ledgerId"],
                           "parameters": {"exceptRequirementIds": [old["requirementId"]]}}}]},
        "preview": {"mode": "revise", "requestKey": "quantity-three", "previewId": initial["previewId"],
                    "previewRevision": initial["previewRevision"], "changes": [
                        {"collection": "equipmentRequirements", "entityId": old["predicate"]["subjectId"], "values": {"quantity": 3}}]}}
    result = execute(chat, TURN_TOOL, args)
    expected = deepcopy(original)
    expected["equipmentRequirements"][0]["quantity"] = 3
    assert result["counts"]["placements"] == 3
    assert chat["service"].prior_package(chat["principal"], chat["binding"])["package"] == expected
    assert execute(chat, TURN_TOOL, args) == result
    chat.update(message=context["userTurn"]["text"], turn="chat-1")
    assert_code("generation_research_policy_stale", lambda: execute(chat, TURN_TOOL, initial_args))
