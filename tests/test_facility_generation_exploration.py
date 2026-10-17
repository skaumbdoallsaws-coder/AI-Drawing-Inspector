"""General provisional planning; synthetic research is not live qualification."""
from copy import deepcopy
import json

import pytest

from ai_inspector.research.web import normalize_response, public_url, ResearchError
from ai_inspector.facility_layout.generation_exploration import CATALOG_TOOL, SEARCH_TOOL, READ_TOOL, PREPARE_TOOL
from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL, CANDIDATE_TOOL
from ai_inspector.facility_layout.generation_admission import PROVISIONAL_SOURCE_KIND
from tests.test_facility_generation_admission import case, assert_code
from tests.test_facility_generation_agent import chat, execute, generate
from tests.test_facility_generation_revision import correction
from ai_inspector.facility_layout.generation_agent import REVISE_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL


@pytest.fixture
def brief(chat, monkeypatch):
    chat["reference"] = {**chat["reference"], "workspaceId": "brief-workspace", "sourceContextRef": None}
    chat["binding"] = chat["agent"].bind(chat["principal"], site_id=chat["options"]["site_id"], layout_id=chat["options"]["layout_id"],
        base_revision=chat["ledger"]["baseRevision"], reference=chat["reference"])
    monkeypatch.setattr(chat["service"], "resolve_process_map", lambda *a: pytest.fail("Provisional context requested an authoritative map"))
    # Translate only test evidence identities, not geometry or compiler results.
    chat["request"]["proposal"] = json.loads(json.dumps(chat["request"]["proposal"]).replace("synthetic-scenario-v1", "brief-interpretation"))
    chat["record"] = json.loads(json.dumps(chat["record"]).replace("synthetic-scenario-v1", "brief-interpretation"))
    return chat


def prepare(brief, label="Small pump assembly"):
    context = brief["context"]
    return {"productLabel": label,
        "processSteps": [{key: value for key, value in step.items() if key != "evidenceRefs"} for step in context["processSteps"]],
        "equipmentMappings": [{key: value for key, value in row.items() if key != "evidenceRefs"} for row in context["equipmentMappings"]],
        "assumptions": ["Two benches are an illustrative starting count, not a capacity calculation."],
        "unknowns": ["Cycle times and installed tooling are not established."], "researchRefs": []}


