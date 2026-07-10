"""Playwright smoke test for the FAI explanation vs. viewport-action contract.

Drives the LIVE app (default http://127.0.0.1:8021) through the exact
interactions from the field report:

    T0  fill a controlled FAI characteristic with an out-of-tolerance value
        through the FAI Sage Fill field
    T1  "what is the impact on the assembly of the failed dimension in the
         fai table?"          -> prose only: no tab switch/highlight/motion,
                                 no scrap/catastrophic/tooling/lot claims
    T2  "what is the affected motion?"
                              -> prose only, names a motion group
    T2b "what motion will be affected?"
                              -> prose only, no action claim
    T3  "show the affected motion"
                              -> assembly tab + highlight + playback at 30 RPM
                                 with an honest status line
    T4  "bring the crankshaft"
                              -> adds crankshaft to the highlighted set,
                                 motion keeps running
    T5  "bring everything back"
                              -> clears display overrides and highlights

Operator-runnable diagnostic (needs a running server with a real
ANTHROPIC_API_KEY); not part of the offline suite.

Outputs:
    runtime_logs/fai_motion_contract_smoke.json
    runtime_logs/fai_motion_contract_smoke.png
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8021/")
PART_NUMBER = os.environ.get("SMOKE_PART_NUMBER", "100006")
THREE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"

BANNED_T1 = ["scrap", "catastrophic", "within minutes", "within seconds",
             "check the last", "tooling", "quarantine", "slam", "will not grip"]


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    findings: dict = {"url": APP_URL, "part": PART_NUMBER, "turns": [], "checks": {}}

    three_js = None
    try:
        if THREE_CACHE.exists() and THREE_CACHE.stat().st_size > 100_000:
            three_js = THREE_CACHE.read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(THREE_CDN_URL, timeout=15) as resp:
                three_js = resp.read().decode("utf-8")
            THREE_CACHE.write_text(three_js, encoding="utf-8")
    except Exception as exc:
        print(f"[smoke:warn] could not prepare local Three.js route: {exc}")

    def record(name: str, ok: bool, detail=None):
        findings["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail is not None and not ok else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        if three_js:
            page.route(
                THREE_CDN_URL,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=three_js,
                ),
            )
        page.on("pageerror", lambda err: print(f"[browser:error] {err}"))
        page.on("requestfailed", lambda req: print(f"[browser:requestfailed] {req.url} :: {req.failure}"))

        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window.__compareDbg && window._handleAgentSend", timeout=30_000)

        # Load the part through the real search UI.
        page.fill("#partSearch", PART_NUMBER)
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(600)
        page.locator(f".search-dropdown-item:has-text('{PART_NUMBER}')").first.click()
        page.wait_for_function(
            f"window.__compareDbg.state.partNumber === '{PART_NUMBER}'", timeout=30_000)
        record("part_loaded", True)

        # Motion package summary must be available (visit Assembly once if
        # the background load has not populated it yet), then Report tab.
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

        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        page.wait_for_function(
            "Array.isArray(window.__compareDbg.state.faiCharacteristics)"
            " && window.__compareDbg.state.faiCharacteristics.length > 0", timeout=20_000)
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        page.wait_for_timeout(800)

        def snap():
            return page.evaluate("""
                (() => {
                    const s = window.__compareDbg.state;
                    const overrides = s.assemblyPartDisplayOverrides || {};
                    return {
                        activeTab: s.activeTab,
                        motionPlaying: !!s.motionPlaying,
                        motionPkgMode: !!s.motionPkgMode,
                        motionRpm: s.motionRpm,
                        highlighted: Array.from(s.partExplorerAgentParts || []).sort(),
                        hidden: Object.keys(overrides).filter(pn => overrides[pn] && overrides[pn].hidden === true),
                    };
                })();
            """)

        def ask(question: str) -> str:
            sent = page.evaluate(
                "async (q) => { try { window._agentInput.value = q;"
                " await window._handleAgentSend(); return { sent: true }; }"
                " catch (err) { return { sent: false, error: String(err).slice(0, 300) }; } }",
                question)
            if not sent.get("sent"):
                raise RuntimeError(f"send failed: {sent.get('error')}")
            page.wait_for_timeout(1000)
            answer = page.evaluate(
                "() => { const m = document.querySelectorAll('#agentMessages .agent-msg-row.assistant');"
                " return m.length ? m[m.length - 1].innerText : ''; }")
            findings["turns"].append({"q": question, "a": answer[:900], "state": snap()})
            return answer

        # T0: force an out-of-tolerance measurement through the real FAI
        # Sage Fill field. Prefer the pin-bore row for this contract, but do
        # not depend on row-level tolerances because this table uses the
        # global tolerance control by default.
        row = page.evaluate("""
            (() => {
                const chars = window.__compareDbg.state.faiCharacteristics || [];
                const hasTol = (c) => Math.max(
                    Math.abs(Number(c.tolPlusMm) || 0),
                    Math.abs(Number(c.tolMinusMm) || 0)
                ) > 0;
                const hasNominal = (c) => Number.isFinite(Number(c.nominalMm));
                const c = chars.find((x) => Number(x.charNumber) === 5 && hasNominal(x))
                    || chars.find((x) => /pin\\s*(bore|hole)|wrist\\s*pin/i.test(String(x.description || x.dimensionText || '')) && hasNominal(x))
                    || chars.find((x) => hasTol(x) && hasNominal(x))
                    || chars[0];
                return { key: c.key, charNumber: c.charNumber,
                         nominal: c.nominalMm, tolPlus: c.tolPlusMm,
                         tolMinus: c.tolMinusMm };
            })();
        """)
        tol_band = max(abs(float(row["tolPlus"] or 0)), abs(float(row["tolMinus"] or 0)), 0.05)
        bad_value = round(float(row["nominal"] or 0) + tol_band + 1.95, 3)
        page.fill("#faiAgentInput", f"#{row['charNumber']}={bad_value}")
        page.click("#faiAgentFillBtn")
        page.wait_for_timeout(500)
        filled = page.evaluate(
            "(k) => window.__compareDbg.state.faiMeasurements[k] || null", row["key"])
        record("t0_fai_fill_applied", filled is not None, {"row": row, "value": bad_value, "filled": filled})

        baseline = snap()
        findings["baseline"] = baseline

        # T1: FAI impact question -> prose only.
        a1 = ask("what is the impact on the assembly of the failed dimension in the fai table?")
        s1 = snap()
        low1 = a1.lower()
        record("t1_answer_received", bool(a1.strip()), a1[:200])
        record("t1_no_tab_switch", s1["activeTab"] == "report", s1)
        record("t1_no_motion", s1["motionPlaying"] is False, s1)
        record("t1_no_new_highlights", s1["highlighted"] == baseline["highlighted"], s1)
        record("t1_no_mojibake", "Â" not in a1 and "â€" not in a1, a1[:200])
        banned_hits = [b for b in BANNED_T1 if b in low1]
        record("t1_no_ungrounded_claims", not banned_hits, {"hits": banned_hits, "answer": a1[:400]})
        record("t1_quantified", any(ch.isdigit() for ch in a1), a1[:200])

        # T2: affected-motion explanation -> prose only, names a group.
        a2 = ask("what is the affected motion?")
        s2 = snap()
        low2 = a2.lower()
        group_labels = page.evaluate("""
            (() => {
                const out = [];
                const info = window.__compareDbg.state.motionPkgInfo;
                const motions = info && info.summary && info.summary.available_motions || [];
                motions.forEach(m => (m.groups || []).forEach(g => {
                    if (g.label) out.push(String(g.label).toLowerCase());
                    if (g.id) out.push(String(g.id).toLowerCase().replace(/_/g, ' '));
                }));
                return out;
            })();
        """)
        record("t2_answer_received", bool(a2.strip()), a2[:200])
        record("t2_no_tab_switch", s2["activeTab"] == "report", s2)
        record("t2_no_motion", s2["motionPlaying"] is False, s2)
        record("t2_no_new_highlights", s2["highlighted"] == baseline["highlighted"], s2)
        norm2 = low2.replace("-", " ")
        norm_labels = [lbl.replace("-", " ") for lbl in group_labels]
        names_group = any(lbl in norm2 for lbl in norm_labels) or "motion group" in norm2 or "crank slider" in norm2
        record("t2_names_motion_group", names_group, {"labels": group_labels, "answer": a2[:400]})

        # T2b: equivalent affected-motion wording -> still prose only.
        a2b = ask("what motion will be affected?")
        s2b = snap()
        low2b = a2b.lower()
        record("t2b_answer_received", bool(a2b.strip()), a2b[:200])
        record("t2b_no_tab_switch", s2b["activeTab"] == "report", s2b)
        record("t2b_no_motion", s2b["motionPlaying"] is False, s2b)
        record("t2b_no_new_highlights", s2b["highlighted"] == baseline["highlighted"], s2b)
        claim_hits = [w for w in ["highlighted", "showing", "playing", "animating", "replaying", "selected", "isolated"] if w in low2b]
        record("t2b_no_false_action_claim", not claim_hits, {"hits": claim_hits, "answer": a2b[:400]})
        norm2b = low2b.replace("-", " ")
        names_group_2b = any(lbl in norm2b for lbl in norm_labels) or "motion group" in norm2b or "affected motion" in norm2b or "crank slider" in norm2b
        record("t2b_names_motion_group", names_group_2b, {"labels": group_labels, "answer": a2b[:400]})

        # T3: explicit request -> assembly + highlight + playback @30, honest.
        a3 = ask("show the affected motion")
        try:
            page.wait_for_function("window.__compareDbg.state.motionPlaying === true", timeout=20_000)
        except Exception:
            pass
        s3 = snap()
        record("t3_tab_assembly", s3["activeTab"] == "assembly", s3)
        record("t3_motion_playing", s3["motionPlaying"] is True, s3)
        record("t3_motion_pkg_mode", s3["motionPkgMode"] is True, s3)
        record("t3_rpm_30", abs(float(s3["motionRpm"] or 0) - 30) < 0.5, s3)
        record("t3_affected_group_highlighted", len(s3["highlighted"]) > 0, s3)
        low3 = a3.lower()
        honest3 = ("did not start" in low3) != bool(s3["motionPlaying"]) \
            if ("did not start" in low3 or "showing" in low3) else True
        record("t3_answer_honest", honest3, a3[:200])

        # T4: additive part request during motion. The crankshaft part number
        # comes from the live motion summary (the drive group carries exactly
        # one part) -- nothing is hardcoded.
        crank_pn = page.evaluate("""
            (() => {
                const s = window.__compareDbg.state;
                const motions = s.motionPkgInfo && s.motionPkgInfo.summary
                    && s.motionPkgInfo.summary.available_motions || [];
                for (const m of motions) for (const g of (m.groups || [])) {
                    if (/crank/i.test(String(g.label || g.id || '')) && (g.part_numbers || []).length === 1) {
                        return String(g.part_numbers[0]);
                    }
                }
                return null;
            })();
        """)
        a4 = ask("bring the crankshaft")
        s4 = snap()
        record("t4_crankshaft_added",
               bool(crank_pn) and crank_pn in s4["highlighted"],
               {"crank_pn": crank_pn, "state": s4, "answer": a4[:200]})
        record("t4_motion_still_running", s4["motionPlaying"] is True, s4)
        record("t4_prior_highlights_kept",
               all(pn in s4["highlighted"] for pn in s3["highlighted"]), s4)

        # T5: restore-all clears overrides and highlights.
        a5 = ask("bring everything back")
        s5 = snap()
        record("t5_highlights_cleared", len(s5["highlighted"]) == 0, s5)
        record("t5_no_hidden_parts", len(s5["hidden"]) == 0, s5)

        png = OUT_DIR / "fai_motion_contract_smoke.png"
        page.screenshot(path=str(png), full_page=False)
        findings["screenshot"] = str(png.relative_to(REPO_ROOT))
        browser.close()

    out = OUT_DIR / "fai_motion_contract_smoke.json"
    out.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"findings -> {out.relative_to(REPO_ROOT)}")
    failed = [k for k, v in findings["checks"].items() if not v["ok"]]
    print(f"{len(findings['checks']) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
