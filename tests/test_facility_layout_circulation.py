from __future__ import annotations

from copy import deepcopy

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.circulation import (
    FacilityCirculationError,
    analyze_primary_circulation_network,
    analyze_primary_circulation_obstacles,
    analyze_primary_circulation_conflicts,
    compile_circulation_conflict_resolution_operations,
    compile_circulation_crossing_operations,
    compile_obstacle_aware_circulation_operations,
    compile_primary_circulation_operations,
    disconnected_department_labels,
    parse_circulation_turn,
    validate_circulation_conflict_resolution_result,
    validate_circulation_crossing_result,
    validate_obstacle_aware_circulation_result,
    validate_primary_circulation_result,
)
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.validate import validate_layout


def _empty_layout() -> dict:
    return create_layout_document(
        layout_id="fl-circulation",
        display_name="Empty Facility",
        association={"siteId": "site-a", "areaId": "main"},
        coordinate_frame={
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "floorAxes": ["+X", "+Z"],
            "datumId": "origin-a",
            "floorElevation": 0,
        },
        source_shell_ref={
            "shellId": "shell-a",
            "shellRevision": "a" * 64,
            "coordinateFrameFingerprint": "b" * 64,
        },
        policy_set_ref={
            "policySetId": "policy-a",
            "policySetRevision": "c" * 64,
        },
        created_at="2026-08-27T00:00:00Z",
    )


def _department_layout(labels: list[str] | None = None) -> dict:
    layout = _empty_layout()
    department_labels = labels or [
        "Receiving",
        "Machining",
        "Assembly",
        "Shipping",
    ]
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "Circulation Plant",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {
            "count": len(department_labels),
            "labels": department_labels,
            "proportions": [1.0 / len(department_labels)] * len(department_labels),
            "arrangement": "columns",
            "orientation": "horizontal",
        },
    )
    return apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _three_row_department_layout() -> dict:
    labels = [
        "Inbound",
        "Raw Materials",
        "Fabrication",
        "Subassembly",
        "Final Inspection",
        "Dispatch",
    ]
    layout = _empty_layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 150,
            "depth": 100,
            "sourceUnit": "m",
            "displayName": "Conflict Resolution Plant",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {
            "count": 6,
            "labels": labels,
            "proportions": [1 / 6] * 6,
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [
                {"labels": labels[0:2], "proportion": None},
                {"labels": labels[2:4], "proportion": None},
                {"labels": labels[4:6], "proportion": None},
            ],
        },
    )
    return apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _mixed_route_layout() -> dict:
    layout = _three_row_department_layout()
    prompts = [
        (
            "Add a 5 m one-way forklift lane from Inbound to Dispatch "
            "through Fabrication and Subassembly."
        ),
        (
            "Add a 2.5 m two-way pedestrian walkway from Raw Materials to "
            "Final Inspection through Subassembly."
        ),
    ]
    for prompt in prompts:
        request = parse_circulation_turn(prompt, layout)["request"]
        compiled = compile_primary_circulation_operations(layout, request)
        layout = apply_facility_layout_operations(
            layout,
            compiled["operations"],
            base_revision=layout_revision(layout),
        )["document"]
    return layout


def _point_crossing_layout() -> dict:
    layout = _department_layout()
    zones = {zone["label"]: zone["zoneId"] for zone in layout["zones"]}
    operations = [
        {
            "op": "add_aisle",
            "routeId": "rt-g23-material",
            "aisle": {
                "label": "Main material aisle",
                "aisleKind": "material",
                "direction": "two_way",
                "corridorWidth": 4,
                "centerline": [
                    {"x": 10, "y": 0, "z": 45},
                    {"x": 110, "y": 0, "z": 45},
                ],
                "color": "#d9a514",
                "clearanceEvidenceStatus": "unverified",
                "sourceZoneId": zones["Receiving"],
                "targetZoneId": zones["Shipping"],
                "viaZoneIds": [],
                "areaAccounting": "overlay",
                "widthAuthority": "user_authored",
            },
        },
        {
            "op": "add_aisle",
            "routeId": "rt-g23-pedestrian",
            "aisle": {
                "label": "Central pedestrian walkway",
                "aisleKind": "pedestrian",
                "direction": "two_way",
                "corridorWidth": 2,
                "centerline": [
                    {"x": 60, "y": 0, "z": 10},
                    {"x": 60, "y": 0, "z": 80},
                ],
                "color": "#2f9d62",
                "clearanceEvidenceStatus": "unverified",
                "sourceZoneId": zones["Machining"],
                "targetZoneId": zones["Assembly"],
                "viaZoneIds": [],
                "areaAccounting": "overlay",
                "widthAuthority": "user_authored",
            },
        },
    ]
    return apply_facility_layout_operations(
        layout,
        operations,
        base_revision=layout_revision(layout),
    )["document"]


