"""Safety and contract tests for provisional chat streaming."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.chat_streaming import (
    BLOCK_DIRECTIVES,
    LINE_DIRECTIVE_MARKERS,
    StreamDirectiveFilter,
    SentenceStreamBuffer,
    provisional_display_prefix,
)


FIXTURE = ROOT / "tests" / "fixtures" / "agent_chat_stream_golden.json"


def _run_chunks(chunks):
    firewall = StreamDirectiveFilter()
    output = []
    directives = []
    for chunk in chunks:
        release = firewall.feed(chunk)
        output.append(release.text)
        if release.directive:
            directives.append(release.directive)
    release = firewall.finish()
    output.append(release.text)
    if release.directive:
        directives.append(release.directive)
    return "".join(output), directives


def test_golden_fixture_is_ascii_and_versioned():
    raw = FIXTURE.read_bytes()
    assert all(byte < 128 for byte in raw)
    payload = json.loads(raw.decode("ascii"))
    assert payload["version"] == 1
    assert len(payload["cases"]) >= 5


def test_firewall_matches_golden_prefix_at_every_split():
    payload = json.loads(FIXTURE.read_text(encoding="ascii"))
    for case in payload["cases"]:
        text = case["raw"]
        expected = case["visible_prefix"]
        chunkings = [[text], list(text)]
        chunkings.extend([[text[:split], text[split:]] for split in range(len(text) + 1)])
        for chunks in chunkings:
            actual, _ = _run_chunks(chunks)
            assert actual == expected, (case["id"], chunks, actual, expected)


def test_every_registered_line_marker_is_hidden_with_case_and_spacing_variants():
    for marker in LINE_DIRECTIVE_MARKERS:
        variants = (
            f"Safe prose.\n{marker}: payload",
            f"Safe prose.\n  {marker.lower()} : payload",
            f"Safe prose.\n\t{marker.title()}\t:\tpayload",
            f"Safe prose.\n{marker}",
        )
        for text in variants:
            actual, directives = _run_chunks(list(text))
            assert actual == "Safe prose.\n", (marker, text, actual)
            assert directives and directives[0].kind == "line_marker"


def test_malformed_and_unterminated_blocks_never_leak():
    variants = (
        "Safe.<tool_calls",
        "Safe.< TOOL_CALLS ",
        "Safe.[UI_ACTIONS",
        "Safe.[ ui_actions ",
        "Safe.<tool_calls>{bad json",
        "Safe.[UI_ACTIONS] {bad json",
    )
    for text in variants:
        actual, _ = _run_chunks(list(text))
        assert actual == "Safe.", (text, actual)


def test_reference_prefix_and_incremental_filter_agree():
    openers = [spec.opener for spec in BLOCK_DIRECTIVES]
    samples = [
        "No machine syntax here.",
        "Answer first.\n" + openers[0] + "[]</tool_calls>",
        "Answer first.\n" + openers[1] + "{}[/UI_ACTIONS]",
        "Answer first.\nFAI_FILL: #1: 10.2",
    ]
    for text in samples:
        actual, _ = _run_chunks([text[:3], text[3:9], text[9:]])
        assert actual == provisional_display_prefix(text)


def test_sentence_buffer_waits_for_complete_boundaries():
    buffer = SentenceStreamBuffer()
    assert list(buffer.feed("Reject. The bore")) == ["Reject."]
    assert list(buffer.feed(" is oversize. Check")) == ["The bore is oversize."]
    assert list(buffer.finish()) == ["Check"]


if __name__ == "__main__":
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
    raise SystemExit(1 if failures else 0)
