"""FAI response grounding cleaner tests.

The cleaner keeps disposition prose measured and grounded:
- "scrap" verdicts become reject/escalate wording unless the user or the
  FAI context used the word;
- invented failure narratives (slam/knock/seize/grip/"within minutes"/
  catastrophic) are cut back to their numeric facts plus a canonical
  escalate-for-disposition sentence;
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
    assert "reject" in low, cleaned
    assert "catastrophic" not in low, cleaned
    assert "within minutes" not in low, cleaned
    assert "slam" not in low, cleaned
    assert "knock" not in low, cleaned
    assert "grip" not in low, cleaned
    assert "tooling" not in low, cleaned
    assert "check the last 10" not in low, cleaned
    assert "escalate it for disposition" in low, cleaned


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
    assert "applies to the inspected part" in low, cleaned


def test_multi_instance_claim_allowed_when_multiple_rows_failed():
    text = "The oversize bore creates lateral play at every piston pin joint."
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=4)
    assert "every piston pin joint" in cleaned.lower(), cleaned


def test_numeric_facts_survive_claim_removal():
    text = ("#5 measured 32.000 mm against 30.000 +/-0.050 mm, 1.950 mm above "
            "the upper limit, so the piston will jam in service.")
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=1)
    assert "1.950 mm above the upper limit" in cleaned, cleaned
    assert "jam" not in cleaned.lower(), cleaned


def test_clean_measured_answer_passes_through():
    text = ("#5 measured 32.000 mm vs nominal 30.000 +/-0.050 mm: 1.950 mm "
            "above the upper limit. It is outside tolerance and should be "
            "rejected or escalated for disposition. As an internal bore above "
            "its upper limit, it likely gives increased clearance and a "
            "looser fit with the mating pin.")
    cleaned = server._clean_report_fai_response(text, support_text="",
                                                failed_row_count=1)
    assert "1.950 mm above the upper limit" in cleaned, cleaned
    assert "rejected or escalated for disposition" in cleaned, cleaned
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
    assert "Characteristic #5" in cleaned, cleaned
    assert "measured 32.0 mm vs nominal 30.0 mm" in cleaned, cleaned
    assert "1.95 mm above the upper limit" in cleaned, cleaned


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
