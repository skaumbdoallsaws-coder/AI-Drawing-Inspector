"""Declared flow and document-read contracts; fixtures do not qualify live semantics."""
from copy import deepcopy

import pytest

from ai_inspector.facility_layout.generation_flow import check_process_sequence, require_process_coverage, FLOW_SCOPE
from ai_inspector.facility_layout.generation_requirements import build_generation_ledger, evaluate_generation_requirements
from ai_inspector.facility_layout.generation_agent import CONTEXT_TOOL, REQUIREMENTS_TOOL, PREVIEW_TOOL, REVISE_TOOL
from ai_inspector.facility_layout.generation_exploration import SEARCH_TOOL, READ_TOOL, PREPARE_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from ai_inspector.research.web import ResearchError
from tests.test_facility_layout_facility_planning import _package
from tests.test_facility_generation_admission import case, assert_code, admitted
from tests.test_facility_generation_agent import chat, execute, generate
from tests.test_facility_generation_exploration import brief, prepare
from tests.test_facility_generation_revision import correction


STEPS = ["receive-material", "assemble-product", "inspect-product"]


def test_sequence_checks_direction_and_reports_bounded_claim():
    package = _package()
    package["routes"][0]["direction"] = "one_way"
    result = check_process_sequence(package, STEPS)
    assert result["passed"] and result["scope"] == FLOW_SCOPE
    assert all(item["routeIds"] == [package["routes"][0]["routeId"]] for item in result["transfers"])


@pytest.mark.parametrize("change,code", [
    (lambda p: p["processSteps"][2].update(predecessorProcessStepIds=[]), "generation_process_precedence_missing"),
    (lambda p: p["processSteps"][1].update(departmentId="missing"), "generation_process_department_binding_missing"),
    (lambda p: p["departments"][1].update(processStepRefs=[]), "generation_process_department_binding_missing"),
    (lambda p: p["equipmentRequirements"][0].update(targetArea="Inspection"), "generation_process_resource_binding_mismatch"),
    (lambda p: p.update(routes=[]), "generation_process_material_route_missing"),
    (lambda p: p["routes"][0].update(routeKind="pedestrian"), "generation_process_material_route_missing"),
    (lambda p: p["routes"][0].update(processStepRefs=[]), "generation_process_material_route_missing"),
    (lambda p: p["routes"][0].update(sourceArea="Inspection", targetArea="Receiving", direction="one_way"), "generation_process_material_route_missing"),
    (lambda p: p["routes"][0].update(viaAreas=[]), "generation_process_material_route_missing"),
    (lambda p: p["departments"].append({**p["departments"][0], "departmentId": "ambiguous"}), "generation_process_material_route_missing"),
])
def test_missing_wrong_or_unbound_flow_is_not_accepted(change, code):
    package = _package()
    change(package)
    result = check_process_sequence(package, STEPS)
    assert not result["passed"]
    assert code in [item.get("code") for item in result["transfers"]]


def test_same_department_only_proves_precedence_not_station_transfer():
    package = _package()
    package["processSteps"][2]["departmentId"] = "assembly"
    package["departments"][1]["processStepRefs"].append("inspect-product")
    result = check_process_sequence(package, STEPS)
    assert result["passed"]
    assert result["transfers"][-1]["limitation"] == "intradepartment_transfer_not_evaluated"


def test_dense_process_feedback_is_bounded():
    steps = [{"processStepId": f"step-{index}", "predecessorProcessStepIds": [f"step-{prior}" for prior in range(index)]}
             for index in range(32)]
    with pytest.raises(Exception) as failure:
        require_process_coverage({"layoutId": "layout", "requirements": []}, {"processSteps": steps})
    assert failure.value.code == "generation_process_sequence_uncovered"
    assert len(failure.value.details["missingEdges"]) == 16
    assert failure.value.details["edgeCount"] == 496 and failure.value.details["truncated"] is True


def test_unrelated_route_segments_cannot_invent_a_material_junction():
    package = _package()
    route = package["routes"][0]
    route.update(sourceArea="Receiving", targetArea="Inspection", viaAreas=[], direction="one_way")
    package["routes"].append({**deepcopy(route), "routeId": "back-to-assembly", "sourceArea": "Inspection", "targetArea": "Assembly"})
    result = check_process_sequence(package, STEPS[:2])
    assert not result["passed"] and result["transfers"][0]["code"] == "generation_process_material_route_missing"


def test_parallel_branches_can_have_separate_sequence_requirements(case):
    context = deepcopy(case["context"])
    context["processSteps"][2]["predecessorProcessStepIds"] = [STEPS[0]]
    ledger = deepcopy(case["ledger"])
    sequence = next(item for item in ledger["requirements"] if item["predicate"]["kind"] == "process_sequence")
    sequence["predicate"]["parameters"]["processStepIds"] = STEPS[:2]
    other = deepcopy(sequence)
    other["requirementId"] = "sequence-2"
    other["predicate"]["parameters"]["processStepIds"] = [STEPS[0], STEPS[2]]
    ledger["requirements"].append(other)
    ledger = build_generation_ledger({key: value for key, value in ledger.items() if key != "ledgerRevision"})
    require_process_coverage(ledger, context)
    other["predicate"]["parameters"]["processStepIds"] = [STEPS[2], STEPS[0]]
    ledger["requirements"][-1] = other
    assert_code("generation_process_sequence_unbound", lambda: require_process_coverage(ledger, context))


