"""Live FAI snapshot and deterministic target-resolution regressions."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from ai_inspector.prompts import compile_skill_context, resolve_fai_request_target  # noqa: E402


def _rows():
    return [
        {"char_number": 1, "description": "Main outside diameter of the piston body", "nominal": 90, "measured": 95, "lower_limit": 89.95, "upper_limit": 90.05, "status": "FAIL"},
        {"char_number": 5, "description": "Wrist-pin hole diameter through the piston", "nominal": 30, "measured": 35, "lower_limit": 29.95, "upper_limit": 30.05, "status": "FAIL"},
        {"char_number": 15, "description": "Ring groove width", "nominal": 4.3, "measured": 4.8, "lower_limit": 4.25, "upper_limit": 4.35, "status": "FAIL"},
    ]


def _snapshot(**overrides):
    value = {
        "table_revision": 28,
        "previous_sage_revision": 26,
        "selected_characteristic_id": "5",
        "newly_failed_characteristic_ids": ["15"],
        "changed_since_last_response": [{
            "id": "15", "row_revision": 7, "previous_status": "PASS",
            "current_status": "FAIL", "previous_measured": 4.3,
            "current_measured": 4.8,
        }],
        "previous_target_characteristic_ids": ["5"],
    }
    value.update(overrides)
    return value


def test_explicit_number_targets_only_that_characteristic():
    result = resolve_fai_request_target("How about measured dimension #5?", _rows(), snapshot=_snapshot())
    assert result["target_characteristic_ids"] == ["5"]
    assert result["resolution"] == "explicit_characteristic_number"
    assert result["mentions_characteristic_number"] is True


def test_selected_row_resolves_generic_singular_question():
    result = resolve_fai_request_target("What is the impact of the failed dimension?", _rows(), snapshot=_snapshot())
    assert result["target_characteristic_ids"] == ["5"]
    assert result["resolution"] == "selected_characteristic"


def test_recent_wording_overrides_stale_selected_row():
    result = resolve_fai_request_target("How about the new failed dimension I just added?", _rows(), snapshot=_snapshot())
    assert result["target_characteristic_ids"] == ["15"]
    assert result["resolution"] == "changed_since_last_response"


def test_general_question_with_multiple_failures_targets_all_once():
    result = resolve_fai_request_target(
        "What are the implications of the current FAI results?",
        _rows(),
        snapshot=_snapshot(selected_characteristic_id=None),
    )
    assert result["request_scope"] == "all_failed_characteristics"
    assert result["target_characteristic_ids"] == ["1", "5", "15"]


def test_explicit_engineering_name_resolves_without_number():
    result = resolve_fai_request_target(
        "What does the wrist pin bore failure affect?", _rows(), snapshot=_snapshot()
    )
    assert result["target_characteristic_ids"] == ["5"]
    assert result["resolution"] == "explicit_characteristic_name"


def test_snapshot_rows_override_stale_compatibility_projection():
    normalized = server.normalize_agent_context({
        "attachments": {
            "inspection": {
                "fai_characteristics": [{"char_number": 1, "measured": 92}],
                "fai_snapshot": {
                    **_snapshot(),
                    "rows": [{"char_number": 1, "measured": 95}],
                },
            }
        }
    })["flat"]
    assert normalized["fai_characteristics"][0]["measured"] == 95
    assert normalized["fai_snapshot"]["table_revision"] == 28


def test_compiler_keeps_only_deterministically_targeted_row_and_join():
    plan, reason = server._compose_production_skill_prompt(
        {
            "route_version": 2,
            "speech_act": "question",
            "primary_workflow": "supplier-fai-disposition",
            "continue_existing_workflow": False,
            "workflow_confidence": 0.99,
            "intents": [{"kind": "explain_assembly_impact", "targets": [], "requested_effects": []}],
            "skill_candidates": [{"id": "trace-assembly-impact", "role": "primary", "confidence": 0.99}],
            "requested_side_effects": {"viewport_write": False, "asset_write": False, "system_write": False},
            "needs_clarification": False,
        },
        mode="assembly",
    )
    assert reason == "" and plan
    ctx = {
        "_user_message": "How about #5?",
        "part_number": "100006",
        "part_name": "Piston",
        "active_mode": "assembly",
        "fai_characteristics": _rows(),
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "resolution": "explicit_characteristic_number",
        },
        "available_parts": [{"part_number": "100006"}],
        "affected_functional_interfaces": [
            {"characteristic_id": "1", "interface": {"pattern_id": "piston-cylinder-guide"}},
            {"characteristic_id": "5", "interface": {"pattern_id": "piston-pin-bearing"}},
        ],
        "functional_relationship_summary": {"graph_id": "synth", "graph_version": "1", "assembly_number": "A"},
        "functional_relationships": [{"pattern_id": "piston-pin-bearing"}],
    }
    compiled = compile_skill_context(ctx, plan["_packages"], mode="assembly").context
    assert [str(row["char_number"]) for row in compiled["fai_characteristics"]] == ["5"]
    assert [item["characteristic_id"] for item in compiled["affected_functional_interfaces"]] == ["5"]


def test_answer_cleanup_removes_unrelated_rows_internal_ids_and_followup():
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": _rows(),
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "5",
            "interface": {
                "pattern_id": "piston-pin-bearing",
                "interface_type": "floating_pin_bearing",
            },
        }],
    }
    answer = (
        "Characteristic #1 measured 95 mm and is oversized. "
        "Characteristic #5 (Wrist-pin hole diameter through the piston) measured 35 mm "
        "against 29.95 to 30.05 mm. The bore controls radial support of the piston pin. "
        "Would you like another analysis?"
    )
    cleaned = server._clean_agent_answer(answer, ctx, "What is the impact of the failed dimension?")
    assert "#1" not in cleaned and "#5" not in cleaned
    assert not server._fai_number_present(cleaned, 95), cleaned
    assert server._fai_number_present(cleaned, 35) and "radial support" in cleaned
    assert not cleaned.endswith("?")


def test_answer_cleanup_removes_unrequested_hold_and_rework_decision():
    rows = [row for row in _rows() if str(row["char_number"]) == "15"]
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["15"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "15",
            "interface": {
                "pattern_id": "piston-ring-retention",
                "interface_type": "ring_retention",
            },
        }],
    }
    answer = (
        "The ring groove measured 4.8 mm vs nominal 4.3 mm, 0.45 mm above "
        "the upper limit. This controls ring side clearance. Hold the inspected "
        "part from assembly pending engineering disposition; hold the inspected "
        "part from assembly pending engineering disposition -- this condition "
        "cannot be reworked."
    )
    cleaned = server._clean_agent_answer(
        answer, ctx, "What is the impact of the new failed dimension?"
    )
    low = cleaned.lower()
    assert "hold the inspected part" not in low, cleaned
    assert "engineering disposition" not in low, cleaned
    assert "rework" not in low, cleaned
    assert "side clearance" in low, cleaned
    assert ";," not in cleaned and ";." not in cleaned, cleaned
    assert ", and use the mating" not in low, cleaned


def test_disposition_cleanup_removes_dangling_conjunction_and_names_next_evidence():
    rows = [row for row in _rows() if str(row["char_number"]) == "5"]
    ctx = {
        "active_mode": "assembly",
        "_user_message": "What is the recommended disposition and next action?",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "5",
            "interface": {
                "pattern_id": "piston-pin-bearing",
                "interface_type": "floating_pin_bearing",
            },
            "adjacent_interfaces": [{"pattern_id": "rod-pin-bearing"}],
        }],
    }
    raw = (
        "The wrist-pin hole diameter measured 35.0 mm against nominal 30.0 mm. "
        "The oversize bore increases pin clearance and reduces radial support. "
        "Reject this characteristic and. Hold the inspected piston pending engineering "
        "disposition to determine whether accept-as-is, rework, or scrap is appropriate."
    )
    cleaned = server._clean_agent_answer(raw, ctx, ctx["_user_message"])
    limited, _ = server._enforce_response_sentence_limit(cleaned, 3)
    final = server._finalize_fai_answer_composition(limited, ctx)
    low = final.lower()
    assert "and." not in low, final
    assert low.count("reject") == 1, final
    assert "actual mating pin diameter" in low, final
    assert "required joint-clearance criterion" in low, final
    assert "pending engineering disposition" in low, final
    assert "scrap" not in low, final

    semicolon_raw = raw.replace("and.", "and;")
    semicolon_cleaned = server._clean_agent_answer(
        semicolon_raw, ctx, ctx["_user_message"]
    )
    semicolon_limited, _ = server._enforce_response_sentence_limit(
        semicolon_cleaned, 3
    )
    semicolon_final = server._finalize_fai_answer_composition(
        semicolon_limited, ctx
    )
    assert "and;" not in semicolon_final.lower(), semicolon_final

    hold_it_raw = (
        "The wrist-pin hole diameter measured 35.0 mm against nominal 30.0 mm. "
        "The oversize bore increases pin clearance and reduces radial support. "
        "Reject the inspected piston and hold it from assembly pending engineering "
        "disposition; the decision to reject, rework, or accept-as-is requires the "
        "actual mating pin diameter and controlling fit specification."
    )
    hold_it_cleaned = server._clean_agent_answer(
        hold_it_raw, ctx, ctx["_user_message"]
    )
    hold_it_limited, _ = server._enforce_response_sentence_limit(hold_it_cleaned, 3)
    hold_it_final = server._finalize_fai_answer_composition(hold_it_limited, ctx)
    hold_it_low = hold_it_final.lower()
    assert hold_it_low.count("reject") == 1, hold_it_final
    assert "actual mating pin diameter" in hold_it_low, hold_it_final
    assert "required joint-clearance criterion" in hold_it_low, hold_it_final


def test_answer_cleanup_removes_hold_but_keeps_functional_explanation():
    rows = [row for row in _rows() if str(row["char_number"]) == "5"]
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": True,
            "needs_clarification": False,
        },
    }
    answer = (
        "Dimension #5 measured 35 mm vs nominal 30 mm. Hold this piston from "
        "assembly pending engineering disposition. The bore controls pin support."
    )
    cleaned = server._clean_agent_answer(answer, ctx, "How about dimension #5?")
    assert "controls pin support" in cleaned, cleaned
    assert "hold" not in cleaned.lower(), cleaned
    assert "engineering disposition" not in cleaned.lower(), cleaned


def test_answer_cleanup_supplies_missing_selected_interface_function():
    rows = [row for row in _rows() if str(row["char_number"]) == "1"]
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["1"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "1",
            "interface": {
                "pattern_id": "piston-cylinder-guide",
                "interface_type": "prismatic_guidance_clearance",
                "missing_external_evidence": [
                    "Upper cylinder block and cylinder-bore system"
                ],
            },
        }],
    }
    answer = (
        "The outside diameter measured 95 mm vs nominal 90 mm and is 4.95 mm "
        "above the upper limit. The oversize condition reduces running clearance. "
        "Engineering disposition is required."
    )
    cleaned = server._clean_agent_answer(
        answer, ctx, "What is the impact of the failed dimension?"
    )
    low = cleaned.lower()
    assert "piston-to-cylinder running clearance" in low, cleaned
    assert "free axial translation" in low, cleaned
    assert "conforming cylinder bore" in low, cleaned


def test_function_coverage_recognizes_increased_pin_clearance_wording():
    fai_request = {
        "request_scope": "specific_characteristic",
        "target_characteristic_ids": ["5"],
        "mentions_characteristic_number": False,
        "needs_clarification": False,
    }
    answer = (
        "The wrist-pin bore failed above its upper limit; increased clearance "
        "between the piston and pin reduces radial support in the reciprocating load path."
    )
    cleaned = server._ensure_fai_function_coverage(
        answer,
        "piston-pin-bearing floating_pin_bearing above_upper",
        fai_request,
    )
    assert cleaned == answer, cleaned


def test_missing_bore_qualifier_handles_decimal_values_and_wrong_block_claim():
    support = (
        '{"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-cylinder-guide","missing_external_evidence":'
        '["Upper cylinder block and cylinder-bore system"]}}]}'
    ).lower()
    text = (
        "The 95.0 mm piston will reduce or eliminate running clearance with the "
        "cylinder bore in the lower engine block."
    )
    cleaned = server._qualify_missing_fai_mating_evidence(text, support)
    low = cleaned.lower()
    assert "lower engine block" not in low, cleaned
    assert "conforming cylinder bore" in low, cleaned
    assert "mating bore measurement" in low, cleaned


def test_pipeline_restores_measurement_after_missing_bore_qualification():
    rows = [row for row in _rows() if str(row["char_number"]) == "1"]
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["1"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "1",
            "interface": {
                "pattern_id": "piston-cylinder-guide",
                "interface_type": "prismatic_guidance_clearance",
                "missing_external_evidence": [
                    "Upper cylinder block and cylinder-bore system"
                ],
            },
        }],
    }
    answer = (
        "The oversize 95.0 mm piston will eliminate running clearance with the "
        "cylinder bore in the lower engine block."
    )
    cleaned = server._clean_agent_answer(
        answer, ctx, "What is the impact of the failed dimension?"
    )
    assert server._fai_number_present(cleaned, 95), cleaned
    assert "lower engine block" not in cleaned.lower(), cleaned
    assert "conforming cylinder bore" in cleaned.lower(), cleaned


def test_answer_cleanup_removes_unrequested_rework_actions():
    rows = [row for row in _rows() if str(row["char_number"]) == "15"]
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["15"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "15",
            "interface": {
                "pattern_id": "piston-ring-retention",
                "interface_type": "ring_retention",
            },
        }],
    }
    answer = (
        "**Rework.** The 4.8 mm ring groove exceeds the 4.35 mm upper limit by "
        "0.45 mm, creating excessive ring side clearance that allows flutter and "
        "blowby. Machine the groove floor deeper or install oversized rings to "
        "restore clearance; what ring thickness is specified for this engine?"
    )
    cleaned = server._clean_agent_answer(
        answer, ctx, "How about the new failed dimension I just added?"
    )
    low = cleaned.lower()
    assert "rework" not in low, cleaned
    assert "machine the groove" not in low and "install oversized" not in low, cleaned
    assert "what ring" not in low and "?" not in cleaned, cleaned
    assert "ring" in low and "side clearance" in low, cleaned
    assert low.count("4.8 mm") == 1, cleaned
    assert "engineering disposition" not in low and "hold" not in low, cleaned


def test_answer_cleanup_drops_borrowed_interface_and_partial_hold():
    rows = [row for row in _rows() if str(row["char_number"]) == "5"]
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": True,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "5",
            "interface": {
                "pattern_id": "piston-pin-bearing",
                "interface_type": "floating_pin_bearing",
            },
        }],
    }
    answer = (
        "Dimension #5 measured 35 mm vs nominal 30 mm. This bore controls "
        "piston-pin bearing clearance. The cylinder bore is also required to "
        "evaluate rework. **Hold the inspected part** -- verify mating data."
    )
    cleaned = server._clean_agent_answer(
        answer, ctx, "How about measured dimension #5?"
    )
    low = cleaned.lower()
    assert "cylinder bore" not in low, cleaned
    assert "bearing clearance" in low and "piston pin" in low, cleaned
    assert "increases bearing clearance" in low, cleaned
    assert "hold the inspected part" not in low, cleaned
    assert "engineering disposition" not in low, cleaned


def test_post_compaction_composition_removes_question_and_noun_fragment():
    rows = [row for row in _rows() if str(row["char_number"]) == "5"]
    ctx = {
        "fai_characteristics": rows,
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": True,
            "needs_clarification": False,
        },
    }
    compacted = (
        "Dimension #5 measured 35 mm vs nominal 30 mm. This bore controls "
        "bearing clearance; an oversize bore increases pin. Does this piston "
        "need another check; this width controls side clearance between. Ring "
        "free play remains within. The "
        "oversize condition creates interference, likely. "
        "Hold the inspected part from assembly pending "
        "engineering disposition."
    )
    cleaned = server._finalize_fai_answer_composition(compacted, ctx)
    low = cleaned.lower()
    assert "increases pin" not in low, cleaned
    assert "does this piston" not in low, cleaned
    assert "between." not in low, cleaned
    assert "within." not in low, cleaned
    assert "controls side clearance." in low, cleaned
    assert "likely." not in low, cleaned
    assert "hold the inspected part" not in low, cleaned
    assert "engineering disposition" not in low, cleaned


def test_explicit_number_remains_visible_in_answer():
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": _rows(),
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": True,
            "needs_clarification": False,
        },
    }
    cleaned = server._clean_agent_answer(
        "Characteristic #5 measured 35 mm vs nominal 30 mm and is 4.95 mm above the upper limit.",
        ctx,
        "How about #5?",
    )
    assert "Characteristic #5" in cleaned


def test_grounding_replacement_uses_only_target_functional_interface():
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": _rows(),
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": True,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "5",
            "interface": {
                "pattern_id": "piston-pin-bearing",
                "interface_type": "floating_pin_bearing",
            },
        }],
        # Unrelated catalog context must not select the cylinder replacement.
        "functional_relationships": [{"pattern_id": "piston-cylinder-guide"}],
    }
    cleaned = server._clean_agent_answer(
        "Characteristic #5 measured 35 mm vs nominal 30 mm and is 4.95 mm oversize. "
        "The pin will rock and knock during motion. Reject this piston and verify the machining setup.",
        ctx,
        "How about #5?",
    )
    low = cleaned.lower()
    assert "rock" not in low and "knock" not in low and "machining setup" not in low
    assert "radial support" in low and "piston pin" in low
    assert "piston-to-cylinder" not in low
    assert "reject this piston" not in low and "scrap" not in low


def test_multiple_target_cleanup_preserves_each_measurement_clause():
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": _rows(),
        "fai_request": {
            "request_scope": "all_failed_characteristics",
            "target_characteristic_ids": ["1", "5", "15"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "1",
            "interface": {"pattern_id": "piston-cylinder-guide", "interface_type": "prismatic_guidance_clearance"},
        }],
    }
    answer = (
        "Outside diameter measured 95 mm vs 90 mm and may bind; "
        "pin bore measured 35 mm vs 30 mm and increases clearance; "
        "ring groove measured 4.8 mm vs 4.3 mm and increases side clearance."
    )
    cleaned = server._clean_agent_answer(answer, ctx, "Summarize all failed FAI results")
    assert "95 mm" in cleaned and "35 mm" in cleaned and "4.8 mm" in cleaned


def test_multiple_target_cleanup_adds_missing_values_without_unrequested_hold():
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": _rows(),
        "fai_request": {
            "request_scope": "all_failed_characteristics",
            "target_characteristic_ids": ["1", "5", "15"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "1",
            "interface": {
                "pattern_id": "piston-cylinder-guide",
                "interface_type": "prismatic_guidance_clearance",
            },
        }],
    }
    answer = (
        "The outside diameter measured 95 mm vs nominal 90 mm. The pin-bore "
        "failure is 4.95 mm beyond its limit, and the ring-groove failure is "
        "0.45 mm beyond its limit. Hold all inspected pistons from assembly "
        "pending engineering disposition."
    )
    cleaned = server._clean_agent_answer(
        answer, ctx, "What are the implications of all current failed FAI results?"
    )
    low = cleaned.lower()
    assert server._fai_number_present(cleaned, 35), cleaned
    assert server._fai_number_present(cleaned, 4.8), cleaned
    assert "hold all inspected pistons" not in low, cleaned
    assert "hold the inspected part" not in low, cleaned
    assert "engineering disposition" not in low, cleaned


def test_pin_bore_impact_answer_is_functional_and_has_no_disposition_instruction():
    row = dict(next(row for row in _rows() if str(row["char_number"]) == "5"))
    row["measured"] = 32.0
    ctx = {
        "active_mode": "assembly",
        "_user_message": "What is the impact of the failed pin-bore on the assembly?",
        "fai_characteristics": [row],
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "5",
            "interface": {
                "pattern_id": "piston-pin-bearing",
                "interface_type": "floating_pin_bearing",
            },
            "adjacent_interfaces": [{"pattern_id": "rod-pin-bearing"}],
        }],
    }
    raw = (
        "The wrist-pin hole diameter measured 32.00 mm against a nominal 30.00 mm "
        "with limits of 29.95 to 30.05 mm, exceeding the upper limit by 1.95 mm. "
        "Hold the inspected part from assembly pending engineering disposition."
    )
    cleaned = server._clean_agent_answer(raw, ctx, ctx["_user_message"])
    low = cleaned.lower()
    assert "piston bosses" in low and "connecting rod" in low, cleaned
    assert "bearing clearance" in low and "radial support" in low, cleaned
    assert "free play" in low and "load" in low, cleaned
    assert "hold" not in low and "disposition" not in low, cleaned


def test_plain_pin_bore_impact_is_exactly_two_direct_sentences():
    row = dict(next(row for row in _rows() if str(row["char_number"]) == "5"))
    row["measured"] = 32.0
    ctx = {
        "active_mode": "assembly",
        "fai_characteristics": [row],
        "fai_request": {
            "request_scope": "specific_characteristic",
            "target_characteristic_ids": ["5"],
            "mentions_characteristic_number": False,
            "needs_clarification": False,
        },
        "affected_functional_interfaces": [{
            "characteristic_id": "5",
            "interface": {
                "pattern_id": "piston-pin-bearing",
                "interface_type": "floating_pin_bearing",
            },
            "adjacent_interfaces": [{"pattern_id": "rod-pin-bearing"}],
        }],
    }
    question = "What is the impact of the failed pin-bore dimension on the assembly?"
    raw = (
        "Wrist-pin hole diameter through the piston measured 32 mm vs nominal "
        "30 mm, 1.95 mm above the upper limit. This bore supports the piston pin "
        "at the piston-to-connecting-rod interface, so the inspected piston would "
        "have increased pin clearance and reduced radial support; actual motion "
        "severity cannot be established without the mating pin measurement and "
        "required clearance."
    )
    cleaned = server._clean_agent_answer(raw, ctx, question)
    assert cleaned == (
        "Wrist-pin hole diameter through the piston measured 32.00 mm, 1.95 mm "
        "above the 30.05 mm upper limit. The oversized bore increases bearing "
        "clearance around the piston pin, reducing radial support in the piston "
        "bosses and introducing free play where the piston transfers load to the "
        "connecting rod during reciprocation."
    )
    assert server._response_sentence_count(cleaned) == 2
    assert "cannot be established" not in cleaned.lower()
    assert "mating pin measurement" not in cleaned.lower()

    assert server._compose_fai_assembly_impact_answer(
        ctx, "Show the affected components in motion."
    ) is None
    assert server._compose_fai_assembly_impact_answer(
        ctx, "How severe is the impact and exactly how much free play is created?"
    ) is None


def _run_without_pytest() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
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
