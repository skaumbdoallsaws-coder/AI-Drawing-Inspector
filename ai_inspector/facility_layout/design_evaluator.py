"""Deterministic feasibility and metric evaluation for Facility design proposals."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Callable, Mapping, Sequence

from .canonical import canonicalize_layout, layout_revision
from .design_brief import (
    FACILITY_DESIGN_CONSTRAINT_KINDS,
    FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
    canonical_design_bytes,
    design_revision,
    validate_facility_design_brief,
)
from .manufacturing_snapshot import validate_facility_manufacturing_snapshot
from .design_routing import validate_design_transfer_route_path


FACILITY_DESIGN_EVALUATOR_VERSION = "facility-design-evaluator-v1"
FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS = 1e-6
FACILITY_DESIGN_AREA_TOLERANCE_SQUARE_METERS = 1e-6

_ROUTE_GEOMETRY_FIELDS = (
    "centerline",
    "corridorWidth",
    "routeKind",
    "routingMode",
    "sourceEndpoint",
    "targetEndpoint",
    "facilityAisle",
)


class FacilityDesignEvaluationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignEvaluationError(code, message, details=details)


def _projection_hash(value: Any) -> str:
    return design_revision(value)


def _index(layout: Mapping[str, Any], collection: str, id_field: str) -> dict[str, Mapping[str, Any]]:
    return {
        str(item[id_field]): item
        for item in layout.get(collection, [])
        if isinstance(item, Mapping) and isinstance(item.get(id_field), str)
    }


def _entity(
    layout: Mapping[str, Any], entity_kind: str, entity_id: str
) -> Mapping[str, Any] | None:
    collections = {
        "placement": ("placements", "placementId"),
        "route": ("routes", "routeId"),
        "zone": ("zones", "zoneId"),
        "process_binding": ("processBindings", "processBindingId"),
    }
    record = collections.get(entity_kind)
    if record is None:
        return None
    return _index(layout, record[0], record[1]).get(entity_id)


def _geometry_projection(entity_kind: str, entity: Mapping[str, Any]) -> Any:
    if entity_kind == "placement":
        return {
            "assetId": entity.get("assetId"),
            "assetDefinitionRevision": entity.get("assetDefinitionRevision"),
            "transform": deepcopy(entity.get("transform")),
            "positionMode": entity.get("positionMode"),
        }
    if entity_kind == "route":
        return {
            field: deepcopy(entity.get(field))
            for field in _ROUTE_GEOMETRY_FIELDS
            if field in entity
        }
    if entity_kind == "zone":
        return {
            "boundary": deepcopy(entity.get("boundary")),
            "floorElevation": entity.get("floorElevation"),
            "heightLimit": entity.get("heightLimit"),
        }
    if entity_kind == "process_binding":
        return {
            field: deepcopy(entity.get(field))
            for field in (
                "productId",
                "processMapId",
                "processMapRevision",
                "processNodeIds",
                "processEdgeIds",
                "placementIds",
                "routeIds",
                "bindingRole",
            )
        }
    return deepcopy(entity)


def _route_projection(route: Mapping[str, Any]) -> dict[str, Any]:
    return _geometry_projection("route", route)


def _point(point: Mapping[str, Any]) -> tuple[float, float, float]:
    try:
        return float(point["x"]), float(point.get("y", 0.0)), float(point["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityDesignEvaluationError(
            "facility_design_route_geometry_invalid",
            "Route centerline contains an invalid point.",
        ) from exc


def route_path_distance_meters(
    layout: Mapping[str, Any], route_ids: Sequence[str]
) -> float:
    routes = _index(layout, "routes", "routeId")
    total = 0.0
    for route_id in route_ids:
        route = routes.get(str(route_id))
        if route is None:
            _fail(
                "facility_design_route_unavailable",
                "Accepted material route is absent from the candidate layout.",
                routeId=route_id,
            )
        centerline = route.get("centerline")
        if not isinstance(centerline, list) or len(centerline) < 2:
            _fail("facility_design_route_geometry_invalid", "Accepted material route has no measurable centerline.", routeId=route_id)
        points = [_point(item) for item in centerline if isinstance(item, Mapping)]
        if len(points) != len(centerline):
            _fail("facility_design_route_geometry_invalid", "Accepted material route has an invalid centerline.", routeId=route_id)
        total += sum(
            math.dist(points[index - 1], points[index])
            for index in range(1, len(points))
        )
    return float(total)


def _placement_center(placement: Mapping[str, Any]) -> tuple[float, float]:
    position = ((placement.get("transform") or {}).get("position") or {})
    try:
        return float(position["x"]), float(position["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityDesignEvaluationError(
            "facility_design_placement_geometry_invalid",
            "Placement has no canonical XZ center.",
        ) from exc


def _rotation_projection(placement: Mapping[str, Any]) -> bytes:
    quaternion = ((placement.get("transform") or {}).get("quaternion") or {})
    return canonical_design_bytes(quaternion)


def _metric(
    metric_id: str,
    *,
    status: str,
    value: int | float | None,
    unit: str,
    baseline_value: int | float | None,
    source_refs: Sequence[str],
    qualification: str,
) -> dict[str, Any]:
    delta = None
    percentage = None
    if status == "measured" and value is not None and baseline_value is not None:
        delta = float(value) - float(baseline_value)
        if abs(float(baseline_value)) > FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS:
            percentage = delta / float(baseline_value) * 100.0
    return {
        "metricId": metric_id,
        "status": status,
        "value": value,
        "unit": unit,
        "baselineValue": baseline_value,
        "delta": delta,
        "percentage": percentage,
        "sourceArtifactRefs": sorted(set(str(item) for item in source_refs)),
        "calculationVersion": FACILITY_DESIGN_EVALUATOR_VERSION,
        "qualification": qualification,
    }


def calculate_facility_design_metrics(
    *,
    baseline_layout: Mapping[str, Any],
    candidate_layout: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    baseline_metrics: Mapping[str, Mapping[str, Any]] | None = None,
    source_bundle: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    baseline = canonicalize_layout(baseline_layout)
    candidate = canonicalize_layout(candidate_layout)
    snapshot_record = validate_facility_manufacturing_snapshot(snapshot)
    candidate_route_validation = validate_design_transfer_route_path(
        candidate,
        snapshot_record,
        source_bundle=source_bundle,
    )
    baseline_route_validation = validate_design_transfer_route_path(
        baseline,
        snapshot_record,
        source_bundle=source_bundle,
    )
    route_distance = float(candidate_route_validation["distanceMeters"])
    baseline_distance = float(baseline_route_validation["distanceMeters"])
    frequency = snapshot_record["materialTransfer"].get("loadedTripsPerShift")
    source_refs = [
        snapshot_record["snapshotRevision"],
        layout_revision(candidate),
        snapshot_record["routePath"]["validationContextRevision"],
    ]
    base_by_id = _index(baseline, "placements", "placementId")
    candidate_by_id = _index(candidate, "placements", "placementId")
    shared_placements = sorted(set(base_by_id) & set(candidate_by_id))
    displacements = []
    rotated = 0
    for placement_id in shared_placements:
        source = base_by_id[placement_id]
        target = candidate_by_id[placement_id]
        source_center = _placement_center(source)
        target_center = _placement_center(target)
        displacement = math.dist(source_center, target_center)
        if displacement > FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS:
            displacements.append(displacement)
        if _rotation_projection(source) != _rotation_projection(target):
            rotated += 1
    base_routes = _index(baseline, "routes", "routeId")
    candidate_routes = _index(candidate, "routes", "routeId")
    changed_routes = sum(
        1
        for route_id in sorted(set(base_routes) & set(candidate_routes))
        if _projection_hash(_route_projection(base_routes[route_id]))
        != _projection_hash(_route_projection(candidate_routes[route_id]))
    )
    binding_ids = {
        node.split(":", 1)[1]
        for node in snapshot_record["dependencyGraph"]["nodes"]
        if isinstance(node, str) and node.startswith("process_binding:")
    }
    prior = baseline_metrics or {}
    baseline_for = lambda metric_id, fallback: (
        prior.get(metric_id, {}).get("value", fallback)
        if isinstance(prior.get(metric_id, {}), Mapping)
        else fallback
    )
    metrics = [
        _metric(
            "loadedRouteDistanceMeters",
            status="measured",
            value=route_distance,
            unit="m",
            baseline_value=baseline_for("loadedRouteDistanceMeters", baseline_distance),
            source_refs=source_refs,
            qualification="Accepted loaded route geometry only; no timing, capacity, congestion, safety, or compliance claim.",
        )
    ]
    if frequency is None:
        metrics.append(
            _metric(
                "loadedTravelMetersPerShift",
                status="unavailable",
                value=None,
                unit="m/shift",
                baseline_value=None,
                source_refs=source_refs,
                qualification="Authored loaded trips per named shift are unavailable; route distance remains measurable.",
            )
        )
    else:
        trips = float(frequency["loadedTripsPerShift"])
        metrics.append(
            _metric(
                "loadedTravelMetersPerShift",
                status="measured",
                value=route_distance * trips,
                unit="m/shift",
                baseline_value=baseline_for(
                    "loadedTravelMetersPerShift", baseline_distance * trips
                ),
                source_refs=[*source_refs, frequency["evidenceRef"]],
                qualification=f"Loaded distance multiplied by reviewed {trips:g} trips for shift {frequency['shiftId']}.",
            )
        )
    metrics.extend(
        [
            _metric(
                "movedPlacementCount",
                status="measured",
                value=len(displacements),
                unit="count",
                baseline_value=baseline_for("movedPlacementCount", 0),
                source_refs=source_refs,
                qualification="Existing placement centers changed beyond the computational comparison tolerance.",
            ),
            _metric(
                "placementDisplacementMeters",
                status="measured",
                value=sum(displacements),
                unit="m",
                baseline_value=baseline_for("placementDisplacementMeters", 0.0),
                source_refs=source_refs,
                qualification="Sum of XZ center displacement for moved existing placements.",
            ),
            _metric(
                "rotatedPlacementCount",
                status="measured",
                value=rotated,
                unit="count",
                baseline_value=baseline_for("rotatedPlacementCount", 0),
                source_refs=source_refs,
                qualification="Existing placements with changed canonical rotation.",
            ),
            _metric(
                "changedRouteCount",
                status="measured",
                value=changed_routes,
                unit="count",
                baseline_value=baseline_for("changedRouteCount", 0),
                source_refs=source_refs,
                qualification="Existing routes with changed canonical geometry or direction.",
            ),
            _metric(
                "affectedProcessBindingCount",
                status="measured",
                value=len(binding_ids),
                unit="count",
                baseline_value=baseline_for(
                    "affectedProcessBindingCount", len(binding_ids)
                ),
                source_refs=source_refs,
                qualification="Process bindings inside the objective dependency closure.",
            ),
        ]
    )
    return sorted(metrics, key=lambda item: item["metricId"])


ContainmentChecker = Callable[
    [Mapping[str, Any], Mapping[str, Any], str, str],
    tuple[str, Mapping[str, Any]],
]


def facility_design_constraint_registry() -> dict[str, dict[str, Any]]:
    version = FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION
    return {
        "preserve_entity_geometry": {
            "predicateVersion": version,
            "targetEntityKinds": ["placement", "zone"],
            "dependencyProjection": ["identity", "geometry"],
            "violationCode": "facility_design_locked_geometry_changed",
            "missingEvidenceBehavior": "stale",
        },
        "preserve_entity_identity": {
            "predicateVersion": version,
            "targetEntityKinds": ["placement", "route", "zone", "process_binding"],
            "dependencyProjection": ["identity"],
            "violationCode": "facility_design_locked_identity_changed",
            "missingEvidenceBehavior": "violated",
        },
        "preserve_route_geometry": {
            "predicateVersion": version,
            "targetEntityKinds": ["route"],
            "dependencyProjection": ["route_geometry", "direction"],
            "violationCode": "facility_design_locked_route_changed",
            "missingEvidenceBehavior": "unavailable",
        },
        "preserve_process_binding": {
            "predicateVersion": version,
            "targetEntityKinds": ["process_binding"],
            "dependencyProjection": ["binding", "referenced_identities"],
            "violationCode": "facility_design_locked_process_binding_changed",
            "missingEvidenceBehavior": "stale",
        },
        "remain_inside_area": {
            "predicateVersion": version,
            "targetEntityKinds": ["placement", "zone"],
            "dependencyProjection": ["placement_footprint", "zone_boundary"],
            "violationCode": "facility_design_area_containment_failed",
            "missingEvidenceBehavior": "unavailable",
        },
    }


def evaluate_facility_design_constraints(
    *,
    baseline_layout: Mapping[str, Any],
    candidate_layout: Mapping[str, Any],
    brief: Mapping[str, Any],
    containment_checker: ContainmentChecker | None = None,
) -> list[dict[str, Any]]:
    baseline = canonicalize_layout(baseline_layout)
    candidate = canonicalize_layout(candidate_layout)
    brief_record = validate_facility_design_brief(brief)
    registry = facility_design_constraint_registry()
    baseline_revision = layout_revision(baseline)
    results = []
    for constraint in brief_record["semanticBody"]["hardConstraints"]:
        if constraint["status"] != "active":
            continue
        kind = constraint["constraintKind"]
        if kind not in FACILITY_DESIGN_CONSTRAINT_KINDS or kind not in registry:
            _fail("facility_design_constraint_kind_unsupported", "Hard constraint has no executable predicate.", constraintKind=kind)
        statuses = []
        evidence = []
        details = {}
        stale_refs = sorted(
            f"{item['entityKind']}:{item['entityId']}"
            for item in constraint["targetRefs"]
            if item["sourceRevision"] != baseline_revision
        )
        if stale_refs:
            statuses.append("stale")
            details["staleTargetRefs"] = stale_refs
        elif kind == "remain_inside_area":
            area_refs = [
                item
                for item in constraint["targetRefs"]
                if item["entityKind"] == "zone"
            ]
            placement_refs = [
                item
                for item in constraint["targetRefs"]
                if item["entityKind"] == "placement"
            ]
            area = (
                _entity(candidate, "zone", area_refs[0]["entityId"])
                if len(area_refs) == 1
                else None
            )
            placements = [
                _entity(candidate, "placement", item["entityId"])
                for item in placement_refs
            ]
            if len(area_refs) != 1 or not placement_refs or area is None:
                statuses.append("unavailable")
            elif any(item is None for item in placements):
                statuses.append("stale")
            elif containment_checker is None:
                statuses.append("unavailable")
            else:
                checks = [
                    containment_checker(
                        candidate,
                        placement,
                        area_refs[0]["entityId"],
                        constraint["predicateVersion"],
                    )
                    for placement in placements
                    if placement is not None
                ]
                details["containmentChecks"] = [dict(item[1]) for item in checks]
                if all(item[0] == "satisfied" for item in checks):
                    statuses.append("satisfied")
                elif any(item[0] == "violated" for item in checks):
                    statuses.append("violated")
                else:
                    statuses.append("unavailable")
        else:
            for ref in constraint["targetRefs"]:
                entity_kind = ref["entityKind"]
                entity_id = ref["entityId"]
                before = _entity(baseline, entity_kind, entity_id)
                after = _entity(candidate, entity_kind, entity_id)
                if kind == "preserve_entity_identity":
                    status = "satisfied" if before is not None and after is not None else "violated"
                elif before is None or after is None:
                    status = registry[kind]["missingEvidenceBehavior"]
                else:
                    projection_kind = "route" if kind == "preserve_route_geometry" else (
                        "process_binding" if kind == "preserve_process_binding" else entity_kind
                    )
                    before_hash = _projection_hash(_geometry_projection(projection_kind, before))
                    after_hash = _projection_hash(_geometry_projection(projection_kind, after))
                    evidence.extend([before_hash, after_hash])
                    status = "satisfied" if before_hash == after_hash else "violated"
                statuses.append(status)
        if "violated" in statuses:
            aggregate = "violated"
        elif "stale" in statuses:
            aggregate = "stale"
        elif "unavailable" in statuses:
            aggregate = "unavailable"
        else:
            aggregate = "satisfied"
        results.append(
            {
                "constraintId": constraint["constraintId"],
                "constraintKind": kind,
                "status": aggregate,
                "predicateVersion": registry[kind]["predicateVersion"],
                "dependencyProjection": registry[kind]["dependencyProjection"],
                "violationCode": None if aggregate == "satisfied" else registry[kind]["violationCode"],
                "evidenceRefs": sorted(set([*constraint["evidenceRefs"], *evidence])),
                "details": details,
            }
        )
    return sorted(results, key=lambda item: item["constraintId"])


def build_facility_design_baseline(
    *,
    baseline_id: str,
    layout: Mapping[str, Any],
    brief: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    containment_checker: ContainmentChecker | None = None,
    source_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_layout = canonicalize_layout(layout)
    constraints = evaluate_facility_design_constraints(
        baseline_layout=canonical_layout,
        candidate_layout=canonical_layout,
        brief=brief,
        containment_checker=containment_checker,
    )
    metrics = calculate_facility_design_metrics(
        baseline_layout=canonical_layout,
        candidate_layout=canonical_layout,
        snapshot=snapshot,
        source_bundle=source_bundle,
    )
    record = {
        "schemaVersion": "facility-design-baseline-v1",
        "baselineId": str(baseline_id),
        "baselineRevision": "",
        "layoutRevision": layout_revision(canonical_layout),
        "briefRevision": validate_facility_design_brief(brief)["briefRevision"],
        "snapshotRevision": validate_facility_manufacturing_snapshot(snapshot)["snapshotRevision"],
        "constraintResults": constraints,
        "metrics": metrics,
        "feasible": all(item["status"] == "satisfied" for item in constraints),
        "evaluatorVersion": FACILITY_DESIGN_EVALUATOR_VERSION,
    }
    without_revision = deepcopy(record)
    without_revision.pop("baselineRevision")
    record["baselineRevision"] = design_revision(without_revision)
    return record


def evaluate_facility_design_candidate(
    *,
    evaluation_id: str,
    baseline_layout: Mapping[str, Any],
    candidate_layout: Mapping[str, Any],
    brief: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    baseline: Mapping[str, Any],
    containment_checker: ContainmentChecker | None = None,
    source_bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_metric_index = {
        item["metricId"]: item for item in baseline.get("metrics", [])
    }
    constraints = evaluate_facility_design_constraints(
        baseline_layout=baseline_layout,
        candidate_layout=candidate_layout,
        brief=brief,
        containment_checker=containment_checker,
    )
    metrics = calculate_facility_design_metrics(
        baseline_layout=baseline_layout,
        candidate_layout=candidate_layout,
        snapshot=snapshot,
        baseline_metrics=baseline_metric_index,
        source_bundle=source_bundle,
    )
    metric_index = {item["metricId"]: item for item in metrics}
    distance = metric_index["loadedRouteDistanceMeters"]
    feasible = all(item["status"] == "satisfied" for item in constraints)
    objective_improved = bool(
        feasible
        and distance["status"] == "measured"
        and distance["baselineValue"] is not None
        and float(distance["baselineValue"]) - float(distance["value"])
        > FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS
    )
    minimum = validate_facility_design_brief(brief)["semanticBody"]["objective"].get(
        "minimumImprovement"
    )
    minimum_satisfied = None
    if minimum is not None:
        measured = metric_index.get(minimum["metricId"])
        minimum_satisfied = bool(
            objective_improved
            and measured is not None
            and measured["status"] == "measured"
            and measured["delta"] is not None
            and -float(measured["delta"])
            + FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS
            >= float(minimum["value"])
        )
    result = {
        "schemaVersion": "facility-design-evaluation-v1",
        "evaluationId": str(evaluation_id),
        "evaluationRevision": "",
        "candidateLayoutRevision": layout_revision(candidate_layout),
        "baselineRevision": str(baseline["baselineRevision"]),
        "briefRevision": validate_facility_design_brief(brief)["briefRevision"],
        "snapshotRevision": validate_facility_manufacturing_snapshot(snapshot)["snapshotRevision"],
        "constraintResults": constraints,
        "metrics": metrics,
        "feasible": feasible,
        "objectiveImproved": objective_improved,
        "minimumImprovementSatisfied": minimum_satisfied,
        "operationallyMeaningful": minimum_satisfied,
        "nonDominated": False,
        "preferred": False,
        "preferenceReason": None,
        "evaluatorVersion": FACILITY_DESIGN_EVALUATOR_VERSION,
    }
    without_revision = deepcopy(result)
    without_revision.pop("evaluationRevision")
    result["evaluationRevision"] = design_revision(without_revision)
    return result


def _active_preference_metric_ids(brief: Mapping[str, Any]) -> list[str]:
    record = validate_facility_design_brief(brief)
    return [
        item["metricId"]
        for item in sorted(
            (
                item
                for item in record["semanticBody"]["preferences"]
                if item["status"] == "active"
            ),
            key=lambda item: (item["priority"], item["preferenceId"]),
        )
    ]


def _smaller_is_better(metric_id: str) -> bool:
    return metric_id in {
        "loadedRouteDistanceMeters",
        "loadedTravelMetersPerShift",
        "movedPlacementCount",
        "placementDisplacementMeters",
        "rotatedPlacementCount",
        "changedRouteCount",
        "affectedProcessBindingCount",
    }


def classify_facility_design_alternatives(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    brief: Mapping[str, Any],
) -> list[dict[str, Any]]:
    results = [deepcopy(dict(item)) for item in evaluations]
    candidates = [item for item in results if item.get("objectiveImproved")]
    metric_ids = [
        "loadedRouteDistanceMeters",
        "movedPlacementCount",
        "placementDisplacementMeters",
        "rotatedPlacementCount",
        "changedRouteCount",
        "affectedProcessBindingCount",
    ]
    indexes = {
        item["evaluationId"]: {metric["metricId"]: metric for metric in item["metrics"]}
        for item in candidates
    }
    for item in candidates:
        current = indexes[item["evaluationId"]]
        dominated = False
        for other in candidates:
            if other["evaluationId"] == item["evaluationId"]:
                continue
            comparison = indexes[other["evaluationId"]]
            comparable = [
                metric_id
                for metric_id in metric_ids
                if current.get(metric_id, {}).get("status") == "measured"
                and comparison.get(metric_id, {}).get("status") == "measured"
            ]
            no_worse = all(
                float(comparison[metric_id]["value"])
                <= float(current[metric_id]["value"])
                + FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS
                for metric_id in comparable
            )
            strictly_better = any(
                float(comparison[metric_id]["value"])
                < float(current[metric_id]["value"])
                - FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS
                for metric_id in comparable
            )
            if comparable and no_worse and strictly_better:
                dominated = True
                break
        item["nonDominated"] = not dominated
    frontier = [item for item in candidates if item.get("nonDominated")]
    preferences = _active_preference_metric_ids(brief)
    if preferences and frontier:
        remaining = frontier
        reasons = []
        for metric_id in preferences:
            measured = [
                item
                for item in remaining
                if indexes[item["evaluationId"]].get(metric_id, {}).get("status")
                == "measured"
            ]
            if not measured:
                continue
            values = [float(indexes[item["evaluationId"]][metric_id]["value"]) for item in measured]
            target = min(values) if _smaller_is_better(metric_id) else max(values)
            remaining = [
                item
                for item in measured
                if abs(float(indexes[item["evaluationId"]][metric_id]["value"]) - target)
                <= FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS
            ]
            reasons.append(metric_id)
            if len(remaining) == 1:
                remaining[0]["preferred"] = True
                remaining[0]["preferenceReason"] = {
                    "wording": "preferred among the evaluated bounded alternatives",
                    "metricPriorityPrefix": reasons,
                }
                break
    for item in results:
        without_revision = deepcopy(item)
        without_revision.pop("evaluationRevision", None)
        item["evaluationRevision"] = design_revision(without_revision)
    return sorted(results, key=lambda item: item["evaluationId"])


__all__ = [
    "FACILITY_DESIGN_AREA_TOLERANCE_SQUARE_METERS",
    "FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION",
    "FACILITY_DESIGN_DISTANCE_TOLERANCE_METERS",
    "FACILITY_DESIGN_EVALUATOR_VERSION",
    "FacilityDesignEvaluationError",
    "build_facility_design_baseline",
    "calculate_facility_design_metrics",
    "classify_facility_design_alternatives",
    "evaluate_facility_design_candidate",
    "evaluate_facility_design_constraints",
    "facility_design_constraint_registry",
    "route_path_distance_meters",
]
