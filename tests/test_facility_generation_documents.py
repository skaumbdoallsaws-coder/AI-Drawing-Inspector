from copy import deepcopy
import json

import pytest

from ai_inspector.facility_layout.generation_agent import generation_tool_specs, generation_provider_tools, CONTEXT_TOOL, PREVIEW_TOOL, REQUIREMENTS_TOOL
from ai_inspector.facility_layout.generation_exploration import DOCUMENT_TOOL, PREPARE_TOOL, CATALOG_TOOL
from ai_inspector.facility_layout.generation_research_policy import POLICY_TOOL
from tests.test_equipment_documents import library, request as reader_request, write_json
from tests.test_facility_generation_admission import case, assert_code
from tests.test_facility_generation_agent import chat, execute, generate
from tests.test_facility_generation_exploration import brief, prepare


def request(library, action="summary", **fields):
    args = reader_request(library, action, **fields)
    asset = {key: args.pop(key) for key in ("assetId", "assetDefinitionRevision")}
    return {**asset, "read": args}


@pytest.fixture
def documents(brief, library):
    asset = brief["context"]["equipmentMappings"][0]
    library["asset"] = {key: asset[key] for key in ("assetId", "assetDefinitionRevision")}
    library["index"]["bindings"][0].update(library["asset"])
    write_json(library["indexPath"], library["index"])
    brief["service"].equipment_documents = library["reader"]
    return brief, library


def test_tool_schemas_are_closed_and_do_not_require_local_evidence_for_every_plan(documents):
    from jsonschema import Draft202012Validator
    _, library = documents
    specs = {spec["name"]: spec["input_schema"] for spec in generation_tool_specs()}
    validator = Draft202012Validator(specs[DOCUMENT_TOOL])
    assert all(not {"oneOf", "allOf", "anyOf"}.intersection(schema) for schema in specs.values())
    for args in (request(library), request(library, "search", query="payload", startPage=1), request(library, "page", pageNumber=1, textOffset=0)):
        validator.validate(args)
        assert not validator.is_valid({**args, "path": "secret"})
    assert "localDocumentRefs" not in specs[PREPARE_TOOL]["required"]


@pytest.mark.parametrize("read", [None, [], {"action": "summary", "assetId": "asset-other"}])
def test_read_options_cannot_override_identity_or_pass_nonobjects(documents, read):
    brief, library = documents
    assert_code("generation_document_request_invalid", lambda: execute(brief, DOCUMENT_TOOL,
        {**request(library), "read": read}))


def test_summary_available_offline_and_receipt_retry_is_identical(documents, monkeypatch):
    brief, library = documents
    brief["message"] = "Do not search the web."
    execute(brief, POLICY_TOOL, {"expectedPolicyRevision": None, "decision": "deny", "sourceText": brief["message"]})
    monkeypatch.setattr(brief["agent"].exploration.researcher, "run", lambda **kwargs: pytest.fail("Unexpected web request"))
    catalog = execute(brief, CATALOG_TOOL, {"query": "", "offset": 0, "limit": 8})
    item = next(row for row in catalog["items"] if row["assetId"] == library["asset"]["assetId"])
    assert item["localDocuments"]["status"] == "registered"
    result = execute(brief, DOCUMENT_TOOL, request(library))
    assert result == execute(brief, DOCUMENT_TOOL, dict(reversed(list(request(library).items()))))
    assert result["productionEligible"] is False


