"""Live browser smoke for FAI snapshot freshness and deterministic row targeting."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8021/")
OUT = ROOT / "runtime_logs" / "fai_live_targeting_smoke.json"
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = ROOT / "runtime_logs" / "three.r128.min.js"


def run() -> int:
    result = {"url": URL, "checks": {}, "turns": []}

    def check(name, ok, detail=None):
        result["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if not ok else ""))

    def has_number(text, value):
        token = re.escape(str(value))
        return bool(re.search(rf"(?<![\d.]){token}(?:\.0+)?(?![\d.])", text or ""))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1660, "height": 1000})
        if THREE_CACHE.exists():
            page.route(
                THREE_URL,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=THREE_CACHE.read_text(encoding="utf-8"),
                ),
            )
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window.__compareDbg && window._handleAgentSend && window.__faiSnapshotDbg", timeout=30_000)
        page.evaluate("""
            (() => {
                window.__faiTargetingFinals = [];
                const originalFetch = window.fetch.bind(window);
                window.fetch = async (...args) => {
                    const response = await originalFetch(...args);
                    const url = String(args[0] && args[0].url || args[0] || '');
                    if (url.includes('/api/agent/chat/v2/stream')) {
                        response.clone().text().then(raw => {
                            raw.split(String.fromCharCode(10)).forEach(line => {
                                if (!line.startsWith('data:')) return;
                                try {
                                    const event = JSON.parse(line.slice(5).trim());
                                    if (event.event === 'response_completed' && event.final) {
                                        window.__faiTargetingFinals.push(event.final);
                                    }
                                } catch (_) {}
                            });
                        }).catch(() => {});
                    }
                    return response;
                };
            })();
        """)

        page.fill("#partSearch", "100006")
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(500)
        page.locator(".search-dropdown-item:has-text('100006')").first.click()
        page.wait_for_function("window.__compareDbg.state.partNumber === '100006'", timeout=30_000)
        page.click(".tab[data-tab='report']")
        page.wait_for_function(
            "window.__compareDbg.state.activeTab === 'report'"
            " && window.__compareDbg.state.faiCharacteristics.length > 0",
            timeout=30_000,
        )
        page.fill("#faiGlobalTol", "0.050")
        page.click("#faiApplyTolAll")
        page.wait_for_timeout(350)
        page.evaluate("""
            (() => {
                const state = window.__compareDbg.state;
                (state.faiCharacteristics || []).filter(row => !row.isReference).forEach(row => {
                    const selector = `tr[data-fai-key="${CSS.escape(row.key)}"] input[data-fai-field="measured"]`;
                    const input = document.querySelector(selector);
                    if (!input) return;
                    input.value = Number(row.nominalMm).toFixed(3);
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                });
            })();
        """)
        page.wait_for_function(
            "() => { const s=window.__compareDbg.state; return s.faiCharacteristics.filter(c=>!c.isReference).every(c=>String(s.faiMeasurements[c.key]||'').trim()); }",
            timeout=8_000,
        )

        targets = page.evaluate("""
            (() => {
                const rows = window.__compareDbg.state.faiCharacteristics || [];
                const find = re => rows.find(row => re.test(String(row.description || '')));
                const outside = find(/main outside diameter/i);
                const pin = find(/wrist-pin hole diameter|pin bore|pin-hole/i);
                const groove = find(/repeated ring groove width|ring groove width/i);
                return Object.fromEntries(Object.entries({outside,pin,groove}).map(([name,row]) => [name, row ? {
                    key:row.key, id:String(row.charNumber), description:row.description, nominal:row.nominalMm
                } : null]));
            })();
        """)
        if not all(targets.values()):
            raise RuntimeError(f"required FAI rows not found: {targets}")

        def edit(row, value):
            selector = f'tr[data-fai-key="{row["key"]}"] input[data-fai-field="measured"]'
            page.locator(selector).fill(str(value))
            page.wait_for_function(
                "args => String(window.__compareDbg.state.faiMeasurements[args.key]) === String(args.value)",
                arg={"key": row["key"], "value": str(value)},
                timeout=5_000,
            )

        def ask(question):
            if page.evaluate("window.__compareDbg.state.activeTab") != "assembly":
                page.click(".tab[data-tab='assembly']")
                page.wait_for_function("window.__compareDbg.state.activeTab === 'assembly'", timeout=15_000)
            page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
            prior_final = page.evaluate("window.__faiTargetingFinals.length")
            prior_rows = page.locator("#agentMessages .agent-msg-row.assistant").count()
            page.evaluate("async q => { window._agentInput.value=q; await window._handleAgentSend(); }", question)
            page.wait_for_function(
                "n => window.__faiTargetingFinals.length > n", arg=prior_final, timeout=120_000
            )
            page.wait_for_function(
                "n => { const rows=[...document.querySelectorAll('#agentMessages .agent-msg-row.assistant')];"
                " const last=rows[rows.length-1]; return rows.length>n && last && !last.classList.contains('agent-stream-pending'); }",
                arg=prior_rows,
                timeout=30_000,
            )
            final = page.evaluate("window.__faiTargetingFinals[window.__faiTargetingFinals.length-1]")
            answer = page.evaluate("""
                () => { const rows=document.querySelectorAll('#agentMessages .agent-msg-row.assistant');
                    return rows[rows.length-1].innerText.trim(); }
            """)
            final_response = str(final.get("response") or "").strip()
            terminal_visible = re.sub(r"[*_`]", "", final_response).strip()
            answer_body = re.sub(r"^Sage\s*", "", answer or "").strip()
            turn = {
                "question": question,
                "answer": answer,
                "final_response": final_response,
                "dom_matches_terminal_response": answer_body == terminal_visible,
                "fai_request": final.get("fai_request"),
            }
            result["turns"].append(turn)
            return turn

        edit(targets["outside"], 95)
        snapshot_before_first = page.evaluate("window.__faiSnapshotDbg.create()")
        first = ask("What is the impact of the failed dimension on the assembly?")
        first_low = first["answer"].lower()
        check("first_turn_targets_selected_outside_diameter", first["fai_request"]["target_characteristic_ids"] == [targets["outside"]["id"]], first)
        check("first_turn_dom_matches_terminal_cleaned_response", first["dom_matches_terminal_response"], first)
        check("first_turn_uses_fresh_95_not_stale_92", has_number(first["answer"], 95) and not has_number(first["answer"], 92), first["answer"])
        check("outside_diameter_answer_explains_cylinder_fit", "cylinder" in first_low and any(word in first_low for word in ("clearance", "interference", "fit", "translation", "insertion")), first["answer"])
        check("outside_answer_has_no_unrequested_disposition_or_generic_hedge", not any(term in first_low for term in ("scrap", "rework", "if this is a controlled fit")), first["answer"])

        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        edit(targets["pin"], 35)
        second = ask(f"How about measured dimension #{targets['pin']['id']}?")
        second_low = second["answer"].lower()
        check("explicit_pin_turn_targets_only_pin", second["fai_request"]["target_characteristic_ids"] == [targets["pin"]["id"]], second)
        check("pin_turn_dom_matches_terminal_cleaned_response", second["dom_matches_terminal_response"], second)
        check("pin_answer_excludes_outside_diameter_failure", not has_number(second["answer"], 95) and has_number(second["answer"], 35), second["answer"])
        check("pin_answer_explains_pin_support", "pin" in second_low and any(word in second_low for word in ("support", "clearance", "bore", "load")), second["answer"])
        check(
            "pin_answer_does_not_borrow_cylinder_interface",
            "piston-to-cylinder" not in second_low
            and "cylinder-bore" not in second_low
            and "cylinder bore" not in second_low,
            second["answer"],
        )

        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        edit(targets["groove"], 4.8)
        third = ask("How about the new failed dimension I just added?")
        third_low = third["answer"].lower()
        check("recent_turn_targets_newest_ring_groove", third["fai_request"]["target_characteristic_ids"] == [targets["groove"]["id"]], third)
        check("ring_turn_dom_matches_terminal_cleaned_response", third["dom_matches_terminal_response"], third)
        check("ring_answer_excludes_prior_failures", has_number(third["answer"], 4.8) and not has_number(third["answer"], 35) and not has_number(third["answer"], 95), third["answer"])
        check("ring_answer_explains_seating_or_side_clearance", "ring" in third_low and any(word in third_low for word in ("side clearance", "seating", "axial")), third["answer"])
        check("ring_answer_has_no_scrap_or_borrowed_interface", "scrap" not in third_low and "piston-to-cylinder" not in third_low and "piston pin" not in third_low, third["answer"])
        check(
            "ring_answer_has_no_unrequested_disposition_or_followup",
            not any(term in third_low for term in ("reject", "rework", "what ring", "would you like"))
            and "?" not in third["answer"]
            and not any(fragment in third_low for fragment in ("between.", "within.", "with.", "permits pin."))
            and "likely." not in third_low
            and third_low.count("hold the inspected") <= 1,
            third["answer"],
        )

        fourth = ask("What are the implications of the current failed FAI results?")
        expected_ids = {targets[name]["id"] for name in ("outside", "pin", "groove")}
        check("general_results_turn_targets_all_failures", set(fourth["fai_request"]["target_characteristic_ids"]) == expected_ids, fourth)
        check("general_turn_dom_matches_terminal_cleaned_response", fourth["dom_matches_terminal_response"], fourth)
        check("general_answer_covers_all_three_measurements", has_number(fourth["answer"], 95) and has_number(fourth["answer"], 35) and has_number(fourth["answer"], 4.8), fourth["answer"])
        check(
            "general_answer_is_single_article_and_composition_clean",
            fourth["answer"].lower().count("hold the inspected part") <= 1
            and "hold all inspected" not in fourth["answer"].lower()
            and "permits pin." not in fourth["answer"].lower()
            and "cylinder bore in the lower engine block" not in fourth["answer"].lower()
            and ".." not in fourth["answer"],
            fourth["answer"],
        )
        check("snapshot_revision_advanced", snapshot_before_first["table_revision"] > 0 and fourth["fai_request"]["table_revision"] >= snapshot_before_first["table_revision"], fourth["fai_request"])

        result["targets"] = targets
        result["initial_snapshot"] = snapshot_before_first
        page.screenshot(path=str(ROOT / "runtime_logs" / "fai_live_targeting_smoke.png"), full_page=True)
        browser.close()

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    failures = [name for name, row in result["checks"].items() if not row["ok"]]
    print(f"{len(result['checks']) - len(failures)} passed, {len(failures)} failed")
    print(f"artifact -> {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
