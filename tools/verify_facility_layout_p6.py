"""Capture source-bound P6 Facility Layout product evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "tests" / "fixtures" / "facility_layout" / "spatial"
DEFAULT_RESULT = EVIDENCE / "p6-product-result.json"
DEFAULT_GHOST = EVIDENCE / "p6-product-ghost.png"
DEFAULT_THREE = EVIDENCE / "p6-product-three.png"


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
    mutation_responses: list[dict[str, Any]] = []

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
                and response.request.method in {"PUT", "POST"}
            ):
                mutation_responses.append(record)

        page.on("response", on_response)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        root = page.locator("#trainFacilityLayoutAuthoring")
        root.locator('[data-view="plan"]').click()

        dismissed = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const session = app.session;
                const workspace = app.workspace;
                const asset = workspace.assetCatalog.find(
                    item => item.assetId === 'asset-forklift'
                );
                const before = session.getState();
                const beforeBytes = JSON.stringify(before.layout);
                const request = {
                    assetId: asset.assetId,
                    assetDefinitionRevision:
                        asset.assetDefinitionRevision,
                    requestedPosition: { x: 12, y: 0, z: 10 },
                    maximumCandidates: 8,
                };
                await session.requestPlacementAlternatives(request);
                const first = session.getState().placementAlternatives;
                const firstIds = first.candidates.map(
                    item => item.candidateId
                );
                const firstGhost = session.getState().ghostPlacement;
                if (first.candidates.length > 1) {
                    session.cyclePlacementAlternative(1);
                }
                const cycledGhost = session.getState().ghostPlacement;
                session.dismissPlacementAlternatives();
                const after = session.getState();
                return {
                    request,
                    baseRevision: before.baseRevision,
                    beforeBytes,
                    afterBytes: JSON.stringify(after.layout),
                    dirtyBefore: before.dirty,
                    dirtyAfter: after.dirty,
                    firstIds,
                    firstGhost,
                    cycledGhost,
                };
            }"""
        )

        proposal = page.evaluate(
            """async request => {
                const session = _trainFacilityLayoutAuthoringApp.session;
                await session.requestPlacementAlternatives(request);
                const state = session.getState();
                const proposal = state.placementAlternatives;
                const selected = proposal.candidates[proposal.selectedIndex];
                return {
                    candidateIds: proposal.candidates.map(
                        item => item.candidateId
                    ),
                    selected,
                    ghost: state.ghostPlacement,
                    uiText: document.querySelector(
                        '#trainFacilityLayoutAuthoring'
                    ).innerText,
                    layoutBytes: JSON.stringify(state.layout),
                    dirty: state.dirty,
                };
            }""",
            dismissed["request"],
        )
        page.screenshot(path=str(DEFAULT_GHOST), full_page=True)

        applied = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const session = app.session;
                const before = session.getState();
                const selected = before.placementAlternatives.candidates[
                    before.placementAlternatives.selectedIndex
                ];
                await session.acceptPlacementAlternative();
                const accepted = session.getState();
                const operations = session.getOperations();
                const created = accepted.layout.placements.find(
                    item => item.assetId === selected.assetId
                );
                const saveResult = await session.save();
                const saved = session.getState();
                const savedBytes = JSON.stringify(saved.layout);
                await session.reload();
                const reopened = session.getState();
                return {
                    selected,
                    operationCount: operations.length,
                    operation: operations[0],
                    created,
                    acceptedDirty: accepted.dirty,
                    saveReceipt: saveResult.receipt,
                    savedRevision: saved.baseRevision,
                    reopenedRevision: reopened.baseRevision,
                    savedLayout: saved.layout,
                    reopenedLayout: reopened.layout,
                    savedBytes,
                    reopenedBytes: JSON.stringify(reopened.layout),
                    reopenedDirty: reopened.dirty,
                    reopenedPlacement: reopened.layout.placements.find(
                        item => item.placementId === created.placementId
                    ),
                };
            }"""
        )

        root.locator('[data-view="3d"]').click()
        page.wait_for_selector(
            "#trainFacilityLayoutAuthoring .ip-flw-three-view canvas",
            state="visible",
            timeout=30_000,
        )
        page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace
                    .executeCommand('fit');
            }"""
        )
        page.wait_for_timeout(300)
        page.screenshot(path=str(DEFAULT_THREE), full_page=True)
        three = page.evaluate(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics()"""
        )
        browser.close()

    selected = proposal["selected"]
    receipt = applied["saveReceipt"]
    checks = {
        "candidate_ids_are_deterministic": (
            dismissed["firstIds"] == proposal["candidateIds"]
            and bool(proposal["candidateIds"])
        ),
        "dismiss_is_byte_identical": (
            dismissed["beforeBytes"] == dismissed["afterBytes"]
            and dismissed["dirtyBefore"] is False
            and dismissed["dirtyAfter"] is False
        ),
        "ghost_preview_is_transient": (
            proposal["layoutBytes"] == dismissed["beforeBytes"]
            and proposal["dirty"] is False
            and proposal["ghost"] is not None
        ),
        "alternatives_cycle": (
            len(proposal["candidateIds"]) == 1
            or dismissed["firstGhost"] != dismissed["cycledGhost"]
        ),
        "safety_is_explicitly_unverified": (
            selected["safetyStatus"] == "unverified"
            and selected["safe"] is False
            and "unverified" in proposal["uiText"].lower()
        ),
        "accept_is_one_exact_operation": (
            applied["operationCount"] == 1
            and applied["operation"]["op"] == "place_asset"
            and applied["created"]["transform"] == selected["transform"]
        ),
        "save_is_one_atomic_apply": (
            receipt["changed"] is True
            and len(receipt["operationResult"]["operationResults"]) == 1
            and len(
                [
                    item
                    for item in mutation_responses
                    if item["method"] == "PUT" and item["status"] == 200
                ]
            )
            == 1
        ),
        "save_reopen_is_exact": (
            applied["savedRevision"] == applied["reopenedRevision"]
            and applied["savedLayout"] == applied["reopenedLayout"]
            and applied["reopenedDirty"] is False
            and applied["reopenedPlacement"] == applied["created"]
        ),
        "three_uses_facility_world_bounds": (
            three["worldBounds"]["minimum"]["x"] == 0
            and three["worldBounds"]["minimum"]["z"] == 0
            and three["worldBounds"]["maximum"]["x"] == 40
            and three["worldBounds"]["maximum"]["z"] == 30
        ),
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
        "no_failed_responses": not failed_responses,
    }
    sources = {
        "appSha256": _sha256(ROOT / "static" / "facility_layout_app.js"),
        "hostSha256": _sha256(
            ROOT / "ai_inspector" / "facility_layout" / "host.py"
        ),
        "indexSha256": _sha256(ROOT / "static" / "index.html"),
        "serviceSha256": _sha256(
            ROOT / "ai_inspector" / "facility_layout" / "service.py"
        ),
        "sessionSha256": _sha256(
            ROOT / "static" / "facility_layout_session.js"
        ),
        "spatialSha256": _sha256(
            ROOT / "ai_inspector" / "facility_layout" / "spatial.py"
        ),
        "threeAdapterSha256": _sha256(
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "transportSha256": _sha256(
            ROOT / "static" / "facility_layout_transport.js"
        ),
        "verifierSha256": _sha256(Path(__file__).resolve()),
        "workspaceSha256": _sha256(
            ROOT / "static" / "facility_layout_workspace.js"
        ),
    }
    result = {
        "schemaVersion": "facility-layout-p6-product-evidence-v1",
        "appUrl": app_url,
        "passed": all(checks.values()),
        "checks": checks,
        "dismissed": dismissed,
        "proposal": proposal,
        "applied": applied,
        "three": three,
        "network": {
            "mutationResponses": mutation_responses,
            "failedResponses": failed_responses,
        },
        "errors": {
            "page": page_errors,
            "console": console_errors,
        },
        "screenshots": {
            "ghost": _image(DEFAULT_GHOST),
            "three": _image(DEFAULT_THREE),
        },
        "source": sources,
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
        default=os.getenv("P6_PRODUCT_APP_URL", "http://127.0.0.1:8036/"),
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