def test_prepare_retains_evidence_but_does_not_grant_geometry_authority(documents):
    brief, library = documents
    summary = execute(brief, DOCUMENT_TOOL, request(library))
    proposed = prepare(brief)
    proposed["localDocumentRefs"] = [summary["localDocumentRef"]]
    receipt = execute(brief, PREPARE_TOOL, proposed)
    evidence = next(row for row in receipt["evidenceRegister"] if row["sourceType"] == "local_equipment_document")
    assert evidence["reviewStatus"] == "pending" and evidence["authority"] == "supporting"
    assert receipt["equipmentMappings"][0]["evidenceRefs"] == ["brief-interpretation"]
    generated, _ = generate(brief)
    assert generated["counts"]["placements"] == 2
    invalid = deepcopy(brief["request"]["proposal"])
    invalid["equipmentRequirements"][0]["authoredSpacing"]["evidenceRef"] = evidence["evidenceId"]
    assert_code("generation_spacing_evidence_not_applicable", lambda: execute(brief, PREVIEW_TOOL,
        {"requestKey": "unapproved-dimension", "expectedLedgerRevision": generated["ledgerRevision"], "proposal": invalid}))
    source, _, _ = brief["service"]._source(brief["principal"], brief["binding"]["siteId"], receipt["sourceContextRef"])
    assert source["localDocumentRefs"] == proposed["localDocumentRefs"]
    assert brief["service"].repository.artifact_pin_count(brief["principal"].tenant_id, brief["binding"]["siteId"], summary["localDocumentRef"]["artifactRevision"]) >= 2
    with (library["root"] / "summary.md").open("a") as stream:
        stream.write("stale")
    assert_code("equipment_document_revision_mismatch", lambda: brief["service"]._source(brief["principal"], brief["binding"]["siteId"], receipt["sourceContextRef"]))


def consultation_requirements(brief, consultations):
    return [{"requirementId": "consultation-" + str(index), "sourceText": brief["message"],
             "kind": "hard_constraint", "disposition": "represented", "reason": None, "supersedes": [],
             "predicate": {"kind": "local_document_consulted", "subjectId": entry["evidenceRef"],
                           "parameters": {key: entry[key] for key in ("assetId", "assetDefinitionRevision", "action")}}}
            for index, entry in enumerate(consultations)]


def consult_documents(brief, library):
    reads = [execute(brief, DOCUMENT_TOOL, request(library)),
             execute(brief, DOCUMENT_TOOL, request(library, "page", pageNumber=1, textOffset=0))]
    context = execute(brief, PREPARE_TOOL, {**prepare(brief), "localDocumentRefs": [read["localDocumentRef"] for read in reads]})
    brief["record"]["requirements"].extend(consultation_requirements(brief, context["localConsultations"]))
    return context


def test_local_consultations_reach_context_ledger_and_preview(documents):
    from ai_inspector.facility_layout.generation_requirements import evaluate_generation_requirements
    brief, library = documents
    context = consult_documents(brief, library)
    consultations = context["localConsultations"]
    assert [item["action"] for item in consultations] == ["summary", "page"]
    assert consultations[1]["documentRevision"] == library["doc"]["sha256"]
    assert execute(brief, CONTEXT_TOOL, {})["compactContext"]["localDocuments"] == consultations
    assert execute(brief, CONTEXT_TOOL, {"section": "localDocuments", "offset": 1, "limit": 1})["items"] == consultations[1:]
    preview, _ = generate(brief)
    assert preview["planningNotes"]["localDocuments"] == consultations
    assert preview["counts"]["placements"] == 2 and preview["saved"] is False
    ledger = brief["agent"]._ledger(brief["principal"], brief["binding"])
    ids = {item["requirementId"] for item in ledger["requirements"] if item["predicate"]["kind"] == "local_document_consulted"}
    result = evaluate_generation_requirements(ledger, brief["request"]["proposal"], execution_context={})
    assert all(not item["passed"] for item in result["checks"] if item["requirementId"] in ids)
    assert len([item for item in result["checks"] if item["requirementId"] in ids]) == 2


@pytest.mark.parametrize("changes", [
    {"action": "page"}, {"assetId": "asset-other"}, {"assetDefinitionRevision": "c" * 64},
])
def test_summary_model_and_revision_are_not_interchangeable(documents, changes):
    brief, library = documents
    consult_documents(brief, library)
    brief["record"]["requirements"][-2]["predicate"]["parameters"].update(changes)
    assert_code("generation_local_consultation_unbound", lambda: execute(brief, REQUIREMENTS_TOOL, brief["record"]))
    assert brief["agent"]._ledger(brief["principal"], brief["binding"]) is None


