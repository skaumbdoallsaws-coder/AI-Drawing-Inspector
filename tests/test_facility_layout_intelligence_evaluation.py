"""Release gate for source-bound Facility Layout semantic intelligence."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from ai_inspector.facility_layout.intelligence_evaluation import (
    GATE_THRESHOLDS,
    evaluate_sage_facility_layout_intelligence,
)
from ai_inspector.facility_layout.chat_context import (
    FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES,
    build_facility_analysis_digest,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CRITICAL_100_PERCENT_GATES = {
    "deterministic_geometry",
    "read_only_safety",
    "unit_fidelity",
    "process_and_route",
    "provenance",
    "bounded_fit",
    "context_compilation",
    "catalog_coverage",
    "g1_generation",
}


def _stable_projection(report):
    result = json.loads(json.dumps(report))
    result.pop("generatedAtUtc", None)
    result.pop("environment", None)
    return result


def test_frozen_facility_intelligence_gate_passes_without_provider_calls():
    report = evaluate_sage_facility_layout_intelligence(REPO_ROOT)

    assert report["status"] == "passed"
    assert report["providerCalls"] == 0
    assert report["networkCalls"] == 0
    assert report["snapshot"]["sourceMutationDetected"] is False
    assert report["summary"]["failedCount"] == 0
    assert report["summary"]["criticalFailureCount"] == 0
    assert report["summary"]["missingSourceBindings"] == []
    assert report["summary"]["structuralConversationCaseCount"] >= 50
    assert all(item["status"] == "passed" for item in report["gates"])
    assert all(item["passed"] for item in report["checks"])


def test_critical_geometry_and_action_gates_are_exactly_100_percent():
    report = evaluate_sage_facility_layout_intelligence(REPO_ROOT)
    gates = {item["gate"]: item for item in report["gates"]}

    assert CRITICAL_100_PERCENT_GATES <= gates.keys()
    for gate_name in CRITICAL_100_PERCENT_GATES:
        gate = gates[gate_name]
        assert GATE_THRESHOLDS[gate_name] == 100.0
        assert gate["passPercent"] == 100.0
        assert gate["failedCount"] == 0


def test_evaluation_is_deterministic_and_source_bound():
    first = evaluate_sage_facility_layout_intelligence(REPO_ROOT)
    second = evaluate_sage_facility_layout_intelligence(REPO_ROOT)

    assert _stable_projection(first) == _stable_projection(second)
    assert first["snapshot"]["fixtureSha256"]
    assert first["snapshot"]["sourceStateSha256"]
    assert first["snapshot"]["semanticProjectionSha256"]
    assert all(item["available"] for item in first["sourceBindings"])
    assert all(len(item["sha256"]) == 64 for item in first["sourceBindings"])


def test_claim_boundary_does_not_overstate_provider_quality():
    report = evaluate_sage_facility_layout_intelligence(REPO_ROOT)
    boundary = report["claimBoundary"]

    assert "quality of arbitrary future provider prose" in boundary["notProved"]
    assert "regulatory compliance" in boundary["notProved"]
    assert "production capacity without operational data" in boundary[
        "notProved"
    ]
    assert boundary["providerShadowEvaluationRequiredFor"]


def test_large_analysis_projection_stays_bounded_and_keeps_zone_identity():
    fixture = json.loads((
        REPO_ROOT
        / "tests/fixtures/facility_layout/semantic_intelligence/"
        "golden-facility-a.json"
    ).read_text(encoding="ascii"))
    state = deepcopy(fixture["state"])
    template = deepcopy(state["zones"][-1])
    for index in range(38):
        zone = deepcopy(template)
        zone["zoneId"] = f"cell-scale-{index + 1:02d}"
        zone["label"] = f"Manufacturing Cell Scale {index + 1:02d}"
        x_value = 102.0 + (index % 19) * 4.0
        # Keep every generated cell inside Machining Hall so this exercises a
        # realistic six-department layout with many nested operational zones.
        z_value = 112.0 + (index // 19) * 8.0
        zone["boundary"] = [
            {"x": x_value, "z": z_value},
            {"x": x_value + 3.0, "z": z_value},
            {"x": x_value + 3.0, "z": z_value + 6.0},
            {"x": x_value, "z": z_value + 6.0},
        ]
        state["zones"].append(zone)

    projected = build_facility_analysis_digest({"counts": {}}, state)

    assert len(projected["zoneIndex"]) == 45
    assert len(projected["departmentSummaries"]) == 6
    assert "zoneSummaries" not in projected
    assert "assetUsage" not in projected
    assert "readDescriptors" not in projected
    assert projected["truncation"]["zoneIndex"] == {
        "returnedCount": 45,
        "omittedCount": 0,
    }
    assert projected["canonicalUtf8Bytes"] <= (
        FACILITY_ANALYSIS_DIGEST_MAXIMUM_BYTES
    )
