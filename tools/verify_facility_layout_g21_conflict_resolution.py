"""Verify G2.1 mixed-traffic conflict resolution in one visible Sage thread."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.circulation import (
    analyze_primary_circulation_conflicts,
)
from verify_facility_layout_g2_circulation import (
    _open_facility,
    _send,
    _state,
    _wait_chat_idle,
)

EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g21-conflict-resolution-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g21-conflict-resolution-browser"

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
LOCATE_PROMPT = "Where do the pedestrian and forklift routes conflict?"
RESOLVE_PROMPT = (
    "Resolve the mixed-traffic conflict with 1.5 m separation without changing "
    "the departments. Compare both rerouting options and keep the shorter "
    "feasible result."
)
CONFIRM_PROMPT = "Do the pedestrian and forklift routes still conflict?"


def _route_contracts(state: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for route in state["routes"]:
        aisle = route.get("aisle") or {}
        contracts.append({
            "routeId": route.get("routeId"),
            "label": route.get("label"),
            "corridorWidth": route.get("corridorWidth"),
            "aisleKind": aisle.get("aisleKind"),
            "direction": aisle.get("direction"),
            "sourceZoneId": aisle.get("sourceZoneId"),
            "targetZoneId": aisle.get("targetZoneId"),
            "viaZoneIds": list(aisle.get("viaZoneIds") or []),
            "areaAccounting": aisle.get("areaAccounting"),
            "widthAuthority": aisle.get("widthAuthority"),
        })
    return contracts


def _centerlines(state: dict[str, Any]) -> dict[str, Any]:
    return {
        str(route.get("routeId")): deepcopy(route.get("centerline") or [])
        for route in state["routes"]
    }


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "conflict": screenshot_root / "01-conflict-located.png",
        "resolved": screenshot_root / "02-conflict-resolved.png",
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
        _send(page, PARTITION_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const plan = state.layout && state.layout.extensions
                    && state.layout.extensions.facilityPlan || {};
                return state.generatedDraft
                    && state.generatedDraft.status === 'complete'
                    && !state.generatedDraft.currentStageId
                    && Number(plan.widthMeters) === 150
                    && Number(plan.depthMeters) === 100
                    && (state.layout.zones || []).length === 6;
            }""",
            timeout=360_000,
        )
        partition_messages = _wait_chat_idle(page, prior)
        partition = _state(page)
        thread_title = page.locator("#agentChatTitle").inner_text()

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
        pedestrian_messages = _wait_chat_idle(page, prior)
        before = _state(page)
        before_analysis = analyze_primary_circulation_conflicts(before["layout"])

        prior = pedestrian_messages
        _send(page, LOCATE_PROMPT)
        locate_messages = _wait_chat_idle(page, prior)
        located = _state(page)
        page.screenshot(path=str(screenshots["conflict"]), full_page=False)

        prior_revision = str(before["generatedDraft"]["draftLayoutRevision"])
        prior = locate_messages
        _send(page, RESOLVE_PROMPT)
        page.wait_for_function(
            """priorRevision => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const draft = state.generatedDraft;
                return draft
                    && draft.status === 'complete'
                    && !draft.currentStageId
                    && String(draft.draftLayoutRevision || '') !== priorRevision
                    && (state.layout.routes || []).length === 2;
            }""",
            arg=prior_revision,
            timeout=360_000,
        )
        resolve_messages = _wait_chat_idle(page, prior)
        resolved = _state(page)
        after_analysis = analyze_primary_circulation_conflicts(resolved["layout"])

        prior = resolve_messages
        _send(page, CONFIRM_PROMPT)
        confirm_messages = _wait_chat_idle(page, prior)
        confirmed = _state(page)
        final_title = page.locator("#agentChatTitle").inner_text()
        page.screenshot(path=str(screenshots["resolved"]), full_page=False)

        restored = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace
                    .executeCommand('undo');
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

    before_contracts = _route_contracts(before)
    after_contracts = _route_contracts(resolved)
    before_centerlines = _centerlines(before)
    after_centerlines = _centerlines(resolved)
    changed_route_ids = sorted(
        route_id for route_id, centerline in before_centerlines.items()
        if after_centerlines.get(route_id) != centerline
    )
    checks = {
        "six_streams_completed": stream_statuses == [200] * 6,
        "same_conversation_and_generation_run": (
            thread_title == final_title
            and partition["generatedDraft"]["runId"]
            == before["generatedDraft"]["runId"]
            == resolved["generatedDraft"]["runId"]
        ),
        "initial_conflict_detected_from_geometry": (
            before_analysis["mixedTrafficConflictCount"] >= 1
            and before_analysis["status"] == "conflict"
        ),
        "read_only_conflict_answer_is_grounded": (
            "mixed-traffic geometric conflict" in locate_messages
            and "current static geometry" in locate_messages
            and "code compliance" in locate_messages
            and located["generatedDraft"]["draftLayoutRevision"]
            == before["generatedDraft"]["draftLayoutRevision"]
        ),
        "conflict_resolved_with_authored_separation": (
            after_analysis["mixedTrafficConflictCount"] == 0
            and after_analysis["status"] == "clear"
            and float(
                after_analysis["mixedTrafficPairMinimumSeparationMeters"]
            ) >= 1.5
        ),
        "department_geometry_byte_parity": (
            resolved["layout"].get("zones") == before["layout"].get("zones")
        ),
        "route_contracts_preserved": after_contracts == before_contracts,
        "resolver_changed_route_geometry": bool(changed_route_ids),
        "post_resolution_answer_matches_geometry": (
            "No mixed pedestrian/material geometric conflict" in confirm_messages
            and confirmed["generatedDraft"]["draftLayoutRevision"]
            == resolved["generatedDraft"]["draftLayoutRevision"]
        ),
        "saved_layout_unchanged_before_undo": (
            confirmed["baseRevision"] == initial["baseRevision"]
            and confirmed["baseLayout"] == initial["baseLayout"]
        ),
        "single_undo_restored_exact_saved_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
        ),
        "no_interruption_message": "Response interrupted" not in confirm_messages,
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g21-conflict-resolution-browser-v1",
        "passed": all(checks.values()),
        "prompts": [
            PARTITION_PROMPT,
            FORKLIFT_PROMPT,
            PEDESTRIAN_PROMPT,
            LOCATE_PROMPT,
            RESOLVE_PROMPT,
            CONFIRM_PROMPT,
        ],
        "checks": checks,
        "streamStatuses": stream_statuses,
        "result": {
            "runId": resolved["generatedDraft"]["runId"],
            "beforeAnalysis": before_analysis,
            "afterAnalysis": after_analysis,
            "changedRouteIds": changed_route_ids,
            "routeContracts": after_contracts,
            "savedBaseRevision": initial["baseRevision"],
            "resolvedDraftRevision": resolved["generatedDraft"][
                "draftLayoutRevision"
            ],
        },
        "responseText": confirm_messages,
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
