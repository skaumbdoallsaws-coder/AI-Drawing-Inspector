"""Closed semantic contract for one resumable full-factory generation run."""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Mapping, Sequence

from .asset_placement import (
    G4_ACCESS_REQUIREMENTS,
    G4_ASSET_PLACEMENT_SCOPE,
    G4_MAXIMUM_ASSET_QUANTITY,
    G4_ORIENTATION_MODES,
    G4_RESOURCE_ROLES,
    build_asset_catalog_snapshot,
)
from .cell_composition import (
    CELL_FEASIBILITY_STRATEGIES,
    G5_CELL_COMPOSITION_SCOPE,
    G5_CELL_OBJECTIVES,
)
from .cell_replication import (
    G6_CELL_REPLICATION_SCOPE,
    G6_MAXIMUM_TARGET_AREAS,
)
from .circulation import (
    G2_CIRCULATION_SCOPE,
    G2_DIRECTIONS,
    G2_ROUTE_KINDS,
)
from .knowledge_foundation import (
    facility_knowledge_revision,
    validate_department_partition_request,
    validate_facility_envelope_request,
)
from .subdivisions import G3_SUBDIVISION_SCOPE


FULL_FACTORY_SCOPE = "full_factory_generation"
FULL_FACTORY_TOOL = "generate_full_factory_draft"
FULL_FACTORY_MAX_ROUTES = 24
FULL_FACTORY_MAX_CROSSINGS = 24
FULL_FACTORY_MAX_SUBDIVISIONS = 24
FULL_FACTORY_MAX_ASSET_REQUESTS = 100
FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY = 900
FULL_FACTORY_MAX_CELL_RECIPES = 24
FULL_FACTORY_MAX_MODULE_FAMILIES = 24

