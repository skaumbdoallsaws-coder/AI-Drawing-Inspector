"""Verify staged G1 Facility generation through the production browser tool path."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "knowledge_foundation"
)
DEFAULT_RESULT = EVIDENCE / "g1-browser-evidence.json"
SCREENSHOTS = {
    "envelope_light": EVIDENCE / "g1-envelope-light.png",
    "departments_light": EVIDENCE / "g1-departments-light.png",
    "plan_light": EVIDENCE / "g1-plan-light.png",
    "three_light": EVIDENCE / "g1-three-light.png",
    "plan_dark": EVIDENCE / "g1-plan-dark.png",
    "three_dark": EVIDENCE / "g1-three-dark.png",
    "undo_empty": EVIDENCE / "g1-undo-empty.png",
    "saved_reload": EVIDENCE / "g1-saved-reload.png",
}
EXPECTED_STAGES = [
    "facility_envelope",
    "macro_departments",
    "primary_circulation",
    "department_subdivisions",
    "department_resources",
    "seed_cells",
    "repeated_modules",
    "floor_communication",
    "deterministic_validation",
    "review_and_save",
]
EXPECTED_LABELS = [
    "Receiving and Stores",
    "Machining",
    "Assembly",
    "Inspection and Shipping",
]


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
            window.__compareDbg
            && typeof window.__compareDbg.executeAgentTool === 'function'
            && typeof _trainFacilityLayoutAuthoringApp !== 'undefined'
            && _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=120_000,
    )


def _set_theme(page: Any, theme: str) -> None:
    page.evaluate(
        """theme => {
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('inspectorp-theme', theme);
            window.dispatchEvent(new CustomEvent(
                'inspectorp-theme-change', { detail: { theme } }
            ));
        }""",
        theme,
    )
    page.wait_for_timeout(250)


def _capture(page: Any, name: str) -> None:
    page.screenshot(path=str(SCREENSHOTS[name]), full_page=False)


def _start_generation(page: Any, *, delay_ms: int) -> dict[str, Any]:
    return page.evaluate(
        """delayMs => {
            const app = _trainFacilityLayoutAuthoringApp;
            window.__facilityGenerationEvents = [];
            window.__facilityGenerationStageDelayMs = delayMs;
            const before = app.session.getState();
            window.__g1BrowserToolPromise = window.__compareDbg.executeAgentTool({
                name: 'generate_facility_departments_draft',
                args: {
                    facility_envelope: {
                        width: 100,
                        depth: 80,
                        source_unit: 'm',
                        display_name: 'G1 Stakeholder Factory',
                        grid_size: 1
                    },
                    departments: {
                        count: 4,
                        labels: [
                            'Receiving and Stores',
                            'Machining',
                            'Assembly',
                            'Inspection and Shipping'
                        ],
                        proportions: [1, 1, 1, 1],
                        arrangement: 'deterministic_grid',
                        orientation: 'horizontal'
                    },
                    execution_mode: 'authorized_draft_run'
                }
            }, 'deviation-analyst');
            return {
                before,
                attachment: window.__facilityLayoutAgentV1
                    .getAttachment('deviation-analyst')
            };
        }""",
        delay_ms,
    )


def _await_generation(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
            const result = await window.__g1BrowserToolPromise;
            const app = _trainFacilityLayoutAuthoringApp;
            await app.workspace.controller.ready();
            return {
                result,
                events: JSON.parse(JSON.stringify(
                    window.__facilityGenerationEvents || []
                )),
                state: app.session.getState(),
                server: await app.transport.reloadLayout()
            };
        }"""
    )


def _layout_empty(layout: dict[str, Any]) -> bool:
    return all(
        not layout.get(field)
        for field in ("zones", "routes", "placements", "floorMarkings")
    )