def test_department_presence_cannot_silently_replace_sequence(chat):
    sequence = next(item for item in chat["record"]["requirements"] if item["predicate"]["kind"] == "process_sequence")
    sequence["predicate"] = {"kind": "department_presence", "subjectId": "assembly", "parameters": {"label": "Assembly"}}
    assert_code("generation_process_sequence_uncovered", lambda: execute(chat, REQUIREMENTS_TOOL, chat["record"]))
    assert chat["agent"]._ledger(chat["principal"], chat["binding"]) is None


def test_direct_admission_checks_sequence_too(case):
    case["request"]["proposal"]["routes"][0]["direction"] = "one_way"
    case["request"]["proposal"]["routes"][0].update(sourceArea="Inspection", targetArea="Receiving")
    assert_code("generation_requirements_not_satisfied", lambda: admitted(case))


def test_failed_correction_cannot_remove_process_flow(chat):
    initial, args = correction(chat)
    proposal = deepcopy(chat["request"]["proposal"])
    proposal["equipmentRequirements"][0]["quantity"] = 3
    proposal["routes"] = []
    assert_code("generation_unrequested_package_change", lambda: execute(chat, PREVIEW_TOOL, {
        "requestKey": "drop-route", "expectedLedgerRevision": args["expectedLedgerRevision"], "proposal": proposal}))
    assert chat["service"].prior_package(chat["principal"], chat["binding"])["previewId"] == initial["previewId"]
    revised = execute(chat, REVISE_TOOL, args)
    assert revised["counts"]["placements"] == 3
    assert revised["processValidation"] == {"scope": FLOW_SCOPE, "checkedSequenceCount": 1, "stationTransfersValidated": False}


@pytest.mark.parametrize("ids", [[], ["a"], ["a", "a"], [True, "b"]])
def test_sequence_schema_rejects_invalid_ids(case, ids):
    body = {key: deepcopy(value) for key, value in case["ledger"].items() if key != "ledgerRevision"}
    next(item for item in body["requirements"] if item["predicate"]["kind"] == "process_sequence")["predicate"]["parameters"]["processStepIds"] = ids
    with pytest.raises(Exception):
        build_generation_ledger(body)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(operation="search"), lambda r: r.update(complete=False),
    lambda r: r.update(requestedUrl="https://manufacturer.example/other"),
    lambda r: r["sources"][0].update(retrieval="search_result"),
])
def test_only_complete_bound_document_reads_can_supply_planning_evidence(brief, monkeypatch, mutation):
    url = "https://manufacturer.example/manual"
    result = {"operation": "read", "requestedUrl": url, "complete": True,
              "sources": [{"url": url, "title": "Manual", "retrieval": "fetched_document"}]}
    mutation(result)
    monkeypatch.setattr(brief["agent"].exploration, "load_research", lambda *args: result)
    with pytest.raises(Exception) as failure:
        brief["agent"].exploration.planning_research(brief["principal"], brief["binding"], [{"artifactId": "fixture"}])
    assert failure.value.code == "generation_research_read_required"
    assert failure.value.details["nextTool"] == READ_TOOL


def test_failed_read_can_recover_with_another_source_without_promoting_search(brief, monkeypatch):
    execute(brief, POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "inherit", "sourceText": None})
    urls = ["https://manufacturer.example/blocked", "https://manufacturer.example/manual"]
    def research(**kwargs):
        if kwargs["operation"] == "search":
            return {"operation": "search", "requestedUrl": None, "complete": True, "sources": [
                {"url": url, "title": "Document", "retrieval": "search_result"} for url in urls]}
        if kwargs["url"] == urls[0]:
            raise ResearchError("research_no_retrieved_sources", "Document unavailable")
        return {"operation": "read", "requestedUrl": urls[1], "complete": True, "sources": [
            {"url": urls[1], "title": "Manual", "retrieval": "fetched_document"}]}
    monkeypatch.setattr(brief["agent"].exploration.researcher, "run", research)
    found = execute(brief, SEARCH_TOOL, {"query": "public equipment manual", "preferredDomains": []})
    read_args = {"researchRef": found["researchRef"], "sourceIndex": 0, "question": "What is documented?"}
    assert_code("research_no_retrieved_sources", lambda: execute(brief, READ_TOOL, read_args))
    read_args["sourceIndex"] = 1
    read = execute(brief, READ_TOOL, read_args)
    request = prepare(brief)
    request["researchRefs"] = [read["researchRef"]]
    context = execute(brief, PREPARE_TOOL, request)
    assert context["reviewStatus"] == "pending" and not context["productionEligible"]
    result, _ = generate(brief)
    assert result["planningNotes"]["sources"] == [{"evidenceRef": "research-0", "url": urls[1], "title": "Manual"}]