_UNITS = frozenset({"m", "mm", "ft", "in"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class FacilityFullFactoryError(RuntimeError):
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


def _closed(value: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FacilityFullFactoryError(
            "full_factory_model_geometry_or_unknown_field",
            f"{field} contains unsupported fields.",
            details={"field": field, "unknown": unknown},
        )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityFullFactoryError(
            "full_factory_program_invalid",
            f"{field} must be an object.",
            details={"field": field},
        )
    return deepcopy(dict(value))


def _list(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise FacilityFullFactoryError(
            "full_factory_program_budget_exceeded",
            f"{field} must be an array with at most {maximum} entries.",
            details={"field": field, "maximum": maximum},
        )
    return deepcopy(value)


def _text(value: Any, field: str, *, maximum: int = 160) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise FacilityFullFactoryError(
            "full_factory_text_invalid",
            f"{field} must be a non-empty string no longer than {maximum} characters.",
            details={"field": field},
        )
    return text


def _positive(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FacilityFullFactoryError(
            "full_factory_dimension_invalid",
            f"{field} must be numeric.",
            details={"field": field},
        )
    number = float(value)
    if not math.isfinite(number) or (number < 0 if allow_zero else number <= 0):
        raise FacilityFullFactoryError(
            "full_factory_dimension_invalid",
            f"{field} must be {'non-negative' if allow_zero else 'positive'}.",
            details={"field": field},
        )
    return number


def _unit(value: Any, field: str) -> str:
    unit = str(value or "").strip().lower()
    if unit not in _UNITS:
        raise FacilityFullFactoryError(
            "full_factory_unit_invalid",
            f"{field} must be m, mm, ft, or in.",
            details={"field": field},
        )
    return unit


def _partition(
    raw: Mapping[str, Any],
    *,
    field: str,
    require_parent: bool,
) -> dict[str, Any]:
    allowed = {
        "count",
        "labels",
        "proportions",
        "arrangement",
        "orientation",
        "rows",
    }
    if require_parent:
        allowed.add("parent_department")
    _closed(raw, allowed, field)
    proportions = deepcopy(raw.get("proportions"))
    if proportions == []:
        proportions = None
    rows = deepcopy(raw.get("rows"))
    arrangement = raw.get("arrangement")
    if isinstance(rows, list) and rows:
        # Explicit row membership is more specific than the generic rows grid mode.
        arrangement = "row_stack"
    request = {
        "count": raw.get("count"),
        "labels": deepcopy(raw.get("labels")),
        "proportions": proportions,
        "arrangement": arrangement,
        "orientation": raw.get("orientation"),
        "rows": rows,
    }
    try:
        normalized = validate_department_partition_request(request)
    except Exception as exc:
        raise FacilityFullFactoryError(
            "full_factory_partition_invalid",
            f"{field} is not a complete deterministic partition.",
            details={"field": field, "cause": str(exc)},
        ) from exc
    result = {
        "count": normalized["count"],
        "labels": list(normalized["labels"]),
        "proportions": list(normalized["proportions"]),
        "arrangement": normalized["arrangement"],
        "orientation": normalized["orientation"],
        "rows": deepcopy(normalized["rows"]),
    }
    if require_parent:
        result["parent_department"] = _text(
            raw.get("parent_department"), f"{field}.parent_department"
        )
    return result


def _canonical_route(raw: Mapping[str, Any], index: int) -> dict[str, Any]:
    field = f"circulation.routes[{index}]"
    _closed(
        raw,
        {
            "route_kind",
            "width",
            "source_unit",
            "source_department",
            "target_department",
            "via_departments",
            "direction",
            "label",
        },
        field,
    )
    route_kind = str(raw.get("route_kind") or "").strip().lower()
    direction = str(raw.get("direction") or "").strip().lower()
    if route_kind not in G2_ROUTE_KINDS or direction not in G2_DIRECTIONS:
        raise FacilityFullFactoryError(
            "full_factory_route_invalid",
            "Full-factory routes require a registered route kind and direction.",
            details={"field": field},
        )
    via = _list(raw.get("via_departments"), f"{field}.via_departments", 50)
    via = [_text(item, f"{field}.via_departments") for item in via]
    return {
        "route_kind": route_kind,
        "width": _positive(raw.get("width"), f"{field}.width"),
        "source_unit": _unit(raw.get("source_unit"), f"{field}.source_unit"),
        "source_department": _text(
            raw.get("source_department"), f"{field}.source_department"
        ),
        "target_department": _text(
            raw.get("target_department"), f"{field}.target_department"
        ),
        "via_departments": via,
        "direction": direction,
        "label": _text(raw.get("label"), f"{field}.label"),
    }


def _canonical_crossing(raw: Mapping[str, Any], index: int) -> dict[str, Any]:
    field = f"circulation.crossings[{index}]"
    _closed(raw, {"route_labels", "width", "depth", "source_unit", "label"}, field)
    labels = _list(raw.get("route_labels"), f"{field}.route_labels", 2)
    labels = [_text(item, f"{field}.route_labels") for item in labels]
    if len(labels) != 2 or len({item.casefold() for item in labels}) != 2:
        raise FacilityFullFactoryError(
            "full_factory_crossing_pair_invalid",
            "Each crossing requires exactly two distinct route labels.",
            details={"field": field},
        )
    label = raw.get("label")
    return {
        "route_labels": labels,
        "width": _positive(raw.get("width"), f"{field}.width"),
        "depth": _positive(raw.get("depth"), f"{field}.depth"),
        "source_unit": _unit(raw.get("source_unit"), f"{field}.source_unit"),
        "label": _text(label, f"{field}.label") if label is not None else None,
    }


def _canonical_asset(raw: Mapping[str, Any], index: int) -> dict[str, Any]:
    field = f"asset_placements[{index}]"
    _closed(
        raw,
        {
            "asset_name",
            "quantity",
            "target_area",
            "orientation_mode",
            "facing_direction",
            "resource_role",
            "access_requirement",
        },
        field,
    )
    quantity = raw.get("quantity")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or not 1 <= quantity <= G4_MAXIMUM_ASSET_QUANTITY
    ):
        raise FacilityFullFactoryError(
            "full_factory_asset_quantity_invalid",
            f"{field}.quantity must be from 1 through {G4_MAXIMUM_ASSET_QUANTITY}.",
        )
    orientation = str(raw.get("orientation_mode") or "").strip()
    role = str(raw.get("resource_role") or "").strip()
    access = str(raw.get("access_requirement") or "").strip()
    if orientation not in G4_ORIENTATION_MODES:
        raise FacilityFullFactoryError(
            "full_factory_asset_orientation_invalid",
            f"{field}.orientation_mode is unsupported.",
        )
    if role not in G4_RESOURCE_ROLES or access not in G4_ACCESS_REQUIREMENTS:
        raise FacilityFullFactoryError(
            "full_factory_asset_semantics_invalid",
            f"{field} has an unsupported resource role or access requirement.",
        )
    facing = raw.get("facing_direction")
    if facing is not None:
        facing = str(facing).strip().lower()
    if orientation == "front_facing":
        if facing not in {"north", "east", "south", "west"}:
            raise FacilityFullFactoryError(
                "full_factory_asset_facing_invalid",
                "Front-facing placement requires north, east, south, or west.",
            )
    elif facing is not None:
        raise FacilityFullFactoryError(
            "full_factory_asset_facing_invalid",
            "facing_direction is valid only with front_facing orientation.",
        )
    return {
        "asset_name": _text(raw.get("asset_name"), f"{field}.asset_name"),
        "quantity": quantity,
        "target_area": _text(raw.get("target_area"), f"{field}.target_area"),
        "orientation_mode": orientation,
        "facing_direction": facing,
        "resource_role": role,
        "access_requirement": access,
    }


def _canonical_seed_cell(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = _mapping(raw, "seed_cell")
    _closed(
        value,
        {
            "target_area",
            "candidate_strategies",
            "selected_strategy",
            "objective",
            "preferred_gap_meters",
            "invert_u",
        },
        "seed_cell",
    )
    strategies = _list(
        value.get("candidate_strategies"),
        "seed_cell.candidate_strategies",
        len(CELL_FEASIBILITY_STRATEGIES),
    )
    strategies = [str(item).strip() for item in strategies]
    if (
        not strategies
        or len(set(strategies)) != len(strategies)
        or any(item not in CELL_FEASIBILITY_STRATEGIES for item in strategies)
    ):
        raise FacilityFullFactoryError(
            "full_factory_cell_strategies_invalid",
            "seed_cell requires one or more distinct registered strategies.",
        )
    selected = value.get("selected_strategy")
    if selected is not None:
        selected = str(selected).strip()
        if selected not in strategies:
            raise FacilityFullFactoryError(
                "full_factory_cell_strategy_invalid",
                "selected_strategy must be one of the candidate strategies.",
            )
    objective = str(value.get("objective") or "").strip()
    if objective not in G5_CELL_OBJECTIVES:
        raise FacilityFullFactoryError(
            "full_factory_cell_objective_invalid",
            "seed_cell objective is unsupported.",
        )
    gap = value.get("preferred_gap_meters")
    if gap is not None:
        gap = _positive(gap, "seed_cell.preferred_gap_meters", allow_zero=True)
        if gap > 20:
            raise FacilityFullFactoryError(
                "full_factory_cell_gap_invalid",
                "seed_cell preferred gap cannot exceed 20 m.",
            )
    if not isinstance(value.get("invert_u"), bool):
        raise FacilityFullFactoryError(
            "full_factory_cell_invert_invalid",
            "seed_cell.invert_u must be boolean.",
        )
    return {
        "target_area": _text(value.get("target_area"), "seed_cell.target_area"),
        "candidate_strategies": strategies,
        "selected_strategy": selected,
        "objective": objective,
        "preferred_gap_meters": gap,
        "invert_u": value["invert_u"],
    }


def _canonical_replication(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    value = _mapping(raw, "cell_replication")
    _closed(
        value,
        {"source_cell", "target_areas", "copy_current_edited_state"},
        "cell_replication",
    )
    targets = _list(
        value.get("target_areas"),
        "cell_replication.target_areas",
        G6_MAXIMUM_TARGET_AREAS,
    )
    targets = [_text(item, "cell_replication.target_areas") for item in targets]
    if not targets or len({item.casefold() for item in targets}) != len(targets):
        raise FacilityFullFactoryError(
            "full_factory_replication_targets_invalid",
            "cell_replication requires distinct target areas.",
        )
    if value.get("copy_current_edited_state") is not False:
        raise FacilityFullFactoryError(
            "full_factory_replication_state_invalid",
            "A new full-factory run can copy only its freshly qualified seed-cell state.",
        )
    return {
        "source_cell": _text(value.get("source_cell"), "cell_replication.source_cell"),
        "target_areas": targets,
        "copy_current_edited_state": False,
    }


def canonicalize_full_factory_request(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one coordinate-free FLI-026 request before any run is created."""

    raw = _mapping(value, "full_factory")
    _closed(
        raw,
        {
            "facility_envelope",
            "departments",
            "circulation",
            "subdivisions",
            "asset_placements",
            "seed_cell",
            "cell_replication",
            "cell_recipes",
            "module_families",
            "execution_mode",
        },
        "full_factory",
    )
    if str(raw.get("execution_mode") or "") != "authorized_draft_run":
        raise FacilityFullFactoryError(
            "full_factory_execution_mode_invalid",
            "Full-factory generation requires authorized_draft_run mode.",
        )
    envelope_raw = _mapping(raw.get("facility_envelope"), "facility_envelope")
    _closed(
        envelope_raw,
        {"width", "depth", "source_unit", "display_name", "grid_size"},
        "facility_envelope",
    )
    envelope_request = {
        "width": envelope_raw.get("width"),
        "depth": envelope_raw.get("depth"),
        "sourceUnit": envelope_raw.get("source_unit"),
        "displayName": envelope_raw.get("display_name"),
    }
    if envelope_raw.get("grid_size") is not None:
        envelope_request["gridSize"] = envelope_raw.get("grid_size")
    try:
        envelope = validate_facility_envelope_request(envelope_request)
    except Exception as exc:
        raise FacilityFullFactoryError(
            "full_factory_envelope_invalid",
            "The full-factory envelope is invalid.",
            details={"cause": str(exc)},
        ) from exc
    departments = _partition(
        _mapping(raw.get("departments"), "departments"),
        field="departments",
        require_parent=False,
    )
    circulation_raw = _mapping(raw.get("circulation"), "circulation")
    _closed(circulation_raw, {"routes", "crossings"}, "circulation")
    routes = [
        _canonical_route(_mapping(item, f"circulation.routes[{index}]"), index)
        for index, item in enumerate(
            _list(
                circulation_raw.get("routes"),
                "circulation.routes",
                FULL_FACTORY_MAX_ROUTES,
            )
        )
    ]
    route_labels = [item["label"] for item in routes]
    if len({item.casefold() for item in route_labels}) != len(route_labels):
        raise FacilityFullFactoryError(
            "full_factory_route_labels_duplicate",
            "Every full-factory route label must be unique.",
        )
    crossings = [
        _canonical_crossing(_mapping(item, f"circulation.crossings[{index}]"), index)
        for index, item in enumerate(
            _list(
                circulation_raw.get("crossings"),
                "circulation.crossings",
                FULL_FACTORY_MAX_CROSSINGS,
            )
        )
    ]
    known_route_labels = {item.casefold() for item in route_labels}
    for crossing in crossings:
        missing = [
            label for label in crossing["route_labels"]
            if label.casefold() not in known_route_labels
        ]
        if missing:
            raise FacilityFullFactoryError(
                "full_factory_crossing_route_unknown",
                "A crossing references a route label not created by this program.",
                details={"labels": missing},
            )

    known_areas = {label.casefold(): label for label in departments["labels"]}
    subdivisions: list[dict[str, Any]] = []
    total_children = 0
    for index, item in enumerate(
        _list(raw.get("subdivisions"), "subdivisions", FULL_FACTORY_MAX_SUBDIVISIONS)
    ):
        subdivision = _partition(
            _mapping(item, f"subdivisions[{index}]"),
            field=f"subdivisions[{index}]",
            require_parent=True,
        )
        parent_key = subdivision["parent_department"].casefold()
        if parent_key not in known_areas:
            raise FacilityFullFactoryError(
                "full_factory_subdivision_parent_unknown",
                "Subdivision parents must be created earlier in the same program.",
                details={"parent": subdivision["parent_department"]},
            )
        duplicates = [
            label for label in subdivision["labels"] if label.casefold() in known_areas
        ]
        if duplicates:
            raise FacilityFullFactoryError(
                "full_factory_area_label_duplicate",
                "Department and child-area labels must be globally unique.",
                details={"labels": duplicates},
            )
        for label in subdivision["labels"]:
            known_areas[label.casefold()] = label
        total_children += subdivision["count"]
        subdivisions.append(subdivision)
    if total_children > 200:
        raise FacilityFullFactoryError(
            "full_factory_program_budget_exceeded",
            "Full-factory child-area count cannot exceed 200.",
        )

    assets = [
        _canonical_asset(_mapping(item, f"asset_placements[{index}]"), index)
        for index, item in enumerate(
            _list(
                raw.get("asset_placements"),
                "asset_placements",
                FULL_FACTORY_MAX_ASSET_REQUESTS,
            )
        )
    ]
    total_assets = sum(item["quantity"] for item in assets)
    if total_assets > FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY:
        raise FacilityFullFactoryError(
            "full_factory_program_budget_exceeded",
            f"Full-factory asset quantity cannot exceed {FULL_FACTORY_MAX_TOTAL_ASSET_QUANTITY}.",
        )
    unknown_targets = [
        item["target_area"]
        for item in assets
        if item["target_area"].casefold() not in known_areas
    ]
    if unknown_targets:
        raise FacilityFullFactoryError(
            "full_factory_asset_target_unknown",
            "Every asset target must be a named area created by this program.",
            details={"targets": sorted(set(unknown_targets))},
        )

    raw_recipes = raw.get("cell_recipes")
    if raw_recipes is not None and raw.get("seed_cell") is not None:
        raise FacilityFullFactoryError(
            "full_factory_cell_contract_ambiguous",
            "Use cell_recipes or the legacy seed_cell alias, not both.",
        )
    if raw_recipes is None:
        legacy_seed = _canonical_seed_cell(raw.get("seed_cell"))
        cell_recipes = [legacy_seed] if legacy_seed is not None else []
    else:
        cell_recipes = [
            _canonical_seed_cell(item)
            for item in _list(
                raw_recipes, "cell_recipes", FULL_FACTORY_MAX_CELL_RECIPES
            )
        ]
    raw_families = raw.get("module_families")
    if raw_families is not None and raw.get("cell_replication") is not None:
        raise FacilityFullFactoryError(
            "full_factory_module_contract_ambiguous",
            "Use module_families or the legacy cell_replication alias, not both.",
        )
    if raw_families is None:
        legacy_replication = _canonical_replication(raw.get("cell_replication"))
        module_families = [legacy_replication] if legacy_replication is not None else []
    else:
        module_families = [
            _canonical_replication(item)
            for item in _list(
                raw_families, "module_families", FULL_FACTORY_MAX_MODULE_FAMILIES
            )
        ]
    recipe_targets = [item["target_area"].casefold() for item in cell_recipes]
    if len(set(recipe_targets)) != len(recipe_targets):
        raise FacilityFullFactoryError(
            "full_factory_cell_target_duplicate",
            "Each cell recipe must have a distinct source target area.",
        )
    for seed in cell_recipes:
        if seed["target_area"].casefold() not in known_areas:
            raise FacilityFullFactoryError(
                "full_factory_cell_target_unknown",
                "The seed cell must target an area created by this program.",
            )
        member_count = sum(
            item["quantity"]
            for item in assets
            if item["target_area"].casefold() == seed["target_area"].casefold()
        )
        if member_count < 2:
            raise FacilityFullFactoryError(
                "full_factory_cell_members_incomplete",
                "The seed-cell target needs at least two assets in this program.",
            )
    occupied_family_targets: set[str] = set()
    recipe_target_set = set(recipe_targets)
    for replication in module_families:
        if replication["source_cell"].casefold() not in recipe_target_set:
            raise FacilityFullFactoryError(
                "full_factory_replication_source_unqualified",
                "Each module family must use a cell recipe created by this program.",
            )
        unknown_replication_targets = [
            target
            for target in replication["target_areas"]
            if target.casefold() not in known_areas
        ]
        if unknown_replication_targets:
            raise FacilityFullFactoryError(
                "full_factory_replication_target_unknown",
                "Every replication target must be a named area created by this program.",
                details={"targets": unknown_replication_targets},
            )
        occupied_targets = {
            item["target_area"].casefold() for item in assets
        } & {target.casefold() for target in replication["target_areas"]}
        if occupied_targets:
            raise FacilityFullFactoryError(
                "full_factory_replication_target_occupied",
                "Replication targets must not receive separate asset placements.",
                details={"targets": sorted(occupied_targets)},
            )
        duplicate_family_targets = occupied_family_targets & {
            target.casefold() for target in replication["target_areas"]
        }
        if duplicate_family_targets:
            raise FacilityFullFactoryError(
                "full_factory_replication_target_conflict",
                "Independent module families cannot target the same area.",
                details={"targets": sorted(duplicate_family_targets)},
            )
        occupied_family_targets.update(
            target.casefold() for target in replication["target_areas"]
        )

    if not any(
        (routes, crossings, subdivisions, assets, cell_recipes, module_families)
    ):
        raise FacilityFullFactoryError(
            "full_factory_scope_incomplete",
            "Use the G1 department tool when no downstream factory content is requested.",
        )
    return {
        "facility_envelope": {
            "width": envelope["source"]["width"],
            "depth": envelope["source"]["depth"],
            "source_unit": envelope["source"]["unit"],
            "display_name": envelope["displayName"],
            "grid_size": envelope_raw.get("grid_size"),
        },
        "departments": departments,
        "circulation": {"routes": routes, "crossings": crossings},
        "subdivisions": subdivisions,
        "asset_placements": assets,
        "cell_recipes": cell_recipes,
        "module_families": module_families,
        "seed_cell": cell_recipes[0] if len(cell_recipes) == 1 else None,
        "cell_replication": module_families[0] if len(module_families) == 1 else None,
        "execution_mode": "authorized_draft_run",
    }


def _resolve_asset(
    catalog: Sequence[Mapping[str, Any]], asset_name: str
) -> dict[str, Any]:
    matches = [
        deepcopy(dict(item))
        for item in catalog
        if isinstance(item, Mapping)
        and str(item.get("displayName") or "").strip().casefold()
        == asset_name.casefold()
    ]
    if len(matches) != 1:
        candidates = sorted(
            str(item.get("displayName") or "")
            for item in catalog
            if isinstance(item, Mapping)
            and asset_name.casefold()
            in str(item.get("displayName") or "").casefold()
        )[:10]
        raise FacilityFullFactoryError(
            "full_factory_asset_name_unresolved",
            "Each full-factory asset name must resolve to one exact catalog definition.",
            details={"assetName": asset_name, "candidates": candidates},
        )
    asset = matches[0]
    asset_id = str(asset.get("assetId") or "").strip()
    revision = str(asset.get("assetDefinitionRevision") or "").strip()
    if _IDENTIFIER.fullmatch(asset_id) is None or not re.fullmatch(
        r"[0-9a-f]{64}", revision
    ):
        raise FacilityFullFactoryError(
            "full_factory_asset_catalog_invalid",
            "The resolved asset lacks an exact stable ID and definition revision.",
            details={"assetName": asset_name},
        )
    return asset


def compile_full_factory_program(
    request: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve exact assets and compile immutable stage inputs for G1-G6."""

    canonical = canonicalize_full_factory_request(request)
    resolved_asset_requests: list[dict[str, Any]] = []
    resolved_intent_assets: list[dict[str, Any]] = []
    for index, item in enumerate(canonical["asset_placements"]):
        asset = _resolve_asset(asset_catalog, item["asset_name"])
        request_id = f"full-factory-asset-{index + 1:03d}"
        resolved_asset_requests.append(
            {
                "request_id": request_id,
                "asset_id": asset["assetId"],
                "asset_definition_revision": asset["assetDefinitionRevision"],
                "quantity": item["quantity"],
                "target_area": item["target_area"],
                "orientation_mode": item["orientation_mode"],
                "facing_direction": item["facing_direction"],
                "resource_role": item["resource_role"],
                "access_requirement": item["access_requirement"],
                "preserve_hierarchy": True,
                "execution_mode": "authorized_draft_run",
            }
        )
        resolved_intent_assets.append(
            {
                "requestId": request_id,
                "assetId": asset["assetId"],
                "assetDefinitionRevision": asset["assetDefinitionRevision"],
                "assetName": asset["displayName"],
                "quantity": item["quantity"],
                "targetArea": item["target_area"],
                "orientationMode": item["orientation_mode"],
                "facingDirection": item["facing_direction"],
                "resourceRole": item["resource_role"],
                "accessRequirement": item["access_requirement"],
            }
        )
    snapshot = build_asset_catalog_snapshot(asset_catalog, resolved_asset_requests)
    route_requests = [
        {
            "action": "create",
            "route_kind": item["route_kind"],
            "width": item["width"],
            "source_unit": item["source_unit"],
            "source_department": item["source_department"],
            "target_department": item["target_department"],
            "via_departments": list(item["via_departments"]),
            "direction": item["direction"],
            "label": item["label"],
            "conflict_scope": None,
            "minimum_separation": None,
            "separation_unit": None,
            "preserve_departments": True,
            "adjust_route_kind": None,
            "obstacle_scope": None,
            "minimum_clearance": None,
            "clearance_unit": None,
            "preserve_route_identity": None,
            "route_id": None,
            "vehicle_profile_id": None,
            "vehicle_profile_revision": None,
            "allow_reverse": None,
            "network_scope": None,
            "crossing_route_ids": [],
            "crossing_width": None,
            "crossing_depth": None,
            "crossing_width_unit": None,
            "crossing_depth_unit": None,
            "preserve_routes": None,
            "execution_mode": "authorized_draft_run",
        }
        for item in canonical["circulation"]["routes"]
    ]
    crossing_requests = [
        {
            "routeLabels": list(item["route_labels"]),
            "crossingWidth": item["width"],
            "crossingDepth": item["depth"],
            "crossingWidthUnit": item["source_unit"],
            "crossingDepthUnit": item["source_unit"],
            "label": item["label"],
        }
        for item in canonical["circulation"]["crossings"]
    ]
    subdivision_requests = [
        {
            "parent_department": item["parent_department"],
            "count": item["count"],
            "labels": list(item["labels"]),
            "proportions": list(item["proportions"]),
            "arrangement": item["arrangement"],
            "orientation": item["orientation"],
            "rows": deepcopy(item["rows"]),
            "preserve_parent": True,
            "execution_mode": "authorized_draft_run",
        }
        for item in canonical["subdivisions"]
    ]
    seed_requests = []
    for seed in canonical["cell_recipes"]:
        seed_requests.append({
            "target_area": seed["target_area"],
            "candidate_strategies": list(seed["candidate_strategies"]),
            "selected_strategy": seed["selected_strategy"],
            "objective": seed["objective"],
            "preferred_gap_meters": seed["preferred_gap_meters"],
            "invert_u": seed["invert_u"],
            "process_sequence_placement_ids": [],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        })
    replication_requests = []
    for replication in canonical["module_families"]:
        replication_requests.append({
            "source_cell": replication["source_cell"],
            "target_areas": list(replication["target_areas"]),
            "copy_current_edited_state": False,
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_source_cell": True,
            "preserve_manual_and_locked": True,
            "execution_mode": "authorized_draft_run",
        })
    stage_inputs: dict[str, dict[str, Any]] = {}
    if route_requests or crossing_requests:
        stage_inputs["primary_circulation"] = {
            "scope": G2_CIRCULATION_SCOPE,
            "requests": route_requests,
            "crossingRequests": crossing_requests,
        }
    if subdivision_requests:
        stage_inputs["department_subdivisions"] = {
            "scope": G3_SUBDIVISION_SCOPE,
            "requests": subdivision_requests,
        }
    if resolved_asset_requests:
        stage_inputs["department_resources"] = {
            "scope": G4_ASSET_PLACEMENT_SCOPE,
            "requests": resolved_asset_requests,
            "assetCatalog": snapshot,
        }
    if seed_requests:
        stage_inputs["seed_cells"] = {
            "scope": G5_CELL_COMPOSITION_SCOPE,
            "requests": seed_requests,
            "request": seed_requests[0] if len(seed_requests) == 1 else None,
            "assetCatalog": snapshot,
        }
    if replication_requests:
        stage_inputs["repeated_modules"] = {
            "scope": G6_CELL_REPLICATION_SCOPE,
            "requests": replication_requests,
            "request": replication_requests[0] if len(replication_requests) == 1 else None,
            "assetCatalog": snapshot,
        }
    resolved_program = {
        "scope": FULL_FACTORY_SCOPE,
        "request": deepcopy(canonical),
        "resolvedAssets": resolved_intent_assets,
        "stageInputs": deepcopy(stage_inputs),
    }
    return {
        "canonicalRequest": canonical,
        "resolvedAssets": resolved_intent_assets,
        "assetCatalogSnapshot": snapshot,
        "stageInputs": stage_inputs,
        "programRevision": facility_knowledge_revision(resolved_program),
    }


def full_factory_tool_spec() -> dict[str, Any]:
    """Return the bounded coordinate-free FLI-026 tool schema."""

    partition_properties = {
        "count": {"type": "integer", "minimum": 1, "maximum": 50},
        "labels": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
        },
        "proportions": {
            "type": ["array", "null"],
            "maxItems": 50,
            "items": {"type": "number", "exclusiveMinimum": 0},
        },
        "arrangement": {
            "type": "string",
            "enum": ["deterministic_grid", "rows", "columns", "row_stack"],
            "description": (
                "Use row_stack whenever rows contains explicit label groupings. "
                "The rows and columns values are generic solver grid modes."
            ),
        },
        "orientation": {
            "type": "string",
            "enum": ["auto", "horizontal", "vertical"],
        },
        "rows": {
            "type": ["array", "null"],
            "description": (
                "Explicit north-to-south row groupings. Supply every label "
                "exactly once and use arrangement row_stack, or null when no "
                "row grouping was requested."
            ),
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "labels": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 50,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "proportion": {"type": ["number", "null"]},
                },
                "required": ["labels", "proportion"],
                "additionalProperties": False,
            },
        },
    }
    partition_required = [
        "count",
        "labels",
        "proportions",
        "arrangement",
        "orientation",
        "rows",
    ]
    subdivision_properties = deepcopy(partition_properties)
    subdivision_properties["parent_department"] = {
        "type": "string",
        "minLength": 1,
    }
    cell_recipe_schema = {
        "type": "object",
        "properties": {
            "target_area": {"type": "string", "minLength": 1},
            "candidate_strategies": {
                "type": "array",
                "minItems": 1,
                "maxItems": len(CELL_FEASIBILITY_STRATEGIES),
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "enum": list(CELL_FEASIBILITY_STRATEGIES),
                },
            },
            "selected_strategy": {
                "type": ["string", "null"],
                "enum": [*CELL_FEASIBILITY_STRATEGIES, None],
            },
            "objective": {
                "type": "string",
                "enum": sorted(G5_CELL_OBJECTIVES),
            },
            "preferred_gap_meters": {
                "type": ["number", "null"],
                "minimum": 0,
                "maximum": 20,
            },
            "invert_u": {"type": "boolean"},
        },
        "required": [
            "target_area",
            "candidate_strategies",
            "selected_strategy",
            "objective",
            "preferred_gap_meters",
            "invert_u",
        ],
        "additionalProperties": False,
    }
    module_family_schema = {
        "type": "object",
        "properties": {
            "source_cell": {"type": "string", "minLength": 1},
            "target_areas": {
                "type": "array",
                "minItems": 1,
                "maxItems": G6_MAXIMUM_TARGET_AREAS,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "copy_current_edited_state": {
                "type": "boolean",
                "const": False,
            },
        },
        "required": [
            "source_cell",
            "target_areas",
            "copy_current_edited_state",
        ],
        "additionalProperties": False,
    }
    return {
        "name": FULL_FACTORY_TOOL,
        "description": (
            "Create one complete unsaved prototype factory draft from a fully "
            "specified high-level intent. Use only when the same request supplies "
            "the facility envelope, macro departments, and downstream routes, "
            "support-area subdivisions, assets, cell intent, or cell replication. "
            "Use exact catalog display names, never asset revisions. Supply no "
            "coordinates, transforms, route points, inferred clearances, safety or "
            "compliance claims, or approval. InspectorPro resolves exact asset "
            "revisions and executes G1-G6 as one durable ten-stage receipt chain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_envelope": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "number", "exclusiveMinimum": 0},
                        "depth": {"type": "number", "exclusiveMinimum": 0},
                        "source_unit": {"type": "string", "enum": sorted(_UNITS)},
                        "display_name": {"type": "string", "minLength": 1},
                        "grid_size": {"type": ["number", "null"]},
                    },
                    "required": [
                        "width",
                        "depth",
                        "source_unit",
                        "display_name",
                        "grid_size",
                    ],
                    "additionalProperties": False,
                },
                "departments": {
                    "type": "object",
                    "properties": deepcopy(partition_properties),
                    "required": partition_required,
                    "additionalProperties": False,
                },
                "circulation": {
                    "type": "object",
                    "properties": {
                        "routes": {
                            "type": "array",
                            "maxItems": FULL_FACTORY_MAX_ROUTES,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "route_kind": {
                                        "type": "string",
                                        "enum": sorted(G2_ROUTE_KINDS),
                                    },
                                    "width": {"type": "number", "exclusiveMinimum": 0},
                                    "source_unit": {
                                        "type": "string",
                                        "enum": sorted(_UNITS),
                                    },
                                    "source_department": {"type": "string", "minLength": 1},
                                    "target_department": {"type": "string", "minLength": 1},
                                    "via_departments": {
                                        "type": "array",
                                        "maxItems": 50,
                                        "items": {"type": "string", "minLength": 1},
                                    },
                                    "direction": {
                                        "type": "string",
                                        "enum": sorted(G2_DIRECTIONS),
                                    },
                                    "label": {"type": "string", "minLength": 1},
                                },
                                "required": [
                                    "route_kind",
                                    "width",
                                    "source_unit",
                                    "source_department",
                                    "target_department",
                                    "via_departments",
                                    "direction",
                                    "label",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "crossings": {
                            "type": "array",
                            "maxItems": FULL_FACTORY_MAX_CROSSINGS,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "route_labels": {
                                        "type": "array",
                                        "minItems": 2,
                                        "maxItems": 2,
                                        "uniqueItems": True,
                                        "items": {"type": "string", "minLength": 1},
                                    },
                                    "width": {"type": "number", "exclusiveMinimum": 0},
                                    "depth": {"type": "number", "exclusiveMinimum": 0},
                                    "source_unit": {
                                        "type": "string",
                                        "enum": sorted(_UNITS),
                                    },
                                    "label": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "route_labels",
                                    "width",
                                    "depth",
                                    "source_unit",
                                    "label",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["routes", "crossings"],
                    "additionalProperties": False,
                },
                "subdivisions": {
                    "type": "array",
                    "maxItems": FULL_FACTORY_MAX_SUBDIVISIONS,
                    "items": {
                        "type": "object",
                        "properties": subdivision_properties,
                        "required": ["parent_department", *partition_required],
                        "additionalProperties": False,
                    },
                },
                "asset_placements": {
                    "type": "array",
                    "maxItems": FULL_FACTORY_MAX_ASSET_REQUESTS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "asset_name": {"type": "string", "minLength": 1},
                            "quantity": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": G4_MAXIMUM_ASSET_QUANTITY,
                            },
                            "target_area": {"type": "string", "minLength": 1},
                            "orientation_mode": {
                                "type": "string",
                                "enum": sorted(G4_ORIENTATION_MODES),
                            },
                            "facing_direction": {
                                "type": ["string", "null"],
                                "enum": ["north", "east", "south", "west", None],
                            },
                            "resource_role": {
                                "type": "string",
                                "enum": sorted(G4_RESOURCE_ROLES),
                            },
                            "access_requirement": {
                                "type": "string",
                                "enum": sorted(G4_ACCESS_REQUIREMENTS),
                            },
                        },
                        "required": [
                            "asset_name",
                            "quantity",
                            "target_area",
                            "orientation_mode",
                            "facing_direction",
                            "resource_role",
                            "access_requirement",
                        ],
                        "additionalProperties": False,
                    },
                },
                "seed_cell": {
                    **deepcopy(cell_recipe_schema),
                    "type": ["object", "null"],
                },
                "cell_recipes": {
                    "type": ["array", "null"],
                    "maxItems": FULL_FACTORY_MAX_CELL_RECIPES,
                    "items": deepcopy(cell_recipe_schema),
                    "description": (
                        "Independent source-cell recipes. Use this array for more "
                        "than one cell family and set seed_cell to null."
                    ),
                },
                "cell_replication": {
                    **deepcopy(module_family_schema),
                    "type": ["object", "null"],
                },
                "module_families": {
                    "type": ["array", "null"],
                    "maxItems": FULL_FACTORY_MAX_MODULE_FAMILIES,
                    "items": deepcopy(module_family_schema),
                    "description": (
                        "Independent replication families. Use this array for more "
                        "than one family and set cell_replication to null."
                    ),
                },
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": [
                "facility_envelope",
                "departments",
                "circulation",
                "subdivisions",
                "asset_placements",
                "seed_cell",
                "cell_replication",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


def is_full_factory_generation_request(message: str) -> bool:
    """Identify multi-gate creation intent so narrower fast paths do not steal it."""

    text = re.sub(r"\s+", " ", str(message or "").strip())
    has_envelope = bool(
        re.search(
            r"\b\d+(?:\.\d+)?\s*(?:m|mm|ft|feet|foot|in|inch|inches|metres?|meters?)\s*"
            r"(?:by|x|×)\s*\d+(?:\.\d+)?\s*"
            r"(?:m|mm|ft|feet|foot|in|inch|inches|metres?|meters?)\b",
            text,
            re.IGNORECASE,
        )
    )
    if not has_envelope:
        return False
    downstream_patterns = (
        r"\b(?:aisle|lane|walkway|route|crosswalk|crossing)\b",
        r"\b(?:divide|subdivide|child areas?|support areas?)\b",
        r"\b(?:place|stage|populate|install)\b[^.!?]{0,100}\b(?:machine|rack|bench|forklift|conveyor|workstation|asset)\b",
        r"\b(?:arrange|compose|build)\b[^.!?]{0,100}\bcell\b",
        r"\b(?:replicate|copy|repeat)\b[^.!?]{0,100}\bcell\b",
    )
    return sum(bool(re.search(pattern, text, re.IGNORECASE)) for pattern in downstream_patterns) >= 2


__all__ = [
    "FULL_FACTORY_SCOPE",
    "FULL_FACTORY_TOOL",
    "FacilityFullFactoryError",
    "canonicalize_full_factory_request",
    "compile_full_factory_program",
    "full_factory_tool_spec",
    "is_full_factory_generation_request",
]
