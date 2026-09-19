from __future__ import annotations

import pytest

from ai_inspector.facility_layout.motion_intent import (
    FACILITY_ACTIVITY_PLAYBACK_TOOL,
    FACILITY_MOTION_PLAYBACK_TOOL,
    activity_playback_tool_spec,
    motion_playback_tool_spec,
    parse_activity_playback_turn,
    parse_motion_playback_turn,
)


REVISION = "a" * 64


def _layout():
    return {
        "routes": [
            {
                "routeId": "rt-main-forklift",
                "label": "Main Forklift Boulevard",
                "routeKind": "forklift",
            },
            {
                "routeId": "rt-return-material",
                "label": "Material Return Loop",
                "routeKind": "material",
            },
            {
                "routeId": "rt-personnel",
                "label": "Personnel Spine",
                "routeKind": "pedestrian",
            },
        ],
        "placements": [
            {"placementId": "pl-forklift-01"},
            {"placementId": "pl-pallet-01"},
        ],
    }


def test_tool_contract_is_closed_and_coordinate_free():
    spec = motion_playback_tool_spec()
    assert spec["name"] == FACILITY_MOTION_PLAYBACK_TOOL
    schema = spec["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "route_id",
        "vehicle_profile_id",
        "vehicle_profile_revision",
        "vehicle_placement_id",
        "travel_direction",
    }
    assert not set(schema["properties"]) & {
        "x",
        "z",
        "poses",
        "speed",
        "duration",
    }


def test_activity_tool_contract_is_closed_and_coordinate_free():
    spec = activity_playback_tool_spec()
    assert spec["name"] == FACILITY_ACTIVITY_PLAYBACK_TOOL
    schema = spec["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "preset",
        "prototype_mode",
        "maximum_actors",
        "scenario_label",
    }
    assert not set(schema["properties"]) & {
        "x",
        "z",
        "poses",
        "speed",
        "duration",
    }


def test_prototype_factory_activity_selects_the_multi_actor_tool():
    result = parse_activity_playback_turn(
        "Play a prototype factory activity view with vehicles on authored "
        "material lanes and operators on authored pedestrian routes. Keep "
        "machines without revision-bound kinematic evidence stationary.",
        _layout(),
    )
    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": "mobile_actors_on_authored_routes",
        "prototypeMode": True,
        "maximumActors": 20,
        "scenarioLabel": "Prototype factory activity",
    }


def test_all_movement_prompt_selects_complete_reference_preset():
    layout = _layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    result = parse_activity_playback_turn(
        "Show the prototype movement candidate map for all moving objects in "
        "this reference factory. Use the existing operators and forklifts, "
        "display the pending handoff links, keep fixed machines stationary, "
        "and do not save.",
        layout,
    )
    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": "reference_complete_navigation",
        "prototypeMode": True,
        "maximumActors": 23,
        "scenarioLabel": "Complete reference movement",
    }


def test_reference_downstream_prompt_selects_eight_existing_operators():
    layout = _layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    result = parse_activity_playback_turn(
        "Play a prototype activity view for the existing operators in the "
        "Inspection, Packaging, and Finished Goods area. Use deterministic "
        "obstruction-free candidate journeys, loop each operator back to its "
        "existing start, do not duplicate placements, and do not save.",
        layout,
    )

    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": "reference_downstream_navigation",
        "prototypeMode": True,
        "maximumActors": 8,
        "scenarioLabel": "Downstream operator movement candidates",
    }


@pytest.mark.parametrize(
    ("prompt", "preset", "label"),
    [
        (
            "Play a prototype Finished Goods put-away cycle using the existing "
            "Electric Forklift. Pick the bottom-right staged pallet, use the "
            "cross aisle and the aisle between Rack Rows R03 and R04, place at "
            "the reviewed R04 shelf bay, return empty on the same physical "
            "aisle, keep the pallet truck parked, and do not save.",
            "reference_finished_goods_putaway",
            "Finished Goods put-away cycle",
        ),
        (
            "Play a prototype Finished Goods dispatch cycle using the existing "
            "Electric Forklift. Travel empty to the reviewed R04 shelf bay, "
            "retrieve the pallet, return loaded to staging on the same physical "
            "aisle, keep the pallet truck parked, and do not save.",
            "reference_finished_goods_dispatch",
            "Finished Goods dispatch cycle",
        ),
    ],
)
def test_finished_goods_vehicle_cycle_selects_exact_reference_preset(
    prompt, preset, label
):
    layout = _layout()
    layout["layoutId"] = "fl-reference-manual-20260812"

    result = parse_activity_playback_turn(prompt, layout)

    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": preset,
        "prototypeMode": True,
        "maximumActors": 1,
        "scenarioLabel": label,
    }


