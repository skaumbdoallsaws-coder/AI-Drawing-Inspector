"""Live acceptance smoke for modular Sage FAI-to-assembly reasoning."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runtime_logs" / "prompt_compiler_fai_assembly_smoke.json"
URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8022/")
PART = os.environ.get("SMOKE_PART_NUMBER", "100006")
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = ROOT / "runtime_logs" / "three.r128.min.js"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    result = {"url": URL, "part": PART, "checks": {}}

    def check(name, ok, detail=None):
        result["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if not ok else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
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
        page.wait_for_function("window.__compareDbg && window._handleAgentSend", timeout=30_000)

        # Capture the authoritative response_completed payload without
        # changing the app's normal stream consumer.
        page.evaluate("""
            (() => {
                if (window.__promptCompilerFetchInstalled) return;
                window.__promptCompilerFetchInstalled = true;
                window.__promptCompilerFinals = [];
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
                                        window.__promptCompilerFinals.push(event.final);
                                    }
                                } catch (_) {}
                            });
                        }).catch(() => {});
                    }
                    return response;
                };
            })();
        """)

        page.fill("#partSearch", PART)
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(600)
        page.locator(f".search-dropdown-item:has-text('{PART}')").first.click()
        page.wait_for_function(f"window.__compareDbg.state.partNumber === '{PART}'", timeout=30_000)

        page.click(".tab[data-tab='report']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'report'", timeout=15_000)
        page.wait_for_function(
            "Array.isArray(window.__compareDbg.state.faiCharacteristics)"
            " && window.__compareDbg.state.faiCharacteristics.length > 0",
            timeout=30_000,
        )
        page.fill("#faiGlobalTol", "0.050")
        page.click("#faiApplyTolAll")
        page.wait_for_timeout(400)

        target = page.evaluate("""
            (() => {
                const chars = window.__compareDbg.state.faiCharacteristics || [];
                const c = chars.find(x => /main outside diameter/i.test(String(x.description || '')))
                    || chars.find(x => Number(x.nominalMm) === 90);
                return c ? {charNumber:c.charNumber,key:c.key,nominal:c.nominalMm,description:c.description} : null;
            })();
        """)
        if not target:
            raise RuntimeError("outside-diameter characteristic not found")
        instruction = f"All nominal except #{target['charNumber']}=88"
        page.fill("#faiAgentInput", instruction)
        page.click("#faiAgentFillBtn")
        try:
            page.wait_for_function(
                "key => window.__compareDbg.state.faiMeasurements[key] != null",
                arg=target["key"],
                timeout=2_000,
            )
        except Exception:
            # Applying the global tolerance re-renders the report. If that
            # replacement raced the first click, repeat the same visible UI
            # action against the newly mounted controls.
            page.fill("#faiAgentInput", instruction)
            page.click("#faiAgentFillBtn")
            page.wait_for_function(
                "key => window.__compareDbg.state.faiMeasurements[key] != null",
                arg=target["key"],
                timeout=5_000,
            )

        statuses = page.evaluate("""
            (() => {
                const s = window.__compareDbg.state;
                return (s.faiCharacteristics || []).filter(c => !c.isReference).map(c => {
                    const ov = s.faiTolOverrides[c.key];
                    const plus = ov ? Number(ov.plus) : Number(c.tolPlusMm);
                    const minus = ov ? Number(ov.minus) : Number(c.tolMinusMm);
                    return {charNumber:c.charNumber, measured:s.faiMeasurements[c.key],
                        status:evaluateCharacteristic(c.nominalMm,plus,minus,s.faiMeasurements[c.key])};
                });
            })();
        """)
        failures = [row for row in statuses if row["status"] == "FAIL"]
        check("one_failed_characteristic", len(failures) == 1, failures)
        check("outside_diameter_is_failure", failures and failures[0]["charNumber"] == target["charNumber"], failures)
        check("all_other_characteristics_pass", all(
            row["status"] == "PASS" for row in statuses if row["charNumber"] != target["charNumber"]
        ), statuses)

        page.click(".tab[data-tab='assembly']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'assembly'", timeout=15_000)
        page.evaluate("window._selectAgent && window._selectAgent('deviation-analyst')")
        page.wait_for_timeout(500)

        question = "what is the implication of the failed dimension on the assembly?"
        prior = page.locator("#agentMessages .agent-msg-row.assistant").count()
        page.evaluate("async q => { window._agentInput.value=q; await window._handleAgentSend(); }", question)
        page.wait_for_function(
            "prior => { const rows=[...document.querySelectorAll('#agentMessages .agent-msg-row.assistant')];"
            " const last=rows[rows.length-1]; return rows.length>prior && last && !last.classList.contains('agent-stream-pending'); }",
            arg=prior,
            timeout=120_000,
        )
        page.wait_for_function("window.__promptCompilerFinals.length > 0", timeout=10_000)
        answer = page.evaluate("""
            () => { const rows=document.querySelectorAll('#agentMessages .agent-msg-row.assistant');
                return rows[rows.length-1].innerText.trim(); }
        """)
        final = page.evaluate("window.__promptCompilerFinals[window.__promptCompilerFinals.length-1]")
        runtime = final.get("skill_runtime") or {}
        accounting = runtime.get("prompt_accounting") or {}
        context_accounting = runtime.get("context_accounting") or {}
        viewport = page.evaluate("""
            (() => { const s=window.__compareDbg.state; return {tab:s.activeTab,
                motion:!!s.motionPlaying, highlighted:Array.from(s.partExplorerAgentParts||[])}; })();
        """)

        low = answer.lower()
        check("compiled_skill_runtime_used", bool(runtime) and runtime.get("fallback") in (False, True), runtime)
        check("prompt_under_10k_chars", 0 < accounting.get("total_chars", 0) < 10_000, accounting)
        check("context_was_pruned", context_accounting.get("reduction_ratio", 0) > 0.2, context_accounting)
        module_ids = {item.get("id") for item in runtime.get("prompt_modules") or []}
        check("versioned_modules_recorded", {
            "sage.identity", "sage.engineering-honesty", "sage.response-style",
            "sage.mode.assembly", "sage.policy.fai-assembly-impact",
        } <= module_ids, runtime.get("prompt_modules"))
        selection = runtime.get("selection") or []
        primary = [item.get("id") for item in selection if item.get("role") == "primary"]
        check("assembly_impact_skill_is_primary", primary == ["trace-assembly-impact"], selection)
        check("skill_contracts_recorded", len(runtime.get("contracts") or []) == len(selection), runtime.get("contracts"))
        check("native_tool_protocol_isolated", (runtime.get("tool_protocol") or {}).get("type") == "anthropic_native_tools_v1", runtime.get("tool_protocol"))
        check("context_validation_is_clean", context_accounting.get("context_status") == "ok" and context_accounting.get("provenance_count", 0) >= 4, context_accounting)
        check("answer_quantifies_result", "88" in answer and "90" in answer and "1.95" in answer, answer)
        check("answer_avoids_unsupported_disposition", not any(term in low for term in ["scrap", "rework to", "will fail", "catastrophic"]), answer)
        check("explanation_is_read_only", viewport == {"tab":"assembly","motion":False,"highlighted":[]}, viewport)
        check("no_tool_call_for_explanation", final.get("tool_call_count") == 0, final.get("tool_calls"))
        max_sentences = ((runtime.get("resolved_policy") or {}).get("output") or {}).get("maximum_sentences", 3)
        answer_body = re.sub(r"^Sage\s*", "", answer).strip()
        sentence_count = len(re.findall(r"[.!?](?:\s|$)", answer_body))
        check("resolved_output_contract_honored", sentence_count <= max_sentences, {"sentences": sentence_count, "maximum": max_sentences, "answer": answer})

        result.update({
            "target": target,
            "instruction": instruction,
            "question": question,
            "answer": answer,
            "skill_runtime": runtime,
            "viewport": viewport,
        })
        page.screenshot(path=str(ROOT / "runtime_logs" / "prompt_compiler_fai_assembly_smoke.png"), full_page=True)
        browser.close()

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    failures = [name for name, row in result["checks"].items() if not row["ok"]]
    print(f"{len(result['checks']) - len(failures)} passed, {len(failures)} failed")
    print(f"artifact -> {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
