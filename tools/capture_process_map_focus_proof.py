"""Capture proof that a Sage request focuses a real Process Map branch."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
APP_URL = os.environ.get(
    "PROCESS_MAP_FOCUS_APP_URL",
    "http://127.0.0.1:8029/?assemblyProfile=tricycle",
)
PROMPT = (
    "Where is the Front Wheel & Brake subassembly on my process map? "
    "Highlight the upstream cards and routes."
)
OUT_DIR = ROOT / "runtime_logs"
SCREENSHOT_PATH = OUT_DIR / "process_map_focus_tricycle_proof.png"
EVIDENCE_PATH = OUT_DIR / "process_map_focus_tricycle_proof.json"


def _open_process_map(page) -> None:
    page.wait_for_timeout(1_500)
    page.locator("#profileCount").inner_text(timeout=120_000)
    page.locator(".tab[data-tab='training']").click()
    page.wait_for_selector(".tab.active[data-tab='training']", timeout=10_000)
    page.wait_for_selector("#trainingTypeRibbonSelect", timeout=30_000)
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
    page.wait_for_function(
        """() => window._getCurrentAgentKey
            && window._getCurrentAgentKey() === 'deviation-analyst'""",
        timeout=10_000,
    )


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1900, "height": 1000},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_map(page)
        page.evaluate("prompt => window._agentContextSendPrompt(prompt)", PROMPT)
        page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow
                    && window.__processMapFlow.editor;
                return !!(editor && editor.agentFocus)
                    && editor.agentFocus.nodeIds.length > 0
                    && editor.agentFocus.edgeIds.length > 0;
            }""",
            timeout=30_000,
        )
        page.wait_for_function(
            """() => Array.from(document.querySelectorAll(
                '.agent-msg.assistant'
            )).some(message => message.textContent.includes(
                'Highlighted Assemble fork and front wheel'
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
                const upstream = Array.from(document.querySelectorAll(
                    '.pm-node.agent-focus-upstream, '
                    + '.pm-junction.agent-focus-upstream'
                ));
                const routes = Array.from(document.querySelectorAll(
                    '.pm-edge.agent-focus-route'
                ));
                const muted = Array.from(document.querySelectorAll(
                    '.pm-node.agent-focus-muted'
                ));
                const card = target && target.querySelector('.pm-node-card');
                const route = routes[0];
                const messages = Array.from(document.querySelectorAll(
                    '.agent-msg.assistant'
                ));
                const targetNode = editor.processMap.canvasNodes.find(
                    node => focus.targetNodeIds.includes(node.nodeId)
                );
                return {
                    prompt,
                    mapId: editor.processMap.mapId,
                    mapName: editor.processMap.displayName,
                    focus: editor.getAgentFocus(),
                    targetName: targetNode && (
                        targetNode.labelOverride
                        || targetNode.name
                        || targetNode.nameSnapshot
                    ),
                    targetCount: target ? 1 : 0,
                    upstreamCount: upstream.length,
                    routeCount: routes.length,
                    mutedCount: muted.length,
                    targetOutline: card
                        ? getComputedStyle(card).outlineColor : null,
                    targetShadow: card
                        ? getComputedStyle(card).boxShadow : null,
                    routeStroke: route
                        ? getComputedStyle(route).stroke : null,
                    routeWidth: route
                        ? getComputedStyle(route).strokeWidth : null,
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
        evidence["consoleErrors"] = console_errors
        page.screenshot(path=str(SCREENSHOT_PATH), full_page=False)
        context.close()
        browser.close()

    evidence["passed"] = bool(
        evidence.get("targetName") == "Assemble fork and front wheel"
        and evidence.get("targetCount") == 1
        and evidence.get("upstreamCount", 0) >= 4
        and evidence.get("routeCount", 0) >= 4
        and "Highlighted Assemble fork and front wheel"
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