def _obstacle_route_layout(*, route_kind: str = "material") -> dict:
    labels = [
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
    layout = _empty_layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "Obstacle Plant",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {
            "count": len(labels),
            "labels": labels,
            "proportions": [1 / len(labels)] * len(labels),
            "arrangement": "row_stack",
            "orientation": "horizontal",
            "rows": [
                {"labels": labels[0:3], "proportion": None},
                {"labels": labels[3:6], "proportion": None},
                {"labels": labels[6:9], "proportion": None},
            ],
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    prompt = (
        f"Add a 4 m {route_kind} aisle from Inbound to Dispatch."
    )
    request = parse_circulation_turn(prompt, layout)["request"]
    compiled = compile_primary_circulation_operations(layout, request)
    return apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _vehicle_profile() -> dict:
    return {
        "vehicleProfileId": "vehicle-g22-forklift",
        "displayName": "G2.2 Test Forklift",
        "overallDimensions": {"length": 2.0, "width": 1.0, "height": 2.0},
        "footprint": [
            {"x": -1.0, "z": -0.5},
            {"x": 1.0, "z": -0.5},
            {"x": 1.0, "z": 0.5},
            {"x": -1.0, "z": 0.5},
        ],
        "wheelbase": 1.2,
        "steeringLimits": {"minimumTurningRadiusMeters": 2.0},
        "speedLimits": {"maximumMetersPerSecond": 1.5},
        "loadLimits": {"maximumKilograms": 1200},
        "gradeLimits": {"maximumPercent": 8},
        "reversePolicy": "allowed",
    }


def _compact_vehicle_route_layout() -> dict:
    layout = _empty_layout()
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 30,
            "depth": 20,
            "sourceUnit": "m",
            "displayName": "Vehicle Obstacle Plant",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        envelope["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    departments = compile_g1_department_operations(
        layout,
        {
            "count": 3,
            "labels": ["Inbound", "Process", "Dispatch"],
            "proportions": [1 / 3, 1 / 3, 1 / 3],
            "arrangement": "columns",
            "orientation": "horizontal",
        },
    )
    layout = apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    request = parse_circulation_turn(
        "Add a 3 m forklift aisle from Inbound to Dispatch.",
        layout,
    )["request"]
    compiled = compile_primary_circulation_operations(layout, request)
    return apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def _machine_obstacle_context(
    *,
    vehicle_profile: dict | None = None,
    compact: bool = False,
) -> dict:
    bounds = (13.0, 7.0, 17.0, 13.0) if compact else (54.0, 38.0, 66.0, 52.0)
    minimum_x, minimum_z, maximum_x, maximum_z = bounds
    context = {
        "schemaVersion": 1,
        "obstacles": [
            {
                "obstacleId": "placement:machine-01",
                "obstacleKind": "placement_footprint",
                "boundary": [
                    {"x": minimum_x, "z": minimum_z},
                    {"x": maximum_x, "z": minimum_z},
                    {"x": maximum_x, "z": maximum_z},
                    {"x": minimum_x, "z": maximum_z},
                ],
                "evidenceStatus": "derived",
                "sourceRef": "machine-01",
            }
        ],
        "sourceRevisions": {
            "layout": "1" * 64,
            "asset:machine-01": "2" * 64,
        },
    }
    if vehicle_profile is not None:
        context["vehicleProfile"] = {
            "document": vehicle_profile,
            "revision": "d" * 64,
            "status": "published",
        }
    return context


@pytest.mark.parametrize("field", ("aisleKind", "direction", "clearanceEvidenceStatus", "widthAuthority"))
@pytest.mark.parametrize("value", ([], {}))
def test_aisle_kinds_that_are_not_strings_are_refused(field: str, value: object) -> None:
    # 2026-11-03: a list or an object here made validation's set test raise TypeError (an HTTP 500 on a whole save).
    layout = _department_layout()
    request = parse_circulation_turn(
        "Add a 6 m material aisle from Receiving to Shipping through Machining and Assembly.",
        layout,
    )["request"]
    compiled = compile_primary_circulation_operations(layout, request)
    document = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validate_layout(document)
    document["routes"][0]["extensions"]["facilityAisle"][field] = value
    with pytest.raises(FacilityValidationError):
        validate_layout(document)


def test_complete_material_route_is_parsed_and_compiled_deterministically() -> None:
    layout = _department_layout()
    turn = parse_circulation_turn(
        "Add a 6 m material aisle from Receiving to Shipping through Machining and Assembly.",
        layout,
    )
    assert turn["kind"] == "build"
    request = turn["request"]
    assert request["sourceDepartment"] == "Receiving"
    assert request["targetDepartment"] == "Shipping"
    assert request["viaDepartments"] == ["Machining", "Assembly"]
    assert request["widthMeters"] == 6.0
    assert request["direction"] == "two_way"
    assert request["assumptions"] == [
        "Two-way circulation was used because direction was omitted."
    ]

    compiled = compile_primary_circulation_operations(layout, request)
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )
    document = result["document"]
    validate_layout(document)
    route = document["routes"][0]
    extension = route["extensions"]["facilityAisle"]
    assert route["corridorWidth"] == 6.0
    assert extension["areaAccounting"] == "overlay"
    assert extension["widthAuthority"] == "user_authored"
    assert len(extension["viaZoneIds"]) == 2
    assert all(
        3.0 <= point["x"] <= 117.0 and 3.0 <= point["z"] <= 87.0
        for point in route["centerline"]
    )
    validation = validate_primary_circulation_result(
        document, compiled["expectedSummary"]
    )
    assert validation["status"] == "valid"


def test_circulation_parser_asks_or_refuses_instead_of_guessing() -> None:
    layout = _department_layout()
    ambiguous = parse_circulation_turn("Add some aisles.", layout)
    assert ambiguous["kind"] == "ask"
    assert ambiguous["code"] == "facility_circulation_width_required"

    policy = parse_circulation_turn(
        "Add whatever fire aisles the code requires.", layout
    )
    assert policy["kind"] == "refuse"
    assert policy["code"] == "facility_circulation_policy_authority_missing"

    coordinates = parse_circulation_turn(
        "Place a 5 m aisle at x=40, z=25.", layout
    )
    assert coordinates["kind"] == "refuse"
    assert coordinates["code"] == "facility_circulation_model_geometry_refused"

    negated = parse_circulation_turn(
        "Do not add a route; just explain the options.", layout
    )
    assert negated["kind"] == "read_only"
    assert negated["mode"] == "options"

    connectivity = parse_circulation_turn(
        "Which departments are not connected by circulation yet?", layout
    )
    assert connectivity["kind"] == "read_only"
    assert connectivity["mode"] == "analysis"
    assert layout["routes"] == []


def test_diverse_create_phrasing_resolves_the_same_semantic_contract() -> None:
    layout = _department_layout()
    cases = [
        (
            "Could you add a two-way 12 ft pedestrian walkway between "
            "Assembly and Shipping?",
            ("Assembly", "Shipping", [], "pedestrian", 12.0, "ft", "two_way"),
        ),
        (
            "Create a six-metre-wide forklift lane connecting Receiving "
            "with Shipping via Machining.",
            ("Receiving", "Shipping", ["Machining"], "forklift", 6.0, "m", "two_way"),
        ),
        (
            "Run a one-way 1500 mm material route from Shipping to "
            "Receiving through Assembly.",
            ("Shipping", "Receiving", ["Assembly"], "material", 1500.0, "mm", "one_way"),
        ),
        (
            "I need a 72 in pedestrian corridor linking Machining with Assembly.",
            ("Machining", "Assembly", [], "pedestrian", 72.0, "in", "two_way"),
        ),
    ]

    for message, expected in cases:
        turn = parse_circulation_turn(message, layout)
        assert turn["kind"] == "build", message
        request = turn["request"]
        actual = (
            request["sourceDepartment"],
            request["targetDepartment"],
            request["viaDepartments"],
            request["routeKind"],
            request["sourceWidth"],
            request["sourceUnit"],
            request["direction"],
        )
        assert actual == expected, message


def test_longest_department_label_wins_without_partial_name_collision() -> None:
    layout = _department_layout([
        "Receiving",
        "Inspection",
        "Inspection and Shipping",
    ])
    turn = parse_circulation_turn(
        "Add a 4 m material aisle from Receiving to Inspection and Shipping.",
        layout,
    )
    assert turn["kind"] == "build"
    assert turn["request"]["sourceDepartment"] == "Receiving"
    assert turn["request"]["targetDepartment"] == "Inspection and Shipping"
    assert turn["request"]["viaDepartments"] == []


def test_parser_preserves_an_explicit_route_label() -> None:
    layout = _department_layout()
    turn = parse_circulation_turn(
        "Add a 6 m material aisle named Main Material Spine from Receiving to "
        "Shipping through Assembly.",
        layout,
    )
    assert turn["kind"] == "build"
    assert turn["request"]["label"] == "Main Material Spine"
    compiled = compile_primary_circulation_operations(layout, turn["request"])
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    assert result["routes"][0]["label"] == "Main Material Spine"


def test_follow_up_preserves_route_identity_and_endpoints() -> None:
    layout = _department_layout()
    create_turn = parse_circulation_turn(
        "Create a 6 m material aisle from Receiving to Shipping through Assembly.",
        layout,
    )
    compiled = compile_primary_circulation_operations(
        layout, create_turn["request"]
    )
    with_route = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    before = deepcopy(with_route["routes"][0])
    follow_up = parse_circulation_turn(
        "Make that aisle 5 m wide and keep the same endpoints.", with_route
    )
    assert follow_up["kind"] == "build"
    edited = compile_primary_circulation_operations(
        with_route, follow_up["request"]
    )
    result = apply_facility_layout_operations(
        with_route,
        edited["operations"],
        base_revision=layout_revision(with_route),
    )["document"]
    after = result["routes"][0]
    assert after["routeId"] == before["routeId"]
    assert after["sourceEndpoint"] == before["sourceEndpoint"]
    assert after["targetEndpoint"] == before["targetEndpoint"]
    assert after["corridorWidth"] == 5.0


def test_follow_up_can_change_direction_kind_or_relative_width() -> None:
    layout = _department_layout()
    create_turn = parse_circulation_turn(
        "Create a 6 m material aisle from Receiving to Shipping.",
        layout,
    )
    compiled = compile_primary_circulation_operations(
        layout, create_turn["request"]
    )
    with_route = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]

    direction = parse_circulation_turn(
        "Make that aisle one-way.", with_route
    )
    assert direction["kind"] == "build"
    assert direction["request"]["widthMeters"] == 6.0
    assert direction["request"]["direction"] == "one_way"

    route_kind = parse_circulation_turn(
        "Change that route to a pedestrian walkway.", with_route
    )
    assert route_kind["kind"] == "build"
    assert route_kind["request"]["routeKind"] == "pedestrian"
    assert route_kind["request"]["widthMeters"] == 6.0

    widened = parse_circulation_turn(
        "Widen that aisle by 2 ft.", with_route
    )
    assert widened["kind"] == "build"
    assert widened["request"]["widthMeters"] == 6.6096

    ambiguous = parse_circulation_turn(
        "Change that route by 1 m.", with_route
    )
    assert ambiguous["kind"] == "ask"
    assert ambiguous["code"] == "facility_circulation_relative_width_ambiguous"

    invalid = parse_circulation_turn(
        "Narrow that aisle by 20 m.", with_route
    )
    assert invalid["kind"] == "ask"
    assert invalid["code"] == "facility_circulation_width_nonpositive"


