"""Trusted demo-plan metadata compiler for the Process Map.

The model selects a product-structure scope. This module loads the app-owned
plan, resolves stable map targets, and emits ordinary Builder operations. It
never writes an asset and never accepts requirement text from the browser.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .repository import canonical_process_map_bytes


DEMO_METADATA_TOOL = "propose_process_map_demo_metadata"
DEMO_METADATA_PLAN_FILENAME = "front-wheel-process-demo.json"
DEMO_METADATA_FILL_MODES = frozenset({"fill_missing"})


class ProcessMapDemoMetadataError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise ProcessMapDemoMetadataError(code, message)


def demo_metadata_tool_spec() -> Dict[str, Any]:
    return {
        "name": DEMO_METADATA_TOOL,
        "description": (
            "Create one reviewable proposal that fills missing card and route "
            "requirements from InspectorPro's trusted illustrative Front Wheel "
            "process plan. The tool never applies the proposal automatically."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scope_occurrence_id"],
            "properties": {
                "scope_occurrence_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "description": "Trusted native occurrence ID for the requested assembly scope.",
                },
                "fill_mode": {
                    "type": "string",
                    "enum": ["fill_missing"],
                    "default": "fill_missing",
                },
            },
        },
    }


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _stable_reference_id(plan_id: str, category: str, source_id: str) -> str:
    value = f"{plan_id}|{category}|{source_id}".encode("utf-8")
    return "pmr-demo-" + hashlib.sha256(value).hexdigest()[:20]


def _load_plan(training_root: Path, product_id: str) -> Tuple[Dict[str, Any], str]:
    root = Path(training_root).resolve()
    path = (
        root
        / product_id
        / "process_knowledge"
        / DEMO_METADATA_PLAN_FILENAME
    ).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        _fail("invalid_demo_plan_path", "The demo-plan path is outside the training root.")
    if not path.is_file():
        _fail(
            "demo_plan_not_found",
            f"No trusted process-plan demo is available for product '{product_id}'.",
        )
    try:
        raw = path.read_bytes()
        plan = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("demo_plan_invalid", f"The trusted demo plan could not be loaded: {exc}")
    if not isinstance(plan, dict):
        _fail("demo_plan_invalid", "The trusted demo plan must be a JSON object.")
    required = {
        "processId": str,
        "revision": str,
        "scope": dict,
        "resources": list,
        "nodes": list,
        "routes": list,
        "disclaimer": str,
    }
    for field, expected in required.items():
        if not isinstance(plan.get(field), expected):
            _fail("demo_plan_invalid", f"The trusted demo plan has an invalid {field} field.")
    if plan.get("demoData") is not True:
        _fail("demo_plan_invalid", "This importer accepts illustrative demo data only.")
    return plan, hashlib.sha256(canonical_process_map_bytes(plan)).hexdigest()


def _occurrence_index(product_structure: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(item["occurrenceId"]): item
        for item in product_structure.get("occurrences", [])
        if isinstance(item, dict) and item.get("occurrenceId")
    }


def _scope_occurrence_ids(
    occurrences: Mapping[str, Mapping[str, Any]], scope_id: str
) -> set[str]:
    if scope_id not in occurrences:
        _fail("demo_scope_not_found", f"Occurrence '{scope_id}' was not found.")
    result = {scope_id}
    changed = True
    while changed:
        changed = False
        for occurrence_id, item in occurrences.items():
            if occurrence_id in result:
                continue
            if str(item.get("parentOccurrenceId") or "") in result:
                result.add(occurrence_id)
                changed = True
    return result


def _logical_connections(process_map: Mapping[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for edge in process_map.get("canvasEdges", []):
        if not isinstance(edge, dict) or not edge.get("edgeId"):
            continue
        logical_id = str(edge.get("logicalConnectionId") or edge["edgeId"])
        groups.setdefault(logical_id, []).append(edge)
    result: List[Dict[str, Any]] = []
    for logical_id, edges in sorted(groups.items()):
        from_ids = {
            str(edge.get("from", {}).get("nodeId"))
            for edge in edges
            if isinstance(edge.get("from"), dict) and edge["from"].get("nodeId")
        }
        to_ids = {
            str(edge.get("to", {}).get("nodeId"))
            for edge in edges
            if isinstance(edge.get("to"), dict) and edge["to"].get("nodeId")
        }
        sources = sorted(from_ids - to_ids)
        targets = sorted(to_ids - from_ids)
        if len(sources) != 1 or len(targets) != 1:
            continue
        ordered = sorted(edges, key=lambda item: str(item.get("edgeId") or ""))
        result.append(
            {
                "logicalConnectionId": logical_id,
                "sourceNodeId": sources[0],
                "targetNodeId": targets[0],
                "edgeId": str(ordered[0]["edgeId"]),
                "edges": ordered,
            }
        )
    return result


def _attached_references(
    process_map: Mapping[str, Any], records: Iterable[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    ids = {
        str(reference_id)
        for record in records
        for reference_id in (
            record.get("referenceIds", [])
            if isinstance(record.get("referenceIds"), list)
            else []
        )
    }
    return [
        item
        for item in process_map.get("referenceCatalog", [])
        if isinstance(item, dict) and str(item.get("referenceId") or "") in ids
    ]


def _reference_identity(reference: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(
        _normalized_text(reference.get(field))
        for field in ("kind", "name", "identifier", "revision", "clause")
    )


def _has_existing_reference(
    attached: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
    *,
    preserve_authored_requirement: bool,
) -> Tuple[bool, bool]:
    source_requirement_id = str(candidate.get("sourceRequirementId") or "")
    source_resource_id = str(candidate.get("sourceResourceId") or "")
    for item in attached:
        if source_requirement_id and str(item.get("sourceRequirementId") or "") == source_requirement_id:
            return True, False
        if source_resource_id and str(item.get("sourceResourceId") or "") == source_resource_id:
            return True, False
        if _reference_identity(item) == _reference_identity(candidate):
            return True, False
        if preserve_authored_requirement and candidate.get("kind") == "requirement":
            same_requirement = all(
                _normalized_text(item.get(field)) == _normalized_text(candidate.get(field))
                for field in ("identifier", "revision", "clause")
            )
            if same_requirement and item.get("demoData") is not True:
                return True, True
    return False, False


def _resource_reference(
    resource: Mapping[str, Any], provenance: Mapping[str, Any]
) -> Dict[str, Any]:
    source_type = str(resource.get("type") or "").strip().casefold()
    kind = "machine" if source_type in {"machine", "equipment"} else "tool"
    resource_id = str(resource.get("id") or "").strip()
    name = str(resource.get("name") or "").strip()
    if not resource_id or not name or source_type not in {
        "machine", "equipment", "tool", "inspectiontool"
    }:
        _fail("demo_plan_invalid", "A demo resource has an unsupported type, id, or name.")
    return {
        "referenceId": _stable_reference_id(
            str(provenance["sourcePlanId"]), "resource", resource_id
        ),
        "kind": kind,
        "name": name,
        "knowledgeStatus": "illustrative",
        "demoData": True,
        "sourceResourceId": resource_id,
        **deepcopy(dict(provenance)),
    }


def _requirement_reference(
    requirement: Mapping[str, Any],
    target_label: str,
    source_requirement_id: str,
    provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    standard_id = str(requirement.get("standardId") or "").strip()
    revision = str(requirement.get("revision") or "").strip()
    section = str(requirement.get("section") or "").strip()
    notes = str(requirement.get("notes") or "").strip()
    if not standard_id or not revision or not section or not notes:
        _fail("demo_plan_invalid", "A demo requirement is missing its source fields.")
    name = f"{target_label}: {standard_id} {section}"[:160].strip()
    return {
        "referenceId": _stable_reference_id(
            str(provenance["sourcePlanId"]), "requirement", source_requirement_id
        ),
        "kind": "requirement",
        "name": name,
        "identifier": standard_id,
        "revision": revision,
        "clause": section,
        "details": notes,
        "knowledgeStatus": "illustrative",
        "demoData": True,
        "sourceRequirementId": source_requirement_id,
        **deepcopy(dict(provenance)),
    }


def _add_reference_operations(
    operations: List[Dict[str, Any]],
    process_map: Mapping[str, Any],
    resources: Mapping[str, Mapping[str, Any]],
    requirements: Any,
    *,
    target_type: str,
    target_id: str,
    target_records: Sequence[Mapping[str, Any]],
    target_label: str,
    source_target_id: str,
    provenance: Mapping[str, Any],
) -> Tuple[int, int]:
    if requirements is None:
        return 0, 0
    if not isinstance(requirements, list):
        _fail("demo_plan_invalid", f"Requirements for '{source_target_id}' must be an array.")
    attached = _attached_references(process_map, target_records)
    requirement_count = 0
    preserved_authored = 0
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            _fail("demo_plan_invalid", f"Requirement {index} for '{source_target_id}' is invalid.")
        resource_id = str(requirement.get("resourceId") or "").strip()
        if resource_id:
            resource = resources.get(resource_id)
            if resource is None:
                _fail("demo_plan_invalid", f"Requirement references unknown resource '{resource_id}'.")
            resource_reference = _resource_reference(resource, provenance)
            exists, _ = _has_existing_reference(
                attached,
                resource_reference,
                preserve_authored_requirement=False,
            )
            if not exists:
                operations.append(
                    {
                        "op": "attach_reference",
                        "targetType": target_type,
                        "targetId": target_id,
                        "reference": resource_reference,
                    }
                )
                attached.append(resource_reference)
        source_requirement_id = f"{source_target_id}:requirement:{index + 1}"
        candidate = _requirement_reference(
            requirement,
            target_label,
            source_requirement_id,
            provenance,
        )
        exists, authored = _has_existing_reference(
            attached,
            candidate,
            preserve_authored_requirement=True,
        )
        if authored:
            preserved_authored += 1
        if exists:
            continue
        operations.append(
            {
                "op": "attach_reference",
                "targetType": target_type,
                "targetId": target_id,
                "reference": candidate,
            }
        )
        attached.append(candidate)
        requirement_count += 1
    return requirement_count, preserved_authored


def compile_demo_metadata_operations(
    training_root: Path,
    product_id: str,
    process_map: Mapping[str, Any],
    product_structure: Mapping[str, Any],
    *,
    scope_occurrence_id: str,
    fill_mode: str = "fill_missing",
    populated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile one trusted demo plan into exact, non-writing Builder operations."""

    if fill_mode not in DEMO_METADATA_FILL_MODES:
        _fail("unsupported_demo_fill_mode", f"Unsupported fill mode '{fill_mode}'.")
    scope_id = str(scope_occurrence_id or "").strip()
    if not scope_id or len(scope_id) > 128:
        _fail("invalid_demo_scope", "scope_occurrence_id must be a stable occurrence ID.")

    plan, source_plan_hash = _load_plan(Path(training_root), product_id)
    occurrences = _occurrence_index(product_structure)
    scope_ids = _scope_occurrence_ids(occurrences, scope_id)
    scope = occurrences[scope_id]
    plan_scope = plan["scope"]
    if _normalized_text(scope.get("name")) != _normalized_text(plan_scope.get("assemblyName")):
        _fail(
            "demo_scope_mismatch",
            "The selected product-structure scope does not match the trusted demo plan.",
        )

    scoped_names: Dict[str, List[str]] = {}
    for occurrence_id in sorted(scope_ids):
        name = _normalized_text(occurrences[occurrence_id].get("name"))
        if name:
            scoped_names.setdefault(name, []).append(occurrence_id)

    native_occurrence_by_plan_id: Dict[str, str] = {}
    unresolved: List[Dict[str, Any]] = []
    for plan_node in plan["nodes"]:
        if not isinstance(plan_node, dict) or not plan_node.get("id"):
            _fail("demo_plan_invalid", "Every demo-plan node requires a stable id.")
        plan_node_id = str(plan_node["id"])
        if not plan_node.get("occurrenceId"):
            continue
        matches = scoped_names.get(_normalized_text(plan_node.get("label")), [])
        if len(matches) == 1:
            native_occurrence_by_plan_id[plan_node_id] = matches[0]
        else:
            unresolved.append(
                {
                    "kind": "node",
                    "planTargetId": plan_node_id,
                    "label": str(plan_node.get("label") or plan_node_id),
                    "reason": "ambiguous_occurrence" if matches else "occurrence_not_found",
                }
            )

    canvas_nodes = [
        node for node in process_map.get("canvasNodes", []) if isinstance(node, dict)
    ]
    occurrence_nodes = {
        str(node.get("sourceOccurrenceId")): node
        for node in canvas_nodes
        if node.get("nodeKind") == "product_occurrence" and node.get("sourceOccurrenceId")
    }
    stage_nodes_by_name: Dict[str, List[Dict[str, Any]]] = {}
    for node in canvas_nodes:
        if node.get("nodeKind") != "process_step":
            continue
        stage_nodes_by_name.setdefault(_normalized_text(node.get("name")), []).append(node)

    map_node_by_plan_id: Dict[str, Dict[str, Any]] = {}
    unresolved_ids = {str(item["planTargetId"]) for item in unresolved}
    for plan_node in plan["nodes"]:
        plan_node_id = str(plan_node["id"])
        if plan_node_id in unresolved_ids:
            continue
        if plan_node.get("occurrenceId"):
            node = occurrence_nodes.get(native_occurrence_by_plan_id.get(plan_node_id, ""))
            if node:
                map_node_by_plan_id[plan_node_id] = node
            else:
                unresolved.append(
                    {
                        "kind": "node",
                        "planTargetId": plan_node_id,
                        "label": str(plan_node.get("label") or plan_node_id),
                        "reason": "card_not_placed",
                    }
                )
            continue
        matches = stage_nodes_by_name.get(_normalized_text(plan_node.get("label")), [])
        if len(matches) == 1:
            map_node_by_plan_id[plan_node_id] = matches[0]
        else:
            unresolved.append(
                {
                    "kind": "node",
                    "planTargetId": plan_node_id,
                    "label": str(plan_node.get("label") or plan_node_id),
                    "reason": "ambiguous_stage" if matches else "stage_not_found",
                }
            )

    resources = {
        str(item.get("id")): item
        for item in plan["resources"]
        if isinstance(item, dict) and item.get("id")
    }
    plan_node_labels = {
        str(item.get("id")): str(item.get("label") or item.get("id"))
        for item in plan["nodes"]
        if isinstance(item, dict) and item.get("id")
    }
    now = populated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    provenance = {
        "sourcePlanId": str(plan["processId"]),
        "sourceRevision": str(plan["revision"]),
        "sourcePlanHash": source_plan_hash,
        "populatedBy": "Sage",
        "populatedAt": now,
    }
    operations: List[Dict[str, Any]] = []
    populated_nodes = 0
    populated_routes = 0
    route_labels = 0
    illustrative_requirements = 0
    preserved_authored = 0

    for plan_node in plan["nodes"]:
        requirements = plan_node.get("requirements")
        if not requirements:
            continue
        plan_node_id = str(plan_node["id"])
        target = map_node_by_plan_id.get(plan_node_id)
        if target is None:
            continue
        count, preserved = _add_reference_operations(
            operations,
            process_map,
            resources,
            requirements,
            target_type="node",
            target_id=str(target["nodeId"]),
            target_records=[target],
            target_label=str(plan_node.get("label") or plan_node_id),
            source_target_id=plan_node_id,
            provenance=provenance,
        )
        if count:
            populated_nodes += 1
            illustrative_requirements += count
        preserved_authored += preserved

    logical_connections = _logical_connections(process_map)
    connections_by_endpoints: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for connection in logical_connections:
        key = (connection["sourceNodeId"], connection["targetNodeId"])
        connections_by_endpoints.setdefault(key, []).append(connection)

    for route in plan["routes"]:
        if not isinstance(route, dict) or not route.get("id"):
            _fail("demo_plan_invalid", "Every demo route requires a stable id.")
        route_id = str(route["id"])
        source = map_node_by_plan_id.get(str(route.get("source") or ""))
        target = map_node_by_plan_id.get(str(route.get("target") or ""))
        if source is None or target is None:
            unresolved.append(
                {
                    "kind": "route",
                    "planTargetId": route_id,
                    "label": str(route.get("name") or route_id),
                    "reason": "route_endpoint_unresolved",
                }
            )
            continue
        matches = connections_by_endpoints.get(
            (str(source["nodeId"]), str(target["nodeId"])), []
        )
        if len(matches) != 1:
            unresolved.append(
                {
                    "kind": "route",
                    "planTargetId": route_id,
                    "label": str(route.get("name") or route_id),
                    "reason": "ambiguous_route" if matches else "route_not_found",
                }
            )
            continue
        connection = matches[0]
        existing_labels = {
            str(edge.get("label") or "").strip()
            for edge in connection["edges"]
            if str(edge.get("label") or "").strip()
        }
        route_name = str(route.get("name") or "").strip()
        if not existing_labels and route_name:
            operations.append(
                {
                    "op": "set_edge_label",
                    "edgeId": connection["edgeId"],
                    "label": route_name,
                }
            )
            route_labels += 1
        elif existing_labels and existing_labels != {route_name}:
            unresolved.append(
                {
                    "kind": "route_label",
                    "planTargetId": route_id,
                    "label": route_name,
                    "reason": "authored_label_preserved",
                }
            )
        count, preserved = _add_reference_operations(
            operations,
            process_map,
            resources,
            route.get("requirements"),
            target_type="edge",
            target_id=connection["edgeId"],
            target_records=connection["edges"],
            target_label=(
                (route_name or route_id)
                + " - "
                + plan_node_labels.get(str(route.get("source") or ""), "source")
            ),
            source_target_id=route_id,
            provenance=provenance,
        )
        if count:
            populated_routes += 1
            illustrative_requirements += count
        preserved_authored += preserved

    import_identity = (
        provenance["sourcePlanId"],
        provenance["sourceRevision"],
        provenance["sourcePlanHash"],
    )
    import_exists = any(
        isinstance(item, dict)
        and tuple(
            str(item.get(field) or "")
            for field in ("sourcePlanId", "sourceRevision", "sourcePlanHash")
        ) == import_identity
        for item in process_map.get("processPlanImports", [])
        if isinstance(process_map.get("processPlanImports", []), list)
    )
    if operations and not import_exists:
        operations.append(
            {
                "op": "record_process_plan_import",
                **provenance,
                "demoData": True,
                "disclaimer": str(plan["disclaimer"]),
            }
        )

    ambiguous = sum(1 for item in unresolved if str(item.get("reason", "")).startswith("ambiguous"))
    summary = {
        "message": (
            "Illustrative Front Wheel metadata proposal ready."
            if operations
            else (
                "No metadata proposal was created because required map targets are missing or ambiguous."
                if unresolved
                else "All matching Front Wheel demo metadata is already populated."
            )
        ),
        "scopeOccurrenceId": scope_id,
        "scopeLabel": str(scope.get("name") or scope_id),
        "nodeRequirementSetsPopulated": populated_nodes,
        "routeNamesPopulated": route_labels,
        "routeRequirementSetsPopulated": populated_routes,
        "illustrativeRequirements": illustrative_requirements,
        "preservedAuthoredValues": preserved_authored,
        "ambiguousMatches": ambiguous,
        "unresolvedCount": len(unresolved),
        "unresolved": unresolved,
        "demoData": True,
        "disclaimer": str(plan["disclaimer"]),
    }
    return {
        "schemaVersion": 1,
        "operations": operations,
        "summary": summary,
        "source": {
            **provenance,
            "demoData": True,
            "fillMode": fill_mode,
        },
    }


__all__ = [
    "DEMO_METADATA_FILL_MODES",
    "DEMO_METADATA_PLAN_FILENAME",
    "DEMO_METADATA_TOOL",
    "ProcessMapDemoMetadataError",
    "compile_demo_metadata_operations",
    "demo_metadata_tool_spec",
]
