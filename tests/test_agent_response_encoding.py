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
