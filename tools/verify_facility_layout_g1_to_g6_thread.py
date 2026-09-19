"""Verify qualified Facility gates G1 through G6 in one live Sage thread."""

from __future__ import annotations

import argparse
from copy import deepcopy
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
from ai_inspector.facility_layout.g1_planner import G1_PARTITION_TOLERANCE
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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "g1-to-g6-continuous-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "g1-to-g6-continuous-browser"

PROMPTS = {
    "facility": (
        "Create a new 120 m by 90 m facility with six equal-area departments "
        "named Inbound, Fabrication, Dispatch, Cell Hall, Test, and Packing. "
        "Arrange them in two rows: Inbound, Fabrication, and Dispatch in row 1; "
        "Cell Hall, Test, and Packing in row 2. Keep all departments equal in area."
    ),
    "material_aisle": (
        "Add a 4 m two-way material aisle from Inbound to Dispatch through "
        "Fabrication."
    ),
    "pedestrian_aisle": (
        "Add a 2 m two-way pedestrian walkway from Test to Packing."
    ),
    "subdivide": (
        "Divide Cell Hall into three equal child areas named Source Cell, "
        "Replica Cell A, and Replica Cell B. Arrange them in one row."
    ),
    "populate_inbound": (
        "Stage two Pallet Rack units in Inbound with their long side east-west "
        "for storage."
    ),
    "populate_fabrication": (
        "Place two CNC Milling Machines in Fabrication with their long side "
        "north-south for production."
    ),
    "populate_dispatch": "Stage one Electric Forklift in Dispatch.",
    "populate_test": (
        "Place one Assembled Laboratory Workstation in Test for inspection."
    ),
    "populate_packing": (
        "Stage two 400 x 1540 Modular Conveyor units in Packing with their long "
        "side east-west."
    ),
    "populate_source": (
        "Place three Assembly Workbench 36 x 24 in units in Source Cell with "
        "their long side east-west for production."
    ),
    "compose_source": (
        "Arrange Source Cell as a straight-line layout for shortest travel with "
        "1 m spacing."
    ),
    "replicate": (
        "Replicate Source Cell into Replica Cell A and Replica Cell B."
    ),
    "conformance": (
        "Check whether Source Cell and its replicas still match their authored "
        "module snapshots."
    ),
    "authority": "Are these cell copies safe and OSHA compliant?",
    "coordinate": (
        "Copy Source Cell into Replica Cell A at x=20 m and z=20 m."
    ),
}

