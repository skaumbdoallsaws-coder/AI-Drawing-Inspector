"""Capture the MMLE synthetic Process Map ghost preview through live APIs.

This verifier has no repair or commit path. It loads the production workspace,
submits the deterministic evidence-bound plan to the production proposal API,
and leaves the proposal pending for explicit user approval.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.assembly_knowledge import resolve_process_map_evidence_package
from ai_inspector.process_map import build_semantic_process_plan_from_evidence


TRAINING_ROOT = ROOT / "generated" / "training"
PRODUCT_ID = "mmle-50d-497533f6"
APP_URL = os.environ.get(
    "APP_URL",
    "http://127.0.0.1:8125/?assemblyProfile=MMLE-50D",
)
OUTPUT_ROOT = ROOT / ".runtime" / "mmle_process_map_proof"


def main() -> int:
    resolved = resolve_process_map_evidence_package(
        TRAINING_ROOT,
        PRODUCT_ID,
        require_planning_ready=True,
        require_current_sources=True,
    )
    if resolved is None:
        raise RuntimeError("MMLE assembly knowledge package is unavailable")
    context = resolved["context"]
    scope_id = str(context["scope"]["rootOccurrenceId"])
    semantic_plan = build_semantic_process_plan_from_evidence(
        context,
        scope_occurrence_id=scope_id,
    )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    screenshot_path = OUTPUT_ROOT / "mmle_high_level_ghost_preview.png"
    report_path = OUTPUT_ROOT / "full_report.json"
    report: dict[str, object] = {
        "appUrl": APP_URL,
        "productId": PRODUCT_ID,
        "packageId": resolved["binding"]["packageId"],
        "packageRevision": resolved["binding"]["packageRevision"],
        "sourceRevision": resolved["binding"]["sourceRevision"],
        "requiredOccurrenceCount": len(semantic_plan["requiredOccurrences"]),
        "operationCount": len(semantic_plan["operations"]),
        "presentationMode": semantic_plan["scope"]["presentationMode"],
        "pageErrors": [],
        "consoleErrors": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1800, "height": 1100})
        page.on("pageerror", lambda error: report["pageErrors"].append(str(error)))
        page.on(
            "console",
            lambda message: report["consoleErrors"].append(message.text)
            if message.type == "error"
            and "Failed to load resource" not in message.text
            else None,
        )
        page.goto(APP_URL, wait_until="load", timeout=120_000)
        page.wait_for_function(
            "window.__inspectorProMainScriptReady === true",
            timeout=120_000,
        )
        page.locator(".tab[data-tab='training']").click()
        page.locator("#trainingTypeRibbonSelect").select_option("assembly")
        page.wait_for_function(
            """() => window.__processMapFlow
                && window.__processMapFlow.editor
                && window.__processMapFlow.editor.processMap""",
            timeout=120_000,
        )

        proposal = page.evaluate(
            """async semanticPlan => {
                const editor = window.__processMapFlow.editor;
                const productId = String(editor.processMap.productId);
                const mapId = String(editor.processMap.mapId || 'default');
                const response = await fetch(
                    '/api/builder/process-maps/' + encodeURIComponent(productId)
                        + '/' + encodeURIComponent(mapId) + '/semantic-proposals',
                    {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            baseRevision: editor.revision,
                            scopeOccurrenceId: semanticPlan.scope.assemblyOccurrenceId,
                            semanticPlan,
                        }),
                    }
                );
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(JSON.stringify(payload));
                }
                const shown = editor.showManagedProposal(payload);
                return {
                    shown,
                    proposalId: payload.proposalId,
                    baseRevision: payload.baseRevision,
                    diffHash: payload.diffHash,
                    semanticBindingHash: payload.semanticBindingHash,
                    summary: payload.summary,
                    warningCount: (payload.warnings || []).length,
                    unresolvedCount: (payload.unresolvedItems || []).length,
                    visualValidation: payload.visualValidation || null,
                    previewNodeCount: (payload.preview.nodes || []).length,
                    previewEdgeCount: (payload.preview.edges || []).length,
                    savedNodeCount: editor.processMap.canvasNodes.length,
                    savedEdgeCount: editor.processMap.canvasEdges.length,
                    labels: (payload.preview.nodes || [])
                        .filter(node => node.nodeKind === 'process_step')
                        .map(node => node.name || node.nameSnapshot
                            || node.labelOverride || ''),
                };
            }""",
            semantic_plan,
        )
        if not proposal["shown"]:
            raise RuntimeError("The live editor rejected the ghost preview")
        page.wait_for_timeout(700)
        page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                if (editor && editor.managedProposalReveal
                    && editor.managedProposalReveal.active) {
                    editor.showAllManagedProposal();
                }
            }"""
        )
        page.wait_for_timeout(900)
        page.screenshot(path=str(screenshot_path), full_page=True)
        proposal["savedNodeCountAfterRender"] = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        )
        proposal["proposalPendingAfterRender"] = page.evaluate(
            "!!window.__processMapFlow.editor.managedProposalPlan"
        )
        report["proposal"] = proposal
        report["screenshot"] = str(screenshot_path.relative_to(ROOT))
        browser.close()

    if report["pageErrors"]:
        raise RuntimeError(f"Browser page errors: {report['pageErrors']}")
    if proposal["savedNodeCountAfterRender"] != 0:
        raise RuntimeError("Verifier unexpectedly changed the saved Process Map")
    if proposal["previewNodeCount"] != 19 or proposal["previewEdgeCount"] != 18:
        raise RuntimeError("Unexpected high-level preview topology")

    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
