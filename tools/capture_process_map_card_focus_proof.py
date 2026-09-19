"""Capture proof that Sage can focus one CAD-identified Process Map card."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
APP_URL = os.environ.get(
    "PROCESS_MAP_FOCUS_APP_URL",
    "http://127.0.0.1:8030/?assemblyProfile=tricycle",
)
PROMPT = "Highlight only the Fork2 part card on my process map."
OUT_DIR = ROOT / "runtime_logs"
SCREENSHOT_PATH = OUT_DIR / "process_map_fork2_card_focus_proof.png"
EVIDENCE_PATH = OUT_DIR / "process_map_fork2_card_focus_proof.json"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1900, "height": 1000},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(1_500)
        page.locator("#profileCount").inner_text(timeout=120_000)
        page.locator(".tab[data-tab='training']").click()
        page.wait_for_selector(".tab.active[data-tab='training']", timeout=10_000)
        page.locator("#trainingTypeRibbonSelect").select_option("assembly")
        page.wait_for_selector("[data-process-flow-editor='true']", timeout=30_000)
        page.wait_for_function(
            """() => {
                const flow = window.__processMapFlow;
                return !!(flow && flow.editor && !flow.editor.destroyed)
                    && flow.editor.processMap.canvasNodes.length > 0;
            }""",
            timeout=30_000,
        )
        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.evaluate("prompt => window._agentContextSendPrompt(prompt)", PROMPT)
        page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow
                    && window.__processMapFlow.editor;
                return !!(editor && editor.agentFocus)
                    && editor.agentFocus.targetNodeIds.length === 1
                    && editor.agentFocus.nodeIds.length === 1
                    && editor.agentFocus.edgeIds.length === 0;
            }""",
            timeout=30_000,
        )
        page.wait_for_function(
            """() => Array.from(document.querySelectorAll(
                '.agent-msg.assistant'
            )).some(message => message.textContent.includes(
                'Highlighted SWPR-Tricycle_Fork2-2'
            ))""",
            timeout=30_000,
        )
        page.wait_for_timeout(750)
        evidence = page.evaluate(
            """prompt => {
                const editor = window.__processMapFlow.editor;
                const focus = editor.agentFocus;
                const target = document.querySelector(
                    '.pm-node.agent-focus-target'
                );
                const card = target && target.querySelector('.pm-node-card');
                const node = editor.processMap.canvasNodes.find(
                    item => focus.targetNodeIds.includes(item.nodeId)
                );
                const occurrence = editor.occurrenceById.get(
                    node && node.sourceOccurrenceId
                );
                const messages = Array.from(document.querySelectorAll(
                    '.agent-msg.assistant'
                ));
                return {
                    prompt,
                    focus: editor.getAgentFocus(),
                    targetName: occurrence && occurrence.name,
                    targetCount: document.querySelectorAll(
                        '.pm-node.agent-focus-target'
                    ).length,
                    upstreamCount: document.querySelectorAll(
                        '.pm-node.agent-focus-upstream'
                    ).length,
                    routeCount: document.querySelectorAll(
                        '.pm-edge.agent-focus-route'
                    ).length,
                    mutedCount: document.querySelectorAll(
                        '.pm-node.agent-focus-muted'
                    ).length,
                    targetOutline: card
                        ? getComputedStyle(card).outlineColor : null,
                    banner: document.querySelector(
                        '.pm-agent-focus-copy'
                    ).textContent.trim(),
                    assistantText: messages.length
                        ? messages[messages.length - 1].textContent.trim()
                        : '',
                };
            }""",
            PROMPT,
        )
        evidence["pageErrors"] = page_errors
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
        context.close()
        browser.close()

    evidence["passed"] = bool(
        evidence.get("targetName") == "SWPR-Tricycle_Fork2-2"
        and evidence.get("targetCount") == 1
        and evidence.get("upstreamCount") == 0
        and evidence.get("routeCount") == 0
        and "1 card | 0 routes" in evidence.get("banner", "")
        and "Highlighted SWPR-Tricycle_Fork2-2"
        in evidence.get("assistantText", "")
        and not evidence.get("pageErrors")
    )
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print(f"screenshot={SCREENSHOT_PATH}")
    print(f"evidence={EVIDENCE_PATH}")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
