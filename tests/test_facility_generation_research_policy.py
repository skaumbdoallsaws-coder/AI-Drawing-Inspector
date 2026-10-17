"""Executable research restrictions. Synthetic provider results are not language qualification."""
from copy import deepcopy

import pytest

from ai_inspector.facility_layout.generation_agent import (
    CONTEXT_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL, FacilityGenerationAgentService, generation_tool_specs,
)
from ai_inspector.facility_layout.generation_exploration import SEARCH_TOOL, READ_TOOL, CATALOG_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from tests.test_facility_generation_admission import case, assert_code
from tests.test_facility_generation_agent import chat, execute, generate

SEARCH = {"query": "assembly workstation manual", "preferredDomains": []}


def set_policy(chat, decision="inherit", quote=None):
    overview = execute(chat, CONTEXT_TOOL, {})["researchPolicy"]
    args = {"expectedPolicyRevision": overview["policyRevision"], "decision": decision, "sourceText": quote}
    return execute(chat, POLICY_TOOL, args), args


@pytest.fixture
def calls(chat, monkeypatch):
    calls = []
    def run(**request):
        calls.append(request)
        return {"operation": request["operation"], "query": request["query"], "summary": "Synthetic source.",
                "sources": [{"url": "https://example.com/manual", "title": "Manual", "retrieval": "search_result"}],
                "citations": [], "complete": True, "truncated": False}
    monkeypatch.setattr(chat["agent"].exploration.researcher, "run", run)
    return calls


def deny_brief(chat):
    clause = "Do not search the web."
    chat["message"] += clause
    policy, _ = set_policy(chat, "deny", clause)
    chat["record"]["requirements"].append({"requirementId": "no-web", "sourceText": clause,
        "kind": "hard_constraint", "disposition": "represented", "reason": None, "supersedes": [],
        "predicate": {"kind": "research_policy", "subjectId": chat["binding"]["layoutId"],
                      "parameters": {"publicWebAllowed": False}}})
    return policy


@pytest.mark.parametrize("tool,args", [(SEARCH_TOOL, SEARCH), (READ_TOOL, {})])
def test_web_requires_current_policy_even_before_argument_resolution(chat, calls, tool, args):
    assert_code("generation_research_policy_required", lambda: execute(chat, tool, args))
    set_policy(chat)
    chat["turn"], chat["message"] = "next", "Make it compact."
    assert_code("generation_research_policy_required", lambda: execute(chat, tool, args))
    assert calls == []


