"""Time all qualified Facility gates plus complete leaf-area population."""

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

from ai_inspector.facility_layout.circulation import (
    analyze_primary_circulation_conflicts,
    analyze_primary_circulation_network,
    analyze_primary_circulation_obstacles,
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
DEFAULT_OUTPUT = EVIDENCE_ROOT / "all-qualified-populated-browser-evidence.json"
DEFAULT_SCREENSHOT_ROOT = EVIDENCE_ROOT / "all-qualified-populated-browser"

PROMPTS = {
    "facility": (
        "Create a new 120 m by 90 m facility with nine equal-area departments "
        "named North West, North Center, North East, Inbound, Restricted Area, "
        "Dispatch, South West, South Center, and South East. Arrange them in "
        "three rows: North West, North Center, and North East in row 1; Inbound, "
        "Restricted Area, and Dispatch in row 2; South West, South Center, and "
        "South East in row 3. Keep all departments equal in area."
    ),
    "conflict_forklift": (
        "Add a 3 m one-way forklift lane from North West to South East through "
        "North Center, Restricted Area, and South Center."
    ),
    "conflict_pedestrian": (
        "Add a 2 m two-way pedestrian walkway from North East to South West "
        "through North Center, Restricted Area, and South Center."
    ),
    "locate_conflict": "Where do the pedestrian and forklift routes conflict?",
    "resolve_conflict": (
        "Resolve the mixed-traffic conflict with 1.5 m separation without "
        "changing the departments. Compare both rerouting options and keep the "
        "shorter feasible result."
    ),
    "confirm_conflict": "Do the pedestrian and forklift routes still conflict?",
    "obstacle_route": "Add a 4 m material aisle from Inbound to Dispatch.",
    "locate_obstacle": (
        "Which routes intersect any machines or restricted regions?"
    ),
    "avoid_obstacle": (
        "Reroute that aisle around the Restricted Area with 1 m clearance. Keep "
        "the departments and route identity unchanged."
    ),
    "confirm_obstacle": (
        "Which routes still intersect machines or restricted regions after that reroute?"
    ),
    "crossing_route": (
        "Add a 2 m pedestrian walkway from North Center to South Center."
    ),
    "reachability": "Can material travel from Inbound to Dispatch?",
    "unmarked_crossings": "Which mixed-traffic crossings are unmarked?",
    "add_crosswalk": (
        "Add a 4 m by 3 m pedestrian crossing where the Inbound to Dispatch "
        "material aisle intersects the North Center to South Center pedestrian "
        "aisle."
    ),
    "marked_crossings": "Which mixed-traffic crossings are unmarked now?",
    "dead_ends": "Which departments are dead ends in the route network?",
    "authority": "Is this route network safe and compliant with fire code?",
    "subdivide": (
        "Divide South East into four equal child areas named Kitting, Mechanical "
        "Build, Electrical Build, and Test. Arrange them in two rows: Kitting and "
        "Mechanical Build in row 1; Electrical Build and Test in row 2."
    ),
    "nested_subdivide": (
        "Divide Mechanical Build into two equal child areas named Assembly Bench "
        "and Verification. Arrange them in one row."
    ),
    "place_machines": (
        "Place two CNC Milling Machines in Assembly Bench with their long side "
        "east-west for production."
    ),
    "place_storage": (
        "Stage three Pallet Racks in Kitting with their long side north-south "
        "for storage."
    ),
    "populate_north_west": "Stage 1 Electric Forklift in North West.",
    "populate_north_center": (
        "Place 2 Pallet Rack units in North Center with their long side "
        "east-west for storage."
    ),
    "populate_north_east": (
        "Place 1 CNC Lathe in North East with its long side north-south for "
        "production."
    ),
    "populate_inbound": "Stage 2 Electric Forklift units in Inbound.",
    "populate_dispatch": (
        "Stage 2 400 x 1540 Modular Conveyor units in Dispatch with their long "
        "side east-west."
    ),
    "populate_south_west": (
        "Place 2 Assembly Workbench 36 x 24 in units in South West with their "
        "long side east-west for production."
    ),
    "populate_south_center": (
        "Place 1 Assembled Laboratory Workstation in South Center for inspection."
    ),
    "populate_electrical_build": (
        "Place 2 Assembly Workbench 36 x 24 in units in Electrical Build with "
        "their long side east-west for production."
    ),
    "populate_test": (
        "Place 1 Assembled Laboratory Workstation in Test for inspection."
    ),
    "populate_verification": (
        "Place 1 Assembly Workbench 48 x 48 in asset in Verification for "
        "inspection."
    ),
    "ambiguous_asset": "Place two workbenches in Verification.",
    "compare_cell": (
        "Compare line, L, and U layouts in Electrical Build for the smallest "
        "envelope with 1 m spacing."
    ),
    "compose_cell": (
        "Arrange Electrical Build using the smallest-envelope feasible option "
        "among line, L, and U layouts with 1 m spacing."
    ),
    "convert_cell": (
        "Convert Electrical Build to an L-shaped layout for minimum movement "
        "with 1 m spacing."
    ),
    "cell_authority": "Is this cell safe and OSHA compliant?",
}

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
CHILD_LABELS = ["Kitting", "Mechanical Build", "Electrical Build", "Test"]
NESTED_LABELS = ["Assembly Bench", "Verification"]

ELIGIBLE_LEAF_AREAS = [
    "North West",
    "North Center",
    "North East",
    "Inbound",
    "Dispatch",
    "South West",
    "South Center",
    "Kitting",
    "Electrical Build",
    "Test",
    "Assembly Bench",
    "Verification",
]

NON_PLACEMENT_AREAS = ["Restricted Area", "South East", "Mechanical Build"]

PLACEMENT_PLAN = {
    "North West": ("Electric Forklift", 1, "staging", "auto"),
    "North Center": ("Pallet Rack", 2, "storage", "long_side_east_west"),
    "North East": ("CNC Lathe", 1, "production", "long_side_north_south"),
    "Inbound": ("Electric Forklift", 2, "staging", "auto"),
    "Dispatch": (
        "400 x 1540 Modular Conveyor",
        2,
        "staging",
        "long_side_east_west",
    ),
    "South West": (
        "Assembly Workbench 36 x 24 in",
        2,
        "production",
        "long_side_east_west",
    ),
    "South Center": (
        "Assembled Laboratory Workstation",
        1,
        "inspection",
        "auto",
    ),
    "Kitting": ("Pallet Rack", 3, "storage", "long_side_north_south"),
    "Electrical Build": (
        "Assembly Workbench 36 x 24 in",
        2,
        "production",
        "long_side_east_west",
    ),
    "Test": (
        "Assembled Laboratory Workstation",
        1,
        "inspection",
        "auto",
    ),
    "Assembly Bench": (
        "CNC Milling Machine",
        2,
        "production",
        "long_side_east_west",
    ),
    "Verification": (
        "Assembly Workbench 48 x 48 in",
        1,
        "inspection",
        "auto",
    ),
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


def _bounds(zone: dict[str, Any]) -> tuple[float, float, float, float]:
    xs = [float(point["x"]) for point in zone["boundary"]]
    zs = [float(point["z"]) for point in zone["boundary"]]
    return min(xs), min(zs), max(xs), max(zs)


def _area(zone: dict[str, Any]) -> float:
    minimum_x, minimum_z, maximum_x, maximum_z = _bounds(zone)
    return (maximum_x - minimum_x) * (maximum_z - minimum_z)


def _parent_id(zone: dict[str, Any]) -> str | None:
    return (
        ((zone.get("extensions") or {}).get("knowledgeFoundation") or {}).get(
            "parentZoneId"
        )
    )


def _route_by_label(layout: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [route for route in layout["routes"] if route.get("label") == label]
    if len(matches) != 1:
        raise AssertionError(f"Expected one route labelled {label!r}; got {len(matches)}")
    return matches[0]


def _crossing_for_pair(
    network: dict[str, Any], route_ids: set[str]
) -> dict[str, Any]:
    matches = [
        crossing
        for crossing in network["crossings"]
        if set(crossing["routeIds"]) == route_ids
        and crossing["intersectionType"] == "point"
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one point crossing for {sorted(route_ids)}; got {len(matches)}"
        )
    return matches[0]


def _child_group(
    layout: dict[str, Any], parent_label: str, labels: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    zones = {zone["label"]: zone for zone in layout["zones"]}
    parent = zones[parent_label]
    children = [zones[label] for label in labels]
    return parent, children


def _children_tile_parent(
    parent: dict[str, Any], children: list[dict[str, Any]]
) -> bool:
    parent_bounds = _bounds(parent)
    contained = all(
        _bounds(child)[0] >= parent_bounds[0] - 1e-9
        and _bounds(child)[1] >= parent_bounds[1] - 1e-9
        and _bounds(child)[2] <= parent_bounds[2] + 1e-9
        and _bounds(child)[3] <= parent_bounds[3] + 1e-9
        and _parent_id(child) == parent["zoneId"]
        for child in children
    )
    return contained and abs(sum(_area(child) for child in children) - _area(parent)) < 1e-9


def _exact_catalog_asset(
    catalog: list[dict[str, Any]], display_name: str
) -> dict[str, Any]:
    matches = [
        item
        for item in catalog
        if str(item.get("displayName") or "") == display_name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"Expected one catalog asset named {display_name!r}; got {len(matches)}"
        )
    return matches[0]


def verify(
    app_url: str,
    output: Path,
    screenshot_root: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_root.mkdir(parents=True, exist_ok=True)
    screenshot_paths = {
        "departments": screenshot_root / "01-g1-departments.png",
        "conflict": screenshot_root / "02-g21-conflict.png",
        "conflict_resolved": screenshot_root / "03-g21-resolved.png",
        "obstacle": screenshot_root / "04-g22-obstacle.png",
        "obstacle_rerouted": screenshot_root / "05-g22-rerouted.png",
        "crossing": screenshot_root / "06-g23-crossing.png",
        "crosswalk": screenshot_root / "07-g23-crosswalk.png",
        "subdivision": screenshot_root / "08-g3-subdivision.png",
        "nested": screenshot_root / "09-g3-nested-subdivision.png",
        "g4_machines": screenshot_root / "10-g4-machines.png",
        "g4_resources": screenshot_root / "11-g4-resources.png",
        "g4_macro_assets": screenshot_root / "12-g4-macro-assets.png",
        "g4_complete": screenshot_root / "13-g4-all-leaf-areas.png",
        "g4_ambiguity": screenshot_root / "14-g4-ambiguity.png",
        "g5_comparison": screenshot_root / "15-g5-comparison.png",
        "g5_composed": screenshot_root / "16-g5-composed.png",
        "g5_converted": screenshot_root / "17-g5-converted.png",
        "g5_authority": screenshot_root / "18-g5-authority.png",
        "undo": screenshot_root / "19-one-undo-blank.png",
    }
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    stream_statuses: list[int] = []
    turn_records: list[dict[str, Any]] = []
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
        setup_seconds = perf_counter() - process_started
        experiment_started = perf_counter()

        def run(
            key: str,
            *,
            predicate: str | None = None,
            arg: Any = None,
        ) -> dict[str, Any]:
            turn_started = perf_counter()
            state = _turn(page, PROMPTS[key], predicate=predicate, arg=arg)
            turn_records.append(
                {
                    "key": key,
                    "prompt": PROMPTS[key],
                    "draftRevision": (
                        (state.get("generatedDraft") or {}).get("draftLayoutRevision")
                    ),
                    "zoneCount": len((state.get("layout") or {}).get("zones") or []),
                    "routeCount": len((state.get("layout") or {}).get("routes") or []),
                    "markingCount": len(
                        (state.get("layout") or {}).get("floorMarkings") or []
                    ),
                    "placementCount": len(
                        (state.get("layout") or {}).get("placements") or []
                    ),
                    "elapsedSeconds": round(
                        perf_counter() - turn_started, 3
                    ),
                    "response": state["messages"].split(PROMPTS[key])[-1].strip(),
                }
            )
            return state

        departments = run(
            "facility",
            predicate="""labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const zones = state.layout && state.layout.zones || [];
                const plan = state.layout && state.layout.extensions
                    && state.layout.extensions.facilityPlan || {};
                const actual = zones.map(zone => zone.label);
                return state.generatedDraft
                    && state.generatedDraft.status === 'complete'
                    && Number(plan.widthMeters) === 120
                    && Number(plan.depthMeters) === 90
                    && actual.length === labels.length
                    && labels.every(label => actual.includes(label));
            }""",
            arg=MACRO_LABELS,
        )
        page.screenshot(path=str(screenshot_paths["departments"]), full_page=False)

        run(
            "conflict_forklift",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.routes || []).length === 1;
            }""",
        )
        conflict_routes = run(
            "conflict_pedestrian",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.routes || []).length === 2;
            }""",
        )
        conflict_before = analyze_primary_circulation_conflicts(
            conflict_routes["layout"]
        )
        conflict_read = run("locate_conflict")
        page.screenshot(path=str(screenshot_paths["conflict"]), full_page=False)

        conflict_revision = conflict_routes["generatedDraft"]["draftLayoutRevision"]
        conflict_resolved = run(
            "resolve_conflict",
            predicate="""priorRevision => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const draft = state.generatedDraft || {};
                return draft.status === 'complete'
                    && String(draft.draftLayoutRevision || '') !== priorRevision
                    && (state.layout && state.layout.routes || []).length === 2;
            }""",
            arg=conflict_revision,
        )
        conflict_after = analyze_primary_circulation_conflicts(
            conflict_resolved["layout"]
        )
        conflict_confirmed = run("confirm_conflict")
        page.screenshot(
            path=str(screenshot_paths["conflict_resolved"]), full_page=False
        )

        obstacle_route_state = run(
            "obstacle_route",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.routes || []).length === 3;
            }""",
        )
        obstacle_route = _route_by_label(
            obstacle_route_state["layout"], "Inbound to Dispatch material aisle"
        )
        obstacle_route_id = obstacle_route["routeId"]
        obstacle_before = analyze_primary_circulation_obstacles(
            obstacle_route_state["layout"]
        )
        obstacle_read = run("locate_obstacle")
        page.screenshot(path=str(screenshot_paths["obstacle"]), full_page=False)

        obstacle_centerline = deepcopy(obstacle_route["centerline"])
        obstacle_rerouted = run(
            "avoid_obstacle",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const routes = state.layout && state.layout.routes || [];
                const route = routes[routes.length - 1] || {};
                const aisle = route.extensions && route.extensions.facilityAisle || {};
                const awareness = aisle.obstacleAwareness || {};
                return Number(awareness.minimumClearanceMeters) === 1
                    && awareness.clearanceAuthority === 'user_authored';
            }""",
        )
        obstacle_route_after = _route_by_label(
            obstacle_rerouted["layout"], "Inbound to Dispatch material aisle"
        )
        obstacle_after = analyze_primary_circulation_obstacles(
            obstacle_rerouted["layout"]
        )
        obstacle_confirmed = run("confirm_obstacle")
        page.screenshot(
            path=str(screenshot_paths["obstacle_rerouted"]), full_page=False
        )

        crossing_routes = run(
            "crossing_route",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.routes || []).length === 4;
            }""",
        )
        crossing_route = _route_by_label(
            crossing_routes["layout"],
            "North Center to South Center pedestrian aisle",
        )
        crossing_route_ids = {obstacle_route_id, crossing_route["routeId"]}
        network_before = analyze_primary_circulation_network(crossing_routes["layout"])
        selected_crossing_before = _crossing_for_pair(
            network_before, crossing_route_ids
        )
        reachability = run("reachability")
        unmarked = run("unmarked_crossings")
        page.screenshot(path=str(screenshot_paths["crossing"]), full_page=False)

        marked = run(
            "add_crosswalk",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                return (state.layout && state.layout.floorMarkings || []).some(
                    item => item.markingType === 'crosswalk'
                );
            }""",
        )
        network_after = analyze_primary_circulation_network(marked["layout"])
        selected_crossing_after = _crossing_for_pair(network_after, crossing_route_ids)
        marked_query = run("marked_crossings")
        dead_ends = run("dead_ends")
        authority_revision = marked_query["generatedDraft"]["draftLayoutRevision"]
        authority = run("authority")
        page.screenshot(path=str(screenshot_paths["crosswalk"]), full_page=False)

        pre_g3_layout = deepcopy(authority["layout"])
        subdivided = run(
            "subdivide",
            predicate="""labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const zones = state.layout && state.layout.zones || [];
                const actual = zones.map(zone => zone.label);
                return zones.length === 13
                    && labels.every(label => actual.includes(label));
            }""",
            arg=CHILD_LABELS,
        )
        page.screenshot(path=str(screenshot_paths["subdivision"]), full_page=False)

        nested = run(
            "nested_subdivide",
            predicate="""labels => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const zones = state.layout && state.layout.zones || [];
                const actual = zones.map(zone => zone.label);
                return zones.length === 15
                    && labels.every(label => actual.includes(label));
            }""",
            arg=NESTED_LABELS,
        )
        page.screenshot(path=str(screenshot_paths["nested"]), full_page=False)

        pre_g4_layout = deepcopy(nested["layout"])
        machines = run(
            "place_machines",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const placements = state.layout && state.layout.placements || [];
                return placements.length === 2
                    && placements.every(item => {
                        const meta = item.metadata || {};
                        return meta.targetArea === 'Assembly Bench'
                            && meta.resourceRole === 'production'
                            && meta.orientationMode === 'long_side_east_west';
                    });
            }""",
        )
        page.screenshot(path=str(screenshot_paths["g4_machines"]), full_page=False)

        resources = run(
            "place_storage",
            predicate="""() => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const placements = state.layout && state.layout.placements || [];
                const racks = placements.filter(item => {
                    const meta = item.metadata || {};
                    return meta.targetArea === 'Kitting'
                        && meta.resourceRole === 'storage'
                        && meta.orientationMode === 'long_side_north_south';
                });
                return placements.length === 5 && racks.length === 3;
            }""",
        )
        page.screenshot(path=str(screenshot_paths["g4_resources"]), full_page=False)

        def populate(
            key: str,
            *,
            expected_total: int,
            target_area: str,
            expected_target_count: int,
        ) -> dict[str, Any]:
            return run(
                key,
                predicate="""expected => {
                    const state = _trainFacilityLayoutAuthoringApp.session.getState();
                    const placements = state.layout && state.layout.placements || [];
                    const target = placements.filter(item => {
                        const meta = item.metadata || {};
                        return meta.targetArea === expected.targetArea;
                    });
                    return placements.length === expected.total
                        && target.length === expected.targetCount;
                }""",
                arg={
                    "total": expected_total,
                    "targetArea": target_area,
                    "targetCount": expected_target_count,
                },
            )

        north_west = populate(
            "populate_north_west",
            expected_total=6,
            target_area="North West",
            expected_target_count=1,
        )
        north_center = populate(
            "populate_north_center",
            expected_total=8,
            target_area="North Center",
            expected_target_count=2,
        )
        north_east = populate(
            "populate_north_east",
            expected_total=9,
            target_area="North East",
            expected_target_count=1,
        )
        inbound_assets = populate(
            "populate_inbound",
            expected_total=11,
            target_area="Inbound",
            expected_target_count=2,
        )
        dispatch_assets = populate(
            "populate_dispatch",
            expected_total=13,
            target_area="Dispatch",
            expected_target_count=2,
        )
        page.screenshot(
            path=str(screenshot_paths["g4_macro_assets"]), full_page=False
        )

        south_west = populate(
            "populate_south_west",
            expected_total=15,
            target_area="South West",
            expected_target_count=2,
        )
        south_center = populate(
            "populate_south_center",
            expected_total=16,
            target_area="South Center",
            expected_target_count=1,
        )
        electrical_build = populate(
            "populate_electrical_build",
            expected_total=18,
            target_area="Electrical Build",
            expected_target_count=2,
        )
        test_assets = populate(
            "populate_test",
            expected_total=19,
            target_area="Test",
            expected_target_count=1,
        )
        all_populated = populate(
            "populate_verification",
            expected_total=20,
            target_area="Verification",
            expected_target_count=1,
        )
        population_seconds = perf_counter() - experiment_started
        page.screenshot(
            path=str(screenshot_paths["g4_complete"]), full_page=False
        )

        resource_revision = all_populated["generatedDraft"]["draftLayoutRevision"]
        ambiguity = run("ambiguous_asset")
        page.screenshot(path=str(screenshot_paths["g4_ambiguity"]), full_page=False)

        def focus_g5_target() -> None:
            focused = page.evaluate(
                """() => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    const adapter = app && app.workspace
                        && app.workspace.topAdapter;
                    if (!adapter || typeof adapter.worldToClient !== 'function'
                            || typeof adapter.zoomAt !== 'function'
                            || typeof adapter.panByPixels !== 'function') {
                        return false;
                    }
                    let point = adapter.worldToClient({ x: 90, z: 7.5 });
                    if (!point || !adapter.zoomAt({
                        clientX: point.x,
                        clientY: point.y,
                    }, 3)) return false;
                    point = adapter.worldToClient({ x: 90, z: 7.5 });
                    const bounds = adapter.svg.getBoundingClientRect();
                    adapter.panByPixels(
                        bounds.left + bounds.width / 2 - point.x,
                        bounds.top + bounds.height / 2 - point.y,
                    );
                    return true;
                }"""
            )
            if focused is not True:
                raise AssertionError("Could not focus the G5 target cell")
            page.wait_for_timeout(300)

        pre_g5_layout = deepcopy(ambiguity["layout"])
        comparison = run("compare_cell")
        focus_g5_target()
        page.screenshot(
            path=str(screenshot_paths["g5_comparison"]), full_page=False
        )

        composed = run(
            "compose_cell",
            predicate="""previousRevision => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const draft = state.generatedDraft || {};
                const zones = state.layout && state.layout.zones || [];
                const target = zones.find(zone => zone.label === 'Electrical Build');
                const extensions = target && target.extensions || {};
                const provenance = extensions.layoutProvenance || {};
                return draft.status === 'complete'
                    && String(draft.draftLayoutRevision || '') !== previousRevision
                    && provenance.command === 'cell_layout'
                    && Boolean(provenance.authoredStrategy);
            }""",
            arg=comparison["generatedDraft"]["draftLayoutRevision"],
        )
        focus_g5_target()
        page.screenshot(path=str(screenshot_paths["g5_composed"]), full_page=False)

        converted = run(
            "convert_cell",
            predicate="""previousRevision => {
                const state = _trainFacilityLayoutAuthoringApp.session.getState();
                const draft = state.generatedDraft || {};
                const zones = state.layout && state.layout.zones || [];
                const target = zones.find(zone => zone.label === 'Electrical Build');
                const provenance = target && target.extensions
                    && target.extensions.layoutProvenance || {};
                return draft.status === 'complete'
                    && String(draft.draftLayoutRevision || '') !== previousRevision
                    && provenance.command === 'cell_layout'
                    && provenance.authoredStrategy === 'l';
            }""",
            arg=composed["generatedDraft"]["draftLayoutRevision"],
        )
        focus_g5_target()
        page.screenshot(path=str(screenshot_paths["g5_converted"]), full_page=False)

        cell_revision = converted["generatedDraft"]["draftLayoutRevision"]
        cell_authority = run("cell_authority")
        full_thread_seconds = perf_counter() - experiment_started
        focus_g5_target()
        page.screenshot(path=str(screenshot_paths["g5_authority"]), full_page=False)

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
        page.screenshot(path=str(screenshot_paths["undo"]), full_page=False)
        browser.close()

    milestone_states = (
        departments,
        conflict_routes,
        conflict_resolved,
        obstacle_route_state,
        obstacle_rerouted,
        crossing_routes,
        marked,
        subdivided,
        nested,
        machines,
        resources,
        north_west,
        north_center,
        north_east,
        inbound_assets,
        dispatch_assets,
        south_west,
        south_center,
        electrical_build,
        test_assets,
        all_populated,
        ambiguity,
        comparison,
        composed,
        converted,
        cell_authority,
    )
    run_ids = {
        str(state["generatedDraft"]["runId"])
        for state in milestone_states
    }
    titles = {state["title"] for state in milestone_states}
    obstacle_before_for_route = [
        item
        for item in obstacle_before["conflicts"]
        if item.get("routeId") == obstacle_route_id
    ]
    obstacle_after_for_route = [
        item
        for item in obstacle_after["conflicts"]
        if item.get("routeId") == obstacle_route_id
    ]
    obstacle_confirmation = obstacle_confirmed["messages"].rsplit(
        PROMPTS["confirm_obstacle"], 1
    )[-1]
    crosswalks = [
        item
        for item in marked["layout"]["floorMarkings"]
        if item.get("markingType") == "crosswalk"
    ]
    macro_before_g3 = {
        zone["label"]: zone
        for zone in pre_g3_layout["zones"]
        if zone["label"] in MACRO_LABELS
    }
    macro_after_g3 = {
        zone["label"]: zone
        for zone in nested["layout"]["zones"]
        if zone["label"] in MACRO_LABELS
    }
    parent, children = _child_group(nested["layout"], "South East", CHILD_LABELS)
    nested_parent, nested_children = _child_group(
        nested["layout"], "Mechanical Build", NESTED_LABELS
    )
    catalog_revisions = {
        (str(item["assetId"]), str(item["assetDefinitionRevision"]))
        for item in catalog
    }
    placements = all_populated["layout"]["placements"]
    placements_by_area = {
        label: [
            item
            for item in placements
            if (item.get("metadata") or {}).get("targetArea") == label
        ]
        for label in ELIGIBLE_LEAF_AREAS
    }
    expected_assets = {
        label: _exact_catalog_asset(catalog, plan[0])
        for label, plan in PLACEMENT_PLAN.items()
    }
    machine_placements = [
        item
        for item in placements
        if (item.get("metadata") or {}).get("targetArea") == "Assembly Bench"
    ]
    rack_placements = [
        item
        for item in placements
        if (item.get("metadata") or {}).get("targetArea") == "Kitting"
    ]
    pre_g5_zones = {
        zone["zoneId"]: deepcopy(zone["boundary"])
        for zone in pre_g5_layout["zones"]
    }
    converted_zones = {
        zone["zoneId"]: zone for zone in converted["layout"]["zones"]
    }
    pre_g5_placements = {
        item["placementId"]: item for item in pre_g5_layout["placements"]
    }
    converted_placements = {
        item["placementId"]: item for item in converted["layout"]["placements"]
    }
    g5_composed_target_zone = next(
        zone
        for zone in composed["layout"]["zones"]
        if zone["label"] == "Electrical Build"
    )
    g5_composed_target_provenance = g5_composed_target_zone["extensions"][
        "layoutProvenance"
    ]
    g5_target_zone = next(
        zone
        for zone in converted["layout"]["zones"]
        if zone["label"] == "Electrical Build"
    )
    g5_target_provenance = g5_target_zone["extensions"]["layoutProvenance"]
    g5_target_members = [
        item
        for item in converted["layout"]["placements"]
        if (item.get("metadata") or {}).get("targetArea") == "Electrical Build"
    ]
    g5_member_ids = {item["placementId"] for item in g5_target_members}
    g4_preserved_fields = (
        "zones",
        "routes",
        "floorMarkings",
        "utilityNetworks",
        "processBindings",
        "groups",
    )
    checks = {
        "all_streams_completed": stream_statuses == [200] * len(PROMPTS),
        "one_visible_conversation": len(titles) == 1,
        "one_durable_generation_run": len(run_ids) == 1,
        "g1_exact_facility_and_macro_departments": (
            [zone["label"] for zone in departments["layout"]["zones"]]
            == MACRO_LABELS
            and departments["layout"]["extensions"]["facilityPlan"]["widthMeters"]
            == 120.0
            and departments["layout"]["extensions"]["facilityPlan"]["depthMeters"]
            == 90.0
        ),
        "g21_detected_mixed_traffic_conflict": (
            conflict_before["mixedTrafficConflictCount"] >= 1
            and conflict_before["status"] == "conflict"
            and "mixed-traffic geometric conflict" in conflict_read["messages"]
        ),
        "g21_resolved_with_exact_authored_separation": (
            conflict_after["mixedTrafficConflictCount"] == 0
            and conflict_after["status"] == "clear"
            and float(conflict_after["mixedTrafficPairMinimumSeparationMeters"])
            >= 1.5
            and "No mixed pedestrian/material geometric conflict"
            in conflict_confirmed["messages"]
        ),
        "g22_detected_protected_obstacle": (
            bool(obstacle_before_for_route)
            and any(
                item.get("obstacleKind") == "protected_zone"
                for item in obstacle_before_for_route
            )
            and "protected" in obstacle_read["messages"].casefold()
        ),
        "g22_rerouted_with_exact_clearance_and_identity": (
            obstacle_route_after["routeId"] == obstacle_route_id
            and obstacle_route_after["corridorWidth"] == 4.0
            and obstacle_route_after["centerline"] != obstacle_centerline
            and not obstacle_after_for_route
            and obstacle_route_after["extensions"]["facilityAisle"][
                "obstacleAwareness"
            ]["minimumClearanceMeters"]
            == 1.0
            and obstacle_route_after["extensions"]["facilityAisle"][
                "obstacleAwareness"
            ]["clearanceAuthority"]
            == "user_authored"
            and "Inbound to Dispatch material aisle" not in obstacle_confirmation
            and "route-to-obstacle geometric conflicts" in obstacle_confirmation
        ),
        "g23_directional_reachability_grounded": (
            "Dispatch is reachable from Inbound" in reachability["messages"]
            and "route-graph reachability only" in reachability["messages"]
        ),
        "g23_unmarked_point_crossing_derived": (
            selected_crossing_before["crosswalkCoverageStatus"] == "unmarked"
            and "unmarked" in unmarked["messages"]
        ),
        "g23_exact_crosswalk_bound_to_derived_crossing": (
            len(crosswalks) == 1
            and selected_crossing_after["crosswalkCoverageStatus"] == "marked"
            and crosswalks[0]["width"] == 4.0
            and crosswalks[0]["depth"] == 3.0
            and crosswalks[0]["metadata"]["dimensionAuthority"]
            == "user_authored"
            and crosswalks[0]["metadata"]["positionAuthority"]
            == "derived_route_centerline_intersection"
        ),
        "g23_network_analysis_and_authority_boundary": (
            "dead-end departments" in dead_ends["messages"]
            and "cannot claim" in authority["messages"]
            and "safe, adequate, compliant" in authority["messages"]
            and authority["generatedDraft"]["draftLayoutRevision"]
            == authority_revision
        ),
        "g3_preserved_macro_routes_and_markings": (
            macro_after_g3 == macro_before_g3
            and nested["layout"]["routes"] == pre_g3_layout["routes"]
            and nested["layout"]["floorMarkings"]
            == pre_g3_layout["floorMarkings"]
        ),
        "g3_exact_first_level_subdivision": (
            _children_tile_parent(parent, children)
            and max(_area(child) for child in children)
            - min(_area(child) for child in children)
            < 1e-9
        ),
        "g3_exact_nested_subdivision": (
            _children_tile_parent(nested_parent, nested_children)
            and max(_area(child) for child in nested_children)
            - min(_area(child) for child in nested_children)
            < 1e-9
        ),
        "g4_every_eligible_leaf_area_populated": (
            set(placements_by_area) == set(ELIGIBLE_LEAF_AREAS)
            and all(
                len(placements_by_area[label]) == plan[1]
                for label, plan in PLACEMENT_PLAN.items()
            )
        ),
        "g4_exact_revisions_roles_and_orientations": all(
            item.get("assetId") == expected_assets[label]["assetId"]
            and item.get("assetDefinitionRevision")
            == expected_assets[label]["assetDefinitionRevision"]
            and (item.get("metadata") or {}).get("resourceRole") == plan[2]
            and (item.get("metadata") or {}).get("orientationMode") == plan[3]
            and (
                str(item.get("assetId") or ""),
                str(item.get("assetDefinitionRevision") or ""),
            )
            in catalog_revisions
            for label, plan in PLACEMENT_PLAN.items()
            for item in placements_by_area[label]
        ),
        "g4_protected_and_container_areas_remain_unpopulated": not any(
            (item.get("metadata") or {}).get("targetArea")
            in NON_PLACEMENT_AREAS
            for item in placements
        ),
        "g4_physical_fit_is_bounded_and_collision_free": (
            _placements_are_bounded_and_separate(all_populated["layout"], catalog)
        ),
        "g4_preserved_all_prior_qualified_state": all(
            all_populated["layout"].get(field) == pre_g4_layout.get(field)
            for field in g4_preserved_fields
        ),
        "g4_access_claims_remain_unverified": (
            all(
                (item.get("metadata") or {}).get("accessStatus") == "unverified"
                for item in placements
            )
            and "Access remains unverified" in all_populated["messages"]
        ),
        "g4_ambiguity_left_the_draft_unchanged": (
            ambiguity["generatedDraft"]["draftLayoutRevision"]
            == resource_revision
            and ambiguity["layout"] == all_populated["layout"]
            and "exact authorized catalog asset" in ambiguity["messages"]
        ),
        "g5_comparison_was_read_only": (
            comparison["generatedDraft"]["draftLayoutRevision"]
            == resource_revision
            and comparison["layout"] == pre_g5_layout
            and "ranks first" in comparison["messages"]
            and "nothing changed" in comparison["messages"]
        ),
        "g5_composed_registered_strategy_with_exact_spacing": (
            g5_composed_target_provenance["command"] == "cell_layout"
            and g5_composed_target_provenance["authoredStrategy"] == "line"
            and g5_composed_target_provenance["parameters"]["preferredGapMeters"] == 1.0
            and g5_composed_target_provenance["parameters"]["preferredGapAuthority"]
            == "user_authored"
            and set(g5_composed_target_provenance["seedEntityIds"])
            == g5_member_ids
            and len(g5_target_members) == 2
            and "unsaved draft" in composed["messages"]
        ),
        "g5_follow_up_converted_only_the_cell_stage": (
            converted["generatedDraft"]["draftLayoutRevision"]
            != composed["generatedDraft"]["draftLayoutRevision"]
            and g5_target_provenance["authoredStrategy"] == "l"
            and g5_target_provenance["parameters"]["objective"]
            == "minimum_movement"
        ),
        "g5_preserved_upstream_geometry_and_resource_identity": (
            set(converted_zones) == set(pre_g5_zones)
            and all(
                converted_zones[zone_id]["boundary"] == boundary
                for zone_id, boundary in pre_g5_zones.items()
            )
            and converted["layout"]["routes"] == pre_g5_layout["routes"]
            and converted["layout"]["floorMarkings"]
            == pre_g5_layout["floorMarkings"]
            and set(converted_placements) == set(pre_g5_placements)
            and all(
                converted_placements[placement_id]["assetId"]
                == before["assetId"]
                and converted_placements[placement_id][
                    "assetDefinitionRevision"
                ] == before["assetDefinitionRevision"]
                and converted_placements[placement_id]["transform"][
                    "quaternion"
                ] == before["transform"]["quaternion"]
                for placement_id, before in pre_g5_placements.items()
            )
            and all(
                converted_placements[placement_id] == before
                for placement_id, before in pre_g5_placements.items()
                if placement_id not in g5_member_ids
            )
            and _placements_are_bounded_and_separate(
                converted["layout"], catalog
            )
        ),
        "g5_authority_refusal_left_the_cell_unchanged": (
            cell_authority["generatedDraft"]["draftLayoutRevision"]
            == cell_revision
            and cell_authority["layout"] == converted["layout"]
            and "cannot claim" in cell_authority["messages"]
            and "safe, compliant, ergonomic, optimal" in cell_authority[
                "messages"
            ]
        ),
        "draft_remained_unsaved": (
            cell_authority["dirty"] is True
            and cell_authority["canSave"] is True
            and cell_authority["baseRevision"] == initial["baseRevision"]
            and cell_authority["baseLayout"] == initial["baseLayout"]
        ),
        "one_undo_restored_exact_blank_base": (
            restored["dirty"] is False
            and restored["baseRevision"] == initial["baseRevision"]
            and restored["layout"] == initial["baseLayout"]
            and restored["baseLayout"] == initial["baseLayout"]
            and not restored["layout"]["zones"]
            and not restored["layout"]["routes"]
            and not restored["layout"]["floorMarkings"]
            and not restored["layout"]["placements"]
        ),
        "no_response_interruption": (
            "Response interrupted" not in cell_authority["messages"]
        ),
        "no_console_errors": not console_errors,
        "no_page_errors": not page_errors,
        "no_failed_responses": not failed_responses,
    }
    evidence = {
        "schemaVersion": "facility-layout-all-qualified-populated-v2",
        "passed": all(checks.values()),
        "checks": checks,
        "timing": {
            "definition": (
                "first Sage submit through final G5 authority-boundary response"
            ),
            "browserSetupSecondsExcluded": round(setup_seconds, 3),
            "populationExperimentSeconds": round(population_seconds, 3),
            "fullThreadIncludingAmbiguitySeconds": round(
                full_thread_seconds, 3
            ),
            "turnCountThroughPopulation": len(PROMPTS) - 5,
            "totalTurnCount": len(PROMPTS),
            "placementCount": len(placements),
        },
        "streamStatuses": stream_statuses,
        "conversationTitle": next(iter(titles)) if len(titles) == 1 else sorted(titles),
        "runId": next(iter(run_ids)) if len(run_ids) == 1 else sorted(run_ids),
        "turns": turn_records,
        "milestones": {
            "g1": {"zoneCount": 9},
            "g21": {
                "beforeConflictCount": conflict_before["mixedTrafficConflictCount"],
                "afterConflictCount": conflict_after["mixedTrafficConflictCount"],
                "minimumSeparationMeters": conflict_after[
                    "mixedTrafficPairMinimumSeparationMeters"
                ],
            },
            "g22": {
                "routeId": obstacle_route_id,
                "beforeConflictCount": len(obstacle_before_for_route),
                "afterConflictCount": len(obstacle_after_for_route),
                "minimumClearanceMeters": 1.0,
            },
            "g23": {
                "crossingId": selected_crossing_after["crossingId"],
                "coverageBefore": selected_crossing_before[
                    "crosswalkCoverageStatus"
                ],
                "coverageAfter": selected_crossing_after[
                    "crosswalkCoverageStatus"
                ],
                "crosswalkId": crosswalks[0]["markingId"] if crosswalks else None,
            },
            "g3": {
                "zoneCount": len(nested["layout"]["zones"]),
                "firstLevelParent": parent["zoneId"],
                "firstLevelChildren": [child["zoneId"] for child in children],
                "nestedParent": nested_parent["zoneId"],
                "nestedChildren": [child["zoneId"] for child in nested_children],
            },
            "g4": {
                "placementCount": len(placements),
                "eligibleLeafAreaCount": len(ELIGIBLE_LEAF_AREAS),
                "nonPlacementAreas": NON_PLACEMENT_AREAS,
                "placementsByArea": {
                    label: {
                        "asset": PLACEMENT_PLAN[label][0],
                        "quantity": len(placements_by_area[label]),
                        "placementIds": [
                            item["placementId"]
                            for item in placements_by_area[label]
                        ],
                    }
                    for label in ELIGIBLE_LEAF_AREAS
                },
                "accessValidatedCount": sum(
                    (item.get("metadata") or {}).get("accessStatus") == "validated"
                    for item in placements
                ),
                "accessUnverifiedCount": sum(
                    (item.get("metadata") or {}).get("accessStatus") == "unverified"
                    for item in placements
                ),
            },
            "g5": {
                "targetArea": "Electrical Build",
                "memberPlacementIds": sorted(g5_member_ids),
                "selectedStrategyAfterFollowUp": g5_target_provenance[
                    "authoredStrategy"
                ],
                "objectiveAfterFollowUp": g5_target_provenance[
                    "parameters"
                ]["objective"],
                "preferredGapMeters": g5_target_provenance["parameters"][
                    "preferredGapMeters"
                ],
                "preferredGapAuthority": g5_target_provenance[
                    "parameters"
                ]["preferredGapAuthority"],
                "processSequenceAuthority": g5_target_provenance[
                    "parameters"
                ]["processSequenceAuthority"],
                "cellRevisionBeforeAuthorityRefusal": cell_revision,
            },
        },
        "errors": {
            "console": console_errors,
            "page": page_errors,
            "failedResponses": failed_responses,
        },
        "screenshots": {
            key: value.relative_to(ROOT).as_posix()
            for key, value in screenshot_paths.items()
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
