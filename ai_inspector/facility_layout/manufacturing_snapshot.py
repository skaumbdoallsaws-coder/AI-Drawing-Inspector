"""Objective-scoped manufacturing evidence for Facility design evaluation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .design_base import facility_design_base_ref, validate_facility_design_base
from .design_brief import (
    canonical_design_bytes,
    design_revision,
    validate_facility_design_brief,
)


FACILITY_MANUFACTURING_SNAPSHOT_SCHEMA_VERSION = (
    "facility-manufacturing-snapshot-v1"
)
FACILITY_MANUFACTURING_SNAPSHOT_CALCULATION_VERSION = "fdl-snapshot-compiler-v1"


class FacilityManufacturingSnapshotError(ValueError):
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
    raise FacilityManufacturingSnapshotError(code, message, details=details)


def _stable_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must be a stable identifier.")
    if not value[0].isalnum() or any(
        not (character.isalnum() or character in "._:-") for character in value
    ):
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must be a stable identifier.")
    return value


def _revision(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must be a lowercase SHA-256 revision.")
    return value


def _without_revision(value: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    result.pop("snapshotRevision", None)
    return result


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must be a UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FacilityManufacturingSnapshotError(
            "facility_manufacturing_snapshot_invalid",
            f"{field} must be a UTC timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must be a UTC timestamp.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        _fail("facility_manufacturing_snapshot_invalid", f"{label} fields are invalid.")
    return deepcopy(dict(value))


def _id_array(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must be an array of stable IDs.")
    result = [_stable_id(item, field) for item in value]
    if len(result) != len(set(result)):
        _fail("facility_manufacturing_snapshot_invalid", f"{field} must contain unique IDs.")
    return result


def _process_map_record(
    process_map: Mapping[str, Any],
    process_map_id: str,
    process_map_revision: str,
) -> dict[str, Any]:
    if not isinstance(process_map, Mapping):
        _fail("facility_manufacturing_process_map_invalid", "Process Map evidence must be an object.")
    candidate: Mapping[str, Any] = process_map
    maps = process_map.get("processMaps")
    if isinstance(maps, list):
        matches = [
            item
            for item in maps
            if isinstance(item, Mapping) and item.get("processMapId") == process_map_id
        ]
        if len(matches) != 1:
            _fail(
                "facility_manufacturing_process_map_unavailable",
                "The exact Process Map ID was not found once.",
                processMapId=process_map_id,
            )
        candidate = matches[0]
    if candidate.get("processMapId") != process_map_id:
        _fail("facility_manufacturing_process_map_unavailable", "Process Map ID does not match the requested binding.")
    reported_revision = candidate.get("processMapRevision") or candidate.get("revision")
    if reported_revision is not None and reported_revision != process_map_revision:
        _fail(
            "facility_manufacturing_process_map_stale",
            "Process Map revision does not match the persisted Facility binding.",
            expected=process_map_revision,
            actual=reported_revision,
        )
    nodes = candidate.get("nodes")
    edges = candidate.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        _fail("facility_manufacturing_process_map_invalid", "Process Map nodes and edges are required.")
    normalized_nodes = []
    for index, raw in enumerate(nodes):
        if not isinstance(raw, Mapping):
            _fail("facility_manufacturing_process_map_invalid", "Process Map node is not an object.", nodeIndex=index)
        node_id = raw.get("nodeId") or raw.get("processNodeId")
        normalized_nodes.append(
            {
                "nodeId": _stable_id(node_id, f"nodes[{index}].nodeId"),
                "operationKind": str(raw.get("operationKind") or raw.get("nodeKind") or "operation"),
                "label": str(raw.get("label") or raw.get("name") or node_id),
            }
        )
    normalized_edges = []
    for index, raw in enumerate(edges):
        if not isinstance(raw, Mapping):
            _fail("facility_manufacturing_process_map_invalid", "Process Map edge is not an object.", edgeIndex=index)
        edge_id = raw.get("edgeId") or raw.get("processEdgeId")
        source = raw.get("fromNodeId") or raw.get("sourceNodeId")
        target = raw.get("toNodeId") or raw.get("targetNodeId")
        normalized_edges.append(
            {
                "edgeId": _stable_id(edge_id, f"edges[{index}].edgeId"),
                "fromNodeId": _stable_id(source, f"edges[{index}].fromNodeId"),
                "toNodeId": _stable_id(target, f"edges[{index}].toNodeId"),
                "edgeKind": str(raw.get("edgeKind") or "precedence"),
            }
        )
    node_ids = [item["nodeId"] for item in normalized_nodes]
    edge_ids = [item["edgeId"] for item in normalized_edges]
    if len(set(node_ids)) != len(node_ids) or len(set(edge_ids)) != len(edge_ids):
        _fail("facility_manufacturing_process_map_invalid", "Process Map node and edge IDs must be unique.")
    unknown_edge_nodes = sorted(
        {
            endpoint
            for edge in normalized_edges
            for endpoint in (edge["fromNodeId"], edge["toNodeId"])
            if endpoint not in set(node_ids)
        }
    )
    if unknown_edge_nodes:
        _fail("facility_manufacturing_process_map_invalid", "Process Map edge references an unknown node.", nodeIds=unknown_edge_nodes)
    return {
        "processMapId": process_map_id,
        "processMapRevision": process_map_revision,
        "nodes": sorted(normalized_nodes, key=lambda item: item["nodeId"]),
        "edges": sorted(normalized_edges, key=lambda item: item["edgeId"]),
    }


def _transfer_frequency(value: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if value is None:
        return None, [
            {
                "code": "facility_loaded_trip_frequency_unavailable",
                "affectedMetricIds": ["loadedTravelMetersPerShift"],
                "message": "Loaded route distance is measurable, but per-shift travel requires authored loaded trips per shift.",
            }
        ]
    if not isinstance(value, Mapping):
        _fail("facility_transfer_frequency_invalid", "Transfer frequency must be an object.")
    result = deepcopy(dict(value))
    required = {
        "loadedTripsPerShift",
        "shiftId",
        "evidenceRef",
        "evidenceStatus",
        "reviewStatus",
    }
    if set(result) != required:
        _fail("facility_transfer_frequency_invalid", "Transfer-frequency fields are invalid.")
    quantity = result["loadedTripsPerShift"]
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
        _fail("facility_transfer_frequency_invalid", "loadedTripsPerShift must be positive.")
    result["loadedTripsPerShift"] = float(quantity)
    _stable_id(result["shiftId"], "shiftId")
    _stable_id(result["evidenceRef"], "evidenceRef")
    if result["evidenceStatus"] not in {"authored", "controlled"}:
        _fail("facility_transfer_frequency_authority_missing", "Transfer frequency requires authored or controlled evidence.")
    if result["reviewStatus"] != "accepted":
        _fail("facility_transfer_frequency_review_required", "Transfer frequency must be accepted before it affects a metric.")
    return result, []


def build_facility_manufacturing_snapshot(
    *,
    snapshot_id: str,
    design_base: Mapping[str, Any],
    design_brief: Mapping[str, Any],
    process_map: Mapping[str, Any],
    transfer: Mapping[str, Any],
    validation_context_revision: str,
    created_at: str,
) -> dict[str, Any]:
    base = validate_facility_design_base(design_base)
    brief = validate_facility_design_brief(design_brief)
    body = brief["semanticBody"]
    if body["baseStateRef"] != facility_design_base_ref(base):
        _fail("facility_manufacturing_base_mismatch", "Brief does not reference the supplied FacilityDesignBase.")
    if body["objective"]["objectiveKind"] != "reduce_loaded_material_travel_v1":
        _fail("facility_design_objective_kind_unsupported", "Snapshot compiler supports only the first material-travel objective.")
    if not isinstance(transfer, Mapping):
        _fail("facility_material_transfer_invalid", "Material transfer evidence must be an object.")
    transfer = deepcopy(dict(transfer))
    required_transfer_fields = {
        "transferId",
        "productId",
        "processMapId",
        "processMapRevision",
        "processEdgeId",
        "sourcePlacementId",
        "sourceConnectorId",
        "targetPlacementId",
        "targetConnectorId",
        "routeIds",
        "processBindingIds",
        "loadedTripsPerShift",
    }
    if set(transfer) != required_transfer_fields:
        _fail("facility_material_transfer_invalid", "Material-transfer fields are invalid.")
    for field in (
        "transferId",
        "productId",
        "processMapId",
        "processEdgeId",
        "sourcePlacementId",
        "sourceConnectorId",
        "targetPlacementId",
        "targetConnectorId",
    ):
        transfer[field] = _stable_id(transfer[field], field)
    transfer["processMapRevision"] = _revision(transfer["processMapRevision"], "processMapRevision")
    if not isinstance(transfer["routeIds"], list) or not transfer["routeIds"]:
        _fail("facility_material_transfer_invalid", "Material transfer requires at least one route ID.")
    transfer["routeIds"] = [_stable_id(item, "routeIds") for item in transfer["routeIds"]]
    if len(set(transfer["routeIds"])) != len(transfer["routeIds"]):
        _fail("facility_material_transfer_invalid", "Material-transfer route IDs must be unique.")
    if not isinstance(transfer["processBindingIds"], list) or not transfer["processBindingIds"]:
        _fail("facility_material_transfer_invalid", "Material transfer requires process bindings.")
    transfer["processBindingIds"] = sorted(
        _stable_id(item, "processBindingIds") for item in transfer["processBindingIds"]
    )
    if set(transfer["processBindingIds"]) != set(body["objective"]["processBindingIds"]):
        _fail("facility_manufacturing_binding_mismatch", "Transfer bindings do not match the objective.")

    layout = base["document"]
    placement_by_id = {
        item["placementId"]: item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping)
    }
    route_by_id = {
        item["routeId"]: item
        for item in layout.get("routes", [])
        if isinstance(item, Mapping)
    }
    binding_by_id = {
        item["processBindingId"]: item
        for item in layout.get("processBindings", [])
        if isinstance(item, Mapping)
    }
    missing_placements = sorted(
        placement_id
        for placement_id in (transfer["sourcePlacementId"], transfer["targetPlacementId"])
        if placement_id not in placement_by_id
    )
    missing_routes = sorted(
        route_id for route_id in transfer["routeIds"] if route_id not in route_by_id
    )
    missing_bindings = sorted(
        binding_id
        for binding_id in transfer["processBindingIds"]
        if binding_id not in binding_by_id
    )
    if missing_placements or missing_routes or missing_bindings:
        _fail(
            "facility_manufacturing_evidence_unavailable",
            "Objective references are missing from the exact FacilityDesignBase.",
            missingPlacementIds=missing_placements,
            missingRouteIds=missing_routes,
            missingProcessBindingIds=missing_bindings,
        )
    process_record = _process_map_record(
        process_map,
        transfer["processMapId"],
        transfer["processMapRevision"],
    )
    node_ids = {item["nodeId"] for item in process_record["nodes"]}
    edge_ids = {item["edgeId"] for item in process_record["edges"]}
    if transfer["processEdgeId"] not in edge_ids:
        _fail("facility_manufacturing_process_binding_invalid", "Material transfer edge is absent from the Process Map.")
    selected_bindings = []
    for binding_id in transfer["processBindingIds"]:
        binding = deepcopy(binding_by_id[binding_id])
        if (
            binding.get("processMapId") != transfer["processMapId"]
            or binding.get("processMapRevision") != transfer["processMapRevision"]
            or binding.get("productId") != transfer["productId"]
        ):
            _fail("facility_manufacturing_process_binding_stale", "Process binding does not match the exact Process Map and product revisions.", processBindingId=binding_id)
        if any(item not in node_ids for item in binding.get("processNodeIds", [])):
            _fail("facility_manufacturing_process_binding_invalid", "Process binding references an unknown Process Map node.", processBindingId=binding_id)
        if any(item not in edge_ids for item in binding.get("processEdgeIds", [])):
            _fail("facility_manufacturing_process_binding_invalid", "Process binding references an unknown Process Map edge.", processBindingId=binding_id)
        selected_bindings.append(binding)
    bound_placement_ids = {
        item for binding in selected_bindings for item in binding.get("placementIds", [])
    }
    bound_route_ids = {
        item for binding in selected_bindings for item in binding.get("routeIds", [])
    }
    if (
        transfer["sourcePlacementId"] not in bound_placement_ids
        or transfer["targetPlacementId"] not in bound_placement_ids
        or not set(transfer["routeIds"]).issubset(bound_route_ids)
    ):
        _fail("facility_manufacturing_process_binding_incomplete", "Persisted process bindings do not cover both endpoints and the complete route path.")
    frequency, frequency_unknowns = _transfer_frequency(transfer["loadedTripsPerShift"])
    transfer["loadedTripsPerShift"] = frequency
    validation_context_revision = _revision(
        validation_context_revision, "validationContextRevision"
    )
    dependency_nodes = sorted(
        {
            *(f"placement:{item}" for item in bound_placement_ids),
            *(f"route:{item}" for item in transfer["routeIds"]),
            *(f"process_binding:{item}" for item in transfer["processBindingIds"]),
            f"process_edge:{transfer['processEdgeId']}",
        }
    )
    record = {
        "schemaVersion": FACILITY_MANUFACTURING_SNAPSHOT_SCHEMA_VERSION,
        "snapshotId": _stable_id(snapshot_id, "snapshotId"),
        "snapshotRevision": "",
        "compilerVersion": FACILITY_MANUFACTURING_SNAPSHOT_CALCULATION_VERSION,
        "baseRef": facility_design_base_ref(base),
        "briefRef": {
            "briefId": brief["briefId"],
            "briefRevision": brief["briefRevision"],
            "briefSemanticFingerprint": brief["briefSemanticFingerprint"],
        },
        "objective": deepcopy(body["objective"]),
        "processMap": process_record,
        "processBindings": sorted(selected_bindings, key=lambda item: item["processBindingId"]),
        "materialTransfer": transfer,
        "endpoints": {
            "source": {
                "placementId": transfer["sourcePlacementId"],
                "connectorId": transfer["sourceConnectorId"],
            },
            "target": {
                "placementId": transfer["targetPlacementId"],
                "connectorId": transfer["targetConnectorId"],
            },
        },
        "routePath": {
            "routeIds": list(transfer["routeIds"]),
            "validationContextRevision": validation_context_revision,
            "status": "accepted",
        },
        "dependencyGraph": {
            "nodes": dependency_nodes,
            "edges": sorted(
                [
                    {
                        "from": f"process_binding:{binding['processBindingId']}",
                        "to": f"placement:{placement_id}",
                    }
                    for binding in selected_bindings
                    for placement_id in binding.get("placementIds", [])
                ]
                + [
                    {
                        "from": f"process_binding:{binding['processBindingId']}",
                        "to": f"route:{route_id}",
                    }
                    for binding in selected_bindings
                    for route_id in binding.get("routeIds", [])
                ],
                key=lambda item: (item["from"], item["to"]),
            ),
        },
        "unknowns": frequency_unknowns,
        "blockingFindings": [],
        "createdAt": _timestamp(created_at, "createdAt"),
    }
    record["snapshotRevision"] = design_revision(_without_revision(record))
    return validate_facility_manufacturing_snapshot(record)


def validate_facility_manufacturing_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_manufacturing_snapshot_invalid", "FacilityManufacturingSnapshot must be an object.")
    result = deepcopy(dict(value))
    required = {
        "schemaVersion",
        "snapshotId",
        "snapshotRevision",
        "compilerVersion",
        "baseRef",
        "briefRef",
        "objective",
        "processMap",
        "processBindings",
        "materialTransfer",
        "endpoints",
        "routePath",
        "dependencyGraph",
        "unknowns",
        "blockingFindings",
        "createdAt",
    }
    if set(result) != required:
        _fail("facility_manufacturing_snapshot_invalid", "FacilityManufacturingSnapshot fields are invalid.")
    if result["schemaVersion"] != FACILITY_MANUFACTURING_SNAPSHOT_SCHEMA_VERSION:
        _fail("facility_manufacturing_snapshot_version_unsupported", "FacilityManufacturingSnapshot version is unsupported.")
    _stable_id(result["snapshotId"], "snapshotId")
    _revision(result["snapshotRevision"], "snapshotRevision")
    if result["compilerVersion"] != FACILITY_MANUFACTURING_SNAPSHOT_CALCULATION_VERSION:
        _fail("facility_manufacturing_snapshot_version_unsupported", "Snapshot compiler version is unsupported.")
    base_ref = _closed(
        result["baseRef"],
        {"baseId", "baseRevision", "baseKind", "layoutId", "layoutRevision"},
        "baseRef",
    )
    for field in ("baseId", "baseKind", "layoutId"):
        _stable_id(base_ref[field], f"baseRef.{field}")
    _revision(base_ref["baseRevision"], "baseRef.baseRevision")
    _revision(base_ref["layoutRevision"], "baseRef.layoutRevision")
    brief_ref = _closed(
        result["briefRef"],
        {"briefId", "briefRevision", "briefSemanticFingerprint"},
        "briefRef",
    )
    _stable_id(brief_ref["briefId"], "briefRef.briefId")
    _revision(brief_ref["briefRevision"], "briefRef.briefRevision")
    _revision(
        brief_ref["briefSemanticFingerprint"],
        "briefRef.briefSemanticFingerprint",
    )
    objective = _closed(
        result["objective"],
        {
            "objectiveId",
            "objectiveKind",
            "targetRefs",
            "processBindingIds",
            "requestedMetricIds",
            "minimumImprovement",
            "evidenceRefs",
        },
        "objective",
    )
    _stable_id(objective["objectiveId"], "objective.objectiveId")
    if objective["objectiveKind"] != "reduce_loaded_material_travel_v1":
        _fail("facility_design_objective_kind_unsupported", "Snapshot objective kind is unsupported.")
    _id_array(objective["processBindingIds"], "objective.processBindingIds", allow_empty=False)
    _id_array(objective["requestedMetricIds"], "objective.requestedMetricIds", allow_empty=False)
    _id_array(objective["evidenceRefs"], "objective.evidenceRefs")
    if not isinstance(objective["targetRefs"], list) or not objective["targetRefs"]:
        _fail("facility_manufacturing_snapshot_invalid", "objective.targetRefs must be non-empty.")
    for target in objective["targetRefs"]:
        target = _closed(
            target,
            {"entityKind", "entityId", "sourceRevision"},
            "objective.targetRef",
        )
        _stable_id(target["entityKind"], "objective.targetRef.entityKind")
        _stable_id(target["entityId"], "objective.targetRef.entityId")
        _revision(target["sourceRevision"], "objective.targetRef.sourceRevision")

    process_map = _closed(
        result["processMap"],
        {"processMapId", "processMapRevision", "nodes", "edges"},
        "processMap",
    )
    _stable_id(process_map["processMapId"], "processMap.processMapId")
    _revision(process_map["processMapRevision"], "processMap.processMapRevision")
    if not isinstance(process_map["nodes"], list) or not isinstance(process_map["edges"], list):
        _fail("facility_manufacturing_snapshot_invalid", "Process Map nodes and edges must be arrays.")
    node_ids = set()
    for node in process_map["nodes"]:
        node = _closed(node, {"nodeId", "operationKind", "label"}, "processMap.node")
        node_ids.add(_stable_id(node["nodeId"], "processMap.node.nodeId"))
        if not isinstance(node["operationKind"], str) or not isinstance(node["label"], str):
            _fail("facility_manufacturing_snapshot_invalid", "Process Map node text is invalid.")
    edge_ids = set()
    for edge in process_map["edges"]:
        edge = _closed(
            edge,
            {"edgeId", "fromNodeId", "toNodeId", "edgeKind"},
            "processMap.edge",
        )
        edge_ids.add(_stable_id(edge["edgeId"], "processMap.edge.edgeId"))
        if edge["fromNodeId"] not in node_ids or edge["toNodeId"] not in node_ids:
            _fail("facility_manufacturing_snapshot_invalid", "Process Map edge endpoint is unknown.")
    if len(node_ids) != len(process_map["nodes"]) or len(edge_ids) != len(process_map["edges"]):
        _fail("facility_manufacturing_snapshot_invalid", "Process Map IDs must be unique.")

    binding_fields = {
        "processBindingId",
        "productId",
        "processMapId",
        "processMapRevision",
        "processNodeIds",
        "processEdgeIds",
        "placementIds",
        "routeIds",
        "bindingRole",
    }
    if not isinstance(result["processBindings"], list) or not result["processBindings"]:
        _fail("facility_manufacturing_snapshot_invalid", "Snapshot processBindings must be non-empty.")
    binding_ids = set()
    for binding in result["processBindings"]:
        binding = _closed(binding, binding_fields, "processBinding")
        binding_ids.add(_stable_id(binding["processBindingId"], "processBinding.processBindingId"))
        _stable_id(binding["productId"], "processBinding.productId")
        if binding["processMapId"] != process_map["processMapId"]:
            _fail("facility_manufacturing_snapshot_invalid", "Process binding map ID is inconsistent.")
        if binding["processMapRevision"] != process_map["processMapRevision"]:
            _fail("facility_manufacturing_snapshot_invalid", "Process binding map revision is inconsistent.")
        if not set(_id_array(binding["processNodeIds"], "processBinding.processNodeIds")).issubset(node_ids):
            _fail("facility_manufacturing_snapshot_invalid", "Process binding node is unknown.")
        if not set(_id_array(binding["processEdgeIds"], "processBinding.processEdgeIds")).issubset(edge_ids):
            _fail("facility_manufacturing_snapshot_invalid", "Process binding edge is unknown.")
        _id_array(binding["placementIds"], "processBinding.placementIds")
        _id_array(binding["routeIds"], "processBinding.routeIds")
        _stable_id(binding["bindingRole"], "processBinding.bindingRole")
    if len(binding_ids) != len(result["processBindings"]):
        _fail("facility_manufacturing_snapshot_invalid", "Process binding IDs must be unique.")

    transfer_fields = {
        "transferId", "productId", "processMapId", "processMapRevision",
        "processEdgeId", "sourcePlacementId", "sourceConnectorId",
        "targetPlacementId", "targetConnectorId", "routeIds",
        "processBindingIds", "loadedTripsPerShift",
    }
    transfer = _closed(result["materialTransfer"], transfer_fields, "materialTransfer")
    for field in (
        "transferId", "productId", "processMapId", "processEdgeId",
        "sourcePlacementId", "sourceConnectorId", "targetPlacementId",
        "targetConnectorId",
    ):
        _stable_id(transfer[field], f"materialTransfer.{field}")
    _revision(transfer["processMapRevision"], "materialTransfer.processMapRevision")
    route_ids = _id_array(transfer["routeIds"], "materialTransfer.routeIds", allow_empty=False)
    transfer_binding_ids = _id_array(
        transfer["processBindingIds"], "materialTransfer.processBindingIds", allow_empty=False
    )
    if not set(transfer_binding_ids).issubset(binding_ids):
        _fail("facility_manufacturing_snapshot_invalid", "Material transfer binding is unknown.")
    if transfer["processEdgeId"] not in edge_ids:
        _fail("facility_manufacturing_snapshot_invalid", "Material transfer edge is unknown.")
    if transfer["loadedTripsPerShift"] is not None:
        _transfer_frequency(transfer["loadedTripsPerShift"])

    endpoints = _closed(result["endpoints"], {"source", "target"}, "endpoints")
    for name in ("source", "target"):
        endpoint = _closed(endpoints[name], {"placementId", "connectorId"}, f"endpoints.{name}")
        _stable_id(endpoint["placementId"], f"endpoints.{name}.placementId")
        _stable_id(endpoint["connectorId"], f"endpoints.{name}.connectorId")
    route_path = _closed(
        result["routePath"],
        {"routeIds", "validationContextRevision", "status"},
        "routePath",
    )
    if _id_array(route_path["routeIds"], "routePath.routeIds", allow_empty=False) != route_ids:
        _fail("facility_manufacturing_snapshot_invalid", "Route path differs from material transfer evidence.")
    _revision(route_path["validationContextRevision"], "routePath.validationContextRevision")
    if route_path["status"] != "accepted":
        _fail("facility_manufacturing_snapshot_invalid", "Only accepted route paths are measurable.")

    graph = _closed(result["dependencyGraph"], {"nodes", "edges"}, "dependencyGraph")
    graph_nodes = _id_array(graph["nodes"], "dependencyGraph.nodes")
    if not isinstance(graph["edges"], list):
        _fail("facility_manufacturing_snapshot_invalid", "Dependency graph edges must be an array.")
    for edge in graph["edges"]:
        edge = _closed(edge, {"from", "to"}, "dependencyGraph.edge")
        if edge["from"] not in graph_nodes or edge["to"] not in graph_nodes:
            _fail("facility_manufacturing_snapshot_invalid", "Dependency graph edge endpoint is unknown.")
    if not isinstance(result["unknowns"], list) or not isinstance(result["blockingFindings"], list):
        _fail("facility_manufacturing_snapshot_invalid", "Snapshot findings must be arrays.")
    result["createdAt"] = _timestamp(result["createdAt"], "createdAt")
    expected = design_revision(_without_revision(result))
    if result["snapshotRevision"] != expected:
        _fail("facility_manufacturing_snapshot_revision_mismatch", "Snapshot revision does not match its immutable bytes.")
    canonical_design_bytes(result)
    return result


def canonical_facility_manufacturing_snapshot_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_design_bytes(validate_facility_manufacturing_snapshot(value))


__all__ = [
    "FACILITY_MANUFACTURING_SNAPSHOT_CALCULATION_VERSION",
    "FACILITY_MANUFACTURING_SNAPSHOT_SCHEMA_VERSION",
    "FacilityManufacturingSnapshotError",
    "build_facility_manufacturing_snapshot",
    "canonical_facility_manufacturing_snapshot_bytes",
    "validate_facility_manufacturing_snapshot",
]
