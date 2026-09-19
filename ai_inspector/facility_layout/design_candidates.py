"""Bounded, isolated candidate recipes for the first Facility design objective."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision
from .design_base import validate_facility_design_base
from .design_brief import (
    canonical_design_bytes,
    design_revision,
    validate_facility_design_brief,
)
from .manufacturing_snapshot import validate_facility_manufacturing_snapshot
from .operations import apply_facility_layout_operations
from .routing import persisted_route_fingerprint
from .design_routing import (
    FacilityDesignRoutingError,
    resolve_design_route_endpoint,
    shortest_design_route_centerline,
)
from .spatial import generate_placement_candidates


FACILITY_DESIGN_CANDIDATE_SCHEMA_VERSION = "facility-design-candidate-v1"
FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES = 4
FACILITY_DESIGN_CANDIDATE_MAXIMUM_ATTEMPTS = 6
FACILITY_DESIGN_CANDIDATE_MAXIMUM_OPERATIONS = 500


class FacilityDesignCandidateError(ValueError):
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
    raise FacilityDesignCandidateError(code, message, details=details)


def _active_permissions(brief: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    record = validate_facility_design_brief(brief)
    return [
        item
        for item in record["semanticBody"]["permittedChanges"]
        if item["status"] == "active"
    ]


def _permitted_target_ids(
    brief: Mapping[str, Any], operation_kind: str, entity_kind: str
) -> list[str]:
    return sorted(
        {
            ref["entityId"]
            for permission in _active_permissions(brief)
            if operation_kind in permission["operationKinds"]
            for ref in permission["targetRefs"]
            if ref["entityKind"] == entity_kind
        }
    )


def _recipe(
    *,
    lever_kind: str,
    target_ids: Sequence[str],
    strategy_id: str,
    route_ids: Sequence[str],
) -> dict[str, Any]:
    semantics = {
        "leverKind": lever_kind,
        "targetIds": sorted(set(target_ids)),
        "strategyId": strategy_id,
        "routeIds": list(route_ids),
    }
    fingerprint = design_revision(semantics)
    return {
        "schemaVersion": FACILITY_DESIGN_CANDIDATE_SCHEMA_VERSION,
        "recipeId": f"fdlr-{fingerprint[:24]}",
        "recipeFingerprint": fingerprint,
        **semantics,
    }


def enumerate_facility_design_candidate_recipes(
    *,
    brief: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    brief_record = validate_facility_design_brief(brief)
    snapshot_record = validate_facility_manufacturing_snapshot(snapshot)
    if brief_record["semanticBody"]["objective"]["objectiveKind"] != "reduce_loaded_material_travel_v1":
        _fail("facility_design_objective_kind_unsupported", "Candidate enumeration supports only the first material-travel objective.")
    editable_routes = set(
        _permitted_target_ids(brief_record, "edit_material_route", "route")
    )
    route_path = [
        route_id
        for route_id in snapshot_record["routePath"]["routeIds"]
        if route_id in editable_routes
    ]
    source_id = snapshot_record["endpoints"]["source"]["placementId"]
    target_id = snapshot_record["endpoints"]["target"]["placementId"]
    movable = set(
        _permitted_target_ids(
            brief_record, "move_placement_within_area", "placement"
        )
    )
    frontier = []
    for route_id in route_path:
        frontier.append(
            _recipe(
                lever_kind="route_only_reflow",
                target_ids=[route_id],
                strategy_id="deterministic_route_reflow_v1",
                route_ids=[route_id],
            )
        )
    if source_id in movable:
        frontier.append(
            _recipe(
                lever_kind="source_buffer_fit",
                target_ids=[source_id],
                strategy_id="deterministic_source_buffer_fit_v1",
                route_ids=route_path,
            )
        )
    if target_id in movable:
        frontier.append(
            _recipe(
                lever_kind="destination_buffer_fit",
                target_ids=[target_id],
                strategy_id="deterministic_destination_buffer_fit_v1",
                route_ids=route_path,
            )
        )
    if source_id in movable and target_id in movable:
        frontier.append(
            _recipe(
                lever_kind="combined_buffer_fit",
                target_ids=[source_id, target_id],
                strategy_id="deterministic_combined_buffer_fit_v1",
                route_ids=route_path,
            )
        )
    route_order = {
        route_id: index for index, route_id in enumerate(route_path)
    }
    lever_order = {
        "source_buffer_fit": 0,
        "destination_buffer_fit": 1,
        "route_only_reflow": 2,
        "combined_buffer_fit": 3,
    }
    frontier.sort(
        key=lambda item: (
            lever_order[item["leverKind"]],
            min(
                (route_order.get(route_id, len(route_order)) for route_id in item["routeIds"]),
                default=len(route_order),
            ),
            item["targetIds"],
            item["strategyId"],
            item["routeIds"],
        )
    )
    selected = frontier[:FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES]
    return {
        "schemaVersion": "facility-design-search-v1",
        "briefRevision": brief_record["briefRevision"],
        "snapshotRevision": snapshot_record["snapshotRevision"],
        "searchStatus": "complete" if len(frontier) <= len(selected) else "truncated",
        "frontierCount": len(frontier),
        "unexpandedFrontierCount": max(0, len(frontier) - len(selected)),
        "recipes": selected,
        "searchFingerprint": design_revision(
            {
                "briefSemanticFingerprint": brief_record["briefSemanticFingerprint"],
                "snapshotRevision": snapshot_record["snapshotRevision"],
                "frontier": frontier,
                "selectedRecipeIds": [item["recipeId"] for item in selected],
            }
        ),
    }


OperationBuilder = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    Sequence[Mapping[str, Any]],
]
SourceOperationBuilder = Callable[
    [
        Mapping[str, Any],
        Mapping[str, Any],
        Mapping[str, Any],
        Mapping[str, Any],
    ],
    Sequence[Mapping[str, Any]],
]


def _operation_target(operation: Mapping[str, Any]) -> tuple[str, str, str]:
    operation_name = operation.get("op")
    if operation_name == "move_placement":
        return "move_placement_within_area", "placement", str(operation.get("placementId") or "")
    if operation_name == "rotate_placement":
        return "rotate_placement_fit", "placement", str(operation.get("placementId") or "")
    if operation_name in {"edit_route", "edit_aisle"}:
        return "edit_material_route", "route", str(operation.get("routeId") or "")
    _fail(
        "facility_design_candidate_operation_forbidden",
        "Candidate operation is outside the first design-loop search surface.",
        operation=operation_name,
    )
    raise AssertionError("unreachable")


def _assert_operations_permitted(
    operations: Sequence[Mapping[str, Any]], brief: Mapping[str, Any]
) -> None:
    permissions = _active_permissions(brief)
    for operation in operations:
        operation_kind, entity_kind, entity_id = _operation_target(operation)
        allowed = any(
            operation_kind in permission["operationKinds"]
            and any(
                ref["entityKind"] == entity_kind and ref["entityId"] == entity_id
                for ref in permission["targetRefs"]
            )
            for permission in permissions
        )
        if not allowed:
            _fail(
                "facility_design_candidate_operation_forbidden",
                "Candidate operation targets an entity that the user did not permit to change.",
                operationKind=operation_kind,
                entityKind=entity_kind,
                entityId=entity_id,
            )


def _identity_payloads(layout: Mapping[str, Any]) -> dict[tuple[str, str], bytes]:
    result: dict[tuple[str, str], bytes] = {}
    for collection, id_field in (
        ("zones", "zoneId"),
        ("placements", "placementId"),
        ("routes", "routeId"),
        ("processBindings", "processBindingId"),
    ):
        for item in layout.get(collection, []):
            if isinstance(item, Mapping) and isinstance(item.get(id_field), str):
                result[(collection, str(item[id_field]))] = canonical_design_bytes(item)
    return result


def execute_facility_design_candidate(
    *,
    candidate_id: str,
    recipe: Mapping[str, Any],
    design_base: Mapping[str, Any],
    brief: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    operation_builder: OperationBuilder,
    updated_at: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    base = validate_facility_design_base(design_base)
    brief_record = validate_facility_design_brief(brief)
    snapshot_record = validate_facility_manufacturing_snapshot(snapshot)
    if snapshot_record["baseRef"]["baseRevision"] != base["baseRevision"]:
        _fail("facility_design_candidate_base_mismatch", "Snapshot and candidate do not share the same immutable base.")
    if snapshot_record["briefRef"]["briefRevision"] != brief_record["briefRevision"]:
        _fail("facility_design_candidate_brief_mismatch", "Snapshot and candidate do not share the same brief revision.")
    if cancel_check is not None and cancel_check():
        _fail("facility_design_candidate_cancelled", "Candidate execution was cancelled before geometry generation.")
    operations = [deepcopy(dict(item)) for item in operation_builder(recipe, base["document"], snapshot_record)]
    if len(operations) > FACILITY_DESIGN_CANDIDATE_MAXIMUM_OPERATIONS:
        _fail(
            "facility_design_candidate_operation_limit_exceeded",
            "Candidate operation batch exceeds the Facility kernel limit.",
            operationCount=len(operations),
        )
    _assert_operations_permitted(operations, brief_record)
    operation_plan_hash = design_revision(operations)
    if cancel_check is not None and cancel_check():
        _fail("facility_design_candidate_cancelled", "Candidate execution was cancelled before atomic operation apply.")
    result = apply_facility_layout_operations(
        base["document"],
        operations,
        base_revision=base["layoutRevision"],
        updated_at=updated_at,
    )
    candidate_layout = result["document"]
    permitted_keys = {
        (
            "placements" if entity_kind == "placement" else "routes",
            entity_id,
        )
        for operation in operations
        for _, entity_kind, entity_id in [_operation_target(operation)]
    }
    before = _identity_payloads(base["document"])
    after = _identity_payloads(candidate_layout)
    unrelated_changes = sorted(
        f"{collection}:{entity_id}"
        for collection, entity_id in set(before) | set(after)
        if (collection, entity_id) not in permitted_keys
        and before.get((collection, entity_id)) != after.get((collection, entity_id))
    )
    if unrelated_changes:
        _fail(
            "facility_design_candidate_closed_world_violation",
            "Candidate changed entities outside the explicit permitted-change set.",
            entityRefs=unrelated_changes,
        )
    artifact = {
        "schemaVersion": FACILITY_DESIGN_CANDIDATE_SCHEMA_VERSION,
        "candidateId": str(candidate_id),
        "candidateRevision": "",
        "recipe": deepcopy(dict(recipe)),
        "recipeFingerprint": str(recipe.get("recipeFingerprint") or design_revision(recipe)),
        "baseRevision": base["baseRevision"],
        "baseLayoutRevision": base["layoutRevision"],
        "briefRevision": brief_record["briefRevision"],
        "snapshotRevision": snapshot_record["snapshotRevision"],
        "operationPlanHash": operation_plan_hash,
        "operations": operations,
        "resultLayoutRevision": layout_revision(candidate_layout),
        "canonicalDiff": deepcopy(result["canonicalDiff"]),
        "diffHash": result["diffHash"],
        "affectedIds": deepcopy(result["affectedIds"]),
        "candidateLayout": candidate_layout,
        "previewPure": True,
    }
    unsigned = deepcopy(artifact)
    unsigned.pop("candidateRevision")
    artifact["candidateRevision"] = design_revision(unsigned)
    canonical_layout_bytes(base["document"])
    return artifact


def fixture_recipe_operation_builder(
    recipe: Mapping[str, Any],
    layout: Mapping[str, Any],
    _snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Translate reviewed fixture edits through the ordinary operation kernel."""

    operations = []
    for edit in recipe.get("placementEdits", []):
        operations.append(
            {
                "op": "move_placement",
                "placementId": edit["placementId"],
                "position": deepcopy(edit["position"]),
                "movementKind": "user",
            }
        )
    route_by_id = {
        item["routeId"]: item
        for item in layout.get("routes", [])
        if isinstance(item, Mapping)
    }
    for edit in recipe.get("routeEdits", []):
        route = deepcopy(route_by_id[edit["routeId"]])
        route["centerline"] = deepcopy(edit["centerline"])
        route["routeFingerprint"] = persisted_route_fingerprint(route)
        operations.append(
            {
                "op": "edit_route",
                "routeId": edit["routeId"],
                "patch": {
                    "centerline": deepcopy(route["centerline"]),
                    "routeFingerprint": route["routeFingerprint"],
                },
            }
        )
    return operations


