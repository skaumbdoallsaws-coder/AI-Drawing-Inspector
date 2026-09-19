"""Resolve revision-bound manufacturing evidence for Facility design loops."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Callable, Mapping, Sequence

from .design_base import validate_facility_design_base
from .design_brief import design_revision, validate_facility_design_brief
from .design_routing import normalize_design_asset_definitions
from .design_service import FacilityDesignServiceError


FACILITY_DESIGN_SOURCE_CONTRACT_VERSION = "facility-design-source-v1"
_TRIPS = re.compile(r"^decision-loaded-trips-([0-9]+(?:\.[0-9]+)?)-(shift-[A-Za-z0-9._:-]+)$")

ProcessMapResolver = Callable[[str, str, str], Mapping[str, Any] | None]


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignServiceError(code, message, details=details)


def _index(
    values: Sequence[Mapping[str, Any]], field: str
) -> dict[str, Mapping[str, Any]]:
    return {
        str(item[field]): item
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get(field), str)
    }


def _process_map_document(
    resolved: Mapping[str, Any] | None,
    *,
    product_id: str,
    process_map_id: str,
    process_map_revision: str,
) -> dict[str, Any]:
    if not isinstance(resolved, Mapping):
        _fail(
            "facility_design_process_map_unavailable",
            "The exact authoritative Process Map revision is unavailable.",
            productId=product_id,
            processMapId=process_map_id,
            requestedRevision=process_map_revision,
        )
    document = resolved.get("document") if isinstance(resolved.get("document"), Mapping) else resolved
    if not isinstance(document, Mapping):
        _fail(
            "facility_design_process_map_invalid",
            "The authoritative Process Map resolver returned no document.",
        )
    reported_revisions = {
        str(value)
        for value in (
            resolved.get("revision"),
            document.get("processMapRevision"),
        )
        if isinstance(value, str) and value
    }
    if reported_revisions != {process_map_revision}:
        _fail(
            "facility_design_process_map_revision_mismatch",
            "The authoritative Process Map does not match the requested revision.",
            requestedRevision=process_map_revision,
            reportedRevisions=sorted(reported_revisions),
        )
    reported_map_id = str(
        document.get("processMapId") or document.get("mapId") or ""
    )
    association = (
        document.get("association")
        if isinstance(document.get("association"), Mapping)
        else {}
    )
    reported_product_id = str(
        document.get("productId") or association.get("productId") or ""
    )
    if reported_map_id != process_map_id or reported_product_id != product_id:
        _fail(
            "facility_design_process_map_identity_mismatch",
            "The authoritative Process Map identity does not match the persisted bindings.",
            requestedProductId=product_id,
            requestedProcessMapId=process_map_id,
            reportedProductId=reported_product_id,
            reportedProcessMapId=reported_map_id,
        )
    raw_nodes = document.get("nodes")
    raw_edges = document.get("edges")
    if not isinstance(raw_nodes, list):
        raw_nodes = document.get("canvasNodes")
    if not isinstance(raw_edges, list):
        raw_edges = document.get("canvasEdges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        _fail(
            "facility_design_process_map_invalid",
            "The authoritative Process Map has no executable node and edge graph.",
        )
    nodes = []
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            continue
        node_id = str(raw.get("nodeId") or raw.get("id") or "")
        if not node_id:
            continue
        nodes.append(
            {
                "nodeId": node_id,
                "operationKind": str(raw.get("operationKind") or raw.get("nodeKind") or raw.get("type") or "operation"),
                "label": str(raw.get("label") or raw.get("name") or node_id),
            }
        )
    edges = []
    for raw in raw_edges:
        if not isinstance(raw, Mapping):
            continue
        from_ref = raw.get("from") if isinstance(raw.get("from"), Mapping) else {}
        to_ref = raw.get("to") if isinstance(raw.get("to"), Mapping) else {}
        edge_id = str(raw.get("edgeId") or raw.get("id") or "")
        source = str(raw.get("fromNodeId") or raw.get("sourceNodeId") or from_ref.get("nodeId") or "")
        target = str(raw.get("toNodeId") or raw.get("targetNodeId") or to_ref.get("nodeId") or "")
        if not edge_id or not source or not target:
            continue
        edges.append(
            {
                "edgeId": edge_id,
                "fromNodeId": source,
                "toNodeId": target,
                "edgeKind": str(raw.get("edgeKind") or raw.get("kind") or "precedence"),
            }
        )
    return {
        "productId": product_id,
        "processMapId": process_map_id,
        "processMapRevision": process_map_revision,
        "nodes": nodes,
        "edges": edges,
    }


def _transfer_frequency(brief: Mapping[str, Any]) -> dict[str, Any] | None:
    for decision in brief["semanticBody"].get("decisionRefs", []):
        match = _TRIPS.fullmatch(str(decision))
        if match is None:
            continue
        value = float(match.group(1))
        evidence = next(
            (
                str(item)
                for item in brief["semanticBody"]["objective"].get("evidenceRefs", [])
                if str(item).startswith("evidence-loaded-trips-")
            ),
            None,
        )
        if evidence is None:
            return None
        return {
            "loadedTripsPerShift": value,
            "shiftId": match.group(2),
            "evidenceRef": evidence,
            "evidenceStatus": "authored",
            "reviewStatus": "accepted",
        }
    return None


def build_facility_design_source_bundle(
    *,
    design_base: Mapping[str, Any],
    design_brief: Mapping[str, Any],
    asset_definitions: Sequence[Mapping[str, Any]],
    process_map_resolver: ProcessMapResolver | None = None,
) -> dict[str, Any]:
    """Compile source evidence from the current base, not candidate fixtures."""

    base = validate_facility_design_base(design_base)
    brief = validate_facility_design_brief(design_brief)
    layout = base["document"]
    body = brief["semanticBody"]
    objective = body["objective"]
    if objective["objectiveKind"] != "reduce_loaded_material_travel_v1":
        _fail(
            "facility_design_objective_kind_unsupported",
            "The generic source resolver supports only loaded material travel.",
        )
    binding_index = _index(
        [item for item in layout.get("processBindings", []) if isinstance(item, Mapping)],
        "processBindingId",
    )
    binding_ids = [str(item) for item in objective["processBindingIds"]]
    missing = [item for item in binding_ids if item not in binding_index]
    if missing:
        _fail(
            "facility_design_process_binding_unavailable",
            "The exact persisted process bindings are unavailable.",
            processBindingIds=missing,
        )
    bindings = [binding_index[item] for item in binding_ids]
    flow = [item for item in bindings if item.get("bindingRole") == "material_flow"]
    if len(flow) != 1 or len(flow[0].get("processEdgeIds", [])) != 1 or not flow[0].get("routeIds"):
        _fail(
            "facility_design_material_transfer_ambiguous",
            "The objective does not resolve to one persisted material-flow binding.",
        )
    map_ids = {str(item.get("processMapId") or "") for item in bindings}
    map_revisions = {str(item.get("processMapRevision") or "") for item in bindings}
    products = {str(item.get("productId") or "") for item in bindings}
    if len(map_ids) != 1 or len(map_revisions) != 1 or len(products) != 1:
        _fail(
            "facility_design_process_binding_stale",
            "Selected process bindings do not share one product and Process Map revision.",
        )
    process_map_id = next(iter(map_ids))
    process_map_revision = next(iter(map_revisions))
    product_id = next(iter(products))
    transfer_edge_id = str(flow[0]["processEdgeIds"][0])
    route_ids = [str(item) for item in flow[0]["routeIds"]]
    routes = _index(
        [item for item in layout.get("routes", []) if isinstance(item, Mapping)],
        "routeId",
    )
    missing_routes = [item for item in route_ids if item not in routes]
    if missing_routes:
        _fail(
            "facility_design_material_route_unavailable",
            "A persisted material-flow route is unavailable.",
            routeIds=missing_routes,
        )
    flow_placement_ids = {
        str(item) for item in flow[0].get("placementIds", [])
    }
    resolved_map = (
        process_map_resolver(product_id, process_map_id, process_map_revision)
        if process_map_resolver is not None
        else None
    )
    process_map = _process_map_document(
        resolved_map,
        product_id=product_id,
        process_map_id=process_map_id,
        process_map_revision=process_map_revision,
    )
    transfer_edges = [
        item for item in process_map["edges"] if item["edgeId"] == transfer_edge_id
    ]
    if len(transfer_edges) != 1:
        _fail(
            "facility_design_process_edge_unavailable",
            "The exact Process Map does not contain one matching transfer edge.",
            processEdgeId=transfer_edge_id,
        )
    edge = transfer_edges[0]
    source_candidates = sorted(
        {
            str(placement_id)
            for binding in bindings
            if edge["fromNodeId"] in binding.get("processNodeIds", [])
            for placement_id in binding.get("placementIds", [])
            if str(placement_id) in flow_placement_ids
        }
    )
    target_candidates = sorted(
        {
            str(placement_id)
            for binding in bindings
            if edge["toNodeId"] in binding.get("processNodeIds", [])
            for placement_id in binding.get("placementIds", [])
            if str(placement_id) in flow_placement_ids
        }
    )
    if len(source_candidates) != 1 or len(target_candidates) != 1:
        _fail(
            "facility_design_transfer_endpoint_unavailable",
            "Process bindings do not establish one directed transfer.",
            sourcePlacementIds=source_candidates,
            targetPlacementIds=target_candidates,
            flowPlacementIds=sorted(flow_placement_ids),
        )
    source_id = source_candidates[0]
    target_id = target_candidates[0]
    objective_placement_ids = {
        str(item["entityId"])
        for item in objective["targetRefs"]
        if item.get("entityKind") == "placement"
    }
    if not {source_id, target_id} <= objective_placement_ids:
        _fail(
            "facility_design_transfer_endpoint_unavailable",
            "The objective does not identify both directed transfer placements.",
        )
    first = routes.get(route_ids[0])
    last = routes.get(route_ids[-1])
    source_endpoint = first.get("sourceEndpoint") if isinstance(first, Mapping) else None
    target_endpoint = last.get("targetEndpoint") if isinstance(last, Mapping) else None
    if (
        not isinstance(source_endpoint, Mapping)
        or source_endpoint.get("kind") != "placement_connector"
        or str(source_endpoint.get("placementId") or "") != source_id
        or not str(source_endpoint.get("connectorId") or "")
        or not isinstance(target_endpoint, Mapping)
        or target_endpoint.get("kind") != "placement_connector"
        or str(target_endpoint.get("placementId") or "") != target_id
        or not str(target_endpoint.get("connectorId") or "")
    ):
        _fail(
            "facility_design_route_endpoint_unavailable",
            "Persisted routes do not bind the authoritative transfer endpoints.",
            sourcePlacementId=source_id,
            targetPlacementId=target_id,
        )
    source_connector = str(source_endpoint["connectorId"])
    target_connector = str(target_endpoint["connectorId"])
    placements = _index(
        [item for item in layout.get("placements", []) if isinstance(item, Mapping)],
        "placementId",
    )
    required_asset_keys = {
        (str(item.get("assetId") or ""), str(item.get("assetDefinitionRevision") or ""))
        for item in placements.values()
    }
    normalized_assets = normalize_design_asset_definitions(asset_definitions)
    selected_assets = [
        item
        for item in normalized_assets
        if (item["assetId"], item["assetDefinitionRevision"])
        in required_asset_keys
    ]
    available_asset_keys = {
        (item["assetId"], item["assetDefinitionRevision"])
        for item in selected_assets
    }
    missing_asset_keys = sorted(required_asset_keys - available_asset_keys)
    if missing_asset_keys:
        _fail(
            "facility_design_asset_definition_unavailable",
            "One or more exact asset-definition revisions are unavailable.",
            assetRevisions=missing_asset_keys,
        )
    containing_areas = {
        str(ref["entityId"]): str(change["containingAreaRef"]["entityId"])
        for change in body.get("permittedChanges", [])
        if isinstance(change, Mapping)
        and isinstance(change.get("containingAreaRef"), Mapping)
        for ref in change.get("targetRefs", [])
        if isinstance(ref, Mapping) and ref.get("entityKind") == "placement"
    }
    evidence_projection = {
        "sourceContractVersion": FACILITY_DESIGN_SOURCE_CONTRACT_VERSION,
        "layoutRevision": base["layoutRevision"],
        "briefRevision": brief["briefRevision"],
        "processMapRevision": process_map_revision,
        "routeIds": route_ids,
        "assetRevisions": sorted(required_asset_keys),
    }
    return {
        "sourceContractVersion": FACILITY_DESIGN_SOURCE_CONTRACT_VERSION,
        "processMap": process_map,
        "transfer": {
            "transferId": f"transfer-{transfer_edge_id}",
            "productId": product_id,
            "processMapId": process_map_id,
            "processMapRevision": process_map_revision,
            "processEdgeId": transfer_edge_id,
            "sourcePlacementId": source_id,
            "sourceConnectorId": source_connector,
            "targetPlacementId": target_id,
            "targetConnectorId": target_connector,
            "routeIds": route_ids,
            "processBindingIds": binding_ids,
            "loadedTripsPerShift": _transfer_frequency(brief),
        },
        "validationContextRevision": design_revision(evidence_projection),
        "candidateUpdatedAt": str(layout.get("updatedAt") or base.get("capturedAt")),
        "assetDefinitions": selected_assets,
        "containingAreaIds": containing_areas,
        "candidateAuthority": "deterministic_geometry_compiler",
        "qualification": (
            "Process bindings, current asset geometry, and authored route endpoints only; "
            "no safety, capacity, timing, or compliance authority."
        ),
    }


__all__ = [
    "FACILITY_DESIGN_SOURCE_CONTRACT_VERSION",
    "FacilityDesignServiceError",
    "build_facility_design_source_bundle",
]
