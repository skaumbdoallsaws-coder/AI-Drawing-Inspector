"""Replay the exact pre-geometry G2 circulation evaluation through Sage."""

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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g2-circulation-baseline-replay.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g2-circulation-baseline-replay"

SETUP_PROMPT = (
    "Create a new 120 m by 90 m facility with eight departments named "
    "Receiving, Stores, Machining, Automation, Assembly, Inspection, Packing, "
    "and Shipping. Arrange them in four rows: Receiving in row 1; Stores, "
    "Machining, and Automation in row 2; Assembly and Inspection in row 3; "
    "Packing and Shipping in row 4. Keep all departments equal in area."
)

CASES = [
    {
        "id": "01-build",
        "category": "build",
        "prompt": (
            "Add a 6 m material aisle from Receiving to Shipping through "
            "Machining and Assembly."
        ),
        "newConversation": True,
    },
    {
        "id": "02-follow-up",
        "category": "follow_up",
        "prompt": "Make that aisle 5 m wide and keep the same endpoints.",
        "newConversation": False,
    },
    {
        "id": "03-ambiguous",
        "category": "clarification",
        "prompt": "Add some aisles.",
        "newConversation": True,
    },
    {
        "id": "04-policy",
        "category": "unsupported_policy",
        "prompt": "Add whatever fire aisles the code requires.",
        "newConversation": True,
    },
    {
        "id": "05-read-only",
        "category": "analysis",
        "prompt": "Which departments are not connected to the material route?",
        "newConversation": True,
    },
    {
        "id": "06-coordinate",
        "category": "coordinate_boundary",
        "prompt": (
            "Place the aisle at x 40, z 25 using these exact model coordinates."
        ),
        "newConversation": True,
    },
    {
        "id": "07-hypothetical",
        "category": "hypothetical",
        "prompt": "What would happen if we added a central aisle?",
        "newConversation": True,
    },
    {
        "id": "08-negated",
        "category": "negated",
        "prompt": "Do not add a route; just explain the options.",
        "newConversation": True,
    },
]


def _draft_revision(state: dict[str, Any]) -> str | None:
    generated = state.get("generatedDraft") or {}
    value = generated.get("draftLayoutRevision")
    return str(value) if value else None


def _latest_text(prior: str, current: str) -> str:
    if prior and current.startswith(prior):
        return current[len(prior) :].strip()
    return current.strip()


def _new_conversation(page: Any) -> str:
    page.locator("#agentChatNewBtn").click()
    page.wait_for_timeout(750)
    page.evaluate("() => window._selectAgent('deviation-analyst')")
    page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
    return page.locator("#agentMessages").inner_text()


