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


def _floor_marking(*, marking_id: str | None = None) -> dict:
    value = {
        "markingType": "direction_arrow",
        "label": "Material flow arrow",
        "semanticRole": "material_flow",
        "transform": {
            "position": {"x": 4.0, "y": 0.0, "z": 2.0},
            "rotationDegrees": 90.0,
        },
        "width": 0.8,
        "depth": 1.6,
        "fillColor": "#ffffff",
        "strokeColor": "#1f2937",
        "opacity": 0.9,
        "text": "",
        "positionMode": "manual",
        "metadata": {"createdBy": "user"},
        "evidence": [],
    }
    if marking_id:
        value["markingId"] = marking_id
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


def test_floor_markings_are_deterministic_editable_and_deletable() -> None:
    layout = _fixture("empty_cell.json")
    operation = {
        "op": "add_floor_marking",
        "floorMarking": _floor_marking(),
    }
    first = apply_facility_layout_operations(layout, [operation])
    second = apply_facility_layout_operations(layout, [operation])

    assert first["createdIds"] == second["createdIds"]
    marking_id = first["createdIds"][0]
    assert marking_id.startswith("fm-")
    assert first["document"]["floorMarkings"][0]["markingId"] == marking_id
    assert canonical_layout_bytes(first["document"]) == canonical_layout_bytes(
        second["document"]
    )

    edited = apply_facility_layout_operations(
        first["document"],
        [{
            "op": "edit_floor_marking",
            "markingId": marking_id,
            "patch": {
                "label": "Outbound material flow",
                "fillColor": "#facc15",
            },
        }],
    )
    assert edited["document"]["floorMarkings"][0]["label"] == (
        "Outbound material flow"
    )

    deleted = apply_facility_layout_operations(
        edited["document"],
        [{"op": "delete_floor_marking", "markingId": marking_id}],
    )
    assert deleted["document"]["floorMarkings"] == []


def test_plan_settings_are_validated_and_persisted_as_layout_extensions() -> None:
    layout = _fixture("empty_cell.json")
    result = apply_facility_layout_operations(
        layout,
        [{
            "op": "set_plan_settings",
            "planSettings": {
                "widthMeters": 55.0,
                "depthMeters": 36.0,
                "gridSpacingMeters": 2.0,
                "majorGridSpacingMeters": 10.0,
            },
        }],
    )

    assert result["document"]["extensions"]["facilityPlan"] == {
        "widthMeters": 55.0,
        "depthMeters": 36.0,
        "gridSpacingMeters": 2.0,
        "majorGridSpacingMeters": 10.0,
    }
    assert result["createdIds"] == []


def test_clear_layout_contents_is_atomic_and_preserves_document_settings() -> None:
    layout = _fixture("utility_cell.json")
    prepared = apply_facility_layout_operations(
        layout,
        [
            {"op": "add_zone", "zone": _zone(zone_id="zn-clear-cell")},
            {
                "op": "add_floor_marking",
                "floorMarking": _floor_marking(marking_id="fm-clear-arrow"),
            },
            {
                "op": "set_plan_settings",
                "planSettings": {
                    "widthMeters": 55.0,
                    "depthMeters": 36.0,
                    "gridSpacingMeters": 2.0,
                    "majorGridSpacingMeters": 10.0,
                },
            },
        ],
    )["document"]
    plan_settings = deepcopy(prepared["extensions"]["facilityPlan"])
    identity = {
        key: deepcopy(prepared[key])
        for key in (
            "schemaVersion",
            "layoutId",
            "displayName",
            "association",
            "coordinateFrame",
            "sourceShellRef",
            "policySetRef",
        )
    }
    expected_affected = {
        "zn-clear-cell",
        "fm-clear-arrow",
        *[item["placementId"] for item in prepared["placements"]],
        *[item["routeId"] for item in prepared["routes"]],
        *[
            item["utilityNetworkId"]
            for item in prepared["utilityNetworks"]
        ],
        *[
            item["processBindingId"]
            for item in prepared["processBindings"]
        ],
    }

    result = apply_facility_layout_operations(
        prepared,
        [{"op": "clear_layout_contents"}],
    )
    document = result["document"]

    for collection in (
        "zones",
        "floorMarkings",
        "placements",
        "routes",
        "utilityNetworks",
        "processBindings",
        "dismissedSuggestions",
    ):
        assert document[collection] == []
    assert document["extensions"]["facilityPlan"] == plan_settings
    assert {key: document[key] for key in identity} == identity
    assert result["createdIds"] == []
    assert expected_affected.issubset(set(result["affectedIds"]))


