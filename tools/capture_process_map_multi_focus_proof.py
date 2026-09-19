"""Capture visual proof that Sage can focus several Process Map scopes at once."""

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
PROMPT = (
    "Where are the Front Wheel and Rear Wheel assemblies on my process map? "
    "Highlight both upstream card groups and routes."
)
OUT_DIR = ROOT / "runtime_logs"
SCREENSHOT_PATH = OUT_DIR / "process_map_multi_focus_tricycle_proof.png"
EVIDENCE_PATH = OUT_DIR / "process_map_multi_focus_tricycle_proof.json"


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
                    && editor.agentFocus.targets.length === 2
                    && editor.agentFocus.targetNodeIds.length === 2
                    && editor.agentFocus.edgeIds.length > 0;
            }""",
            timeout=30_000,
        )
        page.wait_for_function(
            """() => Array.from(document.querySelectorAll(
                '.agent-msg.assistant'
            )).some(message => message.textContent.includes(
                'Highlighted 2 Process Map scopes'
            ))""",
            timeout=30_000,
        )
        page.wait_for_timeout(750)
        evidence = page.evaluate(
            """prompt => {
                const editor = window.__processMapFlow.editor;
                const focus = editor.agentFocus;
                const targets = Array.from(document.querySelectorAll(
                    '.pm-node.agent-focus-target, '
                    + '.pm-junction.agent-focus-target'
                ));
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
                const targetNames = editor.processMap.canvasNodes
                    .filter(node => focus.targetNodeIds.includes(node.nodeId))
                    .map(node => (
                        node.labelOverride || node.name || node.nameSnapshot
                    ))
                    .sort();
                const messages = Array.from(document.querySelectorAll(
                    '.agent-msg.assistant'
                ));
                return {
                    prompt,
                    mapId: editor.processMap.mapId,
                    mapName: editor.processMap.displayName,
                    focus: editor.getAgentFocus(),
                    targetNames,
                    targetCount: targets.length,
                    upstreamCount: upstream.length,
                    routeCount: routes.length,
                    mutedCount: muted.length,
                    targetOutlines: targets.map(target => {
                        const card = target.querySelector('.pm-node-card');
                        return card ? getComputedStyle(card).outlineColor : null;
                    }),
                    routeStrokes: routes.slice(0, 3).map(
                        route => getComputedStyle(route).stroke
                    ),
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

    expected_names = {
        "Assemble fork and front wheel",
        "Assemble rear axle with small wheels",
    }
    evidence["passed"] = bool(
        set(evidence.get("targetNames") or []) == expected_names
        and evidence.get("targetCount") == 2
        and evidence.get("upstreamCount", 0) >= 8
        and evidence.get("routeCount", 0) >= 8
        and evidence.get("banner", "").startswith("2 scopes |")
        and "Highlighted 2 Process Map scopes"
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
