"""Real-kernel correction contracts; no provider or product-specific recipes."""
from copy import deepcopy

import jsonschema
import pytest

from ai_inspector.facility_layout.generation_agent import (
    CONTEXT_TOOL, REQUIREMENTS_TOOL, REVISE_TOOL, generation_tool_specs, generation_turn_outcome,
)
from ai_inspector.facility_layout.generation_requirements import (
    build_generation_ledger, evaluate_generation_requirements, validate_generation_amendment,
)
from tests.test_facility_generation_admission import case, assert_code
from tests.test_facility_generation_agent import chat, execute, generate
from tests.test_facility_generation_requirements import body, amended, assert_error


def correction(chat):
    preview, _ = generate(chat)
    prior = execute(chat, CONTEXT_TOOL, {"section": "requirements"})["items"]
    old = next(item for item in prior if item["predicate"]["kind"] == "resource_quantity")
    chat.update(message="Use three benches instead and keep everything else.", turn="correction-2")
    common = {"sourceText": chat["message"], "kind": "hard_constraint", "disposition": "represented", "reason": None}
    receipt = execute(chat, REQUIREMENTS_TOOL, {"expectedLedgerRevision": preview["ledgerRevision"], "requirements": [
        {**common, "requirementId": "quantity", "supersedes": [old["requirementId"]],
         "predicate": {**old["predicate"], "parameters": {"quantity": 3}}},
        {**common, "requirementId": "preservation", "supersedes": [],
         "predicate": {"kind": "preserve_prior_requirements", "subjectId": chat["binding"]["ledgerId"],
                       "parameters": {"exceptRequirementIds": [old["requirementId"]]}}},
    ]})
    return preview, {"requestKey": "revised-count", "expectedLedgerRevision": receipt["ledgerRevision"],
        "previewId": preview["previewId"], "previewRevision": preview["previewRevision"],
        "changes": [{"collection": "equipmentRequirements", "entityId": old["predicate"]["subjectId"], "values": {"quantity": 3}}]}


def test_semantic_revision_preserves_every_other_field_and_durable_retry(chat, monkeypatch):
    initial, args = correction(chat)
    original = deepcopy(chat["request"]["proposal"])
    revised = execute(chat, REVISE_TOOL, args)
    assert revised["counts"]["placements"] == 3
    assert revised["candidateRevision"] != initial["candidateRevision"]
    package = chat["service"].prior_package(chat["principal"], chat["binding"])["package"]
    expected = deepcopy(original)
    expected["equipmentRequirements"][0]["quantity"] = 3
    assert package == expected
    old = chat["service"].prior_package(chat["principal"], chat["binding"], preview_ref={
        "previewId": initial["previewId"], "previewRevision": initial["previewRevision"]})
    assert old["package"] == original
    monkeypatch.setattr(chat["host"].service, "preview_operations", lambda *a, **k: pytest.fail("Retry recompiled"))
    assert execute(chat, REVISE_TOOL, dict(reversed(list(args.items())))) == revised
    assert generation_turn_outcome([{"tool": REVISE_TOOL, "status": "succeeded"}], preview_available=True)["status"] == "preview_ready"


@pytest.mark.parametrize("mutation,code", [
    (lambda a: a.update(expectedLedgerRevision="0" * 64), "generation_ledger_revision_conflict"),
    (lambda a: a.update(previewRevision="0" * 64), "generation_prior_proposal_mismatch"),
    (lambda a: a["changes"][0]["values"].update(x=10), "generation_revision_changes_invalid"),
    (lambda a: a["changes"][0].update(entityId="missing"), "generation_revision_target_missing"),
    (lambda a: a["changes"].append(deepcopy(a["changes"][0])), "generation_revision_changes_invalid"),
    (lambda a: a.update(changes=[]), "generation_revision_changes_invalid"),
    (lambda a: a["changes"][0]["values"].update(quantity=2), "generation_requirements_not_satisfied"),
    (lambda a: a["changes"][0]["values"].update(quantity=True), "generation_requirements_not_satisfied"),
])
def test_invalid_revision_cannot_replace_prior_candidate(chat, mutation, code):
    initial, args = correction(chat)
    mutation(args)
    assert_code(code, lambda: execute(chat, REVISE_TOOL, args))
    assert chat["service"].prior_package(chat["principal"], chat["binding"])["previewId"] == initial["previewId"]


