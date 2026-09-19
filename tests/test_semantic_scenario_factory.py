from __future__ import annotations

from collections import Counter
from pathlib import Path

from ai_inspector.assembly_knowledge.scenario_factory import (
    CASE_KINDS,
    TARGET_WORKFLOWS,
    build_scenario_factory,
)


ROOT = Path(__file__).resolve().parents[1]


def test_scenario_factory_builds_isolated_validated_coverage() -> None:
    result = build_scenario_factory(ROOT)

    assert result["machineGatePassed"] is True
    assert result["summary"]["candidateCount"] == 100
    assert result["summary"]["goldCandidateCount"] == 48
    assert result["summary"]["heldOutParaphraseCount"] == 40
    assert result["summary"]["syntheticScenarioCount"] == 60
    assert set(TARGET_WORKFLOWS) <= set(result["summary"]["workflowCounts"])
    assert set(CASE_KINDS) <= set(result["summary"]["caseKindCounts"])
    assert result["validation"]["issueCount"] == 0
    assert result["validation"]["unresolvedReferenceCount"] == 0
    assert result["validation"]["exactDuplicatePromptGroups"] == []
    assert result["validation"]["nearDuplicatePromptPairs"] == []
    assert result["validation"]["lineageLeaks"] == {}
    assert result["validation"]["runtimeClaimEligibleCount"] == 0


def test_catalog_paraphrases_cover_all_ten_catalog_entities() -> None:
    result = build_scenario_factory(ROOT)
    paraphrases = [
        item
        for item in result["candidates"]
        if item["caseKind"] == "catalog_paraphrase"
    ]
    counts = Counter(item["entityRefs"][0] for item in paraphrases)

    assert len(counts) == 10
    assert set(counts.values()) == {4}
    assert all(item["partition"] == "evaluation" for item in paraphrases)
    assert all(item["evaluationOnly"] is True for item in paraphrases)
    assert all(item["runtimeClaimEligible"] is False for item in paraphrases)


def test_gold_candidates_remain_pending_and_never_promote_authority() -> None:
    result = build_scenario_factory(ROOT)

    assert len(result["goldCandidates"]) == 48
    assert all(
        item["humanReview"] == {
            "status": "pending",
            "reviewer": None,
            "reviewedAt": None,
            "minutes": 0,
        }
        for item in result["goldCandidates"]
    )
    assert all(item["runtimeClaimEligible"] is False for item in result["goldCandidates"])


def test_action_scenarios_require_permission_and_matching_receipts() -> None:
    result = build_scenario_factory(ROOT)
    action_cases = [item for item in result["candidates"] if item["expectedActions"]]

    assert action_cases
    for item in action_cases:
        permissions = {
            permission["action"]: permission["allowed"]
            for permission in item["permissions"]
        }
        for action in item["expectedActions"]:
            assert action["action"] in permissions
            if action["expectedOutcome"] == "not_executed":
                assert permissions[action["action"]] is False
            elif action["expectedOutcome"] == "failed":
                assert item["receiptConstraints"]["required"] is True
                assert item["receiptConstraints"]["expectedSuccess"] is False
            elif action["expectedOutcome"] == "succeeded":
                assert item["receiptConstraints"]["required"] is True
                assert item["receiptConstraints"]["expectedSuccess"] is True


def test_generation_is_content_idempotent() -> None:
    assert build_scenario_factory(ROOT) == build_scenario_factory(ROOT)
