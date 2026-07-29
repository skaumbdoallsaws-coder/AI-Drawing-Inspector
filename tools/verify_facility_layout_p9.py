"""Capture source-bound P9 Sage Facility Layout preview evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "tests" / "fixtures" / "facility_layout" / "semantic"
DEFAULT_RESULT = EVIDENCE / "p9-product-result.json"
DEFAULT_PLAN = EVIDENCE / "p9-product-plan.png"
DEFAULT_THREE = EVIDENCE / "p9-product-three.png"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        extrema = image.getextrema()
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "width": image.width,
            "height": image.height,
            "nonblank": any(low != high for low, high in extrema),
        }


def _open_facility(page: Any) -> None:
    page.wait_for_function(
        """() => (
            window.__inspectorProMainScriptReady === true
            && typeof switchTab === 'function'
            && typeof _trainApplyTrainingTypeDefaults === 'function'
        )""",
        timeout=120_000,
    )
    page.evaluate(
        """() => {
            const previous = trainingState.type;
            trainingState.type = 'facility_layout';
            trainingState.viewportMode = 'facility_layout';
            _trainApplyTrainingTypeDefaults(previous);
            switchTab('training');
        }"""
    )
    page.wait_for_selector(
        "#trainFacilityLayoutAuthoring.ip-flw-root",
        state="visible",
        timeout=120_000,
    )
    page.wait_for_function(
        """() => !!(
            _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=120_000,
    )