def _route_binding_labels(state: dict[str, Any]) -> dict[str, Any]:
    layout = state["layout"]
    zones = {
        str(zone.get("zoneId")): str(zone.get("label"))
        for zone in layout.get("zones", [])
    }
    route = state["routes"][0]
    aisle = route["aisle"]
    return {
        "source": zones.get(str(aisle.get("sourceZoneId"))),
        "target": zones.get(str(aisle.get("targetZoneId"))),
        "via": [
            zones.get(str(zone_id))
            for zone_id in aisle.get("viaZoneIds", [])
        ],
    }


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []
    results: list[dict[str, Any]] = []

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
        _send(page, SETUP_PROMPT)
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
                    && (layout.zones || []).length === 8;
            }""",
            timeout=360_000,
        )
        _wait_chat_idle(page, prior)
        setup = _state(page)
        setup_screenshot = screenshot_root / "00-eight-department-setup.png"
        page.screenshot(path=str(setup_screenshot), full_page=False)

        route_before_follow_up: dict[str, Any] | None = None
        revision_after_follow_up: str | None = None

        for case in CASES:
            if case["newConversation"]:
                prior = _new_conversation(page)
            else:
                prior = page.locator("#agentMessages").inner_text()
            before = _state(page)
            _send(page, case["prompt"])
            if case["id"] == "01-build":
                page.wait_for_function(
                    """() => {
                        const state = _trainFacilityLayoutAuthoringApp.session.getState();
                        const routes = state.layout && state.layout.routes || [];
                        return routes.length === 1
                            && Number(routes[0].corridorWidth) === 6;
                    }""",
                    timeout=360_000,
                )
            elif case["id"] == "02-follow-up":
                page.wait_for_function(
                    """() => {
                        const state = _trainFacilityLayoutAuthoringApp.session.getState();
                        const routes = state.layout && state.layout.routes || [];
                        return routes.length === 1
                            && Number(routes[0].corridorWidth) === 5;
                    }""",
                    timeout=360_000,
                )
            current = _wait_chat_idle(page, prior)
            after = _state(page)
            answer = _latest_text(prior, current)
            screenshot = screenshot_root / f"{case['id']}.png"
            page.screenshot(path=str(screenshot), full_page=False)

            checks: dict[str, bool]
            if case["id"] == "01-build":
                route = after["routes"][0] if len(after["routes"]) == 1 else {}
                aisle = route.get("aisle") or {}
                bindings = (
                    _route_binding_labels(after)
                    if len(after["routes"]) == 1
                    else {}
                )
                checks = {
                    "one_route_created": len(after["routes"]) == 1,
                    "exact_width_and_kind": (
                        route.get("corridorWidth") == 6.0
                        and aisle.get("aisleKind") == "material"
                        and aisle.get("direction") == "two_way"
                    ),
                    "exact_department_bindings": bindings == {
                        "source": "Receiving",
                        "target": "Shipping",
                        "via": ["Machining", "Assembly"],
                    },
                    "same_generation_run": (
                        setup["generatedDraft"]["runId"]
                        == after["generatedDraft"]["runId"]
                    ),
                    "answer_is_specific": (
                        "requested circulation" in answer
                        and "overlay" in answer
                        and "Two-way circulation" in answer
                    ),
                }
                if route:
                    route_before_follow_up = route
            elif case["id"] == "02-follow-up":
                route = after["routes"][0] if len(after["routes"]) == 1 else {}
                prior_route = route_before_follow_up or {}
                checks = {
                    "one_route_retained": len(after["routes"]) == 1,
                    "width_changed_to_five_metres": (
                        route.get("corridorWidth") == 5.0
                    ),
                    "route_identity_preserved": (
                        route.get("routeId") == prior_route.get("routeId")
                    ),
                    "bindings_preserved": (
                        (route.get("aisle") or {}).get("sourceZoneId")
                        == (prior_route.get("aisle") or {}).get("sourceZoneId")
                        and (route.get("aisle") or {}).get("targetZoneId")
                        == (prior_route.get("aisle") or {}).get("targetZoneId")
                        and (route.get("aisle") or {}).get("viaZoneIds")
                        == (prior_route.get("aisle") or {}).get("viaZoneIds")
                    ),
                    "answer_is_specific": (
                        "requested circulation" in answer
                        and "overlay" in answer
                    ),
                }
                revision_after_follow_up = _draft_revision(after)
            elif case["id"] == "03-ambiguous":
                checks = {
                    "asks_for_width": "What route width should I use?" in answer,
                    "does_not_infer_clearance": "will not infer" in answer,
                    "draft_unchanged": (
                        _draft_revision(after) == revision_after_follow_up
                    ),
                }
            elif case["id"] == "04-policy":
                checks = {
                    "names_missing_authority": (
                        "without an authored policy" in answer
                    ),
                    "invents_no_clearance": (
                        "no clearance value was invented" in answer
                    ),
                    "draft_unchanged": (
                        _draft_revision(after) == revision_after_follow_up
                    ),
                }
            elif case["id"] == "05-read-only":
                expected = ["Stores", "Automation", "Inspection", "Packing"]
                checks = {
                    "uses_active_draft_bindings": all(
                        label in answer for label in expected
                    ),
                    "states_semantic_boundary": (
                        "does not assess code compliance" in answer
                    ),
                    "draft_unchanged": (
                        _draft_revision(after) == revision_after_follow_up
                    ),
                }
            elif case["id"] == "06-coordinate":
                checks = {
                    "rejects_chat_coordinates": (
                        "cannot accept authored route coordinates from chat" in answer
                    ),
                    "routes_geometry_to_inspectorpro": (
                        "InspectorPro will compute the geometry" in answer
                    ),
                    "draft_unchanged": (
                        _draft_revision(after) == revision_after_follow_up
                    ),
                }
            elif case["id"] == "07-hypothetical":
                checks = {
                    "claims_no_uncomputed_benefit": (
                        "no travel benefit is claimed" in answer
                    ),
                    "requests_bounded_inputs": (
                        "named endpoints, a route type, and a width" in answer
                    ),
                    "draft_unchanged": (
                        _draft_revision(after) == revision_after_follow_up
                    ),
                }
            else:
                checks = {
                    "confirms_no_route_added": "No route was added." in answer,
                    "offers_semantic_options": (
                        "department-to-department aisle" in answer
                        and "forklift lane" in answer
                        and "pedestrian walkway" in answer
                    ),
                    "draft_unchanged": (
                        _draft_revision(after) == revision_after_follow_up
                    ),
                }

            results.append({
                "id": case["id"],
                "category": case["category"],
                "prompt": case["prompt"],
                "expectedBehavior": (
                    "build" if case["id"] in {"01-build", "02-follow-up"}
                    else "ask" if case["id"] == "03-ambiguous"
                    else "refuse" if case["id"] in {"04-policy", "06-coordinate"}
                    else "read_only"
                ),
                "answer": answer,
                "checks": checks,
                "passed": all(checks.values()),
                "beforeRevision": _draft_revision(before),
                "afterRevision": _draft_revision(after),
                "routeCount": len(after["routes"]),
                "screenshot": screenshot.relative_to(ROOT).as_posix(),
            })

        before_undo = _state(page)
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
    global_checks = {
        "setup_exact": (
            setup["labels"] == expected_labels
            and setup["layout"]["extensions"]["facilityPlan"]["widthMeters"]
            == 120.0
            and setup["layout"]["extensions"]["facilityPlan"]["depthMeters"]
            == 90.0
        ),
        "all_eight_cases_passed": (
            len(results) == 8 and all(item["passed"] for item in results)
        ),
        "nine_streams_completed": stream_statuses == [200] * 9,
        "saved_layout_unchanged_before_undo": (
            before_undo["baseRevision"] == initial["baseRevision"]
            and before_undo["baseLayout"] == initial["baseLayout"]
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
        "no_interruption_message": all(
            "Response interrupted" not in item["answer"] for item in results
        ),
    }
    evidence = {
        "schemaVersion": "facility-layout-g2-baseline-replay-v1",
        "sourceBaseline": "runtime_logs/facility-g2-intent-baseline/result.json",
        "passed": all(global_checks.values()),
        "summary": {
            "passedCases": sum(1 for item in results if item["passed"]),
            "totalCases": len(results),
            "streamStatuses": stream_statuses,
        },
        "setup": {
            "prompt": SETUP_PROMPT,
            "labels": setup["labels"],
            "runId": setup["generatedDraft"]["runId"],
            "screenshot": setup_screenshot.relative_to(ROOT).as_posix(),
        },
        "cases": results,
        "checks": global_checks,
        "errors": {
            "console": console_errors,
            "page": page_errors,
            "failedResponses": failed_responses,
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
