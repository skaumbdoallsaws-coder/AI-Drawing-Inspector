"""Live Playwright smoke for Phase 5 workflow continuity.

This test uses the real Sage route, selected-skill prompt, registered browser
executors, execution receipts, chat-session persistence, and asset invalidation.
It intentionally verifies semantic continuity without restoring viewport effects.
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
OTHER_PART_NUMBER = os.environ.get("SMOKE_OTHER_PART_NUMBER", "100004")
THREE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report = {"url": APP_URL, "part": PART_NUMBER, "checks": {}, "turns": []}

    def record(name: str, ok: bool, detail=None):
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        suffix = f" :: {detail}" if detail is not None and not ok else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")

    three_js = None
    try:
        if THREE_CACHE.exists() and THREE_CACHE.stat().st_size > 100_000:
            three_js = THREE_CACHE.read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(THREE_CDN_URL, timeout=15) as response:
                three_js = response.read().decode("utf-8")
            THREE_CACHE.write_text(three_js, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke:warn] Three.js route unavailable: {exc}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
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
        page.on("pageerror", lambda error: print(f"[browser:error] {error}"))
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function(
            "window.__compareDbg && window.__workflowDbg && window._handleAgentSend",
            timeout=30_000,
        )

        def load_part(part_number: str):
            page.fill("#partSearch", part_number)
            page.dispatch_event("#partSearch", "input")
            page.wait_for_timeout(600)
            page.locator(f".search-dropdown-item:has-text('{part_number}')").first.click()
            page.wait_for_function(
                f"window.__compareDbg.state.partNumber === '{part_number}'",
                timeout=30_000,
            )

        def ensure_motion_summary():
            try:
                page.wait_for_function(
                    "window.__compareDbg.state.motionPkgInfo"
                    " && window.__compareDbg.state.motionPkgInfo.summary",
                    timeout=10_000,
                )
            except Exception:
                page.click(".tab[data-tab='assembly']")
                page.wait_for_function(
                    "window.__compareDbg.state.motionPkgInfo"
                    " && window.__compareDbg.state.motionPkgInfo.summary",
                    timeout=45_000,
                )

        def viewport_snapshot():
            return page.evaluate("""
                (() => {
                    const s = window.__compareDbg.state;
                    const overrides = s.assemblyPartDisplayOverrides || {};
                    return {
                        active_tab: s.activeTab,
                        motion_playing: !!s.motionPlaying,
                        motion_package_mode: !!s.motionPkgMode,
                        rpm: Number(s.motionRpm) || null,
                        highlighted: Array.from(s.partExplorerAgentParts || []).map(String).sort(),
                        hidden: Object.keys(overrides).filter(
                            pn => overrides[pn] && overrides[pn].hidden === true
                        ).sort(),
                    };
                })();
            """)

        def workflow_snapshot():
            return page.evaluate("window.__workflowDbg.current()")

        def ask(message: str) -> str:
            sent = page.evaluate(
                "async (q) => { try { window._agentInput.value = q;"
                " await window._handleAgentSend(); return {ok:true}; }"
                " catch (error) { return {ok:false,error:String(error)}; } }",
                message,
            )
            if not sent.get("ok"):
                raise RuntimeError(sent.get("error") or "agent send failed")
            page.wait_for_timeout(700)
            answer = page.evaluate(
                "() => { const rows = document.querySelectorAll("
                "'#agentMessages .agent-msg-row.assistant');"
                " return rows.length ? rows[rows.length - 1].innerText : ''; }"
            )
            report["turns"].append({
                "message": message,
                "answer": answer[:800],
                "workflow": workflow_snapshot(),
                "viewport": viewport_snapshot(),
            })
            return answer

        load_part(PART_NUMBER)
        ensure_motion_summary()
        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        page.wait_for_function(
            "Array.isArray(window.__compareDbg.state.faiCharacteristics)"
            " && window.__compareDbg.state.faiCharacteristics.length > 0",
            timeout=20_000,
        )
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        page.wait_for_timeout(600)

        baseline = viewport_snapshot()
        first_answer = ask("What motion will be affected by characteristic 5?")
        first_state = workflow_snapshot()
        first_view = viewport_snapshot()
        session_id = first_state.get("chat_session_id")
        record("initial_answer_received", bool(first_answer.strip()), first_answer[:200])
        record(
            "workflow_started",
            bool(first_state.get("workflow_state"))
            and first_state["workflow_state"].get("workflow_id") == "supplier-fai-disposition",
            first_state,
        )
        record(
            "read_only_turn_kept_viewport",
            first_view["active_tab"] == "report"
            and first_view["motion_playing"] is False
            and first_view["highlighted"] == baseline["highlighted"],
            first_view,
        )

        page.click(".tab[data-tab='drawing']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'drawing'", timeout=15_000)
        show_answer = ask("Show it.")
        try:
            page.wait_for_function("window.__compareDbg.state.motionPlaying === true", timeout=20_000)
        except Exception:
            pass
        shown = viewport_snapshot()
        shown_state = workflow_snapshot()
        record("same_session_across_tab", shown_state.get("chat_session_id") == session_id, shown_state)
        record(
            "show_it_resolved_and_played",
            shown["active_tab"] == "assembly"
            and shown["motion_playing"] is True
            and shown["motion_package_mode"] is True
            and abs(float(shown["rpm"] or 0) - 30.0) < 0.5
            and len(shown["highlighted"]) > 0,
            {"answer": show_answer[:240], "viewport": shown},
        )
        record(
            "workflow_advanced_to_visualization",
            bool(shown_state.get("workflow_state"))
            and shown_state["workflow_state"].get("stage")
            in {"trace_assembly_impact", "visualize_affected_context"},
            shown_state,
        )

        lower_part = page.evaluate("""
            (() => {
                const rows = (window.__compareDbg.state.assemblyContext
                    && window.__compareDbg.state.assemblyContext.part_color_legend) || [];
                const hit = rows.find(row => /lower.*(block|housing)|engine.*block/i.test(
                    String(row.description || '')));
                return hit ? String(hit.part_number) : null;
            })();
        """)
        if not lower_part:
            lower_part = "100002"
        ask("Hide the lower engine block.")
        hidden = viewport_snapshot()
        hidden_state = workflow_snapshot()
        record("resolved_part_hidden", lower_part in hidden["hidden"], hidden)
        record("hide_preserved_motion", hidden["motion_playing"] is True, hidden)
        prior_receipt_tools = {
            receipt.get("tool_id")
            for receipt in (
                (hidden_state.get("workflow_state") or {}).get("last_execution_receipts") or []
            )
            if receipt.get("status") == "succeeded"
        }
        record(
            "prior_visualization_receipts_reconciled",
            {"set_part_highlight", "play_motion"}.issubset(prior_receipt_tools)
            and (hidden_state.get("workflow_state") or {}).get("stage")
            == "visualize_affected_context",
            {"receipt_tools": sorted(prior_receipt_tools), "state": hidden_state},
        )

        ask("Bring that back.")
        restored = viewport_snapshot()
        record("referent_part_restored", lower_part not in restored["hidden"], restored)
        record("restore_preserved_motion", restored["motion_playing"] is True, restored)

        prior_highlights = set(restored["highlighted"])
        crank_part = page.evaluate("""
            (() => {
                const info = window.__compareDbg.state.motionPkgInfo;
                const motions = info && info.summary && info.summary.available_motions || [];
                for (const motion of motions) for (const group of (motion.groups || [])) {
                    if (/crank/i.test(String(group.label || group.id || ''))
                        && (group.part_numbers || []).length === 1) {
                        return String(group.part_numbers[0]);
                    }
                }
                return null;
            })();
        """)
        ask("Also add the crankshaft.")
        additive = viewport_snapshot()
        record("named_part_added", bool(crank_part) and crank_part in additive["highlighted"], {
            "crank_part": crank_part, "viewport": additive,
        })
        record(
            "additive_highlight_preserved_prior_set",
            prior_highlights.issubset(set(additive["highlighted"])),
            additive,
        )
        record("additive_turn_preserved_motion", additive["motion_playing"] is True, additive)

        page.wait_for_timeout(1200)
        before_reload = workflow_snapshot()
        page.reload(wait_until="networkidle", timeout=60_000)
        page.wait_for_function(
            "window.__compareDbg && window.__workflowDbg && window._handleAgentSend",
            timeout=30_000,
        )
        after_reload = workflow_snapshot()
        reset_view = viewport_snapshot()
        record(
            "refresh_restored_semantic_state",
            after_reload.get("chat_session_id") == before_reload.get("chat_session_id")
            and after_reload.get("workflow_state") == before_reload.get("workflow_state"),
            {"before": before_reload, "after": after_reload},
        )
        record(
            "refresh_did_not_replay_viewport_effects",
            reset_view["motion_playing"] is False
            and not reset_view["highlighted"]
            and not reset_view["hidden"],
            reset_view,
        )

        load_part(PART_NUMBER)
        ensure_motion_summary()
        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        resume_answer = ask("What motion were we reviewing?")
        resumed = workflow_snapshot()
        resumed_view = viewport_snapshot()
        record("post_refresh_followup_answered", bool(resume_answer.strip()), resume_answer[:200])
        record(
            "post_refresh_server_state_resumed",
            bool(resumed.get("workflow_state"))
            and resumed["workflow_state"].get("workflow_id") == "supplier-fai-disposition"
            and resumed.get("workflow_state_event", {}).get("event") in {"resumed", "advanced", "continued"},
            resumed,
        )
        record(
            "post_refresh_question_remained_read_only",
            resumed_view["active_tab"] == "report"
            and resumed_view["motion_playing"] is False
            and not resumed_view["highlighted"],
            resumed_view,
        )

        load_part(OTHER_PART_NUMBER)
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        ask("What is the active part number?")
        changed = workflow_snapshot()
        changed_view = viewport_snapshot()
        record("asset_change_invalidated_workflow", changed.get("workflow_state") is None, changed)
        record(
            "asset_invalidation_reported",
            changed.get("workflow_state_event", {}).get("event") == "scope_changed",
            changed,
        )
        record(
            "asset_invalidation_did_not_change_viewport",
            changed_view["motion_playing"] is False and not changed_view["highlighted"],
            changed_view,
        )

        screenshot = OUT_DIR / "phase5_workflow_continuity_smoke.png"
        page.screenshot(path=str(screenshot), full_page=False)
        report["screenshot"] = str(screenshot.relative_to(REPO_ROOT))
        browser.close()

    output = OUT_DIR / "phase5_workflow_continuity_smoke.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    failed = [name for name, result in report["checks"].items() if not result["ok"]]
    print(f"findings -> {output.relative_to(REPO_ROOT)}")
    print(f"{len(report['checks']) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
