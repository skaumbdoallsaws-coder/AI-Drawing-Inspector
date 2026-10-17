"""Bounded provider recovery; no live provider qualification."""
from copy import deepcopy
from types import SimpleNamespace
import asyncio
import json

import jsonschema
import pytest
from starlette.requests import Request

from ai_inspector.facility_layout.generation_agent import (
    CONTEXT_TOOL, PREVIEW_TOOL, REQUIREMENTS_TOOL, TURN_TOOL, generation_initial_tools,
    generation_stage_tools, generation_tool_specs, generation_repair_tool, generation_turn_outcome, generation_source_segments,
)
from ai_inspector.facility_layout.errors import FacilityLayoutError
from tests.test_facility_generation_admission import case
from tests.test_facility_generation_agent import chat, execute
from tests.test_facility_generation_performance import turn_args


@pytest.mark.parametrize("path", ["initial", "reviewed-first", "new", "repair"])
def test_bound_provider_schema_requires_each_named_segment_without_registry_mutation(chat, path):
    if path == "initial":
        execute(chat, TURN_TOOL, turn_args(chat))
        chat["turn"] = "follow-up"
    chat["message"] = "Change the count. Preserve the rest. Still no Save."
    context = execute(chat, CONTEXT_TOOL, {})
    registry = generation_tool_specs()
    original = deepcopy(registry)
    if path in {"initial", "reviewed-first"}:
        selected, _ = generation_initial_tools(registry, context)
    else:
        results = [{"tool": CONTEXT_TOOL, "status": "succeeded", "result": context}]
        if path == "repair":
            results.append({"tool": REQUIREMENTS_TOOL, "status": "failed"})
        selected = generation_stage_tools(registry, source_ready=True, results=results, message=chat["message"])
    name = REQUIREMENTS_TOOL if path == "repair" else TURN_TOOL
    schema = next(item["input_schema"] for item in selected if item["name"] == name)
    if name == TURN_TOOL:
        schema = schema["properties"]["requirementRecord"]
    coverage = jsonschema.Draft202012Validator(schema["properties"]["requirementsBySegment"])
    requirement = {"requirementId": "claim", "kind": "hard_constraint",
        "predicate": {"kind": "planning_claim_scope", "subjectId": chat["binding"]["layoutId"],
                      "parameters": {"planningClaim": "illustrative_prototype"}}}
    valid = {key: [{**requirement, "requirementId": "claim-" + key}] for key in ("s0", "s1", "s2")}
    coverage.validate(valid)
    for bad in ({"s0": valid["s0"]}, {**valid, "s999": valid["s0"]},
                {**valid, "s1": []}, {**valid, "s1": "[]"},
                {**valid, "s1": [{**requirement, "sourceSegmentIds": ["s0"]}]},
                {**valid, "s1": [{**requirement, "predicate": None}]}):
        with pytest.raises(jsonschema.ValidationError):
            coverage.validate(bad)
    assert registry == original


def grouped_record(chat):
    groups = {part["id"]: [] for part in generation_source_segments(chat["message"])}
    for item in deepcopy(chat["record"]["requirements"]):
        start, end = item.pop("start"), item.pop("end")
        matches = [part for part in generation_source_segments(chat["message"]) if part["start"] < end and part["end"] > start]
        assert matches
        if len(matches) > 1:
            assert item["predicate"]["kind"] == "unsaved_preview"
        for part in matches:
            entry = deepcopy(item)
            if len(matches) > 1:
                entry["requirementId"] += "-" + part["id"]
            groups[part["id"]].append(entry)
    return {"expectedLedgerRevision": None, "requirementsBySegment": groups}


def test_grouped_record_reuses_existing_ledger_and_retry_identity(chat):
    grouped = grouped_record(chat)
    flat = {"expectedLedgerRevision": None, "requirements": [
        {**entry, "sourceSegmentIds": [segment]} for segment, entries in grouped["requirementsBySegment"].items() for entry in entries]}
    recorded = execute(chat, REQUIREMENTS_TOOL, grouped)
    assert execute(chat, REQUIREMENTS_TOOL, flat) == recorded
    grouped["requirementsBySegment"] = dict(reversed(list(grouped["requirementsBySegment"].items())))
    assert execute(chat, REQUIREMENTS_TOOL, grouped) == recorded
    preview = execute(chat, PREVIEW_TOOL, {"requestKey": "grouped-proof", "expectedLedgerRevision": recorded["ledgerRevision"],
        "proposal": chat["request"]["proposal"]})
    assert preview["counts"]["placements"] == 2 and not preview["saved"]