def test_local_read_cannot_impersonate_public_fetch(documents):
    brief, library = documents
    consult_documents(brief, library)
    brief["record"]["requirements"][-1]["predicate"] = {"kind": "source_consulted", "subjectId": "local-document-1",
                                                         "parameters": {"url": library["doc"]["url"]}}
    assert_code("generation_consultation_unbound", lambda: execute(brief, REQUIREMENTS_TOOL, brief["record"]))


@pytest.mark.parametrize("args", [{"action": "search", "query": "payload", "startPage": 1},
                                  {"action": "page", "pageNumber": 45, "textOffset": 0}])
def test_discovery_and_scans_cannot_be_used_as_document_reads(documents, args):
    brief, library = documents
    args = deepcopy(args)
    result = execute(brief, DOCUMENT_TOOL, request(library, args.pop("action"), **args))
    assert "localDocumentRef" not in result
    # Relabelling a discovery handle must still fail server-side admission.
    proposed = {**prepare(brief), "localDocumentRefs": [result["discoveryRef"]]}
    assert_code("generation_document_read_required", lambda: execute(brief, PREPARE_TOOL, proposed))


def test_document_receipts_cannot_cross_editor_scopes(documents):
    brief, library = documents
    result = execute(brief, DOCUMENT_TOOL, request(library))
    other = {**brief["binding"], "workspaceId": "different-editor"}
    assert_code("generation_document_scope_mismatch", lambda: brief["agent"].exploration.planning_documents(
        brief["principal"], other, [result["localDocumentRef"]]))
    assert_code("generation_source_catalog_stale", lambda: execute(brief, DOCUMENT_TOOL,
        {**request(library), "assetDefinitionRevision": "b" * 64}))


def test_reference_repair_is_returned_through_authorized_tool(documents):
    from ai_inspector.facility_layout.errors import FacilityValidationError
    brief, library = documents
    args = request(library, "page", pageNumber=1, textOffset=0)
    args["read"]["documentRevision"] = "b" * 64
    with pytest.raises(FacilityValidationError) as caught:
        execute(brief, DOCUMENT_TOOL, args)
    assert caught.value.details["failureKind"] == "reference_mismatch"
    args["read"].update(caught.value.details["registeredReference"])
    assert execute(brief, DOCUMENT_TOOL, args)["textStatus"] == "extracted"


def test_preflight_only_sends_relevant_schema_then_restores_full_toolkit():
    specs = generation_tool_specs()
    original = deepcopy(specs)
    for name in (CONTEXT_TOOL, POLICY_TOOL):
        narrowed = generation_provider_tools(specs, name)
        assert [item["name"] for item in narrowed] == [name]
        assert len(json.dumps(narrowed)) < len(json.dumps(specs)) * 0.1
    assert generation_provider_tools(specs, None) is specs
    assert specs == original
    assert_code("generation_preflight_tool_missing", lambda: generation_provider_tools([], POLICY_TOOL))


def test_local_source_cards_distinguish_summary_and_archived_page(documents):
    from ai_inspector.facility_layout.generation_presentation import generation_research_source_block
    brief, library = documents
    summary = execute(brief, DOCUMENT_TOOL, request(library))
    page = execute(brief, DOCUMENT_TOOL, request(library, "page", pageNumber=1, textOffset=0))
    event = lambda result: {"tool": DOCUMENT_TOOL, "status": "succeeded", "result": result}
    first = generation_research_source_block([event(summary)])["sources"][0]
    assert "underlying manual not opened" in first["specifications"]["Retrieval"]
    current = generation_research_source_block([event(summary), event(page), event(summary)])["sources"][0]
    assert current["specifications"]["Retrieval"] == "Archived PDF page 1"
    assert current["specifications"]["Document SHA-256"] == library["doc"]["sha256"]
    assert current["inferIdentity"] is False and current["publisher"] == ""
    assert list(current["specifications"])[:4] == ["Retrieval", "Scope", "Review", "Link"]
    assert "not an approved" in current["specifications"]["Review"]
    tail = execute(brief, DOCUMENT_TOOL, request(library, "page", pageNumber=1, textOffset=5))
    assert tail["nextTextOffset"] is None and not tail["complete"]
    partial = generation_research_source_block([event(tail)])["sources"][0]
    assert partial["specifications"]["Retrieval"].endswith("; truncated")