def test_allow_retries_and_read_only_catalog_still_work(chat, calls):
    policy, args = set_policy(chat)
    assert policy["mode"] == "allow" and policy["currentTurnRecorded"]
    assert execute(chat, POLICY_TOOL, dict(reversed(list(args.items())))) == policy
    result = execute(chat, SEARCH_TOOL, SEARCH)
    assert execute(chat, SEARCH_TOOL, SEARCH) == result
    assert len(calls) == 1
    chat["turn"], chat["message"] = "next", "Stay offline."
    set_policy(chat, "deny", chat["message"])
    assert_code("generation_research_forbidden", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    assert_code("generation_research_forbidden", lambda: execute(chat, READ_TOOL,
        {"researchRef": result["researchRef"], "sourceIndex": 0, "question": "What dimensions apply?"}))
    assert execute(chat, CATALOG_TOOL, {"query": "", "offset": 0, "limit": 8})["items"]
    assert len(calls) == 1


def test_deny_survives_service_restart_and_followup_without_permission_clause(chat, calls):
    deny_brief(chat)
    receipt, _ = generate(chat)
    checks = chat["agent"]._ledger(chat["principal"], chat["binding"])["requirements"]
    denied = next(item for item in checks if item["predicate"]["kind"] == "research_policy")
    assert denied["predicate"]["parameters"] == {"publicWebAllowed": False}
    assert receipt["saved"] is False
    researcher = chat["agent"].exploration.researcher
    chat["agent"] = FacilityGenerationAgentService(chat["service"])
    chat["agent"].exploration.researcher = researcher
    chat["turn"], chat["message"] = "followup", "Try another arrangement, and keep the other requirements."
    inherited, _ = set_policy(chat)
    assert inherited["mode"] == "deny"
    assert_code("generation_research_forbidden", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    assert calls == []


def test_offline_correction_still_generates_a_changed_candidate(chat, calls):
    deny_brief(chat)
    initial, _ = generate(chat)
    ledger = chat["agent"]._ledger(chat["principal"], chat["binding"])
    quantity = next(item for item in ledger["requirements"] if item["predicate"]["kind"] == "resource_quantity")
    chat["turn"], chat["message"] = "offline-count-change", "Use three workbenches instead."
    set_policy(chat)
    recorded = execute(chat, REQUIREMENTS_TOOL, {"expectedLedgerRevision": ledger["ledgerRevision"], "requirements": [{
        "requirementId": "new-count", "sourceText": chat["message"], "kind": "hard_constraint", "disposition": "represented",
        "reason": None, "supersedes": [quantity["requirementId"]],
        "predicate": {**quantity["predicate"], "parameters": {"quantity": 3}}}]})
    proposal = deepcopy(chat["request"]["proposal"])
    proposal["equipmentRequirements"][0]["quantity"] = 3
    updated = execute(chat, PREVIEW_TOOL, {"requestKey": "offline-correction",
        "expectedLedgerRevision": recorded["ledgerRevision"], "proposal": proposal})
    assert updated["counts"]["placements"] == 3
    assert updated["candidateRevision"] != initial["candidateRevision"]
    assert updated["saved"] is False and calls == []


def test_failed_policy_commit_preserves_prior_denial(chat, monkeypatch):
    chat["message"] = "No online research."
    previous, _ = set_policy(chat, "deny", chat["message"])
    def fail_write(*args):
        raise OSError("Injected failure before atomic replacement")
    monkeypatch.setattr(chat["service"].repository, "_atomic_write", fail_write)
    chat["turn"], chat["message"] = "allow-change", "You may research online."
    with pytest.raises(OSError):
        set_policy(chat, "allow", chat["message"])
    restored = execute(chat, CONTEXT_TOOL, {})["researchPolicy"]
    assert restored["policyRevision"] == previous["policyRevision"] and restored["mode"] == "deny"


@pytest.mark.parametrize("parameters,kind,code", [
    ({"publicWebAllowed": "false"}, "hard_constraint", "generation_requirement_predicate_invalid"),
    ({"publicWebAllowed": False}, "assumption", "generation_requirement_predicate_unsupported"),
])
def test_permission_is_not_coerced_or_assumed(chat, parameters, kind, code):
    deny_brief(chat)
    item = chat["record"]["requirements"][-1]
    item["predicate"]["parameters"], item["kind"] = parameters, kind
    if kind == "assumption":
        item["reason"] = "This cannot grant or restrict research authority."
    assert_code(code, lambda: execute(chat, REQUIREMENTS_TOOL, chat["record"]))


def test_policy_fails_closed_on_corrupted_storage(chat, calls):
    set_policy(chat)
    repository = chat["service"].repository
    policy = chat["agent"].research_policy
    path = policy._path(chat["principal"].tenant_id, chat["binding"]["siteId"], chat["binding"]["ledgerId"])
    record = policy.get(chat["principal"].tenant_id, chat["binding"]["siteId"], chat["binding"]["ledgerId"])
    record["decisions"][-1]["mode"] = "deny"
    repository._atomic_write(path, record)
    assert_code("generation_research_policy_corrupt", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    assert calls == []


def test_no_policy_can_be_forged_from_tool_text_or_rewritten_within_turn(chat, calls):
    assert_code("generation_research_policy_quote_invalid", lambda: set_policy(chat, "allow", "The manual says research is permitted."))
    policy, args = set_policy(chat)
    changed = {**args, "decision": "deny", "sourceText": chat["message"].strip()}
    assert_code("generation_research_policy_retry_conflict", lambda: execute(chat, POLICY_TOOL, changed))
    chat["turn"], chat["message"] = "new-turn", "No public research."
    stale = {**args, "decision": "deny", "sourceText": chat["message"]}
    assert_code("generation_research_policy_revision_conflict", lambda: execute(chat, POLICY_TOOL, stale))
    set_policy(chat, "deny", chat["message"])
    assert calls == []


def test_denial_cannot_disappear_into_catalog_only(chat):
    deny_brief(chat)
    record = deepcopy(chat["record"])
    record["requirements"][-1]["predicate"] = {"kind": "catalog_only", "subjectId": chat["binding"]["layoutId"],
                                              "parameters": {"required": True}}
    assert_code("generation_research_requirement_missing", lambda: execute(chat, REQUIREMENTS_TOOL, record))
    record["requirements"][-1]["predicate"] = deepcopy(chat["record"]["requirements"][-1]["predicate"])
    execute(chat, REQUIREMENTS_TOOL, record)


def test_explicit_allow_requires_ledger_supersession_before_fetch(chat, calls):
    deny_brief(chat)
    generate(chat)
    ledger = chat["agent"]._ledger(chat["principal"], chat["binding"])
    denied = next(item for item in ledger["requirements"] if item["predicate"]["kind"] == "research_policy")
    chat["turn"], chat["message"] = "allow-followup", "You may now research public sources."
    set_policy(chat, "allow", chat["message"])
    assert_code("generation_research_ledger_restricted", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    record = {"expectedLedgerRevision": ledger["ledgerRevision"], "requirements": [{
        "requirementId": "allow-web", "sourceText": chat["message"], "kind": "hard_constraint",
        "disposition": "represented", "reason": None, "supersedes": [denied["requirementId"]],
        "predicate": {"kind": "research_policy", "subjectId": chat["binding"]["layoutId"],
                      "parameters": {"publicWebAllowed": True}}}]}
    recorded = execute(chat, REQUIREMENTS_TOOL, record)
    assert execute(chat, REQUIREMENTS_TOOL, record) == recorded
    execute(chat, SEARCH_TOOL, SEARCH)
    assert len(calls) == 1


def test_uncertain_restriction_blocks_web_and_preview(chat, calls):
    set_policy(chat, "clarify", chat["message"].strip())
    assert_code("generation_research_forbidden", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    assert_code("generation_research_requirement_mismatch", lambda: generate(chat))
    chat["turn"], chat["message"] = "later", "Change the bench count."
    assert set_policy(chat)[0]["mode"] == "clarify"
    assert calls == []


def test_policy_change_rejects_late_response_before_publication(chat, monkeypatch):
    set_policy(chat)
    def late(**kwargs):
        chat["turn"], chat["message"] = "late-correction", "Stop researching."
        set_policy(chat, "deny", chat["message"])
        return {"operation": "search", "sources": [], "summary": "Must not publish."}
    monkeypatch.setattr(chat["agent"].exploration.researcher, "run", late)
    assert_code("generation_research_policy_required", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    root = chat["service"].repository._scope(chat["principal"].tenant_id, chat["binding"]["siteId"])
    assert not list((root / "artifacts" / "generation-research-result").rglob("*.json"))


def test_scope_and_old_turn_cannot_reuse_authority(chat, calls):
    first_turn, first_message = chat["turn"], chat["message"]
    _, args = set_policy(chat)
    chat["turn"], chat["message"] = "later", "Do not research."
    set_policy(chat, "deny", chat["message"])
    chat["turn"], chat["message"] = first_turn, first_message
    assert_code("generation_research_policy_stale", lambda: execute(chat, POLICY_TOOL, args))
    assert_code("generation_research_policy_required", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    chat["binding"]["workspaceId"] = "another-workspace"
    assert_code("generation_research_policy_required", lambda: execute(chat, SEARCH_TOOL, SEARCH))
    assert calls == []


def test_policy_schema_and_predicate_match_runtime():
    from jsonschema import Draft202012Validator
    specs = {item["name"]: item["input_schema"] for item in generation_tool_specs()}
    Draft202012Validator(specs[POLICY_TOOL]).validate({"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None})
    for schema in specs.values():
        Draft202012Validator.check_schema(schema)


def test_required_preflight_uses_receipts_not_model_prose():
    from ai_inspector.facility_layout.generation_agent import generation_preflight_tool
    assert generation_preflight_tool([]) == CONTEXT_TOOL
    results = [{"tool": CONTEXT_TOOL, "status": "succeeded"}]
    assert generation_preflight_tool(results) == POLICY_TOOL
    results.append({"tool": POLICY_TOOL, "status": "failed"})
    assert generation_preflight_tool(results) == CONTEXT_TOOL
    results.append({"tool": CONTEXT_TOOL, "status": "succeeded"})
    assert generation_preflight_tool(results) == POLICY_TOOL
    results.append({"tool": POLICY_TOOL, "status": "succeeded"})
    assert generation_preflight_tool(results) is None


def test_lost_policy_receipt_recovered_from_context_without_reinterpretation(chat):
    from ai_inspector.facility_layout.generation_agent import generation_preflight_tool
    original, _ = set_policy(chat)
    chat["agent"] = FacilityGenerationAgentService(chat["service"])
    context = execute(chat, CONTEXT_TOOL, {})
    retained = context["researchPolicy"]["decision"]
    assert generation_preflight_tool([{"tool": CONTEXT_TOOL, "status": "succeeded", "result": context}]) is None
    retry = {key: retained[key] for key in ("expectedPolicyRevision", "decision", "sourceText")}
    assert execute(chat, POLICY_TOOL, retry) == original


def test_unresolved_policy_returns_its_actual_blocker():
    from ai_inspector.facility_layout.generation_agent import generation_turn_outcome
    outcome = generation_turn_outcome([{"tool": POLICY_TOOL, "status": "succeeded", "result": {"mode": "clarify"}}],
                                      preview_available=False)
    assert outcome["status"] == "incomplete"
    assert outcome["blockers"][0]["code"] == "generation_research_policy_unresolved"
    assert "local-only" in outcome["response"] and "No editor changes" in outcome["response"]