@pytest.mark.parametrize("defect,code", [
    ("missing", "generation_requirement_segment_invalid"),
    ("unknown", "generation_requirement_segment_invalid"),
    ("empty", "generation_requirement_array_invalid"),
    ("string", "generation_requirement_array_invalid"),
    ("locator", "generation_requirement_fields_invalid"),
    ("predicate", "generation_requirement_fields_invalid"),
])
def test_invalid_grouped_record_does_not_commit_or_hide_clauses(chat, defect, code):
    args = grouped_record(chat)
    groups = args["requirementsBySegment"]
    key = next(iter(groups))
    if defect == "missing":
        groups.pop(key)
    elif defect == "unknown":
        groups["s999"] = deepcopy(groups[key])
    elif defect == "empty":
        groups[key] = []
    elif defect == "string":
        groups[key] = json.dumps(groups[key])
    elif defect == "locator":
        groups[key][0]["sourceText"] = "different text"
    else:
        groups[key][0]["predicate"] = None
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, REQUIREMENTS_TOOL, args)
    assert caught.value.code == code
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None


@pytest.mark.parametrize("value", ["[]", "[{\"kind\":\"hard_constraint\"}]", {}, None])
def test_string_or_other_non_array_requirements_are_not_budget_failures_or_committed(chat, value):
    args = deepcopy(chat["record"])
    args["requirements"] = value
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, REQUIREMENTS_TOOL, args)
    assert caught.value.code == "generation_requirement_array_invalid"
    assert caught.value.details["expectedType"] == "array"
    assert caught.value.details["requirementsCommitted"] is False
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None
    assert generation_repair_tool([{"tool": REQUIREMENTS_TOOL, "status": "failed",
                                    "error": caught.value.to_dict()}]) == REQUIREMENTS_TOOL
    assert execute(chat, REQUIREMENTS_TOOL, chat["record"])["ledgerRevision"]


@pytest.mark.parametrize("stop_reason,code", [
    ("refusal", "generation_provider_refused"),
    ("max_tokens", "generation_provider_output_incomplete"),
])
@pytest.mark.parametrize("after_tool", [False, True])
def test_refused_or_truncated_response_never_executes_partial_tools_or_retries(monkeypatch, stop_reason, code, after_tool):
    import server
    calls = {"tools": 0, "provider": 0}
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    partial = SimpleNamespace(stop_reason=stop_reason, usage=usage,
        content=[SimpleNamespace(type="tool_use", name=TURN_TOOL, input={"partial": True}, id="partial")])
    first = SimpleNamespace(stop_reason="tool_use", usage=usage,
        content=[SimpleNamespace(type="tool_use", name=CONTEXT_TOOL, input={}, id="context")]) if after_tool else partial
    finding = {"tool": CONTEXT_TOOL, "status": "failed", "error": {"code": "prior_finding", "message": "Prior finding"}}
    async def execute_reads(reads, **kwargs):
        calls["tools"] += 1
        assert after_tool and calls["tools"] == 1
        assert [item["name"] for item in reads] == [CONTEXT_TOOL]
        return [finding], [deepcopy(finding)], 19, 64000, False
    async def invoke(*args, **kwargs):
        calls["provider"] += 1
        assert after_tool and calls["provider"] == 1
        return partial
    monkeypatch.setattr(server, "_execute_facility_layout_provider_reads", execute_reads)
    monkeypatch.setattr(server, "_invoke_planning_model", invoke)
    monkeypatch.setattr(server, "_invoke_agent_model", lambda *a, **k: pytest.fail("Unexpected provider retry"))
    ctx = {"_facility_generation_binding": {"bound": True}}
    response, trace, _, deferred = asyncio.run(server._resolve_facility_layout_provider_reads(
        response=first, client=object(), request=server.AgentChatRequest(message="Preview only.",
            agent_type="deviation-analyst", client_turn_id="provider-stop"),
        http_request=Request({"type": "http", "headers": []}), ctx=ctx, skill_prompt_plan={},
        system_prompt="", messages=[], provider_tools=generation_tool_specs(), provider="anthropic", model="synthetic",
        reasoning_effort=None, terminal_required_tool=None))
    assert calls == {"tools": int(after_tool), "provider": int(after_tool)}
    assert len(trace) == int(after_tool) and not deferred
    if after_tool:
        assert {key: trace[0][key] for key in finding} == finding
    outcome = ctx["_facility_generation_outcome"]
    assert outcome["status"] == "incomplete" and outcome["blockers"][0]["code"] == code
    assert all(item.type == "text" for item in response.content)
    assert "Partial tool arguments were not executed" in outcome["response"]
    assert generation_turn_outcome([], preview_available=True, provider_stop_reason=stop_reason)["status"] == "incomplete"

