from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.reference_finished_goods import (
    REFERENCE_FINISHED_GOODS_DISPATCH_PRESET,
    REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
    derive_reference_finished_goods_cycle,
)


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
REFERENCE_REVISION = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)


@pytest.fixture(scope="module")
def reference_context() -> tuple[dict, dict]:
    layout = json.loads(REFERENCE_ARCHIVE.read_text(encoding="utf-8"))
    host = LocalFacilityLayoutHost(
        ROOT / ".runtime" / "facility-layout",
        process_map_root=ROOT / "generated" / "training",
        private_assets=True,
        private_asset_root=ROOT,
    )
    try:
        catalog = host.authoritative_asset_catalog()
    finally:
        host.close()
    definitions = {
        (item["assetId"], item["assetDefinitionRevision"]): item
        for item in catalog
    }
    return layout, definitions


def _segment(cycle: dict, segment_id: str) -> dict:
    return next(
        item for item in cycle["segments"]
        if item["segmentId"] == segment_id
    )


def test_putaway_cycle_is_identity_bound_repeatable_and_read_only(
    reference_context: tuple[dict, dict],
) -> None:
    layout, definitions = reference_context
    before = deepcopy(layout)
    archive_hash = hashlib.sha256(REFERENCE_ARCHIVE.read_bytes()).hexdigest()

    first = derive_reference_finished_goods_cycle(
        layout,
        definitions,
        preset=REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
        planner_vehicle_length_meters=3.6,
    )
    second = derive_reference_finished_goods_cycle(
        layout,
        definitions,
        preset=REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
        planner_vehicle_length_meters=3.6,
    )

    assert first == second
    assert first["vehiclePlacementId"] == "pl-e90e3949b8c93730ead8ba11"
    assert first["parkedVehiclePlacementIds"] == [
        "pl-eefd3f2fdce4214b032a418b"
    ]
    assert first["stagedPalletPlacementId"] == (
        "pl-479340da845951337d88c5fc"
    )
    assert first["targetRackPlacementId"] == (
        "pl-07355227ebfb3e23230870b4"
    )
    assert first["targetRackBayFromNorth"] == 10
    assert [item["phase"] for item in first["segments"]] == [
        "finished_goods_pick",
        "loaded_putaway",
        "loaded_putaway",
        "loaded_putaway",
        "return_empty",
        "return_empty",
        "return_empty",
    ]
    assert first["loadValidationStatus"] == "not_evaluated"
    assert first["productionEligible"] is False
    assert layout == before
    assert archive_hash == REFERENCE_REVISION
    assert hashlib.sha256(REFERENCE_ARCHIVE.read_bytes()).hexdigest() == archive_hash


def test_loaded_and_empty_legs_share_one_physical_rack_aisle(
    reference_context: tuple[dict, dict],
) -> None:
    layout, definitions = reference_context
    putaway = derive_reference_finished_goods_cycle(
        layout,
        definitions,
        preset=REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
        planner_vehicle_length_meters=3.6,
    )
    dispatch = derive_reference_finished_goods_cycle(
        layout,
        definitions,
        preset=REFERENCE_FINISHED_GOODS_DISPATCH_PRESET,
        planner_vehicle_length_meters=3.6,
    )

    loaded = _segment(putaway, "loaded-rack-aisle")
    empty = _segment(putaway, "empty-rack-aisle")
    assert loaded["start"] == empty["goal"]
    assert loaded["goal"] == empty["start"]
    assert loaded["displayOffsetMeters"] == 0.12
    assert empty["displayOffsetMeters"] == -0.12

    dispatch_empty = _segment(dispatch, "empty-rack-aisle")
    dispatch_loaded = _segment(dispatch, "loaded-rack-aisle")
    assert dispatch_empty["start"] == dispatch_loaded["goal"]
    assert dispatch_empty["goal"] == dispatch_loaded["start"]


def test_finished_goods_cycle_fails_closed_when_inventory_identity_changes(
    reference_context: tuple[dict, dict],
) -> None:
    layout, definitions = reference_context
    changed = deepcopy(layout)
    parked = next(
        item for item in changed["placements"]
        if item["placementId"] == "pl-eefd3f2fdce4214b032a418b"
    )
    parked["assetId"] = "asset-forklift"

    with pytest.raises(
        ValueError,
        match="Finished Goods actor or staging inventory changed",
    ):
        derive_reference_finished_goods_cycle(
            changed,
            definitions,
            preset=REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
            planner_vehicle_length_meters=3.6,
        )