def test_disconnected_departments_use_generated_route_bindings() -> None:
    layout = _department_layout()
    request = parse_circulation_turn(
        "Add a 4 m pedestrian walkway from Receiving to Machining.", layout
    )["request"]
    compiled = compile_primary_circulation_operations(layout, request)
    document = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    assert disconnected_department_labels(document) == ["Assembly", "Shipping"]


def test_mixed_traffic_conflicts_are_reported_from_exact_corridor_geometry() -> None:
    layout = _mixed_route_layout()
    analysis = analyze_primary_circulation_conflicts(layout)

    assert analysis["status"] == "conflict"
    assert analysis["mixedTrafficConflictCount"] >= 1
    assert analysis["sharedSegmentConflictCount"] >= 1
    assert analysis["mixedTrafficPairMinimumSeparationMeters"] == 0.0
    assert all(
        item["mixedPedestrianMaterialTraffic"] is True
        and item["evidenceStatus"] == "derived"
        for item in analysis["conflicts"]
    )


def test_conflict_parser_distinguishes_analysis_resolution_and_authority() -> None:
    layout = _mixed_route_layout()
    analysis = parse_circulation_turn(
        "Where do the forklift and pedestrian routes conflict?",
        layout,
    )
    resolution = parse_circulation_turn(
        "Separate the forklift lane and pedestrian walkway without changing departments.",
        layout,
    )
    authored = parse_circulation_turn(
        "Resolve the mixed-traffic conflict and keep 1.5 m between the routes.",
        layout,
    )
    policy = parse_circulation_turn(
        "Resolve the crossing using whatever OSHA clearance applies.",
        layout,
    )

    assert analysis == {"kind": "read_only", "mode": "conflicts"}
    assert resolution["kind"] == "build"
    assert resolution["request"]["action"] == "resolve_conflicts"
    assert resolution["request"]["minimumSeparationMeters"] == 0.0
    assert resolution["request"]["separationAuthority"] == (
        "geometric_non_overlap_only"
    )
    assert resolution["request"]["adjustRouteKind"] == "auto_shortest"
    assert authored["request"]["minimumSeparationMeters"] == 1.5
    assert authored["request"]["separationAuthority"] == "user_authored"
    assert policy["kind"] == "refuse"
    assert policy["code"] == "facility_circulation_policy_authority_missing"


