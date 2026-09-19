"""Verify zone partitioning and two aisle additions in one Sage thread."""

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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g2-zone-to-two-aisles-thread.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g2-zone-to-two-aisles-thread"

ZONE_PROMPT = (
    "Create a new 120 m by 90 m facility with eight departments named "
    "Receiving, Stores, Machining, Automation, Assembly, Inspection, Packing, "
    "and Shipping. Arrange them in four rows: Receiving in row 1; Stores, "
    "Machining, and Automation in row 2; Assembly and Inspection in row 3; "
    "Packing and Shipping in row 4. Keep all departments equal in area."
)
MATERIAL_PROMPT = (
    "Now add a 6 m two-way material aisle from Receiving to Shipping through "
    "Machining and Assembly."
)
PEDESTRIAN_PROMPT = (
    "Also add a 3 m pedestrian walkway from Stores to Inspection through "
    "Automation."
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
        "label": route["label"],
        "widthMeters": route["corridorWidth"],
        "routeKind": aisle["aisleKind"],
        "direction": aisle["direction"],
        "source": labels[str(aisle["sourceZoneId"])],
        "target": labels[str(aisle["targetZoneId"])],
        "via": [labels[str(zone_id)] for zone_id in aisle["viaZoneIds"]],
        "areaAccounting": aisle["areaAccounting"],
        "widthAuthority": aisle["widthAuthority"],
        "pointCount": len(route["centerline"]),
    }


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "zones": screenshot_root / "01-partitioned-zones.png",
        "material": screenshot_root / "02-material-aisle.png",
        "twoAisles": screenshot_root / "03-two-aisles-one-thread.png",
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

        initial = _state(page)
        prior = page.locator("#agentMessages").inner_text()
        _send(page, ZONE_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const layout = state.layout || {};
                const plan = layout.extensions
                    && layout.extensions.facilityPlan || {};
                return state.dirty === true
                    && state.canSave === true
                    && state.generatedDraft
                    && state.generatedDraft.status === 'complete'
                    && !state.generatedDraft.currentStageId
                    && Number(plan.widthMeters) === 120
                    && Number(plan.depthMeters) === 90
                    && (layout.zones || []).length === 8
                    && (layout.routes || []).length === 0;
            }""",
            timeout=360_000,
        )
        zone_messages = _wait_chat_idle(page, prior)
        zones = _state(page)
        conversation_title = page.locator("#agentChatTitle").inner_text()
        page.screenshot(path=str(screenshots["zones"]), full_page=False)

        prior = zone_messages
        _send(page, MATERIAL_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                return routes.length === 1
                    && Number(routes[0].corridorWidth) === 6;
            }""",
            timeout=360_000,
        )
        material_messages = _wait_chat_idle(page, prior)
        material = _state(page)
        page.screenshot(path=str(screenshots["material"]), full_page=False)

        prior = material_messages
        _send(page, PEDESTRIAN_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                return routes.length === 2
                    && Number(routes[1].corridorWidth) === 3
                    && routes[1].extensions
                    && routes[1].extensions.facilityAisle
                    && routes[1].extensions.facilityAisle.aisleKind
                        === 'pedestrian';
            }""",
            timeout=360_000,
        )
        final_messages = _wait_chat_idle(page, prior)
        final = _state(page)
        final_conversation_title = page.locator("#agentChatTitle").inner_text()
        page.screenshot(path=str(screenshots["twoAisles"]), full_page=False)

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
        "Receiving",
        "Stores",
        "Machining",
        "Automation",
        "Assembly",
        "Inspection",
        "Packing",
        "Shipping",
    ]
    material_route = _route_summary(material, 0)
    final_material_route = _route_summary(final, 0)
    pedestrian_route = _route_summary(final, 1)
    checks = {
        "three_streams_completed": stream_statuses == [200, 200, 200],
        "one_conversation_thread": (
            conversation_title == final_conversation_title
            and ZONE_PROMPT in final_messages
            and MATERIAL_PROMPT in final_messages
            and PEDESTRIAN_PROMPT in final_messages
        ),
        "exact_partitioned_zones": (
            zones["labels"] == expected_labels
            and len(zones["layout"].get("routes", [])) == 0
            and zones["layout"]["extensions"]["facilityPlan"]["widthMeters"]
            == 120.0
            and zones["layout"]["extensions"]["facilityPlan"]["depthMeters"]
            == 90.0
        ),
        "same_generation_run_throughout": (
            zones["generatedDraft"]["runId"]
            == material["generatedDraft"]["runId"]
            == final["generatedDraft"]["runId"]
        ),
        "material_route_exact": material_route == {
            **material_route,
            "widthMeters": 6.0,
            "routeKind": "material",
            "direction": "two_way",
            "source": "Receiving",
            "target": "Shipping",
            "via": ["Machining", "Assembly"],
            "areaAccounting": "overlay",
            "widthAuthority": "user_authored",
        },
        "material_route_preserved_after_second": (
            final_material_route == material_route
        ),
        "pedestrian_route_exact": pedestrian_route == {
            **pedestrian_route,
            "widthMeters": 3.0,
            "routeKind": "pedestrian",
            "direction": "two_way",
            "source": "Stores",
            "target": "Inspection",
            "via": ["Automation"],
            "areaAccounting": "overlay",
            "widthAuthority": "user_authored",
        },
        "saved_layout_unchanged": (
            final["baseRevision"] == initial["baseRevision"]
            and final["baseLayout"] == initial["baseLayout"]
        ),
        "single_undo_restored_exact_saved_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
        ),
        "no_interruption_message": "Response interrupted" not in final_messages,
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g2-zone-to-two-aisles-thread-v1",
        "passed": all(checks.values()),
        "prompts": [ZONE_PROMPT, MATERIAL_PROMPT, PEDESTRIAN_PROMPT],
        "checks": checks,
        "streamStatuses": stream_statuses,
        "result": {
            "conversationTitle": conversation_title,
            "generationRunId": final["generatedDraft"]["runId"],
            "zoneLabels": zones["labels"],
            "materialRoute": final_material_route,
            "pedestrianRoute": pedestrian_route,
            "savedBaseRevision": initial["baseRevision"],
            "finalDraftRevision": final["generatedDraft"][
                "draftLayoutRevision"
            ],
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
