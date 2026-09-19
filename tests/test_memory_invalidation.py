from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_inspector.memory.invalidation import (
    AUTHORIZATION_KINDS,
    INVALIDATION_ACTIONS,
    REVISION_INVALIDATION_MATRIX,
    REVISION_VECTOR_FIELDS,
    WORKFLOW_STAGE_POLICIES,
    apply_invalidation_action,
    build_reconciliation_event,
    changed_revision_dependencies,
    filter_stale_evidence_refs,
    normalize_revision_vector,
    reconcile_continuity_summary,
    revalidate_entities,
    revalidate_referents,
    revalidate_workflow_stage,
    revision_vector_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "memory"


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="ascii"))


def test_registered_stage_policies_exactly_match_the_frozen_contract() -> None:
    fixture = _fixture("workflow-stage-revalidation-v1.json")
    assert tuple(fixture["dependencyVocabulary"]) == REVISION_VECTOR_FIELDS
    assert set(fixture["authorizationKinds"]) == AUTHORIZATION_KINDS
    assert set(WORKFLOW_STAGE_POLICIES) == {
        item["workflowId"] for item in fixture["workflows"]
    }

    for expected in fixture["workflows"]:
        policy = WORKFLOW_STAGE_POLICIES[expected["workflowId"]]
        assert policy.version == expected["workflowVersion"]
        assert policy.first_stage == expected["firstStage"]
        assert list(policy.stages) == [item["stage"] for item in expected["stages"]]
        for stage_fixture in expected["stages"]:
            stage = policy.stages[stage_fixture["stage"]]
            assert stage.dependencies == frozenset(stage_fixture["dependencies"])
            assert stage.authorization_kind == stage_fixture["authorizationKind"]
            assert stage.safe_predecessor == stage_fixture["safePredecessor"]
            if stage.authorization_kind in AUTHORIZATION_KINDS:
                assert stage.safe_predecessor in policy.stages


def test_all_frozen_stage_revalidation_cases_are_deterministic() -> None:
    fixture = _fixture("workflow-stage-revalidation-v1.json")
    for case in fixture["revalidationCases"]:
        result = revalidate_workflow_stage(
            case["workflowId"],
            case["currentStage"],
            case["changedDependencies"],
        )
        assert result.stage == case["expectedStage"], case["caseId"]
        assert result.event == case["expectedEvent"], case["caseId"]


def test_invalidation_dispatcher_has_a_closed_vocabulary_and_defined_behavior() -> None:
    fixture = _fixture("revision-invalidation-matrix-v1.json")
    assert set(fixture["actions"]) == INVALIDATION_ACTIONS
    assert {
        action
        for item in fixture["items"]
        for dimension, action in item.items()
        if dimension in fixture["dimensions"]
    } == INVALIDATION_ACTIONS
    assert {
        item["item"]: {
            dimension: item[dimension]
            for dimension in fixture["dimensions"]
        }
        for item in fixture["items"]
    } == REVISION_INVALIDATION_MATRIX

    item = {
        "name": "objective",
        "value": {"id": "kept"},
        "dependencies": ["processMapRevision"],
    }
    current = {
        "defaults": {"objective": {"id": "reset"}},
        "revalidator": lambda value, changed: {
            **value,
            "revalidated": sorted(changed),
        },
        "sameScope": True,
    }
    changed = {"processMapRevision"}

    reset = apply_invalidation_action("reset", item, current, changed)
    assert reset.value == {"id": "reset"} and reset.active
    preserve = apply_invalidation_action("preserve", item, current, changed)
    assert preserve.value == {"id": "kept"} and preserve.active
    revalidated = apply_invalidation_action("revalidate", item, current, changed)
    assert revalidated.value["revalidated"] == ["processMapRevision"]
    assert not apply_invalidation_action("invalidate", item, current, changed).active
    assert not apply_invalidation_action(
        "invalidate_affected", item, current, changed
    ).active
    assert apply_invalidation_action(
        "invalidate_affected", item, current, {"drawingRevision"}
    ).active
    audit = apply_invalidation_action("retain_audit_only", item, current, changed)
    assert audit.audit_only and not audit.active
    assert not apply_invalidation_action("never_retain", item, current, changed).active
    assert apply_invalidation_action("scope_gate", item, current, changed).active
    for action in ("mark_stale_refs", "mark_stale_decisions"):
        result = apply_invalidation_action(action, item, current, changed)
        assert result.active and result.stale
    with pytest.raises(ValueError, match="unknown invalidation action"):
        apply_invalidation_action("invented", item, current, changed)


def test_revision_vectors_are_closed_canonical_and_detect_removals() -> None:
    left = {
        "processMapRevision": "map-a",
        "productStructureRevision": "structure-a",
    }
    reordered = {
        "productStructureRevision": "structure-a",
        "processMapRevision": "map-a",
    }
    assert normalize_revision_vector(left) == normalize_revision_vector(reordered)
    assert revision_vector_sha256(left) == revision_vector_sha256(reordered)
    assert changed_revision_dependencies(left, {"processMapRevision": "map-a"}) == {
        "productStructureRevision"
    }
    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_revision_vector({"browserRevision": "untrusted"})