@pytest.mark.parametrize(
    "settings",
    [
        {
            "widthMeters": 0.1,
            "depthMeters": 36.0,
            "gridSpacingMeters": 1.0,
            "majorGridSpacingMeters": 5.0,
        },
        {
            "widthMeters": 55.0,
            "depthMeters": 36.0,
            "gridSpacingMeters": 2.0,
            "majorGridSpacingMeters": 5.0,
        },
        {
            "widthMeters": 55.0,
            "depthMeters": 36.0,
            "gridSpacingMeters": 2.0,
            "majorGridSpacingMeters": 10.0,
            "screenScale": 20,
        },
    ],
)
def test_invalid_plan_settings_reject_the_complete_batch(settings: dict) -> None:
    layout = _fixture("empty_cell.json")
    original = deepcopy(layout)

    with pytest.raises(FacilityLayoutOperationError) as caught:
        apply_facility_layout_operations(
            layout,
            [
                {"op": "rename_layout", "displayName": "Must not survive"},
                {"op": "set_plan_settings", "planSettings": settings},
            ],
        )

    assert caught.value.code == "invalid_operation_field"
    assert caught.value.operation_index == 1
    assert layout == original


def test_locked_floor_marking_rejects_geometry_changes() -> None:
    layout = _fixture("empty_cell.json")
    marking = _floor_marking(marking_id="fm-locked-arrow")
    marking["positionMode"] = "locked"
    added = apply_facility_layout_operations(
        layout,
        [{"op": "add_floor_marking", "floorMarking": marking}],
    )

    with pytest.raises(FacilityLayoutOperationError) as caught:
        apply_facility_layout_operations(
            added["document"],
            [{
                "op": "edit_floor_marking",
                "markingId": "fm-locked-arrow",
                "patch": {"width": 2.0},
            }],
        )

    assert caught.value.code == "locked_object"


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


def test_duplicate_accepts_explicit_vertical_stack_relationship() -> None:
    layout = _fixture("repeated_assets.json")
    relationship = {
        "family": "vertical_stack",
        "stackId": "stack-rack-a",
        "level": 1,
        "count": 3,
        "gapMeters": 0.0,
        "itemHeightMeters": 2.4,
        "evidenceStatus": "unverified",
    }
    result = apply_facility_layout_operations(
        layout,
        [{
            "op": "duplicate_placement",
            "sourcePlacementId": "pl-rack-a",
            "position": {"x": 2.0, "y": 2.4, "z": 2.0},
            "snapRelationship": relationship,
        }],
    )
    duplicate = _placement(result["document"], result["createdIds"][0])

    assert duplicate["snapRelationship"] == relationship
    assert duplicate["snapRelationship"] is not relationship
    assert _placement(layout, "pl-rack-a")["snapRelationship"] is None


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


def test_surface_support_cannot_be_deleted_while_children_reference_it() -> None:
    layout = _fixture("repeated_assets.json")
    support = _placement(layout, "pl-rack-a")
    child = _placement(layout, "pl-rack-b")
    child["snapRelationship"] = {
        "family": "surface_attachment",
        "attachmentId": "surface-rack-a-top",
        "supportPlacementId": support["placementId"],
        "surfaceId": "derived-top",
        "side": "above",
        "localPosition": {"x": 0.0, "z": 0.0},
        "localRotationDegrees": 0,
        "normalOffsetMeters": 0,
        "surfaceSource": "derived_aabb",
        "evidenceStatus": "unverified",
    }
    with pytest.raises(FacilityLayoutOperationError) as captured:
        apply_facility_layout_operations(
            layout,
            [{"op": "delete_placement", "placementId": "pl-rack-a"}],
        )
    assert captured.value.code == "referenced_object_in_use"

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