def verify(app_url: str, output: Path) -> dict[str, Any]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )
        page.on(
            "response",
            lambda response: (
                failed_responses.append(
                    {
                        "method": response.request.method,
                        "status": response.status,
                        "url": response.url,
                    }
                )
                if response.status >= 400
                and not response.url.endswith("/static/manifest.json")
                else None
            ),
        )
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)

        evidence = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const state = app.session.getState();
                const layout = state.layout;
                const asset = app.workspace.assetCatalog.find(item =>
                    item.assetId === 'asset-workbench'
                ) || app.workspace.assetCatalog[0];
                const attachment = window.__facilityLayoutAgentV1
                    .getAttachment('deviation-analyst');
                const before = await app.transport.reloadLayout();
                const plan = {
                    schemaVersion: 1,
                    planId: 'plan-p9-product-workbench',
                    scope: {
                        siteId: attachment.siteId,
                        layoutId: attachment.layoutId,
                        label: 'P9 product verification workcell',
                    },
                    objective: 'place_asset_set',
                    sourceRevisions: {
                        layout: attachment.revision,
                        shell: layout.sourceShellRef.shellRevision,
                        policy: layout.policySetRef.policySetRevision,
                    },
                    requiredCapabilities: [],
                    selectedAssets: [{
                        itemId: 'verification-workbench',
                        assetId: asset.assetId,
                        assetDefinitionRevision:
                            asset.assetDefinitionRevision,
                        quantity: 1,
                        resourceRole: 'workstation',
                        stage: 1,
                        knowledgeStatus: 'inferred',
                        evidenceIds: [],
                        assumptionIds: [
                            'assumption-review-workbench-placement'
                        ],
                    }],
                    requiredZones: [],
                    placementRelationships: [],
                    processBindings: [],
                    flows: [],
                    evidence: [],
                    assumptions: [{
                        assumptionId:
                            'assumption-review-workbench-placement',
                        text: 'Review the proposed workbench placement.',
                        subjectRefs: ['verification-workbench'],
                    }],
                    unresolvedItems: [],
                    alternatives: [
                        {
                            alternativeId: 'balanced',
                            strategy: 'balanced_grid',
                            label: 'Balanced',
                        },
                        {
                            alternativeId: 'compact',
                            strategy: 'compact_rows',
                            label: 'Compact',
                        },
                    ],
                    layoutHints: {
                        density: 'balanced',
                        preserveManual: true,
                        preserveLocked: true,
                        primaryFlow: 'none',
                    },
                };
                const result = await window.__facilityLayoutAgentV1
                    .buildPreview(
                    { semantic_plan: plan },
                    'deviation-analyst'
                );
                await app.workspace.controller.ready();
                const after = app.session.getState();
                const serverAfter = await app.transport.reloadLayout();
                return {
                    result,
                    attachment,
                    before,
                    after,
                    serverAfter,
                    reviewText: Array.from(
                        document.querySelectorAll(
                            '#trainFacilityLayoutAuthoring '
                            + '[data-proposal-review]'
                        )
                    ).map(item => item.textContent.trim()),
                };
            }"""
        )

        root = page.locator("#trainFacilityLayoutAuthoring")
        root.locator('[data-view="plan"]').click()
        root.screenshot(path=str(DEFAULT_PLAN))
        root.locator('[data-view="3d"]').click()
        page.wait_for_timeout(300)
        root.screenshot(path=str(DEFAULT_THREE))
        root.locator('[data-view="plan"]').click()

        dismissed = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                await app.session.dismissLayoutProposal();
                const state = app.session.getState();
                const server = await app.transport.reloadLayout();
                return { state, server };
            }"""
        )
        browser.close()

    attachment = evidence["attachment"]
    checks = {
        "minimal_browser_attachment": (
            set(attachment)
            == {
                "siteId",
                "layoutId",
                "revision",
                "state",
                "proposalId",
                "receiptIds",
            }
            and "layout" not in attachment
            and "camera" not in attachment
            and "evidence" not in attachment
            and "digest" not in attachment
        ),
        "semantic_preview_tool_succeeded": (
            evidence["result"]["ok"] is True
            and evidence["result"]["previewOnly"] is True
            and evidence["result"]["saved"] is False
        ),
        "proposal_is_installed": bool(
            evidence["after"]["layoutProposal"]
        ),
        "preview_does_not_dirty_session": (
            evidence["after"]["dirty"] is False
        ),
        "preview_does_not_mutate_saved_layout": (
            evidence["before"]["revision"]
            == evidence["serverAfter"]["revision"]
            and evidence["before"]["layout"]
            == evidence["serverAfter"]["layout"]
        ),
        "review_is_visible_and_bounded": (
            bool(evidence["reviewText"])
            and all(len(item) <= 600 for item in evidence["reviewText"])
        ),
        "dismiss_is_byte_identical": (
            dismissed["state"]["layoutProposal"] is None
            and dismissed["state"]["dirty"] is False
            and dismissed["server"]["revision"]
            == evidence["before"]["revision"]
            and dismissed["server"]["layout"]
            == evidence["before"]["layout"]
        ),
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
        "no_failed_responses": not failed_responses,
    }
    result = {
        "schemaVersion": "facility-layout-p9-product-evidence-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "errors": {
            "console": console_errors,
            "page": page_errors,
        },
        "network": {"failedResponses": failed_responses},
        "semantic": {
            "selectedProposalId": evidence["result"][
                "selectedProposalId"
            ],
            "summary": deepcopy(
                evidence["result"]["semanticPlan"]["summary"]
            ),
            "assumptionCount": len(
                evidence["result"]["semanticPlan"]["assumptions"]
            ),
            "unresolvedCount": len(
                evidence["result"]["semanticPlan"]["unresolvedItems"]
            ),
        },
        "screenshots": {
            "plan": _image(DEFAULT_PLAN),
            "three": _image(DEFAULT_THREE),
        },
        "source": {
            "agentRuntimeSha256": _sha256(
                ROOT
                / "ai_inspector"
                / "facility_layout"
                / "agent_runtime.py"
            ),
            "hostSha256": _sha256(
                ROOT / "ai_inspector" / "facility_layout" / "host.py"
            ),
            "indexSha256": _sha256(ROOT / "static" / "index.html"),
            "observationSha256": _sha256(
                ROOT
                / "ai_inspector"
                / "facility_layout"
                / "observation.py"
            ),
            "semanticPlanSha256": _sha256(
                ROOT
                / "ai_inspector"
                / "facility_layout"
                / "semantic_plan.py"
            ),
            "serverSha256": _sha256(ROOT / "server.py"),
            "sessionSha256": _sha256(
                ROOT / "static" / "facility_layout_session.js"
            ),
            "verifierSha256": _sha256(Path(__file__)),
        },
    }
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )
    for name, passed in checks.items():
        print(("PASS" if passed else "FAIL") + "\t" + name)
    print("RESULT\t" + str(output))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://127.0.0.1:8040/")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    result = verify(args.app_url, args.output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