def test_entities_referents_and_evidence_are_revalidated_from_current_targets() -> None:
    target_index = {
        "part": ["P-2"],
        "fai_characteristic": ["7"],
        "motion_group": ["group-current"],
        "process_edge": ["edge-current"],
        "facility_placement": ["pl-current"],
    }
    entities = revalidate_entities(
        {
            "part_number": "P-1",
            "part_numbers": ["P-1", "P-2"],
            "characteristic_numbers": ["5", "7"],
            "process_edge_ids": ["edge-old", "edge-current"],
            "facility_placement_ids": ["pl-old", "pl-current"],
        },
        target_index,
    )
    assert "part_number" not in entities
    assert entities["part_numbers"] == ["P-2"]
    assert entities["characteristic_numbers"] == ["7"]
    assert entities["process_edge_ids"] == ["edge-current"]
    assert entities["facility_placement_ids"] == ["pl-current"]

    referents = revalidate_referents(
        {
            "last_part_numbers": ["P-1", "P-2"],
            "last_process_edge_ids": ["edge-old", "edge-current"],
            "last_facility_placement_ids": ["pl-old", "pl-current"],
            "last_targets": [
                {"kind": "part", "id": "P-1"},
                {"kind": "part", "id": "P-2"},
                {"kind": "unindexed", "id": "keep-by-contract"},
            ],
        },
        target_index,
    )
    assert referents["last_part_numbers"] == ["P-2"]
    assert referents["last_process_edge_ids"] == ["edge-current"]
    assert referents["last_facility_placement_ids"] == ["pl-current"]
    assert [item["id"] for item in referents["last_targets"]] == [
        "P-2",
        "keep-by-contract",
    ]

    refs = filter_stale_evidence_refs(
        [
            "process-map:default:node-1",
            "fai:P-2:7",
            "motion-package:cycle-a",
        ],
        {"faiRevision", "motionAssetPin"},
    )
    assert refs == ["process-map:default:node-1"]


def test_reconciliation_event_applies_all_changed_revision_dimensions() -> None:
    before_state = {
        "entities": {"process_map_id": "default", "part_number": "P-1"},
        "referents": {"last_process_node_ids": ["removed-node"]},
        "evidence_refs": [
            "process-map:default:removed-node",
            "motion-package:old",
        ],
    }
    after_state = {
        "entities": {"process_map_id": "default"},
        "referents": {},
        "evidence_refs": [],
    }
    event = build_reconciliation_event(
        previous_scope_fingerprint="scope-v1:same",
        current_scope_fingerprint="scope-v1:same",
        previous_revision_vector={
            "processMapRevision": "map-a",
            "assemblyKnowledgeRevision": "knowledge-a",
            "facilityPolicyRevision": "policy-a",
        },
        current_revision_vector={
            "processMapRevision": "map-b",
            "assemblyKnowledgeRevision": "knowledge-b",
            "facilityPolicyRevision": "policy-b",
        },
        workflow_state_event="same_scope_revision_advanced",
        previous_workflow_state=before_state,
        current_workflow_state=after_state,
    )
    assert event["outcome"] == "same_scope_revision_advanced"
    assert event["dimensions"] == [
        "mapOrLayoutRevision",
        "structureOrEvidenceRevision",
        "policyRevision",
    ]
    assert event["removedEntityFieldCount"] == 1
    assert event["removedReferentFieldCount"] == 1
    assert event["removedEvidenceRefCount"] == 2
    assert {
        (row["item"], row["dimension"], row["action"])
        for row in event["actions"]
    } >= {
        ("semanticPreview", "mapOrLayoutRevision", "invalidate"),
        ("approvalToken", "policyRevision", "invalidate"),
        ("referents", "structureOrEvidenceRevision", "revalidate"),
        ("continuitySummary", "policyRevision", "mark_stale_decisions"),
    }


def test_continuity_is_scope_gated_and_stale_evidence_is_removed() -> None:
    summary = {
        "schemaVersion": "sage-continuity-summary-1.0",
        "summaryRevision": 2,
        "throughTurnSequence": 9,
        "objective": {"text": "Review the map", "sourceTurnIds": ["turn-1"]},
        "userClaims": [],
        "continuityDecisions": [],
        "assumptions": [],
        "corrections": [],
        "openQuestions": [],
        "referencedEntities": [],
        "sourceEvidenceRefs": [
            "process-map:default:node-1",
            "fai:P-1:7",
        ],
        "warnings": [],
    }
    scope_changed = reconcile_continuity_summary(
        summary,
        reconciliation_event={"outcome": "scope_changed"},
    )
    assert scope_changed.summary is None
    assert scope_changed.action == "scope_gate"

    explicit_comparison = reconcile_continuity_summary(
        summary,
        reconciliation_event={"outcome": "scope_changed"},
        explicit_cross_scope_comparison=True,
    )
    assert explicit_comparison.summary is not None
    assert explicit_comparison.action == "scope_gate"
    assert explicit_comparison.warnings == (
        "continuity_summary_cross_scope_comparison_only",
    )

    revision_changed = reconcile_continuity_summary(
        summary,
        reconciliation_event={
            "outcome": "same_scope_revision_advanced",
            "changedDependencies": ["processMapRevision"],
        },
    )
    assert revision_changed.summary["sourceEvidenceRefs"] == ["fai:P-1:7"]
    assert revision_changed.stale_evidence_refs == (
        "process-map:default:node-1",
    )
    assert revision_changed.action == "mark_stale_refs"