def test_conflict_resolution_preserves_identity_width_bindings_and_departments() -> None:
    layout = _mixed_route_layout()
    before = deepcopy(layout)
    request = parse_circulation_turn(
        "Separate the forklift lane and pedestrian walkway without changing departments.",
        layout,
    )["request"]
    compiled = compile_circulation_conflict_resolution_operations(layout, request)
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_circulation_conflict_resolution_result(
        before,
        result,
        compiled["expectedSummary"],
    )

    assert validation["status"] == "valid", validation
    assert validation["mixedTrafficConflictCount"] == 0
    assert result["zones"] == before["zones"]
    assert [route["routeId"] for route in result["routes"]] == [
        route["routeId"] for route in before["routes"]
    ]
    assert [route["corridorWidth"] for route in result["routes"]] == [5.0, 2.5]
    assert compiled["expectedSummary"]["beforeConflictCount"] >= 1
    assert compiled["expectedSummary"]["afterConflictCount"] == 0
    assert len(compiled["expectedSummary"]["alternatives"]) == 2
    assert compiled["expectedSummary"]["selectedAlternativeId"] in {
        "reroute_pedestrian",
        "reroute_material",
    }


def test_conflict_resolution_honors_explicit_geometric_separation() -> None:
    layout = _mixed_route_layout()
    request = parse_circulation_turn(
        "Resolve the mixed-traffic overlap with 1.5 m separation and preserve departments.",
        layout,
    )["request"]
    compiled = compile_circulation_conflict_resolution_operations(layout, request)
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    analysis = analyze_primary_circulation_conflicts(result)

    assert analysis["mixedTrafficConflictCount"] == 0
    assert analysis["mixedTrafficPairMinimumSeparationMeters"] >= 1.5
    assert compiled["expectedSummary"]["separationAuthority"] == "user_authored"


