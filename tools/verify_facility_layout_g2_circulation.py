"""Verify G2 circulation through the visible Sage Facility Layout workflow."""

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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g2-circulation-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g2-circulation-browser"

FACILITY_PROMPT = (
    "Create a new 120 m by 90 m facility and divide it into four equal "
    "departments named Receiving, Machining, Assembly, and Shipping."
)
ROUTE_PROMPT = (
    "Add a 6 m material aisle from Receiving to Shipping through Machining "
    "and Assembly."
)
FOLLOW_UP_PROMPT = "Make that aisle 5 m wide and keep the same endpoints."
CONNECTIVITY_PROMPT = "Which departments are not connected by circulation yet?"
AMBIGUOUS_PROMPT = "Add some aisles."
POLICY_PROMPT = "Add whatever fire aisles the code requires."


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
            typeof _trainFacilityLayoutAuthoringApp !== 'undefined'
            && _trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
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
    page.wait_for_timeout(350)
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
                layout: layout,
                baseLayout: state.baseLayout,
                labels: (layout.zones || []).map(zone => zone.label),
                routes: (layout.routes || []).map(route => ({
                    routeId: route.routeId,
                    label: route.label,
                    corridorWidth: route.corridorWidth,
                    centerline: route.centerline,
                    aisle: route.extensions
                        && route.extensions.facilityAisle || null,
                })),
            };
        }"""
    )


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "departments": screenshot_root / "01-departments.png",
        "route": screenshot_root / "02-material-route-6m.png",
        "follow_up": screenshot_root / "03-material-route-5m.png",
        "guardrails": screenshot_root / "04-circulation-guardrails.png",
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
        _send(page, FACILITY_PROMPT)
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
                    && (layout.zones || []).length === 4;
            }""",
            timeout=360_000,
        )
        facility_messages = _wait_chat_idle(page, prior)
        departments = _state(page)
        page.screenshot(path=str(screenshots["departments"]), full_page=False)

        prior = facility_messages
        _send(page, ROUTE_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                const route = routes[routes.length - 1];
                return routes.length === 1
                    && route
                    && Number(route.corridorWidth) === 6
                    && route.extensions
                    && route.extensions.facilityAisle
                    && route.extensions.facilityAisle.areaAccounting === 'overlay';
            }""",
            timeout=360_000,
        )
        route_messages = _wait_chat_idle(page, prior)
        routed = _state(page)
        page.screenshot(path=str(screenshots["route"]), full_page=False)

        prior = route_messages
        _send(page, FOLLOW_UP_PROMPT)
        page.wait_for_function(
            """() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                return routes.length === 1
                    && Number(routes[0].corridorWidth) === 5;
            }""",
            timeout=360_000,
        )
        follow_up_messages = _wait_chat_idle(page, prior)
        resized = _state(page)
        page.screenshot(path=str(screenshots["follow_up"]), full_page=False)

        prior = follow_up_messages
        _send(page, CONNECTIVITY_PROMPT)
        connectivity_messages = _wait_chat_idle(page, prior)
        after_connectivity = _state(page)

        prior = connectivity_messages
        _send(page, AMBIGUOUS_PROMPT)
        ambiguous_messages = _wait_chat_idle(page, prior)
        after_ambiguous = _state(page)

        prior = ambiguous_messages
        _send(page, POLICY_PROMPT)
        policy_messages = _wait_chat_idle(page, prior)
        after_policy = _state(page)
        page.screenshot(path=str(screenshots["guardrails"]), full_page=False)

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

    initial_base = initial["baseLayout"]
    routed_route = routed["routes"][0]
    resized_route = resized["routes"][0]
    no_change_revisions = {
        after_connectivity["generatedDraft"]["draftLayoutRevision"],
        after_ambiguous["generatedDraft"]["draftLayoutRevision"],
        after_policy["generatedDraft"]["draftLayoutRevision"],
        resized["generatedDraft"]["draftLayoutRevision"],
    }
    checks = {
        "six_streams_completed": stream_statuses == [200] * 6,
        "exact_facility_and_departments": (
            departments["labels"]
            == ["Receiving", "Machining", "Assembly", "Shipping"]
            and departments["layout"]["extensions"]["facilityPlan"][
                "widthMeters"
            ] == 120.0
            and departments["layout"]["extensions"]["facilityPlan"][
                "depthMeters"
            ] == 90.0
        ),
        "route_added_to_same_run": (
            departments["generatedDraft"]["runId"]
            == routed["generatedDraft"]["runId"]
            and len(routed["routes"]) == 1
        ),
        "route_is_deterministic_overlay": (
            routed_route["corridorWidth"] == 6.0
            and routed_route["aisle"]["aisleKind"] == "material"
            and routed_route["aisle"]["direction"] == "two_way"
            and routed_route["aisle"]["areaAccounting"] == "overlay"
            and routed_route["aisle"]["widthAuthority"] == "user_authored"
            and len(routed_route["aisle"]["viaZoneIds"]) == 2
            and len(routed_route["centerline"]) >= 2
        ),
        "follow_up_preserved_identity": (
            resized_route["routeId"] == routed_route["routeId"]
            and resized_route["corridorWidth"] == 5.0
            and resized_route["aisle"]["sourceZoneId"]
            == routed_route["aisle"]["sourceZoneId"]
            and resized_route["aisle"]["targetZoneId"]
            == routed_route["aisle"]["targetZoneId"]
            and resized_route["aisle"]["viaZoneIds"]
            == routed_route["aisle"]["viaZoneIds"]
        ),
        "read_only_connectivity_answer": (
            "Every department is bound" in connectivity_messages
            and after_connectivity["generatedDraft"]["draftLayoutRevision"]
            == resized["generatedDraft"]["draftLayoutRevision"]
        ),
        "ambiguous_request_asked_for_width": (
            "What route width should I use?" in ambiguous_messages
            and after_ambiguous["generatedDraft"]["draftLayoutRevision"]
            == resized["generatedDraft"]["draftLayoutRevision"]
        ),
        "policy_request_refused_without_invention": (
            "cannot add code-required circulation" in policy_messages
            and "no clearance value was invented" in policy_messages
            and after_policy["generatedDraft"]["draftLayoutRevision"]
            == resized["generatedDraft"]["draftLayoutRevision"]
        ),
        "read_only_turns_did_not_revise_draft": len(no_change_revisions) == 1,
        "saved_layout_unchanged_before_undo": (
            after_policy["baseRevision"] == initial["baseRevision"]
            and after_policy["baseLayout"] == initial_base
        ),
        "single_undo_restored_exact_saved_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial_base
            and restored["baseLayout"] == initial_base
        ),
        "no_interruption_message": "Response interrupted" not in policy_messages,
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g2-circulation-browser-evidence-v1",
        "passed": all(checks.values()),
        "prompts": [
            FACILITY_PROMPT,
            ROUTE_PROMPT,
            FOLLOW_UP_PROMPT,
            CONNECTIVITY_PROMPT,
            AMBIGUOUS_PROMPT,
            POLICY_PROMPT,
        ],
        "checks": checks,
        "streamStatuses": stream_statuses,
        "result": {
            "runId": routed["generatedDraft"]["runId"],
            "departmentLabels": departments["labels"],
            "routeBefore": routed_route,
            "routeAfter": resized_route,
            "savedBaseRevision": initial["baseRevision"],
            "draftRevision": resized["generatedDraft"]["draftLayoutRevision"],
        },
        "responseText": policy_messages,
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
