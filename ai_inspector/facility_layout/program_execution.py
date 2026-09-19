"""Deterministic execution compiler for coordinate-free FacilityProgram artifacts."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations
import logging
import math
import time
from typing import Any, Mapping, Sequence

from .canonical import (
    canonicalize_layout,
    layout_revision,
    trusted_canonical_layout_revision,
)
from .cell_composition import compile_cell_composition_program
from .cell_replication import (
    FacilityCellReplicationError,
    compile_cell_replication_program,
)
from .circulation import (
    G2_CIRCULATION_SCOPE,
    compile_circulation_crossing_operations,
    compile_obstacle_aware_circulation_network_operations,
    compile_primary_circulation_operations,
)
from .diff import build_exact_layout_diff
from .facility_program import canonicalize_facility_program
from .floor_communication import compile_marking_array
from .g1_planner import compile_g1_department_operations, compile_g1_envelope_operations
from .industrial_patterns import compile_industrial_pattern
from .knowledge_foundation import canonical_facility_knowledge_bytes
from .operations import (
    apply_facility_layout_operations,
    apply_prevalidated_facility_layout_operations,
)
from .subdivisions import compile_department_subdivision_program
from .spatial import diagnose_layout, placement_spatial_records


FACILITY_PROGRAM_OPERATION_PLAN_SCHEMA = "facility-program-operation-plan-v1"
FACILITY_PROGRAM_EXECUTION_RESULT_SCHEMA = "facility-program-execution-result-v1"
FACILITY_PROGRAM_WORKFLOW_SCOPE = "reference_quality_facility_program"
FACILITY_PROGRAM_STAGE_INPUT_SCOPE = "facility_program_operation_plan_stage"
FACILITY_PROGRAM_OPERATION_BATCH_LIMIT = 500
FACILITY_PROGRAM_NONFINAL_PLACEMENT_FLOOR = 100

LOGGER = logging.getLogger(__name__)


class FacilityProgramExecutionError(RuntimeError):
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


def facility_program_allowed_contact_pairs(
    layout: Mapping[str, Any],
) -> set[tuple[str, str]]:
    """Return reviewed contact classes that are intentional in RQ programs."""

    guard_runs: dict[tuple[str, str], list[str]] = {}
    allowed: set[tuple[str, str]] = set()
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        placement_id = str(placement.get("placementId") or "")
        metadata = placement.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        if (
            placement.get("assetId")
            == "asset-5987t55-wire-mesh-machine-guard-panel"
            and metadata.get("spacingAuthority") == "panel_abutment_geometry"
        ):
            guard_runs.setdefault(
                (
                    str(metadata.get("targetZoneId") or ""),
                    str(metadata.get("batchId") or ""),
                ),
                [],
            ).append(placement_id)
        relationship = placement.get("snapRelationship")
        if isinstance(relationship, Mapping):
            support_id = str(relationship.get("supportPlacementId") or "")
            if placement_id and support_id:
                allowed.add(tuple(sorted((placement_id, support_id))))
    for placement_ids in guard_runs.values():
        allowed.update(
            tuple(sorted(pair))
            for pair in combinations(sorted(placement_ids), 2)
        )
    return allowed


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _apply(working: Mapping[str, Any], operations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = deepcopy(dict(working))
    for index in range(0, len(operations), FACILITY_PROGRAM_OPERATION_BATCH_LIMIT):
        values = operations[index : index + FACILITY_PROGRAM_OPERATION_BATCH_LIMIT]
        result = apply_prevalidated_facility_layout_operations(
            result,
            values,
            base_revision=trusted_canonical_layout_revision(result),
        )["document"]
    return result


def _route_request(route: Mapping[str, Any]) -> dict[str, Any]:
    source = route.get("source_department") or route.get("source_area")
    target = route.get("target_department") or route.get("target_area")
    via = route.get("via_departments")
    if not isinstance(via, list):
        via = route.get("via_areas") or []
    return {
        "action": "create",
        "route_kind": route["route_kind"],
        "width": route["width"],
        "source_unit": route["source_unit"],
        "source_department": source,
        "target_department": target,
        "via_departments": list(via),
        "direction": route["direction"],
        "label": route["label"],
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


def _zone_index(layout: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping):
            continue
        label = str(zone.get("label") or "").strip().casefold()
        if not label or label in result:
            raise FacilityProgramExecutionError(
                "facility_program_target_area_ambiguous",
                "FacilityProgram target areas must resolve by one unique label.",
                details={"label": label},
            )
        result[label] = zone
    return result


def _catalog_index(
    catalog: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (
            str(item.get("assetId") or ""),
            str(item.get("assetDefinitionRevision") or ""),
        ): item
        for item in catalog
        if isinstance(item, Mapping)
        and item.get("assetId")
        and item.get("assetDefinitionRevision")
    }


def _placement_obstacle_context(
    layout: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a revision-bound obstacle snapshot from exact placed assets."""

    assets = _catalog_index(catalog)
    grouped_bounds: dict[str, list[float]] = {}
    source_revisions: dict[str, str] = {
        "placements": _revision(layout.get("placements", [])),
    }
    for placement in sorted(
        (
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping)
        ),
        key=lambda item: str(item.get("placementId") or ""),
    ):
        placement_id = str(placement.get("placementId") or "")
        asset_id = str(placement.get("assetId") or "")
        asset_revision = str(placement.get("assetDefinitionRevision") or "")
        asset = assets.get((asset_id, asset_revision))
        if asset is None:
            raise FacilityProgramExecutionError(
                "facility_program_route_obstacle_geometry_unavailable",
                "An exact placed-asset revision is unavailable for route reflow.",
                details={"placementId": placement_id, "assetId": asset_id},
            )
        source_revisions[f"asset:{asset_id}"] = asset_revision
        try:
            records = placement_spatial_records(placement, asset)
        except (TypeError, ValueError) as exc:
            raise FacilityProgramExecutionError(
                "facility_program_route_obstacle_geometry_unavailable",
                "A placed asset has no usable footprint for route reflow.",
                details={"placementId": placement_id, "assetId": asset_id},
            ) from exc
        metadata = placement.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        target_zone_id = str(
            metadata.get("targetZoneId")
            or next(iter(placement.get("zoneIds") or []), "")
        )
        key = target_zone_id or placement_id
        for record in records:
            low_x, low_z, high_x, high_z = record.bounds
            bounds = grouped_bounds.setdefault(
                key,
                [float(low_x), float(low_z), float(high_x), float(high_z)],
            )
            bounds[0] = min(bounds[0], float(low_x))
            bounds[1] = min(bounds[1], float(low_z))
            bounds[2] = max(bounds[2], float(high_x))
            bounds[3] = max(bounds[3], float(high_z))
    obstacles = []
    for target_zone_id, bounds in sorted(grouped_bounds.items()):
        low_x, low_z, high_x, high_z = bounds
        obstacles.append(
            {
                "obstacleId": _stable_id(
                    "placement-batch-obstacle",
                    {"targetZoneId": target_zone_id},
                ),
                "obstacleKind": "occupied_area_envelope",
                "boundary": [
                    {"x": round(low_x, 6), "z": round(low_z, 6)},
                    {"x": round(high_x, 6), "z": round(low_z, 6)},
                    {"x": round(high_x, 6), "z": round(high_z, 6)},
                    {"x": round(low_x, 6), "z": round(high_z, 6)},
                ],
                "evidenceStatus": "derived",
                "sourceRef": target_zone_id[:256],
            }
        )
    return {
        "schemaVersion": 1,
        "obstacles": obstacles,
        "sourceRevisions": source_revisions,
    }


