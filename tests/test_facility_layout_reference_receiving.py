from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.reference_receiving import (
    REFERENCE_RECEIVING_PUTAWAY_PRESET,
    derive_reference_receiving_cycles,
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
VEHICLE_LENGTH_METERS = 2.648569941520691


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


def _derive(layout: dict, definitions: dict) -> dict:
    return derive_reference_receiving_cycles(
        layout,
        definitions,
        preset=REFERENCE_RECEIVING_PUTAWAY_PRESET,
        planner_vehicle_length_meters=VEHICLE_LENGTH_METERS,
    )


def _segment(cycle: dict, segment_id: str) -> dict:
    return next(
        item for item in cycle["segments"]
        if item["segmentId"] == segment_id
    )


def test_receiving_cycles_are_identity_bound_repeatable_and_read_only(
    reference_context: tuple[dict, dict],
) -> None:
    layout, definitions = reference_context
    before = deepcopy(layout)
    archive_hash = hashlib.sha256(REFERENCE_ARCHIVE.read_bytes()).hexdigest()

    first = _derive(layout, definitions)
    second = _derive(layout, definitions)

    assert first == second
    assert first["zoneId"] == "zn-ddb3bfb9cf0f76ab06227420"
    assert [item["cycleKey"] for item in first["cycles"]] == [
        "lower_staging_to_lower_racks",
        "upper_staging_to_middle_racks",
    ]
    assert [item["vehiclePlacementId"] for item in first["cycles"]] == [
        "pl-ca9c06196db29edb3b53d4a9",
        "pl-6c217be9a92f28415348f8e2",
    ]
    assert [item["stagedPalletPlacementId"] for item in first["cycles"]] == [
        "pl-b69cba1ef008746bff0d883c",
        "pl-18056c207e7965f8b359ffa0",
    ]
    assert [item["targetRackPlacementId"] for item in first["cycles"]] == [
        "pl-dbeac632dd935d99cc7fed69",
        "pl-3d0d6b6f6b23e780acc8affe",
    ]
    assert len(first["parkedVehiclePlacementIds"]) == 6
    assert first["loadValidationStatus"] == "not_evaluated"
    assert first["productionEligible"] is False
    assert layout == before
    assert archive_hash == REFERENCE_REVISION
    assert hashlib.sha256(REFERENCE_ARCHIVE.read_bytes()).hexdigest() == archive_hash


def test_each_receiving_cycle_returns_on_the_same_physical_aisles(
    reference_context: tuple[dict, dict],
) -> None:
    receiving = _derive(*reference_context)

    for cycle in receiving["cycles"]:
        for loaded_id, empty_id in (
            ("loaded-rack-aisle", "empty-rack-aisle"),
            ("loaded-cross-aisle", "empty-cross-aisle"),
            ("loaded-access-aisle", "empty-access-aisle"),
        ):
            loaded = _segment(cycle, loaded_id)
            empty = _segment(cycle, empty_id)
            assert loaded["start"] == empty["goal"]
            assert loaded["goal"] == empty["start"]
            assert loaded["displayOffsetMeters"] == 0.12
            assert empty["displayOffsetMeters"] == -0.12


def test_receiving_cycles_fail_closed_when_inventory_changes(
    reference_context: tuple[dict, dict],
) -> None:
    layout, definitions = reference_context
    changed = deepcopy(layout)
    changed["placements"] = [
        item
        for item in changed["placements"]
        if item["placementId"] != "pl-ff1b58f6e0dafc73b45a7b3a"
    ]

    with pytest.raises(
        ValueError,
        match="Receiving actor or storage inventory changed",
    ):
        _derive(changed, definitions)