def test_corrected_notes_do_not_assert_initial_count_and_context_is_compact(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    first, change = correction(brief)
    assert first["planningNotes"]["assumptions"] == prepare(brief)["assumptions"]
    revised = execute(brief, REVISE_TOOL, change)
    notes = revised["planningNotes"]
    assert prepare(brief)["assumptions"][0] not in notes["assumptions"]
    assert notes["historicalAssumptions"] == prepare(brief)["assumptions"]
    assert notes["contextNotesStatus"] == "historical_not_revalidated"
    compact = execute(brief, CONTEXT_TOOL, {})
    assert compact["compactContextComplete"] is True
    prior = compact["compactContext"]["previousProposal"]
    assert prior["previewId"] == revised["previewId"]
    assert prior["package"]["equipmentRequirements"][0]["quantity"] == 3
    assert all(item["disposition"] != "superseded" for item in compact["compactContext"]["activeRequirements"])


@pytest.mark.parametrize("label,quantity", [("Small pump assembly", 2), ("Valve refurbishment", 3), ("Sensor enclosure assembly", 4)])
def test_new_brief_without_authored_map_compiles_different_counts(brief, label, quantity):
    overview = execute(brief, CONTEXT_TOOL, {})
    assert overview["source"] is None and overview["nextAction"] == PREPARE_TOOL
    assert overview["floor"]["boundsMeters"]
    catalog = execute(brief, CATALOG_TOOL, {"query": "workbench", "offset": 0, "limit": 8})
    assert any(item["assetId"] == "asset-workbench" for item in catalog["items"])
    source = execute(brief, PREPARE_TOOL, prepare(brief, label))
    assert source["processMapAuthored"] is False and source["reviewStatus"] == "pending"
    assert source["sourceContextRef"]["artifactKind"] == PROVISIONAL_SOURCE_KIND
    for item in brief["record"]["requirements"]:
        if item["predicate"]["kind"] == "resource_quantity":
            item["predicate"]["parameters"]["quantity"] = quantity
    brief["request"]["proposal"]["equipmentRequirements"][0]["quantity"] = quantity
    receipt, _ = generate(brief)
    assert receipt["counts"]["placements"] == quantity
    assert receipt["planningNotes"]["provisional"] is True
    assert receipt["planningNotes"]["unknowns"] == prepare(brief)["unknowns"]
    assert receipt["saved"] is receipt["editorChanged"] is False
    ledger = brief["agent"]._ledger(brief["principal"], brief["binding"])
    assert not any(ref["sourceKind"] == "process_map" for ref in ledger["sourceRefs"])
    rebound = brief["agent"].bind(brief["principal"], site_id=brief["options"]["site_id"], layout_id=brief["options"]["layout_id"],
        base_revision=brief["ledger"]["baseRevision"], reference=brief["reference"])
    assert rebound["ledgerId"] == brief["binding"]["ledgerId"]
    assert rebound["sourceContextRef"] == source["sourceContextRef"]


def test_context_cannot_borrow_review_or_unknown_catalog(brief):
    request = prepare(brief)
    request["reviewStatus"] = "confirmed"
    assert_code("generation_admission_fields_invalid", lambda: execute(brief, PREPARE_TOOL, request))
    request = prepare(brief)
    request["equipmentMappings"][0]["assetId"] = "invented-machine"
    assert_code("generation_source_catalog_stale", lambda: execute(brief, PREPARE_TOOL, request))
    assert_code("generation_context_not_proposed", lambda: execute(brief, REQUIREMENTS_TOOL, brief["record"]))


def test_provisional_process_cycle_is_actual_validator_refusal(brief):
    request = prepare(brief)
    request["processSteps"][0]["predecessorProcessStepIds"] = [request["processSteps"][-1]["processStepId"]]
    assert_code("facility_planning_process_cycle", lambda: execute(brief, PREPARE_TOOL, request))


def test_same_catalog_model_can_serve_distinct_operations_but_duplicate_assignment_is_rejected(brief):
    request = prepare(brief)
    first = request["processSteps"][0]
    second = {**deepcopy(first), "processStepId": "second-operation", "label": "Second operation",
              "predecessorProcessStepIds": [first["processStepId"]]}
    request["processSteps"].append(second)
    mapping = deepcopy(request["equipmentMappings"][0])
    mapping["processStepRefs"] = [second["processStepId"]]
    request["equipmentMappings"].append(mapping)
    result = execute(brief, PREPARE_TOOL, request)
    assert len(result["equipmentMappings"]) == 2
    request["equipmentMappings"].append(deepcopy(mapping))
    from ai_inspector.facility_layout.errors import FacilityLayoutError
    with pytest.raises(FacilityLayoutError) as caught:
        execute(brief, PREPARE_TOOL, request)
    assert caught.value.code == "generation_source_mapping_invalid"
    assert caught.value.details["assetId"] == mapping["assetId"]
    assert caught.value.details["processStepRefs"] == mapping["processStepRefs"]


def test_quoted_requirements_preserve_offsets_and_assumption_checks(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    record = deepcopy(brief["record"])
    for item in record["requirements"]:
        start, end = item.pop("start"), item.pop("end")
        item["sourceText"] = brief["message"][start:end]
        if item["predicate"]["kind"] == "resource_quantity":
            item.update(kind="assumption", reason="Provisional quantity pending production requirements.")
    receipt = execute(brief, REQUIREMENTS_TOOL, record)
    assert execute(brief, REQUIREMENTS_TOOL, record) == receipt
    for expected, actual in zip(brief["record"]["requirements"], receipt["requirements"]):
        assert actual["source"]["start"] == expected["start"]
        assert actual["source"]["end"] == expected["end"]
    proposal = deepcopy(brief["request"]["proposal"])
    proposal["equipmentRequirements"][0]["quantity"] += 1
    assert_code("generation_requirements_not_satisfied", lambda: execute(brief, PREVIEW_TOOL,
        {"requestKey": "wrong-assumption", "expectedLedgerRevision": receipt["ledgerRevision"], "proposal": proposal}))
    amended = {**record, "expectedLedgerRevision": receipt["ledgerRevision"]}
    assert_code("generation_turn_already_recorded", lambda: execute(brief, REQUIREMENTS_TOOL, amended))


def test_unknown_or_ambiguous_quote_is_not_guessed(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    record = deepcopy(brief["record"])
    item = record["requirements"][0]
    item.pop("start")
    item.pop("end")
    item["sourceText"] = "text not in the user request"
    assert_code("generation_requirement_quote_invalid", lambda: execute(brief, REQUIREMENTS_TOOL, record))
    item["sourceText"] = "a"
    brief["message"] = "a a"
    assert_code("generation_requirement_quote_invalid", lambda: execute(brief, REQUIREMENTS_TOOL, record))


def test_bad_permission_error_identifies_required_classification(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    record = deepcopy(brief["record"])
    permission = next(item for item in record["requirements"] if item["predicate"]["kind"] == "unsaved_preview")
    permission["kind"] = "hard_constraint"
    with pytest.raises(Exception) as failure:
        execute(brief, REQUIREMENTS_TOOL, record)
    assert failure.value.code == "generation_requirement_predicate_unsupported"
    assert failure.value.details["permittedRequirementKinds"] == ["permission"]
    assert failure.value.details["requirementId"]
    assert "unsaved_preview" in str(failure.value)


def test_uncovered_clause_is_returned_for_repair(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    brief["message"] += " Also keep this constraint."
    with pytest.raises(Exception) as failure:
        execute(brief, REQUIREMENTS_TOOL, brief["record"])
    assert failure.value.code == "generation_requirement_clause_unaccounted"
    assert any("Also keep this constraint." in item["text"] for item in failure.value.details["uncovered"])
    assert failure.value.details["quoteExtensions"]
    assert "not validated semantic repairs" in failure.value.details["quoteExtensionsQualification"]
    assert brief["agent"]._ledger(brief["principal"], brief["binding"]) is None


def test_quote_extensions_identify_the_input_requirement_not_another_period():
    from ai_inspector.facility_layout.generation_agent import _coverage_quote_extensions
    text = "Use catalog assets. Keep staged parts."
    start = text.index(".")
    sources = [{"requirementId": "catalog", "start": 0, "end": start},
               {"requirementId": "staging", "start": start + 2, "end": len(text)}]
    before = deepcopy(sources)
    options = _coverage_quote_extensions(text, [{"start": start, "end": start + 1}], sources)
    assert options == [{"requirementId": "catalog", "sourceText": "Use catalog assets."}]
    assert sources == before


def test_quote_extensions_remain_bounded_and_do_not_guess_duplicate_quotes():
    from ai_inspector.facility_layout.generation_agent import _coverage_quote_extensions
    text = "x." * 10
    gaps = [{"start": index, "end": index + 1} for index in range(1, 20, 2)]
    sources = [{"requirementId": "item-" + str(index), "start": index - 1, "end": index} for index in range(1, 20, 2)]
    assert _coverage_quote_extensions(text, gaps, sources) == []
    text = " ".join("item-" + str(index) + "." for index in range(10))
    gaps, sources = [], []
    for index in range(10):
        start = text.index("item-" + str(index))
        end = text.index(".", start)
        gaps.append({"start": end, "end": end + 1})
        sources.append({"requirementId": "item-" + str(index), "start": start, "end": end})
    assert len(_coverage_quote_extensions(text, gaps, sources)) == 4
    assert _coverage_quote_extensions("x" * 1100 + ".", [{"start": 1100, "end": 1101}],
        [{"requirementId": "long", "start": 0, "end": 1100}]) == []


def test_provisional_context_revision_keeps_ledger_and_explicit_correction(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    initial, _ = generate(brief)
    ledger_id = brief["binding"]["ledgerId"]
    prior = execute(brief, CONTEXT_TOOL, {"section": "requirements"})
    previous_equipment = execute(brief, CONTEXT_TOOL, {"section": "previousEquipment"})
    assert previous_equipment["items"] == brief["request"]["proposal"]["equipmentRequirements"]
    assert previous_equipment["previousProposal"]["previewRevision"] == initial["previewRevision"]
    quantity = next(item for item in prior["items"] if item["predicate"]["kind"] == "resource_quantity")
    brief["turn"], brief["message"] = "correction-2", "Use three benches; retain the rest."
    request = prepare(brief)
    request["assumptions"] = ["Three benches as requested; capacity still unverified."]
    execute(brief, PREPARE_TOOL, request)
    assert brief["binding"]["ledgerId"] == ledger_id
    record = {"expectedLedgerRevision": initial["ledgerRevision"], "requirements": [{"requirementId": "quantity-change",
        "start": 0, "end": len(brief["message"]), "kind": "hard_constraint", "disposition": "represented",
        "predicate": {**quantity["predicate"], "parameters": {"quantity": 3}}, "reason": None,
        "supersedes": [quantity["requirementId"]]}]}
    updated = execute(brief, REQUIREMENTS_TOOL, record)
    assert execute(brief, CONTEXT_TOOL, {"section": "previousEquipment"}) == previous_equipment
    prior_package = execute(brief, CONTEXT_TOOL, {"section": "previousPackage"})
    proposal = {**prior_package["packageFields"],
                "equipmentRequirements": deepcopy(previous_equipment["items"]),
                "departments": execute(brief, CONTEXT_TOOL, {"section": "previousDepartments"})["items"],
                "routes": execute(brief, CONTEXT_TOOL, {"section": "previousRoutes"})["items"]}
    proposal["equipmentRequirements"][0]["quantity"] = 3
    current = execute(brief, PREVIEW_TOOL, {"requestKey": "corrected", "expectedLedgerRevision": updated["ledgerRevision"], "proposal": proposal})
    assert current["counts"]["placements"] == 3
    assert execute(brief, CONTEXT_TOOL, {"section": "previousEquipment"})["items"][0]["quantity"] == 3
    assert previous_equipment["items"][0]["quantity"] == 2
    stored_prior = brief["service"]._load(brief["principal"], brief["options"]["site_id"], brief["options"]["layout_id"],
        brief["binding"]["workspaceId"], "generation-isolated-preview", initial["previewId"])
    assert len(stored_prior["candidateLayout"]["placements"]) == 2
    assert_code("generation_ledger_revision_conflict", lambda: execute(brief, PREVIEW_TOOL,
        {"requestKey": "old", "expectedLedgerRevision": initial["ledgerRevision"], "proposal": proposal}))


def test_prior_package_retrieval_is_scoped_and_failed_preview_keeps_last_good(brief):
    execute(brief, PREPARE_TOOL, prepare(brief))
    assert execute(brief, CONTEXT_TOOL, {"section": "previousPackage"})["previousProposal"] is None
    initial, _ = generate(brief)
    proposal = deepcopy(brief["request"]["proposal"])
    proposal["equipmentRequirements"][0]["quantity"] += 1
    assert_code("generation_requirements_not_satisfied", lambda: execute(brief, PREVIEW_TOOL,
        {"requestKey": "rejected", "expectedLedgerRevision": initial["ledgerRevision"], "proposal": proposal}))
    assert execute(brief, CONTEXT_TOOL, {"section": "previousPackage"})["previousProposal"]["previewId"] == initial["previewId"]
    foreign = {**brief["binding"], "workspaceId": "foreign"}
    assert_code("generation_artifact_not_found", lambda: brief["service"].prior_package(brief["principal"], foreign))


def test_research_receipt_is_scoped_durable_and_not_review(brief, monkeypatch):
    execute(brief, POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None})
    calls = []
    def researched(**kwargs):
        calls.append(kwargs)
        return {"operation": kwargs["operation"], "requestedUrl": kwargs.get("url"),
                "sources": [{"url": "https://manufacturer.example/specs", "title": "Equipment specifications",
                             "retrieval": "fetched_document" if kwargs["operation"] == "read" else "search_result"}],
                "summary": "Illustrative research response used only by this unit test.", "citations": [], "complete": True,
                "reviewStatus": "pending", "productionEligible": False}
    monkeypatch.setattr(brief["agent"].exploration.researcher, "run", researched)
    args = {"query": "manual assembly bench specifications", "preferredDomains": []}
    result = execute(brief, SEARCH_TOOL, args)
    assert execute(brief, SEARCH_TOOL, args) == result
    assert len(calls) == 1
    read = execute(brief, READ_TOOL, {"researchRef": result["researchRef"], "sourceIndex": 0, "question": "What load conditions apply?"})
    assert calls[-1]["operation"] == "read" and calls[-1]["url"] == result["sources"][0]["url"]
    context = prepare(brief)
    context["researchRefs"] = [result["researchRef"]]
    assert_code("generation_research_read_required", lambda: execute(brief, PREPARE_TOOL, context))
    assert brief["binding"]["source"] is None
    context["researchRefs"] = [read["researchRef"]]
    proposed = execute(brief, PREPARE_TOOL, context)
    assert len(proposed["evidenceRegister"]) == 2
    assert all(item["reviewStatus"] == "pending" for item in proposed["evidenceRegister"])
    assert all(item["evidenceRefs"] == ["brief-interpretation"] for item in proposed["equipmentMappings"])
    assert not proposed["bindingsTruncated"]
    alternate = {**brief["binding"], "workspaceId": "another-workspace"}
    assert_code("generation_research_scope_mismatch", lambda: brief["agent"].exploration.load_research(brief["principal"], alternate, result["researchRef"]))


def test_consultation_catalog_and_disclosure_obligations_use_server_receipts(brief, monkeypatch):
    execute(brief, POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None})
    url = "https://manufacturer.example/technical-manual"
    monkeypatch.setattr(brief["agent"].exploration.researcher, "run", lambda **kwargs: {
        "operation": kwargs["operation"], "requestedUrl": kwargs.get("url"),
        "sources": [{"url": url, "title": "Technical manual",
                     "retrieval": "fetched_document" if kwargs["operation"] == "read" else "search_result"}],
        "summary": "Synthetic primary-source content for this contract test, not manufacturing evidence.",
        "citations": [], "complete": True, "reviewStatus": "pending", "productionEligible": False})
    result = execute(brief, SEARCH_TOOL, {"query": "manufacturer equipment documentation", "preferredDomains": []})
    result = execute(brief, READ_TOOL, {"researchRef": result["researchRef"], "sourceIndex": 0, "question": "What documented limits apply?"})
    context = prepare(brief)
    context["researchRefs"] = [result["researchRef"]]
    execute(brief, PREPARE_TOOL, context)
    proposal = brief["request"]["proposal"]
    for item in proposal["equipmentRequirements"]:
        item["evidenceRefs"].append("research-0")
    for name, subject, parameters in [
        ("catalog_only", brief["binding"]["layoutId"], {"required": True}),
        ("assumptions_disclosed", brief["binding"]["layoutId"], {"required": True}),
        ("source_consulted", "research-0", {"url": url}),
    ]:
        brief["record"]["requirements"].append({"requirementId": name, "sourceText": brief["message"],
            "kind": "hard_constraint", "disposition": "represented", "predicate": {"kind": name, "subjectId": subject, "parameters": parameters},
            "reason": None, "supersedes": []})
    invalid = deepcopy(brief["record"])
    invalid["requirements"][-1]["predicate"]["parameters"]["url"] = "https://manufacturer.example/not-retrieved"
    assert_code("generation_consultation_unbound", lambda: execute(brief, REQUIREMENTS_TOOL, invalid))
    assert brief["agent"]._ledger(brief["principal"], brief["binding"]) is None
    receipt, _ = generate(brief)
    assert receipt["planningNotes"]["sources"] == [{"evidenceRef": "research-0", "url": url, "title": "Technical manual"}]
    from ai_inspector.facility_layout.generation_requirements import evaluate_generation_requirements
    ledger = brief["agent"]._ledger(brief["principal"], brief["binding"])
    untrusted = evaluate_generation_requirements(ledger, proposal)
    assert untrusted["requirementsSatisfied"] is False, "Missing trusted context must not pass workflow obligations"
    incorrect = deepcopy(proposal)
    incorrect["equipmentRequirements"][0]["authoredSpacing"]["evidenceRef"] = "research-0"
    assert_code("generation_spacing_evidence_not_applicable", lambda: execute(brief, PREVIEW_TOOL, {
        "requestKey": "unsupported-clearance-attribution", "expectedLedgerRevision": ledger["ledgerRevision"], "proposal": incorrect}))
    prior = brief["service"].prior_package(brief["principal"], brief["binding"])
    assert prior["previewId"] == receipt["previewId"], "Refusal must retain the prior valid preview"


@pytest.mark.parametrize("url", ["file:///C:/secret", "http://localhost/a", "http://127.0.0.1/a", "https://user:pass@company.com/a",
    "https://10.0.0.1", "https://metadata.internal/", "https://[::1]/", "https://2130706433/", "https://example.com:8155/", "https://company.local/x"])
def test_research_rejects_non_public_targets(url):
    with pytest.raises(ResearchError):
        public_url(url)


def test_model_only_citations_cannot_impersonate_search():
    response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "A plausible claim",
        "citations": [{"url": "https://manufacturer.example/manual", "cited_text": "Fabricated"}]}]}
    with pytest.raises(ResearchError, match="No retrievable"):
        normalize_response(response, operation="search", query="specs", url=None, model="synthetic")


def test_real_source_blocks_filter_unretrieved_citations_and_report_partial():
    response = {"stop_reason": "pause_turn", "content": [
        {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://maker.example/manual", "title": "Manual"}]},
        {"type": "text", "text": "Findings", "citations": [
            {"url": "https://maker.example/manual", "cited_text": "Documented value"},
            {"url": "https://fake.example/", "cited_text": "Not retrieved"}]},
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "too_many_requests"}},
    ]}
    result = normalize_response(response, operation="search", query="specs", url=None, model="synthetic")
    assert not result["complete"] and result["errors"] == ["too_many_requests"]
    assert len(result["citations"]) == 1 and result["reviewStatus"] == "pending"


def test_source_truncation_keeps_cited_urls_and_never_orphans_citations():
    sources = [{"type": "web_search_result", "url": f"https://maker.example/doc-{index}", "title": f"Doc {index}"} for index in range(20)]
    response = {"stop_reason": "end_turn", "content": [
        {"type": "web_search_tool_result", "content": sources},
        {"type": "text", "text": "Findings", "citations": [
            {"url": item["url"], "cited_text": "Retrieved value"} for item in reversed(sources)]},
    ]}
    result = normalize_response(response, operation="search", query="specs", url=None, model="synthetic")
    urls = {item["url"] for item in result["sources"]}
    assert result["sources"][0]["url"] == sources[-1]["url"]
    assert len(urls) == 8 and result["truncated"]
    assert all(item["url"] in urls for item in result["citations"])
