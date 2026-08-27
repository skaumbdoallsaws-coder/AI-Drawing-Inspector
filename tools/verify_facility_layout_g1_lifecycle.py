"""Verify G1 draft replacement across unsaved and concurrent Save states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g1-lifecycle-browser-evidence.json"
DEFAULT_SCREENSHOT = EVIDENCE_ROOT / "g1-lifecycle-browser.png"


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
    page.wait_for_function(
        """() => !!(
            _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
            && window.__facilityLayoutAgentV1
            && typeof window.__facilityLayoutAgentV1.generateDepartments
                === 'function'
        )""",
        timeout=120_000,
    )


def _request(width: float, depth: float, labels: list[str]) -> dict[str, Any]:
    return {
        "execution_mode": "authorized_draft_run",
        "facility_envelope": {
            "width": width,
            "depth": depth,
            "source_unit": "m",
            "display_name": "Main Facility Layout",
        },
        "departments": {
            "count": len(labels),
            "labels": labels,
            "proportions": [1 / len(labels)] * len(labels),
            "arrangement": "deterministic_grid",
            "orientation": "auto",
        },
    }


def _state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            const layout = state.layout || {};
            const plan = layout.extensions && layout.extensions.facilityPlan || {};
            return {
                runId: state.generatedDraft && state.generatedDraft.runId || null,
                status: state.generatedDraft && state.generatedDraft.status || null,
                widthMeters: plan.widthMeters,
                depthMeters: plan.depthMeters,
                labels: (layout.zones || []).map(zone => zone.label),
                baseLabels: (state.baseLayout.zones || []).map(zone => zone.label),
                dirty: state.dirty,
                busy: state.busy,
                canSave: state.canSave,
            };
        }"""
    )


def verify(app_url: str, output: Path, screenshot: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    labels_a = ["Receiving", "Machining", "Assembly", "Shipping"]
    labels_b = ["Stores", "Fabrication", "Build", "Quality"]
    labels_c = ["Inbound", "Cutting", "Welding", "Assembly", "Dispatch"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
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
                    "method": response.request.method,
                    "status": response.status,
                    "url": response.url,
                })

        page.on("response", observe_response)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        first_result = page.evaluate(
            """request => window.__facilityLayoutAgentV1.generateDepartments(
                request, 'deviation-analyst'
            )""",
            _request(100, 80, labels_a),
        )
        first = _state(page)
        second_result = page.evaluate(
            """request => window.__facilityLayoutAgentV1.generateDepartments(
                request, 'deviation-analyst'
            )""",
            _request(100, 100, labels_b),
        )
        second = _state(page)
        concurrent = page.evaluate(
            """async request => {
                const save = _trainFacilityLayoutAuthoringApp.workspace
                    .executeCommand('save');
                const generation = window.__facilityLayoutAgentV1
                    .generateDepartments(
                    request, 'deviation-analyst'
                );
                const values = await Promise.all([save, generation]);
                return { generation: values[1] };
            }""",
            _request(120, 90, labels_c),
        )
        third = _state(page)
        page.screenshot(path=str(screenshot), full_page=False)
        page.evaluate(
            """() => _trainFacilityLayoutAuthoringApp.workspace
                .executeCommand('undo')"""
        )
        restored = _state(page)
        browser.close()

    checks = {
        "first_completed": first_result.get("ok") is True
        and first["status"] == "complete" and first["canSave"] is True,
        "unsaved_followup_superseded": second_result.get("ok") is True
        and second_result.get("supersededRunId") == first["runId"]
        and second["runId"] != first["runId"],
        "different_dimensions_and_labels_recompiled": second == {
            **second,
            "widthMeters": 100,
            "depthMeters": 100,
            "labels": labels_b,
        },
        "concurrent_save_and_generation_completed": (
            concurrent["generation"].get("ok") is True
            and third["status"] == "complete"
            and third["canSave"] is True
            and third["busy"] is False
        ),
        "brownfield_request_is_dynamic": (
            third["widthMeters"] == 120
            and third["depthMeters"] == 90
            and third["labels"] == labels_c
            and third["baseLabels"] == labels_b
        ),
        "undo_restored_saved_base": (
            restored["widthMeters"] == 100
            and restored["depthMeters"] == 100
            and restored["labels"] == labels_b
            and restored["dirty"] is False
        ),
        "no_session_busy": all(
            result.get("error") != "session_busy"
            for result in (first_result, second_result, concurrent["generation"])
        ),
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g1-lifecycle-browser-evidence-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "results": {
            "first": first_result,
            "second": second_result,
            "concurrent": concurrent,
        },
        "states": {
            "first": first,
            "second": second,
            "third": third,
            "restored": restored,
        },
        "errors": {
            "console": console_errors,
            "page": page_errors,
            "failedResponses": failed_responses,
        },
        "screenshot": screenshot.relative_to(ROOT).as_posix(),
    }
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8141/")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--screenshot", type=Path, default=DEFAULT_SCREENSHOT)
    args = parser.parse_args()
    evidence = verify(args.url, args.output, args.screenshot)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
