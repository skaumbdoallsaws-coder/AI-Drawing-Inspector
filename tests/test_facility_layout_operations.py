from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    layout_revision,
)
from ai_inspector.facility_layout.diff import build_exact_layout_diff
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.operations import (
    FacilityLayoutOperationError,
    apply_facility_layout_operations,
    create_layout_document,
)


FIXTURES = Path(__file__).parent / "fixtures" / "facility_layout"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _placement(layout: dict, placement_id: str) -> dict:
    return next(item for item in layout["placements"] if item["placementId"] == placement_id)


def _zone(*, zone_id: str | None = None) -> dict:
    value = {
        "zoneType": "staging",
        "label": "Inbound staging",
        "boundary": [
            {"x": 0.0, "z": 0.0},
            {"x": 3.0, "z": 0.0},
            {"x": 3.0, "z": 2.0},
            {"x": 0.0, "z": 2.0},
        ],
        "floorElevation": 0.0,
        "anchors": [],
        "evidence": [],
    }
    if zone_id:
        value["zoneId"] = zone_id
    return value


def test_same_batch_produces_identical_bytes_diff_and_hash() -> None:
    layout = _fixture("empty_cell.json")
    operations = [
        {"op": "rename_layout", "displayName": "Receiving Cell"},
        {"op": "add_zone", "zone": _zone()},
    ]
    base_revision = layout_revision(layout)

    first = apply_facility_layout_operations(
        layout,
        operations,
        base_revision=base_revision,
        updated_at="2026-07-28T01:00:00Z",
    )
    second = apply_facility_layout_operations(
        layout,
        operations,
        base_revision=base_revision,
        updated_at="2026-07-28T01:00:00Z",
    )

    assert canonical_layout_bytes(first["document"]) == canonical_layout_bytes(
        second["document"]
    )
    assert first["canonicalDiff"] == second["canonicalDiff"]
    assert first["diffHash"] == second["diffHash"]
    assert first["createdIds"] == second["createdIds"]
    assert first["createdIds"][0].startswith("zn-")


def test_generated_identity_is_bound_to_base_revision_and_operation_index() -> None:
    layout = _fixture("empty_cell.json")
    operation = {"op": "add_zone", "zone": _zone()}
    first = apply_facility_layout_operations(
        layout,
        [operation],
        base_revision="1" * 64,
    )
    different_base = apply_facility_layout_operations(
        layout,
        [operation],
        base_revision="2" * 64,
    )
    different_index = apply_facility_layout_operations(
        layout,
        [
            {"op": "rename_layout", "displayName": layout["displayName"]},
            operation,
        ],
        base_revision="1" * 64,
    )

    assert first["createdIds"] != different_base["createdIds"]
    assert first["createdIds"] != different_index["createdIds"]


def test_failed_batch_does_not_mutate_input_or_return_partial_changes() -> None:
    layout = _fixture("empty_cell.json")
    original = deepcopy(layout)

    with pytest.raises(FacilityLayoutOperationError) as caught:
        apply_facility_layout_operations(
            layout,
            [
                {"op": "rename_layout", "displayName": "Must not survive"},
                {
                    "op": "move_placement",
                    "placementId": "pl-missing",
                    "position": {"x": 1.0, "y": 0.0, "z": 2.0},
                },
            ],
        )

    assert caught.value.code == "operation_target_not_found"
    assert caught.value.operation_index == 1
    assert layout == original


def test_invalid_created_object_fails_the_batch_without_mutating_input() -> None:
    layout = _fixture("empty_cell.json")
    original = deepcopy(layout)
    invalid_placement = {
        "assetId": "asset-machine",
        "assetDefinitionRevision": "e" * 64,
        "transform": {
            "position": {"x": 1.0, "y": 0.0, "z": 1.0},
            "quaternion": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "scale": 1,
        },
        # positionMode, snapRelationship, and metadata are deliberately absent.
    }

    with pytest.raises(FacilityValidationError) as caught:
        apply_facility_layout_operations(
            layout,
            [{"op": "place_asset", "placement": invalid_placement}],
        )

    assert caught.value.code == "invalid_layout_shape"
    assert layout == original