def test_revision_cannot_weaken_an_unmodified_spacing_constraint(chat):
    _, args = correction(chat)
    args["changes"][0]["values"]["authoredSpacing"] = {
        **chat["request"]["proposal"]["equipmentRequirements"][0]["authoredSpacing"], "value": 0.1}
    assert_code("generation_requirements_not_satisfied", lambda: execute(chat, REVISE_TOOL, args))


def test_revision_still_requires_current_user_turn(chat):
    assert_code("generation_turn_not_recorded", lambda: execute(chat, REVISE_TOOL, {}))
    _, args = correction(chat)
    chat.update(message="Now use four benches.", turn="correction-3")
    assert_code("generation_turn_not_recorded", lambda: execute(chat, REVISE_TOOL, args))


def preservation_ledger():
    before = build_generation_ledger(body())
    after = amended(before)
    after = {key: value for key, value in after.items() if key != "ledgerRevision"}
    after["requirements"].append({"requirementId": "keep-others", "source": deepcopy(after["requirements"][-1]["source"]),
        "kind": "hard_constraint", "disposition": "represented", "reason": None, "supersededBy": [],
        "predicate": {"kind": "preserve_prior_requirements", "subjectId": before["ledgerId"],
                      "parameters": {"exceptRequirementIds": ["R-1"]}}})
    return before, after


def test_preservation_is_a_checked_amendment_not_waiver_or_permanent_freeze():
    before, body_after = preservation_ledger()
    after = build_generation_ledger(body_after)
    validate_generation_amendment(before, after)
    package = {"equipmentRequirements": [{"requirementId": "assembly-benches", "quantity": 3}]}
    assert evaluate_generation_requirements(after, package)["requirementsSatisfied"]
    package["equipmentRequirements"][0]["quantity"] = 2
    assert not evaluate_generation_requirements(after, package)["requirementsSatisfied"]
    later = deepcopy(body_after)
    later["parentLedgerRevision"] = after["ledgerRevision"]
    later["turns"].append({"turnId": "turn-3", "text": "Use four benches."})
    successor = deepcopy(later["requirements"][1])
    later["requirements"][1].update(disposition="superseded", reason="User changed count", supersededBy=["R-3"])
    successor.update(requirementId="R-3", source={"turnId": "turn-3", "start": 0, "end": 17})
    successor["predicate"]["parameters"]["quantity"] = 4
    later["requirements"].append(successor)
    validate_generation_amendment(after, build_generation_ledger(later))


@pytest.mark.parametrize("exceptions", [[], ["missing"], ["R-1", "R-2"], ["R-1", "R-1"]])
def test_preservation_exceptions_cannot_hide_extra_changes(exceptions):
    _, value = preservation_ledger()
    value["requirements"][-1]["predicate"]["parameters"]["exceptRequirementIds"] = exceptions
    assert_error("generation_requirement_preservation_invalid", lambda: build_generation_ledger(value))


def test_published_requirement_schema_rejects_runtime_invalid_combinations(chat):
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == REQUIREMENTS_TOOL)
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors(chat["record"]))
    invalid = deepcopy(chat["record"])
    invalid["requirements"][0]["predicate"] = None
    assert list(validator.iter_errors(invalid))
    invalid = deepcopy(chat["record"])
    invalid["requirements"][0]["reason"] = "A hard constraint cannot be an assumption rationale."
    assert list(validator.iter_errors(invalid))
    invalid = deepcopy(chat["record"])
    invalid["requirements"][0]["kind"] = "assumption"
    assert list(validator.iter_errors(invalid))
    invalid = deepcopy(chat["record"])
    invalid["requirements"][1]["kind"] = "hard_constraint"
    assert list(validator.iter_errors(invalid))
    unresolved = {"expectedLedgerRevision": None, "requirements": [{"requirementId": "gap", "sourceText": "Missing evidence.",
        "kind": "unknown", "disposition": "needs_clarification", "predicate": None, "reason": "Which configuration?", "supersedes": []}]}
    assert not list(validator.iter_errors(unresolved))


def test_revision_schema_validates_only_semantic_fields(chat):
    _, args = correction(chat)
    schema = next(item["input_schema"] for item in generation_tool_specs() if item["name"] == REVISE_TOOL)
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors(args))
    args["changes"][0]["values"]["coordinates"] = {"x": 1, "z": 2}
    assert list(validator.iter_errors(args))
