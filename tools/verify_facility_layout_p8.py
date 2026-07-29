"""Capture source-bound P8 Facility Layout proposal evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "tests" / "fixtures" / "facility_layout" / "planning"
DEFAULT_RESULT = EVIDENCE / "p8-product-result.json"
DEFAULT_PLAN = EVIDENCE / "p8-product-plan.png"
DEFAULT_THREE = EVIDENCE / "p8-product-three.png"


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


def _without_server_timestamps(layout: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(layout)
    result.pop("updatedAt", None)
    return result


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
    authority_responses: list[dict[str, Any]] = []

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

        def on_response(response: Any) -> None:
            record = {
                "method": response.request.method,
                "status": response.status,
                "url": response.url,
            }
            if response.status >= 400 and not response.url.endswith(
                "/static/manifest.json"
            ):
                failed_responses.append(record)
            if (
                "/api/facility-layouts/" in response.url
                and any(
                    suffix in response.url
                    for suffix in (
                        "/proposals",
                        "/approvals",
                        "/apply",
                        "/receipts/",
                    )
                )
            ):
                authority_responses.append(record)

        page.on("response", on_response)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        root = page.locator("#trainFacilityLayoutAuthoring")
        root.locator('[data-view="plan"]').click()

        initial = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const state = app.session.getState();
                const server = await app.transport.reloadLayout();
                return {
                    revision: state.baseRevision,
                    layout: state.layout,
                    layoutBytes: JSON.stringify(state.layout),
                    dirty: state.dirty,
                    server,
                };
            }"""
        )

        first_preview = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                await app.workspace.executeCommand('auto-arrange');
                await app.workspace.controller.ready();
                const state = app.session.getState();
                const selected = state.layoutProposal.alternatives[
                    state.layoutProposal.selectedIndex
                ];
                return {
                    state,
                    selected,
                    rendered: app.workspace.controller.getState().layout,
                    views: app.workspace.controller.getState().views,
                    text: document.querySelector(
                        '#trainFacilityLayoutAuthoring'
                    ).innerText,
                };
            }"""
        )
        root.locator(".ip-flw-viewport-pane").screenshot(
            path=str(DEFAULT_PLAN)
        )

        root.locator('[data-view="3d"]').click()
        page.wait_for_selector(
            "#trainFacilityLayoutAuthoring .ip-flw-three-view canvas",
            state="visible",
            timeout=30_000,
        )
        page.evaluate(
            """async () => {
                const workspace = _trainFacilityLayoutAuthoringApp.workspace;
                await workspace.executeCommand('fit');
                await workspace.controller.ready();
            }"""
        )
        page.wait_for_timeout(350)
        root.locator(".ip-flw-viewport-pane").screenshot(
            path=str(DEFAULT_THREE)
        )
        three = page.evaluate(
            """() => ({
                controller: _trainFacilityLayoutAuthoringApp.workspace
                    .controller.getState(),
                diagnostics: _trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.getDiagnostics(),
            })"""
        )

        cycled = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const before = app.session.getState().layoutProposal;
                if (before.alternatives.length > 1) {
                    app.session.cycleLayoutProposal(1);
                }
                await app.workspace.controller.ready();
                const state = app.session.getState();
                return {
                    proposal: state.layoutProposal,
                    selected: state.layoutProposal.alternatives[
                        state.layoutProposal.selectedIndex
                    ],
                    rendered: app.workspace.controller.getState().layout,
                    savedLayoutBytes: JSON.stringify(state.layout),
                    dirty: state.dirty,
                };
            }"""
        )

        dismissed = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const before = app.session.getState();
                await app.session.dismissLayoutProposal();
                const after = app.session.getState();
                const server = await app.transport.reloadLayout();
                return {
                    beforeRevision: before.baseRevision,
                    afterRevision: after.baseRevision,
                    beforeLayoutBytes: JSON.stringify(before.layout),
                    afterLayoutBytes: JSON.stringify(after.layout),
                    serverLayoutBytes: JSON.stringify(server.layout),
                    dirty: after.dirty,
                    proposal: after.layoutProposal,
                    rendered: app.workspace.controller.getState().layout,
                };
            }"""
        )

        applied = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                await app.workspace.executeCommand('auto-arrange');
                const before = app.session.getState();
                const selected = before.layoutProposal.alternatives[
                    before.layoutProposal.selectedIndex
                ];
                const result = await app.session
                    .approveAndApplyLayoutProposal();
                await app.workspace.controller.ready();
                const after = app.session.getState();
                const server = await app.transport.reloadLayout();
                return {
                    selected,
                    result,
                    after,
                    server,
                    rendered: app.workspace.controller.getState().layout,
                };
            }"""
        )
        browser.close()

    preview_layout = first_preview["selected"]["ghostPreview"]["layout"]
    cycled_layout = cycled["selected"]["ghostPreview"]["layout"]
    receipt = applied["result"]["receipt"]["receipt"]
    applied_layout = applied["after"]["layout"]
    commit_result = applied["result"]["receipt"]["operationResult"]
    checks = {
        "preview_is_revision_bound": (
            first_preview["state"]["baseRevision"] == initial["revision"]
            and first_preview["selected"]["transactionBinding"][
                "baseRevision"
            ]
            == initial["revision"]
        ),
        "preview_does_not_dirty_saved_state": (
            first_preview["state"]["dirty"] is False
            and first_preview["state"]["layout"] == initial["layout"]
        ),
        "plan_renders_exact_preview": (
            first_preview["rendered"] == preview_layout
            and len(preview_layout["placements"]) >= 1
        ),
        "three_renders_same_preview": (
            three["controller"]["layout"] == preview_layout
            and three["diagnostics"]["placementCount"]
            == len(preview_layout["placements"])
        ),
        "preview_state_is_visible": (
            "preview not saved" in first_preview["text"].lower()
            and "approve" in first_preview["text"].lower()
        ),
        "alternatives_cycle_without_dirtying": (
            cycled["rendered"] == cycled_layout
            and cycled["savedLayoutBytes"] == initial["layoutBytes"]
            and cycled["dirty"] is False
        ),
        "dismiss_is_byte_identical": (
            dismissed["beforeRevision"] == dismissed["afterRevision"]
            and dismissed["beforeLayoutBytes"]
            == dismissed["afterLayoutBytes"]
            == dismissed["serverLayoutBytes"]
            and dismissed["dirty"] is False
            and dismissed["proposal"] is None
            and dismissed["rendered"] == initial["layout"]
        ),
        "apply_equals_selected_preview": (
            commit_result["document"]
            == applied["selected"]["ghostPreview"]["layout"]
            and _without_server_timestamps(applied_layout)
            == _without_server_timestamps(
                applied["selected"]["ghostPreview"]["layout"]
            )
            and applied["rendered"] == applied_layout
            and applied["server"]["layout"] == applied_layout
        ),
        "apply_returns_canonical_receipt": (
            receipt["revision"] == applied["after"]["baseRevision"]
            and receipt["binding"]["diffHash"]
            == applied["selected"]["transactionBinding"]["diffHash"]
            and receipt["proposalId"]
            == applied["selected"]["proposalId"]
        ),
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
        "no_failed_responses": not failed_responses,
    }
    source_paths = {
        "apiSha256": ROOT / "ai_inspector" / "facility_layout" / "api.py",
        "appSha256": ROOT / "static" / "facility_layout_app.js",
        "hostSha256": ROOT / "ai_inspector" / "facility_layout" / "host.py",
        "indexSha256": ROOT / "static" / "index.html",
        "plannerSha256": (
            ROOT / "ai_inspector" / "facility_layout" / "planner.py"
        ),
        "serviceSha256": (
            ROOT / "ai_inspector" / "facility_layout" / "service.py"
        ),
        "sessionSha256": ROOT / "static" / "facility_layout_session.js",
        "threeAdapterSha256": (
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "transactionAdapterSha256": (
            ROOT
            / "ai_inspector"
            / "facility_layout"
            / "transaction_adapter.py"
        ),
        "transportSha256": (
            ROOT / "static" / "facility_layout_transport.js"
        ),
        "verifierSha256": Path(__file__).resolve(),
        "workspaceSha256": (
            ROOT / "static" / "facility_layout_workspace.js"
        ),
    }
    result = {
        "schemaVersion": "facility-layout-p8-product-evidence-v1",
        "appUrl": app_url,
        "passed": all(checks.values()),
        "checks": checks,
        "initial": initial,
        "firstPreview": first_preview,
        "cycled": cycled,
        "dismissed": dismissed,
        "applied": applied,
        "three": three,
        "network": {
            "authorityResponses": authority_responses,
            "failedResponses": failed_responses,
        },
        "errors": {
            "page": page_errors,
            "console": console_errors,
        },
        "screenshots": {
            "plan": _image(DEFAULT_PLAN),
            "three": _image(DEFAULT_THREE),
        },
        "source": {
            field: _sha256(path) for field, path in source_paths.items()
        },
    }
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--app-url",
        default=os.getenv("P8_PRODUCT_APP_URL", "http://127.0.0.1:8037/"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    result = verify(args.app_url, args.output.resolve())
    for name, passed in result["checks"].items():
        print(("PASS" if passed else "FAIL") + "\t" + name)
    print(f"RESULT\t{args.output.resolve()}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
