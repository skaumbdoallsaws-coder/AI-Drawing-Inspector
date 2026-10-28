"""place_asset_array: a straight row of copies of one placement, replaceable by its arrayId."""
from copy import deepcopy

import pytest

from ai_inspector.facility_layout.operations import FacilityLayoutOperationError, apply_facility_layout_operations
from tests.test_facility_site_property import fixture

RACK = {"assetId": "asset-pallet-rack", "assetDefinitionRevision": "c" * 64,
        "transform": {"position": {"x": 2.0, "y": 0, "z": 5.0}, "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
                      "scale": 1},
        "positionMode": "manual", "snapRelationship": None, "metadata": {"instanceLabel": "Rack bay"}}


def row(count, array_id="racks-a"):
    return {"op": "place_asset_array", "arrayId": array_id, "placement": deepcopy(RACK),
            "step": {"x": 0, "z": 2.53}, "count": count}


def test_a_row_places_numbered_copies_a_step_apart_and_replaces_itself():
    doc = apply_facility_layout_operations(fixture(), [row(3)])["document"]
    placed = {p["placementId"]: p for p in doc["placements"]}
    assert sorted(placed) == ["pl-racks-a-001", "pl-racks-a-002", "pl-racks-a-003"]
    assert [placed[k]["transform"]["position"]["z"] for k in sorted(placed)] == [5.0, 7.53, 10.06]
    assert placed["pl-racks-a-002"]["metadata"]["instanceLabel"] == "Rack bay 2"
    again = apply_facility_layout_operations(doc, [row(2)])["document"]
    assert sorted(p["placementId"] for p in again["placements"]) == ["pl-racks-a-001", "pl-racks-a-002"]
    both = apply_facility_layout_operations(again, [row(1, "racks-b")])["document"]
    assert len(both["placements"]) == 3


@pytest.mark.parametrize("change", [{"arrayId": "Bad Id"}, {"count": 0}, {"count": 201}, {"step": {"x": "far", "z": 1}},
                                    {"extra": 1}])
def test_bad_rows_are_refused(change):
    with pytest.raises(FacilityLayoutOperationError):
        apply_facility_layout_operations(fixture(), [{**row(2), **change}])


def test_a_whole_row_is_removed_at_once():
    doc = apply_facility_layout_operations(fixture(), [row(3), row(2, "racks-b")])["document"]
    gone = apply_facility_layout_operations(doc, [{"op": "delete_asset_array", "arrayId": "racks-a"}])["document"]
    assert sorted(p["placementId"] for p in gone["placements"]) == ["pl-racks-b-001", "pl-racks-b-002"]
    with pytest.raises(FacilityLayoutOperationError):
        apply_facility_layout_operations(gone, [{"op": "delete_asset_array", "arrayId": "racks-a"}])
