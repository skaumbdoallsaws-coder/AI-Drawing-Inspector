"""Verify G3 nested department subdivisions through visible Sage chat."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g3-subdivision-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g3-subdivision-browser"

FACILITY_PROMPT = (
    "Create a new 120 m by 80 m facility with four equal departments named "
    "Receiving, Machining, Assembly, and Shipping. Arrange them in two rows: "
    "Receiving and Machining in row 1; Assembly and Shipping in row 2."
)
SUBDIVISION_PROMPT = (
    "Divide Assembly into four equal child areas named Kitting, Mechanical Build, "
    "Electrical Build, and Test. Arrange them in two rows: Kitting and Mechanical "
    "Build in row 1; Electrical Build and Test in row 2."
)
MACRO_LABELS = ["Receiving", "Machining", "Assembly", "Shipping"]
CHILD_LABELS = ["Kitting", "Mechanical Build", "Electrical Build", "Test"]


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
            && window.__facilityLayoutAgentV1
            && typeof window.__facilityLayoutAgentV1.generateSubdivision
                === 'function'
        )""",
        timeout=120_000,
    )


def _send(page: Any, prompt: str) -> None:
    page.locator("#agentInput").fill(prompt)
    page.locator("#agentSendBtn").click()


def _wait_chat_idle(page: Any, prior_text: str) -> str:
    page.wait_for_function(
        """prior => {
            const session = typeof getCurrentAgentSession === 'function'
                ? getCurrentAgentSession() : null;
            const messages = document.getElementById('agentMessages');
            const send = document.getElementById('agentSendBtn');
            const text = messages ? messages.innerText : '';
            return text !== prior
                && send
                && send.getAttribute('aria-label') === 'Send message'
                && document.querySelectorAll(
                    '#agentMessages .agent-stream-pending'
                ).length === 0
                && (!session || (
                    session.waiting !== true
                    && !session.activeStream
                ));
        }""",
        arg=prior_text,
        timeout=360_000,
    )
    page.wait_for_timeout(500)
    return page.locator("#agentMessages").inner_text()


