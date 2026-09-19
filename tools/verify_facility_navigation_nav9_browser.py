"""Capture NAV9 Plan/3D evidence without modifying the manual reference."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import strftime
from typing import Any

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

from verify_facility_navigation_nav2 import (
    ARCHIVE,
    OPERATOR_ID,
    REFERENCE_LAYOUT_ID,
    SITE_ID,
    _http_json,
    _open_facility,
    _prepare_path,
    _sha,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fixtures" / "facility_layout" / "navigation" / "browser"
REPORT = OUTPUT / "nav9-browser-evidence-v1.json"
REFERENCE_SHA256 = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)
EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)


def _pixel_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGB")
        stat = ImageStat.Stat(image)
        extrema = stat.extrema
        return {
            "width": image.width,
            "height": image.height,
            "mean": [round(float(value), 3) for value in stat.mean],
            "standardDeviation": [
                round(float(value), 3) for value in stat.stddev
            ],
            "channelRanges": [maximum - minimum for minimum, maximum in extrema],
            "nonblank": max(stat.stddev) >= 3.0 and max(
                maximum - minimum for minimum, maximum in extrema
            ) >= 24,
        }


def _bootstrap(base_url: str, scratch_id: str) -> dict[str, Any]:
    value = _http_json(base_url, "/api/facility-layout-bootstrap")
    value["layoutId"] = scratch_id
    value["layout"] = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}/{scratch_id}",
    )
    return value


def _set_theme(page: Any, theme: str) -> None:
    page.evaluate(
        """theme => {
            localStorage.setItem('inspectorpro.theme', theme);
            document.documentElement.setAttribute('data-theme', theme);
        }""",
        theme,
    )


def _seek_checkpoint(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
            const activity = workspace.threeAdapter.activity;
            const state = activity.getState();
            const checkpoint = Number(state.durationSeconds || 0) * 0.375;
            activity.pause();
            activity.seek(checkpoint);
            workspace.threeAdapter.invalidate();
            return {checkpoint, actorId: state.actors[0].actorId};
        }"""
    )


def _capture(
    page: Any,
    *,
    theme: str,
    viewport_name: str,
    width: int,
    height: int,
    view: str,
) -> dict[str, Any]:
    page.set_viewport_size({"width": width, "height": height})
    _set_theme(page, theme)
    checkpoint = _seek_checkpoint(page)
    if view == "plan":
        page.evaluate(
            """() => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                workspace._setViewMode('plan');
                workspace.topAdapter.fitLayout();
            }"""
        )
        page.wait_for_timeout(700)
        surface = page.locator("#ip-flw-plan-view")
    else:
        page.evaluate(
            """() => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                workspace._setViewMode('3d');
            }"""
        )
        page.wait_for_timeout(300)
        page.evaluate(
            """actorId => {
                const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                workspace.threeAdapter.activity.focusActor(actorId);
                workspace.threeAdapter.invalidate();
            }""",
            checkpoint["actorId"],
        )
        page.wait_for_timeout(1_200)
        surface = page.locator("#ip-flw-three-view")
    name = f"nav9-{viewport_name}-{theme}-{view}"
    full_path = OUTPUT / f"{name}.png"
    surface_path = OUTPUT / f"{name}-surface.png"
    page.screenshot(path=str(full_path), full_page=False)
    surface.screenshot(path=str(surface_path))
    state = page.evaluate(
        """() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const workspace = app.workspace;
            const three = workspace.threeAdapter.activity.getState();
            const plan = workspace.topAdapter.activitySnapshot;
            const root = document.querySelector('#trainFacilityLayoutAuthoring');
            const panel = root.querySelector('.ip-flw-motion-panel');
            const properties = root.querySelector('.ip-flw-properties');
            const panelBox = panel && !panel.hidden
                ? panel.getBoundingClientRect() : null;
            const propertiesStyle = properties
                ? getComputedStyle(properties) : null;
            const rootBox = root.getBoundingClientRect();
            const selected = three.actors.find(
                actor => actor.actorId === three.selectedActorId
            ) || three.actors[0];
            const planActor = plan && Array.isArray(plan.actors)
                ? plan.actors.find(actor => actor.actorId === selected.actorId)
                : null;
            return {
                selectedActorId: selected.actorId,
                threePose: selected.pose,
                planPose: planActor && planActor.pose,
                threeLoaded: three.loaded,
                threeStatus: three.status,
                actorCount: three.actors.length,
                exactVisualCount: three.actors.filter(
                    actor => actor.exactCatalogVisual === true
                ).length,
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: document.documentElement.clientWidth,
                rootWidth: rootBox.width,
                propertiesVisible: Boolean(
                    propertiesStyle && propertiesStyle.display !== 'none'
                ),
                panelWithinRoot: !panelBox || (
                    panelBox.left >= rootBox.left - 1
                    && panelBox.right <= rootBox.right + 1
                    && panelBox.top >= rootBox.top - 1
                    && panelBox.bottom <= rootBox.bottom + 1
                ),
            };
        }"""
    )
    state["poseAgreement"] = state["threePose"] == state["planPose"]
    state["fullScreenshot"] = full_path.relative_to(ROOT).as_posix()
    state["surfaceScreenshot"] = surface_path.relative_to(ROOT).as_posix()
    state["surfacePixels"] = _pixel_metrics(surface_path)
    return state