def _compile_route_reflow_operations(
    layout: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    route_labels: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reflow authored routes around the completed static placement field."""

    if not route_labels:
        return [], deepcopy(dict(layout))
    started = time.perf_counter()
    working = deepcopy(dict(layout))
    context = _placement_obstacle_context(working, catalog)
    LOGGER.debug(
        "Facility route-reflow obstacle context: %d records in %.3fs",
        len(context["obstacles"]),
        time.perf_counter() - started,
    )
    route_by_label = {
        str(item.get("label") or "").casefold(): item
        for item in working.get("routes", [])
        if isinstance(item, Mapping)
    }
    route_ids = []
    for label in route_labels:
        route = route_by_label.get(str(label).casefold())
        if route is None:
            raise FacilityProgramExecutionError(
                "facility_program_route_reflow_target_missing",
                "A FacilityProgram route is unavailable for deterministic reflow.",
                details={"label": label},
            )
        route_ids.append(str(route.get("routeId") or ""))
    try:
        compiled = compile_obstacle_aware_circulation_network_operations(
            working,
            route_ids,
            context,
        )
    except Exception as exc:
        raise FacilityProgramExecutionError(
            getattr(exc, "code", "facility_program_route_reflow_failed"),
            str(exc),
            details=dict(getattr(exc, "details", {}) or {}),
        ) from exc
    operations = list(compiled["operations"])
    if operations:
        working = _apply(working, operations)
    LOGGER.debug(
        "Facility route reflow complete in %.3fs",
        time.perf_counter() - started,
    )
    return operations, working


def _rectangle(zone: Mapping[str, Any]) -> tuple[float, float, float, float]:
    points = [
        (float(item["x"]), float(item["z"]))
        for item in zone.get("boundary", [])
        if isinstance(item, Mapping)
    ]
    xs = sorted({round(item[0], 9) for item in points})
    zs = sorted({round(item[1], 9) for item in points})
    if len(points) != 4 or len(xs) != 2 or len(zs) != 2:
        raise FacilityProgramExecutionError(
            "facility_program_pattern_zone_unsupported",
            "Resource patterns currently require rectangular target areas.",
        )
    return xs[0], zs[0], xs[1], zs[1]


def _virtual_zone(
    zone: Mapping[str, Any], bounds: tuple[float, float, float, float]
) -> dict[str, Any]:
    low_x, low_z, high_x, high_z = bounds
    result = deepcopy(dict(zone))
    result["boundary"] = [
        {"x": low_x, "z": low_z},
        {"x": high_x, "z": low_z},
        {"x": high_x, "z": high_z},
        {"x": low_x, "z": high_z},
    ]
    return result


def _partition_for_batches(
    zone: Mapping[str, Any], count: int, *, horizontal: bool
) -> list[dict[str, Any]]:
    low_x, low_z, high_x, high_z = _rectangle(zone)
    values = []
    for index in range(count):
        if horizontal:
            left = low_x + (high_x - low_x) * index / count
            right = low_x + (high_x - low_x) * (index + 1) / count
            bounds = (left, low_z, right, high_z)
        else:
            bottom = low_z + (high_z - low_z) * index / count
            top = low_z + (high_z - low_z) * (index + 1) / count
            bounds = (low_x, bottom, high_x, top)
        values.append(_virtual_zone(zone, bounds))
    return values


def _batch_order(resource_batches: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = {str(item["batch_id"]): deepcopy(dict(item)) for item in resource_batches}
    dependencies = {
        batch_id: set(str(item) for item in batch.get("placement_dependencies", []))
        for batch_id, batch in values.items()
    }
    ready = sorted(batch_id for batch_id, refs in dependencies.items() if not refs)
    result = []
    while ready:
        batch_id = ready.pop(0)
        result.append(values[batch_id])
        for other_id in sorted(values):
            if batch_id in dependencies[other_id]:
                dependencies[other_id].remove(batch_id)
                if not dependencies[other_id] and values[other_id] not in result and other_id not in ready:
                    ready.append(other_id)
        ready.sort()
    if len(result) != len(values):
        raise FacilityProgramExecutionError(
            "facility_program_batch_dependency_cycle",
            "Resource-batch dependencies contain a cycle.",
        )
    return result


def _compile_resource_operations(
    layout: Mapping[str, Any],
    resource_batches: Sequence[Mapping[str, Any]],
    catalog: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    zones = _zone_index(layout)
    assets = _catalog_index(catalog)
    ordered = _batch_order(resource_batches)
    by_target: dict[str, list[dict[str, Any]]] = {}
    for batch in ordered:
        by_target.setdefault(str(batch["target_area"]).casefold(), []).append(batch)
    operations = []
    summaries = []
    for target_key in sorted(by_target):
        zone = zones.get(target_key)
        if zone is None:
            raise FacilityProgramExecutionError(
                "facility_program_target_area_unknown",
                "A resource batch targets an area that is not in the draft.",
                details={"targetArea": target_key},
            )
        batches = sorted(
            by_target[target_key],
            key=lambda item: (
                0 if str(item["placement_pattern"]).startswith("guard_run") else 1,
                str(item["batch_id"]),
            ),
        )
        guard_batches = [
            item for item in batches if str(item["placement_pattern"]).startswith("guard_run")
        ]
        if len(guard_batches) > 1:
            raise FacilityProgramExecutionError(
                "facility_program_guard_family_conflict",
                "One target area cannot contain multiple independent guard runs.",
            )
        ordinary = [item for item in batches if item not in guard_batches]
        compiled_by_id: dict[str, dict[str, Any]] = {}
        if guard_batches:
            guard = guard_batches[0]
            identity = guard["exact_catalog_identity"]
            asset = assets.get((identity["asset_id"], identity["asset_definition_revision"]))
            if asset is None:
                raise FacilityProgramExecutionError(
                    "facility_program_asset_revision_unavailable",
                    "A resource batch exact catalog revision is unavailable.",
                )
            compiled_by_id[guard["batch_id"]] = compile_industrial_pattern(
                zone,
                asset,
                batch_id=guard["batch_id"],
                quantity=guard["quantity"],
                pattern_id=guard["placement_pattern"],
                semantic_orientation=guard["semantic_orientation"],
            )
            metrics = compiled_by_id[guard["batch_id"]]["metrics"]
            low_x, low_z, high_x, high_z = _rectangle(zone)
            center_x = (low_x + high_x) / 2.0
            center_z = (low_z + high_z) / 2.0
            inset_x = max(0.0, (high_x - low_x - float(metrics["envelopeWidthMeters"])) / 2.0)
            inset_z = max(0.0, (high_z - low_z - float(metrics["envelopeDepthMeters"])) / 2.0)
            interior_margin = 0.2
            interior = _virtual_zone(
                zone,
                (
                    low_x + inset_x + interior_margin,
                    low_z + inset_z + interior_margin,
                    high_x - inset_x - interior_margin,
                    high_z - inset_z - interior_margin,
                ),
            )
        else:
            interior = deepcopy(dict(zone))

        if ordinary:
            low_x, low_z, high_x, high_z = _rectangle(interior)
            preferred_horizontal = (high_x - low_x) >= (high_z - low_z)
            attempts = [preferred_horizontal, not preferred_horizontal]
            last_error: Exception | None = None
            selected: dict[str, dict[str, Any]] | None = None
            for horizontal in attempts:
                candidate: dict[str, dict[str, Any]] = {}
                virtual_zones = _partition_for_batches(
                    interior, len(ordinary), horizontal=horizontal
                )
                try:
                    for batch, target in zip(ordinary, virtual_zones, strict=True):
                        identity = batch["exact_catalog_identity"]
                        asset = assets.get(
                            (identity["asset_id"], identity["asset_definition_revision"])
                        )
                        if asset is None:
                            raise FacilityProgramExecutionError(
                                "facility_program_asset_revision_unavailable",
                                "A resource batch exact catalog revision is unavailable.",
                                details={"batchId": batch["batch_id"]},
                            )
                        spacing = batch.get("authored_spacing")
                        candidate[batch["batch_id"]] = compile_industrial_pattern(
                            target,
                            asset,
                            batch_id=batch["batch_id"],
                            quantity=batch["quantity"],
                            pattern_id=batch["placement_pattern"],
                            semantic_orientation=batch["semantic_orientation"],
                            authored_spacing_meters=(
                                spacing.get("value") if isinstance(spacing, Mapping) else None
                            ),
                            spacing_evidence_ref=(
                                spacing.get("evidence_ref") if isinstance(spacing, Mapping) else None
                            ),
                        )
                except Exception as exc:
                    last_error = exc
                    continue
                selected = candidate
                break
            if selected is None:
                if isinstance(last_error, FacilityProgramExecutionError):
                    raise last_error
                details = getattr(last_error, "details", {}) if last_error else {}
                raise FacilityProgramExecutionError(
                    "facility_program_resource_set_unplaceable",
                    "The complete resource family does not fit its target area.",
                    details={"targetArea": str(zone.get("label") or ""), **dict(details)},
                ) from last_error
            compiled_by_id.update(selected)

        for batch in batches:
            compiled = compiled_by_id[batch["batch_id"]]
            operations.extend(compiled["operations"])
            summaries.append(
                {
                    "batchId": batch["batch_id"],
                    "targetArea": batch["target_area"],
                    "patternId": batch["placement_pattern"],
                    "requestedQuantity": batch["quantity"],
                    "placedQuantity": compiled["placedQuantity"],
                    "metrics": deepcopy(compiled["metrics"]),
                }
            )
    return operations, summaries


def _qualify_industrial_module_sources(
    layout: Mapping[str, Any],
    module_families: Sequence[Mapping[str, Any]],
    recipe_ids: set[str],
    *,
    program_revision: str,
) -> list[dict[str, Any]]:
    zones = _zone_index(layout)
    operations = []
    qualified: set[str] = set()
    for family in sorted(module_families, key=lambda item: str(item["family_id"])):
        source = str(family["source_recipe_or_cell"])
        if source in recipe_ids:
            continue
        key = source.casefold()
        if key in qualified:
            continue
        zone = zones.get(key)
        if zone is None:
            raise FacilityProgramExecutionError(
                "facility_program_module_source_unknown",
                "A module family source area is not in the compiled draft.",
                details={"familyId": family["family_id"], "sourceArea": source},
            )
        zone_id = str(zone.get("zoneId") or "")
        placement_ids = sorted(
            str(item.get("placementId") or "")
            for item in layout.get("placements", [])
            if isinstance(item, Mapping)
            and zone_id in {str(value) for value in item.get("zoneIds", [])}
            and item.get("placementId")
        )
        if not placement_ids:
            raise FacilityProgramExecutionError(
                "facility_program_module_source_empty",
                "An industrial module source must contain exact placed resources.",
                details={"familyId": family["family_id"], "sourceArea": source},
            )
        extensions = deepcopy(dict(zone.get("extensions") or {}))
        extensions["cellGroup"] = {
            "schemaVersion": 1,
            "groupKind": "manufacturing_cell",
            "membership": "geometric",
            "envelopePadding": 0.0,
            "autoNumber": {
                "seriesId": _stable_id(
                    "series-rq-module",
                    {"programRevision": program_revision, "sourceZoneId": zone_id},
                ),
                "baseName": str(zone.get("label") or "")[:80],
                "prefix": "M",
                "start": 1,
                "padding": 2,
                "sequence": 1,
            },
        }
        provenance = {
            "schemaVersion": 1,
            "command": "industrial_pattern_module_source",
            "generatedBy": "facility_program_operation_plan_v1",
            "programRevision": program_revision,
            "familyId": family["family_id"],
            "authoredStrategy": "deterministic_industrial_pattern_set",
            "seedEntityIds": placement_ids,
            "parameters": {
                "sourceZoneId": zone_id,
                "sourceArea": str(zone.get("label") or ""),
                "placementCount": len(placement_ids),
            },
            "qualification": (
                "This binds an exact deterministic placement set for translation. "
                "It does not establish process, safety, capacity, or compliance equivalence."
            ),
        }
        extensions["layoutProvenance"] = deepcopy(provenance)
        operations.append(
            {
                "op": "edit_zone",
                "zoneId": zone_id,
                "patch": {"extensions": extensions},
                "layoutProvenance": provenance,
                "layoutProvenanceSeedEntityIds": placement_ids,
            }
        )
        qualified.add(key)
    return operations


def _make_batches(
    stages: Sequence[tuple[str, Sequence[Mapping[str, Any]], int]],
    stage_checkpoints: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    previous_batch_id: str | None = None
    for stage_sequence, (stage_id, operations, planned_count) in enumerate(stages, start=1):
        values = [deepcopy(dict(item)) for item in operations]
        chunks = [
            values[index : index + FACILITY_PROGRAM_OPERATION_BATCH_LIMIT]
            for index in range(0, len(values), FACILITY_PROGRAM_OPERATION_BATCH_LIMIT)
        ] or [[]]
        stage_batches = []
        planned_remaining = planned_count
        for batch_sequence, chunk in enumerate(chunks, start=1):
            batch_planned = (
                min(len(chunk), planned_remaining)
                if stage_id == "department_resources"
                else (planned_count if len(chunks) == 1 else min(len(chunk), planned_remaining))
            )
            planned_remaining = max(0, planned_remaining - batch_planned)
            batch_id = _stable_id(
                "facility-program-batch",
                {"stageId": stage_id, "sequence": batch_sequence, "operations": chunk},
            )
            stage_batches.append(
                {
                    "batchId": batch_id,
                    "stageId": stage_id,
                    "sequence": batch_sequence,
                    "operationCount": len(chunk),
                    "plannedInstanceCount": batch_planned,
                    "operationsRevision": _revision(chunk),
                    "operations": chunk,
                    "prerequisiteBatchIds": [previous_batch_id] if previous_batch_id else [],
                }
            )
            previous_batch_id = batch_id
        result.append(
            {
                "stageId": stage_id,
                "sequence": stage_sequence,
                "operationCount": len(values),
                "plannedInstanceCount": planned_count,
                "batchCount": len(stage_batches),
                "batches": stage_batches,
                "expectedCounts": deepcopy(
                    stage_checkpoints[stage_id]["expectedCounts"]
                ),
                "expectedDraftRevision": stage_checkpoints[stage_id][
                    "expectedDraftRevision"
                ],
            }
        )
    resource_stage = next(
        (item for item in result if item["stageId"] == "department_resources"), None
    )
    if resource_stage:
        for batch in resource_stage["batches"][:-1]:
            if batch["plannedInstanceCount"] < FACILITY_PROGRAM_NONFINAL_PLACEMENT_FLOOR:
                raise FacilityProgramExecutionError(
                    "facility_program_placement_batch_too_small",
                    "A non-final placement batch violates the frozen construction floor.",
                )
    return result


def _facility_program_stage_checkpoint(
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "expectedCounts": {
            "zones": len(layout.get("zones", [])),
            "routes": len(layout.get("routes", [])),
            "placements": len(layout.get("placements", [])),
            "floorMarkings": len(layout.get("floorMarkings", [])),
        },
        "expectedDraftRevision": layout_revision(layout),
    }


def compile_facility_program_operation_plan(
    program: Mapping[str, Any],
    base_layout: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile a complete prototype program before mutating the active draft."""

    compile_started = time.perf_counter()
    canonical = canonicalize_facility_program(program)
    LOGGER.debug("Facility Program canonicalized in %.3fs", time.perf_counter() - compile_started)
    if canonical["authority_and_mode"]["mode"] == "reference_reproduction":
        raise FacilityProgramExecutionError(
            "facility_program_reference_adapter_required",
            "Reference reproduction must use the reviewed manifest adapter.",
        )
    if canonical["unresolved_requirements"]:
        raise FacilityProgramExecutionError(
            "facility_program_blocking_findings",
            "The FacilityProgram has unresolved requirements and cannot execute.",
            details={"count": len(canonical["unresolved_requirements"])},
        )
    base = canonicalize_layout(deepcopy(dict(base_layout)))
    working = deepcopy(base)
    compiled_stages: list[tuple[str, list[dict[str, Any]], int]] = []
    stage_checkpoints: dict[str, dict[str, Any]] = {}

    envelope = canonical["facility_envelope"]
    envelope_compiled = compile_g1_envelope_operations(
        working,
        {
            "width": envelope["width"],
            "depth": envelope["depth"],
            "sourceUnit": envelope["source_unit"],
            "displayName": envelope["display_name"],
            **({"gridSize": envelope["grid_size"]} if envelope["grid_size"] is not None else {}),
        },
        replace_existing=any(
            working.get(field)
            for field in ("zones", "routes", "placements", "floorMarkings")
        ),
    )
    working = _apply(working, envelope_compiled["operations"])
    compiled_stages.append(("facility_envelope", envelope_compiled["operations"], 0))
    stage_checkpoints["facility_envelope"] = _facility_program_stage_checkpoint(
        working
    )
    LOGGER.debug("Facility Program envelope complete at %.3fs", time.perf_counter() - compile_started)

    if len(canonical["macro_departments"]) != 1 or "count" not in canonical["macro_departments"][0]:
        raise FacilityProgramExecutionError(
            "facility_program_macro_partition_invalid",
            "Intent-driven programs require one deterministic macro partition request.",
        )
    macro_compiled = compile_g1_department_operations(
        working, canonical["macro_departments"][0]
    )
    working = _apply(working, macro_compiled["operations"])
    compiled_stages.append(
        ("macro_departments", macro_compiled["operations"], macro_compiled["plannedInstanceCount"])
    )
    stage_checkpoints["macro_departments"] = _facility_program_stage_checkpoint(
        working
    )
    LOGGER.debug("Facility Program macros complete at %.3fs", time.perf_counter() - compile_started)

    primary_operations = []
    for route in canonical["route_network"]["primary_routes"]:
        compiled = compile_primary_circulation_operations(working, _route_request(route))
        primary_operations.extend(compiled["operations"])
    if primary_operations:
        working = _apply(working, primary_operations)
    compiled_stages.append(("primary_circulation", primary_operations, len(primary_operations)))
    stage_checkpoints["primary_circulation"] = _facility_program_stage_checkpoint(
        working
    )
    LOGGER.debug("Facility Program primary routes complete at %.3fs", time.perf_counter() - compile_started)

    subdivision_operations = []
    if canonical["area_hierarchy"]:
        if any("parent_department" not in item for item in canonical["area_hierarchy"]):
            raise FacilityProgramExecutionError(
                "facility_program_area_hierarchy_invalid",
                "Intent-driven area hierarchy requires deterministic subdivision groups.",
            )
        compiled = compile_department_subdivision_program(
            working, canonical["area_hierarchy"]
        )
        subdivision_operations = list(compiled["operations"])
        working = _apply(working, subdivision_operations)
    compiled_stages.append(
        ("department_subdivisions", subdivision_operations, len(subdivision_operations))
    )
    stage_checkpoints["department_subdivisions"] = _facility_program_stage_checkpoint(
        working
    )
    LOGGER.debug("Facility Program subdivisions complete at %.3fs", time.perf_counter() - compile_started)

    resource_operations, resource_summaries = _compile_resource_operations(
        working, canonical["resource_batches"], asset_catalog
    )
    working = _apply(working, resource_operations)
    compiled_stages.append(
        ("department_resources", resource_operations, len(resource_operations))
    )
    stage_checkpoints["department_resources"] = _facility_program_stage_checkpoint(
        working
    )
    LOGGER.debug("Facility Program resources complete at %.3fs", time.perf_counter() - compile_started)

    recipe_by_id = {item["recipe_id"]: item for item in canonical["cell_recipes"]}
    seed_operations = _qualify_industrial_module_sources(
        working,
        canonical["module_families"],
        set(recipe_by_id),
        program_revision=_revision(canonical),
    )
    if seed_operations:
        working = _apply(working, seed_operations)
    for recipe in canonical["cell_recipes"]:
        selected = recipe["selected_strategy_or_objective"]
        selected_strategy = selected if selected in recipe["candidate_strategies"] else None
        objective = selected if selected_strategy is None else "smallest_envelope"
        spacing = recipe.get("authored_spacing")
        request = {
            "target_area": recipe["target_area"],
            "candidate_strategies": list(recipe["candidate_strategies"]),
            "selected_strategy": selected_strategy,
            "objective": objective,
            "preferred_gap_meters": (
                spacing.get("value") if isinstance(spacing, Mapping) else None
            ),
            "invert_u": False,
            "process_sequence_placement_ids": [],
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        }
        compiled = compile_cell_composition_program(
            working,
            request,
            asset_catalog,
            defer_post_validation=True,
            include_compiled_document=True,
        )
        seed_operations.extend(compiled["operations"])
        working = compiled.pop("_compiledDocument")
    compiled_stages.append(("seed_cells", seed_operations, len(seed_operations)))
    stage_checkpoints["seed_cells"] = _facility_program_stage_checkpoint(working)
    LOGGER.debug("Facility Program seed cells complete at %.3fs", time.perf_counter() - compile_started)

    module_operations = []
    targeted: set[str] = set()
    for family in canonical["module_families"]:
        overlap = targeted & {item.casefold() for item in family["target_areas"]}
        if overlap:
            raise FacilityProgramExecutionError(
                "facility_program_family_target_conflict",
                "Module families cannot target the same area without an explicit disjoint composition contract.",
                details={"areas": sorted(overlap)},
            )
        targeted.update(item.casefold() for item in family["target_areas"])
        source = recipe_by_id.get(family["source_recipe_or_cell"])
        source_area = source["target_area"] if source else family["source_recipe_or_cell"]
        request = {
            "source_cell": source_area,
            "target_areas": list(family["target_areas"]),
            "copy_current_edited_state": False,
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_source_cell": True,
            "preserve_manual_and_locked": True,
            "execution_mode": "authorized_draft_run",
        }
        try:
            compiled = compile_cell_replication_program(
                working,
                request,
                asset_catalog,
                defer_spatial_validation=True,
                defer_post_validation=True,
                include_compiled_document=True,
            )
        except FacilityCellReplicationError as exc:
            details = deepcopy(exc.details)
            details.update(
                {
                    "familyId": family["family_id"],
                    "sourceArea": source_area,
                    "targetAreas": list(family["target_areas"]),
                }
            )
            raise FacilityProgramExecutionError(
                exc.code,
                str(exc),
                details=details,
            ) from exc
        module_operations.extend(compiled["operations"])
        working = compiled.pop("_compiledDocument")
    compiled_stages.append(("repeated_modules", module_operations, len(module_operations)))
    stage_checkpoints["repeated_modules"] = _facility_program_stage_checkpoint(
        working
    )
    LOGGER.debug("Facility Program repeated modules complete at %.3fs", time.perf_counter() - compile_started)

    floor_operations = []
    pending_floor_operations = []
    for route in canonical["route_network"]["local_routes"]:
        compiled = compile_primary_circulation_operations(working, _route_request(route))
        floor_operations.extend(compiled["operations"])
    if floor_operations:
        working = _apply(working, floor_operations)
    LOGGER.debug("Facility Program local routes complete at %.3fs", time.perf_counter() - compile_started)
    route_labels = [
        str(item["label"])
        for item in (
            *canonical["route_network"]["primary_routes"],
            *canonical["route_network"]["local_routes"],
        )
    ]
    reflow_operations, working = _compile_route_reflow_operations(
        working,
        asset_catalog,
        route_labels,
    )
    floor_operations.extend(reflow_operations)
    LOGGER.debug("Facility Program route reflow complete at %.3fs", time.perf_counter() - compile_started)
    routes_by_label = {
        str(item.get("label") or "").casefold(): item
        for item in working.get("routes", [])
        if isinstance(item, Mapping)
    }
    for item in canonical["floor_communication"]:
        if "anchor_relationship" in item:
            marking_array = compile_marking_array(working, item)
            floor_operations.extend(marking_array["operations"])
            pending_floor_operations.extend(marking_array["operations"])
            continue
        if "route_labels" not in item:
            raise FacilityProgramExecutionError(
                "facility_program_floor_pattern_not_compiled",
                "The floor-communication pattern is not supported by this compiler.",
            )
        route_ids = []
        for label in item["route_labels"]:
            route = routes_by_label.get(str(label).casefold())
            if route is None:
                raise FacilityProgramExecutionError(
                    "facility_program_crossing_route_unknown",
                    "A crossing references a route not present in the compiled network.",
                )
            route_ids.append(str(route.get("routeId") or ""))
        crossing = compile_circulation_crossing_operations(
            working,
            {
                "action": "add_crossing",
                "route_kind": None,
                "width": None,
                "source_unit": None,
                "source_department": None,
                "target_department": None,
                "via_departments": [],
                "direction": None,
                "label": item.get("label"),
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
                "network_scope": "route_network",
                "crossing_route_ids": route_ids,
                "crossing_width": item["width"],
                "crossing_depth": item["depth"],
                "crossing_width_unit": item["source_unit"],
                "crossing_depth_unit": item["source_unit"],
                "preserve_routes": True,
                "execution_mode": "authorized_draft_run",
            },
            defer_post_validation=True,
        )
        floor_operations.extend(crossing["operations"])
        pending_floor_operations.extend(crossing["operations"])
    if pending_floor_operations:
        working = _apply(working, pending_floor_operations)
    LOGGER.debug("Facility Program floor communication complete at %.3fs", time.perf_counter() - compile_started)
    spatial_analysis = diagnose_layout(
        working,
        asset_catalog,
        allowed_contact_pairs=facility_program_allowed_contact_pairs(working),
    )
    blocking_findings = [
        item
        for item in spatial_analysis.get("findings", [])
        if isinstance(item, Mapping) and item.get("severity") == "error"
    ]
    if blocking_findings:
        affected_ids = {ref for finding in blocking_findings for ref in finding.get("subjectRefs", [])}
        affected_batches = sorted({str((item.get("metadata") or {}).get("batchId")) for item in working.get("placements", [])
                                   if item["placementId"] in affected_ids and (item.get("metadata") or {}).get("batchId")})
        raise FacilityProgramExecutionError(
            "facility_program_spatial_validation_failed",
            "The complete FacilityProgram draft failed deterministic spatial validation.",
            details={
                "findingCount": len(blocking_findings),
                "findingCodes": sorted(
                    {str(item.get("code") or "") for item in blocking_findings}
                ),
                "findings": deepcopy(blocking_findings[:8]),
                "findingsTruncated": len(blocking_findings) > 8,
                "affectedBatchIds": affected_batches[:16],
                "repairParameters": ["authoredSpacing", "semanticOrientation", "placementPattern", "department areaShare/row"],
                "repairQualification": "Change only parameters allowed by the retained brief; do not remove equipment or relax checks to force acceptance.",
            },
        )
    LOGGER.debug("Facility Program deterministic validation complete at %.3fs", time.perf_counter() - compile_started)
    compiled_stages.append(("floor_communication", floor_operations, len(floor_operations)))
    compiled_stages.append(("deterministic_validation", [], 0))
    compiled_stages.append(("review_and_save", [], 0))
    final_checkpoint = _facility_program_stage_checkpoint(working)
    stage_checkpoints["floor_communication"] = deepcopy(final_checkpoint)
    stage_checkpoints["deterministic_validation"] = deepcopy(final_checkpoint)
    stage_checkpoints["review_and_save"] = deepcopy(final_checkpoint)

    stages = _make_batches(compiled_stages, stage_checkpoints)
    core = {
        "schemaVersion": FACILITY_PROGRAM_OPERATION_PLAN_SCHEMA,
        "programId": canonical["identity"]["program_id"],
        "programRevision": _revision(canonical),
        "baseLayoutRevision": layout_revision(base),
        "stages": stages,
        "resourceSummaries": resource_summaries,
        "expectedCounts": {
            "zones": len(working.get("zones", [])),
            "routes": len(working.get("routes", [])),
            "placements": len(working.get("placements", [])),
            "floorMarkings": len(working.get("floorMarkings", [])),
        },
        "expectedDraftRevision": layout_revision(working),
        "authority": deepcopy(canonical["authority_and_mode"]),
    }
    core["planRevision"] = _revision(core)
    return core


def validate_facility_program_operation_plan(
    operation_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a persisted operation plan without recompiling model intent."""

    required = {
        "schemaVersion",
        "programId",
        "programRevision",
        "baseLayoutRevision",
        "stages",
        "resourceSummaries",
        "expectedCounts",
        "expectedDraftRevision",
        "authority",
        "planRevision",
    }
    if not isinstance(operation_plan, Mapping) or set(operation_plan) != required:
        raise FacilityProgramExecutionError(
            "facility_program_operation_plan_invalid",
            "FacilityProgram plan fields are invalid.",
        )
    result = deepcopy(dict(operation_plan))
    if result["schemaVersion"] != FACILITY_PROGRAM_OPERATION_PLAN_SCHEMA:
        raise FacilityProgramExecutionError(
            "facility_program_operation_plan_invalid",
            "FacilityProgram plan schema is invalid.",
        )
    unsigned = deepcopy(result)
    observed_revision = unsigned.pop("planRevision")
    if observed_revision != _revision(unsigned):
        raise FacilityProgramExecutionError(
            "facility_program_operation_plan_revision_mismatch",
            "FacilityProgram plan revision does not match its contents.",
        )
    if not isinstance(result["stages"], list) or len(result["stages"]) != 10:
        raise FacilityProgramExecutionError(
            "facility_program_operation_plan_invalid",
            "FacilityProgram plan must contain the complete ten-stage graph.",
        )
    expected_stage_ids = (
        "facility_envelope",
        "macro_departments",
        "primary_circulation",
        "department_subdivisions",
        "department_resources",
        "seed_cells",
        "repeated_modules",
        "floor_communication",
        "deterministic_validation",
        "review_and_save",
    )
    completed_batches: set[str] = set()
    for sequence, (stage, expected_stage_id) in enumerate(
        zip(result["stages"], expected_stage_ids, strict=True), start=1
    ):
        if (
            not isinstance(stage, Mapping)
            or stage.get("stageId") != expected_stage_id
            or stage.get("sequence") != sequence
            or not isinstance(stage.get("batches"), list)
        ):
            raise FacilityProgramExecutionError(
                "facility_program_operation_plan_invalid",
                "FacilityProgram stage ordering is invalid.",
            )
        stage_operation_count = 0
        stage_planned_count = 0
        for batch in stage["batches"]:
            operations = batch.get("operations") if isinstance(batch, Mapping) else None
            prerequisites = (
                batch.get("prerequisiteBatchIds")
                if isinstance(batch, Mapping)
                else None
            )
            if (
                not isinstance(operations, list)
                or len(operations) > FACILITY_PROGRAM_OPERATION_BATCH_LIMIT
                or not isinstance(prerequisites, list)
                or any(item not in completed_batches for item in prerequisites)
                or batch.get("operationCount") != len(operations)
                or batch.get("operationsRevision") != _revision(operations)
            ):
                raise FacilityProgramExecutionError(
                    "facility_program_operation_plan_invalid",
                    "FacilityProgram batch integrity or dependency ordering is invalid.",
                )
            planned = batch.get("plannedInstanceCount")
            if isinstance(planned, bool) or not isinstance(planned, int) or planned < 0:
                raise FacilityProgramExecutionError(
                    "facility_program_operation_plan_invalid",
                    "FacilityProgram batch planned-instance count is invalid.",
                )
            batch_id = str(batch.get("batchId") or "")
            if not batch_id or batch_id in completed_batches:
                raise FacilityProgramExecutionError(
                    "facility_program_operation_plan_invalid",
                    "FacilityProgram batch identity is invalid.",
                )
            completed_batches.add(batch_id)
            stage_operation_count += len(operations)
            stage_planned_count += planned
        if (
            stage.get("operationCount") != stage_operation_count
            or stage.get("plannedInstanceCount") != stage_planned_count
            or stage.get("batchCount") != len(stage["batches"])
        ):
            raise FacilityProgramExecutionError(
                "facility_program_operation_plan_invalid",
                "FacilityProgram stage totals do not match its batches.",
            )
        checkpoint_counts = stage.get("expectedCounts")
        checkpoint_revision = stage.get("expectedDraftRevision")
        if (
            not isinstance(checkpoint_counts, Mapping)
            or set(checkpoint_counts) != {
                "zones",
                "routes",
                "placements",
                "floorMarkings",
            }
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in checkpoint_counts.values()
            )
            or not isinstance(checkpoint_revision, str)
            or len(checkpoint_revision) != 64
        ):
            raise FacilityProgramExecutionError(
                "facility_program_operation_plan_invalid",
                "FacilityProgram stage checkpoint is invalid.",
            )
    counts = result["expectedCounts"]
    if not isinstance(counts, Mapping) or set(counts) != {
        "zones",
        "routes",
        "placements",
        "floorMarkings",
    } or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise FacilityProgramExecutionError(
            "facility_program_operation_plan_invalid",
            "FacilityProgram expected entity counts are invalid.",
        )
    return result


def execute_facility_program_operation_plan(
    base_layout: Mapping[str, Any], operation_plan: Mapping[str, Any]
) -> dict[str, Any]:
    """Execute the immutable plan as one unsaved cumulative draft."""

    operation_plan = validate_facility_program_operation_plan(operation_plan)
    base = canonicalize_layout(deepcopy(dict(base_layout)))
    if layout_revision(base) != operation_plan.get("baseLayoutRevision"):
        raise FacilityProgramExecutionError(
            "facility_program_base_revision_mismatch",
            "FacilityProgram execution base revision changed.",
        )
    draft = deepcopy(base)
    current_revision = layout_revision(base)
    completed: set[str] = set()
    receipts = []
    for stage in operation_plan.get("stages", []):
        for batch in stage.get("batches", []):
            prerequisites = set(batch.get("prerequisiteBatchIds") or [])
            missing = sorted(prerequisites - completed)
            if missing:
                raise FacilityProgramExecutionError(
                    "facility_program_prerequisite_incomplete",
                    "A FacilityProgram batch cannot execute before its prerequisites.",
                    details={"batchId": batch.get("batchId"), "missing": missing},
                )
            before = current_revision
            operations = list(batch.get("operations") or [])
            if operations:
                applied = apply_prevalidated_facility_layout_operations(
                    draft,
                    operations,
                    base_revision=before,
                )
                draft = applied["document"]
                current_revision = trusted_canonical_layout_revision(draft)
            receipts.append(
                {
                    "receiptId": _stable_id(
                        "facility-program-receipt",
                        {
                            "planRevision": operation_plan.get("planRevision"),
                            "batchId": batch.get("batchId"),
                            "base": before,
                            "result": current_revision,
                        },
                    ),
                    "batchId": batch.get("batchId"),
                    "stageId": stage.get("stageId"),
                    "baseDraftRevision": before,
                    "resultDraftRevision": current_revision,
                    "operationCount": batch.get("operationCount"),
                    "plannedInstanceCount": batch.get("plannedInstanceCount"),
                    "prerequisiteBatchIds": sorted(prerequisites),
                    "status": "valid",
                }
            )
            completed.add(str(batch.get("batchId") or ""))
        stage_counts = {
            "zones": len(draft.get("zones", [])),
            "routes": len(draft.get("routes", [])),
            "placements": len(draft.get("placements", [])),
            "floorMarkings": len(draft.get("floorMarkings", [])),
        }
        if (
            stage_counts != stage.get("expectedCounts")
            or current_revision != stage.get("expectedDraftRevision")
        ):
            raise FacilityProgramExecutionError(
                "facility_program_stage_execution_drift",
                "FacilityProgram stage execution differs from its immutable checkpoint.",
                details={
                    "stageId": stage.get("stageId"),
                    "expectedCounts": stage.get("expectedCounts"),
                    "actualCounts": stage_counts,
                    "expectedDraftRevision": stage.get("expectedDraftRevision"),
                    "actualDraftRevision": current_revision,
                },
            )
    counts = {
        "zones": len(draft.get("zones", [])),
        "routes": len(draft.get("routes", [])),
        "placements": len(draft.get("placements", [])),
        "floorMarkings": len(draft.get("floorMarkings", [])),
    }
    final_revision = layout_revision(draft)
    if counts != operation_plan.get("expectedCounts") or final_revision != operation_plan.get("expectedDraftRevision"):
        raise FacilityProgramExecutionError(
            "facility_program_execution_drift",
            "FacilityProgram execution differs from its immutable preflight plan.",
            details={"expectedCounts": operation_plan.get("expectedCounts"), "actualCounts": counts},
        )
    return {
        "schemaVersion": FACILITY_PROGRAM_EXECUTION_RESULT_SCHEMA,
        "status": "complete",
        "saved": False,
        "saveEligibility": "review_required",
        "baseLayoutRevision": layout_revision(base),
        "draftLayoutRevision": final_revision,
        "operationPlanRevision": operation_plan.get("planRevision"),
        "draftLayout": draft,
        "undoLayout": base,
        "receiptChain": receipts,
        "cumulativeDiff": build_exact_layout_diff(base, draft),
        "counts": counts,
        "authority": deepcopy(operation_plan.get("authority") or {}),
    }


def amend_facility_program_resource_batch(
    current_layout: Mapping[str, Any],
    facility_program: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    batch_id: str,
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace one dependency-independent target-area resource set in place.

    This is the bounded RQ2 amendment path. It accepts semantic resource
    fields only, preserves every non-placement collection byte-for-byte, and
    returns an unsaved draft with the exact prior layout as Undo.
    """

    allowed_patch_fields = {
        "quantity",
        "placement_pattern",
        "semantic_orientation",
        "authored_spacing",
    }
    if not isinstance(patch, Mapping) or not patch:
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_invalid",
            "A local resource amendment requires at least one supported field.",
        )
    unknown = sorted(set(patch) - allowed_patch_fields)
    if unknown:
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_invalid",
            "A local resource amendment contains unsupported fields.",
            details={"unknown": unknown},
        )
    requested_batch_id = str(batch_id or "").strip()
    if not requested_batch_id:
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_invalid",
            "A local resource amendment requires an exact batch ID.",
        )

    current = canonicalize_layout(deepcopy(dict(current_layout)))
    canonical = canonicalize_facility_program(facility_program)
    matches = [
        item
        for item in canonical["resource_batches"]
        if item["batch_id"] == requested_batch_id
    ]
    if len(matches) != 1:
        raise FacilityProgramExecutionError(
            "facility_program_resource_batch_unknown",
            "The requested resource batch is not uniquely present in the FacilityProgram.",
            details={"batchId": requested_batch_id},
        )
    original_batch = matches[0]
    target_area = str(original_batch["target_area"])
    target_key = target_area.casefold()
    target_batch_ids = {
        item["batch_id"]
        for item in canonical["resource_batches"]
        if str(item["target_area"]).casefold() == target_key
    }

    external_dependents = sorted(
        item["batch_id"]
        for item in canonical["resource_batches"]
        if item["batch_id"] not in target_batch_ids
        and target_batch_ids & set(item.get("placement_dependencies") or [])
    )
    recipe_dependents = sorted(
        item["recipe_id"]
        for item in canonical["cell_recipes"]
        if target_batch_ids & set(item.get("member_batches") or [])
    )
    module_dependents = sorted(
        item["family_id"]
        for item in canonical["module_families"]
        if (
            str(item.get("source_recipe_or_cell") or "").casefold()
            == target_key
            or target_key
            in {
                str(area).casefold()
                for area in item.get("target_areas") or []
            }
        )
    )
    if external_dependents or recipe_dependents or module_dependents:
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_has_dependents",
            "This resource set feeds another batch or cell/module stage and requires dependency-chain recompilation.",
            details={
                "batchId": requested_batch_id,
                "externalBatchIds": external_dependents,
                "recipeIds": recipe_dependents,
                "moduleFamilyIds": module_dependents,
            },
        )

    candidate_program = deepcopy(canonical)
    candidate_batch = next(
        item
        for item in candidate_program["resource_batches"]
        if item["batch_id"] == requested_batch_id
    )
    candidate_batch.update(deepcopy(dict(patch)))
    candidate_program = canonicalize_facility_program(candidate_program)
    candidate_target_batches = [
        deepcopy(item)
        for item in candidate_program["resource_batches"]
        if str(item["target_area"]).casefold() == target_key
    ]
    for item in candidate_target_batches:
        item["placement_dependencies"] = [
            dependency
            for dependency in item.get("placement_dependencies") or []
            if dependency in target_batch_ids
        ]

    zones = _zone_index(current)
    target_zone = zones.get(target_key)
    if target_zone is None:
        raise FacilityProgramExecutionError(
            "facility_program_target_area_unknown",
            "The local amendment target area is not in the current draft.",
            details={"targetArea": target_area},
        )
    target_zone_id = str(target_zone.get("zoneId") or "")
    removed_placements = [
        item
        for item in current.get("placements", [])
        if isinstance(item, Mapping)
        and target_zone_id in {str(value) for value in item.get("zoneIds", [])}
        and isinstance(item.get("metadata"), Mapping)
        and str(item["metadata"].get("batchId") or "") in target_batch_ids
    ]
    represented_batch_ids = {
        str(item["metadata"].get("batchId") or "")
        for item in removed_placements
    }
    if represented_batch_ids != target_batch_ids:
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_state_mismatch",
            "The current draft does not contain the complete target-area resource set.",
            details={
                "expectedBatchIds": sorted(target_batch_ids),
                "actualBatchIds": sorted(represented_batch_ids),
            },
        )

    unrelated_before = [
        deepcopy(item)
        for item in current.get("placements", [])
        if str(item.get("placementId") or "")
        not in {
            str(placement.get("placementId") or "")
            for placement in removed_placements
        }
    ]
    delete_operations = [
        {
            "op": "delete_placement",
            "placementId": str(item.get("placementId") or ""),
        }
        for item in sorted(
            removed_placements,
            key=lambda value: str(value.get("placementId") or ""),
            reverse=True,
        )
    ]
    stripped = _apply(current, delete_operations)
    replacement_operations, summaries = _compile_resource_operations(
        stripped,
        candidate_target_batches,
        asset_catalog,
    )
    amended = _apply(stripped, replacement_operations)

    for collection in ("zones", "routes", "floorMarkings"):
        if canonical_facility_knowledge_bytes(current.get(collection, [])) != (
            canonical_facility_knowledge_bytes(amended.get(collection, []))
        ):
            raise FacilityProgramExecutionError(
                "facility_program_local_amendment_scope_violation",
                "A local resource amendment changed protected Facility geometry.",
                details={"collection": collection},
            )
    unrelated_after = [
        deepcopy(item)
        for item in amended.get("placements", [])
        if not (
            target_zone_id in {str(value) for value in item.get("zoneIds", [])}
            and isinstance(item.get("metadata"), Mapping)
            and str(item["metadata"].get("batchId") or "") in target_batch_ids
        )
    ]
    if canonical_facility_knowledge_bytes(unrelated_before) != (
        canonical_facility_knowledge_bytes(unrelated_after)
    ):
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_scope_violation",
            "A local resource amendment changed unrelated placements.",
        )

    spatial = diagnose_layout(
        amended,
        asset_catalog,
        allowed_contact_pairs=facility_program_allowed_contact_pairs(amended),
    )
    blocking = [
        item
        for item in spatial.get("findings", [])
        if isinstance(item, Mapping) and item.get("severity") == "error"
    ]
    if blocking:
        raise FacilityProgramExecutionError(
            "facility_program_local_amendment_validation_failed",
            "The local resource amendment failed deterministic spatial validation.",
            details={
                "findingCount": len(blocking),
                "findingCodes": sorted(
                    {str(item.get("code") or "") for item in blocking}
                ),
            },
        )

    current_revision = layout_revision(current)
    amended_revision = layout_revision(amended)
    return {
        "schemaVersion": "facility-program-resource-amendment-v1",
        "status": "complete",
        "saved": False,
        "saveEligibility": "review_required",
        "batchId": requested_batch_id,
        "targetArea": target_area,
        "targetZoneId": target_zone_id,
        "programRevisionBefore": _revision(canonical),
        "programRevisionAfter": _revision(candidate_program),
        "facilityProgram": candidate_program,
        "appliedPatch": {
            field: deepcopy(candidate_batch[field])
            for field in sorted(patch)
        },
        "baseLayoutRevision": current_revision,
        "draftLayoutRevision": amended_revision,
        "removedPlacementCount": len(removed_placements),
        "placedPlacementCount": sum(
            int(item.get("placedQuantity") or 0) for item in summaries
        ),
        "amendedBatchIds": sorted(target_batch_ids),
        "draftLayout": amended,
        "undoLayout": current,
        "cumulativeDiff": build_exact_layout_diff(current, amended),
        "validation": {
            "status": "valid",
            "findingCount": len(spatial.get("findings", [])),
            "blockingFindingCount": 0,
        },
    }


__all__ = [
    "FACILITY_PROGRAM_EXECUTION_RESULT_SCHEMA",
    "FACILITY_PROGRAM_OPERATION_PLAN_SCHEMA",
    "FACILITY_PROGRAM_STAGE_INPUT_SCOPE",
    "FACILITY_PROGRAM_WORKFLOW_SCOPE",
    "FacilityProgramExecutionError",
    "amend_facility_program_resource_batch",
    "compile_facility_program_operation_plan",
    "execute_facility_program_operation_plan",
    "facility_program_allowed_contact_pairs",
    "validate_facility_program_operation_plan",
]