def test_conflict_resolution_honors_explicit_route_adjustment_intent() -> None:
    layout = _mixed_route_layout()
    pedestrian = parse_circulation_turn(
        "Reroute the pedestrian walkway to remove the conflict and keep the forklift lane fixed.",
        layout,
    )["request"]
    material = parse_circulation_turn(
        "Move the forklift route to resolve the overlap and keep the pedestrian walkway fixed.",
        layout,
    )["request"]

    assert pedestrian["adjustRouteKind"] == "pedestrian"
    assert material["adjustRouteKind"] == "material"
    pedestrian_result = compile_circulation_conflict_resolution_operations(
        layout,
        pedestrian,
    )
    material_result = compile_circulation_conflict_resolution_operations(
        layout,
        material,
    )
    assert pedestrian_result["expectedSummary"]["selectedAlternativeId"] == (
        "reroute_pedestrian"
    )
    assert material_result["expectedSummary"]["selectedAlternativeId"] == (
        "reroute_material"
    )


def test_obstacle_parser_distinguishes_analysis_reroute_and_authority() -> None:
    layout = _obstacle_route_layout()

    analysis = parse_circulation_turn(
        "Does this route hit any machines or restricted regions?",
        layout,
    )
    reroute = parse_circulation_turn(
        "Reroute that aisle around the Restricted Area with 1 m clearance.",
        layout,
    )
    policy = parse_circulation_turn(
        "Reroute that aisle around the obstacle using whatever OSHA clearance applies.",
        layout,
    )
    turning = parse_circulation_turn(
        "Reroute the forklift lane around the machine and respect its turning radius.",
        layout,
    )
    inventory = parse_circulation_turn(
        "What machines are in this layout?",
        layout,
    )

    assert analysis == {"kind": "read_only", "mode": "obstacles"}
    assert reroute["kind"] == "build"
    assert reroute["request"]["action"] == "avoid_obstacles"
    assert reroute["request"]["minimumClearanceMeters"] == 1.0
    assert reroute["request"]["clearanceAuthority"] == "user_authored"
    assert reroute["request"]["preserveDepartments"] is True
    assert reroute["request"]["preserveRouteIdentity"] is True
    assert policy["kind"] == "refuse"
    assert policy["code"] == "facility_circulation_policy_authority_missing"
    assert turning["kind"] == "ask"
    assert turning["code"] == "facility_circulation_vehicle_profile_required"
    assert inventory["kind"] == "not_applicable"


def test_authority_and_coordinate_guards_run_before_generic_classification() -> None:
    layout = _obstacle_route_layout(route_kind="forklift")
    cases = [
        (
            "Make this aisle safe for any forklift.",
            "facility_circulation_vehicle_profile_required",
        ),
        (
            "Validate the turning radius using a typical warehouse forklift.",
            "facility_circulation_vehicle_profile_required",
        ),
        (
            "Reroute using whatever OSHA clearance applies.",
            "facility_circulation_policy_authority_missing",
        ),
        (
            "Put the detour at x=40 m and z=25 m.",
            "facility_circulation_model_geometry_refused",
        ),
    ]

    for prompt, code in cases:
        turn = parse_circulation_turn(prompt, layout)
        assert turn["kind"] == "refuse", prompt
        assert turn["code"] == code, prompt
        assert "request" not in turn, prompt


