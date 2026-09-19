"""Verify blank default and replacement of a dirty editor in one Sage thread."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from verify_facility_layout_g2_circulation import (
    _open_facility,
    _send,
    _state,
    _wait_chat_idle,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "blank-default-replacement-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "blank-default-replacement"

PARTITION_PROMPT = (
    "Create a new 150 m by 100 m facility with six equal-area departments "
    "named Inbound, Raw Materials, Fabrication, Subassembly, Final Inspection, "
    "and Dispatch. Arrange them in three rows: Inbound and Raw Materials in "
    "row 1; Fabrication and Subassembly in row 2; Final Inspection and "
    "Dispatch in row 3."
)
FORKLIFT_PROMPT = (
    "Add a 5 m one-way forklift lane from Inbound to Dispatch through "
    "Fabrication and Subassembly."
)
PEDESTRIAN_PROMPT = (
    "Add a 2.5 m two-way pedestrian walkway from Raw Materials to Final "
    "Inspection through Subassembly."
)


def _zone_id_to_label(state: dict[str, Any]) -> dict[str, str]:
    return {
        str(zone.get("zoneId")): str(zone.get("label"))
        for zone in state["layout"].get("zones", [])
    }


def _route_summary(state: dict[str, Any], index: int) -> dict[str, Any]:
    route = state["routes"][index]
    aisle = route["aisle"]
    labels = _zone_id_to_label(state)
    return {
        "routeId": route["routeId"],
        "widthMeters": route["corridorWidth"],
        "routeKind": aisle["aisleKind"],
        "direction": aisle["direction"],
        "source": labels[str(aisle["sourceZoneId"])],
        "target": labels[str(aisle["targetZoneId"])],
        "via": [labels[str(zone_id)] for zone_id in aisle["viaZoneIds"]],
        "areaAccounting": aisle["areaAccounting"],
        "widthAuthority": aisle["widthAuthority"],
    }


def _empty_layout(layout: dict[str, Any]) -> bool:
    return not any((
        layout.get("zones", []),
        layout.get("routes", []),
        layout.get("placements", []),
        layout.get("floorMarkings", []),
    ))


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "blank": screenshot_root / "00-blank-default.png",
        "dirty": screenshot_root / "01-unsaved-manual-zone.png",
        "partition": screenshot_root / "02-six-department-partition.png",
        "final": screenshot_root / "03-two-aisles.png",
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
                failed_responses.append({
                    "method": response.request.method,
                    "status": response.status,
                    "url": response.url,
                })

        page.on("response", observe_response)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)

        blank = _state(page)
        page.screenshot(path=str(screenshots["blank"]), full_page=False)

        page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.session.createZones([{
                    label: 'Temporary Manual Zone',
                    zoneType: 'workcell',
                    minX: 5,
                    minZ: 5,
                    width: 10,
                    depth: 10,
                }]);
            }"""
        )
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return state.dirty === true
                    && !state.generatedDraft
                    && (state.layout.zones || []).length === 1;
            }""",
            timeout=60_000,
        )
        dirty = _state(page)
        page.screenshot(path=str(screenshots["dirty"]), full_page=False)

        prior = page.locator("#agentMessages").inner_text()
        _send(page, PARTITION_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const layout = state.layout || {};
                const plan = layout.extensions
                    && layout.extensions.facilityPlan || {};
                return state.dirty === true
                    && state.generatedDraft
                    && state.generatedDraft.status === 'complete'
                    && !state.generatedDraft.currentStageId
                    && Number(plan.widthMeters) === 150
                    && Number(plan.depthMeters) === 100
                    && (layout.zones || []).length === 6
                    && !(layout.zones || []).some(
                        zone => zone.label === 'Temporary Manual Zone'
                    );
            }""",
            timeout=360_000,
        )
        partition_messages = _wait_chat_idle(page, prior)
        partition = _state(page)
        conversation_title = page.locator("#agentChatTitle").inner_text()
        page.screenshot(path=str(screenshots["partition"]), full_page=False)

        prior = partition_messages
        _send(page, FORKLIFT_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                return routes.length === 1
                    && Number(routes[0].corridorWidth) === 5;
            }""",
            timeout=360_000,
        )
        forklift_messages = _wait_chat_idle(page, prior)
        forklift = _state(page)

        prior = forklift_messages
        _send(page, PEDESTRIAN_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                return routes.length === 2
                    && Number(routes[1].corridorWidth) === 2.5;
            }""",
            timeout=360_000,
        )
        final_messages = _wait_chat_idle(page, prior)
        final = _state(page)
        final_title = page.locator("#agentChatTitle").inner_text()
        page.screenshot(path=str(screenshots["final"]), full_page=False)

        restored = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('undo');
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    baseRevision: state.baseRevision,
                    dirty: state.dirty,
                    layout: state.layout,
                    baseLayout: state.baseLayout,
                };
            }"""
        )
        browser.close()

    expected_labels = [
        "Inbound",
        "Raw Materials",
        "Fabrication",
        "Subassembly",
        "Final Inspection",
        "Dispatch",
    ]
    forklift_route = _route_summary(final, 0)
    pedestrian_route = _route_summary(final, 1)
    checks = {
        "default_loaded_blank": (
            _empty_layout(blank["layout"])
            and _empty_layout(blank["baseLayout"])
            and blank["dirty"] is False
            and blank["layout"]["displayName"] == "Blank Facility Layout"
        ),
        "dirty_manual_state_reproduced": (
            dirty["dirty"] is True
            and dirty["labels"] == ["Temporary Manual Zone"]
            and dirty["generatedDraft"] is None
        ),
        "exact_prompt_replaced_dirty_editor": (
            partition["labels"] == expected_labels
            and "Temporary Manual Zone" not in partition["labels"]
            and "facility_generation_editor_changed" not in partition_messages
        ),
        "exact_dimensions": (
            partition["layout"]["extensions"]["facilityPlan"]["widthMeters"]
            == 150.0
            and partition["layout"]["extensions"]["facilityPlan"]["depthMeters"]
            == 100.0
        ),
        "one_conversation_thread": (
            conversation_title == final_title
            and PARTITION_PROMPT in final_messages
            and FORKLIFT_PROMPT in final_messages
            and PEDESTRIAN_PROMPT in final_messages
        ),
        "same_generation_run": (
            partition["generatedDraft"]["runId"]
            == forklift["generatedDraft"]["runId"]
            == final["generatedDraft"]["runId"]
        ),
        "forklift_route_exact": forklift_route == {
            "routeId": forklift_route["routeId"],
            "widthMeters": 5.0,
            "routeKind": "forklift",
            "direction": "one_way",
            "source": "Inbound",
            "target": "Dispatch",
            "via": ["Fabrication", "Subassembly"],
            "areaAccounting": "overlay",
            "widthAuthority": "user_authored",
        },
        "pedestrian_route_exact": pedestrian_route == {
            "routeId": pedestrian_route["routeId"],
            "widthMeters": 2.5,
            "routeKind": "pedestrian",
            "direction": "two_way",
            "source": "Raw Materials",
            "target": "Final Inspection",
            "via": ["Subassembly"],
            "areaAccounting": "overlay",
            "widthAuthority": "user_authored",
        },
        "saved_blank_base_unchanged": (
            final["baseRevision"] == blank["baseRevision"]
            and final["baseLayout"] == blank["baseLayout"]
        ),
        "single_undo_restored_blank_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == blank["baseRevision"]
            and restored["layout"] == blank["baseLayout"]
            and restored["baseLayout"] == blank["baseLayout"]
        ),
        "three_streams_completed": stream_statuses == [200, 200, 200],
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
        "no_interruption_message": "Response interrupted" not in final_messages,
    }
    evidence = {
        "schemaVersion": "facility-layout-blank-default-replacement-v1",
        "passed": all(checks.values()),
        "prompts": [PARTITION_PROMPT, FORKLIFT_PROMPT, PEDESTRIAN_PROMPT],
        "checks": checks,
        "streamStatuses": stream_statuses,
        "result": {
            "blankBaseRevision": blank["baseRevision"],
            "generationRunId": final["generatedDraft"]["runId"],
            "zoneLabels": partition["labels"],
            "forkliftRoute": forklift_route,
            "pedestrianRoute": pedestrian_route,
        },
        "responseText": final_messages,
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