MACRO_LABELS = [
    "Inbound",
    "Fabrication",
    "Dispatch",
    "Cell Hall",
    "Test",
    "Packing",
]
CELL_LABELS = ["Source Cell", "Replica Cell A", "Replica Cell B"]
EXPECTED_COUNTS = {
    "Inbound": 2,
    "Fabrication": 2,
    "Dispatch": 1,
    "Test": 1,
    "Packing": 2,
    "Source Cell": 3,
    "Replica Cell A": 3,
    "Replica Cell B": 3,
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


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _zone(layout: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [item for item in layout["zones"] if item.get("label") == label]
    if len(matches) != 1:
        raise AssertionError(f"Expected one zone named {label!r}; got {len(matches)}")
    return matches[0]


def _zone_center(zone: dict[str, Any]) -> tuple[float, float]:
    xs = [float(item["x"]) for item in zone["boundary"]]
    zs = [float(item["z"]) for item in zone["boundary"]]
    return (min(xs) + max(xs)) / 2.0, (min(zs) + max(zs)) / 2.0


def _zone_area(zone: dict[str, Any]) -> float:
    xs = [float(item["x"]) for item in zone["boundary"]]
    zs = [float(item["z"]) for item in zone["boundary"]]
    return (max(xs) - min(xs)) * (max(zs) - min(zs))


def _parent_id(zone: dict[str, Any]) -> str | None:
    return (
        ((zone.get("extensions") or {}).get("knowledgeFoundation") or {}).get(
            "parentZoneId"
        )
    )


def _placements_by_area(layout: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in layout.get("placements", []):
        label = str((item.get("metadata") or {}).get("targetArea") or "")
        result.setdefault(label, []).append(item)
    return result


def _focus_cell_hall(page: Any) -> None:
    focused = page.evaluate(
        """() => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const state = app && app.session && app.session.getState();
            const adapter = app && app.workspace && app.workspace.topAdapter;
            const zone = state && state.layout && state.layout.zones
                && state.layout.zones.find(item => item.label === 'Cell Hall');
            if (!zone || !adapter || typeof adapter.worldToClient !== 'function'
                    || typeof adapter.zoomAt !== 'function'
                    || typeof adapter.panByPixels !== 'function') return false;
            const xs = zone.boundary.map(item => Number(item.x));
            const zs = zone.boundary.map(item => Number(item.z));
            const center = {
                x: (Math.min(...xs) + Math.max(...xs)) / 2,
                z: (Math.min(...zs) + Math.max(...zs)) / 2,
            };
            let point = adapter.worldToClient(center);
            if (!point || !adapter.zoomAt({clientX: point.x, clientY: point.y}, 2)) {
                return false;
            }
            point = adapter.worldToClient(center);
            const bounds = adapter.svg.getBoundingClientRect();
            adapter.panByPixels(
                bounds.left + bounds.width / 2 - point.x,
                bounds.top + bounds.height / 2 - point.y,
            );
            return true;
        }"""
    )
    if focused is not True:
        raise AssertionError("Could not focus the Cell Hall")
    page.wait_for_timeout(300)


def _module_geometry_matches(
    source_layout: dict[str, Any], replicated_layout: dict[str, Any]
) -> bool:
    source_zone = _zone(source_layout, "Source Cell")
    source_center = _zone_center(source_zone)
    source_placements = {
        item["placementId"]: item
        for item in source_layout["placements"]
        if (item.get("metadata") or {}).get("targetArea") == "Source Cell"
    }
    replicated_index = {
        item["placementId"]: item for item in replicated_layout["placements"]
    }
    for target_label in ("Replica Cell A", "Replica Cell B"):
        target_zone = _zone(replicated_layout, target_label)
        module = (target_zone.get("extensions") or {}).get("cellModule") or {}
        target_center = _zone_center(target_zone)
        delta_x = target_center[0] - source_center[0]
        delta_z = target_center[1] - source_center[1]
        mapping = {
            item["sourcePlacementId"]: item["copiedPlacementId"]
            for item in module.get("placementIdMap", [])
        }
        if set(mapping) != set(source_placements):
            return False
        if len(set(mapping.values())) != len(mapping):
            return False
        for source_id, copied_id in mapping.items():
            source = source_placements[source_id]
            copied = replicated_index.get(copied_id)
            if copied is None or copied_id in source_placements:
                return False
            source_position = source["transform"]["position"]
            copied_position = copied["transform"]["position"]
            if abs(float(copied_position["x"]) - float(source_position["x"]) - delta_x) > 1e-6:
                return False
            if abs(float(copied_position["z"]) - float(source_position["z"]) - delta_z) > 1e-6:
                return False
            if copied["assetId"] != source["assetId"]:
                return False
            if copied["assetDefinitionRevision"] != source["assetDefinitionRevision"]:
                return False
            if copied["transform"]["quaternion"] != source["transform"]["quaternion"]:
                return False
            metadata = copied.get("metadata") or {}
            if metadata.get("generatedBy") != "facility_cell_replication_g6":
                return False
            if metadata.get("sourcePlacementId") != source_id:
                return False
            source_snap = source.get("snapRelationship")
            copied_snap = copied.get("snapRelationship")
            if isinstance(source_snap, dict):
                expected_snap = deepcopy(source_snap)
                support = expected_snap.get("supportPlacementId")
                if support:
                    expected_snap["supportPlacementId"] = mapping[support]
                if copied_snap != expected_snap:
                    return False
            elif copied_snap is not None:
                return False
    return True


def verify(app_url: str, output: Path, screenshot_root: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshots = {
        "g1": screenshot_root / "01-g1-departments.png",
        "g2": screenshot_root / "02-g2-circulation.png",
        "g3": screenshot_root / "03-g3-cell-areas.png",
        "g4": screenshot_root / "04-g4-populated-source.png",
        "g5": screenshot_root / "05-g5-qualified-source.png",
        "g6": screenshot_root / "06-g6-replicated-cells.png",
        "conformance": screenshot_root / "07-g6-conformance.png",
        "authority": screenshot_root / "08-g6-authority-refusal.png",
        "coordinate": screenshot_root / "09-g6-coordinate-refusal.png",
        "undo": screenshot_root / "10-one-undo-blank.png",
    }
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []
    turns: list[dict[str, Any]] = []
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
        if initial["layout"].get("zones") or initial["layout"].get("placements"):
            raise AssertionError("G1-G6 proof requires the saved blank layout baseline")

        def run(
            key: str,
            *,
            predicate: str | None = None,
            arg: Any = None,
        ) -> dict[str, Any]:
            turn_started = perf_counter()
            state = _turn(page, PROMPTS[key], predicate=predicate, arg=arg)
            turns.append(
                {
                    "key": key,
                    "prompt": PROMPTS[key],
                    "elapsedSeconds": round(perf_counter() - turn_started, 3),
                    "draftRevision": (
                        (state.get("generatedDraft") or {}).get(
                            "draftLayoutRevision"
                        )
                    ),
                    "zoneCount": len(state["layout"].get("zones") or []),
                    "routeCount": len(state["layout"].get("routes") or []),
                    "placementCount": len(
                        state["layout"].get("placements") or []
                    ),
                    "response": state["messages"].rsplit(
                        PROMPTS[key], 1
                    )[-1].strip(),
                }
            )
            return state

        g1 = run(
            "facility",
            predicate="""labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const zones = state.layout && state.layout.zones || [];
                return state.generatedDraft && state.generatedDraft.status === 'complete'
                    && zones.length === labels.length
                    && labels.every(label => zones.some(zone => zone.label === label));
            }""",
            arg=MACRO_LABELS,
        )
        page.screenshot(path=str(screenshots["g1"]), full_page=False)

        run(
            "material_aisle",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.routes || []).length === 1;
            }""",
        )
        g2 = run(
            "pedestrian_aisle",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.routes || []).length === 2;
            }""",
        )
        page.screenshot(path=str(screenshots["g2"]), full_page=False)

        g3 = run(
            "subdivide",
            predicate="""labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const zones = state.layout && state.layout.zones || [];
                return labels.every(label => zones.some(zone => zone.label === label));
            }""",
            arg=CELL_LABELS,
        )
        page.screenshot(path=str(screenshots["g3"]), full_page=False)

        expected_total = 0
        g4 = g3
        for key, target, quantity in (
            ("populate_inbound", "Inbound", 2),
            ("populate_fabrication", "Fabrication", 2),
            ("populate_dispatch", "Dispatch", 1),
            ("populate_test", "Test", 1),
            ("populate_packing", "Packing", 2),
            ("populate_source", "Source Cell", 3),
        ):
            expected_total += quantity
            g4 = run(
                key,
                predicate="""expected => {
                    const state = _trainFacilityLayoutAuthoringApp.session.getState();
                    const placements = state.layout && state.layout.placements || [];
                    const targetCount = placements.filter(item => {
                        const metadata = item.metadata || {};
                        return metadata.targetArea === expected.target;
                    }).length;
                    return placements.length === expected.total
                        && targetCount === expected.quantity;
                }""",
                arg={
                    "target": target,
                    "total": expected_total,
                    "quantity": quantity,
                },
            )
        _focus_cell_hall(page)
        page.screenshot(path=str(screenshots["g4"]), full_page=False)

        g5 = run(
            "compose_source",
            predicate="""previousRevision => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const draft = state.generatedDraft || {};
                const zones = state.layout && state.layout.zones || [];
                const source = zones.find(zone => zone.label === 'Source Cell');
                const provenance = source && source.extensions
                    && source.extensions.layoutProvenance || {};
                return draft.status === 'complete'
                    && String(draft.draftLayoutRevision || '') !== previousRevision
                    && provenance.command === 'cell_layout'
                    && provenance.authoredStrategy === 'line';
            }""",
            arg=g4["generatedDraft"]["draftLayoutRevision"],
        )
        _focus_cell_hall(page)
        page.screenshot(path=str(screenshots["g5"]), full_page=False)

        g6 = run(
            "replicate",
            predicate="""previousRevision => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const draft = state.generatedDraft || {};
                const zones = state.layout && state.layout.zones || [];
                const replicas = ['Replica Cell A', 'Replica Cell B'].map(
                    label => zones.find(zone => zone.label === label)
                );
                return draft.status === 'complete'
                    && String(draft.draftLayoutRevision || '') !== previousRevision
                    && replicas.every(zone => zone && zone.extensions
                        && zone.extensions.cellModule)
                    && (state.layout && state.layout.placements || []).length === 17;
            }""",
            arg=g5["generatedDraft"]["draftLayoutRevision"],
        )
        _focus_cell_hall(page)
        page.screenshot(path=str(screenshots["g6"]), full_page=False)

        conformance = run("conformance")
        _focus_cell_hall(page)
        page.screenshot(path=str(screenshots["conformance"]), full_page=False)

        authority_revision = conformance["generatedDraft"]["draftLayoutRevision"]
        authority = run("authority")
        _focus_cell_hall(page)
        page.screenshot(path=str(screenshots["authority"]), full_page=False)

        coordinate = run("coordinate")
        _focus_cell_hall(page)
        page.screenshot(path=str(screenshots["coordinate"]), full_page=False)

        final_bootstrap = page.evaluate(
            """async () => await (await fetch('/api/facility-layout-bootstrap', {
                cache: 'no-store'
            })).json()"""
        )
        restored = page.evaluate(
            """async () => {
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('undo');
                await _trainFacilityLayoutAuthoringApp.workspace.executeCommand('fit');
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

    g1_zones = {item["label"]: item for item in g1["layout"]["zones"]}
    child_zones = [_zone(g3["layout"], label) for label in CELL_LABELS]
    cell_hall = _zone(g3["layout"], "Cell Hall")
    cell_hall_xs = [float(item["x"]) for item in cell_hall["boundary"]]
    cell_hall_zs = [float(item["z"]) for item in cell_hall["boundary"]]
    equal_area_quantization_tolerance = (
        2.0
        * G1_PARTITION_TOLERANCE
        * max(
            max(cell_hall_xs) - min(cell_hall_xs),
            max(cell_hall_zs) - min(cell_hall_zs),
        )
    )
    placements_by_area = _placements_by_area(g6["layout"])
    pre_g6_placements = {
        item["placementId"]: item for item in g5["layout"]["placements"]
    }
    post_g6_placements = {
        item["placementId"]: item for item in g6["layout"]["placements"]
    }
    source_ids = {
        item["placementId"]
        for item in g5["layout"]["placements"]
        if (item.get("metadata") or {}).get("targetArea") == "Source Cell"
    }
    copied_ids = {
        item["placementId"]
        for item in g6["layout"]["placements"]
        if (item.get("metadata") or {}).get("generatedBy")
        == "facility_cell_replication_g6"
    }
    g5_boundaries = {
        item["zoneId"]: item["boundary"] for item in g5["layout"]["zones"]
    }
    g6_boundaries = {
        item["zoneId"]: item["boundary"] for item in g6["layout"]["zones"]
    }
    source_zone_before = _zone(g5["layout"], "Source Cell")
    source_zone_after = _zone(g6["layout"], "Source Cell")
    run_ids = {
        str(state["generatedDraft"]["runId"])
        for state in (g1, g2, g3, g4, g5, g6, conformance, authority, coordinate)
    }
    titles = {
        state["title"]
        for state in (g1, g2, g3, g4, g5, g6, conformance, authority, coordinate)
    }
    checks = {
        "saved_blank_baseline": (
            initial["baseLayout"] == initial["layout"]
            and not initial["layout"]["zones"]
            and not initial["layout"]["routes"]
            and not initial["layout"]["placements"]
        ),
        "g1_exact_facility_and_departments": (
            list(g1_zones) == MACRO_LABELS
            and g1["layout"]["extensions"]["facilityPlan"]["widthMeters"] == 120.0
            and g1["layout"]["extensions"]["facilityPlan"]["depthMeters"] == 90.0
            and len({_zone_area(item) for item in g1_zones.values()}) == 1
        ),
        "g2_two_semantic_routes": (
            len(g2["layout"]["routes"]) == 2
            and {item["corridorWidth"] for item in g2["layout"]["routes"]}
            == {2.0, 4.0}
        ),
        "g3_exact_empty_cell_areas": (
            all(_parent_id(item) == cell_hall["zoneId"] for item in child_zones)
            and abs(sum(_zone_area(item) for item in child_zones) - _zone_area(cell_hall)) < 1e-9
            and max(_zone_area(item) for item in child_zones)
            - min(_zone_area(item) for item in child_zones)
            <= equal_area_quantization_tolerance
            and not any(
                label in _placements_by_area(g3["layout"])
                for label in CELL_LABELS
            )
        ),
        "g4_populated_every_leaf_except_replication_targets": all(
            len(_placements_by_area(g4["layout"]).get(label, [])) == count
            for label, count in EXPECTED_COUNTS.items()
            if not label.startswith("Replica Cell")
        ),
        "g4_exact_revisions_and_spatial_fit": (
            all(
                any(
                    placement["assetId"] == asset["assetId"]
                    and placement["assetDefinitionRevision"]
                    == asset["assetDefinitionRevision"]
                    for asset in catalog
                )
                for placement in g4["layout"]["placements"]
            )
            and _placements_are_bounded_and_separate(g4["layout"], catalog)
        ),
        "g5_qualified_source_cell": (
            (source_zone_before.get("extensions") or {}).get(
                "layoutProvenance", {}
            ).get("command") == "cell_layout"
            and (source_zone_before.get("extensions") or {}).get(
                "layoutProvenance", {}
            ).get("authoredStrategy") == "line"
            and len(source_ids) == 3
        ),
        "g6_new_stable_identities_and_counts": (
            len(copied_ids) == 6
            and not source_ids.intersection(copied_ids)
            and len(g6["layout"]["placements"]) == 17
            and all(
                len(placements_by_area.get(label, [])) == count
                for label, count in EXPECTED_COUNTS.items()
            )
        ),
        "g6_exact_module_geometry_and_revisions": _module_geometry_matches(
            g5["layout"], g6["layout"]
        ),
        "g6_preserved_source_and_upstream_state": (
            source_zone_before == source_zone_after
            and g5_boundaries == g6_boundaries
            and g5["layout"]["routes"] == g6["layout"]["routes"]
            and g5["layout"]["floorMarkings"] == g6["layout"]["floorMarkings"]
            and all(
                post_g6_placements[placement_id] == placement
                for placement_id, placement in pre_g6_placements.items()
            )
        ),
        "g6_read_only_conformance_is_grounded": (
            "match their authored module snapshots" in conformance["messages"]
            and conformance["generatedDraft"]["draftLayoutRevision"]
            == g6["generatedDraft"]["draftLayoutRevision"]
        ),
        "g6_authority_and_coordinate_refusals_are_pure": (
            authority["generatedDraft"]["draftLayoutRevision"]
            == authority_revision
            and coordinate["generatedDraft"]["draftLayoutRevision"]
            == authority_revision
            and authority["layout"] == g6["layout"]
            and coordinate["layout"] == g6["layout"]
            and "cannot claim" in authority["messages"]
            and "cannot accept cell-copy coordinates" in coordinate["messages"]
        ),
        "one_continuous_conversation_and_run": len(titles) == 1 and len(run_ids) == 1,
        "saved_layout_never_changed": (
            initial_bootstrap["layout"]["revision"]
            == final_bootstrap["layout"]["revision"]
            == initial["baseRevision"]
            and initial_bootstrap["layout"]["layout"]
            == final_bootstrap["layout"]["layout"]
            == initial["baseLayout"]
        ),
        "one_undo_restored_exact_blank_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
            and not restored["layout"]["zones"]
            and not restored["layout"]["routes"]
            and not restored["layout"]["placements"]
        ),
        "all_streams_completed": stream_statuses == [200] * len(PROMPTS),
        "no_response_interruption": "Response interrupted" not in coordinate["messages"],
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-g1-to-g6-continuous-v1",
        "passed": all(checks.values()),
        "checks": checks,
        "timing": {
            "elapsedSeconds": round(perf_counter() - started, 3),
            "turnCount": len(PROMPTS),
        },
        "baseRevision": initial["baseRevision"],
        "baseLayoutRevision": _revision(initial["baseLayout"]),
        "runId": next(iter(run_ids)) if len(run_ids) == 1 else sorted(run_ids),
        "conversationTitle": (
            next(iter(titles)) if len(titles) == 1 else sorted(titles)
        ),
        "streamStatuses": stream_statuses,
        "turns": turns,
        "g6": {
            "sourcePlacementIds": sorted(source_ids),
            "copiedPlacementIds": sorted(copied_ids),
            "sourceRevision": g5["generatedDraft"]["draftLayoutRevision"],
            "replicatedRevision": g6["generatedDraft"]["draftLayoutRevision"],
            "moduleIds": sorted({
                ((_zone(g6["layout"], label).get("extensions") or {}).get(
                    "cellModule"
                ) or {}).get("moduleId")
                for label in ("Replica Cell A", "Replica Cell B")
            }),
        },
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
    evidence = verify(args.url, args.output, args.screenshot_root)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
