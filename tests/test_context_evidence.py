"""Deterministic context consistency, provenance, and budget tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from ai_inspector.prompts import (  # noqa: E402
    ContextBudgetError,
    compile_skill_context,
    split_compiled_context_by_origin,
)


def _route() -> dict:
    return {
        "route_version": 2,
        "speech_act": "question",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": False,
        "workflow_confidence": 0.99,
        "intents": [{
            "kind": "explain_assembly_impact",
            "targets": [],
            "requested_effects": [],
        }],
        "skill_candidates": [
            {"id": "trace-assembly-impact", "role": "primary", "confidence": 0.99},
        ],
        "requested_side_effects": {
            "viewport_write": False,
            "asset_write": False,
            "system_write": False,
        },
        "needs_clarification": False,
    }


def _packages():
    plan, reason = server._compose_production_skill_prompt(_route(), mode="assembly")
    assert reason == "" and plan is not None
    return plan["_packages"]


def _context(rows: list[dict]) -> dict:
    return {
        "_user_message": "what is the supported assembly impact?",
        "part_number": "SYNTH-INSPECTED",
        "part_name": "Synthetic inspected part",
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "available_parts": [
            {"part_number": "SYNTH-INSPECTED", "description": "Synthetic inspected part"},
            {"part_number": "SYNTH-MATE", "description": "Synthetic mating part"},
        ],
    }


def _compile_row(description: str, measured: float) -> tuple[dict, object]:
    compiled = compile_skill_context(
        _context([{
            "char_number": "1",
            "description": description,
            "nominal": 10.0,
            "lower_limit": 9.95,
            "upper_limit": 10.05,
            "measured": measured,
            "status": "FAIL",
            "unit": "mm",
        }]),
        _packages(),
        mode="assembly",
    )
    return compiled.context["fai_characteristics"][0], compiled


def test_generic_internal_and_external_fit_direction():
    cases = [
        ("Shaft outside diameter", 9.8, "external_diameter", "increased_clearance"),
        (
            "Shaft outside diameter",
            10.2,
            "external_diameter",
            "reduced_clearance_or_increased_interference",
        ),
        ("Bearing bore diameter", 10.2, "internal_diameter", "increased_clearance"),
        (
            "Bearing bore diameter",
            9.8,
            "internal_diameter",
            "reduced_clearance_or_increased_interference",
        ),
    ]
    for description, measured, feature_kind, effect in cases:
        row, compiled = _compile_row(description, measured)
        assert row["fit_feature_kind"] == feature_kind
        assert row["fit_effect_hint"] == effect
        assert row["computed_status"] if "computed_status" in row else row["status"] == "FAIL"
        assert row["out_of_tolerance_by"] == 0.15
        classifications = {item["classification"] for item in compiled.provenance}
        assert {
            "observed_fact",
            "product_requirement",
            "calculated_fact",
            "engineering_inference",
        } <= classifications


def test_non_fit_geometry_does_not_invent_fit_direction():
    row, compiled = _compile_row("Hole true position", 10.2)
    assert "fit_feature_kind" not in row
    assert "fit_effect_hint" not in row
    assert not any(
        item["classification"] == "engineering_inference"
        for item in compiled.provenance
    )


def test_contradictory_fai_and_identity_context_is_reported():
    ctx = _context([
        {
            "char_number": "5",
            "description": "Bore diameter",
            "nominal": 10.0,
            "lower_limit": 9.95,
            "upper_limit": 10.05,
            "measured": 10.2,
            "status": "PASS",
        },
        {
            "char_number": "5",
            "description": "Bore diameter duplicate",
            "nominal": 10.0,
            "lower_limit": 9.95,
            "upper_limit": 10.05,
            "measured": 10.3,
            "status": "FAIL",
        },
    ])
    ctx["available_parts"] = [{"part_number": "SYNTH-OTHER"}]
    compiled = compile_skill_context(ctx, _packages(), mode="assembly")
    diagnostics = compiled.context["context_diagnostics"]
    assert diagnostics["status"] == "error"
    conflict_types = {item["type"] for item in diagnostics["conflicts"]}
    assert {
        "fai_status_conflict",
        "duplicate_characteristic_conflict",
        "inspected_part_not_in_assembly_context",
    } <= conflict_types
    rendered = server._build_context_message(compiled.context)
    assert "CONTEXT VALIDATION: ERROR" in rendered
    assert "Treat conflicts as disputed evidence" in rendered


def test_missing_required_context_is_explicit_not_silent():
    ctx = _context([{
        "char_number": "1",
        "description": "Shaft outside diameter",
        "nominal": 10.0,
        "lower_limit": 9.95,
        "upper_limit": 10.05,
        "measured": 9.8,
        "status": "FAIL",
    }])
    ctx.pop("available_parts")
    compiled = compile_skill_context(ctx, _packages(), mode="assembly")
    diagnostics = compiled.context["context_diagnostics"]
    assert diagnostics["status"] == "warning"
    assert diagnostics["missing_required_context"] == ["assembly.parts"]
    assert compiled.accounting["missing_required_context"] == ["assembly.parts"]
    provider = {
        row["contextKey"]: row
        for row in compiled.accounting["providers"]
    }["assembly.parts"]
    assert provider["required"] is True
    assert provider["included"] is False
    assert provider["omissionReason"] == "required_context_unavailable"


def test_context_budget_prunes_optional_data_but_preserves_required_evidence():
    ctx = _context([{
        "char_number": "1",
        "description": "Shaft outside diameter",
        "nominal": 10.0,
        "lower_limit": 9.95,
        "upper_limit": 10.05,
        "measured": 9.8,
        "status": "FAIL",
    }])
    ctx["profile_features"] = [
        {"id": f"feature-{index}", "semantic_name": "Synthetic feature " + ("x" * 80)}
        for index in range(800)
    ]
    ctx["viewport_context"] = {
        "state": {"active_tab": "assembly"},
        "motion": {"groups": [{"id": f"group-{index}", "label": "y" * 80} for index in range(300)]},
    }
    compiled = compile_skill_context(ctx, _packages(), mode="assembly")
    budget = compiled.accounting["budget"]
    assert budget["removed_optional_context"]
    assert budget["budget_exceeded"] is False
    assert budget["estimated_tokens"] <= budget["maximum_tokens"]
    assert "fai_characteristics" in compiled.context
    assert "available_parts" in compiled.context
    assert budget["required_evidence_preserved"] is True


def test_required_context_over_budget_fails_closed_with_provider_names():
    ctx = _context([{
        "char_number": "1",
        "description": "Shaft outside diameter",
        "nominal": 10.0,
        "lower_limit": 9.95,
        "upper_limit": 10.05,
        "measured": 9.8,
        "status": "FAIL",
    }])
    ctx["available_parts"] = [
        {
            "part_number": f"SYNTH-{index:04d}",
            "description": "required assembly evidence " + ("x" * 120),
        }
        for index in range(500)
    ]
    with pytest.raises(ContextBudgetError) as caught:
        compile_skill_context(ctx, _packages(), mode="assembly")
    assert caught.value.code == "required_context_budget_exceeded"
    assert "assembly.parts" in caught.value.details["providers"]


def test_server_and_browser_context_are_split_by_registered_origin():
    package = SimpleNamespace(
        manifest=SimpleNamespace(
            id="test-process-map-skill",
            requires_context=("process_map.state",),
            optional_context=("assembly.parts",),
        ),
        contract=SimpleNamespace(
            maximum_context_tokens=6000,
            context_priorities=("process_map.state", "assembly.parts"),
            forbidden_context=(),
            required_evidence=(),
        ),
    )
    compiled = compile_skill_context(
        {
            "active_mode": "process_map",
            "process_map_state": {"dirty": False, "selection": []},
            "available_parts": [{"part_number": "BROWSER-CLAIM"}],
        },
        (package,),
        mode="process_map",
    )
    trusted, untrusted = split_compiled_context_by_origin(
        compiled.context,
        (package,),
    )
    assert trusted == {
        "process_map_state": {"dirty": False, "selection": []}
    }
    assert untrusted["available_parts"] == [
        {"part_number": "BROWSER-CLAIM"}
    ]
    providers = {
        row["contextKey"]: row for row in compiled.accounting["providers"]
    }
    assert providers["process_map.state"]["origin"] == "server"
    assert providers["assembly.parts"]["origin"] == "browser"


def test_pure_viewport_context_has_empty_provenance_without_error():
    route = {
        "route_version": 2,
        "speech_act": "command",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": True,
        "workflow_confidence": 0.99,
        "intents": [{
            "kind": "visualize_affected_context",
            "targets": [],
            "requested_effects": ["highlight_parts"],
        }],
        "skill_candidates": [
            {"id": "control-cad-viewport", "role": "primary", "confidence": 0.99},
        ],
        "requested_side_effects": {
            "viewport_write": True,
            "asset_write": False,
            "system_write": False,
        },
        "needs_clarification": False,
    }
    plan, reason = server._compose_production_skill_prompt(route, mode="assembly")
    assert reason == "" and plan is not None
    compiled = compile_skill_context(
        {
            "part_number": "SYNTH-INSPECTED",
            "active_mode": "assembly",
            "viewport_context": {
                "state": {"active_tab": "assembly"},
                "part_legend": [{"part_number": "SYNTH-INSPECTED"}],
            },
        },
        plan["_packages"],
        mode="assembly",
    )
    assert compiled.provenance == ()
    assert compiled.accounting["provenance_count"] == 0
    assert compiled.accounting["context_status"] == "ok"


def _run_without_pytest() -> int:
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return failures


if __name__ == "__main__":
    raise SystemExit(_run_without_pytest())
