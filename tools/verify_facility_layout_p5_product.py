"""Capture source-bound evidence for the production P5 Facility Layout mount."""

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
AUTHORING = ROOT / "tests" / "fixtures" / "facility_layout" / "authoring"
DEFAULT_RESULT = AUTHORING / "p5-product-result.json"
DEFAULT_PLAN = AUTHORING / "p5-product-integration.png"
DEFAULT_THREE = AUTHORING / "p5-product-three-integration.png"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "width": image.width,
            "height": image.height,
            "nonblank": any(low != high for low, high in extrema),
        }


def _open_facility(page: Any) -> None:
    page.evaluate(
        """() => {
            if (state.activeTab !== 'training') switchTab('training');
            const previous = trainingState.type;
            trainingState.type = 'facility_layout';
            trainingState.viewportMode = 'facility_layout';
            try { _trainApplyTrainingTypeDefaults(previous); } catch (_) {}
        }"""
    )
    page.wait_for_selector(
        "#trainFacilityLayoutAuthoring.ip-flw-root",
        state="visible",
        timeout=120_000,
    )
    page.wait_for_function(
        """() => {
            const app = _trainFacilityLayoutAuthoringApp;
            return !!(
                app
                && app.workspace
                && app.workspace.threeAdapter
                && app.workspace.threeAdapter.getDiagnostics().controlsActive
                && document.querySelectorAll(
                    '#trainFacilityLayoutAuthoring .ip-flw-asset-row[data-asset-id]'
                ).length >= 4
            );
        }""",
        timeout=120_000,
    )