def _same_saved_content(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    left_content = dict(left)
    right_content = dict(right)
    for field in ("createdAt", "updatedAt"):
        left_content.pop(field, None)
        right_content.pop(field, None)
    return left_content == right_content


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
        _set_theme(page, "light")

        first_start = _start_generation(page, delay_ms=500)
        page.wait_for_function(
            """() => (window.__facilityGenerationEvents || []).some(
                event => event.completedStageId === 'facility_envelope'
            )""",
            timeout=120_000,
        )
        _capture(page, "envelope_light")
        page.wait_for_function(
            """() => (window.__facilityGenerationEvents || []).some(
                event => event.completedStageId === 'macro_departments'
            )""",
            timeout=120_000,
        )
        _capture(page, "departments_light")
        first = _await_generation(page)

        root = page.locator("#trainFacilityLayoutAuthoring")
        root.locator('[data-view="plan"]').click()
        page.wait_for_timeout(350)
        _capture(page, "plan_light")
        root.locator('[data-view="3d"]').click()
        page.wait_for_timeout(900)
        _capture(page, "three_light")
        root.locator('[data-view="plan"]').click()
        _set_theme(page, "dark")
        _capture(page, "plan_dark")
        root.locator('[data-view="3d"]').click()
        page.wait_for_timeout(650)
        _capture(page, "three_dark")
        root.locator('[data-view="plan"]').click()

        undo = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const result = await app.workspace.executeCommand('undo');
                await app.workspace.controller.ready();
                return {
                    result,
                    state: app.session.getState(),
                    server: await app.transport.reloadLayout()
                };
            }"""
        )
        _capture(page, "undo_empty")

        _set_theme(page, "light")
        second_start = _start_generation(page, delay_ms=0)
        second = _await_generation(page)
        save = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                const result = await app.workspace.executeCommand('save');
                await app.workspace.controller.ready();
                return {
                    result,
                    state: app.session.getState(),
                    server: await app.transport.reloadLayout()
                };
            }"""
        )

        page.reload(wait_until="load", timeout=120_000)
        _open_facility(page)
        reloaded = page.evaluate(
            """async () => {
                const app = _trainFacilityLayoutAuthoringApp;
                await app.workspace.controller.ready();
                return {
                    state: app.session.getState(),
                    server: await app.transport.reloadLayout()
                };
            }"""
        )
        _capture(page, "saved_reload")
        browser.close()

    first_layout = first["state"]["layout"]
    first_plan = first_layout["extensions"]["facilityPlan"]
    first_labels = [zone["label"] for zone in first_layout["zones"]]
    first_stages = [
        event["completedStageId"]
        for event in first["events"]
        if event["completedStageId"] != "run_started"
    ]
    second_stages = [
        event["completedStageId"]
        for event in second["events"]
        if event["completedStageId"] != "run_started"
    ]
    saved_layout = save["server"]["layout"]
    reloaded_layout = reloaded["state"]["layout"]
    checks = {
        "production_tool_dispatch_succeeded": (
            first["result"].get("ok") is True
            and first["result"].get("name")
            == "generate_facility_departments_draft"
        ),
        "started_from_empty_layout": _layout_empty(
            first_start["before"]["layout"]
        ),
        "exact_stage_order": first_stages == EXPECTED_STAGES,
        "ten_revision_bound_receipts": (
            first["result"].get("completedStageCount") == 10
            and first["result"].get("receiptCount") == 10
            and len(first["state"]["generatedDraft"]["receiptChain"]) == 10
        ),
        "exact_facility_dimensions": (
            first_plan["widthMeters"] == 100
            and first_plan["depthMeters"] == 80
        ),
        "exact_department_labels": first_labels == EXPECTED_LABELS,
        "g1_scope_remains_bounded": (
            first_layout["routes"] == []
            and first_layout["placements"] == []
            and first_layout["floorMarkings"] == []
        ),
        "review_draft_is_unsaved_and_actionable": (
            first["state"]["dirty"] is True
            and first["state"]["canSave"] is True
            and first["state"]["canUndo"] is True
            and first["state"]["generatedDraft"]["prototypeMode"] is True
            and first["state"]["generatedDraft"]["saveEligibility"]
            == "eligible"
        ),
        "saved_layout_untouched_before_approval": (
            first["server"]["revision"]
            == first_start["before"]["baseRevision"]
            and first["server"]["layout"]
            == first_start["before"]["baseLayout"]
        ),
        "undo_restores_exact_empty_base": (
            undo["state"]["layout"] == first_start["before"]["baseLayout"]
            and undo["state"]["dirty"] is False
            and undo["state"]["generatedDraft"] is None
            and undo["server"]["layout"]
            == first_start["before"]["baseLayout"]
        ),
        "second_run_is_deterministic": (
            second["result"].get("ok") is True
            and second_stages == EXPECTED_STAGES
            and second["state"]["layout"] == first_layout
        ),
        "explicit_save_persists_exact_draft": (
            save["state"]["dirty"] is False
            and save["state"]["generatedDraft"] is None
            and _same_saved_content(
                saved_layout,
                second["state"]["layout"],
            )
            and save["server"]["revision"]
            != second_start["before"]["baseRevision"]
        ),
        "reload_preserves_saved_geometry": (
            reloaded_layout == saved_layout
            and [zone["label"] for zone in reloaded_layout["zones"]]
            == EXPECTED_LABELS
        ),
        "all_screenshots_nonblank": all(
            _image(path)["nonblank"] for path in SCREENSHOTS.values()
        ),
        "no_page_errors": not page_errors,
        "no_console_errors": not console_errors,
        "no_failed_responses": not failed_responses,
    }
    result = {
        "schemaVersion": "facility-layout-g1-browser-evidence-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "errors": {"console": console_errors, "page": page_errors},
        "network": {"failedResponses": failed_responses},
        "generation": {
            "tool": "generate_facility_departments_draft",
            "executionMode": "authorized_draft_run",
            "prototypeMode": True,
            "stages": first_stages,
            "receiptCount": first["result"].get("receiptCount"),
            "facility": {"widthMeters": 100, "depthMeters": 80},
            "departmentLabels": first_labels,
            "firstRunId": first["result"].get("runId"),
            "secondRunId": second["result"].get("runId"),
            "cumulativeDiffHash": second["result"].get(
                "cumulativeDiffHash"
            ),
            "savedRevision": save["server"]["revision"],
        },
        "screenshots": {
            name: _image(path) for name, path in SCREENSHOTS.items()
        },
        "source": {
            "coordinatorSha256": _sha256(
                ROOT
                / "ai_inspector"
                / "facility_layout"
                / "generation_coordinator.py"
            ),
            "runRepositorySha256": _sha256(
                ROOT
                / "ai_inspector"
                / "facility_layout"
                / "generation_run_repository.py"
            ),
            "hostSha256": _sha256(
                ROOT / "ai_inspector" / "facility_layout" / "host.py"
            ),
            "indexSha256": _sha256(ROOT / "static" / "index.html"),
            "sessionSha256": _sha256(
                ROOT / "static" / "facility_layout_session.js"
            ),
            "verifierSha256": _sha256(Path(__file__)),
        },
    }
    output.write_text(
        json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    for name, passed in checks.items():
        print(("PASS" if passed else "FAIL") + "\t" + name)
    print("RESULT\t" + str(output))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://127.0.0.1:8141/")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()
    result = verify(args.app_url, args.output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
