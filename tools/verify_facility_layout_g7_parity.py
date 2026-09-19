"""Capture source-bound G7 Plan/3D and light/dark parity evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from urllib.request import urlopen

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_facility_knowledge_bytes,
)
from verify_facility_layout_g2_circulation import _open_facility


EVIDENCE_ROOT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "production_hardening"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "fli030-parity-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "fli030-parity"
VIEWPORTS = ((1440, 960), (390, 844))
THEMES = ("light", "dark")
VIEWS = ("plan", "3d")
SOURCE_PATHS = (
    "static/index.html",
    "static/facility_layout_editor.js",
    "static/facility_layout_session.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_transport.js",
    "static/facility_layout_workspace.css",
    "static/facility_layout_workspace.js",
    "tools/verify_facility_layout_g7_parity.py",
)


PROGRAM = {
    "facility_envelope": {
        "width": 120,
        "depth": 90,
        "source_unit": "m",
        "display_name": "G7 Parity Factory",
        "grid_size": 1,
    },
    "departments": {
        "count": 9,
        "labels": [
            "North West",
            "North Center",
            "North East",
            "Inbound",
            "Restricted Area",
            "Dispatch",
            "South West",
            "South Center",
            "South East",
        ],
        "proportions": None,
        "arrangement": "row_stack",
        "orientation": "horizontal",
        "rows": [
            {
                "labels": ["North West", "North Center", "North East"],
                "proportion": None,
            },
            {
                "labels": ["Inbound", "Restricted Area", "Dispatch"],
                "proportion": None,
            },
            {
                "labels": ["South West", "South Center", "South East"],
                "proportion": None,
            },
        ],
    },
    "circulation": {
        "routes": [
            {
                "route_kind": "material",
                "width": 4,
                "source_unit": "m",
                "source_department": "Inbound",
                "target_department": "Dispatch",
                "via_departments": [],
                "direction": "two_way",
                "label": "Inbound to Dispatch material aisle",
            },
            {
                "route_kind": "pedestrian",
                "width": 2,
                "source_unit": "m",
                "source_department": "North Center",
                "target_department": "South Center",
                "via_departments": [],
                "direction": "two_way",
                "label": "North to South pedestrian aisle",
            },
        ],
        "crossings": [
            {
                "route_labels": [
                    "Inbound to Dispatch material aisle",
                    "North to South pedestrian aisle",
                ],
                "width": 4,
                "depth": 3,
                "source_unit": "m",
                "label": "Central pedestrian crossing",
            }
        ],
    },
    "subdivisions": [
        {
            "parent_department": "South East",
            "count": 3,
            "labels": ["Kitting", "Electrical Build", "Test"],
            "proportions": None,
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [
                {
                    "labels": ["Kitting", "Electrical Build", "Test"],
                    "proportion": None,
                }
            ],
        }
    ],
    "asset_placements": [
        {
            "asset_name": "Assembly Workbench",
            "quantity": 2,
            "target_area": "Electrical Build",
            "orientation_mode": "long_side_east_west",
            "facing_direction": None,
            "resource_role": "production",
            "access_requirement": "physical_only",
        }
    ],
    "seed_cell": {
        "target_area": "Electrical Build",
        "candidate_strategies": ["line", "l", "u"],
        "selected_strategy": None,
        "objective": "smallest_envelope",
        "preferred_gap_meters": 1,
        "invert_u": False,
    },
    "cell_replication": {
        "source_cell": "Electrical Build",
        "target_areas": ["Kitting", "Test"],
        "copy_current_edited_state": False,
    },
    "execution_mode": "authorized_draft_run",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _revision(value: Any) -> str:
    return _sha256_bytes(canonical_facility_knowledge_bytes(value))


def _source_binding() -> dict[str, Any]:
    records = []
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        records.append(
            {
                "path": relative,
                "byteLength": path.stat().st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
        )
    return {
        "files": records,
        "aggregateSha256": _revision(records),
    }


def _pixel_metrics(payload: bytes) -> dict[str, Any]:
    with Image.open(BytesIO(payload)) as source:
        image = source.convert("RGB")
        width, height = image.size
        pixels = list(image.getdata())
    corners = (
        pixels[0],
        pixels[width - 1],
        pixels[(height - 1) * width],
        pixels[-1],
    )
    background = Counter(corners).most_common(1)[0][0]
    changed = 0
    maximum_delta = 0
    for red, green, blue in pixels:
        delta = (
            abs(red - background[0])
            + abs(green - background[1])
            + abs(blue - background[2])
        )
        maximum_delta = max(maximum_delta, delta)
        if delta > 24:
            changed += 1
    return {
        "width": width,
        "height": height,
        "backgroundRgb": list(background),
        "changedPixelCount": changed,
        "changedPixelFraction": round(changed / max(1, width * height), 8),
        "maximumDelta": maximum_delta,
        "nonblank": changed >= 1000 and maximum_delta >= 40,
    }


def _saved_bootstrap(app_url: str) -> dict[str, Any]:
    with urlopen(
        app_url.rstrip("/") + "/api/facility-layout-bootstrap", timeout=30
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_unsaved_factory(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """async program => {
            const app = window._trainFacilityLayoutAuthoringApp;
            let state = app.session.getState();
            if (state.generatedDraft) {
                await app.session.undo();
            } else if (state.dirty) {
                app.session.discard();
            }
            let run = await app.transport.startFullFactoryGeneration({
                prototypeMode: true,
                supersedeActiveDraft: true,
                workspaceId: 'workspace-facility-layout',
                fullFactory: program,
            });
            let transitions = 0;
            while (run.currentStageId && transitions < 128) {
                run = await app.transport.continueGenerationRun({
                    runId: run.runId,
                    explicitStageAcceptance: false,
                });
                transitions += 1;
                if (run.draftLayout) {
                    app.session.installGenerationDraft(run);
                }
            }
            await app.workspace.executeCommand('fit');
            await app.workspace.whenIdle();
            return { run, transitions, state: app.session.getState() };
        }""",
        PROGRAM,
    )


def _capture_state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const state = app.session.getState();
            const root = document.querySelector('#trainFacilityLayoutAuthoring');
            const viewport = root.querySelector('.ip-flw-viewport-pane');
            const canvas = root.querySelector('#ip-flw-three-view canvas');
            const plan = root.querySelector(
                'svg[data-facility-layout-view="top-plan"]'
            );
            const rect = value => value ? (() => {
                const box = value.getBoundingClientRect();
                return {
                    x: box.x, y: box.y, width: box.width, height: box.height,
                    right: box.right, bottom: box.bottom,
                };
            })() : null;
            return {
                theme: window.getInspectorProTheme(),
                viewMode: app.workspace.viewMode,
                layout: state.layout,
                dirty: state.dirty,
                generatedDraft: state.generatedDraft,
                topDiagnostics: app.workspace.topAdapter.getDiagnostics(),
                threeDiagnostics: app.workspace.threeAdapter.getDiagnostics(),
                rootRect: rect(root),
                viewportRect: rect(viewport),
                planRect: rect(plan),
                canvasRect: rect(canvas),
            };
        }"""
    )