def test_repeated_asset_instances_move_independently() -> None:
    layout = _fixture("repeated_assets.json")
    result = apply_facility_layout_operations(
        layout,
        [
            {
                "op": "move_placement",
                "placementId": "pl-rack-a",
                "position": {"x": 4.0, "y": 0.0, "z": 5.0},
                "movementKind": "user",
            }
        ],
    )

    moved = _placement(result["document"], "pl-rack-a")
    untouched = _placement(result["document"], "pl-rack-b")
    assert moved["transform"]["position"] == {"x": 4.0, "y": 0.0, "z": 5.0}
    assert moved["positionMode"] == "manual"
    assert untouched == _placement(layout, "pl-rack-b")


def test_locked_manual_and_auto_movement_rules() -> None:
    layout = _fixture("repeated_assets.json")

    with pytest.raises(FacilityLayoutOperationError) as locked:
        apply_facility_layout_operations(
            layout,
            [
                {
                    "op": "move_placement",
                    "placementId": "pl-rack-b",
                    "position": {"x": 9.0, "y": 0.0, "z": 2.0},
                }
            ],
        )
    assert locked.value.code == "locked_placement_movement"

    manual = deepcopy(layout)
    _placement(manual, "pl-rack-a")["positionMode"] = "manual"
    with pytest.raises(FacilityLayoutOperationError) as preserved:
        apply_facility_layout_operations(
            manual,
            [
                {
                    "op": "move_placement",
                    "placementId": "pl-rack-a",
                    "position": {"x": 3.0, "y": 0.0, "z": 3.0},
                    "movementKind": "automatic",
                }
            ],
        )
    assert preserved.value.code == "manual_placement_preserved"

    auto = apply_facility_layout_operations(
        layout,
        [
            {
                "op": "move_placement",
                "placementId": "pl-rack-a",
                "position": {"x": 3.0, "y": 0.0, "z": 3.0},
                "movementKind": "automatic",
            }
        ],
    )
    assert _placement(auto["document"], "pl-rack-a")["positionMode"] == "auto"


def test_set_mode_then_move_is_an_explicit_unlock_transaction() -> None:
    layout = _fixture("repeated_assets.json")
    result = apply_facility_layout_operations(
        layout,
        [
            {
                "op": "set_position_mode",
                "placementId": "pl-rack-b",
                "positionMode": "manual",
            },
            {
                "op": "rotate_placement",
                "placementId": "pl-rack-b",
                "quaternion": {"x": 0.0, "y": 1.0, "z": 0.0, "w": 0.0},
            },
        ],
    )
    rack = _placement(result["document"], "pl-rack-b")
    assert rack["positionMode"] == "manual"
    assert rack["transform"]["quaternion"] == {
        "x": 0.0,
        "y": 1.0,
        "z": 0.0,
        "w": 0.0,
    }


def test_duplicate_is_independent_and_clears_snap_relationship() -> None:
    layout = _fixture("repeated_assets.json")
    source = _placement(layout, "pl-rack-a")
    source["snapRelationship"] = {
        "kind": "row",
        "placementId": "pl-rack-b",
    }
    result = apply_facility_layout_operations(
        layout,
        [
            {
                "op": "duplicate_placement",
                "sourcePlacementId": "pl-rack-a",
                "position": {"x": 10.0, "y": 0.0, "z": 2.0},
            }
        ],
    )
    new_id = result["createdIds"][0]
    duplicate = _placement(result["document"], new_id)

    assert duplicate["assetId"] == source["assetId"]
    assert duplicate["placementId"] != source["placementId"]
    assert duplicate["snapRelationship"] is None
    assert duplicate["positionMode"] == "manual"
    assert duplicate["transform"]["position"]["x"] == 10.0
    assert _placement(result["document"], "pl-rack-a")["transform"]["position"]["x"] == 2.0


def test_delete_zone_and_placement_reject_live_references() -> None:
    two_assets = _fixture("two_asset_cell.json")
    with pytest.raises(FacilityLayoutOperationError) as zone_error:
        apply_facility_layout_operations(
            two_assets,
            [{"op": "delete_zone", "zoneId": "zn-machine-cell"}],
        )
    assert zone_error.value.code == "referenced_object_in_use"

    utility = _fixture("utility_cell.json")
    with pytest.raises(FacilityLayoutOperationError) as placement_error:
        apply_facility_layout_operations(
            utility,
            [{"op": "delete_placement", "placementId": "pl-air-machine"}],
        )
    assert placement_error.value.code == "referenced_object_in_use"


