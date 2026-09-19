from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.canonical import canonical_layout_bytes
from ai_inspector.facility_layout.spatial import (
    placement_spatial_records,
    polygon_contains_polygon,
    polygons_intersect,
)
from verify_facility_layout_g2_circulation import (
    _open_facility,
    _send,
    _wait_chat_idle,
)


EVIDENCE_ROOT = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "knowledge_foundation"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g4-asset-placement-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g4-asset-placement-browser"

PROMPTS = {
    "facility": (
        "Create a new 120 m by 90 m facility and divide it into four equal "
        "departments named Inbound, Machining, Assembly, and Dispatch."
    ),
    "subdivide": (
        "Divide Assembly into two equal child areas named Mechanical Build and "
        "Verification. Arrange them in one row."
    ),
    "machines": (
        "Place two CNC Milling Machines in Mechanical Build with their long "
        "side east-west for production."
    ),
    "storage": (
        "Stage three Pallet Racks in Machining with their long side north-south "
        "for storage."
    ),
    "authority_refusal": (
        "Place one Assembly Workbench in Verification with whatever OSHA "
        "clearance applies."
    ),
    "coordinate_refusal": (
        "Place one Assembly Workbench at x=10 z=10 in Verification."
    ),
    "ambiguous_asset": "Place two workbenches in Verification.",
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
    predicate: str | None = None,
    arg: Any = None,
) -> dict[str, Any]:
    prior = page.locator("#agentMessages").inner_text()
    _send(page, prompt)
    if predicate is not None:
        page.wait_for_function(predicate, arg=arg, timeout=360_000)
    _wait_chat_idle(page, prior)
    return _state(page)


def _catalog_index(catalog: list[dict[str, Any]]) -> dict[tuple[str, str], dict]:
    return {
        (str(item["assetId"]), str(item["assetDefinitionRevision"])): item
        for item in catalog
    }


def _zone_index(layout: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(zone["zoneId"]): zone
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping) and zone.get("zoneId")
    }


def _physical_records(
    layout: Mapping[str, Any],
    catalog: list[dict[str, Any]],
) -> list[tuple[str, Any]]:
    assets = _catalog_index(catalog)
    records = []
    for placement in layout.get("placements", []):
        key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        asset = assets.get(key)
        if asset is None:
            raise AssertionError(f"Missing exact catalog revision for {key}")
        for record in placement_spatial_records(placement, asset["definition"]):
            if record.record_kind == "physical":
                records.append((str(placement["placementId"]), record))
    return records


def _placements_are_bounded_and_separate(
    layout: Mapping[str, Any],
    catalog: list[dict[str, Any]],
) -> bool:
    zones = _zone_index(layout)
    records = _physical_records(layout, catalog)
    by_placement = {}
    for placement_id, record in records:
        by_placement.setdefault(placement_id, []).append(record)
    for placement in layout.get("placements", []):
        metadata = placement.get("metadata") or {}
        zone = zones.get(str(metadata.get("targetZoneId") or ""))
        if zone is None:
            return False
        boundary = tuple(
            (float(point["x"]), float(point["z"]))
            for point in zone.get("boundary", [])
        )
        if not all(
            polygon_contains_polygon(boundary, record.polygon)
            for record in by_placement.get(placement["placementId"], [])
        ):
            return False
    for index, (left_id, left) in enumerate(records):
        for right_id, right in records[index + 1 :]:
            if left_id == right_id:
                continue
            vertical_overlap = not (
                left.maximum_y <= right.minimum_y
                or right.maximum_y <= left.minimum_y
            )
            if vertical_overlap and polygons_intersect(
                left.polygon, right.polygon
            ):
                return False
    return True