def verify(app_url: str, output: Path, screenshot_root: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    source_before = _source_binding()
    bootstrap_before = _saved_bootstrap(app_url)
    saved_before = bootstrap_before["layout"]
    if any(
        saved_before["layout"].get(key)
        for key in ("zones", "routes", "floorMarkings", "placements")
    ):
        raise RuntimeError("G7 parity proof requires the saved blank baseline.")

    records = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    interaction = {"attempted": False, "cameraChanged": False}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORTS[0][0], "height": VIEWPORTS[0][1]},
            device_scale_factor=1,
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

        def observe(response: Any) -> None:
            if response.status >= 400 and not response.url.endswith(
                "/static/manifest.json"
            ):
                failed_responses.append(
                    {
                        "method": response.request.method,
                        "status": response.status,
                        "url": response.url,
                    }
                )

        page.on("response", observe)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        built = _build_unsaved_factory(page)
        if (
            built["run"].get("status") != "complete"
            or built["run"].get("currentStageId") is not None
        ):
            raise RuntimeError(f"G7 factory generation did not complete: {built['run']}")
        expected_layout = built["state"]["layout"]
        expected_revision = _revision(expected_layout)
        expected_ids = {
            "zones": sorted(item["zoneId"] for item in expected_layout["zones"]),
            "routes": sorted(item["routeId"] for item in expected_layout["routes"]),
            "markings": sorted(
                item["markingId"] for item in expected_layout["floorMarkings"]
            ),
            "placements": sorted(
                item["placementId"] for item in expected_layout["placements"]
            ),
        }

        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            for theme in THEMES:
                page.evaluate("theme => window.setInspectorProTheme(theme)", theme)
                for view in VIEWS:
                    root = page.locator("#trainFacilityLayoutAuthoring")
                    root.locator(f'[data-view="{view}"]').click()
                    page.wait_for_function(
                        "view => window._trainFacilityLayoutAuthoringApp.workspace.viewMode === view",
                        arg=view,
                        timeout=30_000,
                    )
                    page.evaluate(
                        """async () => {
                            const app = window._trainFacilityLayoutAuthoringApp;
                            await app.workspace.executeCommand('fit');
                            await app.workspace.whenIdle();
                        }"""
                    )
                    if view == "3d":
                        page.wait_for_function(
                            """() => {
                                const value = window._trainFacilityLayoutAuthoringApp
                                    .workspace.threeAdapter.getDiagnostics();
                                return value.status === 'ready'
                                    && value.pendingLoads === 0
                                    && value.placementTransformAudit.status === 'match';
                            }""",
                            timeout=120_000,
                        )
                    page.wait_for_timeout(300)
                    state = _capture_state(page)
                    surface = (
                        root.locator("#ip-flw-three-view canvas")
                        if view == "3d"
                        else root.locator(
                            'svg[data-facility-layout-view="top-plan"]'
                        )
                    )
                    surface_png = surface.screenshot()
                    surface_metrics = _pixel_metrics(surface_png)
                    name = f"{width}x{height}-{theme}-{view}"
                    full_path = screenshot_root / f"{name}.png"
                    page.screenshot(path=str(full_path), full_page=False)
                    full_payload = full_path.read_bytes()
                    current_ids = {
                        "zones": sorted(
                            item["zoneId"] for item in state["layout"]["zones"]
                        ),
                        "routes": sorted(
                            item["routeId"] for item in state["layout"]["routes"]
                        ),
                        "markings": sorted(
                            item["markingId"]
                            for item in state["layout"]["floorMarkings"]
                        ),
                        "placements": sorted(
                            item["placementId"]
                            for item in state["layout"]["placements"]
                        ),
                    }
                    active_rect = (
                        state["canvasRect"] if view == "3d" else state["planRect"]
                    )
                    viewport_rect = state["viewportRect"]
                    checks = {
                        "themeApplied": state["theme"] == theme,
                        "viewApplied": state["viewMode"] == view,
                        "layoutRevisionStable": (
                            _revision(state["layout"]) == expected_revision
                        ),
                        "entityIdsStable": current_ids == expected_ids,
                        "dirtyUnsavedDraft": (
                            state["dirty"] is True
                            and state["generatedDraft"]["status"] == "complete"
                        ),
                        "planRepresentationMatches": (
                            state["topDiagnostics"]["placementTransformAudit"][
                                "status"
                            ]
                            == "match"
                        ),
                        "threeRepresentationMatches": (
                            state["threeDiagnostics"]["placementTransformAudit"][
                                "status"
                            ]
                            == "match"
                        ),
                        "threeSceneCountsMatch": (
                            state["threeDiagnostics"]["placementCount"]
                            == len(expected_ids["placements"])
                            and state["threeDiagnostics"]["routeCount"]
                            == len(expected_ids["routes"])
                            and state["threeDiagnostics"]["floorMarkingCount"]
                            == len(expected_ids["markings"])
                        ),
                        "surfaceIsVisibleAndContained": bool(
                            active_rect
                            and viewport_rect
                            and active_rect["width"] >= 250
                            and active_rect["height"] >= 180
                            and active_rect["x"] + 1 >= viewport_rect["x"]
                            and active_rect["y"] + 1 >= viewport_rect["y"]
                            and active_rect["right"]
                            <= viewport_rect["right"] + 1
                            and active_rect["bottom"]
                            <= viewport_rect["bottom"] + 1
                        ),
                        "surfacePixelsNonblank": surface_metrics["nonblank"],
                    }
                    records.append(
                        {
                            "name": name,
                            "viewport": {"width": width, "height": height},
                            "theme": theme,
                            "view": view,
                            "layoutRevision": _revision(state["layout"]),
                            "entityIds": current_ids,
                            "surfacePixels": surface_metrics,
                            "surfaceSha256": _sha256_bytes(surface_png),
                            "screenshot": {
                                "path": full_path.relative_to(ROOT).as_posix(),
                                "sha256": _sha256_bytes(full_payload),
                                "byteLength": len(full_payload),
                            },
                            "diagnostics": {
                                "topPlan": state["topDiagnostics"],
                                "three": state["threeDiagnostics"],
                            },
                            "checks": checks,
                            "passed": all(checks.values()),
                        }
                    )

                    if (
                        view == "3d"
                        and width == VIEWPORTS[0][0]
                        and theme == "light"
                        and not interaction["attempted"]
                    ):
                        interaction["attempted"] = True
                        before_camera = state["threeDiagnostics"]["camera"]
                        box = surface.bounding_box()
                        if box:
                            page.mouse.move(
                                box["x"] + box["width"] * 0.5,
                                box["y"] + box["height"] * 0.5,
                            )
                            page.mouse.down()
                            page.mouse.move(
                                box["x"] + box["width"] * 0.65,
                                box["y"] + box["height"] * 0.45,
                                steps=8,
                            )
                            page.mouse.up()
                            page.wait_for_timeout(300)
                            after_camera = _capture_state(page)[
                                "threeDiagnostics"
                            ]["camera"]
                            interaction["cameraChanged"] = (
                                before_camera != after_camera
                            )
                            page.evaluate(
                                """async () => {
                                    const app = window._trainFacilityLayoutAuthoringApp;
                                    await app.workspace.executeCommand('fit');
                                    await app.workspace.whenIdle();
                                }"""
                            )

        theme_hashes = {
            (record["viewport"]["width"], record["view"]): set()
            for record in records
        }
        for record in records:
            theme_hashes[(record["viewport"]["width"], record["view"])].add(
                record["surfaceSha256"]
            )
        theme_repainted = all(len(values) == 2 for values in theme_hashes.values())
        undo = page.evaluate(
            """async () => {
                const app = window._trainFacilityLayoutAuthoringApp;
                await app.session.undo();
                await app.workspace.whenIdle();
                return app.session.getState();
            }"""
        )
        context.close()
        browser.close()

    bootstrap_after = _saved_bootstrap(app_url)
    saved_after = bootstrap_after["layout"]
    source_after = _source_binding()
    checks = {
        "eightParitySurfacesCaptured": len(records) == 8,
        "allSurfaceChecksPassed": all(record["passed"] for record in records),
        "oneExactWorldRevision": (
            {record["layoutRevision"] for record in records}
            == {expected_revision}
        ),
        "themeRepaintedEverySurface": theme_repainted,
        "threeCameraInteractionWorked": all(interaction.values()),
        "savedLayoutUnchanged": saved_after == saved_before,
        "undoRestoredExactBlankBase": (
            undo["dirty"] is False
            and undo["generatedDraft"] is None
            and undo["layout"] == undo["baseLayout"] == saved_before["layout"]
        ),
        "sourceStableDuringCapture": source_before == source_after,
        "noPageErrors": not page_errors,
        "noConsoleErrors": not console_errors,
        "noFailedResponses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-fli030-parity-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "sourceBinding": source_before,
        "baseRevision": saved_before["revision"],
        "draftRevision": expected_revision,
        "run": {
            "runId": built["run"]["runId"],
            "status": built["run"]["status"],
            "transitionCount": built["transitions"],
            "receiptCount": len(built["run"].get("receiptChain") or []),
        },
        "entityIds": expected_ids,
        "interaction": interaction,
        "records": records,
        "errors": {
            "page": page_errors,
            "console": console_errors,
            "responses": failed_responses,
        },
    }
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8141/")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--screenshot-root", type=Path, default=DEFAULT_SCREENSHOT_ROOT
    )
    args = parser.parse_args()
    evidence = verify(
        args.url,
        args.output.resolve(),
        args.screenshot_root.resolve(),
    )
    for record in evidence["records"]:
        print(("PASS" if record["passed"] else "FAIL") + "\t" + record["name"])
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
