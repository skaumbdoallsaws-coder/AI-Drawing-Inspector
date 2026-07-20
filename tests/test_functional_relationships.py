"""Functional relationship graph, FAI join, and prompt-context tests."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from ai_inspector.product_intelligence import (  # noqa: E402
    FunctionalRelationshipRegistry,
    build_functional_context,
    validate_functional_relationship_graph,
)


ASSEMBLY_PATH = ROOT / "400S_Sorted_Library" / "assemblies" / "100001_assembly.json"
CATALOG_PATH = ROOT / "ai_inspector" / "product_intelligence" / "catalogs" / "100001.json"


def _graph() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="ascii"))


def _assembly() -> dict:
    return json.loads(ASSEMBLY_PATH.read_text(encoding="utf-8-sig"))


def _row(description: str, *, number: str = "1", feature_kind: str | None = None) -> dict:
    row = {
        "char_number": number,
        "description": description,
        "nominal": 10.0,
        "lower_limit": 9.95,
        "upper_limit": 10.05,
        "measured": 11.0,
        "status": "FAIL",
    }
    if feature_kind:
        row["fit_feature_kind"] = feature_kind
    return row


def test_catalog_validates_against_all_assembly_instances():
    report = validate_functional_relationship_graph(_graph(), assembly_data=_assembly())
    assert report.ok, report.errors
    assert report.coverage == {
        "physical_instance_count": 38,
        "covered_instance_count": 38,
        "uncovered_instance_ids": [],
        "organizational_instance_count": 5,
        "external_entity_count": 2,
    }


def test_registry_load_is_ascii_and_strict():
    raw = CATALOG_PATH.read_bytes()
    raw.decode("ascii")
    graph, report = FunctionalRelationshipRegistry().load(
        "100001", assembly_data=_assembly()
    )
    assert report.ok
    assert graph["graph_id"] == "functional-graph:100001"


def test_catalog_source_hashes_match_current_evidence():
    for source in _graph()["source_evidence"]:
        source_path = ROOT / source["path"]
        assert source_path.exists(), source_path
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source["sha256"]


def test_validator_rejects_embedded_dimension_data():
    graph = _graph()
    graph["component_types"][0]["description"] += " with 25 mm clearance"
    report = validate_functional_relationship_graph(graph)
    assert not report.ok
    assert any("dimensional value" in error for error in report.errors)


def test_validator_rejects_wrong_instance_part_number():
    graph = _graph()
    physical = next(row for row in graph["component_instances"] if row["kind"] == "physical")
    physical["part_number"] = "100002" if physical["part_number"] != "100002" else "100003"
    report = validate_functional_relationship_graph(graph, assembly_data=_assembly())
    assert not report.ok
    assert any("part-number mismatch" in error or "does not match its instance" in error for error in report.errors)


def test_piston_outer_diameter_joins_cylinder_guide_without_inventing_upper_block():
    context = build_functional_context(
        _graph(),
        part_number="100006",
        fai_characteristics=[
            _row("Main outside diameter of the piston body", feature_kind="external_diameter")
        ],
    )
    affected = context["affected_functional_interfaces"]
    assert len(affected) == 1
    assert affected[0]["controlled_feature"]["feature_ref"] == "piston.skirt-running-surface"
    assert affected[0]["interface"]["pattern_id"] == "piston-cylinder-guide"
    assert affected[0]["interface"]["missing_external_evidence"] == [
        "Upper cylinder block and cylinder-bore system"
    ]
    assert any(
        item["entity_id"] == "external:upper-cylinder-block"
        and item["presence"] == "absent_from_extract"
        for item in context["functional_relationship_summary"]["external_entities"]
    )


def test_pin_bore_join_traces_one_hop_through_pin_to_rod():
    context = build_functional_context(
        _graph(),
        part_number="100006",
        fai_characteristics=[
            _row("Wrist-pin hole diameter through the piston", number="5", feature_kind="internal_diameter")
        ],
    )
    affected = context["affected_functional_interfaces"]
    assert len(affected) == 1
    item = affected[0]
    assert item["controlled_feature"]["feature_ref"] == "piston.pin-bores"
    assert item["interface"]["pattern_id"] == "piston-pin-bearing"
    assert [row["pattern_id"] for row in item["adjacent_interfaces"]] == ["rod-pin-bearing"]


def test_ring_groove_join_is_retention_not_motion_playback():
    context = build_functional_context(
        _graph(),
        part_number="100006",
        fai_characteristics=[_row("Three repeated ring groove widths")],
    )
    affected = context["affected_functional_interfaces"]
    assert len(affected) == 1
    assert affected[0]["controlled_feature"]["feature_ref"] == "piston.ring-grooves"
    assert affected[0]["interface"]["pattern_id"] == "piston-ring-retention"


def test_unrelated_feature_without_functional_interface_does_not_fabricate_join():
    context = build_functional_context(
        _graph(),
        part_number="100006",
        fai_characteristics=[_row("Crown dome rise")],
    )
    assert context["affected_functional_interfaces"] == []


def test_normalized_agent_context_attaches_graph_and_join():
    normalized = server.normalize_agent_context(
        {
            "attachments": {
                "part": {"part_number": "100006", "part_name": "Piston"},
                "inspection": {
                    "fai_characteristics": [
                        _row("Main outside diameter of the piston body", feature_kind="external_diameter")
                    ]
                },
                "session": {"active_mode": "assembly"},
            }
        }
    )
    flat = normalized["flat"]
    assert flat["functional_relationship_summary"]["assembly_number"] == "100001"
    assert flat["affected_functional_interfaces"][0]["interface"]["pattern_id"] == "piston-cylinder-guide"
    assert normalized["attachments"]["assembly"]["functional_relationships"]


def test_router_facts_advertise_functional_context_without_authorizing_action():
    ctx = server.normalize_agent_context(
        {
            "attachments": {
                "part": {"part_number": "100006", "part_name": "Piston"},
                "inspection": {
                    "fai_characteristics": [
                        _row("Main outside diameter of the piston body", feature_kind="external_diameter")
                    ]
                },
                "session": {"active_mode": "assembly"},
            }
        }
    )["flat"]
    _assets, contexts, facts = server._skill_route_context(ctx)
    assert "assembly.functional_relationships" in contexts
    assert facts["affected_functional_interfaces"] == [
        {
            "characteristic_id": "1",
            "feature_ref": "piston.skirt-running-surface",
            "interface_pattern_id": "piston-cylinder-guide",
        }
    ]


def test_compiled_trace_context_includes_only_compact_functional_provider():
    route = {
        "route_version": 2,
        "speech_act": "analyze",
        "primary_workflow": "supplier-fai-disposition",
        "continue_existing_workflow": False,
        "workflow_confidence": 0.99,
        "intents": [{
            "kind": "explain_assembly_impact",
            "targets": [{"kind": "assembly", "id": "current"}],
            "requested_effects": [],
        }],
        "skill_candidates": [
            {"id": "trace-assembly-impact", "role": "primary", "confidence": 0.99},
            {"id": "reason-about-assembly-context", "role": "support", "confidence": 0.99},
        ],
        "requested_side_effects": {
            "viewport_write": False,
            "asset_write": False,
            "system_write": False,
        },
        "needs_clarification": False,
    }
    plan, reason = server._compose_production_skill_prompt(route, mode="assembly")
    assert reason == "" and plan is not None
    ctx = server.normalize_agent_context(
        {
            "attachments": {
                "part": {"part_number": "100006", "part_name": "Piston"},
                "inspection": {
                    "fai_characteristics": [
                        _row("Main outside diameter of the piston body", feature_kind="external_diameter")
                    ]
                },
                "selection": {
                    "available_parts": [
                        {"part_number": "100006", "description": "Piston"},
                        {"part_number": "100002", "description": "Lower Engine Block"},
                    ]
                },
                "session": {"active_mode": "assembly"},
            }
        }
    )["flat"]
    compiled = server.compile_skill_context(ctx, plan["_packages"], mode="assembly")
    assert compiled.accounting["derived_context"] == ["assembly.functional_relationships"]
    assert "functional_relationships" in compiled.context
    assert "component_instances" not in compiled.context
    assert "interfaces" not in compiled.context
    rendered = server._build_context_message(compiled.context)
    assert "[FUNCTIONAL RELATIONSHIP GRAPH]" in rendered
    assert "[FAILED CHARACTERISTIC TO FUNCTIONAL INTERFACE JOIN]" in rendered
    assert "free axial translation" in rendered
    assert "Upper cylinder block and cylinder-bore system" in rendered


def test_functional_provider_is_not_injected_for_unrelated_skill():
    plan, reason = server._compose_production_skill_prompt(
        {
            "route_version": 2,
            "speech_act": "question",
            "primary_workflow": "supplier-fai-disposition",
            "continue_existing_workflow": False,
            "workflow_confidence": 0.99,
            "intents": [{
                "kind": "assess_fai_characteristic",
                "targets": [],
                "requested_effects": [],
            }],
            "skill_candidates": [
                {"id": "assess-fai-characteristic", "role": "primary", "confidence": 0.99}
            ],
            "requested_side_effects": {
                "viewport_write": False,
                "asset_write": False,
                "system_write": False,
            },
            "needs_clarification": False,
        },
        mode="report_fai",
    )
    assert reason == "" and plan is not None
    ctx = server.normalize_agent_context(
        {
            "attachments": {
                "part": {"part_number": "100006", "part_name": "Piston"},
                "inspection": {"fai_characteristics": [_row("Main outside diameter")]},
                "session": {"active_mode": "report_fai"},
            }
        }
    )["flat"]
    compiled = server.compile_skill_context(ctx, plan["_packages"], mode="report_fai")
    assert compiled.accounting["derived_context"] == []
    assert "functional_relationships" not in compiled.context


def test_legacy_renderer_keeps_functional_graph_out_of_unrelated_turns():
    context = build_functional_context(_graph(), part_number="100006")
    unrelated = {
        "_user_message": "Fill characteristic one with the measured value.",
        "part_number": "100006",
        **context,
    }
    relevant = {
        **unrelated,
        "_user_message": "How does this part function in the assembly?",
    }
    assert "[FUNCTIONAL RELATIONSHIP GRAPH]" not in server._build_context_message(unrelated)
    assert "[FUNCTIONAL RELATIONSHIP GRAPH]" in server._build_context_message(relevant)


def _run_without_pytest() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
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