def _state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            const layout = state.layout || {};
            return {
                baseRevision: state.baseRevision,
                dirty: state.dirty,
                canSave: state.canSave,
                generatedDraft: state.generatedDraft,
                layout,
                baseLayout: state.baseLayout,
                messages: document.getElementById('agentMessages').innerText,
            };
        }"""
    )


def _bounds(zone: dict[str, Any]) -> tuple[float, float, float, float]:
    points = zone["boundary"]
    xs = [float(point["x"]) for point in points]
    zs = [float(point["z"]) for point in points]
    return min(xs), min(zs), max(xs), max(zs)


def _area(zone: dict[str, Any]) -> float:
    x0, z0, x1, z1 = _bounds(zone)
    return (x1 - x0) * (z1 - z0)


def _parent_id(zone: dict[str, Any]) -> str | None:
    return (
        ((zone.get("extensions") or {}).get("knowledgeFoundation") or {}).get(
            "parentZoneId"
        )
    )


def _rectangles_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > 1e-9
        and min(left[3], right[3]) - max(left[1], right[1]) > 1e-9
    )


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "departments": screenshot_root / "01-macro-departments.png",
        "subdivision": screenshot_root / "02-assembly-subdivided.png",
    }
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []

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

        def observe_response(response: Any) -> None:
            if "/api/agent/chat/v2/stream" in response.url:
                stream_statuses.append(response.status)
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

        page.on("response", observe_response)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)

        initial = _state(page)
        prior = initial["messages"]
        _send(page, FACILITY_PROMPT)
        page.wait_for_function(
            """labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const layout = state.layout || {};
                const plan = layout.extensions
                    && layout.extensions.facilityPlan || {};
                const actual = (layout.zones || []).map(zone => zone.label);
                return state.dirty === true
                    && state.canSave === true
                    && state.generatedDraft
                    && state.generatedDraft.status === 'complete'
                    && Number(plan.widthMeters) === 120
                    && Number(plan.depthMeters) === 80
                    && actual.length === labels.length
                    && labels.every(label => actual.includes(label));
            }""",
            arg=MACRO_LABELS,
            timeout=360_000,
        )
        macro_messages = _wait_chat_idle(page, prior)
        macro = _state(page)
        page.screenshot(path=str(screenshots["departments"]), full_page=False)

        macro_by_label = {
            zone["label"]: deepcopy(zone) for zone in macro["layout"]["zones"]
        }
        prior = macro_messages
        _send(page, SUBDIVISION_PROMPT)
        page.wait_for_function(
            """labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const zones = state.layout && state.layout.zones || [];
                const actual = zones.map(zone => zone.label);
                return state.dirty === true
                    && state.canSave === true
                    && state.generatedDraft
                    && state.generatedDraft.status === 'complete'
                    && zones.length === 8
                    && labels.every(label => actual.includes(label));
            }""",
            arg=CHILD_LABELS,
            timeout=360_000,
        )
        subdivision_messages = _wait_chat_idle(page, prior)
        subdivided = _state(page)
        page.screenshot(path=str(screenshots["subdivision"]), full_page=False)

        restored = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('undo');
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    baseRevision: state.baseRevision,
                    dirty: state.dirty,
                    layout: state.layout,
                    baseLayout: state.baseLayout,
                    generatedDraft: state.generatedDraft,
                };
            }"""
        )
        browser.close()

    zones = subdivided["layout"]["zones"]
    zones_by_label = {zone["label"]: zone for zone in zones}
    assembly = zones_by_label["Assembly"]
    children = [zones_by_label[label] for label in CHILD_LABELS]
    assembly_bounds = _bounds(assembly)
    children_inside = all(
        _bounds(child)[0] >= assembly_bounds[0] - 1e-9
        and _bounds(child)[1] >= assembly_bounds[1] - 1e-9
        and _bounds(child)[2] <= assembly_bounds[2] + 1e-9
        and _bounds(child)[3] <= assembly_bounds[3] + 1e-9
        for child in children
    )
    no_child_overlap = not any(
        _rectangles_overlap(_bounds(children[left]), _bounds(children[right]))
        for left in range(len(children))
        for right in range(left + 1, len(children))
    )
    child_areas = [_area(child) for child in children]
    messages = subdivided["messages"]
    checks = {
        "two_streams_completed": stream_statuses == [200, 200],
        "no_interruption_message": "Response interrupted" not in messages,
        "exact_macro_departments": [
            zone["label"] for zone in macro["layout"]["zones"]
        ] == MACRO_LABELS,
        "same_generation_run": (
            macro["generatedDraft"]["runId"]
            == subdivided["generatedDraft"]["runId"]
        ),
        "macro_parent_and_unrelated_zones_unchanged": all(
            zones_by_label[label] == macro_by_label[label] for label in MACRO_LABELS
        ),
        "exact_child_labels": [child["label"] for child in children] == CHILD_LABELS,
        "children_bound_to_assembly": all(
            _parent_id(child) == assembly["zoneId"] for child in children
        ),
        "children_inside_parent": children_inside,
        "children_do_not_overlap": no_child_overlap,
        "children_cover_parent_exactly": abs(sum(child_areas) - _area(assembly)) < 1e-9,
        "children_are_equal_area": max(child_areas) - min(child_areas) < 1e-9,
        "review_draft_is_unsaved": (
            subdivided["dirty"] is True
            and subdivided["canSave"] is True
            and subdivided["baseRevision"] == initial["baseRevision"]
            and subdivided["baseLayout"] == initial["baseLayout"]
        ),
        "sage_reported_preservation_and_validation": (
            "parent department and unrelated layout geometry were preserved"
            in messages
            and "Validation returned valid" in messages
        ),
        "single_undo_restored_exact_saved_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
        ),
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g3-subdivision-browser-evidence-v1",
        "passed": all(checks.values()),
        "prompts": [FACILITY_PROMPT, SUBDIVISION_PROMPT],
        "checks": checks,
        "streamStatuses": stream_statuses,
        "result": {
            "runId": subdivided["generatedDraft"]["runId"],
            "macroLabels": MACRO_LABELS,
            "parentZoneId": assembly["zoneId"],
            "parentAreaSquareMeters": _area(assembly),
            "childLabels": CHILD_LABELS,
            "childAreasSquareMeters": child_areas,
            "draftRevision": subdivided["generatedDraft"]["draftLayoutRevision"],
            "savedBaseRevision": initial["baseRevision"],
        },
        "responseText": messages,
        "errors": {
            "console": console_errors,
            "page": page_errors,
            "failedResponses": failed_responses,
        },
        "screenshots": {
            key: value.relative_to(ROOT).as_posix()
            for key, value in screenshots.items()
        },
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
    parser.add_argument(
        "--screenshot-root",
        type=Path,
        default=DEFAULT_SCREENSHOT_ROOT,
    )
    args = parser.parse_args()
    evidence = verify(args.url, args.output, args.screenshot_root)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