def test_pattern_provenance_covers_seed_and_copy_then_marks_manual_drift() -> None:
    layout = _fixture("repeated_assets.json")
    provenance = {
        "schemaVersion": 1,
        "provenanceId": "layout-pattern:test-linear-a",
        "command": "linear_pattern",
        "authoredStrategy": None,
        "seedEntityIds": ["pl-rack-a"],
        "parameters": {"count": 2, "pitch": 4.0},
        "manuallyEditedSinceCreation": False,
    }
    patterned = apply_facility_layout_operations(
        layout,
        [{
            "op": "duplicate_placement",
            "sourcePlacementId": "pl-rack-a",
            "position": {"x": 6.0, "y": 0.0, "z": 2.0},
            "layoutProvenance": provenance,
            "layoutProvenanceSeedEntityIds": ["pl-rack-a"],
        }],
    )
    copy_id = patterned["createdIds"][0]
    source = _placement(patterned["document"], "pl-rack-a")
    copied = _placement(patterned["document"], copy_id)

    for item in (source, copied):
        stored = item["metadata"]["layoutProvenance"]
        assert stored["provenanceId"] == "layout-pattern:test-linear-a"
        assert stored["authoredGeometry"]["kind"] == "placement"
        assert stored["manuallyEditedSinceCreation"] is False

    moved = apply_facility_layout_operations(
        patterned["document"],
        [{
            "op": "move_placement",
            "placementId": copy_id,
            "position": {"x": 7.0, "y": 0.0, "z": 2.0},
            "movementKind": "user",
        }],
    )
    drift = _placement(moved["document"], copy_id)["metadata"][
        "layoutProvenance"
    ]
    assert drift["geometryEditedSinceCreation"] is True
    assert drift["manuallyEditedSinceCreation"] is True
    assert drift["authoredGeometry"]["transform"]["position"] == {
        "x": 6.0,
        "y": 0.0,
        "z": 2.0,
    }


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


def test_route_and_process_binding_operations_are_atomic_and_reference_safe():
    layout = _fixture("two_asset_cell.json")
    route = deepcopy(layout["routes"][0])
    route.pop("routeId")
    layout["routes"] = []

    added = apply_facility_layout_operations(
        layout,
        [{"op": "add_route", "route": route}],
        base_revision="4" * 64,
    )
    route_id = added["createdIds"][0]
    assert route_id.startswith("rt-")
    assert added["document"]["routes"][0]["routeId"] == route_id

    edited = apply_facility_layout_operations(
        added["document"],
        [
            {
                "op": "edit_route",
                "routeId": route_id,
                "patch": {"corridorWidth": 1.25},
            },
            {
                "op": "attach_process_binding",
                "processBinding": {
                    "productId": "product-demo",
                    "processMapId": "pm-demo",
                    "processMapRevision": "5" * 64,
                    "processNodeIds": ["node-operation"],
                    "processEdgeIds": ["edge-flow"],
                    "placementIds": ["pl-machine-01"],
                    "routeIds": [route_id],
                    "bindingRole": "material_flow",
                },
            },
        ],
        base_revision=layout_revision(added["document"]),
    )
    binding_id = next(
        item
        for item in edited["createdIds"]
        if item.startswith("pb-")
    )
    assert edited["document"]["routes"][0]["corridorWidth"] == 1.25

    with pytest.raises(FacilityLayoutOperationError) as referenced:
        apply_facility_layout_operations(
            edited["document"],
            [{"op": "delete_route", "routeId": route_id}],
        )
    assert referenced.value.code == "referenced_object_in_use"

    removed = apply_facility_layout_operations(
        edited["document"],
        [
            {
                "op": "detach_process_binding",
                "processBindingId": binding_id,
            },
            {"op": "delete_route", "routeId": route_id},
        ],
    )
    assert removed["document"]["routes"] == []
    assert removed["document"]["processBindings"] == []


