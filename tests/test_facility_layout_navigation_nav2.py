from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.operations import (
    FacilityLayoutOperationError,
    apply_facility_layout_operations,
    supported_facility_layout_operations,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "facility_layout"


def _layout() -> dict:
    return json.loads((FIXTURES / "two_asset_cell.json").read_text(encoding="ascii"))


def _manual_navigation() -> dict:
    return {
        "schemaVersion": 1,
        "anchors": [
            {
                "navigationAnchorId": "na-operator-home",
                "anchorKind": "actor_home",
                "ownerRef": {
                    "ownerKind": "placement",
                    "ownerId": "pl-machine-01",
                },
                "interactionKind": "none",
                "positionAuthority": "ui_authored",
                "localPosition": {"x": 4, "z": 4},
                "derivedPositionRef": None,
                "approachDirections": ["any"],
                "actorClasses": ["pedestrian"],
                "evidenceStatus": "authored",
                "evidence": ["ev-plan-pointer"],
                "reviewStatus": "pending",
            }
        ],
        "movementPrograms": [
            {
                "movementProgramId": "nmp-operator-loop",
                "actorPlacementId": "pl-machine-01",
                "actorClass": "pedestrian",
                "actorProfileRef": {
                    "profileKind": "pedestrian",
                    "profileId": "operator-profile-standard",
                    "profileRevision": "1" * 64,
                },
                "orderedStops": [
                    {
                        "stopId": "nst-operator-home",
                        "navigationAnchorId": "na-operator-home",
                        "interactionKind": "none",
                        "required": True,
                    }
                ],
                "loopMode": "closed_loop",
                "requiredRouteIds": [],
                "requiredAnchorIds": ["na-operator-home"],
                "forbiddenZoneIds": [],
                "forbiddenRouteIds": [],
                "manualPathConstraintIds": ["nmc-operator-loop"],
                "handoffProgramIds": [],
                "sourceRevisions": {"layout": "2" * 64},
                "evidenceStatus": "authored",
                "evidence": ["ev-plan-pointer"],
                "reviewStatus": "pending",
            }
        ],
        "manualPathConstraints": [
            {
                "manualPathConstraintId": "nmc-operator-loop",
                "movementProgramId": "nmp-operator-loop",
                "constraintMode": "complete_override",
                "authoredPolyline": [
                    {"x": 4, "z": 4},
                    {"x": 8, "z": 4},
                    {"x": 8, "z": 8},
                    {"x": 4, "z": 4},
                ],
                "snapRefs": [
                    {
                        "pointIndex": 0,
                        "refKind": "navigation_anchor",
                        "refId": "na-operator-home",
                    }
                ],
                "lockedSegmentIndexes": [],
                "direction": "forward",
                "positionAuthority": "ui_authored",
                "evidenceStatus": "authored",
                "evidence": ["ev-plan-pointer"],
                "reviewStatus": "pending",
            }
        ],
        "handoffPrograms": [],
    }


def test_plan_pointer_navigation_operation_is_atomic_and_exactly_undoable() -> None:
    base = _layout()
    base_revision = layout_revision(base)
    operation = {
        "op": "set_facility_navigation",
        "authoringSource": "plan_pointer",
        "facilityNavigation": _manual_navigation(),
    }
    result = apply_facility_layout_operations(
        base,
        [operation],
        base_revision=base_revision,
    )

    assert result["changed"] is True
    assert len(result["operationResults"]) == 1
    assert result["document"]["extensions"]["facilityNavigation"] == (
        _manual_navigation()
    )
    assert base.get("extensions", {}).get("facilityNavigation") is None
    assert result["createdIds"] == [
        "na-operator-home",
        "nmc-operator-loop",
        "nmp-operator-loop",
    ]
    assert "set_facility_navigation" in supported_facility_layout_operations()


@pytest.mark.parametrize("authoring_source", [None, "model", "chat"])
def test_coordinate_authoring_operation_requires_plan_pointer_origin(
    authoring_source: str | None,
) -> None:
    base = _layout()
    operation = {
        "op": "set_facility_navigation",
        "authoringSource": authoring_source,
        "facilityNavigation": _manual_navigation(),
    }
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply_facility_layout_operations(
            base,
            [operation],
            base_revision=layout_revision(base),
        )
    assert error.value.code == "facility_navigation_coordinate_authority_forbidden"


def test_navigation_operation_rejects_unknown_fields_and_dangling_actors() -> None:
    base = _layout()
    unknown = {
        "op": "set_facility_navigation",
        "authoringSource": "plan_pointer",
        "facilityNavigation": _manual_navigation(),
        "coordinatesFromChat": True,
    }
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply_facility_layout_operations(
            base,
            [unknown],
            base_revision=layout_revision(base),
        )
    assert error.value.code == "invalid_operation_field"

    dangling = _manual_navigation()
    dangling["movementPrograms"][0]["actorPlacementId"] = "pl-missing"
    with pytest.raises(FacilityLayoutOperationError) as error:
        apply_facility_layout_operations(
            base,
            [{
                "op": "set_facility_navigation",
                "authoringSource": "plan_pointer",
                "facilityNavigation": dangling,
            }],
            base_revision=layout_revision(base),
        )
    assert error.value.code == "facility_navigation_dangling_identity"


def test_navigation_edit_preserves_unrelated_extensions_and_reports_ids() -> None:
    base = _layout()
    base["extensions"] = {"thirdParty": {"keep": True}}
    first = apply_facility_layout_operations(
        base,
        [{
            "op": "set_facility_navigation",
            "authoringSource": "plan_pointer",
            "facilityNavigation": _manual_navigation(),
        }],
        base_revision=layout_revision(base),
    )["document"]
    changed = deepcopy(_manual_navigation())
    changed["manualPathConstraints"][0]["authoredPolyline"][1] = {
        "x": 9,
        "z": 4,
    }
    second = apply_facility_layout_operations(
        first,
        [{
            "op": "set_facility_navigation",
            "authoringSource": "plan_pointer",
            "facilityNavigation": changed,
        }],
        base_revision=layout_revision(first),
    )
    assert second["document"]["extensions"]["thirdParty"] == {"keep": True}
    assert second["createdIds"] == []
    assert set(second["affectedIds"]) == {
        "na-operator-home",
        "nmc-operator-loop",
        "nmp-operator-loop",
    }
