from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeRepository,
    FixtureMultimodalProvider,
    adapt_bridge_package,
    apply_review_action,
    authorize_enrichment_plan,
    build_process_map_evidence_context,
    compile_deterministic_evidence,
    execute_economy_enrichment,
    plan_enrichment_request,
    resolve_process_map_evidence_package,
)
from ai_inspector.assembly_knowledge.enrichment import ENRICHMENT_PROMPT_VERSION
from ai_inspector.process_map import (
    ProcessMapBuilderError,
    SemanticProcessPlanError,
    approve_process_map_proposal,
    build_semantic_process_plan_from_evidence,
    compile_semantic_process_plan,
    load_named_process_map,
    propose_semantic_process_map_preview,
    reset_process_map_builder_state_for_tests,
)
from ai_inspector.prompts.context import context_provider_origin


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


def _planning_ready_documents(tmp_path: Path):
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
    contact_sheet = b"fixture-contact-sheet"
    contact_sheet_hash = hashlib.sha256(contact_sheet).hexdigest()
    documents["package.json"]["assetHashes"] = {
        "visuals/presentation/contact-sheet.png": contact_sheet_hash,
    }
    documents["visual_manifest.json"]["contactSheets"] = [
        {
            "contactSheetId": "sheet-1",
            "assetPath": "visuals/presentation/contact-sheet.png",
            "assetHash": contact_sheet_hash,
            "width": 1800,
            "height": 1300,
            "viewIds": [],
        }
    ]
    documents["visual_manifest.json"]["views"] = []
    budget = plan_enrichment_request(
        documents,
        provider="fixture",
        model="fixture-model-v1",
        prompt_version=ENRICHMENT_PROMPT_VERSION,
    )
    authorization = authorize_enrichment_plan(
        budget,
        explicit_approval=True,
        user_id="fixture-user",
        session_id="fixture-session",
        idempotency_key="p6-enrichment",
        unknown_pricing_acknowledged=True,
    )
    response = json.loads(RESPONSE_FIXTURE.read_text(encoding="ascii"))
    result = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=budget,
        authorization=authorization,
        provider=FixtureMultimodalProvider([response]),
    )
    return (
        result["documents"],
        source,
        {"visuals/presentation/contact-sheet.png": contact_sheet},
    )


def _process_structure(documents) -> dict:
    occurrences = documents["product_structure.json"]["occurrences"]
    by_id = {item["occurrenceId"]: item for item in occurrences}

    def level(item):
        depth = 0
        parent = item.get("parentOccurrenceId")
        while parent:
            depth += 1
            parent = by_id[parent].get("parentOccurrenceId")
        return 3 if item.get("kind") == "part" else depth

    return {
        "schemaVersion": 1,
        "productId": "tricycle",
        "productName": "Tricycle",
        "occurrences": [
            {
                "occurrenceId": item["occurrenceId"],
                "parentOccurrenceId": item.get("parentOccurrenceId"),
                "itemId": item.get("itemId"),
                "name": item.get("name"),
                "kind": item.get("kind"),
                "level": level(item),
                "partIds": (
                    [item["itemId"]]
                    if item.get("kind") == "part" and item.get("itemId")
                    else []
                ),
            }
            for item in occurrences
        ],
    }