def verify(app_url: str, result_path: Path) -> dict[str, Any]:
    page_errors: list[str] = []
    console_errors: list[str] = []
    AUTHORING.mkdir(parents=True, exist_ok=True)

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
        page.goto(app_url, wait_until="load", timeout=120_000)
        # Let the large classic application script finish its late lexical
        # initialization before probing; repeated CDP evaluation can otherwise
        # interrupt it between declaration and initialization.
        page.wait_for_timeout(2_000)
        ready = False
        probe: dict[str, Any] = {}
        for _ in range(50):
            probe = page.evaluate(
                """() => ({
                    documentReady: document.readyState,
                    switchTabType: typeof switchTab,
                    defaultsType: typeof _trainApplyTrainingTypeDefaults,
                    mainScriptReady: window.__inspectorProMainScriptReady,
                    sourceHasReady: document.documentElement.innerHTML
                        .includes('__inspectorProMainScriptReady'),
                    href: location.href,
                })"""
            )
            ready = (
                probe["documentReady"] == "complete"
                and probe["switchTabType"] == "function"
                and probe["defaultsType"] == "function"
                and probe["mainScriptReady"] is True
            )
            if ready:
                break
            page.wait_for_timeout(100)
        if not ready:
            raise RuntimeError(
                "InspectorPro main script did not become ready: "
                f"{probe!r}; pageErrors={page_errors!r}; "
                f"consoleErrors={console_errors!r}"
            )
        _open_facility(page)
        root = page.locator("#trainFacilityLayoutAuthoring")
        root.locator('[data-view="plan"]').click()
        page.wait_for_timeout(300)
        page.screenshot(path=str(DEFAULT_PLAN), full_page=True)

        initial = page.evaluate(
            """() => {
                const app = _trainFacilityLayoutAuthoringApp;
                return {
                    assetRows: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring '
                        + '.ip-flw-asset-row[data-asset-id]'
                    ).length,
                    placements: app.session.getState().layout.placements.length,
                    roots: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring'
                    ).length,
                    planSvgs: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring '
                        + 'svg[data-facility-layout-view="top-plan"]'
                    ).length,
                    canvases: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring '
                        + '.ip-flw-three-view canvas'
                    ).length,
                    threeDisabled: document.querySelector(
                        '#trainFacilityLayoutAuthoring [data-view="3d"]'
                    ).disabled,
                    diagnostics: app.workspace.threeAdapter.getDiagnostics(),
                };
            }"""
        )

        root.locator('[data-view="3d"]').click()
        canvas = root.locator(".ip-flw-three-view canvas")
        canvas.wait_for(state="visible", timeout=30_000)
        before_camera = page.evaluate(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics().camera"""
        )
        box = canvas.bounding_box()
        if not box:
            raise RuntimeError("Production Facility Layout canvas has no bounds.")
        page.mouse.move(
            box["x"] + box["width"] * 0.5,
            box["y"] + box["height"] * 0.5,
        )
        page.mouse.down(button="left")
        page.mouse.move(
            box["x"] + box["width"] * 0.65,
            box["y"] + box["height"] * 0.38,
            steps=12,
        )
        page.mouse.up(button="left")
        page.wait_for_timeout(400)
        after_camera = page.evaluate(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDiagnostics().camera"""
        )

        drop = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const workspace = app.workspace;
                const root = document.querySelector(
                    '#trainFacilityLayoutAuthoring'
                );
                const row = root.querySelector(
                    '.ip-flw-asset-row[data-asset-id="asset-forklift"]'
                );
                const canvas = root.querySelector(
                    '.ip-flw-three-view canvas'
                );
                const rect = canvas.getBoundingClientRect();
                const transfer = new DataTransfer();
                row.dispatchEvent(new DragEvent('dragstart', {
                    bubbles: true,
                    cancelable: true,
                    dataTransfer: transfer,
                }));
                const init = {
                    bubbles: true,
                    cancelable: true,
                    dataTransfer: transfer,
                    clientX: rect.left + rect.width * 0.5,
                    clientY: rect.top + rect.height * 0.5,
                };
                const beforeIds = new Set(
                    app.session.getState().layout.placements.map(
                        value => value.placementId
                    )
                );
                canvas.dispatchEvent(new DragEvent('dragover', init));
                const ghost = app.session.getState().ghostPlacement;
                const before = app.session.getState().layout.placements.length;
                canvas.dispatchEvent(new DragEvent('drop', init));
                await workspace.whenIdle();
                const alternatives = app.session.getState()
                    .placementAlternatives;
                let acceptedCandidateId = null;
                let acceptedSafetyStatus = null;
                if (alternatives && alternatives.candidates.length) {
                    const selected = alternatives.candidates[
                        alternatives.selectedIndex
                    ];
                    acceptedCandidateId = selected.candidateId;
                    acceptedSafetyStatus = selected.safetyStatus;
                    await app.session.acceptPlacementAlternative();
                    await workspace.whenIdle();
                }
                const afterState = app.session.getState();
                const created = afterState.layout.placements.find(
                    value => value.assetId === 'asset-forklift'
                        && !beforeIds.has(value.placementId)
                );
                const after = afterState.layout.placements.length;
                await workspace.executeCommand('undo');
                await workspace.whenIdle();
                const undone = app.session.getState();
                return {
                    before,
                    after,
                    afterUndo: undone.layout.placements.length,
                    dirtyAfterUndo: undone.dirty,
                    ghostWorld: ghost && ghost.worldPosition,
                    createdWorld: created && created.transform.position,
                    acceptedCandidateId,
                    acceptedSafetyStatus,
                };
            }"""
        )
        page.screenshot(path=str(DEFAULT_THREE), full_page=True)

        page.evaluate(
            """() => {
                window.__p5RetainedFacilityApp =
                    _trainFacilityLayoutAuthoringApp;
                window.__p5RetainedFacilityWorkspace =
                    _trainFacilityLayoutAuthoringApp.workspace;
                const previous = trainingState.type;
                trainingState.type = 'service';
                _trainApplyTrainingTypeDefaults(previous);
            }"""
        )
        page.wait_for_function(
            """() => {
                const app = window.__p5RetainedFacilityApp;
                const workspace = window.__p5RetainedFacilityWorkspace;
                return !!(
                    app
                    && workspace
                    && app === _trainFacilityLayoutAuthoringApp
                    && app.getState().suspended
                    && workspace.getState().suspended
                    && !workspace.root.isConnected
                    && document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring'
                    ).length === 0
                );
            }""",
            timeout=30_000,
        )
        suspended = page.evaluate(
            """() => {
                const app = window.__p5RetainedFacilityApp;
                const workspace = window.__p5RetainedFacilityWorkspace;
                const diagnostics = workspace.threeAdapter.getDiagnostics();
                return {
                    roots: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring'
                    ).length,
                    canvasesInDocument: Array.from(
                        document.querySelectorAll('canvas')
                    ).filter(canvas => workspace.root.contains(canvas)).length,
                    appRetained: app === _trainFacilityLayoutAuthoringApp,
                    appSuspended: app.getState().suspended,
                    workspaceSuspended: workspace.getState().suspended,
                    rootConnected: workspace.root.isConnected,
                    pendingFrame: diagnostics.demandRendering.pendingFrame,
                    observerActive: diagnostics.lifecycle.observerActive,
                };
            }"""
        )
        _open_facility(page)
        remounted = page.evaluate(
            """() => {
                const app = _trainFacilityLayoutAuthoringApp;
                const diagnostics = app.workspace.threeAdapter.getDiagnostics();
                return {
                    roots: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring'
                    ).length,
                    planSvgs: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring '
                        + 'svg[data-facility-layout-view="top-plan"]'
                    ).length,
                    canvases: document.querySelectorAll(
                        '#trainFacilityLayoutAuthoring '
                        + '.ip-flw-three-view canvas'
                    ).length,
                    sameApp: app === window.__p5RetainedFacilityApp,
                    sameWorkspace: app.workspace
                        === window.__p5RetainedFacilityWorkspace,
                    appSuspended: app.getState().suspended,
                    workspaceSuspended: app.workspace.getState().suspended,
                    rootConnected: app.workspace.root.isConnected,
                    observerActive: diagnostics.lifecycle.observerActive,
                };
            }"""
        )
        browser.close()

    checks = {
        "production_workspace_mounted": (
            initial["roots"] == 1
            and initial["assetRows"] >= 4
            and initial["planSvgs"] == 1
        ),
        "production_three_tab_enabled": initial["threeDisabled"] is False,
        "local_orbit_controls_active": (
            initial["diagnostics"]["controlsActive"] is True
        ),
        "orbit_changes_camera": (
            before_camera["position"] != after_camera["position"]
        ),
        "drop_after_orbit_uses_world_coordinates": (
            drop["after"] == drop["before"] + 1
            and drop["createdWorld"] is not None
            and drop["acceptedCandidateId"] is not None
        ),
        "undo_restores_exact_draft": (
            drop["afterUndo"] == drop["before"]
            and drop["dirtyAfterUndo"] is False
        ),
        "workflow_switch_suspends_workspace": (
            suspended == {
                "roots": 0,
                "canvasesInDocument": 0,
                "appRetained": True,
                "appSuspended": True,
                "workspaceSuspended": True,
                "rootConnected": False,
                "pendingFrame": False,
                "observerActive": False,
            }
        ),
        "resume_reuses_one_workspace": (
            remounted == {
                "roots": 1,
                "planSvgs": 1,
                "canvases": 1,
                "sameApp": True,
                "sameWorkspace": True,
                "appSuspended": False,
                "workspaceSuspended": False,
                "rootConnected": True,
                "observerActive": True,
            }
        ),
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
    }
    sources = {
        "appSha256": _sha256(ROOT / "static" / "facility_layout_app.js"),
        "editorSha256": _sha256(
            ROOT / "static" / "facility_layout_editor.js"
        ),
        "hostSha256": _sha256(
            ROOT / "ai_inspector" / "facility_layout" / "host.py"
        ),
        "indexSha256": _sha256(ROOT / "static" / "index.html"),
        "threeAdapterSha256": _sha256(
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "transportSha256": _sha256(
            ROOT / "static" / "facility_layout_transport.js"
        ),
        "threeClassicSha256": _sha256(
            ROOT
            / "static"
            / "vendor"
            / "three"
            / "0.128.0"
            / "build"
            / "three.min.js"
        ),
        "threeModuleSha256": _sha256(
            ROOT
            / "static"
            / "vendor"
            / "three"
            / "0.184.0"
            / "build"
            / "three.module.min.js"
        ),
        "orbitControlsSha256": _sha256(
            ROOT
            / "static"
            / "vendor"
            / "three"
            / "0.184.0"
            / "examples"
            / "jsm"
            / "controls"
            / "OrbitControls.js"
        ),
        "verifierSha256": _sha256(Path(__file__).resolve()),
        "workspaceSha256": _sha256(
            ROOT / "static" / "facility_layout_workspace.js"
        ),
    }
    result = {
        "schemaVersion": "facility-layout-p5-product-evidence-v1",
        "appUrl": app_url,
        "passed": all(checks.values()),
        "checks": checks,
        "initial": initial,
        "camera": {"before": before_camera, "after": after_camera},
        "drop": drop,
        "suspended": suspended,
        "remounted": remounted,
        "errors": {
            "page": page_errors,
            "console": console_errors,
        },
        "screenshots": {
            "plan": _image(DEFAULT_PLAN),
            "three": _image(DEFAULT_THREE),
        },
        "source": sources,
    }
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--app-url",
        default=os.getenv("P5_PRODUCT_APP_URL", "http://127.0.0.1:8023/"),
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