def test_multiword_protected_label_is_an_obstacle_without_g1_zone_type() -> None:
    layout = _obstacle_route_layout()
    restricted = next(
        zone for zone in layout["zones"] if zone["label"] == "Restricted Area"
    )
    restricted["zoneType"] = "workcell"

    analysis = analyze_primary_circulation_obstacles(layout)

    assert analysis["routeObstacleConflictCount"] == 1
    assert analysis["conflicts"][0]["obstacleKind"] == "protected_zone"


def test_protected_zone_is_detected_and_rerouted_with_exact_clearance() -> None:
    layout = _obstacle_route_layout()
    before = deepcopy(layout)
    initial = analyze_primary_circulation_obstacles(layout)

    assert initial["status"] == "conflict"
    assert initial["routeObstacleConflictCount"] == 1
    assert initial["conflicts"][0]["obstacleKind"] == "protected_zone"

    request = parse_circulation_turn(
        "Reroute that aisle around the Restricted Area with 1 m clearance.",
        layout,
    )["request"]
    compiled = compile_obstacle_aware_circulation_operations(layout, request)
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_obstacle_aware_circulation_result(
        result,
        compiled["expectedSummary"],
    )

    assert validation["status"] == "valid", validation
    assert result["zones"] == before["zones"]
    assert result["routes"][0]["routeId"] == before["routes"][0]["routeId"]
    assert result["routes"][0]["corridorWidth"] == 4.0
    assert (
        result["routes"][0]["extensions"]["facilityAisle"]["sourceZoneId"]
        == before["routes"][0]["extensions"]["facilityAisle"]["sourceZoneId"]
    )
    awareness = result["routes"][0]["extensions"]["facilityAisle"][
        "obstacleAwareness"
    ]
    assert awareness["minimumClearanceMeters"] == 1.0
    assert awareness["clearanceAuthority"] == "user_authored"
    assert awareness["vehicleTurningValidated"] is False
    assert analyze_primary_circulation_obstacles(
        result,
        minimum_clearance_meters=1.0,
    )["routeObstacleConflictCount"] == 0
    validate_layout(result)


def test_obstacle_preservation_hashes_canonicalize_client_numeric_shapes() -> None:
    layout = _obstacle_route_layout()
    layout["zones"][0]["anchors"] = [
        {
            "anchorId": "za-g22-client-float",
            "anchorKind": "material",
            "position": {"x": 10.0, "y": 0.0, "z": 75.0},
            "facing": {"x": 1.0, "y": 0.0, "z": 0.0},
            "allowedRouteKinds": ["material"],
            "evidence": [],
        }
    ]
    request = parse_circulation_turn(
        "Reroute that aisle around the Restricted Area with 1 m clearance.",
        layout,
    )["request"]
    compiled = compile_obstacle_aware_circulation_operations(layout, request)
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]

    validation = validate_obstacle_aware_circulation_result(
        result,
        compiled["expectedSummary"],
    )

    assert validation["status"] == "valid", validation
    assert validation["errors"] == []


def test_external_machine_footprint_is_revision_bound_and_avoided() -> None:
    layout = _obstacle_route_layout()
    context = _machine_obstacle_context()
    initial = analyze_primary_circulation_obstacles(layout, context)

    assert initial["routeObstacleConflictCount"] >= 1
    assert any(
        item["obstacleKind"] == "placement_footprint"
        for item in initial["conflicts"]
    )

    route = layout["routes"][0]
    compiled = compile_obstacle_aware_circulation_operations(
        layout,
        {
            "action": "avoid_obstacles",
            "obstacle_scope": "static_geometry",
            "minimum_clearance": None,
            "clearance_unit": None,
            "preserve_departments": True,
            "preserve_route_identity": True,
            "route_id": route["routeId"],
            "vehicle_profile_id": None,
            "vehicle_profile_revision": None,
            "allow_reverse": None,
        },
        context,
    )
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_obstacle_aware_circulation_result(
        result,
        compiled["expectedSummary"],
        context,
    )

    assert validation["status"] == "valid", validation
    assert compiled["expectedSummary"]["clearanceAuthority"] == (
        "geometric_non_overlap_only"
    )
    assert compiled["expectedSummary"]["vehicleTurningValidated"] is False


