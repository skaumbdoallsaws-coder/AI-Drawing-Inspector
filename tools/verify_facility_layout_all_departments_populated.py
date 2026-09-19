"""Time a blank-to-populated Facility Layout session in visible Sage chat."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from verify_facility_layout_g2_circulation import (
    _open_facility,
    _send,
    _wait_chat_idle,
)
from verify_facility_layout_g4_asset_placement import (
    _placements_are_bounded_and_separate,
)


EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = (
    EVIDENCE_ROOT / "g4-all-departments-populated-browser-evidence.json"
)
DEFAULT_SCREENSHOT_ROOT = (
    EVIDENCE_ROOT / "g4-all-departments-populated-browser"
)

PROMPTS = {
    "facility": (
        "Create a new 120 m by 90 m facility with six equal-area departments "
        "named Receiving, Storage, Machining, Assembly, Inspection, and "
        "Dispatch. Arrange them in two rows: Receiving, Storage, and Machining "
        "in row 1; Assembly, Inspection, and Dispatch in row 2."
    ),
    "receiving": "Stage 2 Electric Forklift units in Receiving.",
    "storage": (
        "Place 4 Pallet Rack units in Storage with their long side east-west "
        "for storage."
    ),
    "machining": (
        "Place 3 CNC Milling Machine units in Machining with their long side "
        "north-south for production."
    ),
    "assembly": (
        "Place 4 Assembly Workbench 36 x 24 in units in Assembly with their "
        "long side east-west for production."
    ),
    "inspection": (
        "Place 2 Assembled Laboratory Workstation units in Inspection for "
        "inspection."
    ),
    "dispatch": (
        "Stage 2 400 x 1540 Modular Conveyor units in Dispatch with their long "
        "side east-west."
    ),
}

DEPARTMENT_LABELS = [
    "Receiving",
    "Storage",
    "Machining",
    "Assembly",
    "Inspection",
    "Dispatch",
]

PLACEMENT_PLAN = {
    "Receiving": {
        "asset": "Electric Forklift",
        "quantity": 2,
        "role": "staging",
        "orientation": "auto",
    },
    "Storage": {
        "asset": "Pallet Rack",
        "quantity": 4,
        "role": "storage",
        "orientation": "long_side_east_west",
    },
    "Machining": {
        "asset": "CNC Milling Machine",
        "quantity": 3,
        "role": "production",
        "orientation": "long_side_north_south",
    },
    "Assembly": {
        "asset": "Assembly Workbench 36 x 24 in",
        "quantity": 4,
        "role": "production",
        "orientation": "long_side_east_west",
    },
    "Inspection": {
        "asset": "Assembled Laboratory Workstation",
        "quantity": 2,
        "role": "inspection",
        "orientation": "auto",
    },
    "Dispatch": {
        "asset": "400 x 1540 Modular Conveyor",
        "quantity": 2,
        "role": "staging",
        "orientation": "long_side_east_west",
    },
}


def _state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = _trainFacilityLayoutAuthoringApp.session.getState();
            return {
                baseRevision: state.baseRevision,
                dirty: state.dirty,
                canSave: state.canSave,
                generatedDraft: state.generatedDraft,
                layout: state.layout,
                baseLayout: state.baseLayout,
                title: document.getElementById('agentChatTitle').innerText,
                messages: document.getElementById('agentMessages').innerText,
            };
        }"""
    )


def _turn(
    page: Any,
    prompt: str,
    *,
    predicate: str,
    arg: Any,
) -> dict[str, Any]:
    prior = page.locator("#agentMessages").inner_text()
    _send(page, prompt)
    page.wait_for_function(predicate, arg=arg, timeout=360_000)
    _wait_chat_idle(page, prior)
    return _state(page)


def _exact_catalog_asset(
    catalog: list[dict[str, Any]], display_name: str
) -> dict[str, Any]:
    matches = [
        item for item in catalog if str(item.get("displayName") or "") == display_name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one catalog asset named {display_name!r}; got {len(matches)}"
        )
    return matches[0]