def test_utility_topology_operations_preserve_referential_integrity():
    layout = _fixture("utility_cell.json")
    network_id = "un-compressed-air"
    added = apply_facility_layout_operations(
        layout,
        [
            {
                "op": "add_utility_network_node",
                "utilityNetworkId": network_id,
                "node": {
                    "networkNodeId": "nn-air-review-drop",
                    "nodeKind": "junction",
                    "networkRole": "junction",
                    "position": {"x": 6.0, "y": 3.0, "z": 3.0},
                },
            },
            {
                "op": "add_utility_network_segment",
                "utilityNetworkId": network_id,
                "segment": {
                    "networkSegmentId": "ns-air-review-drop",
                    "sourceNetworkNodeId": "nn-air-branch",
                    "targetNetworkNodeId": "nn-air-review-drop",
                    "centerline": [
                        {"x": 4.0, "y": 3.0, "z": 3.0},
                        {"x": 6.0, "y": 3.0, "z": 3.0},
                    ],
                    "interface": {"nominalDiameterMm": 12},
                    "capacity": {"maximumFlowCfm": 35},
                    "requirements": [],
                    "evidence": [],
                },
            },
        ],
    )
    network = added["document"]["utilityNetworks"][0]
    assert any(
        item["networkNodeId"] == "nn-air-review-drop"
        for item in network["nodes"]
    )

    with pytest.raises(FacilityLayoutOperationError) as referenced:
        apply_facility_layout_operations(
            added["document"],
            [
                {
                    "op": "delete_utility_network_node",
                    "utilityNetworkId": network_id,
                    "networkNodeId": "nn-air-review-drop",
                }
            ],
        )
    assert referenced.value.code == "referenced_object_in_use"

    removed = apply_facility_layout_operations(
        added["document"],
        [
            {
                "op": "edit_utility_network_segment",
                "utilityNetworkId": network_id,
                "networkSegmentId": "ns-air-review-drop",
                "patch": {"capacity": {"maximumFlowCfm": 30}},
            },
            {
                "op": "delete_utility_network_segment",
                "utilityNetworkId": network_id,
                "networkSegmentId": "ns-air-review-drop",
            },
            {
                "op": "delete_utility_network_node",
                "utilityNetworkId": network_id,
                "networkNodeId": "nn-air-review-drop",
            },
        ],
    )
    network = removed["document"]["utilityNetworks"][0]
    assert not any(
        item["networkNodeId"] == "nn-air-review-drop"
        for item in network["nodes"]
    )
    assert not any(
        item["networkSegmentId"] == "ns-air-review-drop"
        for item in network["segments"]
    )


def test_semantic_aisle_operations_create_world_route_and_rebind_fingerprint():
    layout = _fixture("empty_cell.json")
    base_revision = layout_revision(layout)
    added = apply_facility_layout_operations(
        layout,
        [{
            "op": "add_aisle",
            "aisle": {
                "label": "Main Forklift Boulevard",
                "aisleKind": "forklift",
                "direction": "two_way",
                "color": "#d9a514",
                "corridorWidth": 10.668,
                "centerline": [
                    {"x": 0.0, "y": 0.0, "z": 12.0},
                    {"x": 40.0, "y": 0.0, "z": 12.0},
                ],
                "clearanceEvidenceStatus": "unverified",
            },
        }],
        base_revision=base_revision,
    )
    route = added["document"]["routes"][0]
    route_id = route["routeId"]
    first_fingerprint = route["routeFingerprint"]

    assert route_id.startswith("rt-")
    assert route["label"] == "Main Forklift Boulevard"
    assert route["sourceEndpoint"]["kind"] == "world_point"
    assert route["targetEndpoint"]["position"]["x"] == 40.0
    assert route["extensions"]["facilityAisle"] == {
        "schemaVersion": 1,
        "aisleKind": "forklift",
        "direction": "two_way",
        "color": "#d9a514",
        "clearanceEvidenceStatus": "unverified",
    }

    edited = apply_facility_layout_operations(
        added["document"],
        [{
            "op": "edit_aisle",
            "routeId": route_id,
            "patch": {
                "corridorWidth": 12.0,
                "direction": "one_way",
            },
        }],
        base_revision=layout_revision(added["document"]),
    )
    changed = edited["document"]["routes"][0]
    assert changed["corridorWidth"] == 12.0
    assert changed["extensions"]["facilityAisle"]["direction"] == "one_way"
    assert changed["routeFingerprint"] != first_fingerprint
