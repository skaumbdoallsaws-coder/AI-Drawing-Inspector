"""Shared server/browser viewport authorization vectors.

The browser half is exercised by test_viewport_intent_mapping.js. This file
loads the exact same fixture and evaluates the server-side gate. Separate
hand-written allow/veto suites are intentionally not used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "viewport_authorization_cases.json"


def _fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="ascii"))


def test_fixture_shape_and_ids_are_stable():
    payload = _fixture()
    assert payload["schema_version"] == 1
    cases = payload.get("cases")
    assert isinstance(cases, list) and len(cases) >= 30
    ids = [case.get("id") for case in cases]
    assert all(isinstance(case_id, str) and case_id for case_id in ids)
    assert len(ids) == len(set(ids))
    for case in cases:
        assert isinstance(case.get("message"), str) and case["message"].strip()
        expected = case.get("expected")
        assert set(expected) == {
            "explicit_action", "state_question", "allow_additive", "allow_destructive"
        }
        assert all(isinstance(value, bool) for value in expected.values())


def test_fixture_authorization_columns_are_internally_consistent():
    for case in _fixture()["cases"]:
        expected = case["expected"]
        assert expected["allow_additive"] is expected["explicit_action"], case["id"]
        assert expected["allow_destructive"] is (
            expected["explicit_action"] and not expected["state_question"]
        ), case["id"]


def test_server_gate_matches_shared_browser_vectors():
    for case in _fixture()["cases"]:
        message = case["message"]
        expected = case["expected"]
        actual = {
            "explicit_action": server._message_explicitly_requests_viewport_change(message),
            "state_question": server._is_viewport_state_question(message),
            "allow_additive": server._viewport_write_authorized(message, destructive=False),
            "allow_destructive": server._viewport_write_authorized(message, destructive=True),
        }
        assert actual == expected, f"{case['id']}: expected={expected}, actual={actual}"


if __name__ == "__main__":
    import traceback

    tests = sorted(
        (name, obj) for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    )
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"PASS {name}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