def verify(base_url: str) -> dict[str, Any]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reference_before = _sha(ARCHIVE)
    if reference_before != REFERENCE_SHA256:
        raise AssertionError("The manual reference archive is not the frozen revision.")
    reference = _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}/{REFERENCE_LAYOUT_ID}",
    )
    scratch_id = "fl-nav9-browser-" + strftime("%Y%m%d-%H%M%S")
    scratch = deepcopy(reference["layout"])
    scratch["layoutId"] = scratch_id
    scratch["displayName"] = "NAV9 Browser Evidence Scratch"
    scratch.setdefault("extensions", {}).pop("facilityNavigation", None)
    _http_json(
        base_url,
        f"/api/facility-layouts/{SITE_ID}",
        method="POST",
        payload={"layout": scratch, "makeDefault": False},
    )
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    captures = []
    evidence: dict[str, Any] = {}
    try:
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": True,
                "args": [
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                    "--enable-gpu",
                    "--use-angle=d3d11",
                ],
            }
            if EDGE.is_file():
                launch_options["executable_path"] = str(EDGE)
            browser = playwright.chromium.launch(**launch_options)
            browser_version = browser.version
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
            )
            context.add_init_script(
                "localStorage.setItem('inspectorpro.theme', 'light');"
            )
            page = context.new_page()
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error" else None,
            )

            def observe_response(response: Any) -> None:
                if response.status >= 400 and not response.url.endswith(
                    "/static/manifest.json"
                ):
                    failed_responses.append({
                        "status": response.status,
                        "method": response.request.method,
                        "url": response.url,
                    })

            page.on("response", observe_response)
            page.route(
                "**/api/facility-layout-bootstrap",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(_bootstrap(base_url, scratch_id)),
                ),
            )
            page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
            _open_facility(page)
            before = page.evaluate(
                """() => JSON.parse(JSON.stringify(
                    window._trainFacilityLayoutAuthoringApp.session.getState()
                ))"""
            )
            start = {"x": 196.596, "z": 60.6552}
            authored = _prepare_path(
                page,
                actor_id=OPERATOR_ID,
                points=[
                    start,
                    {"x": 196.596, "z": 56.0},
                    {"x": 190.0, "z": 56.0},
                    {"x": 196.596, "z": 56.0},
                    start,
                ],
                loop_mode="closed_loop",
            )
            if not authored["applied"]:
                raise AssertionError("The Plan-authored operator loop was rejected.")
            setup = page.evaluate(
                """async () => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    const workspace = app.workspace;
                    workspace.closeNavigationDialog(false);
                    const navigation = app.session.getState().layout.extensions
                        .facilityNavigation;
                    const programId = navigation.movementPrograms[0]
                        .movementProgramId;
                    const state = app.session.getState();
                    const basePayload = {
                        baseRevision: state.baseRevision,
                        operations: state.operations || [],
                    };
                    const compiled = await workspace.motionTransport
                        .compileNavigationSnapshot({
                            ...basePayload,
                            request: {
                                movementProgramId: programId,
                                prototypeMode: true,
                            },
                        });
                    const packageId = compiled.summary.navigationPackageId;
                    const planned = await workspace.motionTransport
                        .planActorJourney({
                            ...basePayload,
                            request: {
                                navigationPackageId: packageId,
                                movementProgramId: programId,
                                prototypeMode: true,
                            },
                        });
                    if (!planned.summary
                            || planned.summary.outcome !== 'accepted') {
                        const packagePayload = await workspace.motionTransport
                            .getNavigationPackage({ packageId });
                        return {
                            refused: planned.summary || planned,
                            compiled: compiled.summary,
                            navigationPackage: packagePayload,
                            programId,
                            session: JSON.parse(JSON.stringify(
                                app.session.getState()
                            )),
                        };
                    }
                    const result = await workspace.startNavigationActivityPlayback({
                        movementProgramIds: [],
                        journeySolutionIds: [planned.summary.journeySolutionId],
                        handoffResultIds: [],
                        scenarioLabel: 'NAV9 browser acceptance',
                        prototypeMode: true,
                    });
                    workspace.threeAdapter.activity.pause();
                    return {
                        result,
                        compiled: compiled.summary,
                        planned: planned.summary,
                        programId,
                        session: JSON.parse(JSON.stringify(app.session.getState())),
                        activity: workspace.threeAdapter.activity.getState(),
                    };
                }"""
            )
            if setup.get("refused"):
                diagnostic = ROOT / ".runtime" / "nav9-browser-refusal.json"
                diagnostic.parent.mkdir(parents=True, exist_ok=True)
                diagnostic.write_text(
                    json.dumps(setup, indent=2, sort_keys=True) + "\n",
                    encoding="ascii",
                )
                raise AssertionError(
                    "NAV9 journey refusal: "
                    + json.dumps(setup["refused"], sort_keys=True)
                    + f"; diagnostic={diagnostic.relative_to(ROOT)}"
                )
            for viewport_name, width, height in (
                ("desktop", 1920, 1080),
                ("mobile", 430, 932),
            ):
                for theme in ("light", "dark"):
                    for view in ("plan", "3d"):
                        captures.append(_capture(
                            page,
                            theme=theme,
                            viewport_name=viewport_name,
                            width=width,
                            height=height,
                            view=view,
                        ))

            page.set_viewport_size({"width": 1920, "height": 1080})
            _set_theme(page, "light")
            frame_before = page.evaluate(
                """() => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    workspace._setViewMode('3d');
                    const before = workspace.threeAdapter.getDiagnostics()
                        .demandRendering.renderedFrames;
                    workspace.threeAdapter.activity.play();
                    return before;
                }"""
            )
            graphics = page.evaluate(
                """() => {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext('webgl2')
                        || canvas.getContext('webgl');
                    const extension = gl && gl.getExtension(
                        'WEBGL_debug_renderer_info'
                    );
                    return {
                        vendor: extension ? gl.getParameter(
                            extension.UNMASKED_VENDOR_WEBGL
                        ) : null,
                        renderer: extension ? gl.getParameter(
                            extension.UNMASKED_RENDERER_WEBGL
                        ) : null,
                    };
                }"""
            )
            page.wait_for_timeout(60_000)
            playback_end = page.evaluate(
                """() => {
                    const workspace = window._trainFacilityLayoutAuthoringApp.workspace;
                    workspace.threeAdapter.activity.pause();
                    return {
                        renderedFrames: workspace.threeAdapter.getDiagnostics()
                            .demandRendering.renderedFrames,
                        activity: workspace.threeAdapter.activity.getState(),
                        visibilityState: document.visibilityState,
                    };
                }"""
            )
            frames = playback_end["renderedFrames"] - frame_before
            fps = frames / 60.0
            after_playback = page.evaluate(
                """() => JSON.parse(JSON.stringify(
                    window._trainFacilityLayoutAuthoringApp.session.getState()
                ))"""
            )
            page.evaluate(
                """async () => window._trainFacilityLayoutAuthoringApp.workspace
                    .executeCommand('undo')"""
            )
            after_undo = page.evaluate(
                """() => JSON.parse(JSON.stringify(
                    window._trainFacilityLayoutAuthoringApp.session.getState()
                ))"""
            )
            context.close()
            browser.close()
            evidence = {
                "schemaVersion": "facility-navigation-nav9-browser-evidence-v1",
                "referenceLayoutId": REFERENCE_LAYOUT_ID,
                "scratchLayoutId": scratch_id,
                "referenceSha256Before": reference_before,
                "authoring": {
                    "applied": authored["applied"],
                    "programId": setup["programId"],
                    "validationStatus": authored["navigation"][
                        "validationStatus"
                    ],
                },
                "activity": {
                    "scenarioId": setup["result"]["scenarioId"],
                    "plannerOutcome": setup["planned"]["outcome"],
                    "acceptedJourneyCount": len(
                        setup["result"]["journeySolutionIds"]
                    ),
                    "internallyPlannedJourneyCount": setup["result"][
                        "plannedJourneyCount"
                    ],
                    "actorCount": len(setup["activity"]["actors"]),
                    "readOnlyPresentation": setup["result"][
                        "readOnlyPresentation"
                    ],
                },
                "captures": captures,
                "playback": {
                    "durationSeconds": 60,
                    "renderedFrames": frames,
                    "framesPerSecond": round(fps, 3),
                    "minimumFramesPerSecond": 30,
                    "visibilityState": playback_end["visibilityState"],
                    "activityStatusAfterWindow": playback_end["activity"][
                        "status"
                    ],
                    "browserVersion": browser_version,
                    "graphics": graphics,
                },
                "state": {
                    "operationCountBefore": len(before.get("operations") or []),
                    "operationCountAfterAuthoring": len(
                        setup["session"].get("operations") or []
                    ),
                    "operationCountAfterPlayback": len(
                        after_playback.get("operations") or []
                    ),
                    "operationCountAfterUndo": len(
                        after_undo.get("operations") or []
                    ),
                    "baseRevisionBefore": before.get("baseRevision"),
                    "baseRevisionAfterPlayback": after_playback.get(
                        "baseRevision"
                    ),
                    "navigationAfterUndo": (
                        after_undo.get("layout", {}).get("extensions", {}).get(
                            "facilityNavigation"
                        )
                    ),
                },
                "consoleErrors": console_errors,
                "pageErrors": page_errors,
                "failedResponses": failed_responses,
            }
    finally:
        current = _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}",
        )
        _http_json(
            base_url,
            f"/api/facility-layouts/{SITE_ID}/{scratch_id}/archive",
            method="POST",
            payload={"baseRevision": current["revision"]},
        )

    reference_after = _sha(ARCHIVE)
    evidence["referenceSha256After"] = reference_after
    evidence["checks"] = {
        "referenceUnchanged": reference_before == reference_after,
        "exactReferenceRevision": reference_after == REFERENCE_SHA256,
        "planAuthoringValidated": (
            evidence["authoring"]["applied"] is True
            and evidence["authoring"]["validationStatus"] == "validated"
        ),
        "navigationPipelineBuilt": (
            evidence["activity"]["plannerOutcome"] == "accepted"
            and evidence["activity"]["acceptedJourneyCount"] == 1
            and evidence["activity"]["actorCount"] == 1
            and evidence["activity"]["readOnlyPresentation"] is True
        ),
        "allPlanAnd3dCapturesPresent": len(captures) == 8,
        "allSurfacesNonblank": all(
            item["surfacePixels"]["nonblank"] for item in captures
        ),
        "allPlanAnd3dPosesAgree": all(
            item["poseAgreement"] for item in captures
        ),
        "exactCatalogVisualLoaded": all(
            item["exactVisualCount"] == item["actorCount"]
            for item in captures if "-3d" in item["fullScreenshot"]
        ),
        "motionPanelContained": all(
            item["panelWithinRoot"] for item in captures
        ),
        "mobilePropertiesInspectorHidden": all(
            item["propertiesVisible"] is False
            for item in captures
            if "-mobile-" in item["fullScreenshot"]
        ),
        "playbackAtLeast30Fps": (
            evidence["playback"]["framesPerSecond"] >= 30
        ),
        "playbackDidNotMutateDraft": (
            evidence["state"]["operationCountAfterPlayback"]
            == evidence["state"]["operationCountAfterAuthoring"]
            and evidence["state"]["baseRevisionAfterPlayback"]
            == evidence["state"]["baseRevisionBefore"]
        ),
        "exactUndoRestoredBase": (
            evidence["state"]["operationCountAfterUndo"] == 0
            and evidence["state"]["navigationAfterUndo"] is None
        ),
        "noBrowserErrors": not console_errors and not page_errors,
        "noFailedHttp": not failed_responses,
    }
    REPORT.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    failed = [name for name, passed in evidence["checks"].items() if not passed]
    if failed:
        raise AssertionError("NAV9 browser checks failed: " + ", ".join(failed))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    evidence = verify(args.url)
    print(json.dumps({
        "checks": evidence["checks"],
        "playback": evidence["playback"],
        "report": REPORT.relative_to(ROOT).as_posix(),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