def verify(app_url: str, output: Path, screenshot_root: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "blank": screenshot_root / "00-blank-start.png",
        "departments": screenshot_root / "01-six-departments.png",
        "receiving": screenshot_root / "02-receiving-populated.png",
        "storage": screenshot_root / "03-storage-populated.png",
        "machining": screenshot_root / "04-machining-populated.png",
        "assembly": screenshot_root / "05-assembly-populated.png",
        "inspection": screenshot_root / "06-inspection-populated.png",
        "complete": screenshot_root / "07-all-departments-populated.png",
        "undo": screenshot_root / "08-one-undo-blank.png",
    }
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []
    turns: list[dict[str, Any]] = []
    process_started = perf_counter()

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
        bootstrap = page.evaluate(
            """async () => await (await fetch('/api/facility-layout-bootstrap', {
                cache: 'no-store'
            })).json()"""
        )
        catalog = bootstrap["assetCatalog"]
        _open_facility(page)
        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
        initial = _state(page)
        page.screenshot(path=str(screenshots["blank"]), full_page=False)
        setup_seconds = perf_counter() - process_started

        experiment_started = perf_counter()

        def run(key: str, expected_placements: int) -> dict[str, Any]:
            turn_started = perf_counter()
            state = _turn(
                page,
                PROMPTS[key],
                predicate="""expected => {
                    const state = _trainFacilityLayoutAuthoringApp.session.getState();
                    const draft = state.generatedDraft || {};
                    const zones = state.layout && state.layout.zones || [];
                    const placements = state.layout && state.layout.placements || [];
                    return draft.status === 'complete'
                        && zones.length === 6
                        && placements.length === expected;
                }""",
                arg=expected_placements,
            )
            turns.append(
                {
                    "key": key,
                    "prompt": PROMPTS[key],
                    "elapsedSeconds": round(perf_counter() - turn_started, 3),
                    "draftRevision": state["generatedDraft"]["draftLayoutRevision"],
                    "placementCount": len(state["layout"].get("placements", [])),
                    "response": state["messages"].rsplit(PROMPTS[key], 1)[-1].strip(),
                }
            )
            return state

        departments = run("facility", 0)
        department_layout = deepcopy(departments["layout"])
        page.screenshot(path=str(screenshots["departments"]), full_page=False)

        receiving = run("receiving", 2)
        page.screenshot(path=str(screenshots["receiving"]), full_page=False)
        storage = run("storage", 6)
        page.screenshot(path=str(screenshots["storage"]), full_page=False)
        machining = run("machining", 9)
        page.screenshot(path=str(screenshots["machining"]), full_page=False)
        assembly = run("assembly", 13)
        page.screenshot(path=str(screenshots["assembly"]), full_page=False)
        inspection = run("inspection", 15)
        page.screenshot(path=str(screenshots["inspection"]), full_page=False)
        complete = run("dispatch", 17)
        experiment_seconds = perf_counter() - experiment_started
        page.screenshot(path=str(screenshots["complete"]), full_page=False)

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
        page.screenshot(path=str(screenshots["undo"]), full_page=False)
        browser.close()

    placements = complete["layout"]["placements"]
    placements_by_area = {
        label: [
            item
            for item in placements
            if (item.get("metadata") or {}).get("targetArea") == label
        ]
        for label in DEPARTMENT_LABELS
    }
    expected_assets = {
        label: _exact_catalog_asset(catalog, plan["asset"])
        for label, plan in PLACEMENT_PLAN.items()
    }
    run_ids = {
        str(state["generatedDraft"]["runId"])
        for state in (
            departments,
            receiving,
            storage,
            machining,
            assembly,
            inspection,
            complete,
        )
    }
    titles = {
        state["title"]
        for state in (
            departments,
            receiving,
            storage,
            machining,
            assembly,
            inspection,
            complete,
        )
    }
    checks = {
        "started_from_exact_blank_saved_layout": (
            not initial["layout"].get("zones")
            and not initial["layout"].get("placements")
            and initial["layout"] == initial["baseLayout"]
        ),
        "seven_streams_completed": stream_statuses == [200] * len(PROMPTS),
        "one_visible_conversation": len(titles) == 1,
        "one_durable_generation_run": len(run_ids) == 1,
        "six_exact_equal_area_departments": (
            [zone["label"] for zone in department_layout["zones"]]
            == DEPARTMENT_LABELS
            and department_layout["extensions"]["facilityPlan"]["widthMeters"]
            == 120.0
            and department_layout["extensions"]["facilityPlan"]["depthMeters"]
            == 90.0
        ),
        "every_department_populated_to_exact_quantity": all(
            len(placements_by_area[label]) == plan["quantity"]
            for label, plan in PLACEMENT_PLAN.items()
        ),
        "all_assets_bound_to_exact_catalog_revisions": all(
            item.get("assetId") == expected_assets[label]["assetId"]
            and item.get("assetDefinitionRevision")
            == expected_assets[label]["assetDefinitionRevision"]
            for label, records in placements_by_area.items()
            for item in records
        ),
        "all_roles_and_orientations_match_intent": all(
            (item.get("metadata") or {}).get("resourceRole") == plan["role"]
            and (item.get("metadata") or {}).get("orientationMode")
            == plan["orientation"]
            for label, plan in PLACEMENT_PLAN.items()
            for item in placements_by_area[label]
        ),
        "all_physical_placements_bounded_and_collision_free": (
            _placements_are_bounded_and_separate(complete["layout"], catalog)
        ),
        "department_geometry_preserved_during_population": (
            complete["layout"]["zones"] == department_layout["zones"]
        ),
        "access_claims_remain_unverified": all(
            (item.get("metadata") or {}).get("accessStatus") == "unverified"
            for item in placements
        ),
        "saved_layout_unchanged_until_approval": (
            complete["dirty"] is True
            and complete["canSave"] is True
            and complete["baseRevision"] == initial["baseRevision"]
            and complete["baseLayout"] == initial["baseLayout"]
        ),
        "one_undo_restores_exact_blank_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
            and not restored["layout"].get("zones")
            and not restored["layout"].get("placements")
        ),
        "no_response_interruption": "Response interrupted" not in complete["messages"],
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-all-departments-populated-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "timing": {
            "definition": "first Sage submit through final Sage response",
            "browserSetupSecondsExcluded": round(setup_seconds, 3),
            "experimentSeconds": round(experiment_seconds, 3),
            "turnCount": len(PROMPTS),
            "placementCount": len(placements),
            "placementsPerSecond": round(
                len(placements) / experiment_seconds, 3
            ),
        },
        "conversationTitle": next(iter(titles)) if len(titles) == 1 else sorted(titles),
        "runId": next(iter(run_ids)) if len(run_ids) == 1 else sorted(run_ids),
        "streamStatuses": stream_statuses,
        "turns": turns,
        "departments": {
            label: {
                "asset": plan["asset"],
                "quantity": plan["quantity"],
                "placementIds": [
                    item["placementId"] for item in placements_by_area[label]
                ],
            }
            for label, plan in PLACEMENT_PLAN.items()
        },
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
