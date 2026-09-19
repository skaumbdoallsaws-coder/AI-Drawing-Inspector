"""Capture browser evidence for revision-bound Facility motion playback."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAYOUT = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
DEFAULT_PAYLOAD = (
    ROOT
    / ".runtime"
    / "facility-motion"
    / "browser-clone-motion-payload.json"
)
DEFAULT_OUTPUT = ROOT / ".runtime" / "facility-motion" / "evidence"
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image_evidence(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        sampled = image.resize((128, 72))
        colors = sampled.getcolors(128 * 72) or []
        extrema = image.getextrema()
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
            "byteLength": path.stat().st_size,
            "width": image.width,
            "height": image.height,
            "nonblank": any(low != high for low, high in extrema),
            "sampledColorCount": len(colors),
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
            window._trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && _trainFacilityLayoutAuthoringApp.session.getState().loaded
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=180_000,
    )
    page.evaluate(
        """async () => {
            const app = window._trainFacilityLayoutAuthoringApp;
            if (app.workspace.controller
                    && typeof app.workspace.controller.ready === 'function') {
                await app.workspace.controller.ready();
            }
        }"""
    )


def _snapshot(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const session = app.session.getState();
            const three = app.workspace.threeAdapter.motion.getState();
            const planDiagnostics = app.workspace.topAdapter.getDiagnostics();
            const threeDiagnostics = app.workspace.threeAdapter.getDiagnostics();
            return {
                layoutId: session.layout.layoutId,
                baseRevision: session.baseRevision,
                dirty: session.dirty,
                operationCount: session.operations.length,
                zoneCount: session.layout.zones.length,
                routeCount: session.layout.routes.length,
                placementCount: session.layout.placements.length,
                markingCount: session.layout.floorMarkings.length,
                viewMode: app.workspace.viewMode,
                workspaceMotion: JSON.parse(JSON.stringify(app.workspace.motionState)),
                threeMotion: three,
                planMotion: planDiagnostics.motion,
                threeDiagnostics,
                adapterWalkthrough: threeDiagnostics.navigation.walkthrough,
                adapterDrone: threeDiagnostics.navigation.drone,
                walkthrough: JSON.parse(JSON.stringify(app.workspace.threeWalkthrough)),
                drone: JSON.parse(JSON.stringify(app.workspace.threeDrone)),
                layoutBytes: JSON.stringify(session.layout),
            };
        }"""
    )


def _seek(page: Any, fraction: float, view: str) -> dict[str, Any]:
    page.evaluate(
        """([fraction, view]) => {
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            workspace._setViewMode(view);
            const motion = workspace.threeAdapter.motion;
            const state = motion.getState();
            motion.pause();
            motion.seek(state.durationSeconds * fraction);
        }""",
        [fraction, view],
    )
    page.wait_for_timeout(700)
    return _snapshot(page)


