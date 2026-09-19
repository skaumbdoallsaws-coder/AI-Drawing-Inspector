from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeEnrichmentCache,
    EnrichmentBudgetError,
    adapt_bridge_package,
    assert_authorization_matches_plan,
    authorize_enrichment_plan,
    build_enrichment_semantic_input,
    compile_deterministic_evidence,
    enrichment_process_reference_map,
    plan_enrichment_request,
    validate_package_documents,
)
from ai_inspector.assembly_knowledge.enrichment import (
    ENRICHMENT_PROMPT_VERSION,
    execute_economy_enrichment,
    validate_output_for_package,
)
from ai_inspector.assembly_knowledge.enrichment_schema import EnrichmentOutputError
from ai_inspector.assembly_knowledge.provider import (
    EnrichmentProviderError,
    FixtureMultimodalProvider,
)


PACKAGE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)
RESPONSE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "enrichment"
    / "economy_response.json"
)


def _documents(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    documents = compile_deterministic_evidence(
        adapt_bridge_package(
            PACKAGE_FIXTURE,
            source_root=source,
            root_assembly=root,
            product_id="tricycle",
        ).documents
    )
    documents["package.json"]["assetHashes"] = {
        "visuals/presentation/contact-sheet.png": "1" * 64,
    }
    documents["visual_manifest.json"]["contactSheets"] = [
        {
            "contactSheetId": "sheet-1",
            "assetPath": "visuals/presentation/contact-sheet.png",
            "assetHash": "1" * 64,
            "width": 1800,
            "height": 1300,
            "viewIds": [],
        }
    ]
    documents["visual_manifest.json"]["views"] = []
    return documents


def _response():
    return json.loads(RESPONSE_FIXTURE.read_text(encoding="ascii"))


def _plan_and_authorization(documents):
    plan = plan_enrichment_request(
        documents,
        provider="fixture",
        model="fixture-model-v1",
        prompt_version=ENRICHMENT_PROMPT_VERSION,
    )
    authorization = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="fixture-enrichment-1001",
        unknown_pricing_acknowledged=True,
    )
    assert authorization["authorized"] is True
    return plan, authorization


