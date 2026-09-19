from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = (
    ROOT
    / ".runtime"
    / "facility-layout"
    / "layouts"
    / "local"
    / "site-local"
    / "layouts"
    / "fl-reference-manual-20260812.json"
)
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "facility_layout" / "navigation"
BASELINE = FIXTURE_ROOT / "nav0-reference-baseline-v1.json"
REVIEW = FIXTURE_ROOT / "nav0-reference-review-v1.json"
OUTPUT = FIXTURE_ROOT / "nav9-reference-acceptance-v1.json"
EXPECTED_ARCHIVE_SHA256 = (
    "a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088"
)
PENDING_CODE = "facility_navigation_reference_review_pending"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(points: list[dict[str, Any]]) -> LineString:
    return LineString([(float(item["x"]), float(item["z"])) for item in points])


def _polygon(points: list[dict[str, Any]]) -> Polygon:
    return Polygon([(float(item["x"]), float(item["z"])) for item in points])


def main() -> None:
    archive_before = _sha256(ARCHIVE)
    if archive_before != EXPECTED_ARCHIVE_SHA256:
        raise RuntimeError("The frozen manual reference archive has changed.")
    layout = _load(ARCHIVE)
    baseline = _load(BASELINE)
    review = _load(REVIEW)
    if review["baselineRevision"] != baseline["baselineRevision"]:
        raise RuntimeError("The NAV0 review receipt is stale.")
    approved = [
        *review["approvedOperatorCycleIds"],
        *review["approvedVehiclePlacementIds"],
        *review["approvedHandoffIds"],
    ]
    if review["reviewStatus"] != "pending" or approved:
        raise RuntimeError(
            "This evaluator cannot create or reinterpret a human review event."
        )

    placements = {
        item["placementId"]: item for item in layout.get("placements", [])
    }
    routes = {item["routeId"]: item for item in layout.get("routes", [])}
    operator_ids = {
        item["candidateId"] for item in baseline["operatorCycleCandidates"]
    }

    operators = []
    for item in baseline["operatorCycleCandidates"]:
        centerline = _line(item["candidateCenterline"])
        boundary = _polygon(item["candidateTraversableBoundary"])
        missing_assignments = sorted(
            set(item["assignedPlacementIds"]) - set(placements)
        )
        geometry_passed = (
            not centerline.is_empty
            and centerline.length > 0
            and boundary.is_valid
            and boundary.covers(centerline)
        )
        identity_passed = (
            item["placementId"] in placements and not missing_assignments
        )
        operators.append({
            "candidateId": item["candidateId"],
            "placementId": item["placementId"],
            "zoneId": item["zoneId"],
            "technicalChecks": {
                "candidateCenterlineInsideCandidateBoundary": geometry_passed,
                "existingActorIdentity": item["placementId"] in placements,
                "assignedPlacementIdentityClosure": not missing_assignments,
                "candidateLengthMeters": round(centerline.length, 6),
            },
            "reviewStatus": "pending",
            "productionEligible": False,
            "outcome": "review_pending",
            "code": PENDING_CODE,
            "eligibleForReviewedPlanning": geometry_passed and identity_passed,
        })

    vehicles = []
    for item in baseline["vehicleCandidates"]:
        route = routes.get(item["routeId"])
        route_line = _line(route["centerline"]) if route else LineString()
        vehicles.append({
            "placementId": item["placementId"],
            "routeId": item["routeId"],
            "laneStatus": item["laneStatus"],
            "technicalChecks": {
                "existingActorIdentity": item["placementId"] in placements,
                "existingRouteIdentity": route is not None,
                "routeGeometryAvailable": not route_line.is_empty,
            },
            "reviewStatus": "pending",
            "productionEligible": False,
            "outcome": "authority_missing",
            "code": "facility_navigation_vehicle_profile_unavailable",
            "eligibleForReviewedPlanning": False,
        })

    handoffs = []
    for item in baseline["handoffCandidates"]:
        centerline = _line(item["candidateCenterline"])
        participant_ids_exist = (
            item["fromPlanId"] in operator_ids
            and item["toPlanId"] in operator_ids
        )
        handoffs.append({
            "candidateId": item["candidateId"],
            "fromPlanId": item["fromPlanId"],
            "toPlanId": item["toPlanId"],
            "technicalChecks": {
                "participantCandidateIdentityClosure": participant_ids_exist,
                "candidateCenterlineAvailable": (
                    not centerline.is_empty and centerline.length > 0
                ),
                "candidateLengthMeters": round(centerline.length, 6),
            },
            "reviewStatus": "pending",
            "productionEligible": False,
            "outcome": "review_pending",
            "code": PENDING_CODE,
            "eligibleForReviewedPlanning": False,
        })

    counts = {
        "operatorCandidates": len(operators),
        "vehicleCandidates": len(vehicles),
        "handoffCandidates": len(handoffs),
        "reviewedOperatorCycles": len(review["approvedOperatorCycleIds"]),
        "reviewedVehicles": len(review["approvedVehiclePlacementIds"]),
        "reviewedHandoffs": len(review["approvedHandoffIds"]),
        "omittedCandidateCases": 0,
    }
    if counts["operatorCandidates"] != 12:
        raise RuntimeError("The reference operator candidate count changed.")
    if counts["vehicleCandidates"] != 4:
        raise RuntimeError("The reference vehicle candidate count changed.")
    if counts["handoffCandidates"] != 7:
        raise RuntimeError("The reference handoff candidate count changed.")
    output = {
        "schemaVersion": "facility-navigation-nav9-reference-acceptance-v1",
        "status": "promotion_held_review_pending",
        "source": {
            "layoutId": layout["layoutId"],
            "layoutRevision": archive_before,
            "baselineRevision": baseline["baselineRevision"],
            "reviewSchemaVersion": review["schemaVersion"],
        },
        "counts": counts,
        "operatorCandidates": operators,
        "vehicleCandidates": vehicles,
        "handoffCandidates": handoffs,
        "scenario": {
            "built": False,
            "actorCount": 0,
            "reasonCode": PENDING_CODE,
            "reason": (
                "The frozen review receipt contains no approved operator, "
                "vehicle, or handoff identities. Candidate geometry checks do "
                "not grant human authority."
            ),
        },
        "promotion": {
            "eligible": False,
            "requiredReviewer": review["approver"],
            "requiredReviewerRole": review["approverRole"],
            "requiredEvent": "explicit_product_owner_reference_review",
        },
        "authorityBoundary": review["authorityBoundary"],
    }
    output["acceptanceRevision"] = hashlib.sha256(
        json.dumps(
            output,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    if _sha256(ARCHIVE) != archive_before:
        raise RuntimeError("The evaluator modified the reference archive.")
    OUTPUT.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    print(json.dumps({
        "output": str(OUTPUT),
        "status": output["status"],
        "counts": counts,
        "operatorGeometryPassed": sum(
            item["technicalChecks"][
                "candidateCenterlineInsideCandidateBoundary"
            ]
            for item in operators
        ),
        "archiveUnchanged": _sha256(ARCHIVE) == archive_before,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