def _source_asset_definition(
    placement: Mapping[str, Any],
    source_bundle: Mapping[str, Any],
) -> Mapping[str, Any]:
    asset_id = str(placement.get("assetId") or "")
    revision = str(placement.get("assetDefinitionRevision") or "")
    matches = [
        item
        for item in source_bundle.get("assetDefinitions", [])
        if isinstance(item, Mapping)
        and str(
            item.get("assetId")
            or (item.get("definition") or {}).get("assetId")
            or ""
        )
        == asset_id
        and str(item.get("assetDefinitionRevision") or item.get("revision") or "")
        == revision
    ]
    if len(matches) != 1:
        _fail(
            "placement_no_fit",
            "The movable placement has no exact revision-bound asset geometry.",
            affectedIds=[str(placement.get("placementId") or "")],
        )
    return matches[0]


def _position(placement: Mapping[str, Any]) -> dict[str, float]:
    value = ((placement.get("transform") or {}).get("position") or {})
    try:
        return {
            "x": float(value["x"]),
            "y": float(value.get("y", 0.0)),
            "z": float(value["z"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityDesignCandidateError(
            "placement_no_fit",
            "The movable placement has no canonical position.",
        ) from exc


def _with_moved_placement(
    layout: Mapping[str, Any],
    placement_id: str,
    position: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(layout))
    for placement in result.get("placements", []):
        if isinstance(placement, Mapping) and placement.get("placementId") == placement_id:
            placement["transform"]["position"] = deepcopy(dict(position))
            return result
    _fail(
        "placement_no_fit",
        "The movable placement is absent from the candidate layout.",
        affectedIds=[placement_id],
    )
    raise AssertionError("unreachable")


def _fit_operation(
    layout: Mapping[str, Any],
    placement_id: str,
    requested_position: Mapping[str, Any],
    source_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    placement = next(
        (
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId") == placement_id
        ),
        None,
    )
    if not isinstance(placement, Mapping):
        _fail(
            "placement_no_fit",
            "The movable placement is absent from the candidate layout.",
            affectedIds=[placement_id],
        )
    asset = _source_asset_definition(placement, source_bundle)
    try:
        generated = generate_placement_candidates(
            layout,
            asset,
            requested_position,
            source_bundle.get("assetDefinitions", []),
            enabled_families=("grid", "boundary", "row", "alignment"),
            requested_quaternion=(placement.get("transform") or {}).get("quaternion"),
            target_placement_id=placement_id,
            asset_definition_revision=str(placement["assetDefinitionRevision"]),
            maximum_candidates=64,
        )
    except (TypeError, ValueError) as exc:
        raise FacilityDesignCandidateError(
            "placement_no_fit",
            "The deterministic fit engine could not evaluate the movable placement.",
            details={"affectedIds": [placement_id], "reason": str(exc)},
        ) from exc
    containing_area = (
        source_bundle.get("containingAreaIds", {}).get(placement_id)
        if isinstance(source_bundle.get("containingAreaIds"), Mapping)
        else None
    )
    candidates = [
        item
        for item in generated.get("candidates", [])
        if isinstance(item, Mapping)
        and (
            containing_area is None
            or (item.get("snapRelationship") or {}).get("zoneId")
            == containing_area
        )
    ]
    current = _position(placement)
    candidates = [
        item
        for item in candidates
        if any(
            abs(float(item["transform"]["position"][axis]) - current[axis]) > 1.0e-6
            for axis in ("x", "z")
        )
    ]
    if not candidates:
        _fail(
            "placement_no_fit",
            "No collision-free placement alternative exists in the permitted area.",
            affectedIds=[placement_id],
        )
    selected = candidates[0]
    return {
        "op": "move_placement",
        "placementId": placement_id,
        "position": deepcopy(selected["transform"]["position"]),
        # The active brief is the user's explicit permission to move this
        # otherwise manual placement. The recipe and candidate artifact retain
        # that deterministic fit, rather than the user, selected the position.
        "movementKind": "user",
    }


def deterministic_design_operation_builder(
    recipe: Mapping[str, Any],
    layout: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    source_bundle: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Compile coordinate-free recipes through fit and routing engines."""

    working = deepcopy(canonicalize_layout(layout))
    transfer = snapshot["materialTransfer"]
    placements = {
        str(item.get("placementId")): item
        for item in working.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    source_id = str(transfer["sourcePlacementId"])
    target_id = str(transfer["targetPlacementId"])
    operations: list[dict[str, Any]] = []
    lever = str(recipe.get("leverKind") or "")
    move_ids: list[str] = []
    if lever == "source_buffer_fit":
        move_ids = [source_id]
    elif lever == "destination_buffer_fit":
        move_ids = [target_id]
    elif lever == "combined_buffer_fit":
        move_ids = [source_id, target_id]
    elif lever != "route_only_reflow":
        _fail(
            "no_layout_alternative",
            "The selected deterministic strategy is not supported.",
            strategyId=recipe.get("strategyId"),
        )
    for placement_id in move_ids:
        opposite_id = target_id if placement_id == source_id else source_id
        opposite = placements.get(opposite_id)
        if not isinstance(opposite, Mapping):
            _fail(
                "placement_no_fit",
                "The opposite transfer endpoint is unavailable.",
                affectedIds=[opposite_id],
            )
        operation = _fit_operation(
            working,
            placement_id,
            _position(opposite),
            source_bundle,
        )
        operations.append(operation)
        working = _with_moved_placement(
            working,
            placement_id,
            operation["position"],
        )
        placements[placement_id] = next(
            item
            for item in working["placements"]
            if item.get("placementId") == placement_id
        )

    route_by_id = {
        str(item.get("routeId")): item
        for item in working.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    route_ids = [str(item) for item in recipe.get("routeIds", [])]
    if move_ids:
        route_ids = [
            route_id
            for route_id in route_ids
            if route_id in route_by_id
            and any(
                isinstance(route_by_id[route_id].get(endpoint_name), Mapping)
                and route_by_id[route_id][endpoint_name].get("kind")
                == "placement_connector"
                and str(
                    route_by_id[route_id][endpoint_name].get("placementId")
                    or ""
                )
                in move_ids
                for endpoint_name in ("sourceEndpoint", "targetEndpoint")
            )
        ]
        missing_connections = sorted(
            placement_id
            for placement_id in move_ids
            if not any(
                any(
                    isinstance(route_by_id[route_id].get(endpoint_name), Mapping)
                    and str(
                        route_by_id[route_id][endpoint_name].get("placementId")
                        or ""
                    )
                    == placement_id
                    for endpoint_name in ("sourceEndpoint", "targetEndpoint")
                )
                for route_id in route_ids
            )
        )
        if missing_connections:
            _fail(
                "no_layout_alternative",
                "A moved transfer endpoint has no permitted connected route to reflow.",
                affectedIds=missing_connections,
            )
    if not route_ids:
        _fail(
            "no_layout_alternative",
            "The coordinate-free design recipe does not identify a mutable route.",
            strategyId=recipe.get("strategyId"),
        )
    excluded = [source_id, target_id]
    for route_id in route_ids:
        route = route_by_id.get(route_id)
        if not isinstance(route, Mapping):
            _fail(
                "route_blocked",
                "The mutable route is absent from the candidate layout.",
                affectedIds=[route_id],
            )
        try:
            start = resolve_design_route_endpoint(
                working,
                route.get("sourceEndpoint") or {},
                route_kind=str(route.get("routeKind") or "material"),
                direction="source",
                source_bundle=source_bundle,
            )
            goal = resolve_design_route_endpoint(
                working,
                route.get("targetEndpoint") or {},
                route_kind=str(route.get("routeKind") or "material"),
                direction="target",
                source_bundle=source_bundle,
            )
            centerline = shortest_design_route_centerline(
                working,
                start=start,
                goal=goal,
                corridor_width_meters=float(route["corridorWidth"]),
                source_bundle=source_bundle,
                excluded_placement_ids=excluded,
            )
        except FacilityDesignRoutingError as exc:
            raise FacilityDesignCandidateError(
                "route_blocked",
                str(exc),
                details={
                    "affectedIds": [route_id],
                    "sourceCode": exc.code,
                    **exc.details,
                },
            ) from exc
        updated_route = deepcopy(dict(route))
        updated_route["centerline"] = centerline
        updated_route["routeFingerprint"] = persisted_route_fingerprint(updated_route)
        operations.append(
            {
                "op": "edit_route",
                "routeId": route_id,
                "patch": {
                    "centerline": centerline,
                    "routeFingerprint": updated_route["routeFingerprint"],
                },
            }
        )
        route["centerline"] = centerline
        route["routeFingerprint"] = updated_route["routeFingerprint"]
    return operations


__all__ = [
    "FACILITY_DESIGN_CANDIDATE_MAXIMUM_ATTEMPTS",
    "FACILITY_DESIGN_CANDIDATE_MAXIMUM_LINEAGES",
    "FACILITY_DESIGN_CANDIDATE_MAXIMUM_OPERATIONS",
    "FACILITY_DESIGN_CANDIDATE_SCHEMA_VERSION",
    "FacilityDesignCandidateError",
    "enumerate_facility_design_candidate_recipes",
    "execute_facility_design_candidate",
    "deterministic_design_operation_builder",
    "fixture_recipe_operation_builder",
]
