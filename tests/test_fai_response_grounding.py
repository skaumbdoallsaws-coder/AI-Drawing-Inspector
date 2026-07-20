"""FAI response grounding cleaner tests.

The cleaner keeps FAI prose measured and grounded:
- "scrap" verdicts become reject wording unless the user or the
  FAI context used the word;
- invented failure narratives (slam/knock/seize/grip/"within minutes"/
  catastrophic) are cut back to their numeric facts plus a neutral evidence
  limitation when the mating interface is unavailable;
- invented process-control directives (lot checks, tooling drift) are
  dropped unless asked about;
- a single failed inspected part is never multiplied into "every joint".

Run: python tests/test_fai_response_grounding.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


OBSERVED_BAD_ANSWER = (
    "Scrap. The diameter 32mm pin bore (#5, +2mm oversize) will not grip the "
    "diameter 30mm piston pin - the connecting rod small-end will slam "
    "side-to-side during reciprocation, causing severe audible knock and "
    "catastrophic piston-pin bore wear within minutes of operation. You must "
    "scrap this piston and verify that the tooling for the diameter 30mm bore "
    "operation hasn't drifted - check the last 10 parts from this lot "
    "immediately."
)


def test_observed_bad_answer_is_fully_grounded():
    cleaned = server._clean_report_fai_response(
        OBSERVED_BAD_ANSWER, support_text="", failed_row_count=1)
    low = cleaned.lower()
    assert "scrap" not in low, cleaned
    assert "reject" not in low, cleaned
    assert "catastrophic" not in low, cleaned
    assert "within minutes" not in low, cleaned
    assert "slam" not in low, cleaned
    assert "knock" not in low, cleaned
    assert "grip" not in low, cleaned
    assert "tooling" not in low, cleaned
    assert "check the last 10" not in low, cleaned
    assert "available context does not establish" in low, cleaned
    assert "disposition" not in low, cleaned


def test_scrap_and_seize_allowed_when_user_asked():
    text = "Scrap this part. The pin may seize during operation."
    support = "should we scrap it? will it seize?"
    cleaned = server._clean_report_fai_response(text, support_text=support,
                                                failed_row_count=1)
    assert "Scrap" in cleaned, cleaned
    assert "seize" in cleaned.lower(), cleaned


def test_tooling_directive_kept_when_asked_about_tooling():
    text = "Verify that the tooling has not drifted before running more parts."
    support = "could this be tooling drift on the lot?"
    cleaned = server._clean_report_fai_response(text, support_text=support,
                                                failed_row_count=1)
    assert "tooling" in cleaned.lower(), cleaned


def test_tooling_directive_dropped_when_uninvited():
    text = ("Measured 32.000 mm exceeds the upper limit. Verify that the "
            "tooling has not drifted and check the last 10 parts from this lot.")
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=1)
    low = cleaned.lower()
    assert "tooling" not in low, cleaned
    assert "last 10" not in low, cleaned
    assert "32.000 mm" in cleaned, cleaned


def test_single_failed_row_is_not_multiplied_across_instances():
    text = "The oversize bore creates lateral play at every piston pin joint."
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=1)
    low = cleaned.lower()
    assert "every piston pin joint" not in low, cleaned
    assert "lateral play" in low, cleaned


def test_multiple_failed_dimensions_do_not_authorize_multiple_instances():
    text = "The oversize bore creates lateral play at every piston pin joint."
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=4)
    assert "every piston pin joint" not in cleaned.lower(), cleaned
    assert "lateral play" in cleaned.lower(), cleaned


def test_explicit_instance_evidence_can_authorize_multiple_instances():
    text = "The oversize bore creates lateral play at every piston pin joint."
    support = '{"failed_instance_count": 4}'
    cleaned = server._clean_report_fai_response(
        text, support_text=support, failed_row_count=1
    )
    assert "every piston pin joint" in cleaned.lower(), cleaned


def test_supported_term_does_not_hide_later_unsupported_claims():
    text = (
        "The oversize bore creates excessive radial clearance, permitting "
        "uncontrolled pin float, piston-boss rock, and audible knock."
    )
    support = (
        '{"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-pin-bearing","functions":'
        '["permit intended pin float"],"qualitative_requirements":'
        '["controlled bearing clearance"]}}]}'
    )
    cleaned = server._clean_report_fai_response(
        text, support_text=support, failed_row_count=1
    )
    low = cleaned.lower()
    assert "radial clearance" in low, cleaned
    assert "rock" not in low, cleaned
    assert "knock" not in low, cleaned
    assert "audible" not in low, cleaned
    assert not cleaned.rstrip().endswith("permitting."), cleaned


def test_safe_function_prefix_prevents_duplicate_fallback_after_later_claim():
    support = (
        '{"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-pin-bearing","functions":'
        '["support the piston pin","transfer piston load into the pin"]},'
        '"adjacent_interfaces":[{"pattern_id":"rod-pin-bearing",'
        '"functions":["transfer load between the pin and rod"]}]}]}'
    )
    state = server._new_fai_sentence_clean_state(support, failed_row_count=1)
    first = server._clean_fai_sentence(
        "The oversize bore increases pin clearance and reduces radial support, "
        "allowing piston rock.",
        state,
    )
    second = server._clean_fai_sentence(
        "The piston-pin-connecting rod interface will exhibit audible knock.",
        state,
    )
    joined = " ".join(first + second)
    assert "increases pin clearance" in joined.lower(), joined
    assert "rock" not in joined.lower() and "knock" not in joined.lower(), joined
    assert joined.lower().count("hold the inspected part") == 0, joined


def test_pin_bore_function_sentence_names_the_supported_load_path():
    support = (
        '{"deviation_direction":"above_upper",'
        '"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-pin-bearing"},"adjacent_interfaces":'
        '[{"pattern_id":"rod-pin-bearing"}]}]}'
    )
    sentence, coverage = server._fai_function_requirement_sentence(support)
    low = sentence.lower()
    assert "piston bosses" in low, sentence
    assert "connecting rod" in low, sentence
    assert "load" in low and "free play" in low, sentence
    assert coverage is not None and coverage.search(sentence), sentence


def test_claim_removal_does_not_leave_that_permits_noun_fragment():
    text = (
        "The oversize bore creates excessive pin clearance that permits pin "
        "rock and audible knock."
    )
    cleaned = server._clean_report_fai_response(
        text, support_text="", failed_row_count=3
    )
    low = cleaned.lower()
    assert "rock" not in low and "knock" not in low, cleaned
    assert "that permits pin" not in low and "permits pin." not in low, cleaned


def test_normal_function_text_does_not_authorize_failure_mode_claim():
    text = "The oversize piston will bind during reciprocation."
    support = (
        "What is the assembly impact?\n"
        '{"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-ring-retention","qualitative_requirements":'
        '["avoid groove binding"]}}]}'
    )
    cleaned = server._clean_report_fai_response(
        text, support_text=support, failed_row_count=3
    )
    assert "bind" not in cleaned.lower(), cleaned


def test_unrequested_wear_claim_is_removed_without_losing_clearance_effect():
    text = (
        "The oversize groove increases ring side clearance and degrades sealing, "
        "accelerating groove wear."
    )
    cleaned = server._clean_report_fai_response(
        text, support_text="What is the assembly impact?", failed_row_count=1
    )
    low = cleaned.lower()
    assert "side clearance" in low, cleaned
    assert "wear" not in low, cleaned


def test_unsupported_risk_tail_does_not_leave_sentence_fragment():
    text = (
        "An oversize piston reduces radial clearance or creates interference, "
        "risking seizure or scuffing."
    )
    support = (
        '{"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-cylinder-guide","qualitative_requirements":'
        '["controlled radial clearance","free axial translation"]}}]}'
    )
    cleaned = server._clean_report_fai_response(
        text, support_text=support, failed_row_count=3
    )
    low = cleaned.lower()
    assert "reduces radial clearance or creates interference" in low, cleaned
    assert "seiz" not in low, cleaned
    assert "scuff" not in low, cleaned
    assert "risking." not in low, cleaned


def test_supported_consequence_removes_unrequested_hold_after_claim_removal():
    text = (
        "The 5 mm oversize creates excessive radial clearance, permitting "
        "uncontrolled pin float, piston-boss rock, and audible knock; hold the "
        "inspected piston from assembly pending engineering disposition."
    )
    support = (
        '{"affected_functional_interfaces":[{"interface":'
        '{"pattern_id":"piston-pin-bearing","functions":'
        '["permit intended pin float"],"qualitative_requirements":'
        '["controlled bearing clearance"]}}]}'
    )
    cleaned = server._clean_report_fai_response(
        text, support_text=support, failed_row_count=1
    )
    low = cleaned.lower()
    assert "excessive radial clearance" in low, cleaned
    assert "rock" not in low and "knock" not in low, cleaned
    assert "hold the inspected piston" not in low, cleaned
    assert "engineering disposition" not in low, cleaned


def test_numeric_facts_survive_claim_removal():
    text = ("#5 measured 32.000 mm against 30.000 +/-0.050 mm, 1.950 mm above "
            "the upper limit, so the piston will jam in service.")
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=1)
    assert "1.950 mm above the upper limit" in cleaned, cleaned
    assert "jam" not in cleaned.lower(), cleaned


def test_claim_removal_preserves_complete_mating_noun_phrase():
    text = (
        "This oversize piston running surface would reduce the radial clearance "
        "between the piston and cylinder bore, likely causing interference, "
        "binding during reciprocating motion, or preventing assembly altogether."
    )
    cleaned = server._clean_report_fai_response(
        text,
        support_text="Main outside diameter measured outside tolerance.",
        failed_row_count=1,
    )
    assert "between the piston and cylinder bore." in cleaned, cleaned
    assert "between the piston." not in cleaned, cleaned
    assert "binding" not in cleaned.lower(), cleaned
    assert "preventing assembly" not in cleaned.lower(), cleaned

    second = (
        "The oversized condition would reduce clearance or create interference "
        "with the mating cylinder bore, potentially preventing free axial "
        "translation, causing binding during reciprocating motion."
    )
    cleaned_second = server._clean_report_fai_response(
        second,
        support_text="Main outside diameter measured outside tolerance.",
        failed_row_count=1,
    )
    assert "would reduce clearance or create interference" in cleaned_second, cleaned_second
    assert "preventing free axial translation" in cleaned_second, cleaned_second
    assert "binding" not in cleaned_second.lower(), cleaned_second


def test_clean_measured_answer_removes_unrequested_disposition_clause():
    text = ("#5 measured 32.000 mm vs nominal 30.000 +/-0.050 mm: 1.950 mm "
            "above the upper limit. It is outside tolerance and should be "
            "rejected or escalated for disposition. As an internal bore above "
            "its upper limit, it likely gives increased clearance and a "
            "looser fit with the mating pin.")
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=1)
    assert "1.950 mm above the upper limit" in cleaned, cleaned
    assert "rejected or escalated for disposition" not in cleaned, cleaned
    assert "disposition" not in cleaned.lower(), cleaned
    assert "increased clearance" in cleaned, cleaned
    assert "likely" in cleaned, cleaned


def test_missing_numeric_answer_gets_failed_row_prefix():
    support = (
        "FAI TABLE:\n"
        "  #5: Wrist-pin hole diameter through the piston. -- nominal=30.0 "
        "tol=+0.05/-0.05 measured=32.0 [FAIL] limits=[29.95, 30.05] "
        "delta_from_nominal=2.0 direction=above_upper out_of_tolerance_by=1.95 "
        "fit_feature_kind=internal_bore fit_effect_hint=increased clearance\n"
    )
    text = (
        "The measured deviation applies to the inspected part; the FAI data "
        "does not show other instances of this component out of tolerance. "
        "This bore should be rejected and escalated for disposition."
    )
    cleaned = server._clean_report_fai_response(text, support_text=support,
                                                failed_row_count=1)
    assert "Wrist-pin hole diameter through the piston" in cleaned, cleaned
    assert "Characteristic #5" not in cleaned, cleaned
    assert "measured 32.0 mm vs nominal 30.0 mm" in cleaned, cleaned
    assert "1.95 mm above the upper limit" in cleaned, cleaned


def test_missing_numeric_answer_gets_prefix_from_production_json_support():
    # Reproduces the live T1 miss: the cleaner call site passes the user
    # message plus json.dumps(fai_characteristics), NOT rendered context
    # lines. The backstop must fire on that shape too.
    import json as _json

    rows = [
        {"char_number": "1", "description": "Overall length", "nominal": 90.0,
         "tol_plus": 0.0, "tol_minus": 0.0, "measured": None, "status": "PENDING"},
        {"char_number": "5", "description": "Pin bore diameter", "nominal": 30.0,
         "tol_plus": 0.05, "tol_minus": 0.05, "measured": 32.0, "status": "FAIL",
         "lower_limit": 29.95, "upper_limit": 30.05,
         "deviation_direction": "above_upper", "out_of_tolerance_by": 1.95},
    ]
    support = (
        "what is the impact on the assembly of the failed dimension in the fai table?\n"
        + _json.dumps(rows, default=str)
    )
    text = (
        "The measured deviation applies to the inspected part; the FAI data "
        "does not show other instances of this component out of tolerance. "
        "If this is a controlled fit dimension, escalate it for disposition "
        "against the mating part requirements."
    )
    cleaned = server._clean_report_fai_response(text, support_text=support,
                                                failed_row_count=1)
    assert "Pin bore diameter" in cleaned, cleaned
    assert "Characteristic #5" not in cleaned, cleaned
    assert "measured 32.0 mm vs nominal 30.0 mm" in cleaned, cleaned
    assert "1.95 mm above the upper limit" in cleaned, cleaned


def test_partial_numeric_answer_missing_nominal_gets_complete_prefix():
    import json as _json

    rows = [{
        "char_number": 1, "description": "Outside diameter", "nominal": 90.0,
        "tol_plus": 0.05, "tol_minus": 0.05, "measured": 88.0,
        "lower_limit": 89.95, "upper_limit": 90.05,
        "out_of_tolerance_by": 1.95, "deviation_direction": "below_lower",
        "status": "FAIL",
    }]
    answer = "The measured 88.00 mm diameter is 1.95 mm below the 89.95 mm lower limit."
    cleaned = server._clean_report_fai_response(
        answer,
        support_text="question\n" + _json.dumps(rows),
        failed_row_count=1,
    )
    assert "vs nominal 90.0 mm" in cleaned, cleaned
    assert cleaned.endswith(answer), cleaned


def test_grounding_prefix_compacts_float_artifacts():
    prefix = server._fai_failed_row_prefix_from_rows([{
        "char_number": 1, "description": "Outside diameter", "nominal": 90,
        "tol_plus": 0.05, "tol_minus": 0.05, "measured": 88,
        "lower_limit": 89.95, "upper_limit": 90.05,
        "out_of_tolerance_by": 1.9500000000000028,
        "deviation_direction": "below_lower", "status": "FAIL",
    }])
    assert "1.95 mm below the lower limit" in prefix, prefix
    assert "1.9500000000000028" not in prefix, prefix


def test_grounding_prefix_derives_exceedance_from_measured_value_and_limits():
    prefix = server._fai_failed_row_prefix_from_rows([{
        "char_number": 5,
        "description": "Wrist-pin hole diameter through the piston",
        "nominal": 30.0,
        "measured": 32.0,
        "lower_limit": 29.95,
        "upper_limit": 30.05,
        "status": "FAIL",
    }], mention_characteristic_number=False)
    assert "1.95 mm above the upper limit" in prefix, prefix
    assert "outside tolerance" not in prefix, prefix


def test_numeric_out_of_tolerance_row_is_grounded_while_status_is_pending():
    import json as _json

    rows = [
        {"char_number": "5", "description": "Pin bore diameter", "nominal": 30.0,
         "tol_plus": 0.0, "tol_minus": 0.0, "measured": 32.0, "status": "PENDING"}
    ]
    support = "FAI TABLE:\n" + _json.dumps(rows, default=str)
    cleaned = server._clean_report_fai_response(
        "The measured deviation applies to the inspected part.",
        support_text=support,
        failed_row_count=0,
    )
    assert "Pin bore diameter" in cleaned, cleaned
    assert "Characteristic #5" not in cleaned, cleaned
    assert "measured 32.0 mm vs nominal 30.0 mm" in cleaned, cleaned


if __name__ == "__main__":
    import traceback

    _tests = sorted(
        (name, obj) for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    )
    _passed = _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            _passed += 1
            print(f"PASS {_name}")
        except Exception:  # noqa: BLE001
            _failed += 1
            print(f"FAIL {_name}")
            traceback.print_exc()
    print(f"{_passed} passed, {_failed} failed")
    raise SystemExit(1 if _failed else 0)
