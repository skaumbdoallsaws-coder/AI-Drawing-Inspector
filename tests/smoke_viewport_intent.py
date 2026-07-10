"""Playwright smoke test for the hybrid viewport intent layer.

Drives the LIVE app (default http://127.0.0.1:8021). Flow:
    load part 100006 -> ensure motion package context -> Report tab ->
    ask an FAI disposition question -> ask the typo-phrased
    "can you the show the affected motion?" -> assert the classifier +
    deterministic executor produced: activeTab=assembly, motionPlaying,
    motionPkgMode, motionRpm 30, affected group parts highlighted.

Operator-runnable diagnostic (needs a running server with a real
ANTHROPIC_API_KEY); not part of the offline pytest suite.

Outputs:
    runtime_logs/viewport_intent_smoke.json
    runtime_logs/viewport_intent_smoke.png
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8021/")
PART_NUMBER = os.environ.get("SMOKE_PART_NUMBER", "100006")
FAI_QUESTION = "For FAI item #1, what does this deviation mean for the piston?"
MOTION_QUESTION = "can you the show the affected motion?"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    findings: dict = {"url": APP_URL, "part": PART_NUMBER, "checks": {}}

    def record(name: str, ok: bool, detail=None):
        findings["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail is not None and not ok else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.on("console", lambda msg: (
            print(f"[browser:{msg.type}] {msg.text}")
            if any(k in msg.text for k in ("ViewportIntent", "MotionPkg", "ToolDispatch", "error"))
            else None))
        page.on("pageerror", lambda err: print(f"[browser:error] {err}"))

        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window.__compareDbg && window._handleAgentSend", timeout=30_000)

        # 1. Load the part through the real search UI.
        page.fill("#partSearch", PART_NUMBER)
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(600)
        item = page.locator(f".search-dropdown-item:has-text('{PART_NUMBER}')").first
        item.click()
        page.wait_for_function(
            f"window.__compareDbg.state.partNumber === '{PART_NUMBER}'", timeout=30_000)
        record("part_loaded", True)

        # 2. Make sure the motion package summary is available (the piston's
        #    parent assembly context). Visit the Assembly tab once if the
        #    background load has not populated it yet.
        try:
            page.wait_for_function(
                "window.__compareDbg.state.motionPkgInfo && window.__compareDbg.state.motionPkgInfo.summary",
                timeout=10_000)
        except Exception:
            page.click(".tab[data-tab='assembly']")
            page.wait_for_function(
                "window.__compareDbg.state.motionPkgInfo && window.__compareDbg.state.motionPkgInfo.summary",
                timeout=45_000)
        record("motion_summary_loaded", True)

        # 3. Report tab + Sage.
        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        page.wait_for_timeout(800)

        def ask(question: str, timeout_ms: int = 240_000) -> str:
            # Await the whole turn inside the page: handleAgentSend resolves
            # only after the response is processed and tool calls executed,
            # which serializes turns (a second send while the previous turn
            # is still waiting is silently dropped by the session guard).
            sent = page.evaluate(
                "async (q) => { try { window._agentInput.value = q;"
                " await window._handleAgentSend(); return { sent: true }; }"
                " catch (err) { return { sent: false, error: String(err).slice(0, 300) }; } }",
                question)
            if not sent.get("sent"):
                raise RuntimeError(f"send failed: {sent.get('error')}")
            page.wait_for_timeout(1000)
            return page.evaluate(
                "() => { const m = document.querySelectorAll('#agentMessages .agent-msg-row.assistant');"
                " return m.length ? m[m.length - 1].innerText : ''; }")

        # 4. FAI disposition question (language + encoding checks).
        fai_answer = ask(FAI_QUESTION)
        findings["fai_answer"] = fai_answer[:600]
        record("fai_answer_received", bool(fai_answer.strip()))
        record("fai_no_mojibake", "Â" not in fai_answer and "â€" not in fai_answer,
               fai_answer[:200])
        _lower = fai_answer.lower()
        record("fai_no_catastrophic_claims",
               ("seize" not in _lower and "jam" not in _lower) or "likely" in _lower or "may" in _lower,
               fai_answer[:200])

        # 5. The typo-phrased motion request from the Report tab.
        motion_answer = ask(MOTION_QUESTION)
        findings["motion_answer"] = motion_answer[:600]

        # Give playback a moment to bind + start.
        try:
            page.wait_for_function("window.__compareDbg.state.motionPlaying === true", timeout=20_000)
        except Exception:
            pass
        snap = page.evaluate("""
            (() => {
                const s = window.__compareDbg.state;
                return {
                    activeTab: s.activeTab,
                    motionPlaying: !!s.motionPlaying,
                    motionPkgMode: !!s.motionPkgMode,
                    motionRpm: s.motionRpm,
                    highlighted: Array.from(s.partExplorerAgentParts || []).sort(),
                };
            })();
        """)
        findings["viewport_state"] = snap
        record("activeTab_assembly", snap["activeTab"] == "assembly", snap)
        record("motionPlaying", snap["motionPlaying"] is True, snap)
        record("motionPkgMode", snap["motionPkgMode"] is True, snap)
        record("motionRpm_30", abs(float(snap["motionRpm"] or 0) - 30) < 0.5, snap)
        record("affected_group_highlighted", len(snap["highlighted"]) > 0, snap)
        record("motion_answer_honest",
               ("did not start" in motion_answer.lower()) != snap["motionPlaying"]
               if "did not start" in motion_answer.lower() or "showing" in motion_answer.lower()
               else True,
               motion_answer[:200])

        png = OUT_DIR / "viewport_intent_smoke.png"
        page.screenshot(path=str(png), full_page=False)
        findings["screenshot"] = str(png.relative_to(REPO_ROOT))
        browser.close()

    out = OUT_DIR / "viewport_intent_smoke.json"
    out.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"findings -> {out.relative_to(REPO_ROOT)}")
    failed = [k for k, v in findings["checks"].items() if not v["ok"]]
    print(f"{len(findings['checks']) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