def test_receiving_vehicle_cycles_select_exact_reference_preset():
    layout = _layout()
    layout["layoutId"] = "fl-reference-manual-20260812"

    result = parse_activity_playback_turn(
        "Play prototype Receiving pallet-to-rack cycles using two existing "
        "Compact Green Forklifts. Pick inbound pallets from the left staging "
        "banks, travel through the access and cross aisles to the assigned "
        "storage bays, align and place, then return empty on the same aisles. "
        "Keep every other Receiving vehicle parked and do not save.",
        layout,
    )

    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": "reference_receiving_putaway",
        "prototypeMode": True,
        "maximumActors": 2,
        "scenarioLabel": "Receiving pallet-to-rack cycles",
    }


def test_packaging_cycle_prompt_selects_reviewed_downstream_preset():
    layout = _layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    result = parse_activity_playback_turn(
        "Play a prototype Packaging activity. Each existing Packaging operator "
        "picks from the left pallet, works at their current table, walks around "
        "the table's right side to place the finished product on the existing "
        "cart, then returns empty to the input pallet and repeats. Reuse existing "
        "operators and carts; do not duplicate placements and do not save.",
        layout,
    )

    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": "reference_downstream_navigation",
        "prototypeMode": True,
        "maximumActors": 8,
        "scenarioLabel": "Downstream operator movement candidates",
    }


def test_inspection_cycle_prompt_selects_reviewed_downstream_preset():
    layout = _layout()
    layout["layoutId"] = "fl-reference-manual-20260812"
    result = parse_activity_playback_turn(
        "Play the prototype Quality Inspection activity. Each existing "
        "Inspection operator picks from the left input table, loads and "
        "inspects the part at the current laboratory workstation, records "
        "and unloads the result, places the inspected part in the right "
        "container, then returns empty to the input table and repeats. Reuse "
        "existing operators and equipment; do not duplicate placements and "
        "do not save.",
        layout,
    )

    assert result["kind"] == "build"
    assert result["request"] == {
        "preset": "reference_downstream_navigation",
        "prototypeMode": True,
        "maximumActors": 8,
        "scenarioLabel": "Downstream operator movement candidates",
    }


def test_activity_actor_limit_is_preserved_without_motion_geometry():
    result = parse_activity_playback_turn(
        "Show a prototype factory activity playback with vehicles and people "
        "on authored routes, up to 10 actors.",
        _layout(),
    )
    assert result["kind"] == "build"
    assert result["request"]["maximumActors"] == 10


@pytest.mark.parametrize(
    ("prompt", "code"),
    [
        (
            "Simulate prototype factory activity and forklift congestion.",
            "facility_activity_simulation_unsupported",
        ),
        (
            "Show a safe prototype factory activity with vehicles on routes.",
            "facility_activity_safety_authority_missing",
        ),
        (
            "Show prototype factory activity throughput on the routes.",
            "facility_activity_throughput_authority_missing",
        ),
    ],
)
def test_activity_claims_fail_closed(prompt, code):
    result = parse_activity_playback_turn(prompt, _layout())
    assert result["kind"] == "refuse"
    assert result["code"] == code


def test_activity_requires_explicit_prototype_and_authored_routes():
    confirmation = parse_activity_playback_turn(
        "Show factory activity with vehicles on authored routes.",
        _layout(),
    )
    assert confirmation["kind"] == "ask"
    assert confirmation["code"] == (
        "facility_activity_prototype_confirmation_required"
    )
    missing_routes = parse_activity_playback_turn(
        "Show a prototype factory activity view with vehicles on routes.",
        {"routes": [], "placements": []},
    )
    assert missing_routes["kind"] == "ask"
    assert missing_routes["code"] == "facility_activity_authored_routes_required"


