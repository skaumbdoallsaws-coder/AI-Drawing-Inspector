"""Product-neutral process-map template catalog and instantiation."""

from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .repository import (
    ProcessMapConflictError,
    ProcessMapNotFoundError,
    ProcessMapValidationError,
    _write_bytes_atomic,
    canonical_process_map_bytes,
    create_process_map,
    load_named_process_map,
    load_product_structure,
    process_map_revision,
)
from .schema_v3 import (
    PROCESS_MAP_LAYOUT_VERSION,
    PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
    validate_placement_map,
)
from .validate import has_structural_errors


PROCESS_MAP_TEMPLATE_SCHEMA_VERSION = 1
_TEMPLATE_ID_RE = re.compile(r"^pmt-[a-z0-9][a-z0-9-]{2,59}$")
_TEMPLATE_FILE_RE = re.compile(r"^(pmt-[a-z0-9][a-z0-9-]{2,59})\.json$")
_TEMPLATE_WRITE_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _template_directory(training_root: Path) -> Path:
    root = training_root.resolve()
    candidate = (root / "_templates" / "process_maps").resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProcessMapNotFoundError("process-map template directory escaped training root") from exc
    return candidate


def _clean_template_id(value: str) -> str:
    template_id = value.strip() if isinstance(value, str) else ""
    if _TEMPLATE_ID_RE.fullmatch(template_id) is None:
        raise ProcessMapNotFoundError("process-map template not found")
    return template_id


def _template_asset(training_root: Path, template_id: str) -> Path:
    safe_id = _clean_template_id(template_id)
    directory = _template_directory(training_root)
    candidate = (directory / f"{safe_id}.json").resolve()
    try:
        candidate.relative_to(directory)
    except ValueError as exc:
        raise ProcessMapNotFoundError("process-map template not found") from exc
    return candidate


