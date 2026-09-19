from __future__ import annotations

from copy import deepcopy

from ai_inspector.facility_layout.reference_quality import (
    approve_reference_manifest,
    build_reference_manifest,
    build_reference_review_receipt,
    derive_zone_relationships,
)


def _zone(zone_id: str, label: str, x0: float, z0: float, x1: float, z1: float):
    return {
        "zoneId": zone_id,
        "label": label,
        "zoneType": "workcell",
        "floorElevation": 0,
        "boundary": [
            {"x": x0, "z": z0},
            {"x": x1, "z": z0},
            {"x": x1, "z": z1},
            {"x": x0, "z": z1},
        ],
        "anchors": [],
        "evidence": [],
        "extensions": {},
    }


def test_zone_relationships_choose_the_smallest_unique_container() -> None:
    values = derive_zone_relationships(
        [
            _zone("macro", "Macro", 0, 0, 20, 20),
            _zone("cell", "Cell", 2, 2, 10, 10),
            _zone("station", "Station", 3, 3, 5, 5),
        ]
    )
    by_id = {item["zoneId"]: item for item in values}
    assert by_id["macro"]["derivedParentZoneId"] is None
    assert by_id["cell"]["derivedParentZoneId"] == "macro"
    assert by_id["station"]["derivedParentZoneId"] == "cell"
    assert all(item["reviewStatus"] == "pending" for item in values)


def test_review_receipt_never_grants_approval_with_unresolved_items() -> None:
    manifest = {
        "manifestId": "manifest-1",
        "manifestRevision": "revision-1",
        "source": {"layoutRevision": "layout-revision-1"},
        "unresolved": [{"code": "needs_review"}],
    }
    receipt = build_reference_review_receipt(
        manifest, approver="Shadrack", approved=True
    )
    assert receipt["reviewStatus"] == "pending"
    assert receipt["approvalRequested"] is True
    assert receipt["approvalEligible"] is False
    assert "not manufacturing" in receipt["authorityBoundary"]


def test_explicit_reference_approval_records_every_derived_relationship() -> None:
    manifest = {
        "manifestId": "manifest-1",
        "manifestRevision": "a" * 64,
        "source": {"layoutRevision": "b" * 64},
        "unresolved": [],
        "zoneRelationships": [
            {"zoneId": "cell-1", "derivedParentZoneId": "department-1"}
        ],
        "placementBindings": [
            {"placementId": "asset-1", "derivedTargetZoneId": "cell-1"}
        ],
        "contactAudit": {
            "contacts": [
                {
                    "leftPlacementId": "asset-1",
                    "rightPlacementId": "support-1",
                    "contactClass": "supported_or_surface_attached",
                }
            ]
        },
    }
    receipt = approve_reference_manifest(
        manifest,
        approver="Shadrack",
        reviewed_at="2026-08-29T17:00:00Z",
    )

    assert receipt["reviewStatus"] == "approved"
    assert receipt["acceptedDerivedRelationshipCount"] == 2
    assert receipt["acceptedContactClassCount"] == 1
    assert len(receipt["acceptedDerivedRelationships"]) == 2
    assert receipt["reviewedAt"] == "2026-08-29T17:00:00Z"


def test_reference_manifest_rejects_a_count_drift() -> None:
    layout = {
        "schemaVersion": 1,
        "layoutId": "wrong-counts",
        "displayName": "Wrong Counts",
        "association": {"tenantId": "local", "siteId": "site-local"},
        "coordinateFrame": {
            "units": "m",
            "handedness": "right",
            "upAxis": "+Y",
            "originConvention": "south_west_floor",
            "northDirection": "+Z",
        },
        "sourceShellRef": {"shellId": "shell", "revision": "rev"},
        "policySetRef": {"policySetId": "policy", "revision": "rev"},
        "zones": [],
        "routes": [],
        "placements": [],
        "floorMarkings": [],
        "utilityNetworks": [],
        "processBindings": [],
        "dismissedSuggestions": [],
        "status": "draft",
        "createdAt": "2026-08-29T00:00:00Z",
        "updatedAt": "2026-08-29T00:00:00Z",
        "extensions": {},
    }
    try:
        build_reference_manifest(
            deepcopy(layout), [], source_path="fixture.json", source_file_sha256="x"
        )
    except RuntimeError as error:
        assert "Reference counts changed" in str(error)
    else:
        raise AssertionError("Count drift should fail closed")
