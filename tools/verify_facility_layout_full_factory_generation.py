"""Verify FLI-026 full-factory generation through one live Sage request."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_facility_knowledge_bytes,
)
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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "fli026-full-factory-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "fli026-full-factory-browser"

PROMPT = (
    "Create one complete unsaved prototype factory draft named FLI-026 Factory. "
    "Make the facility 120 m by 90 m with a 1 m grid and nine equal-area "
    "departments named North West, North Center, North East, Inbound, "
    "Restricted Area, Dispatch, South West, South Center, and South East. "
    "Arrange them in three rows: North West, North Center, and North East in "
    "row 1; Inbound, Restricted Area, and Dispatch in row 2; South West, South "
    "Center, and South East in row 3. Add a 4 m two-way material aisle named "
    "Inbound to Dispatch material aisle from Inbound to Dispatch, and a 2 m "
    "two-way pedestrian aisle named North to South pedestrian aisle from North "
    "Center to South Center. Add a 4 m by 3 m crossing named Central pedestrian "
    "crossing where those two named routes intersect. Divide South East into "
    "three equal child areas named Kitting, Electrical Build, and Test in one "
    "row. Place two exact Assembly Workbench assets in Electrical Build with "
    "their long side east-west for production, using physical fit only. Arrange "
    "Electrical Build using the smallest-envelope feasible option among line, "
    "L, and U layouts with exactly 1 m spacing. Replicate Electrical Build into "
    "the empty Kitting and Test areas. Keep the whole result as one unsaved "
    "prototype draft; do not save it."
)

MACRO_LABELS = [
    "North West",
    "North Center",
    "North East",
    "Inbound",
    "Restricted Area",
    "Dispatch",
    "South West",
    "South Center",
    "South East",
]
CHILD_LABELS = ["Kitting", "Electrical Build", "Test"]
ROUTE_LABELS = {
    "Inbound to Dispatch material aisle",
    "North to South pedestrian aisle",
}


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _state(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = window._trainFacilityLayoutAuthoringApp.session.getState();
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


def _zone(layout: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [item for item in layout.get("zones", []) if item.get("label") == label]
    if len(matches) != 1:
        raise AssertionError(f"Expected one zone named {label!r}; got {len(matches)}")
    return matches[0]


def _parent_id(zone: dict[str, Any]) -> str | None:
    return (
        ((zone.get("extensions") or {}).get("knowledgeFoundation") or {}).get(
            "parentZoneId"
        )
    )


def _placements_by_area(layout: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in layout.get("placements", []):
        area = str((item.get("metadata") or {}).get("targetArea") or "")
        result.setdefault(area, []).append(item)
    return result


def verify(app_url: str, output: Path, screenshot_root: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "blank": screenshot_root / "01-blank-before.png",
        "draft": screenshot_root / "02-complete-unsaved-factory.png",
        "undo": screenshot_root / "03-one-undo-blank.png",
    }
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []
    generation_requests: list[dict[str, Any]] = []
    started = perf_counter()

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

        def observe(response: Any) -> None:
            if "/api/agent/chat/v2/stream" in response.url:
                stream_statuses.append(response.status)
            if "/api/facility-layout-generation/" in response.url:
                generation_requests.append(
                    {
                        "method": response.request.method,
                        "status": response.status,
                        "url": response.url,
                    }
                )
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
        initial_bootstrap = page.evaluate(
            """async () => await (await fetch('/api/facility-layout-bootstrap', {
                cache: 'no-store'
            })).json()"""
        )
        catalog = initial_bootstrap["assetCatalog"]
        _open_facility(page)
        page.evaluate("() => window._selectAgent('deviation-analyst')")
        page.wait_for_selector("#agentInput", state="visible", timeout=30_000)
        initial = _state(page)
        if any(
            initial["layout"].get(key)
            for key in ("zones", "routes", "floorMarkings", "placements")
        ):
            raise AssertionError("FLI-026 proof requires the saved blank baseline")
        page.screenshot(path=str(screenshots["blank"]), full_page=False)

        prior_text = page.locator("#agentMessages").inner_text()
        turn_started = perf_counter()
        _send(page, PROMPT)
        page.wait_for_function(
            """expected => {
                const app = window._trainFacilityLayoutAuthoringApp;
                const state = app && app.session && app.session.getState();
                const layout = state && state.layout || {};
                const draft = state && state.generatedDraft || {};
                return draft.status === 'complete'
                    && draft.workflowScope === 'full_factory_generation'
                    && Array.isArray(draft.receiptChain)
                    && draft.receiptChain.length === 10
                    && (layout.zones || []).length === expected.zones
                    && (layout.routes || []).length === expected.routes
                    && (layout.floorMarkings || []).length === expected.markings
                    && (layout.placements || []).length === expected.placements;
            }""",
            arg={"zones": 12, "routes": 2, "markings": 1, "placements": 6},
            timeout=360_000,
        )
        response_text = _wait_chat_idle(page, prior_text)
        page.evaluate(
            """async () => {
                await window._trainFacilityLayoutAuthoringApp.workspace.executeCommand('fit');
            }"""
        )
        page.wait_for_timeout(500)
        complete = _state(page)
        page.screenshot(path=str(screenshots["draft"]), full_page=False)

        final_bootstrap = page.evaluate(
            """async () => await (await fetch('/api/facility-layout-bootstrap', {
                cache: 'no-store'
            })).json()"""
        )
        restored = page.evaluate(
            """async () => {
                await window._trainFacilityLayoutAuthoringApp.workspace.executeCommand('undo');
                await window._trainFacilityLayoutAuthoringApp.workspace.executeCommand('fit');
                const state = window._trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    baseRevision: state.baseRevision,
                    dirty: state.dirty,
                    generatedDraft: state.generatedDraft,
                    layout: state.layout,
                    baseLayout: state.baseLayout,
                };
            }"""
        )
        page.wait_for_timeout(350)
        page.screenshot(path=str(screenshots["undo"]), full_page=False)
        browser.close()

    layout = complete["layout"]
    draft = complete["generatedDraft"] or {}
    south_east = _zone(layout, "South East")
    child_zones = [_zone(layout, label) for label in CHILD_LABELS]
    by_area = _placements_by_area(layout)
    catalog_by_id = {
        item["assetId"]: item
        for item in catalog
        if isinstance(item, dict) and item.get("assetId")
    }
    route_labels = {str(item.get("label") or "") for item in layout["routes"]}
    marking = layout["floorMarkings"][0]
    seed = _zone(layout, "Electrical Build")
    replicas = [_zone(layout, "Kitting"), _zone(layout, "Test")]
    checks = {
        "blank_saved_baseline": (
            initial["layout"] == initial["baseLayout"]
            and not initial["dirty"]
            and not initial["layout"]["zones"]
        ),
        "one_live_sage_request": stream_statuses == [200],
        "one_durable_full_factory_run": (
            draft.get("workflowScope") == "full_factory_generation"
            and draft.get("status") == "complete"
            and len(draft.get("receiptChain") or []) == 10
            and bool(draft.get("fullFactoryProgramRevision"))
        ),
        "exact_envelope_and_macro_departments": (
            layout["displayName"] == "FLI-026 Factory"
            and layout["extensions"]["facilityPlan"]["widthMeters"] == 120.0
            and layout["extensions"]["facilityPlan"]["depthMeters"] == 90.0
            and [item["label"] for item in layout["zones"][:9]] == MACRO_LABELS
        ),
        "exact_subdivision_hierarchy": (
            len(layout["zones"]) == 12
            and all(_parent_id(item) == south_east["zoneId"] for item in child_zones)
        ),
        "exact_routes_and_crossing": (
            route_labels == ROUTE_LABELS
            and {float(item["corridorWidth"]) for item in layout["routes"]}
            == {2.0, 4.0}
            and marking.get("markingType") == "crosswalk"
            and float(marking.get("width")) == 4.0
            and float(marking.get("depth")) == 3.0
            and (marking.get("metadata") or {}).get("positionAuthority")
            == "derived_route_centerline_intersection"
        ),
        "exact_assets_fit_and_revision_bound": (
            len(layout["placements"]) == 6
            and all(len(by_area.get(label, [])) == 2 for label in CHILD_LABELS)
            and all(
                item.get("assetId") == "asset-workbench"
                and item.get("assetDefinitionRevision")
                == catalog_by_id["asset-workbench"]["assetDefinitionRevision"]
                for item in layout["placements"]
            )
            and _placements_are_bounded_and_separate(layout, catalog)
        ),
        "qualified_seed_and_replicas": (
            (seed.get("extensions") or {}).get("layoutProvenance", {}).get(
                "authoredStrategy"
            )
            in {"line", "l", "u"}
            and all(
                bool((item.get("extensions") or {}).get("cellModule"))
                for item in replicas
            )
        ),
        "valid_unsaved_review_boundary": (
            complete["dirty"] is True
            and complete["canSave"] is True
            and draft.get("saveEligibility") == "eligible"
            and bool(draft.get("cumulativeDiffHash"))
            and final_bootstrap["layout"]["revision"] == initial["baseRevision"]
            and final_bootstrap["layout"]["layout"] == initial["baseLayout"]
        ),
        "one_undo_restored_exact_blank_base": (
            restored["dirty"] is False
            and restored["generatedDraft"] is None
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
        ),
        "response_reports_complete_unsaved_factory": (
            "complete prototype factory" in response_text.lower()
            and "save" in response_text.lower()
            and "undo" in response_text.lower()
            and "Response interrupted" not in response_text
        ),
        "all_generation_requests_succeeded": (
            len(generation_requests) == 12
            and all(item["status"] == 200 for item in generation_requests)
        ),
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-fli026-full-factory-browser-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "prompt": PROMPT,
        "timing": {
            "fullFactoryTurnSeconds": round(perf_counter() - turn_started, 3),
            "totalSeconds": round(perf_counter() - started, 3),
        },
        "baseRevision": initial["baseRevision"],
        "baseLayoutRevision": _revision(initial["baseLayout"]),
        "run": {
            "runId": draft.get("runId"),
            "workflowScope": draft.get("workflowScope"),
            "programRevision": draft.get("fullFactoryProgramRevision"),
            "receiptCount": len(draft.get("receiptChain") or []),
            "cumulativeDiffHash": draft.get("cumulativeDiffHash"),
        },
        "draftCounts": {
            "zones": len(layout["zones"]),
            "routes": len(layout["routes"]),
            "floorMarkings": len(layout["floorMarkings"]),
            "placements": len(layout["placements"]),
        },
        "response": response_text.rsplit(PROMPT, 1)[-1].strip(),
        "streamStatuses": stream_statuses,
        "generationRequests": generation_requests,
        "errors": {
            "console": console_errors,
            "page": page_errors,
            "responses": failed_responses,
        },
        "screenshots": {
            key: str(path.relative_to(ROOT)).replace("\\", "/")
            for key, path in screenshots.items()
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
        "--screenshot-root", type=Path, default=DEFAULT_SCREENSHOT_ROOT
    )
    args = parser.parse_args()
    evidence = verify(
        args.url,
        args.output.resolve(),
        args.screenshot_root.resolve(),
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