def capture(args: argparse.Namespace) -> dict[str, Any]:
    layout_path = Path(args.layout).resolve()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_before = _sha256(layout_path)
    archived_layout = json.loads(layout_path.read_text(encoding="utf-8"))
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    server_errors: list[str] = []
    screenshots: list[Path] = []

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "headless": True,
            "args": [
                "--enable-precise-memory-info",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ],
        }
        if DEFAULT_EDGE.is_file():
            launch_options["executable_path"] = str(DEFAULT_EDGE)
        browser = playwright.chromium.launch(**launch_options)
        browser_version = browser.version
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            reduced_motion="no-preference",
        )
        context.add_init_script(
            "localStorage.setItem('inspectorpro.theme', 'dark');"
        )
        page = context.new_page()
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
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.method} {request.url}: {request.failure}"
            ),
        )
        page.on(
            "response",
            lambda response: (
                server_errors.append(f"{response.status} {response.url}")
                if response.status >= 500
                else None
            ),
        )
        page.goto(args.url, wait_until="domcontentloaded", timeout=120_000)
        _open_facility(page)
        initial = _snapshot(page)
        if initial["baseRevision"] != payload["package"]["layoutRevision"]:
            raise RuntimeError("Motion payload and active layout revisions differ.")
        browser_layout = json.loads(initial["layoutBytes"])
        browser_layout["layoutId"] = archived_layout["layoutId"]
        matches_archive = browser_layout == archived_layout
        if not matches_archive:
            raise RuntimeError(
                "The browser fixture differs from the archived manual layout."
            )
        page.evaluate(
            """(payload) => {
                const app = window._trainFacilityLayoutAuthoringApp;
                return app.workspace.loadMotionPresentation(
                    payload,
                    app.session.getState().baseRevision
                );
            }""",
            payload,
        )

        plan_20 = _seek(page, 0.20, "plan")
        path = output_dir / "01-plan-motion-20-percent.png"
        page.screenshot(path=str(path))
        screenshots.append(path)

        plan_70 = _seek(page, 0.70, "plan")
        path = output_dir / "02-plan-motion-70-percent.png"
        page.screenshot(path=str(path))
        screenshots.append(path)

        three_mid = _seek(page, 0.50, "3d")
        page.evaluate(
            """async () => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                if (workspace.controller && workspace.controller.ready) {
                    await workspace.controller.ready();
                }
                workspace.threeAdapter.fitLayout();
            }"""
        )
        page.wait_for_timeout(1500)
        three_mid = _snapshot(page)
        path = output_dir / "03-3d-motion-midpoint.png"
        page.screenshot(path=str(path))
        screenshots.append(path)

        page.wait_for_function(
            """() => (
                window._trainFacilityLayoutAuthoringApp.workspace
                    .threeAdapter.getDiagnostics().pendingLoads === 0
            )""",
            timeout=180_000,
        )
        page.wait_for_timeout(2000)

        playback_probe = page.evaluate(
            """async () => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                const motion = workspace.threeAdapter.motion;
                motion.setRate(4);
                const before = motion.getState();
                motion.play();
                await new Promise((resolve) => setTimeout(resolve, 1000));
                motion.pause();
                motion.play();
                let frames = 0;
                const started = performance.now();
                await new Promise((resolve) => {
                    function tick(now) {
                        frames += 1;
                        if (now - started >= 3000) resolve();
                        else requestAnimationFrame(tick);
                    }
                    requestAnimationFrame(tick);
                });
                motion.pause();
                const after = motion.getState();
                return {
                    frames,
                    elapsedWallSeconds: (performance.now() - started) / 1000,
                    before,
                    after,
                };
            }"""
        )

        page.locator('[data-three-command="drone"]').click()
        page.wait_for_timeout(1000)
        drone = _snapshot(page)
        path = output_dir / "04-3d-drone-motion-loaded.png"
        page.screenshot(path=str(path))
        screenshots.append(path)

        page.evaluate(
            """() => window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.exitDrone('acceptance_switch')"""
        )
        page.wait_for_function(
            """() => !window._trainFacilityLayoutAuthoringApp.workspace
                .threeAdapter.getDroneState().active"""
        )
        page.locator('[data-three-command="walkthrough"]').click()
        page.wait_for_timeout(1000)
        walkthrough = _snapshot(page)
        path = output_dir / "05-3d-walkthrough-motion-loaded.png"
        page.screenshot(path=str(path))
        screenshots.append(path)

        final = _snapshot(page)
        browser.close()

    archive_after = _sha256(layout_path)
    plan_pose_equal = (
        plan_70["planMotion"]["pose"] == plan_70["threeMotion"]["pose"]
    )
    report = {
        "schemaVersion": 1,
        "acceptanceId": "facility-motion-manual-reference-browser-fm6",
        "url": args.url,
        "browserVersion": browser_version,
        "archive": {
            "path": layout_path.relative_to(ROOT).as_posix(),
            "sha256Before": archive_before,
            "sha256After": archive_after,
            "byteIdentical": archive_before == archive_after,
        },
        "layout": {
            "layoutId": initial["layoutId"],
            "revision": initial["baseRevision"],
            "zoneCount": initial["zoneCount"],
            "routeCount": initial["routeCount"],
            "placementCount": initial["placementCount"],
            "markingCount": initial["markingCount"],
            "dirtyBefore": initial["dirty"],
            "dirtyAfter": final["dirty"],
            "operationCountAfter": final["operationCount"],
            "browserLayoutByteIdentical": (
                initial["layoutBytes"] == final["layoutBytes"]
            ),
            "matchesArchivedManualExceptLayoutId": matches_archive,
        },
        "motion": {
            "packageId": payload["package"]["packageId"],
            "prototypeLabel": payload.get("prototypeLabel"),
            "plan20": plan_20["threeMotion"],
            "plan70": plan_70["threeMotion"],
            "threeMidpoint": three_mid["threeMotion"],
            "planAndThreePoseEqual": plan_pose_equal,
            "markerVisible": plan_70["planMotion"]["markerVisible"],
            "distanceAdvanced": (
                plan_70["threeMotion"]["distanceMeters"]
                > plan_20["threeMotion"]["distanceMeters"]
            ),
            "playbackProbe": playback_probe,
            "measuredFramesPerSecond": (
                playback_probe["frames"]
                / playback_probe["elapsedWallSeconds"]
            ),
        },
        "immersiveModes": {
            "droneActive": drone["adapterDrone"]["active"],
            "droneMotionLoaded": drone["threeMotion"]["loaded"],
            "walkthroughActive": walkthrough["adapterWalkthrough"]["active"],
            "walkthroughReason": walkthrough["adapterWalkthrough"]["reason"],
            "walkthroughMotionLoaded": walkthrough["threeMotion"]["loaded"],
        },
        "errors": {
            "page": page_errors,
            "console": console_errors,
            "failedRequests": failed_requests,
            "server5xx": server_errors,
        },
        "screenshots": [_image_evidence(path) for path in screenshots],
    }
    required = [
        report["archive"]["byteIdentical"],
        report["layout"]["browserLayoutByteIdentical"],
        report["layout"]["matchesArchivedManualExceptLayoutId"],
        report["layout"]["dirtyAfter"] is False,
        report["layout"]["operationCountAfter"] == 0,
        report["motion"]["planAndThreePoseEqual"],
        report["motion"]["markerVisible"],
        report["motion"]["distanceAdvanced"],
        report["motion"]["measuredFramesPerSecond"] >= 30,
        report["immersiveModes"]["droneActive"],
        report["immersiveModes"]["droneMotionLoaded"],
        report["immersiveModes"]["walkthroughActive"],
        report["immersiveModes"]["walkthroughMotionLoaded"],
        not any(report["errors"].values()),
        all(item["nonblank"] for item in report["screenshots"]),
    ]
    report["passed"] = all(required)
    report_path = output_dir / "facility-motion-browser-evidence.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8153/")
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    report = capture(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