def test_unreferenced_zone_and_placement_delete_without_cascade() -> None:
    layout = _fixture("repeated_assets.json")
    result = apply_facility_layout_operations(
        layout,
        [{"op": "delete_placement", "placementId": "pl-rack-a"}],
    )
    assert [item["placementId"] for item in result["document"]["placements"]] == [
        "pl-rack-b"
    ]

    empty = _fixture("empty_cell.json")
    added = apply_facility_layout_operations(
        empty,
        [{"op": "add_zone", "zone": _zone(zone_id="zn-temporary")}],
    )
    deleted = apply_facility_layout_operations(
        added["document"],
        [{"op": "delete_zone", "zoneId": "zn-temporary"}],
    )
    assert deleted["document"]["zones"] == []


def test_unknown_compatible_fields_round_trip_through_targeted_edits() -> None:
    layout = _fixture("two_asset_cell.json")
    layout["futureTopLevel"] = {"enabled": True}
    layout["zones"][0]["futureZoneField"] = {"review": "retain"}
    layout["placements"][0]["futurePlacementField"] = [1, 2, 3]

    result = apply_facility_layout_operations(
        layout,
        [
            {
                "op": "edit_zone",
                "zoneId": "zn-machine-cell",
                "patch": {"label": "Machining and inspection"},
            },
            {
                "op": "move_placement",
                "placementId": "pl-workstation-01",
                "position": {"x": 9.0, "y": 0.0, "z": 4.0},
            },
        ],
    )
    document = result["document"]
    assert document["futureTopLevel"] == {"enabled": True}
    assert document["zones"][0]["futureZoneField"] == {"review": "retain"}
    assert document["placements"][0]["futurePlacementField"] == [1, 2, 3]


def test_empty_and_semantic_noop_are_byte_stable() -> None:
    layout = _fixture("empty_cell.json")
    empty = apply_facility_layout_operations(
        layout,
        [],
        updated_at="2026-07-28T09:00:00Z",
    )
    same_name = apply_facility_layout_operations(
        layout,
        [{"op": "rename_layout", "displayName": layout["displayName"]}],
        updated_at="2026-07-28T09:00:00Z",
    )

    assert not empty["changed"]
    assert not same_name["changed"]
    assert canonical_layout_bytes(empty["document"]) == canonical_layout_bytes(layout)
    assert canonical_layout_bytes(same_name["document"]) == canonical_layout_bytes(layout)
    assert empty["canonicalDiff"]["entries"] == []
    assert same_name["canonicalDiff"]["entries"] == []


def test_archive_makes_layout_read_only() -> None:
    layout = _fixture("empty_cell.json")
    archived = apply_facility_layout_operations(
        layout,
        [{"op": "archive_layout"}],
    )["document"]
    assert archived["status"] == "archived"

    with pytest.raises(FacilityLayoutOperationError) as caught:
        apply_facility_layout_operations(
            archived,
            [{"op": "rename_layout", "displayName": "Not allowed"}],
        )
    assert caught.value.code == "archived_layout_read_only"


def test_exact_diff_contains_lossless_before_and_after_values() -> None:
    before = _fixture("empty_cell.json")
    after = deepcopy(before)
    after["displayName"] = "Changed"
    after["futureField"] = {"value": 7}

    diff = build_exact_layout_diff(before, after)

    assert diff["changed"]
    assert diff["entries"] == [
        {
            "op": "replace",
            "path": "/displayName",
            "before": "Empty Cell",
            "after": "Changed",
        },
        {
            "op": "add",
            "path": "/futureField",
            "after": {"value": 7},
        },
    ]
    assert len(diff["beforeRevision"]) == 64
    assert len(diff["afterRevision"]) == 64


def test_create_layout_document_is_deterministic_and_empty() -> None:
    fixture = _fixture("empty_cell.json")
    kwargs = {
        "layout_id": "fl-created",
        "display_name": "Created layout",
        "association": fixture["association"],
        "coordinate_frame": fixture["coordinateFrame"],
        "source_shell_ref": fixture["sourceShellRef"],
        "policy_set_ref": fixture["policySetRef"],
        "catalog_snapshot_revision": fixture["catalogSnapshotRevision"],
        "created_at": "2026-07-28T02:00:00Z",
        "extensions": {"futureTopLevel": {"retained": True}},
    }
    first = create_layout_document(**kwargs)
    second = create_layout_document(**kwargs)

    assert canonical_layout_bytes(first) == canonical_layout_bytes(second)
    assert first["zones"] == []
    assert first["placements"] == []
    assert first["futureTopLevel"] == {"retained": True}
