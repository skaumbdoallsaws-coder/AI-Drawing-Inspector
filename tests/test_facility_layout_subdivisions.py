from __future__ import annotations

from copy import deepcopy

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.g1_planner import (
    compile_g1_department_operations,
    compile_g1_envelope_operations,
)
from ai_inspector.facility_layout.operations import (
    apply_facility_layout_operations,
    create_layout_document,
)
from ai_inspector.facility_layout.subdivisions import (
    compile_department_subdivision_program,
    parse_subdivision_turn,
    validate_department_subdivision_result,
)


def _layout() -> dict:
    layout = create_layout_document(
        layout_id="fl-g3",
        display_name="G3 Facility",
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
        created_at="2026-08-28T00:00:00Z",
    )
    envelope = compile_g1_envelope_operations(
        layout,
        {
            "width": 120,
            "depth": 90,
            "sourceUnit": "m",
            "displayName": "G3 Facility",
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
            "count": 4,
            "labels": ["Receiving", "Machining", "Assembly", "Shipping"],
            "arrangement": "deterministic_grid",
        },
    )
    return apply_facility_layout_operations(
        layout,
        departments["operations"],
        base_revision=layout_revision(layout),
    )["document"]


def test_parse_equal_area_and_authored_row_subdivisions() -> None:
    layout = _layout()
    equal = parse_subdivision_turn(
        "Divide Assembly into four equal child areas named Kitting, "
        "Mechanical Build, Electrical Build, and Test.",
        layout,
    )
    assert equal["kind"] == "build"
    assert equal["request"]["proportions"] == [0.25] * 4
    assert equal["request"]["assumptions"] == ["equal_area_partition"]

    rows = parse_subdivision_turn(
        "Subdivide Assembly into four child areas named Kitting, Mechanical "
        "Build, Electrical Build, and Test. Two rows: Kitting and Mechanical "
        "Build in row 1; Electrical Build and Test in row 2.",
        layout,
    )
    assert rows["kind"] == "build"
    assert rows["request"]["arrangement"] == "row_stack"
    assert [row["labels"] for row in rows["request"]["rows"]] == [
        ["Kitting", "Mechanical Build"],
        ["Electrical Build", "Test"],
    ]


def test_subdivision_parser_fails_closed_on_ambiguity_and_coordinates() -> None:
    layout = _layout()
    incomplete = parse_subdivision_turn(
        "Divide Assembly into child areas for production.", layout
    )
    assert incomplete["kind"] == "ask"
    assert incomplete["code"] == "facility_subdivision_intent_incomplete"

    mismatch = parse_subdivision_turn(
        "Divide Assembly into three child areas named Kitting and Test.", layout
    )
    assert mismatch["kind"] == "ask"
    assert mismatch["code"] == "facility_subdivision_label_count_mismatch"

    coordinates = parse_subdivision_turn(
        "Divide Assembly into two zones named Build and Test at x=40 z=20.",
        layout,
    )
    assert coordinates["kind"] == "refuse"
    assert coordinates["code"] == "facility_subdivision_coordinate_ownership"


def test_compiler_preserves_parent_and_supports_nested_children() -> None:
    layout = _layout()
    before = deepcopy(layout)
    first = parse_subdivision_turn(
        "Divide Assembly into two child areas named Mechanical Build and "
        "Electrical Build.",
        layout,
    )["request"]
    initial = compile_department_subdivision_program(layout, [first])
    with_children = apply_facility_layout_operations(
        layout,
        initial["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    second = parse_subdivision_turn(
        "Divide Mechanical Build into two child areas named Bench A and Bench B.",
        with_children,
    )["request"]
    nested = compile_department_subdivision_program(layout, [first, second])
    result = apply_facility_layout_operations(
        layout,
        nested["operations"],
        base_revision=layout_revision(layout),
    )["document"]
    validation = validate_department_subdivision_result(
        result, nested["expectedSummary"]
    )
    assert validation["status"] == "valid"
    assert validation["subdivisionCount"] == 2
    assert len(result["zones"]) == 8
    assert result["zones"][:4] == before["zones"]
    assert result["routes"] == before["routes"]

