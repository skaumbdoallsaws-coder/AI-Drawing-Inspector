from __future__ import annotations

from pathlib import Path

from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.reference_benchmark import (
    evaluate_reference_generalization,
    reference_generalization_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_BENCHMARK_REVISION = (
    "623bde7674567ae5824b4ffb1d7e61742b8972d9a633354ffd8366eaf9d62153"
)


def test_level_b_program_set_is_frozen_diverse_and_reference_independent() -> None:
    benchmark = reference_generalization_benchmark()

    assert benchmark["benchmarkRevision"] == FROZEN_BENCHMARK_REVISION
    assert len(benchmark["cases"]) == 6
    traits = {
        trait for case in benchmark["cases"] for trait in case["traits"]
    }
    assert {
        "guard_dense",
        "zero_guarding",
        "over_500_placements",
        "loop_route_topology",
        "multiple_cell_families",
        "negative_control",
    } <= traits
    payload = str(benchmark).casefold()
    assert "receiving + raw material" not in payload
    assert "manufacturing cell a01" not in payload
    assert "inspection + packing + finished goods" not in payload


def test_level_b_generalization_executes_exactly_and_fails_closed() -> None:
    catalog = build_private_local_asset_catalog(ROOT)
    report = evaluate_reference_generalization(catalog)

    assert report["benchmarkRevision"] == FROZEN_BENCHMARK_REVISION
    assert report["passedCount"] == report["caseCount"] == 6
    results = {item["caseId"]: item for item in report["results"]}
    assert results["guard-dense"]["counts"]["placements"] == 180
    assert results["zero-guard"]["counts"]["placements"] == 44
    assert results["over-500"]["counts"]["placements"] == 600
    assert results["over-500"]["stageBatchCounts"]["department_resources"] == 2
    assert results["loop-topology"]["counts"]["routes"] == 4
    assert results["mixed-cell-families"]["counts"]["placements"] == 39
    assert all(
        item.get("saved") is False and item.get("undoExact") is True
        for item in report["results"]
        if item["status"] == "passed"
    )
    refusal = results["infeasible-negative-control"]
    assert refusal["status"] == "expected_refusal"
    assert refusal["errorCode"] == "facility_program_resource_set_unplaceable"
    assert refusal["baseRevisionUnchanged"] is True