@pytest.mark.parametrize(
    ("prompt", "code"),
    [
        (
            "Can motion playback show how many pallets an hour this aisle moves?",
            "facility_motion_throughput_authority_missing",
        ),
        (
            "Does this route playback prove the traffic pattern is safe?",
            "facility_motion_safety_authority_missing",
        ),
        (
            "Does this motion replay prove the route network is compliant with OSHA?",
            "facility_motion_safety_authority_missing",
        ),
        (
            "Simulate the forklift fleet.",
            "facility_motion_simulation_unsupported",
        ),
        (
            "Show me forklift congestion at shift change.",
            "facility_motion_simulation_unsupported",
        ),
        (
            "Show continuous clearance during playback on this forklift route.",
            "facility_motion_continuous_clearance_unsupported",
        ),
        (
            "Replay the forklift route through x=40 and z=25.",
            "facility_motion_model_trajectory_refused",
        ),
        (
            "Drive the forklift route at 3 m/s.",
            "facility_motion_model_trajectory_refused",
        ),
    ],
)
def test_unsupported_claims_refuse_before_planning(prompt, code):
    result = parse_motion_playback_turn(prompt, _layout())
    assert result["kind"] == "refuse"
    assert result["code"] == code
    assert "Nothing changed" in result["response"]


def test_unrelated_show_request_is_not_stolen():
    assert parse_motion_playback_turn(
        "Show the drawing dimensions.", _layout()
    ) == {"kind": "not_applicable"}


@pytest.mark.parametrize(
    "prompt",
    [
        "Is this crossing safe for pedestrians?",
        "Place a 5 m material aisle at x=40, z=25.",
        "Make this aisle safe for any forklift.",
        "What if a direct route reduced travel by 20 percent?",
    ],
)
def test_non_playback_circulation_intent_is_not_stolen(prompt):
    assert parse_motion_playback_turn(prompt, _layout()) == {
        "kind": "not_applicable"
    }


def test_complete_proxy_request_resolves_exact_authored_route():
    result = parse_motion_playback_turn(
        "Replay a forklift on Main Forklift Boulevard using vehicle profile "
        f"forklift-standard revision {REVISION}.",
        _layout(),
    )
    assert result["kind"] == "build"
    assert result["proxy"] is True
    assert result["request"] == {
        "routeId": "rt-main-forklift",
        "vehicleProfileRef": {
            "vehicleProfileId": "forklift-standard",
            "vehicleProfileRevision": REVISION,
        },
        "travelDirection": "forward",
    }


def test_route_id_reverse_and_real_vehicle_are_preserved_as_identities():
    result = parse_motion_playback_turn(
        "Animate this forklift using vehicle placement ID pl-forklift-01 on route "
        "id rt-return-material in reverse using vehicle profile lift-2t revision "
        f"{REVISION}.",
        _layout(),
    )
    assert result["kind"] == "build"
    assert result["proxy"] is False
    assert result["request"]["vehiclePlacementId"] == "pl-forklift-01"
    assert result["request"]["travelDirection"] == "reverse"


def test_missing_or_nonexact_authority_asks_without_guessing():
    missing = parse_motion_playback_turn(
        "Replay a forklift on Main Forklift Boulevard.", _layout()
    )
    assert missing["kind"] == "ask"
    assert missing["code"] == "facility_motion_vehicle_profile_required"

    short = parse_motion_playback_turn(
        "Replay a forklift on Main Forklift Boulevard using vehicle profile "
        "forklift-standard revision abc123.",
        _layout(),
    )
    assert short["kind"] == "ask"
    assert "64-character" in short["response"]


def test_missing_route_never_defaults_to_the_only_or_first_route():
    result = parse_motion_playback_turn(
        "Replay a forklift using vehicle profile forklift-standard revision "
        f"{REVISION}.",
        _layout(),
    )
    assert result["kind"] == "ask"
    assert result["code"] == "facility_motion_route_required"


def test_pedestrian_route_and_unknown_vehicle_placement_fail_closed():
    pedestrian = parse_motion_playback_turn(
        "Replay a vehicle on Personnel Spine using vehicle profile cart revision "
        f"{REVISION}.",
        _layout(),
    )
    assert pedestrian["kind"] == "refuse"
    assert pedestrian["code"] == "facility_motion_route_not_vehicle_traversable"

    unknown = parse_motion_playback_turn(
        "Replay this forklift using vehicle placement pl-missing on Main Forklift "
        "Boulevard with vehicle profile forklift-standard revision "
        f"{REVISION}.",
        _layout(),
    )
    assert unknown["kind"] == "ask"
    assert unknown["code"] == "facility_motion_vehicle_placement_not_found"


def test_real_vehicle_language_requires_stable_placement_identity():
    result = parse_motion_playback_turn(
        "Show this forklift moving on Main Forklift Boulevard using vehicle profile "
        f"forklift-standard revision {REVISION}.",
        _layout(),
    )
    assert result["kind"] == "ask"
    assert result["code"] == "facility_motion_vehicle_placement_required"
