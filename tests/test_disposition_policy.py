"""Engineer-approved FAI disposition policy regressions."""

from __future__ import annotations

import copy
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from ai_inspector.product_intelligence import (  # noqa: E402
    DispositionPolicyError,
    DispositionPolicyRegistry,
    evaluate_disposition_policy,
    validate_disposition_policy,
)


def _row(measured: float = 32.0) -> dict:
    return {
        "char_number": 5,
        "description": "Wrist-pin hole diameter through the piston",
        "nominal": 30.0,
        "measured": measured,
        "lower_limit": 29.95,
        "upper_limit": 30.05,
        "status": "FAIL",
    }


def _interfaces() -> list[dict]:
    return [{
        "characteristic_id": "5",
        "interface": {"pattern_id": "piston-pin-bearing"},
    }]


def test_approved_pin_bore_policy_returns_final_scrap_decision():
    policy = DispositionPolicyRegistry().load("100001")
    assert policy is not None
    decision = evaluate_disposition_policy(
        policy,
        part_number="100006",
        fai_rows=[_row()],
        target_characteristic_ids=["5"],
        affected_interfaces=_interfaces(),
    )
    assert decision is not None
    assert decision.disposition == "scrap_replace"
    assert math.isclose(decision.deviation, 1.95, abs_tol=1e-9)
    assert decision.use_as_is_allowed is False
    assert decision.rework_allowed is False


def test_policy_does_not_auto_scrap_a_borderline_failure():
    policy = DispositionPolicyRegistry().load("100001")
    decision = evaluate_disposition_policy(
        policy,
        part_number="100006",
        fai_rows=[_row(30.06)],
        target_characteristic_ids=["5"],
        affected_interfaces=_interfaces(),
    )
    assert decision is None


def test_policy_requires_approved_delegated_authority():
    policy = DispositionPolicyRegistry().load("100001")
    assert policy is not None
    policy["authority"]["status"] = "draft"
    decision = evaluate_disposition_policy(
        policy,
        part_number="100006",
        fai_rows=[_row()],
        target_characteristic_ids=["5"],
        affected_interfaces=_interfaces(),
    )
    assert decision is None


def test_policy_rejects_string_boolean_fields():
    policy = DispositionPolicyRegistry().load("100001")
    assert policy is not None
    invalid = copy.deepcopy(policy)
    invalid["rules"][0]["decision"]["rework_allowed"] = "false"
    try:
        validate_disposition_policy(invalid)
    except DispositionPolicyError:
        return
    raise AssertionError("string boolean must be rejected")


def test_server_returns_two_sentence_decision_without_model_escalation():
    message = "What is the recommended disposition and next action?"
    ctx = {
        "assembly_number": "100001",
        "part_number": "100006",
        "fai_characteristics": [_row()],
        "affected_functional_interfaces": _interfaces(),
    }
    server._apply_fai_request_targeting(ctx, message)
    result = server._approved_fai_disposition_result(
        ctx, message, "deviation-analyst"
    )
    assert result is not None
    assert result["tool_source"] == "approved_disposition_policy"
    assert result["response"] == (
        "**Scrap and replace this piston; do not assemble it.** "
        "The wrist-pin bore measured 32.00 mm, 1.95 mm above the 30.05 mm "
        "upper limit; this gross oversize condition is not eligible for "
        "use-as-is or rework."
    )
    lowered = result["response"].lower()
    assert "engineering disposition" not in lowered
    assert "engineering must" not in lowered
    assert server._response_sentence_count(result["response"]) == 2


def test_server_falls_back_when_no_approved_policy_exists():
    message = "What is the recommended disposition?"
    ctx = {
        "assembly_number": "SYNTH-NO-POLICY",
        "part_number": "SYNTH-PART",
        "fai_characteristics": [_row()],
    }
    server._apply_fai_request_targeting(ctx, message)
    assert server._approved_fai_disposition_result(
        ctx, message, "deviation-analyst"
    ) is None


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
