import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


def test_agent_response_cleaner_removes_mojibake_dash_and_quotes():
    text = (
        "The Piston reciprocates in the engine cylinder \u00e2\" it is the "
        "moving compression face. It uses \u00e2\u20ac\u0153quoted\u00e2\u20ac\u009d "
        "text, another dash \u0101\u20ac\", a \u017230 bore, and a direction "
        "arrow \u00e2\u2020\u2019 here."
    )

    cleaned = server._clean_agent_response(text)

    assert cleaned == (
        'The Piston reciprocates in the engine cylinder - it is the '
        'moving compression face. It uses "quoted" text, another dash -, '
        'a diameter 30 bore, and a direction arrow -> here.'
    )
    assert "\u00e2" not in cleaned
    assert "\u0101" not in cleaned
    assert "\u0172" not in cleaned
    assert "\ufffd" not in cleaned


def test_agent_response_cleaner_normalizes_smart_punctuation():
    text = "A piston - but with smart dash \u2014 and smart quotes \u201ctest\u201d."

    cleaned = server._clean_agent_response(text)

    assert cleaned == 'A piston - but with smart dash - and smart quotes "test".'

def test_agent_response_cleaner_removes_mojibake_plus_minus():
    # "Â±" is the mojibake form of the plus-minus sign that leaked
    # into FAI deviation answers as "Â±0.05mm".
    text = "Tolerance is Â±0.05mm on this characteristic."
    cleaned = server._clean_agent_response(text)
    assert cleaned == "Tolerance is +/-0.05mm on this characteristic."
    assert "Â" not in cleaned


def test_agent_response_cleaner_converts_engineering_symbols_to_ascii():
    text = "Nominal 25.400 ± 0.05 mm at 20°, volume 5 mm³."
    cleaned = server._clean_agent_response(text)
    for ch in ("±", "°", "³"):
        assert ch not in cleaned
    assert "+/-" in cleaned and "deg" in cleaned and "mm^3" in cleaned


def test_report_fai_response_cleaner_removes_unsupported_damage_claims():
    text = (
        "Reject. The bore is out of tolerance. "
        "Forced assembly risks pin galling or boss fracture. "
        "Escalate for disposition."
    )
    cleaned = server._clean_report_fai_response(text)
    lower = cleaned.lower()
    assert "galling" not in lower
    assert "fracture" not in lower
    assert "forced assembly" not in lower
    assert "exact interference or failure mode is not determined" in cleaned


def test_report_fai_response_cleaner_preserves_decimal_measurements():
    text = (
        "Reject. The pin bore measured 30.100mm on an upper limit of "
        "30.050mm -- that is +0.050mm oversize, so the pin will float "
        "and rock in the bore."
    )
    cleaned = server._clean_report_fai_response(text)
    lower = cleaned.lower()
    assert "30.100mm" in cleaned
    assert "30.050mm" in cleaned
    assert "+0.050mm" in cleaned
    assert "pin will." not in cleaned
    assert "float" not in lower
    assert "rock" not in lower
    assert "exact interference or failure mode is not determined" in cleaned


def test_report_fai_response_cleaner_trims_incomplete_allowing_clause():
    text = (
        "Reject. The +0.050mm oversize pin bore creates excessive clearance "
        "with the connecting rod small end, likely allowing piston rock at the pin joint."
    )
    cleaned = server._clean_report_fai_response(text)
    lower = cleaned.lower()
    assert "excessive clearance with the connecting rod small end." in cleaned
    assert "allowing piston" not in lower
    assert "rock" not in lower
    assert "exact interference or failure mode is not determined" in cleaned


def test_report_fai_response_cleaner_trims_incomplete_increasing_clause():
    text = (
        "Accept. The +0.050mm oversize pin bore creates excessive clearance "
        "with the connecting rod small end, likely increasing pin rock."
    )
    cleaned = server._clean_report_fai_response(text)
    lower = cleaned.lower()
    assert cleaned.startswith("Reject.")
    assert "excessive clearance with the connecting rod small end." in cleaned
    assert "increasing pin" not in lower
    assert "rock" not in lower


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