def _read_template(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ProcessMapNotFoundError("process-map template not found")
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProcessMapNotFoundError("process-map template could not be loaded") from exc
    if not isinstance(value, dict) or value.get("templateSchemaVersion") != PROCESS_MAP_TEMPLATE_SCHEMA_VERSION:
        raise ProcessMapNotFoundError("process-map template has an unsupported schema")
    if value.get("templateId") != path.stem or not isinstance(value.get("skeleton"), dict):
        raise ProcessMapNotFoundError("process-map template identity is invalid")
    return value


def _new_template_id(training_root: Path) -> str:
    directory = _template_directory(training_root)
    for _attempt in range(64):
        template_id = f"pmt-{secrets.token_hex(4)}"
        if not (directory / f"{template_id}.json").exists():
            return template_id
    raise ProcessMapNotFoundError("could not allocate process-map template identity")


def _pruned_reference_catalog(skeleton: Dict[str, Any]) -> None:
    records = [*skeleton.get("canvasNodes", []), *skeleton.get("canvasEdges", [])]
    used = {
        reference_id
        for record in records
        if isinstance(record, dict) and isinstance(record.get("referenceIds"), list)
        for reference_id in record["referenceIds"]
        if isinstance(reference_id, str)
    }
    catalog = [
        reference for reference in skeleton.get("referenceCatalog", [])
        if isinstance(reference, dict) and reference.get("referenceId") in used
    ]
    if catalog:
        skeleton["referenceCatalog"] = catalog
    else:
        skeleton.pop("referenceCatalog", None)


def process_map_template_skeleton(process_map: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Strip product occurrences and return a reusable process skeleton."""
    source_nodes = process_map.get("canvasNodes") if isinstance(process_map.get("canvasNodes"), list) else []
    source_edges = process_map.get("canvasEdges") if isinstance(process_map.get("canvasEdges"), list) else []
    kept_nodes = [
        deepcopy(node) for node in source_nodes
        if isinstance(node, dict) and node.get("nodeKind") in {"process_step", "junction"}
    ]
    kept_ids = {node.get("nodeId") for node in kept_nodes}
    kept_edges = [
        deepcopy(edge) for edge in source_edges
        if isinstance(edge, dict)
        and edge.get("from", {}).get("nodeId") in kept_ids
        and edge.get("to", {}).get("nodeId") in kept_ids
    ]
    incident_ids = {
        endpoint.get("nodeId")
        for edge in kept_edges
        for endpoint in (edge.get("from", {}), edge.get("to", {}))
        if isinstance(endpoint, dict)
    }
    kept_nodes = [
        node for node in kept_nodes
        if node.get("nodeKind") != "junction" or node.get("nodeId") in incident_ids
    ]
    kept_ids = {node.get("nodeId") for node in kept_nodes}
    kept_edges = [
        edge for edge in kept_edges
        if edge.get("from", {}).get("nodeId") in kept_ids
        and edge.get("to", {}).get("nodeId") in kept_ids
    ]
    groups: List[Dict[str, Any]] = []
    for source_group in process_map.get("canvasGroups", []) if isinstance(process_map.get("canvasGroups"), list) else []:
        if not isinstance(source_group, dict):
            continue
        group = deepcopy(source_group)
        group["memberNodeIds"] = [
            node_id for node_id in group.get("memberNodeIds", []) if node_id in kept_ids
        ]
        groups.append(group)
    skeleton: Dict[str, Any] = {
        "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        "canvasNodes": kept_nodes,
        "canvasEdges": kept_edges,
        "canvasGroups": groups,
        "viewport": deepcopy(process_map.get("viewport") or {"x": 0, "y": 0, "scale": 1}),
    }
    if isinstance(process_map.get("referenceCatalog"), list):
        skeleton["referenceCatalog"] = deepcopy(process_map["referenceCatalog"])
    _pruned_reference_catalog(skeleton)
    dropped = {
        "productOccurrences": sum(
            1 for node in source_nodes
            if isinstance(node, dict) and node.get("nodeKind") == "product_occurrence"
        ),
        "nodes": len(source_nodes) - len(kept_nodes),
        "edges": len(source_edges) - len(kept_edges),
    }
    return skeleton, dropped


def _template_validation_map(skeleton: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
        "productId": "template",
        "productName": "Template",
        "sourceStructureRevision": "template",
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        "canvasNodes": deepcopy(skeleton.get("canvasNodes", [])),
        "canvasEdges": deepcopy(skeleton.get("canvasEdges", [])),
        "canvasGroups": deepcopy(skeleton.get("canvasGroups", [])),
        "viewport": deepcopy(skeleton.get("viewport") or {"x": 0, "y": 0, "scale": 1}),
        **(
            {"referenceCatalog": deepcopy(skeleton["referenceCatalog"])}
            if isinstance(skeleton.get("referenceCatalog"), list) else {}
        ),
    }


def save_process_map_template(
    training_root: Path,
    product_id: str,
    map_id: str,
    base_revision: str,
    *,
    display_name: str,
    description: Optional[str] = None,
    template_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Save a product-neutral skeleton outside every product directory."""
    loaded = load_named_process_map(training_root, product_id, map_id)
    supplied = base_revision.strip() if isinstance(base_revision, str) else ""
    if supplied != loaded["revision"]:
        raise ProcessMapConflictError(loaded["revision"])
    name = display_name.strip() if isinstance(display_name, str) else ""
    if not name or len(name) > 120:
        raise ProcessMapValidationError([{
            "severity": "error",
            "code": "invalid_template_name",
            "message": "Template displayName must contain 1 to 120 characters.",
        }])
    details = description.strip() if isinstance(description, str) else ""
    if len(details) > 2000:
        raise ProcessMapValidationError([{
            "severity": "error",
            "code": "invalid_template_description",
            "message": "Template description must contain at most 2000 characters.",
        }])
    skeleton, dropped = process_map_template_skeleton(loaded["map"])
    findings = validate_placement_map(_template_validation_map(skeleton), set())
    if has_structural_errors(findings):
        raise ProcessMapValidationError(findings)
    with _TEMPLATE_WRITE_LOCK:
        safe_template_id = (
            _clean_template_id(template_id)
            if template_id else _new_template_id(training_root)
        )
        asset = _template_asset(training_root, safe_template_id)
        if asset.exists():
            raise ProcessMapValidationError([{
                "severity": "error",
                "code": "template_id_exists",
                "message": f"Template '{safe_template_id}' already exists.",
            }])
        now = _utc_now()
        template: Dict[str, Any] = {
            "templateSchemaVersion": PROCESS_MAP_TEMPLATE_SCHEMA_VERSION,
            "templateId": safe_template_id,
            "displayName": name,
            "status": "template",
            "createdAt": now,
            "updatedAt": now,
            "skeleton": skeleton,
        }
        if details:
            template["description"] = details
        _write_bytes_atomic(asset, canonical_process_map_bytes(template))
    return {
        "template": template,
        "revision": process_map_revision(template),
        "findings": findings,
        "dropped": dropped,
        "assetName": asset.name,
    }


def list_process_map_templates(training_root: Path) -> Dict[str, Any]:
    directory = _template_directory(training_root)
    templates: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    if directory.is_dir():
        for asset in sorted(directory.glob("*.json"), key=lambda path: path.name):
            match = _TEMPLATE_FILE_RE.fullmatch(asset.name)
            if match is None:
                findings.append({
                    "severity": "warning",
                    "code": "unrecognized_template_asset",
                    "message": f"Ignored unrecognized template asset '{asset.name}'.",
                })
                continue
            try:
                template = _read_template(asset)
            except ProcessMapNotFoundError:
                findings.append({
                    "severity": "warning",
                    "code": "invalid_template_asset",
                    "message": f"Template asset '{asset.name}' could not be loaded.",
                })
                continue
            skeleton = template["skeleton"]
            templates.append({
                "templateId": template["templateId"],
                "displayName": template.get("displayName") or template["templateId"],
                "description": template.get("description") or "",
                "status": "template",
                "nodeCount": len(skeleton.get("canvasNodes", [])),
                "edgeCount": len(skeleton.get("canvasEdges", [])),
                "groupCount": len(skeleton.get("canvasGroups", [])),
                "createdAt": template.get("createdAt"),
                "updatedAt": template.get("updatedAt"),
                "revision": process_map_revision(template),
            })
    templates.sort(key=lambda item: (str(item["displayName"]).lower(), item["templateId"]))
    return {
        "templateSchemaVersion": PROCESS_MAP_TEMPLATE_SCHEMA_VERSION,
        "templates": templates,
        "findings": findings,
    }


def load_process_map_template(training_root: Path, template_id: str) -> Dict[str, Any]:
    asset = _template_asset(training_root, template_id)
    template = _read_template(asset)
    return {
        "template": template,
        "revision": process_map_revision(template),
        "assetName": asset.name,
    }


def _fresh_id(prefix: str, used: Set[str], forbidden: Set[str]) -> str:
    for _attempt in range(64):
        candidate = f"{prefix}-{secrets.token_hex(6)}"
        if candidate not in used and candidate not in forbidden:
            used.add(candidate)
            return candidate
    raise ProcessMapNotFoundError("could not regenerate template identifiers")


def instantiate_template_skeleton(skeleton: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, str]]]:
    """Clone a skeleton and regenerate every persisted graph identifier."""
    source_nodes = skeleton.get("canvasNodes") if isinstance(skeleton.get("canvasNodes"), list) else []
    source_edges = skeleton.get("canvasEdges") if isinstance(skeleton.get("canvasEdges"), list) else []
    source_groups = skeleton.get("canvasGroups") if isinstance(skeleton.get("canvasGroups"), list) else []
    source_catalog = skeleton.get("referenceCatalog") if isinstance(skeleton.get("referenceCatalog"), list) else []
    forbidden = {
        str(value)
        for record, keys in (
            *((node, ("nodeId",)) for node in source_nodes if isinstance(node, dict)),
            *((edge, ("edgeId", "logicalConnectionId")) for edge in source_edges if isinstance(edge, dict)),
            *((group, ("groupId",)) for group in source_groups if isinstance(group, dict)),
            *((reference, ("referenceId",)) for reference in source_catalog if isinstance(reference, dict)),
        )
        for key in keys
        for value in (record.get(key),)
        if value
    }
    used: Set[str] = set()
    node_ids = {
        str(node["nodeId"]): _fresh_id("pmj" if node.get("nodeKind") == "junction" else "pmn", used, forbidden)
        for node in source_nodes if isinstance(node, dict) and node.get("nodeId")
    }
    edge_ids = {
        str(edge["edgeId"]): _fresh_id("pme", used, forbidden)
        for edge in source_edges if isinstance(edge, dict) and edge.get("edgeId")
    }
    logical_values = sorted({
        str(edge.get("logicalConnectionId") or edge.get("edgeId"))
        for edge in source_edges if isinstance(edge, dict) and edge.get("edgeId")
    })
    logical_ids = {value: _fresh_id("pml", used, forbidden) for value in logical_values}
    group_ids = {
        str(group["groupId"]): _fresh_id("pmg", used, forbidden)
        for group in source_groups if isinstance(group, dict) and group.get("groupId")
    }
    reference_ids = {
        str(reference["referenceId"]): _fresh_id("pmr", used, forbidden)
        for reference in source_catalog if isinstance(reference, dict) and reference.get("referenceId")
    }

    nodes: List[Dict[str, Any]] = []
    for source in source_nodes:
        if not isinstance(source, dict) or source.get("nodeId") not in node_ids:
            continue
        node = deepcopy(source)
        node["nodeId"] = node_ids[str(source["nodeId"])]
        if isinstance(node.get("referenceIds"), list):
            node["referenceIds"] = [reference_ids[value] for value in node["referenceIds"] if value in reference_ids]
        nodes.append(node)
    edges: List[Dict[str, Any]] = []
    for source in source_edges:
        if not isinstance(source, dict) or source.get("edgeId") not in edge_ids:
            continue
        edge = deepcopy(source)
        old_logical = str(source.get("logicalConnectionId") or source["edgeId"])
        edge["edgeId"] = edge_ids[str(source["edgeId"])]
        edge["logicalConnectionId"] = logical_ids[old_logical]
        edge["from"]["nodeId"] = node_ids[str(source["from"]["nodeId"])]
        edge["to"]["nodeId"] = node_ids[str(source["to"]["nodeId"])]
        if isinstance(edge.get("referenceIds"), list):
            edge["referenceIds"] = [reference_ids[value] for value in edge["referenceIds"] if value in reference_ids]
        edges.append(edge)
    groups: List[Dict[str, Any]] = []
    for source in source_groups:
        if not isinstance(source, dict) or source.get("groupId") not in group_ids:
            continue
        group = deepcopy(source)
        group["groupId"] = group_ids[str(source["groupId"])]
        group["memberNodeIds"] = [node_ids[value] for value in source.get("memberNodeIds", []) if value in node_ids]
        groups.append(group)
    catalog: List[Dict[str, Any]] = []
    for source in source_catalog:
        if not isinstance(source, dict) or source.get("referenceId") not in reference_ids:
            continue
        reference = deepcopy(source)
        reference["referenceId"] = reference_ids[str(source["referenceId"])]
        catalog.append(reference)
    instantiated: Dict[str, Any] = {
        "canvasNodes": nodes,
        "canvasEdges": edges,
        "canvasGroups": groups,
        "viewport": deepcopy(skeleton.get("viewport") or {"x": 0, "y": 0, "scale": 1}),
    }
    if catalog:
        instantiated["referenceCatalog"] = catalog
    return instantiated, {
        "nodes": node_ids,
        "edges": edge_ids,
        "logicalConnections": logical_ids,
        "groups": group_ids,
        "references": reference_ids,
    }


def create_process_map_from_template(
    training_root: Path,
    product_id: str,
    template_id: str,
    *,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    loaded_template = load_process_map_template(training_root, template_id)
    template = loaded_template["template"]
    content, remap = instantiate_template_skeleton(template["skeleton"])
    structure = load_product_structure(training_root, product_id)
    initial: Dict[str, Any] = {
        "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
        "productId": product_id,
        "productName": str(structure["productStructure"].get("productName") or product_id),
        "sourceStructureRevision": structure["structureRevision"],
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        **content,
    }
    created = create_process_map(
        training_root,
        product_id,
        display_name=(display_name or f"{template.get('displayName') or template_id} Copy"),
        association={"productId": product_id},
        initial_content=initial,
    )
    created["templateId"] = template_id
    created["templateRevision"] = loaded_template["revision"]
    created["idRemap"] = remap
    return created