def test_vehicle_reroute_requires_exact_published_profile_revision() -> None:
    layout = _compact_vehicle_route_layout()
    route = layout["routes"][0]
    raw_request = {
        "action": "avoid_obstacles",
        "obstacle_scope": "static_geometry",
        "minimum_clearance": 0.5,
        "clearance_unit": "m",
        "preserve_departments": True,
        "preserve_route_identity": True,
        "route_id": route["routeId"],
        "vehicle_profile_id": "vehicle-g22-forklift",
        "vehicle_profile_revision": "d" * 64,
        "allow_reverse": True,
    }

    with pytest.raises(FacilityCirculationError) as unavailable:
        compile_obstacle_aware_circulation_operations(
            layout,
            raw_request,
            _machine_obstacle_context(compact=True),
        )
    assert unavailable.value.code == "facility_circulation_vehicle_profile_unavailable"

    context = _machine_obstacle_context(
        vehicle_profile=_vehicle_profile(),
        compact=True,
    )
    compiled = compile_obstacle_aware_circulation_operations(
        layout,
        raw_request,
        context,
    )
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_obstacle_aware_circulation_result(
        result,
        compiled["expectedSummary"],
        context,
    )

    assert validation["status"] == "valid", validation
    assert validation["vehicleTurningValidated"] is True
    assert result["routes"][0]["routingMode"] == "vehicle"
    assert result["routes"][0]["vehicleProfileRef"] == {
        "vehicleProfileId": "vehicle-g22-forklift",
        "vehicleProfileRevision": "d" * 64,
    }
    assert result["routes"][0]["sweptEnvelope"]["status"] == "validated"
    assert result["routes"][0]["sweptEnvelope"]["gridResolutionMeters"] == 0.5
    validate_layout(result)


def test_vehicle_reroute_scales_lattice_for_full_size_demo_floor() -> None:
    layout = _obstacle_route_layout(route_kind="forklift")
    route = layout["routes"][0]
    context = _machine_obstacle_context(
        vehicle_profile=_vehicle_profile(),
    )
    compiled = compile_obstacle_aware_circulation_operations(
        layout,
        {
            "action": "avoid_obstacles",
            "obstacle_scope": "static_geometry",
            "minimum_clearance": 0.5,
            "clearance_unit": "m",
            "preserve_departments": True,
            "preserve_route_identity": True,
            "route_id": route["routeId"],
            "vehicle_profile_id": "vehicle-g22-forklift",
            "vehicle_profile_revision": "d" * 64,
            "allow_reverse": True,
        },
        context,
    )

    patch = compiled["operations"][0]["patch"]
    assert patch["sweptEnvelope"]["gridResolutionMeters"] == 1.0
    assert patch["obstacleAwareness"]["vehicleTurningValidated"] is True


def test_g23_network_analysis_respects_direction_and_reports_topology() -> None:
    layout = _department_layout()
    for prompt in (
        "Add a 3 m one-way material aisle from Receiving to Machining.",
        "Add a 3 m two-way material aisle from Machining to Assembly.",
    ):
        request = parse_circulation_turn(prompt, layout)["request"]
        compiled = compile_primary_circulation_operations(layout, request)
        layout = apply_facility_layout_operations(
            layout,
            compiled["operations"],
            base_revision=layout_revision(layout),
        )["document"]

    forward = analyze_primary_circulation_network(
        layout,
        source_department="Receiving",
        target_department="Assembly",
        route_kind="material",
    )
    reverse = analyze_primary_circulation_network(
        layout,
        source_department="Assembly",
        target_department="Receiving",
        route_kind="material",
    )

    assert forward["query"]["reachable"] is True
    assert forward["query"]["path"]["departmentLabels"] == [
        "Receiving",
        "Machining",
        "Assembly",
    ]
    assert reverse["query"]["reachable"] is False
    assert forward["unconnectedDepartmentLabels"] == ["Shipping"]
    assert set(forward["topologicalDeadEndDepartmentLabels"]) == {
        "Receiving",
        "Assembly",
    }
    assert forward["directionallyMutuallyReachable"] is False


def test_g23_network_questions_are_classified_without_provider_reasoning() -> None:
    layout = _department_layout()

    reachability = parse_circulation_turn(
        "Can material travel from Receiving to Shipping?",
        layout,
    )
    dead_ends = parse_circulation_turn(
        "Which departments are dead ends in the route network?",
        layout,
    )
    unsupported = parse_circulation_turn(
        "Is this the safest route network for our traffic capacity?",
        layout,
    )

    assert reachability == {
        "kind": "read_only",
        "mode": "network",
        "query": {
            "sourceDepartment": "Receiving",
            "targetDepartment": "Shipping",
            "routeKind": "material",
            "deadEnds": False,
            "crossingCoverage": False,
        },
    }
    assert dead_ends["kind"] == "read_only"
    assert dead_ends["mode"] == "network"
    assert dead_ends["query"]["deadEnds"] is True
    assert unsupported["kind"] == "refuse"
    assert unsupported["code"] == "facility_circulation_operational_authority_missing"