@pytest.mark.parametrize("has_prior", [False, True])
def test_preservation_schema_requires_a_real_prior_ledger(chat, has_prior):
    from ai_inspector.facility_layout.generation_agent import _bind_requirement_segments
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == REQUIREMENTS_TOOL)
    _bind_requirement_segments(schema, [{"id": "s0"}], has_prior_requirements=has_prior)
    record = {"expectedLedgerRevision": None, "requirementsBySegment": {"s0": [{
        "requirementId": "preserve", "kind": "hard_constraint", "predicate": {
            "kind": "preserve_prior_requirements", "subjectId": chat["binding"]["ledgerId"],
            "parameters": {"exceptRequirementIds": []}}}]}}
    validator = jsonschema.Draft202012Validator(schema)
    if has_prior:
        validator.validate(record)
    else:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(record)
    # Server refusal also applies to old schemas and a model ignoring its schema.
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, REQUIREMENTS_TOOL, {**chat["record"], "requirements": [
            *chat["record"]["requirements"], {"requirementId": "bad-preserve", "sourceSegmentIds": ["s0"],
                "kind": "hard_constraint", "predicate": record["requirementsBySegment"]["s0"][0]["predicate"]}]})
    assert caught.value.code == "generation_requirement_preservation_invalid"


def test_grouped_compound_records_each_clause_and_retries_without_compiling_twice(chat, monkeypatch):
    args = turn_args(chat)
    args["requirementRecord"] = grouped_record(chat)
    context = execute(chat, CONTEXT_TOOL, {})
    tools = generation_stage_tools(generation_tool_specs(), source_ready=True,
        results=[{"tool": CONTEXT_TOOL, "status": "succeeded", "result": context}], message=chat["message"])
    schema = next(item["input_schema"] for item in tools if item["name"] == TURN_TOOL)
    jsonschema.Draft202012Validator(schema).validate(args)
    result = execute(chat, TURN_TOOL, args)
    assert result["counts"]["placements"] == 2 and not result["saved"]
    monkeypatch.setattr(chat["host"].service, "preview_operations", lambda *a, **k: pytest.fail("Retry compiled twice"))
    args["requirementRecord"]["requirementsBySegment"] = dict(reversed(list(args["requirementRecord"]["requirementsBySegment"].items())))
    assert execute(chat, TURN_TOOL, args) == result


@pytest.mark.parametrize("missing_kind", ["envelope_dimensions", "unsaved_preview", "resource_quantity"])
def test_missing_mandatory_predicate_is_repairable_before_ledger_commit(chat, missing_kind):
    args = turn_args(chat)
    target = next(item for item in args["requirementRecord"]["requirements"] if item["predicate"]["kind"] == missing_kind)
    missing_subject = target["predicate"]["subjectId"]
    # Keep textual coverage complete so this exercises required predicate coverage.
    target.update(kind="hard_constraint", predicate={"kind": "catalog_only", "subjectId": chat["binding"]["layoutId"],
                                                    "parameters": {"required": True}})
    with pytest.raises(FacilityLayoutError) as caught:
        execute(chat, TURN_TOOL, args)
    assert caught.value.code == "generation_requirements_incomplete"
    assert {"kind": missing_kind, "subjectId": missing_subject} in caught.value.details["missingPredicates"]
    assert caught.value.details["planningTurn"]["requirementsRecorded"] is False
    assert caught.value.details["planningTurn"]["nextTool"] == REQUIREMENTS_TOOL
    assert execute(chat, CONTEXT_TOOL, {})["ledger"] is None
    assert generation_repair_tool([{"tool": TURN_TOOL, "status": "failed", "error": caught.value.to_dict()}]) == REQUIREMENTS_TOOL
    repaired = execute(chat, REQUIREMENTS_TOOL, chat["record"])
    preview = execute(chat, PREVIEW_TOOL, {"requestKey": "coverage-repair", "expectedLedgerRevision": repaired["ledgerRevision"],
        "proposal": chat["request"]["proposal"]})
    assert preview["counts"]["placements"] == 2 and not preview["saved"]


def test_explicit_unresolved_requirement_can_be_retained_but_cannot_preview(chat):
    args = deepcopy(chat["record"])
    target = next(item for item in args["requirements"] if item["predicate"]["kind"] == "envelope_dimensions")
    target.update(disposition="needs_clarification", predicate=None, reason="Confirm the usable envelope dimensions.")
    ledger = execute(chat, REQUIREMENTS_TOOL, args)
    assert any(item["disposition"] == "needs_clarification" for item in ledger["requirements"])
    with pytest.raises(FacilityLayoutError):
        execute(chat, PREVIEW_TOOL, {"requestKey": "unresolved", "expectedLedgerRevision": ledger["ledgerRevision"],
            "proposal": chat["request"]["proposal"]})