def verify(app_url: str, output: Path, screenshot_root: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "areas": screenshot_root / "01-g3-target-areas.png",
        "machines": screenshot_root / "02-g4-machines.png",
        "resources": screenshot_root / "03-g4-resources.png",
        "refusals": screenshot_root / "04-g4-refusals.png",
    }
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []
    turns = []

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

        def run(
            key: str,
            *,
            predicate: str | None = None,
            arg: Any = None,
        ) -> dict[str, Any]:
            state = _turn(page, PROMPTS[key], predicate=predicate, arg=arg)
            turns.append(
                {
                    "key": key,
                    "prompt": PROMPTS[key],
                    "draftRevision": (
                        (state.get("generatedDraft") or {}).get(
                            "draftLayoutRevision"
                        )
                    ),
                    "zoneCount": len(state["layout"].get("zones", [])),
                    "placementCount": len(
                        state["layout"].get("placements", [])
                    ),
                    "response": state["messages"].rsplit(
                        PROMPTS[key], 1
                    )[-1].strip(),
                }
            )
            return state

        facility = run(
            "facility",
            predicate="""() => {
                const s = _trainFacilityLayoutAuthoringApp.session.getState();
                const labels = (s.layout && s.layout.zones || []).map(z => z.label);
                return s.generatedDraft && s.generatedDraft.status === 'complete'
                    && labels.length === 4
                    && labels.includes('Inbound')
                    && labels.includes('Machining')
                    && labels.includes('Assembly')
                    && labels.includes('Dispatch');
            }""",
        )
        subdivided = run(
            "subdivide",
            predicate="""() => {
                const s = _trainFacilityLayoutAuthoringApp.session.getState();
                const labels = (s.layout && s.layout.zones || []).map(z => z.label);
                return labels.length === 6
                    && labels.includes('Mechanical Build')
                    && labels.includes('Verification');
            }""",
        )
        page.screenshot(path=str(screenshots["areas"]), full_page=False)
        zones_before_assets = deepcopy(subdivided["layout"]["zones"])
        other_collections_before_assets = {
            field: deepcopy(subdivided["layout"].get(field, []))
            for field in (
                "routes",
                "floorMarkings",
                "utilityNetworks",
                "processBindings",
                "groups",
            )
        }

        machines = run(
            "machines",
            predicate="""() => {
                const s = _trainFacilityLayoutAuthoringApp.session.getState();
                const p = s.layout && s.layout.placements || [];
                return p.length === 2 && p.every(item =>
                    item.assetId === 'asset-cnc-mill'
                    && item.metadata
                    && item.metadata.generatedBy === 'facility_asset_placement_g4'
                );
            }""",
        )
        page.screenshot(path=str(screenshots["machines"]), full_page=False)
        resources = run(
            "storage",
            predicate="""() => {
                const s = _trainFacilityLayoutAuthoringApp.session.getState();
                const p = s.layout && s.layout.placements || [];
                return p.length === 5
                    && p.filter(item => item.assetId === 'asset-pallet-rack').length === 3;
            }""",
        )
        page.screenshot(path=str(screenshots["resources"]), full_page=False)

        revision_before_refusals = resources["generatedDraft"][
            "draftLayoutRevision"
        ]
        authority = run(
            "authority_refusal",
            predicate="""() => document.getElementById('agentMessages')
                .innerText.includes('cannot claim or invent equipment safety')""",
        )
        coordinate = run(
            "coordinate_refusal",
            predicate="""() => document.getElementById('agentMessages')
                .innerText.includes('cannot accept asset coordinates')""",
        )
        ambiguous = run(
            "ambiguous_asset",
            predicate="""() => document.getElementById('agentMessages')
                .innerText.includes('one exact authorized catalog asset')""",
        )
        page.screenshot(path=str(screenshots["refusals"]), full_page=False)

        restored = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('undo');
                const s = _trainFacilityLayoutAuthoringApp.session.getState();
                return {
                    baseRevision: s.baseRevision,
                    dirty: s.dirty,
                    layout: s.layout,
                    baseLayout: s.baseLayout,
                    generatedDraft: s.generatedDraft,
                };
            }"""
        )
        saved_after = page.evaluate(
            """async ({siteId, layoutId}) => await (await fetch(
                '/api/facility-layouts/' + encodeURIComponent(siteId)
                    + '/' + encodeURIComponent(layoutId),
                {cache: 'no-store'}
            )).json()""",
            {
                "siteId": bootstrap["siteId"],
                "layoutId": bootstrap["layoutId"],
            },
        )
        browser.close()

    placements = resources["layout"]["placements"]
    machine_placements = [
        item for item in placements if item["assetId"] == "asset-cnc-mill"
    ]
    rack_placements = [
        item for item in placements if item["assetId"] == "asset-pallet-rack"
    ]
    run_ids = {
        state["generatedDraft"]["runId"]
        for state in (facility, subdivided, machines, resources)
    }
    checks = {
        "all_streams_completed": stream_statuses == [200] * len(PROMPTS),
        "one_visible_conversation": len(
            {state["title"] for state in (facility, subdivided, machines, resources)}
        )
        == 1,
        "one_durable_generation_run": len(run_ids) == 1,
        "exact_catalog_revisions_bound": all(
            (
                item["assetId"], item["assetDefinitionRevision"]
            )
            in _catalog_index(catalog)
            for item in placements
        ),
        "g3_hierarchy_and_other_collections_preserved": (
            resources["layout"]["zones"] == zones_before_assets
            and all(
                resources["layout"].get(field, []) == value
                for field, value in other_collections_before_assets.items()
            )
        ),
        "two_machines_in_named_child_area": (
            len(machine_placements) == 2
            and all(
                item["metadata"]["targetArea"] == "Mechanical Build"
                and item["metadata"]["resourceRole"] == "production"
                and item["metadata"]["orientationMode"]
                == "long_side_east_west"
                for item in machine_placements
            )
        ),
        "three_storage_racks_in_macro_department": (
            len(rack_placements) == 3
            and all(
                item["metadata"]["targetArea"] == "Machining"
                and item["metadata"]["resourceRole"] == "storage"
                and item["metadata"]["orientationMode"]
                == "long_side_north_south"
                for item in rack_placements
            )
        ),
        "physical_geometry_bounded_and_collision_free": (
            _placements_are_bounded_and_separate(resources["layout"], catalog)
        ),
        "access_claims_remain_unverified": (
            all(
                item["metadata"]["accessStatus"] == "unverified"
                and item["metadata"]["clearanceEvidenceComplete"] is False
                for item in placements
            )
            and "Access remains unverified" in resources["messages"]
        ),
        "authority_geometry_and_ambiguity_refuse_without_mutation": (
            authority["generatedDraft"]["draftLayoutRevision"]
            == revision_before_refusals
            and coordinate["generatedDraft"]["draftLayoutRevision"]
            == revision_before_refusals
            and ambiguous["generatedDraft"]["draftLayoutRevision"]
            == revision_before_refusals
            and "cannot claim or invent" in authority["messages"].casefold()
            and "cannot accept asset coordinates" in coordinate[
                "messages"
            ].casefold()
            and "one exact authorized catalog asset" in ambiguous[
                "messages"
            ].casefold()
        ),
        "saved_layout_unchanged_until_approval": (
            canonical_layout_bytes(saved_after["layout"])
            == canonical_layout_bytes(initial["baseLayout"])
        ),
        "one_undo_restores_exact_blank_base": (
            restored["dirty"] is False
            and canonical_layout_bytes(restored["layout"])
            == canonical_layout_bytes(initial["baseLayout"])
        ),
        "no_browser_or_http_errors": (
            not console_errors
            and not page_errors
            and not failed_responses
        ),
    }
    evidence = {
        "schemaVersion": 1,
        "gate": "G4",
        "scope": "asset_placement_and_department_resources",
        "appUrl": app_url,
        "prompts": PROMPTS,
        "turns": turns,
        "checks": checks,
        "summary": {
            "passed": sum(checks.values()),
            "total": len(checks),
            "placementCount": len(placements),
            "accessValidatedCount": sum(
                item["metadata"]["accessStatus"] == "validated"
                for item in placements
            ),
            "accessUnverifiedCount": sum(
                item["metadata"]["accessStatus"] == "unverified"
                for item in placements
            ),
            "streamStatuses": stream_statuses,
            "failedResponses": failed_responses,
            "consoleErrors": console_errors,
            "pageErrors": page_errors,
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
    if not all(checks.values()):
        failed = [key for key, value in checks.items() if not value]
        raise AssertionError("G4 browser checks failed: " + ", ".join(failed))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8141/")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--screenshot-root", type=Path, default=DEFAULT_SCREENSHOT_ROOT
    )
    args = parser.parse_args()
    evidence = verify(args.url, args.output, args.screenshot_root)
    print(
        "G4 browser verification: "
        f"{evidence['summary']['passed']}/{evidence['summary']['total']} passed"
    )
    print(f"Evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