@pytest.mark.parametrize(
    "message",
    [
        "Is this network safe?",
        "Is this crossing safe for pedestrians?",
        "Is this aisle layout adequate?",
        "Is this route network compliant with fire code?",
        "Does this layout meet OSHA egress requirements?",
        "How safe is this circulation for operators?",
        "Does this route comply with NFPA requirements?",
        "Are these pedestrian crossings adequate?",
    ],
)
def test_g23_interrogative_safety_and_compliance_claims_refuse_deterministically(
    message: str,
) -> None:
    turn = parse_circulation_turn(message, _department_layout())

    assert turn["kind"] == "refuse"
    assert turn["code"] == "facility_circulation_operational_authority_missing"
    assert "compliant" in turn["response"]
    assert "nothing changed" in turn["response"]


def test_g23_explicit_crosswalk_is_derived_and_preserves_routes_and_zones() -> None:
    layout = _point_crossing_layout()
    before_routes = deepcopy(layout["routes"])
    before_zones = deepcopy(layout["zones"])
    turn = parse_circulation_turn(
        "Add a 4 m by 3 m pedestrian crossing at the route intersection.",
        layout,
    )

    assert turn["kind"] == "build"
    request = turn["request"]
    assert request["action"] == "add_crossing"
    assert request["crossingWidthMeters"] == 4.0
    assert request["crossingDepthMeters"] == 3.0
    compiled = compile_circulation_crossing_operations(layout, request)
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_circulation_crossing_result(
        result,
        compiled["expectedSummary"],
    )
    network = analyze_primary_circulation_network(result)

    assert validation["status"] == "valid", validation
    assert result["routes"] == before_routes
    assert result["zones"] == before_zones
    assert len(result["floorMarkings"]) == 1
    assert network["unmarkedMixedTrafficPointCrossingCount"] == 0
    assert network["crossings"][0]["crosswalkCoverageStatus"] == "marked"
    assert network["crossings"][0]["crosswalkMarkingIds"] == [
        result["floorMarkings"][0]["markingId"]
    ]
    assert "does not establish" in validation["qualification"]
    validate_layout(result)


def test_g23_crosswalk_requires_dimensions_and_one_unmarked_point_crossing() -> None:
    layout = _point_crossing_layout()
    missing = parse_circulation_turn(
        "Mark the pedestrian crossing.",
        layout,
    )
    assert missing["kind"] == "ask"
    assert missing["code"] == "facility_circulation_crossing_dimensions_required"

    turn = parse_circulation_turn(
        "Add a 4 m by 3 m crosswalk.",
        layout,
    )
    compiled = compile_circulation_crossing_operations(layout, turn["request"])
    marked = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    repeated = parse_circulation_turn(
        "Add a 5 m by 3 m crosswalk.",
        marked,
    )
    assert repeated["kind"] == "ask"
    assert repeated["code"] == "facility_circulation_crossing_ambiguous"


def test_g23_local_path_edit_preserves_route_identity_and_unaffected_routes() -> None:
    layout = _three_row_department_layout()
    for prompt in (
        "Add a 2 m pedestrian walkway from Raw Materials to Subassembly.",
        "Add a 4 m material aisle from Inbound to Dispatch.",
    ):
        request = parse_circulation_turn(prompt, layout)["request"]
        compiled = compile_primary_circulation_operations(layout, request)
        layout = apply_facility_layout_operations(
            layout,
            compiled["operations"],
            base_revision=layout_revision(layout),
        )["document"]
    before_routes = deepcopy(layout["routes"])
    edited_route_id = before_routes[-1]["routeId"]
    unaffected = deepcopy(before_routes[0])

    turn = parse_circulation_turn(
        "Reroute that aisle through Fabrication and keep everything else unchanged.",
        layout,
    )
    assert turn["kind"] == "build"
    assert turn["request"]["pathChanged"] is True
    assert turn["request"]["viaDepartments"] == ["Fabrication"]
    compiled = compile_primary_circulation_operations(layout, turn["request"])
    result = apply_facility_layout_operations(
        layout,
        compiled["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_primary_circulation_result(
        result,
        compiled["expectedSummary"],
    )

    assert validation["status"] == "valid", validation
    assert result["routes"][0] == unaffected
    assert result["routes"][-1]["routeId"] == edited_route_id
    aisle = result["routes"][-1]["extensions"]["facilityAisle"]
    zone_by_id = {zone["zoneId"]: zone["label"] for zone in result["zones"]}
    assert [zone_by_id[item] for item in aisle["viaZoneIds"]] == ["Fabrication"]
    assert result["routes"][-1]["centerline"] != before_routes[-1]["centerline"]