def _write_process_product(training_root: Path, documents) -> None:
    product_dir = training_root / "tricycle"
    product_dir.mkdir(parents=True, exist_ok=True)
    structure = _process_structure(documents)
    nodes = [
        {
            "nodeId": item["occurrenceId"],
            "level": item["level"],
            "name": item["name"],
            "parentNodeId": item["parentOccurrenceId"],
            "partIds": item["partIds"],
        }
        for item in structure["occurrences"]
    ]
    (product_dir / "tricycle_process_map_working_draft.json").write_text(
        json.dumps(
            {
                "schemaVersion": "fixture-process-map-1",
                "productId": "tricycle",
                "productName": "Tricycle",
                "nodes": nodes,
            },
            indent=2,
        )
        + "\n",
        encoding="ascii",
    )
    (product_dir / "tricycle_product_structure.json").write_text(
        json.dumps(structure, indent=2) + "\n",
        encoding="ascii",
    )
    (product_dir / "tricycle_unique_items.json").write_text(
        json.dumps(
            {
                "items": [
                    {"partId": item["itemId"]}
                    for item in structure["occurrences"]
                    if item.get("kind") == "part" and item.get("itemId")
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="ascii",
    )


def _semantic_plan(resolved) -> dict:
    context = resolved["context"]
    documents = resolved["documents"]
    structure = documents["product_structure.json"]
    root_id = structure["rootOccurrenceId"]
    leaf_ids = sorted(
        item["occurrenceId"]
        for item in structure["occurrences"]
        if item.get("kind") == "part"
    )
    operation = documents["process_candidates.json"]["operationFamilies"][0]
    branch = documents["process_candidates.json"]["branches"][0]
    assumption_ids = list(operation.get("assumptionIds", []))
    assumptions_by_id = {
        item["id"]: item
        for item in documents["process_candidates.json"]["assumptions"]
    }
    return {
        "schemaVersion": 1,
        "planId": "plan-tricycle-fixture",
        "evidenceBinding": {
            field: resolved["binding"][field]
            for field in (
                "packageId",
                "packageRevision",
                "sourceRevision",
                "evidenceFingerprint",
                "contextFingerprint",
            )
        },
        "scope": {
            "assemblyOccurrenceId": root_id,
            "label": "Tricycle",
        },
        "requiredOccurrences": [
            {
                "occurrenceId": occurrence_id,
                "quantity": 1,
                "role": "input",
                "knowledgeStatus": "derived",
                "evidence": [
                    {
                        "sourceType": "assembly_structure",
                        "sourceRef": context["identity"]["sourceRevision"],
                        "supports": "component-membership",
                    }
                ],
            }
            for occurrence_id in leaf_ids
        ],
        "operations": [
            {
                "id": operation["operationId"],
                "operationType": "operation",
                "label": operation["label"],
                "inputs": [
                    {"ref": occurrence_id, "type": "occurrence"}
                    for occurrence_id in leaf_ids
                ],
                "output": {"ref": root_id, "type": "occurrence"},
                "branchId": branch["branchId"],
                "stageIndex": 1,
                "knowledgeStatus": "inferred",
                "evidence": [
                    {
                        "sourceType": "domain_heuristic",
                        "sourceRef": operation["claimId"],
                        "supports": "candidate-operation",
                    }
                ],
                "assumptionIds": assumption_ids,
                "properties": {},
            }
        ],
        "intermediateResults": [],
        "junctions": [],
        "branches": [
            {"id": branch["branchId"], "label": branch["label"]}
        ],
        "evidence": [],
        "assumptions": [
            {
                "id": assumption_id,
                "text": assumptions_by_id[assumption_id]["text"],
            }
            for assumption_id in assumption_ids
        ],
        "layoutHints": [
            {
                "ref": operation["operationId"],
                "branchId": branch["branchId"],
                "stageIndex": 1,
            }
        ],
        "unresolvedQuestions": list(
            documents["process_candidates.json"]["unresolvedQuestions"]
        ),
    }


def _prepared_runtime(tmp_path: Path):
    documents, source, assets = _planning_ready_documents(tmp_path / "input")
    training_root = tmp_path / "training"
    _write_process_product(training_root, documents)
    repository = AssemblyKnowledgeRepository(training_root)
    repository.write(documents, assets=assets)
    repository.bind_source_root("tricycle", documents["package.json"]["packageId"], source)
    resolved = resolve_process_map_evidence_package(
        training_root,
        "tricycle",
        require_planning_ready=True,
        require_current_sources=True,
    )
    assert resolved is not None
    return training_root, repository, resolved


def test_trusted_context_exposes_reviewable_process_candidates(tmp_path: Path):
    documents, _, _ = _planning_ready_documents(tmp_path)
    context = build_process_map_evidence_context(documents)
    assert context["identity"]["readiness"] == "planning_ready"
    assert len(context["identity"]["contextFingerprint"]) == 64
    assert context["processCandidates"]["operationFamilies"]
    operation = context["processCandidates"]["operationFamilies"][0]
    assert operation["knowledgeStatus"] == "inferred"
    assert operation["authority"] == "supporting"
    assert operation["reviewStatus"] == "pending"
    assert context["assumptions"]
    assert context["unresolvedQuestions"]
    assert context["semanticBoundary"]["cadFactsDoNotEstablish"]
    assert context_provider_origin("process_map.evidence") == "server"


def test_semantic_plan_binds_exact_assembly_knowledge_identity(tmp_path: Path):
    training_root, _, resolved = _prepared_runtime(tmp_path)
    loaded = load_named_process_map(training_root, "tricycle", "default")
    plan = _semantic_plan(resolved)
    compiled = compile_semantic_process_plan(
        plan,
        scope_occurrence_id=plan["scope"]["assemblyOccurrenceId"],
        base_revision=loaded["revision"],
        process_map=loaded["map"],
        product_structure=loaded["productStructure"],
        structure_revision=loaded["structureRevision"],
        assembly_knowledge=resolved,
    )
    assert compiled["binding"]["assemblyKnowledge"] == plan["evidenceBinding"]
    assert compiled["summary"]["requiredOccurrenceCount"] == 3
    stale = json.loads(json.dumps(plan))
    stale["evidenceBinding"]["packageRevision"] = "f" * 64
    with pytest.raises(SemanticProcessPlanError) as error:
        compile_semantic_process_plan(
            stale,
            scope_occurrence_id=plan["scope"]["assemblyOccurrenceId"],
            base_revision=loaded["revision"],
            process_map=loaded["map"],
            product_structure=loaded["productStructure"],
            structure_revision=loaded["structureRevision"],
            assembly_knowledge=resolved,
        )
    assert "stale_assembly_knowledge_binding" in {
        item["code"] for item in error.value.findings
    }


def test_trusted_candidates_compile_into_complete_semantic_plan(tmp_path: Path):
    training_root, _, resolved = _prepared_runtime(tmp_path)
    loaded = load_named_process_map(training_root, "tricycle", "default")
    scope_id = resolved["context"]["scope"]["rootOccurrenceId"]
    plan = build_semantic_process_plan_from_evidence(
        resolved["context"],
        scope_occurrence_id=scope_id,
    )
    compiled = compile_semantic_process_plan(
        plan,
        scope_occurrence_id=scope_id,
        base_revision=loaded["revision"],
        process_map=loaded["map"],
        product_structure=loaded["productStructure"],
        structure_revision=loaded["structureRevision"],
        assembly_knowledge=resolved,
    )
    assert compiled["summary"]["requiredOccurrenceCount"] == 3
    assert compiled["summary"]["operationCount"] == 2
    assert compiled["summary"]["inferredOperationCount"] == 2
    assert compiled["binding"]["assemblyKnowledge"] == plan["evidenceBinding"]


def test_trusted_converging_candidates_create_parallel_junction(tmp_path: Path):
    _, _, resolved = _prepared_runtime(tmp_path)
    context = json.loads(json.dumps(resolved["context"]))
    scope_id = context["scope"]["rootOccurrenceId"]
    occurrence_ids = sorted(
        str(item["occurrenceId"])
        for item in context["occurrences"]
        if item.get("kind") == "part"
    )
    assert len(occurrence_ids) == 3
    source_claim = context["processCandidates"]["operationFamilies"][0][
        "claimId"
    ]
    context["processCandidates"] = {
        "operationFamilies": [
            {
                "operationId": "prepare-left",
                "claimId": source_claim,
                "label": "Prepare left branch",
                "inputRefs": occurrence_ids[:1],
                "outputRef": "state-left",
                "predecessorOperationIds": [],
                "branchId": "left",
                "knowledgeStatus": "inferred",
                "assumptionIds": [],
            },
            {
                "operationId": "prepare-right",
                "claimId": source_claim,
                "label": "Prepare right branch",
                "inputRefs": occurrence_ids[1:],
                "outputRef": "state-right",
                "predecessorOperationIds": [],
                "branchId": "right",
                "knowledgeStatus": "inferred",
                "assumptionIds": [],
            },
            {
                "operationId": "join-branches",
                "claimId": source_claim,
                "label": "Join prepared branches",
                "inputRefs": [],
                "outputRef": scope_id,
                "predecessorOperationIds": [
                    "prepare-left",
                    "prepare-right",
                ],
                "branchId": "main",
                "knowledgeStatus": "inferred",
                "assumptionIds": [],
            },
        ],
        "intermediateResults": [
            {
                "intermediateResultId": "state-left",
                "label": "Prepared left branch",
            },
            {
                "intermediateResultId": "state-right",
                "label": "Prepared right branch",
            },
        ],
        "branches": [
            {"branchId": "left", "label": "Left"},
            {"branchId": "right", "label": "Right"},
            {"branchId": "main", "label": "Main"},
        ],
    }

    plan = build_semantic_process_plan_from_evidence(
        context,
        scope_occurrence_id=scope_id,
    )
    assert len(plan["junctions"]) == 1
    junction = plan["junctions"][0]
    assert junction["junctionType"] == "parallel_and"
    assert junction["inputs"] == ["state-left", "state-right"]
    assert junction["outputs"] == ["join-branches"]


def test_unknown_package_evidence_is_rejected(tmp_path: Path):
    training_root, _, resolved = _prepared_runtime(tmp_path)
    loaded = load_named_process_map(training_root, "tricycle", "default")
    plan = _semantic_plan(resolved)
    plan["operations"][0]["evidence"][0]["sourceRef"] = "invented-evidence"
    with pytest.raises(SemanticProcessPlanError) as error:
        compile_semantic_process_plan(
            plan,
            scope_occurrence_id=plan["scope"]["assemblyOccurrenceId"],
            base_revision=loaded["revision"],
            process_map=loaded["map"],
            product_structure=loaded["productStructure"],
            structure_revision=loaded["structureRevision"],
            assembly_knowledge=resolved,
        )
    assert "semantic_evidence_ref_unknown" in {
        item["code"] for item in error.value.findings
    }


def test_package_revision_change_invalidates_builder_approval(tmp_path: Path):
    reset_process_map_builder_state_for_tests()
    training_root, repository, resolved = _prepared_runtime(tmp_path)
    loaded = load_named_process_map(training_root, "tricycle", "default")
    plan = _semantic_plan(resolved)
    proposal = propose_semantic_process_map_preview(
        training_root,
        "tricycle",
        "default",
        loaded["revision"],
        scope_occurrence_id=plan["scope"]["assemblyOccurrenceId"],
        semantic_plan=plan,
    )
    assert proposal["semanticBinding"]["assemblyKnowledge"] == plan[
        "evidenceBinding"
    ]
    assert load_named_process_map(
        training_root, "tricycle", "default"
    )["map"]["canvasNodes"] == []

    pending_claim = next(
        item
        for item in resolved["documents"]["process_candidates.json"]["claims"]
        if item.get("reviewStatus") == "pending"
    )
    revised = apply_review_action(
        resolved["documents"],
        base_revision=resolved["binding"]["packageRevision"],
        source_revision=resolved["binding"]["sourceRevision"],
        claim_id=pending_claim["claimId"],
        action="defer",
        actor="fixture-user",
        timestamp="2026-07-25T12:00:00Z",
    )
    repository.write(
        revised,
        base_revision=resolved["binding"]["packageRevision"],
    )
    with pytest.raises(ProcessMapBuilderError) as error:
        approve_process_map_proposal(
            training_root,
            proposal["proposalId"],
            product_id="tricycle",
            map_id="default",
            base_revision=proposal["baseRevision"],
            diff_hash_value=proposal["diffHash"],
            user_id="fixture-user",
            session_id="fixture-session",
            idempotency_key="p6-stale-package",
            explicit_approval=True,
            semantic_binding_hash=proposal["semanticBindingHash"],
        )
    assert error.value.code == "assembly_knowledge_stale"
    assert load_named_process_map(
        training_root, "tricycle", "default"
    )["map"]["canvasNodes"] == []
    reset_process_map_builder_state_for_tests()