def test_fixture_output_is_strict_and_revision_bound(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    assert validate_output_for_package(_response(), documents)["schemaVersion"] == 1
    stale = _response()
    stale["sourceRevision"] = "f" * 64
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(stale, documents)
    assert exc.value.findings[0]["code"] == "stale_source_revision"


def test_compact_process_refs_are_resolved_before_validation(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    compact = _response()
    process_refs = enrichment_process_reference_map(
        documents["product_structure.json"]
    )

    def compact_ref(value):
        return process_refs.get(value, value)

    for row in compact["occurrenceRoles"]:
        row["occurrenceId"] = compact_ref(row["occurrenceId"])
    for field in (
        "functionalRelationships",
        "processBranches",
        "intermediateResults",
        "operationFamilies",
        "assumptions",
        "unresolvedQuestions",
    ):
        for row in compact[field]:
            for reference_field in (
                "occurrenceRefs",
                "inputOccurrenceRefs",
                "inputRefs",
                "subjectRefs",
            ):
                if reference_field in row:
                    row[reference_field] = [
                        compact_ref(ref) for ref in row[reference_field]
                    ]
            if "outputRef" in row:
                row["outputRef"] = compact_ref(row["outputRef"])

    assert validate_output_for_package(compact, documents) == _response()


def test_unknown_ids_and_manufacturing_values_are_rejected(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    invalid = _response()
    invalid["occurrenceRoles"][0]["occurrenceId"] = "occ-unknown"
    invalid["operationFamilies"][0]["torque"] = 8
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(invalid, documents)
    codes = {item["code"] for item in exc.value.findings}
    assert "unknown_occurrence_ref" in codes
    assert "unknown_field" in codes


def test_empty_process_candidate_collections_are_rejected(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    invalid = _response()
    invalid["processBranches"] = []
    invalid["intermediateResults"] = []
    invalid["operationFamilies"] = []
    invalid["unresolvedQuestions"] = []
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(invalid, documents)
    codes = {item["code"] for item in exc.value.findings}
    assert "process_branch_required" in codes
    assert "operation_family_required" in codes
    assert "process_input_coverage_missing" in codes
    assert "final_assembly_output_missing" in codes


def _semantic_pilot_response(documents, selected_occurrence_id: str):
    scoped = build_enrichment_semantic_input(
        documents,
        task_mode="semantic_pilot",
        selected_occurrence_ids=[selected_occurrence_id],
    )
    process_refs = enrichment_process_reference_map(
        documents["product_structure.json"]
    )
    interface = scoped["interfaces"][0]
    occurrence_refs = [process_refs[item] for item in interface["occurrenceRefs"]]
    return {
        "schemaVersion": 1,
        "sourceRevision": documents["package.json"]["sourceRevision"],
        "occurrenceRoles": [
            {
                "occurrenceId": process_refs[selected_occurrence_id],
                "role": "candidate support member",
                "function": "May support an adjacent constrained component.",
                "evidenceRefs": [],
                "assumptionRefs": [],
            }
        ],
        "functionalRelationships": [
            {
                "candidateKey": "relationship-candidate-1",
                "occurrenceRefs": occurrence_refs,
                "relationshipType": "candidate constrained interface",
                "description": "The supplied mate connects these occurrences.",
                "evidenceRefs": [],
                "assumptionRefs": [],
            }
        ],
        "jointArchetypes": [
            {
                "candidateKey": "joint-candidate-1",
                "interfaceId": interface["interfaceId"],
                "archetype": "candidate constrained joint",
                "description": "The mate may represent a constrained joint.",
                "evidenceRefs": [],
                "assumptionRefs": [],
            }
        ],
        "processBranches": [],
        "intermediateResults": [],
        "operationFamilies": [],
        "assumptions": [],
        "unresolvedQuestions": [],
    }


def test_semantic_pilot_scope_is_bounded_and_has_no_process_obligation(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    full = build_enrichment_semantic_input(documents)
    interface = documents["interface_graph.json"]["interfaces"][0]
    selected = interface["occurrenceRefs"][0]
    scoped = build_enrichment_semantic_input(
        documents,
        task_mode="semantic_pilot",
        selected_occurrence_ids=[selected],
    )
    scoped_ids = {item["occurrenceId"] for item in scoped["occurrences"]}
    assert scoped["taskMode"] == "semantic_pilot"
    assert scoped["requiredProcessInputRefs"] == []
    assert selected in scoped_ids
    assert set(interface["occurrenceRefs"]) <= scoped_ids
    assert documents["product_structure.json"]["rootOccurrenceId"] in scoped_ids
    assert len(scoped["occurrences"]) < len(full["occurrences"])


def test_semantic_pilot_compiles_reviewable_claims_without_replacing_process(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    selected = documents["interface_graph.json"]["interfaces"][0][
        "occurrenceRefs"
    ][0]
    plan = plan_enrichment_request(
        documents,
        provider="fixture",
        model="fixture-model-v1",
        prompt_version="semantic-pilot-v1",
        task_mode="semantic_pilot",
        changed_occurrence_ids=[selected],
    )
    assert plan["taskMode"] == "semantic_pilot"
    assert plan["selectedOccurrenceIds"] == [selected]
    assert plan["estimatedInputTokensPerCall"] < 24_000
    authorization = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="fixture-user",
        session_id="semantic-pilot-session",
        idempotency_key="semantic-pilot-1001",
        unknown_pricing_acknowledged=True,
    )
    original_process = copy.deepcopy(documents["process_candidates.json"])
    result = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=FixtureMultimodalProvider(
            [_semantic_pilot_response(documents, selected)]
        ),
    )
    enriched = result["documents"]
    assert enriched["package.json"]["readiness"] == documents["package.json"][
        "readiness"
    ]
    for field in ("claims", "branches", "intermediateResults", "operationFamilies"):
        assert enriched["process_candidates.json"][field] == original_process[field]
    model_claims = [
        item
        for item in enriched["functional_context.json"]["claims"]
        if item["generatedBy"]["kind"] == "model"
    ]
    assert len(model_claims) == 3
    assert {item["authority"] for item in model_claims} == {"supporting"}
    assert {item["reviewStatus"] for item in model_claims} == {"pending"}
    assert enriched["package.json"]["productionEligible"] is False


def test_process_candidates_must_cover_every_required_leaf(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    invalid = _response()
    invalid["operationFamilies"][0]["inputRefs"].remove(
        "occ-8d0010067c83ffed87397c32"
    )
    invalid["intermediateResults"][0]["inputOccurrenceRefs"].remove(
        "occ-8d0010067c83ffed87397c32"
    )
    invalid["unresolvedQuestions"] = []
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(invalid, documents)
    assert {item["code"] for item in exc.value.findings} == {
        "process_input_coverage_missing"
    }
    finding = next(
        item
        for item in exc.value.findings
        if item["code"] == "process_input_coverage_missing"
    )
    assert finding["details"]["occurrenceIds"] == [
        "occ-8d0010067c83ffed87397c32"
    ]


def test_process_candidates_require_one_final_root_output(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    missing = _response()
    missing["operationFamilies"][1]["outputRef"] = None
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(missing, documents)
    assert "final_assembly_output_missing" in {
        item["code"] for item in exc.value.findings
    }

    unfinished = _response()
    unfinished["operationFamilies"][1]["predecessorKeys"] = []
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(unfinished, documents)
    assert "final_assembly_output_missing" in {
        item["code"] for item in exc.value.findings
    }


def test_sequential_operations_may_update_the_same_root(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    valid = _response()
    valid["intermediateResults"] = []
    valid["operationFamilies"][0]["outputRef"] = (
        "occ-20a5f423ae5b61f24f3914ff"
    )
    valid["operationFamilies"][1]["inputRefs"] = [
        "occ-20a5f423ae5b61f24f3914ff"
    ]
    assert validate_output_for_package(valid, documents) == valid


def test_parallel_terminal_operations_may_share_the_root(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    valid = _response()
    valid["intermediateResults"] = []
    valid["operationFamilies"][0]["outputRef"] = (
        "occ-20a5f423ae5b61f24f3914ff"
    )
    valid["operationFamilies"][1]["inputRefs"] = [
        "occ-20a5f423ae5b61f24f3914ff"
    ]
    valid["operationFamilies"][1]["predecessorKeys"] = []
    assert validate_output_for_package(valid, documents) == valid


def test_required_occurrence_may_be_explicitly_unresolved(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    valid = _response()
    missing_ref = "occ-8d0010067c83ffed87397c32"
    valid["operationFamilies"][0]["inputRefs"].remove(missing_ref)
    valid["intermediateResults"][0]["inputOccurrenceRefs"].remove(missing_ref)
    valid["unresolvedQuestions"][0]["subjectRefs"].append(missing_ref)
    assert validate_output_for_package(valid, documents) == valid


def test_operation_precedence_must_be_acyclic(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    invalid = _response()
    invalid["operationFamilies"][0]["predecessorKeys"] = [
        "complete-tricycle-assembly"
    ]
    with pytest.raises(EnrichmentOutputError) as exc:
        validate_output_for_package(invalid, documents)
    assert "operation_precedence_cycle" in {
        item["code"] for item in exc.value.findings
    }


def test_one_call_compiles_only_inferred_supporting_candidates(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    provider = FixtureMultimodalProvider([_response()])
    result = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=provider,
    )
    assert len(provider.calls) == 1
    assert len(provider.calls[0]["images"]) == 1
    submitted = json.loads(provider.calls[0]["userText"])
    assert submitted["semanticInput"]["rootOccurrenceId"] == (
        "occ-20a5f423ae5b61f24f3914ff"
    )
    assert len(
        submitted["semanticInput"]["requiredProcessInputRefs"]
    ) == 3
    enriched = result["documents"]
    assert enriched["package.json"]["readiness"] == "planning_ready"
    assert enriched["package.json"]["productionEligible"] is False
    assert enriched["package.json"]["enrichmentReceipt"]["usage"] == {
        "inputTokens": 100,
        "outputTokens": 50,
        "totalTokens": 150,
        "imageCount": 1,
        "providerAttempts": 1,
        "schemaCorrections": 0,
    }
    model_claims = [
        item
        for name in ("functional_context.json", "process_candidates.json")
        for item in enriched[name]["claims"]
        if item["generatedBy"]["kind"] == "model"
    ]
    assert model_claims
    assert {item["knowledgeStatus"] for item in model_claims} == {"inferred"}
    assert {item["authority"] for item in model_claims} == {"supporting"}
    assert {item["reviewStatus"] for item in model_claims} == {"pending"}
    assert not [
        item
        for item in validate_package_documents(enriched)
        if item.get("severity") == "error"
    ]


def test_invalid_first_response_gets_one_image_free_schema_correction(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    malformed = _response()
    malformed["sourceRevision"] = "f" * 64
    provider = FixtureMultimodalProvider([malformed, _response()])
    result = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=provider,
    )
    assert len(provider.calls) == 2
    assert provider.calls[0]["images"]
    assert provider.calls[1]["images"] == []
    assert provider.calls[1]["correctionOnly"] is True
    correction = json.loads(provider.calls[1]["userText"])
    assert len(
        correction["semanticInput"]["requiredProcessInputRefs"]
    ) == 3
    assert result["usage"]["schemaCorrections"] == 1
    assert result["usage"]["providerAttempts"] == 2


def test_schema_correction_cannot_erase_process_scope(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    malformed = _response()
    malformed["sourceRevision"] = "f" * 64
    erased = _response()
    erased["processBranches"] = []
    erased["intermediateResults"] = []
    erased["operationFamilies"] = []
    provider = FixtureMultimodalProvider([malformed, erased])
    with pytest.raises(EnrichmentOutputError) as exc:
        execute_economy_enrichment(
            documents,
            package_dir=tmp_path,
            budget_plan=plan,
            authorization=authorization,
            provider=provider,
        )
    assert len(provider.calls) == 2
    assert provider.calls[1]["images"] == []
    assert provider.calls[1]["correctionOnly"] is True
    assert "operation_family_required" in {
        item["code"] for item in exc.value.findings
    }


def test_transient_failure_retries_once_and_permanent_failure_does_not(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    transient = FixtureMultimodalProvider(
        [_response(), _response()],
        errors=[
            EnrichmentProviderError(
                "fixture_timeout",
                "timeout",
                retryable=True,
            ),
            None,
        ],
    )
    result = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=transient,
    )
    assert len(transient.calls) == 2
    assert result["usage"]["providerAttempts"] == 2

    permanent = FixtureMultimodalProvider(
        [_response()],
        errors=[
            EnrichmentProviderError(
                "fixture_bad_request",
                "bad request",
                retryable=False,
            )
        ],
    )
    with pytest.raises(EnrichmentProviderError):
        execute_economy_enrichment(
            documents,
            package_dir=tmp_path,
            budget_plan=plan,
            authorization=authorization,
            provider=permanent,
        )
    assert len(permanent.calls) == 1


def test_cache_prevents_a_second_provider_call(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    cache = AssemblyKnowledgeEnrichmentCache(tmp_path / "cache")
    first_provider = FixtureMultimodalProvider([_response()])
    first = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=first_provider,
        cache=cache,
    )
    assert first["fromCache"] is False
    second_provider = FixtureMultimodalProvider([])
    second = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=second_provider,
        cache=cache,
    )
    assert second["fromCache"] is True
    assert second_provider.calls == []
    assert second["documents"]["package.json"]["enrichmentReceipt"]["fromCache"] is True


def test_stale_authorization_blocks_before_provider_invocation(
    tmp_path: Path,
) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    changed_plan = copy.deepcopy(plan)
    changed_plan["requestFingerprint"] = "f" * 64
    provider = FixtureMultimodalProvider([_response()])
    with pytest.raises(EnrichmentBudgetError):
        execute_economy_enrichment(
            documents,
            package_dir=tmp_path,
            budget_plan=changed_plan,
            authorization=authorization,
            provider=provider,
        )
    assert provider.calls == []


def test_authorization_helper_still_rejects_forged_receipt(tmp_path: Path) -> None:
    documents = _documents(tmp_path)
    plan, authorization = _plan_and_authorization(documents)
    forged = dict(authorization)
    forged["requestFingerprint"] = "0" * 64
    with pytest.raises(EnrichmentBudgetError):
        assert_authorization_matches_plan(plan, forged)
