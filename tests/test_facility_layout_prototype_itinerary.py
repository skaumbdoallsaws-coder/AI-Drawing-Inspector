from __future__ import annotations

import json
from pathlib import Path

from ai_inspector.facility_layout.canonical import canonical_layout_bytes
from ai_inspector.facility_layout.movement_inventory import (
    contained_area_zone_labels,
    enumerate_area,
)
from ai_inspector.facility_layout.navigation_contract import (
    navigation_identity_index,
    validate_facility_navigation_extension,
)
from ai_inspector.facility_layout.prototype_itinerary import (
    REFERENCE_DOWNSTREAM_ROOT_ZONE_LABEL,
    assert_itinerary_binding,
    build_prototype_itinerary,
)


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = (
    ROOT
    / ".runtime/facility-layout/layouts/local/site-local/layouts"
    / "fl-reference-manual-20260812.json"
)
REFERENCE_REVISION = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)
PROFILE_REVISION = "b" * 64


def _layout() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def test_reference_itinerary_reuses_eight_actors_and_exact_placement_revisions() -> None:
    layout = _layout()
    before = canonical_layout_bytes(layout)
    labels = contained_area_zone_labels(
        layout,
        [REFERENCE_DOWNSTREAM_ROOT_ZONE_LABEL],
    )
    inventory = enumerate_area(layout, labels)

    itinerary = build_prototype_itinerary(
        layout,
        inventory,
        layout_revision=REFERENCE_REVISION,
        actor_profile_id="prototype-operator-profile",
        actor_profile_revision=PROFILE_REVISION,
    )

    assert canonical_layout_bytes(layout) == before
    assert itinerary["unsupportedActors"] == []
    assert len(itinerary["programCandidates"]) == 8
    assert len(itinerary["facilityNavigation"]["anchors"]) == 36
    assert len(itinerary["facilityNavigation"]["movementPrograms"]) == 24

    placements = {
        item["placementId"]: item for item in layout["placements"]
    }
    actor_ids = {
        group["actorPlacementId"] for group in itinerary["programCandidates"]
    }
    assert len(actor_ids) == 8
    assert actor_ids <= placements.keys()
    packaging_groups = [
        group for group in itinerary["programCandidates"]
        if group.get("cycleKind") == "packaging"
    ]
    assert len(packaging_groups) == 4
    for group in packaging_groups:
        assert [
            item["phase"] for item in group["cycleSegments"]
        ] == ["carry_in", "carry_out", "return_empty"]
        assert len(group["snapshotAnchorIds"]) == 4
        assert len(group["requestedStopPlacementIds"]) == 3
        assert group["rightBypassPlacementId"] not in (
            group["requestedStopPlacementIds"]
        )
    packaging_program_ids = {
        item["movementProgramId"]
        for group in packaging_groups
        for item in group["cycleSegments"]
    }
    packaging_programs = [
        item for item in itinerary["facilityNavigation"]["movementPrograms"]
        if item["movementProgramId"] in packaging_program_ids
    ]
    assert len(packaging_programs) == 12
    assert {item["loopMode"] for item in packaging_programs} == {"one_way"}

    inspection_groups = [
        group for group in itinerary["programCandidates"]
        if group.get("cycleKind") == "inspection"
    ]
    assert len(inspection_groups) == 4
    for group in inspection_groups:
        assert [
            item["phase"] for item in group["cycleSegments"]
        ] == ["inspection_pick", "inspection_place", "return_empty"]
        assert len(group["snapshotAnchorIds"]) == 5
        assert len(group["requestedStopPlacementIds"]) == 3
        assert len(group["returnBypassPlacementIds"]) == 2
        assert [item["stop"] for item in group["reviewedStopActions"]] == [
            "A",
            "B",
            "C",
        ]
        assert group["reviewedStopActions"][0]["actions"] == ["load"]
        assert group["reviewedStopActions"][1]["actions"] == [
            "load",
            "inspect",
            "record",
            "unload",
        ]
        assert group["reviewedStopActions"][2]["actions"] == ["unload"]
    inspection_program_ids = {
        item["movementProgramId"]
        for group in inspection_groups
        for item in group["cycleSegments"]
    }
    inspection_programs = [
        item for item in itinerary["facilityNavigation"]["movementPrograms"]
        if item["movementProgramId"] in inspection_program_ids
    ]
    assert len(inspection_programs) == 12
    assert {item["loopMode"] for item in inspection_programs} == {"one_way"}

    northeast_anchors = [
        item for item in itinerary["facilityNavigation"]["anchors"]
        if item["approachDirections"] == ["northeast"]
    ]
    assert len(northeast_anchors) == 8
    assert {item["anchorKind"] for item in northeast_anchors} == {
        "aisle_access"
    }
    assert sum(
        item["approachDirections"] == ["northwest"]
        for item in itinerary["facilityNavigation"]["anchors"]
    ) == 4
    assert sum(
        item["approachDirections"] == ["southwest"]
        for item in itinerary["facilityNavigation"]["anchors"]
    ) == 4
    for anchor in itinerary["facilityNavigation"]["anchors"]:
        owner_id = anchor["ownerRef"]["ownerId"]
        assert anchor["derivedPositionRef"]["sourceId"] == owner_id
        assert anchor["derivedPositionRef"]["sourceRevision"] == (
            placements[owner_id]["assetDefinitionRevision"]
        )

    validated = validate_facility_navigation_extension(
        itinerary["facilityNavigation"],
        navigation_identity_index(layout),
    )
    assert validated["schemaVersion"] == 1
    assert_itinerary_binding(itinerary, layout, REFERENCE_REVISION)
