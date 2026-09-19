"""Live Playwright smoke for source-tree process-map authoring."""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.process_map import spatialize_semantic_suggestions


OUT_DIR = ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8023/")
THREE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"


def _install_cached_three_route(page) -> None:
    if not THREE_CACHE.exists() or THREE_CACHE.stat().st_size <= 100_000:
        return
    three_js = THREE_CACHE.read_text(encoding="utf-8")
    page.route(
        THREE_CDN_URL,
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body=three_js,
        ),
    )


def _synthetic_structure() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "racing-bike",
        "productName": "Synthetic Product Structure",
        "occurrences": [
            {
                "occurrenceId": "root",
                "parentOccurrenceId": None,
                "itemId": None,
                "name": "Synthetic Assembly",
                "kind": "assembly",
                "level": 0,
                "partIds": ["SYN-A", "SYN-B"],
            },
            {
                "occurrenceId": "module-a",
                "parentOccurrenceId": "root",
                "itemId": None,
                "name": "Module A",
                "kind": "subassembly",
                "level": 1,
                "partIds": ["SYN-A"],
            },
            {
                "occurrenceId": "module-b",
                "parentOccurrenceId": "root",
                "itemId": None,
                "name": "Module B",
                "kind": "subassembly",
                "level": 1,
                "partIds": ["SYN-B"],
            },
            {
                "occurrenceId": "part-a-1",
                "parentOccurrenceId": "module-a",
                "itemId": "RB-003",
                "name": "Repeated Part A",
                "kind": "part",
                "level": 2,
                "partIds": ["RB-003"],
            },
            {
                "occurrenceId": "part-a-2",
                "parentOccurrenceId": "module-a",
                "itemId": "RB-003",
                "name": "Repeated Part A",
                "kind": "part",
                "level": 2,
                "partIds": ["RB-003"],
            },
            {
                "occurrenceId": "part-b",
                "parentOccurrenceId": "module-b",
                "itemId": "SYN-B",
                "name": "Part B",
                "kind": "part",
                "level": 2,
                "partIds": ["SYN-B"],
            },
        ],
    }


def _synthetic_process_map() -> dict:
    return {
        "schemaVersion": 3,
        "mapId": "default",
        "productId": "racing-bike",
        "productName": "Synthetic Process Map",
        "displayName": "Synthetic Process Map",
        "association": {"productId": "racing-bike"},
        "status": "active",
        "createdAt": "2026-07-20T00:00:00Z",
        "updatedAt": "2026-07-20T00:00:00Z",
        "sourceStructureRevision": "structure-rev-1",
        "layoutVersion": 1,
        "canvasNodes": [],
        "canvasEdges": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def _synthetic_routing_process_map() -> dict:
    process_map = _synthetic_process_map()
    process_map["layoutVersion"] = 3
    process_map["canvasNodes"] = [
        {
            "nodeId": "route-source",
            "nodeKind": "process_step",
            "processType": "operation",
            "name": "Source operation",
            "position": {"x": 80, "y": 240},
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
        {
            "nodeId": "route-obstacle",
            "nodeKind": "process_step",
            "processType": "inspection",
            "name": "Unrelated inspection",
            "position": {"x": 480, "y": 190},
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
        {
            "nodeId": "route-target",
            "nodeKind": "process_step",
            "processType": "output",
            "name": "Target output",
            "position": {"x": 900, "y": 240},
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
    ]
    process_map["canvasEdges"] = [
        {
            "edgeId": "route-edge",
            "from": {"nodeId": "route-source", "port": "out"},
            "to": {"nodeId": "route-target", "port": "in"},
            "kind": "precedence",
        }
    ]
    process_map["canvasGroups"] = []
    return process_map


def _synthetic_phase7_arrangement_map(grouped: bool = False) -> dict:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "process_map_spatial" / "phase7_arrangement.json")
        .read_text(encoding="utf-8")
    )
    process_map = copy.deepcopy(fixture["groupMap" if grouped else "ungroupedMap"])
    process_map.update({
        "mapId": "default",
        "productId": "racing-bike",
        "productName": "Phase 7 Arrangement Fixture",
        "displayName": "Phase 7 Arrangement Fixture",
        "association": {"productId": "racing-bike"},
        "status": "active",
        "createdAt": "2026-07-22T00:00:00Z",
        "updatedAt": "2026-07-22T00:00:00Z",
        "sourceStructureRevision": "structure-rev-1",
        "viewport": {"x": 0, "y": 0, "scale": 1},
    })
    for node in process_map["canvasNodes"]:
        node.setdefault("name", f"Phase 7 {node['nodeId'].upper()}")
        node.setdefault("portOrientation", "horizontal")
        node.setdefault("portOrder", "input_first")
    return process_map


def _synthetic_map_entry(store: dict, map_id: str) -> dict | None:
    if map_id == "default":
        return {"map": store["map"], "revision": store["revision"]}
    return store.setdefault("namedMaps", {}).get(map_id)


def _synthetic_loaded_map_payload(store: dict, map_id: str) -> dict | None:
    entry = _synthetic_map_entry(store, map_id)
    if entry is None:
        return None
    return {
        "success": True,
        "map": copy.deepcopy(entry["map"]),
        "revision": entry["revision"],
        "findings": copy.deepcopy(store.get("findings", [])),
        "productStructure": copy.deepcopy(store["structure"]),
        "structureRevision": "structure-rev-1",
        "assetName": f"{map_id}.json",
        "defaultMapId": "default",
    }


def _synthetic_process_map_summaries(store: dict) -> list[dict]:
    records = [("default", _synthetic_map_entry(store, "default"))]
    records.extend(sorted(store.setdefault("namedMaps", {}).items()))
    summaries = []
    for map_id, entry in records:
        process_map = entry["map"]
        if process_map.get("status") == "archived":
            continue
        summaries.append({
            "mapId": map_id,
            "displayName": process_map.get("displayName") or map_id,
            "association": copy.deepcopy(process_map.get("association") or {}),
            "status": process_map.get("status") or "draft",
            "createdAt": process_map.get("createdAt") or "2026-07-20T00:00:00Z",
            "updatedAt": process_map.get("updatedAt") or "2026-07-20T00:00:00Z",
            "revision": entry["revision"],
            "isDefault": map_id == "default",
        })
    return sorted(summaries, key=lambda item: (item["displayName"].lower(), item["mapId"]))


def _synthetic_validate_and_save(store: dict, map_id: str, payload: dict) -> tuple[int, dict]:
    entry = _synthetic_map_entry(store, map_id)
    if entry is None:
        return 404, {"detail": "Process map not found"}
    submitted = copy.deepcopy(payload.get("map") or {})
    store["putCount"] += 1
    store.setdefault("events", []).append({
        "kind": "save",
        "mapId": map_id,
        "baseRevision": payload.get("baseRevision"),
    })
    if store.pop("conflictNext", False):
        next_revision = "rev-external"
        if map_id == "default":
            store["revision"] = next_revision
        else:
            entry["revision"] = next_revision
        return 409, {"error": "revision_conflict", "currentRevision": next_revision}
    if payload.get("baseRevision") != entry["revision"]:
        return 409, {"error": "revision_conflict", "currentRevision": entry["revision"]}
    pairs = {
        (edge.get("from", {}).get("nodeId"), edge.get("to", {}).get("nodeId")): edge
        for edge in submitted.get("canvasEdges", [])
        if edge.get("kind") == "precedence"
    }
    reverse_pair = next(
        (
            edge for (source, target), edge in pairs.items()
            if (target, source) in pairs
        ),
        None,
    )
    if reverse_pair:
        return 422, {
            "error": "validation_failed",
            "findings": [{
                "severity": "error",
                "code": "precedence_cycle",
                "edgeId": reverse_pair.get("edgeId"),
                "message": "Precedence edges must not form a cycle.",
            }],
        }
    next_revision = f"rev-{store['putCount'] + 1}"
    submitted["mapId"] = map_id
    submitted["productId"] = "racing-bike"
    submitted["updatedAt"] = f"2026-07-20T00:00:{store['putCount']:02d}Z"
    if map_id == "default":
        store["map"] = submitted
        store["revision"] = next_revision
    else:
        entry["map"] = submitted
        entry["revision"] = next_revision
    store["findings"] = []
    return 200, _synthetic_loaded_map_payload(store, map_id)


def _install_synthetic_process_map_route(page, store: dict) -> None:
    def fulfill(route, status: int, payload: dict) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def handler(route) -> None:
        request = route.request
        if request.method == "GET":
            fulfill(
                route,
                200,
                {
                    "success": True,
                    "map": copy.deepcopy(store["map"]),
                    "revision": store["revision"],
                    "findings": copy.deepcopy(store.get("findings", [])),
                    "productStructure": copy.deepcopy(store["structure"]),
                    "structureRevision": "structure-rev-1",
                    "assetName": "synthetic_process_map.json",
                },
            )
            return

        status, result = _synthetic_validate_and_save(
            store,
            "default",
            request.post_data_json or {},
        )
        fulfill(route, status, result)

    page.route("**/api/training/process-map/racing-bike", handler)


def _install_spatial_telemetry_route(page, events: list[dict]) -> None:
    def handler(route) -> None:
        payload = route.request.post_data_json or {}
        events.append(copy.deepcopy(payload))
        route.fulfill(
            status=202,
            content_type="application/json",
            body=json.dumps({"success": True}),
        )

    page.route("**/api/training/process-map-spatial-events", handler)


def _install_synthetic_map_management_routes(page, store: dict) -> None:
    def fulfill(route, status: int, payload: dict) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def fresh_map_id() -> str:
        store["mapIdCounter"] = store.get("mapIdCounter", 0) + 1
        return f"pm-smoke-{store['mapIdCounter']:02d}"

    def create_map(display_name: str, source: dict | None = None) -> dict:
        map_id = fresh_map_id()
        process_map = copy.deepcopy(source if source is not None else _synthetic_process_map())
        process_map.update({
            "mapId": map_id,
            "displayName": display_name,
            "status": "draft",
            "createdAt": "2026-07-20T01:00:00Z",
            "updatedAt": "2026-07-20T01:00:00Z",
        })
        if source is None:
            process_map["canvasNodes"] = []
            process_map["canvasEdges"] = []
            process_map["canvasGroups"] = []
            process_map["layoutVersion"] = 2
        revision = f"rev-created-{store['mapIdCounter']}"
        store.setdefault("namedMaps", {})[map_id] = {
            "map": process_map,
            "revision": revision,
        }
        return _synthetic_loaded_map_payload(store, map_id)

    def template_skeleton(process_map: dict) -> dict:
        nodes = [
            copy.deepcopy(node) for node in process_map.get("canvasNodes", [])
            if node.get("nodeKind") in {"process_step", "junction"}
        ]
        node_ids = {node.get("nodeId") for node in nodes}
        edges = [
            copy.deepcopy(edge) for edge in process_map.get("canvasEdges", [])
            if edge.get("from", {}).get("nodeId") in node_ids
            and edge.get("to", {}).get("nodeId") in node_ids
        ]
        groups = []
        for source in process_map.get("canvasGroups", []):
            group = copy.deepcopy(source)
            group["memberNodeIds"] = [
                node_id for node_id in group.get("memberNodeIds", []) if node_id in node_ids
            ]
            groups.append(group)
        return {
            "schemaVersion": 3,
            "layoutVersion": 2,
            "canvasNodes": nodes,
            "canvasEdges": edges,
            "canvasGroups": groups,
            "viewport": copy.deepcopy(process_map.get("viewport") or {"x": 0, "y": 0, "scale": 1}),
        }

    def instantiate_skeleton(skeleton: dict) -> dict:
        store["templateCloneCounter"] = store.get("templateCloneCounter", 0) + 1
        suffix = f"clone-{store['templateCloneCounter']}"
        nodes = copy.deepcopy(skeleton.get("canvasNodes", []))
        node_ids = {
            node["nodeId"]: f"{node['nodeId']}-{suffix}"
            for node in nodes
        }
        for node in nodes:
            node["nodeId"] = node_ids[node["nodeId"]]
        logical_ids = {}
        edges = copy.deepcopy(skeleton.get("canvasEdges", []))
        for edge in edges:
            old_edge_id = edge["edgeId"]
            old_logical = edge.get("logicalConnectionId") or old_edge_id
            logical_ids.setdefault(old_logical, f"{old_logical}-{suffix}")
            edge["edgeId"] = f"{old_edge_id}-{suffix}"
            edge["logicalConnectionId"] = logical_ids[old_logical]
            edge["from"]["nodeId"] = node_ids[edge["from"]["nodeId"]]
            edge["to"]["nodeId"] = node_ids[edge["to"]["nodeId"]]
        groups = copy.deepcopy(skeleton.get("canvasGroups", []))
        for group in groups:
            group["groupId"] = f"{group['groupId']}-{suffix}"
            group["memberNodeIds"] = [node_ids[node_id] for node_id in group.get("memberNodeIds", [])]
        return {
            "canvasNodes": nodes,
            "canvasEdges": edges,
            "canvasGroups": groups,
            "viewport": copy.deepcopy(skeleton.get("viewport") or {"x": 0, "y": 0, "scale": 1}),
        }

    def template_handler(route) -> None:
        templates = [
            {
                "templateId": item["templateId"],
                "displayName": item["displayName"],
                "description": item.get("description", ""),
                "status": "template",
                "nodeCount": len(item["skeleton"].get("canvasNodes", [])),
                "edgeCount": len(item["skeleton"].get("canvasEdges", [])),
                "groupCount": len(item["skeleton"].get("canvasGroups", [])),
                "revision": item["revision"],
            }
            for item in store.setdefault("templates", {}).values()
        ]
        fulfill(route, 200, {"success": True, "templates": templates, "findings": []})

    def collection_handler(route) -> None:
        request = route.request
        if request.method == "GET":
            fulfill(route, 200, {
                "success": True,
                "registryVersion": 1,
                "defaultMapId": "default",
                "maps": _synthetic_process_map_summaries(store),
                "findings": [],
            })
            return
        payload = request.post_data_json or {}
        source_id = payload.get("duplicateOf")
        source_entry = _synthetic_map_entry(store, source_id) if source_id else None
        if source_id and source_entry is None:
            fulfill(route, 404, {"detail": "Process map not found"})
            return
        result = create_map(
            str(payload.get("displayName") or "Untitled Process Map"),
            source_entry["map"] if source_entry else None,
        )
        fulfill(route, 200, result)

    def named_handler(route) -> None:
        request = route.request
        path = urlparse(request.url).path
        prefix = "/api/training/process-maps/racing-bike/"
        suffix = path[len(prefix):] if path.startswith(prefix) else ""
        parts = [part for part in suffix.split("/") if part]
        if not parts:
            fulfill(route, 404, {"detail": "Process map not found"})
            return
        if parts[0] == "from-template":
            payload = request.post_data_json or {}
            template = store.setdefault("templates", {}).get(payload.get("templateId"))
            if template is None:
                fulfill(route, 404, {"detail": "Process-map template not found"})
                return
            content = instantiate_skeleton(template["skeleton"])
            base = _synthetic_process_map()
            base.update(content)
            result = create_map(str(payload.get("displayName") or template["displayName"]), base)
            result["templateId"] = template["templateId"]
            fulfill(route, 200, result)
            return
        map_id = parts[0]
        entry = _synthetic_map_entry(store, map_id)
        if entry is None:
            fulfill(route, 404, {"detail": "Process map not found"})
            return
        operation = parts[1] if len(parts) > 1 else ""
        if operation == "suggestions":
            fulfill(route, 200, {
                "success": True,
                "schemaVersion": 1,
                "engineVersion": "synthetic-1",
                "productId": "racing-bike",
                "mapId": map_id,
                "revision": entry["revision"],
                "suggestions": [],
                "summary": {"returned": 0, "edgeSuggestions": 0, "annotations": 0},
            })
            return
        if operation == "archive":
            payload = request.post_data_json or {}
            if map_id == "default":
                fulfill(route, 422, {"error": "default_map_cannot_be_archived"})
                return
            if payload.get("baseRevision") != entry["revision"]:
                fulfill(route, 409, {"error": "revision_conflict", "currentRevision": entry["revision"]})
                return
            entry["map"]["status"] = "archived"
            entry["revision"] = f"rev-archived-{map_id}"
            fulfill(route, 200, _synthetic_loaded_map_payload(store, map_id))
            return
        if operation == "save-as-template":
            payload = request.post_data_json or {}
            if payload.get("baseRevision") != entry["revision"]:
                fulfill(route, 409, {"error": "revision_conflict", "currentRevision": entry["revision"]})
                return
            template_id = f"pmt-smoke-{len(store.setdefault('templates', {})) + 1}"
            skeleton = template_skeleton(entry["map"])
            template = {
                "templateSchemaVersion": 1,
                "templateId": template_id,
                "displayName": str(payload.get("displayName") or "Process Map Template"),
                "status": "template",
                "skeleton": skeleton,
                "revision": f"template-rev-{len(store['templates']) + 1}",
            }
            store["templates"][template_id] = template
            fulfill(route, 200, {
                "success": True,
                "template": copy.deepcopy(template),
                "revision": template["revision"],
                "findings": [],
                "dropped": {},
            })
            return
        if request.method == "GET":
            fulfill(route, 200, _synthetic_loaded_map_payload(store, map_id))
            return
        status, result = _synthetic_validate_and_save(store, map_id, request.post_data_json or {})
        fulfill(route, status, result)

    page.route("**/api/training/process-map-templates", template_handler)
    page.route("**/api/training/process-maps/racing-bike", collection_handler)
    page.route("**/api/training/process-maps/racing-bike/**", named_handler)
    page.route(
        "**/api/builder/process-maps/policy",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "success": True,
                "writeEnabled": store.get("builderWriteEnabled", True),
                "contractVersion": 1,
            }),
        ),
    )


def _install_synthetic_suggestion_route(page, store: dict) -> None:
    def handler(route) -> None:
        requested_revision = parse_qs(urlparse(route.request.url).query).get(
            "revision", [""]
        )[0]
        store["suggestionCalls"] = store.get("suggestionCalls", 0) + 1
        if requested_revision != store["revision"]:
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({
                    "error": "revision_conflict",
                    "currentRevision": store["revision"],
                }),
            )
            return
        dismissed = set(store["map"].get("dismissedSuggestions", []))
        existing = {
            (
                edge.get("from", {}).get("nodeId"),
                edge.get("to", {}).get("nodeId"),
                edge.get("kind", "precedence"),
            )
            for edge in store["map"].get("canvasEdges", [])
        }
        suggestions = []
        for suggestion in store.get("suggestions", []):
            if suggestion.get("suggestionId") in dismissed:
                continue
            edge = suggestion.get("edge")
            if edge and (
                edge.get("from", {}).get("nodeId"),
                edge.get("to", {}).get("nodeId"),
                edge.get("kind", "precedence"),
            ) in existing:
                continue
            suggestions.append(copy.deepcopy(suggestion))
        spatial_summary = None
        if store.get("spatializeSuggestions"):
            spatialized = spatialize_semantic_suggestions(store["map"], suggestions)
            suggestions = spatialized["suggestions"]
            spatial_summary = spatialized["summary"]
        response_body = {
            "success": True,
            "schemaVersion": 1,
            "engineVersion": "synthetic-1",
            "productId": "racing-bike",
            "mapId": "default",
            "revision": store["revision"],
            "suggestions": suggestions,
            "summary": {
                "returned": len(suggestions),
                "edgeSuggestions": sum(1 for item in suggestions if item.get("edge")),
                "placementSuggestions": sum(1 for item in suggestions if item.get("placement")),
                "annotations": sum(1 for item in suggestions if item.get("annotation")),
            },
        }
        if spatial_summary is not None:
            response_body["spatialSummary"] = spatial_summary
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(response_body),
        )

    page.route(
        "**/api/training/process-maps/racing-bike/default/suggestions?*",
        handler,
    )


def _install_synthetic_agent_route(page, store: dict, captured: list[dict]) -> None:
    page.route(
        "**/api/agent/chat/streaming-status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"enabled": False, "agents": []}),
        ),
    )

    def handler(route) -> None:
        request = route.request
        if request.method != "POST":
            route.fallback()
            return
        payload = copy.deepcopy(request.post_data_json or {})
        captured.append(payload)
        store.setdefault("events", []).append({"kind": "agent"})
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "response": "The saved process map has one linear flow.",
                "tool_calls": [],
                "workflow_state": None,
            }),
        )

    page.route("**/api/agent/chat", handler)


def _install_synthetic_semantic_agent_route(
    page,
    semantic_plan: dict,
    captured: list[dict],
) -> None:
    def handler(route) -> None:
        request = route.request
        if request.method != "POST":
            route.fallback()
            return
        payload = copy.deepcopy(request.post_data_json or {})
        captured.append(payload)
        message = str(payload.get("message") or "")
        if "build and visually validate" not in message.lower():
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "response": "The saved process map has one linear flow.",
                    "tool_calls": [],
                    "workflow_state": None,
                }),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "response": "Preparing one complete process-map proposal.",
                "tool_calls": [{
                    "name": "build_process_map_preview",
                    "args": {
                        "scope_occurrence_id": "module-a",
                        "semantic_plan": copy.deepcopy(semantic_plan),
                    },
                }],
                "skill_runtime": {
                    "workflow": {"id": "process-map-generation"},
                },
                "workflow_state": None,
            }),
        )

    page.route("**/api/agent/chat", handler)


def _install_synthetic_spatial_proposal_routes(page, store: dict) -> None:
    proposal_node = {
        "nodeId": "pmn-agent-browser",
        "nodeKind": "product_occurrence",
        "sourceOccurrenceId": "part-a-1",
        "itemIdSnapshot": "RB-003",
        "nameSnapshot": "Repeated Part A",
        "position": {"x": 100, "y": 220},
        "portOrientation": "horizontal",
        "portOrder": "input_first",
    }
    proposal = {
        "success": True,
        "proposalId": "pm-proposal-browser",
        "action": "apply_operations",
        "productId": "racing-bike",
        "mapId": "default",
        "baseRevision": "phase6-rev-1",
        "diffHash": "d" * 64,
        "spatialBindingHash": "b" * 64,
        "preview": {"nodes": [proposal_node], "edges": [], "groups": []},
        "summary": {
            "action": "place_card",
            "label": "Repeated Part A",
            "message": "Placed Repeated Part A.",
        },
    }

    def fulfill(route, status: int, payload: dict) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def proposal_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("spatialEvents", []).append({"kind": "proposal", "body": payload})
        if payload.get("baseRevision") != store["revision"]:
            fulfill(route, 409, {"error": "revision_conflict", "currentRevision": store["revision"]})
            return
        response = copy.deepcopy(proposal)
        response["baseRevision"] = store["revision"]
        fulfill(route, 200, response)

    def approval_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("spatialEvents", []).append({"kind": "approval", "body": payload})
        valid = (
            payload.get("baseRevision") == store["revision"]
            and payload.get("diffHash") == proposal["diffHash"]
            and payload.get("spatialBindingHash") == proposal["spatialBindingHash"]
            and payload.get("explicitApproval") is True
        )
        if not valid:
            fulfill(route, 403, {"error": "approval_binding_mismatch"})
            return
        store["approvalKey"] = payload.get("idempotencyKey")
        fulfill(route, 200, {
            "success": True,
            "approvalToken": "phase6-approval-token",
            "proposalId": proposal["proposalId"],
            "diffHash": proposal["diffHash"],
            "spatialBindingHash": proposal["spatialBindingHash"],
        })

    def apply_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("spatialEvents", []).append({"kind": "apply", "body": payload})
        valid = (
            payload.get("approvalToken") == "phase6-approval-token"
            and payload.get("baseRevision") == store["revision"]
            and payload.get("diffHash") == proposal["diffHash"]
            and payload.get("spatialBindingHash") == proposal["spatialBindingHash"]
            and payload.get("idempotencyKey") == store.get("approvalKey")
        )
        if not valid:
            fulfill(route, 403, {"error": "approval_binding_mismatch"})
            return
        saved_map = copy.deepcopy(store["map"])
        saved_map["canvasNodes"] = [
            *saved_map.get("canvasNodes", []),
            copy.deepcopy(proposal_node),
        ]
        saved_map["layoutVersion"] = 3
        store["map"] = saved_map
        store["revision"] = "phase6-rev-2"
        fulfill(route, 200, {
            "success": True,
            "map": copy.deepcopy(saved_map),
            "revision": store["revision"],
            "findings": [],
            "productStructure": copy.deepcopy(store["structure"]),
            "structureRevision": "structure-rev-1",
            "receipt": {
                "receiptId": "phase6-receipt",
                "proposalId": proposal["proposalId"],
                "diffHash": proposal["diffHash"],
                "spatialBindingHash": proposal["spatialBindingHash"],
                "outcome": copy.deepcopy(proposal["summary"]),
            },
        })

    page.route(
        "**/api/builder/process-maps/racing-bike/default/spatial-proposals",
        proposal_handler,
    )
    page.route(
        "**/api/builder/process-map-proposals/pm-proposal-browser/approve",
        approval_handler,
    )
    page.route("**/api/builder/process-map-apply", apply_handler)


def _install_synthetic_semantic_proposal_routes(page, store: dict) -> None:
    preview_nodes = [
        {
            "nodeId": "semantic-part-a-1",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "part-a-1",
            "itemIdSnapshot": "RB-003",
            "nameSnapshot": "Repeated Part A",
            "position": {"x": 80, "y": 80},
            "positionMode": "auto",
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
        {
            "nodeId": "semantic-part-a-2",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "part-a-2",
            "itemIdSnapshot": "RB-003",
            "nameSnapshot": "Repeated Part A",
            "position": {"x": 80, "y": 310},
            "positionMode": "auto",
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
        {
            "nodeId": "semantic-junction",
            "nodeKind": "junction",
            "junctionType": "parallel_and",
            "position": {"x": 440, "y": 195},
            "positionMode": "auto",
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
        {
            "nodeId": "semantic-stage",
            "nodeKind": "process_step",
            "processType": "operation",
            "name": "Join Module A parts",
            "position": {"x": 600, "y": 195},
            "positionMode": "auto",
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
        {
            "nodeId": "semantic-module-a",
            "nodeKind": "product_occurrence",
            "sourceOccurrenceId": "module-a",
            "nameSnapshot": "Module A",
            "position": {"x": 1000, "y": 195},
            "positionMode": "auto",
            "portOrientation": "horizontal",
            "portOrder": "input_first",
        },
    ]
    preview_edges = [
        {
            "edgeId": "semantic-edge-a1",
            "from": {"nodeId": "semantic-part-a-1", "port": "out"},
            "to": {"nodeId": "semantic-junction", "port": "in"},
            "kind": "precedence",
        },
        {
            "edgeId": "semantic-edge-a2",
            "from": {"nodeId": "semantic-part-a-2", "port": "out"},
            "to": {"nodeId": "semantic-junction", "port": "in"},
            "kind": "precedence",
        },
        {
            "edgeId": "semantic-edge-junction",
            "from": {"nodeId": "semantic-junction", "port": "out"},
            "to": {"nodeId": "semantic-stage", "port": "in"},
            "kind": "precedence",
        },
        {
            "edgeId": "semantic-edge-output",
            "from": {"nodeId": "semantic-stage", "port": "out"},
            "to": {"nodeId": "semantic-module-a", "port": "in"},
            "kind": "precedence",
        },
    ]
    proposal = {
        "success": True,
        "proposalId": "pm-semantic-proposal-browser",
        "action": "apply_operations",
        "productId": "racing-bike",
        "mapId": "default",
        "baseRevision": store["revision"],
        "diffHash": "d" * 64,
        "managedProposalType": "semantic_process_map",
        "semanticBindingHash": "c" * 64,
        "preview": {
            "nodes": preview_nodes,
            "edges": preview_edges,
            "groups": [],
        },
        "summary": {
            "message": "Review the complete Module A process-map proposal.",
            "requiredOccurrenceCount": 2,
            "operationCount": 1,
            "junctionCount": 1,
            "connectionCount": 4,
            "assumptionCount": 1,
            "unresolvedCount": 0,
        },
        "createdIds": {
            "nodeIds": [node["nodeId"] for node in preview_nodes],
            "edgeIds": [edge["edgeId"] for edge in preview_edges],
        },
        "visualValidation": {
            "schemaVersion": 1,
            "status": "corrected",
            "correctionCount": 2,
            "labelCorrectionCount": 1,
            "membershipCorrectionCount": 1,
            "unresolvedItems": [],
            "artifact": {
                "artifactId": "visual-fixture",
                "assetHash": "e" * 64,
                "width": 1200,
                "height": 900,
                "url": (
                    "/api/builder/process-map-proposals/"
                    "pm-semantic-proposal-browser/visual-validation-image"
                ),
            },
        },
        "warnings": [],
        "unresolvedItems": [],
    }

    def fulfill(route, status: int, payload: dict) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def proposal_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("semanticEvents", []).append(
            {"kind": "proposal", "body": payload}
        )
        delay_seconds = float(store.get("semanticProposalDelaySeconds") or 0)
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        response = copy.deepcopy(proposal)
        response["baseRevision"] = store["revision"]
        fulfill(route, 200, response)

    def approval_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("semanticEvents", []).append(
            {"kind": "approval", "body": payload}
        )
        valid = (
            payload.get("baseRevision") == store["revision"]
            and payload.get("diffHash") == proposal["diffHash"]
            and payload.get("semanticBindingHash")
                == proposal["semanticBindingHash"]
            and payload.get("explicitApproval") is True
        )
        if not valid:
            fulfill(route, 403, {"error": "approval_binding_mismatch"})
            return
        store["semanticApprovalKey"] = payload.get("idempotencyKey")
        fulfill(
            route,
            200,
            {
                "success": True,
                "approvalToken": "semantic-approval-token",
                "proposalId": proposal["proposalId"],
                "diffHash": proposal["diffHash"],
                "semanticBindingHash": proposal["semanticBindingHash"],
            },
        )

    def apply_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("semanticEvents", []).append(
            {"kind": "apply", "body": payload}
        )
        valid = (
            payload.get("approvalToken") == "semantic-approval-token"
            and payload.get("baseRevision") == store["revision"]
            and payload.get("diffHash") == proposal["diffHash"]
            and payload.get("semanticBindingHash")
                == proposal["semanticBindingHash"]
            and payload.get("idempotencyKey")
                == store.get("semanticApprovalKey")
        )
        if not valid:
            fulfill(route, 403, {"error": "approval_binding_mismatch"})
            return
        store["map"]["layoutVersion"] = 3
        store["map"]["canvasNodes"] = copy.deepcopy(preview_nodes)
        store["map"]["canvasEdges"] = copy.deepcopy(preview_edges)
        store["map"]["canvasGroups"] = []
        previous_revision = store["revision"]
        store["revision"] = "semantic-rev-2"
        fulfill(
            route,
            200,
            {
                **_synthetic_loaded_map_payload(store, "default"),
                "receipt": {
                    "receiptId": "semantic-receipt",
                    "proposalId": proposal["proposalId"],
                    "action": "apply_operations",
                    "productId": "racing-bike",
                    "mapId": "default",
                    "baseRevision": previous_revision,
                    "revision": store["revision"],
                    "diffHash": proposal["diffHash"],
                    "semanticBindingHash": proposal["semanticBindingHash"],
                    "createdIds": copy.deepcopy(proposal["createdIds"]),
                    "warnings": [],
                    "unresolvedItems": [],
                    "outcome": copy.deepcopy(proposal["summary"]),
                },
            },
        )

    page.route(
        "**/api/builder/process-maps/racing-bike/default/semantic-proposals",
        proposal_handler,
    )
    page.route(
        "**/api/builder/process-map-proposals/pm-semantic-proposal-browser/approve",
        approval_handler,
    )
    page.route("**/api/builder/process-map-apply", apply_handler)


def _install_synthetic_metadata_proposal_routes(page, store: dict) -> None:
    node = copy.deepcopy(store["map"]["canvasNodes"][0])
    edge = copy.deepcopy(store["map"]["canvasEdges"][0])
    node["referenceIds"] = ["demo-machine", "demo-node-requirement"]
    edge["label"] = "Install demo component"
    edge["referenceIds"] = ["demo-route-requirement"]
    catalog = [
        {
            "referenceId": "demo-machine",
            "kind": "machine",
            "name": "Wheel assembly fixture",
            "knowledgeStatus": "illustrative",
            "demoData": True,
            "sourcePlanId": "front-wheel-brake-demo",
            "sourceRevision": "A",
            "sourcePlanHash": "a" * 64,
            "sourceResourceId": "res-wheel-fixture",
            "populatedBy": "Sage",
            "populatedAt": "2026-07-22T12:00:00Z",
        },
        {
            "referenceId": "demo-node-requirement",
            "kind": "requirement",
            "name": "Demo component: WI-FW-001 3.1",
            "identifier": "WI-FW-001",
            "revision": "A",
            "clause": "3.1",
            "details": "Illustrative card requirement.",
            "knowledgeStatus": "illustrative",
            "demoData": True,
            "sourcePlanId": "front-wheel-brake-demo",
            "sourceRevision": "A",
            "sourcePlanHash": "a" * 64,
            "sourceRequirementId": "part-demo:requirement:1",
            "populatedBy": "Sage",
            "populatedAt": "2026-07-22T12:00:00Z",
        },
        {
            "referenceId": "demo-route-requirement",
            "kind": "requirement",
            "name": "Install demo component: WI-FW-001 3.2",
            "identifier": "WI-FW-001",
            "revision": "A",
            "clause": "3.2",
            "details": "Illustrative routing requirement.",
            "knowledgeStatus": "illustrative",
            "demoData": True,
            "sourcePlanId": "front-wheel-brake-demo",
            "sourceRevision": "A",
            "sourcePlanHash": "a" * 64,
            "sourceRequirementId": "route-demo:requirement:1",
            "populatedBy": "Sage",
            "populatedAt": "2026-07-22T12:00:00Z",
        },
    ]
    proposal = {
        "success": True,
        "proposalId": "pm-metadata-proposal-browser",
        "action": "apply_operations",
        "productId": "racing-bike",
        "mapId": "default",
        "baseRevision": store["revision"],
        "diffHash": "e" * 64,
        "managedProposalType": "process_metadata",
        "preview": {"nodes": [node], "edges": [edge], "groups": []},
        "summary": {
            "message": "Illustrative Front Wheel metadata proposal ready.",
            "nodeRequirementSetsPopulated": 1,
            "routeNamesPopulated": 1,
            "routeRequirementSetsPopulated": 1,
            "illustrativeRequirements": 2,
            "unresolvedCount": 0,
            "demoData": True,
        },
    }

    def fulfill(route, status: int, payload: dict) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def proposal_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("metadataEvents", []).append({"kind": "proposal", "body": payload})
        response = copy.deepcopy(proposal)
        response["baseRevision"] = store["revision"]
        fulfill(route, 200, response)

    def approval_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("metadataEvents", []).append({"kind": "approval", "body": payload})
        valid = (
            payload.get("baseRevision") == store["revision"]
            and payload.get("diffHash") == proposal["diffHash"]
            and payload.get("explicitApproval") is True
            and "spatialBindingHash" not in payload
        )
        if not valid:
            fulfill(route, 403, {"error": "approval_binding_mismatch"})
            return
        store["metadataApprovalKey"] = payload.get("idempotencyKey")
        fulfill(route, 200, {
            "success": True,
            "approvalToken": "metadata-approval-token",
            "proposalId": proposal["proposalId"],
            "diffHash": proposal["diffHash"],
        })

    def apply_handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        store.setdefault("metadataEvents", []).append({"kind": "apply", "body": payload})
        valid = (
            payload.get("approvalToken") == "metadata-approval-token"
            and payload.get("baseRevision") == store["revision"]
            and payload.get("diffHash") == proposal["diffHash"]
            and payload.get("idempotencyKey") == store.get("metadataApprovalKey")
            and "spatialBindingHash" not in payload
        )
        if not valid:
            fulfill(route, 403, {"error": "approval_binding_mismatch"})
            return
        saved_map = copy.deepcopy(store["map"])
        saved_map["canvasNodes"][0] = node
        saved_map["canvasEdges"][0] = edge
        saved_map["referenceCatalog"] = catalog
        saved_map["processPlanImports"] = [{
            "sourcePlanId": "front-wheel-brake-demo",
            "sourceRevision": "A",
            "sourcePlanHash": "a" * 64,
            "demoData": True,
            "disclaimer": "Illustrative demo data only.",
            "populatedBy": "Sage",
            "populatedAt": "2026-07-22T12:00:00Z",
        }]
        store["map"] = saved_map
        store["revision"] = "metadata-rev-2"
        fulfill(route, 200, {
            "success": True,
            "map": copy.deepcopy(saved_map),
            "revision": store["revision"],
            "findings": [],
            "productStructure": copy.deepcopy(store["structure"]),
            "structureRevision": "structure-rev-1",
            "receipt": {
                "receiptId": "metadata-receipt",
                "proposalId": proposal["proposalId"],
                "diffHash": proposal["diffHash"],
                "outcome": copy.deepcopy(proposal["summary"]),
            },
        })

    page.route(
        "**/api/builder/process-maps/racing-bike/default/demo-metadata-proposals",
        proposal_handler,
    )
    page.route(
        "**/api/builder/process-map-proposals/pm-metadata-proposal-browser/approve",
        approval_handler,
    )
    page.route("**/api/builder/process-map-apply", apply_handler)


def _install_synthetic_metadata_chat_stream(page, captured: list[dict]) -> None:
    page.route(
        "**/api/agent/chat/streaming-status",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "enabled": True,
                "agents": ["sage"],
                "high_risk_modes": False,
            }),
        ),
    )

    def handler(route) -> None:
        payload = copy.deepcopy(route.request.post_data_json or {})
        captured.append(payload)
        response_id = "stream-metadata-smoke"
        events = [
            {
                "v": 1,
                "event": "response_started",
                "response_id": response_id,
                "seq": 0,
                "ts": 1,
                "message_id": "assistant-metadata-smoke",
                "agent_type": "deviation-analyst",
            },
            {
                "v": 1,
                "event": "action_bundle_validated",
                "response_id": response_id,
                "seq": 1,
                "ts": 2,
                "source": "native",
            },
            {
                "v": 1,
                "event": "response_completed",
                "response_id": response_id,
                "seq": 2,
                "ts": 3,
                "final": {
                    "response": "",
                    "tool_calls": [{
                        "name": "propose_process_map_demo_metadata",
                        "args": {
                            "scope_occurrence_id": "module-a",
                            "fill_mode": "fill_missing",
                        },
                    }],
                    "tool_call_count": 1,
                    "tool_source": "native",
                },
                "usage": {},
                "timings": {},
            },
        ]
        body = "".join(
            "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"
            for event in events
        )
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
            body=body,
        )

    page.route("**/api/agent/chat/v2/stream", handler)


def _wait_for_process_flow_entry(page) -> None:
    page.wait_for_timeout(1_500)
    page.locator("#profileCount").inner_text(timeout=120_000)
    page.locator(".tab[data-tab='training']").click()
    page.wait_for_selector(".tab.active[data-tab='training']", timeout=10_000)
    page.wait_for_selector("#trainingTypeRibbonSelect", timeout=30_000)
    page.locator("#trainingTypeRibbonSelect").select_option("assembly")
    page.wait_for_selector("[data-process-flow-editor='true']", timeout=30_000)


def _open_process_flow(page) -> None:
    _wait_for_process_flow_entry(page)


def _ensure_process_flow_editor(page) -> None:
    if page.locator("[data-process-flow-editor='true']").count() == 0:
        page.wait_for_selector("#trainingTypeRibbonSelect", timeout=15_000)
        page.locator("#trainingTypeRibbonSelect").select_option("assembly")
    page.wait_for_selector("[data-process-flow-editor='true']", timeout=15_000)


def _expand(page, occurrence_id: str) -> None:
    row = page.locator(f".pm-tree-row[data-occurrence-id='{occurrence_id}']")
    row.scroll_into_view_if_needed()
    if row.get_attribute("aria-expanded") == "false":
        row.locator(".pm-tree-caret").click()


def _drag_tree_item(page, occurrence_id: str, target_x: float, target_y: float) -> None:
    source = page.locator(f".pm-tree-row[data-occurrence-id='{occurrence_id}']")
    source.scroll_into_view_if_needed()
    source.drag_to(
        page.locator(".pm-viewport"),
        target_position={"x": target_x, "y": target_y},
        force=True,
    )


def _drag_connection(page, from_id: str, to_id: str) -> None:
    page.evaluate("window.__processMapFlow.editor.setCanvasInteractionMode('select')")
    output_box = page.locator(f".pm-node[data-node-id='{from_id}'] .pm-port-out").bounding_box()
    input_box = page.locator(f".pm-node[data-node-id='{to_id}'] .pm-port-in").bounding_box()
    assert output_box is not None and input_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(input_box["x"] + input_box["width"] / 2, input_box["y"] + input_box["height"] / 2, steps=8)
    page.mouse.up()


def _sketch_connection(page, from_id: str, to_id: str) -> list[dict]:
    page.evaluate("window.__processMapFlow.editor.setCanvasInteractionMode('select')")
    output_box = page.locator(
        f".pm-node[data-node-id='{from_id}'] .pm-port-out"
    ).bounding_box()
    input_box = page.locator(
        f".pm-node[data-node-id='{to_id}'] .pm-port-in"
    ).bounding_box()
    viewport_box = page.locator(".pm-viewport").bounding_box()
    assert output_box is not None and input_box is not None and viewport_box is not None
    start = {
        "x": output_box["x"] + output_box["width"] / 2,
        "y": output_box["y"] + output_box["height"] / 2,
    }
    end = {
        "x": input_box["x"] + input_box["width"] / 2,
        "y": input_box["y"] + input_box["height"] / 2,
    }
    center_y = (start["y"] + end["y"]) / 2
    preferred_sign = 1 if center_y < viewport_box["y"] + viewport_box["height"] / 2 else -1
    screen_points = None
    for signed_offset in (
        preferred_sign * 90,
        preferred_sign * 150,
        preferred_sign * 220,
        preferred_sign * -90,
        preferred_sign * -150,
    ):
        route_y = max(
            viewport_box["y"] + 50,
            min(viewport_box["y"] + viewport_box["height"] - 50, center_y + signed_offset),
        )
        candidates = [
            {"x": start["x"] + (end["x"] - start["x"]) * 0.34, "y": route_y},
            {
                "x": start["x"] + (end["x"] - start["x"]) * 0.68,
                "y": route_y + (28 if signed_offset > 0 else -28),
            },
        ]
        unobstructed = page.evaluate(
            """points => points.every(point => {
                const target = document.elementFromPoint(point.x, point.y);
                return target && !target.closest(
                    '.pm-node, .pm-junction, button, input, select, textarea, '
                    + '.pm-group-header, .pm-group-resize'
                );
            })""",
            candidates,
        )
        if unobstructed:
            screen_points = candidates
            break
    assert screen_points is not None
    page.locator(
        f".pm-node[data-node-id='{from_id}'] .pm-port-out"
    ).dispatch_event(
        "pointerdown",
        {"button": 0, "clientX": start["x"], "clientY": start["y"], "pointerId": 501},
    )
    for index, point in enumerate(screen_points):
        page.locator(".pm-viewport").dispatch_event(
            "pointermove",
            {
                "button": 0,
                "clientX": point["x"],
                "clientY": point["y"],
                "pointerId": 502 + index,
            },
        )
        page.locator(".pm-viewport").dispatch_event(
            "pointerdown",
            {
                "button": 0,
                "clientX": point["x"],
                "clientY": point["y"],
                "pointerId": 502 + index,
            },
        )
    page.locator(
        f".pm-node[data-node-id='{to_id}'] .pm-port-in"
    ).dispatch_event(
        "pointerdown",
        {"button": 0, "clientX": end["x"], "clientY": end["y"], "pointerId": 510},
    )
    return screen_points


def _edge_screen_point(page, edge_id: str, fraction: float = 0.5) -> dict:
    return page.locator(f".pm-edge-hit[data-edge-id='{edge_id}']").evaluate(
        """(path, fraction) => {
            const point = path.getPointAtLength(path.getTotalLength() * fraction);
            const matrix = path.getScreenCTM();
            return {
                x: matrix.a * point.x + matrix.c * point.y + matrix.e,
                y: matrix.b * point.x + matrix.d * point.y + matrix.f,
            };
        }""",
        fraction,
    )


def _drag_connection_to_edge(page, from_id: str, edge_id: str, fraction: float = 0.5) -> dict:
    page.evaluate("window.__processMapFlow.editor.setCanvasInteractionMode('select')")
    output_box = page.locator(f".pm-node[data-node-id='{from_id}'] .pm-port-out").bounding_box()
    target = _edge_screen_point(page, edge_id, fraction)
    assert output_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(target["x"], target["y"], steps=10)
    preview = {
        "dot": page.locator(".pm-junction-preview").count(),
        "highlight": page.locator(f".pm-edge.branch-target[data-edge-id='{edge_id}']").count(),
    }
    page.mouse.up()
    return preview


def _drag_connection_to_junction(page, from_id: str, junction_id: str) -> None:
    page.evaluate("window.__processMapFlow.editor.setCanvasInteractionMode('select')")
    output_box = page.locator(f".pm-node[data-node-id='{from_id}'] .pm-port-out").bounding_box()
    junction_box = page.locator(f".pm-junction[data-node-id='{junction_id}']").bounding_box()
    assert output_box is not None and junction_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(junction_box["x"] + junction_box["width"] / 2, junction_box["y"] + junction_box["height"] / 2, steps=8)
    page.mouse.up()


def _drag_connection_from_junction(page, junction_id: str, to_id: str) -> None:
    page.evaluate("window.__processMapFlow.editor.setCanvasInteractionMode('select')")
    junction = page.locator(f".pm-junction[data-node-id='{junction_id}']")
    junction.hover()
    output_box = junction.locator(".pm-junction-handle").bounding_box()
    input_box = page.locator(f".pm-node[data-node-id='{to_id}'] .pm-port-in").bounding_box()
    assert output_box is not None and input_box is not None
    page.mouse.move(output_box["x"] + output_box["width"] / 2, output_box["y"] + output_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(input_box["x"] + input_box["width"] / 2, input_box["y"] + input_box["height"] / 2, steps=8)
    page.mouse.up()


def _position_card_in_viewport(
    page,
    node_id: str,
    x_ratio: float,
    y_ratio: float,
    scale: float,
) -> None:
    page.evaluate(
        """({ nodeId, xRatio, yRatio, scale }) => {
            const editor = window.__processMapFlow.editor;
            const viewport = editor.viewport.getBoundingClientRect();
            const position = editor.positions[nodeId];
            const centerX = position.x + position.width / 2;
            const centerY = position.y + position.height / 2;
            editor.transform.scale = scale;
            editor.transform.x = viewport.width * xRatio - centerX * scale;
            editor.transform.y = viewport.height * yRatio - centerY * scale;
            editor.applyTransform();
        }""",
        {
            "nodeId": node_id,
            "xRatio": x_ratio,
            "yRatio": y_ratio,
            "scale": scale,
        },
    )
    page.wait_for_timeout(120)


def _toolbar_geometry(page, node_id: str) -> dict:
    return page.evaluate(
        """nodeId => {
            const compact = element => {
                const value = element.getBoundingClientRect();
                return {
                    x: value.x,
                    y: value.y,
                    width: value.width,
                    height: value.height,
                    right: value.right,
                    bottom: value.bottom,
                };
            };
            const overlaps = (left, right) => !(
                left.right <= right.x || right.right <= left.x
                || left.bottom <= right.y || right.bottom <= left.y
            );
            const toolbarElement = document.querySelector('.pm-card-toolbar');
            const node = document.querySelector(`.pm-node[data-node-id="${nodeId}"]`);
            const inputElement = node.querySelector(':scope > .pm-port-in');
            const outputElement = node.querySelector(':scope > .pm-port-out');
            const toolbar = compact(toolbarElement);
            const card = compact(node);
            const input = compact(inputElement);
            const output = compact(outputElement);
            const viewport = compact(window.__processMapFlow.editor.viewport);
            const placement = toolbarElement.dataset.placement || '';
            const style = getComputedStyle(toolbarElement);
            return {
                toolbar,
                card,
                input,
                output,
                viewport,
                placement,
                onScreen: toolbar.x >= 11 && toolbar.y >= 11
                    && toolbar.right <= window.innerWidth - 11
                    && toolbar.bottom <= window.innerHeight - 11,
                withinViewport: toolbar.x >= viewport.x + 11
                    && toolbar.y >= viewport.y + 11
                    && toolbar.right <= viewport.right - 11
                    && toolbar.bottom <= viewport.bottom - 11,
                overlapsInput: overlaps(toolbar, input),
                overlapsOutput: overlaps(toolbar, output),
                horizontalCenterError: Math.abs(
                    toolbar.x + toolbar.width / 2 - (card.x + card.width / 2)
                ),
                verticalCenterError: Math.abs(
                    toolbar.y + toolbar.height / 2 - (card.y + card.height / 2)
                ),
                backgroundColor: style.backgroundColor,
                color: style.color,
                borderColor: style.borderColor,
                animationName: style.animationName,
            };
        }""",
        node_id,
    )


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {"url": APP_URL, "checks": {}, "page_errors": []}

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        live_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        live_page = live_context.new_page()
        _install_cached_three_route(live_page)
        live_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        live_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(live_page)
        live_payload = live_page.evaluate(
            """async () => (await (await fetch('/api/training/process-map/racing-bike')).json())"""
        )
        record(
            "live_catalog_and_saved_placements_remain_separate",
            live_payload["map"]["schemaVersion"] == 3
            and len(live_payload["productStructure"]["occurrences"]) > 0
            and live_page.locator(".pm-node, .pm-junction").count()
            == len(live_payload["map"]["canvasNodes"])
            and (
                live_page.locator(".pm-empty-state:visible").count() == 1
            ) == (len(live_payload["map"]["canvasNodes"]) == 0),
            {
                "canvasNodes": len(live_payload["map"]["canvasNodes"]),
                "sourceOccurrences": len(live_payload["productStructure"]["occurrences"]),
            },
        )
        record(
            "solidworks_style_source_tree_is_separate_from_canvas",
            live_page.locator(".pm-structure-sidebar").count() == 1
            and live_page.locator(".pm-tree-row").count() > 0,
        )
        palettes = {}
        viewport_surfaces = {}
        for theme in ("light", "dark"):
            live_page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
            palettes[theme] = live_page.locator(".pm-structure-sidebar").evaluate(
                "el => { const s = getComputedStyle(el); return { body: s.getPropertyValue('--cad-folder-body').trim(), tab: s.getPropertyValue('--cad-folder-tab').trim(), stroke: s.getPropertyValue('--cad-folder-stroke').trim() }; }"
            )
            viewport_surfaces[theme] = live_page.locator(".pm-viewport").evaluate(
                "el => { const base = getComputedStyle(el); const dots = getComputedStyle(el, '::before'); return { base: base.backgroundImage, dots: dots.backgroundImage, dotSize: dots.backgroundSize }; }"
            )
            live_page.screenshot(
                path=str(OUT_DIR / f"process_flow_source_tree_{theme}.png"),
                full_page=False,
            )
        record(
            "folder_palette_is_shared_and_visible_in_both_themes",
            palettes["light"] == palettes["dark"]
            and palettes["dark"] == {"body": "#e2a52e", "tab": "#ffd166", "stroke": "#6b4a12"},
            palettes,
        )
        record(
            "flow_viewport_uses_cad_surface_with_dot_field",
            all(
                "gradient" in viewport_surfaces[theme]["base"]
                and "radial-gradient" in viewport_surfaces[theme]["dots"]
                and viewport_surfaces[theme]["dotSize"] == "22px 22px"
                for theme in ("light", "dark")
            ),
            viewport_surfaces,
        )
        spatial_runtime = live_page.evaluate(
            """async () => {
                const runtime = window.InspectorProProcessMapSpatial;
                if (!runtime) return { available: false };
                const contract = await runtime.loadSpatialContract();
                const transform = { x: 88, y: -40, scale: 0.28 };
                const source = { x: 410.5, y: -23.25 };
                const viewport = runtime.worldToViewport(source, transform);
                const restored = runtime.viewportToWorld(viewport, transform);
                return {
                    available: true,
                    contractId: runtime.CONTRACT_ID,
                    envelopeMatchesEditor:
                        contract.geometry.nodeEnvelopes.default.width
                            === window.InspectorProProcessMap.NODE_WIDTH
                        && contract.geometry.nodeEnvelopes.default.height
                            === window.InspectorProProcessMap.NODE_HEIGHT
                        && contract.geometry.junction.hitDiameter
                            === window.InspectorProProcessMap.JUNCTION_HIT_SIZE,
                    delta: Math.max(
                        Math.abs(restored.x - source.x),
                        Math.abs(restored.y - source.y)
                    ),
                };
            }"""
        )
        record(
            "shared_spatial_runtime_is_loaded_and_coordinate_stable",
            spatial_runtime.get("available") is True
            and spatial_runtime.get("contractId") == "process-map-spatial-contract-v1"
            and spatial_runtime.get("envelopeMatchesEditor") is True
            and spatial_runtime.get("delta", 1) < 1e-9,
            spatial_runtime,
        )
        live_context.close()

        fallback_context = browser.new_context(viewport={"width": 1400, "height": 900})
        fallback_page = fallback_context.new_page()
        _install_cached_three_route(fallback_page)
        fallback_page.route(
            "**/api/training/process-map/racing-bike",
            lambda route: route.fulfill(status=404, content_type="application/json", body='{"detail":"disabled"}'),
        )
        fallback_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        fallback_page.locator(".tab[data-tab='training']").click()
        fallback_page.wait_for_selector("#trainingTypeRibbonSelect")
        fallback_page.locator("#trainingTypeRibbonSelect").select_option("assembly")
        fallback_page.wait_for_selector("[data-training-process-map-state='unavailable']")
        record(
            "unavailable_flow_does_not_restore_legacy_structure",
            fallback_page.locator("[data-training-product-structure-diagram]").count() == 0
            and fallback_page.locator("[data-training-open-process-flow]").count() == 0
            and fallback_page.locator("[data-training-process-map-state='unavailable']").count() == 1,
        )
        fallback_context.close()

        store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        analysis_requests: list[dict] = []
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        _install_cached_three_route(page)
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(page, store)
        _install_synthetic_map_management_routes(page, store)
        _install_synthetic_suggestion_route(page, store)
        _install_synthetic_agent_route(page, store, analysis_requests)
        page.route(
            "**/api/training/process-map-spatial-placement-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": True}),
            ),
        )
        page.route(
            "**/api/training/process-map-spatial-analysis-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": True}),
            ),
        )
        page.route(
            "**/api/training/process-map-auto-routing-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        page.route(
            "**/api/training/process-map-agent-layout-write-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(page)

        record(
            "loading_and_expanding_tree_creates_no_canvas_nodes",
            page.locator(".pm-node").count() == 0,
        )
        initial_sidebar = page.locator(".pm-structure-sidebar").bounding_box()
        initial_divider = page.locator(".ip-pane-divider").bounding_box()
        initial_toggle = page.get_by_role("button", name="Collapse pane").bounding_box()
        initial_resize_hit = page.locator(".ip-pane-divider-resize").bounding_box()
        toggle_face = page.get_by_role("button", name="Collapse pane").evaluate(
            "el => { const s = getComputedStyle(el, '::before'); "
            "return { width: parseFloat(s.width), height: parseFloat(s.height), "
            "left: parseFloat(s.left) }; }"
        )
        record(
            "solidworks_splitter_toggle_is_attached_and_vertically_centered",
            initial_sidebar is not None
            and initial_divider is not None
            and initial_toggle is not None
            and initial_resize_hit is not None
            and initial_divider["width"] <= 2
            and initial_resize_hit["width"] >= 8
            and toggle_face["width"] <= 16
            and toggle_face["height"] >= 40
            and toggle_face["left"] <= 1
            and abs(
                initial_sidebar["x"] + initial_sidebar["width"]
                - initial_divider["x"]
            ) < 2
            and abs(initial_toggle["x"] - initial_divider["x"]) < 2
            and abs(
                initial_toggle["y"] + initial_toggle["height"] / 2
                - (initial_divider["y"] + initial_divider["height"] / 2)
            ) < 2
            and page.locator(".pm-workspace > .pm-structure-toggle").count() == 0,
            {
                "sidebar": initial_sidebar,
                "divider": initial_divider,
                "toggle": initial_toggle,
                "resizeHit": initial_resize_hit,
                "toggleFace": toggle_face,
            },
        )
        resize_hit = page.locator(".ip-pane-divider-resize")
        resize_box = resize_hit.bounding_box()
        assert resize_box is not None and initial_sidebar is not None
        resize_y = resize_box["y"] + min(80, resize_box["height"] / 4)
        page.mouse.move(resize_box["x"] + resize_box["width"] / 2, resize_y)
        page.mouse.down()
        page.mouse.move(resize_box["x"] + resize_box["width"] / 2 + 40, resize_y)
        page.mouse.up()
        resized_sidebar = page.locator(".pm-structure-sidebar").bounding_box()
        expanded_viewport = page.locator(".pm-viewport").bounding_box()
        record(
            "splitter_drag_resizes_without_collapsing_or_changing_graph_state",
            resized_sidebar is not None
            and resized_sidebar["width"] > initial_sidebar["width"] + 30
            and not page.locator(".pm-editor").evaluate(
                "el => el.classList.contains('structure-collapsed')"
            )
            and page.locator(".pm-node").count() == 0,
            {"before": initial_sidebar, "after": resized_sidebar},
        )
        page.get_by_role("button", name="Collapse pane").click()
        page.wait_for_selector(".pm-editor.structure-collapsed")
        page.wait_for_timeout(220)
        collapsed_viewport = page.locator(".pm-viewport").bounding_box()
        record(
            "assembly_tree_collapses_to_the_divider_without_changing_graph_state",
            expanded_viewport is not None
            and collapsed_viewport is not None
            and collapsed_viewport["x"] < expanded_viewport["x"] - 200
            and page.locator(".pm-structure-sidebar").get_attribute("aria-hidden") == "true"
            and page.locator(".pm-structure-sidebar").get_attribute("inert") is not None
            and page.get_by_role("button", name="Expand pane").get_attribute("aria-expanded") == "false"
            and page.locator(".ip-pane-divider.is-collapsed").count() == 1
            and page.locator(".pm-node").count() == 0,
            {"expanded": expanded_viewport, "collapsed": collapsed_viewport},
        )
        page.locator(".tab[data-tab='drawing']").click()
        page.locator(".tab[data-tab='training']").click()
        page.wait_for_selector("[data-process-flow-editor='true'].structure-collapsed")
        record(
            "assembly_tree_collapse_state_survives_training_tab_remount",
            page.get_by_role("button", name="Expand pane").count() == 1
            and page.locator(".pm-node").count() == 0,
        )
        page.get_by_role("button", name="Expand pane").click()
        page.wait_for_function(
            "!document.querySelector('[data-process-flow-editor=true]').classList.contains('structure-collapsed')"
        )
        page.wait_for_timeout(220)
        restored_viewport = page.locator(".pm-viewport").bounding_box()
        restored_sidebar = page.locator(".pm-structure-sidebar").bounding_box()
        record(
            "assembly_tree_expands_at_its_last_width_without_relaying_out_the_map",
            expanded_viewport is not None
            and restored_viewport is not None
            and abs(restored_viewport["x"] - expanded_viewport["x"]) < 2
            and resized_sidebar is not None
            and restored_sidebar is not None
            and abs(restored_sidebar["width"] - resized_sidebar["width"]) < 2
            and page.locator(".pm-node").count() == 0,
            {
                "expanded": expanded_viewport,
                "restored": restored_viewport,
                "resizedSidebar": resized_sidebar,
                "restoredSidebar": restored_sidebar,
            },
        )
        page.get_by_role("button", name="Collapse pane").press("Space")
        page.wait_for_selector(".pm-editor.structure-collapsed")
        page.get_by_role("button", name="Expand pane").press("Enter")
        page.wait_for_function(
            "!document.querySelector('[data-process-flow-editor=true]').classList.contains('structure-collapsed')"
        )
        record(
            "splitter_toggle_supports_space_and_enter",
            page.get_by_role("button", name="Collapse pane").get_attribute("aria-expanded") == "true",
        )
        page.evaluate(
            "window.__processMapFlow.setRequiredOccurrenceScope('module-b', 'Module B')"
        )
        page.evaluate(
            "window._dispatchUiAction('process_map', {"
            "type: 'set_process_map_part_scope', "
            "scope_occurrence_id: 'module-a', label: 'Untrusted Label'})"
        )
        required_state = page.evaluate(
            "window.__processMapFlow.requiredOccurrenceSelection"
        )
        record(
            "agent_scope_replaces_previous_result_and_expands_only_matching_paths",
            required_state is not None
            and required_state["scopeOccurrenceId"] == "module-a"
            and required_state["label"] == "Module A"
            and required_state["requiredOccurrenceIds"] == ["part-a-1", "part-a-2"]
            and page.locator(".pm-tree-row.agent-required").count() == 2
            and page.locator(".pm-tree-row[data-occurrence-id='part-b'].agent-required").count() == 0
            and page.locator(".pm-tree-row[data-occurrence-id='module-a']").get_attribute("aria-expanded") == "true"
            and page.evaluate("window.__processMapFlow.editor.dirty") is False
            and page.locator(".pm-node").count() == 0,
            required_state,
        )
        summary = page.locator(".pm-required-summary")
        record(
            "required_part_summary_reports_progress_and_navigation",
            summary.get_attribute("data-required-total") == "2"
            and summary.get_attribute("data-required-placed") == "0"
            and summary.get_attribute("data-required-remaining") == "2"
            and page.get_by_role("button", name="Previous required part").count() == 1
            and page.get_by_role("button", name="Next required part").count() == 1
            and page.get_by_role(
                "button", name="Preview all remaining required parts in an organized layout"
            ).count() == 1
            and page.get_by_role("button", name="Clear required-part highlights").count() == 1,
        )
        map_before_batch = page.evaluate(
            "JSON.stringify(window.__processMapFlow.editor.processMap)"
        )
        page.get_by_role(
            "button", name="Preview all remaining required parts in an organized layout"
        ).click()
        page.wait_for_function(
            "window.__processMapFlow.editor.batchPlacementPlan"
            " && document.querySelectorAll('.pm-batch-placement-ghost').length === 2"
        )
        batch_preview = page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const entries = editor.batchPlacementPlan.entries;
                return {
                    nodeCount: editor.processMap.canvasNodes.length,
                    dirty: editor.dirty,
                    historyDepth: editor.history.undoStack.length,
                    positions: entries.map(entry => ({
                        id: entry.sourceOccurrenceId,
                        x: entry.candidate.position.x,
                        y: entry.candidate.position.y,
                    })),
                };
            }"""
        )
        first_preview, second_preview = batch_preview["positions"]
        previews_overlap = not (
            first_preview["x"] + 270 < second_preview["x"]
            or second_preview["x"] + 270 < first_preview["x"]
            or first_preview["y"] + 146 < second_preview["y"]
            or second_preview["y"] + 146 < first_preview["y"]
        )
        record(
            "phase5_required_parts_batch_is_preview_only_and_overlap_free",
            batch_preview["nodeCount"] == 0
            and batch_preview["dirty"] is False
            and batch_preview["historyDepth"] == 0
            and not previews_overlap
            and page.evaluate("JSON.stringify(window.__processMapFlow.editor.processMap)")
                == map_before_batch,
            batch_preview,
        )
        page.screenshot(
            path=str(OUT_DIR / "process_flow_required_parts_batch_preview.png"),
            full_page=False,
        )
        page.get_by_role(
            "button", name="Add every previewed required part as one undoable change"
        ).click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 2"
            " && !window.__processMapFlow.editor.batchPlacementPlan"
        )
        record(
            "phase5_required_parts_batch_commits_atomically_in_one_history_entry",
            page.evaluate("window.__processMapFlow.editor.history.undoStack.length") == 1
            and page.locator(".pm-batch-placement-ghost").count() == 0
            and page.locator(".pm-required-summary").get_attribute("data-required-placed") == "2",
        )
        page.evaluate("window.__processMapFlow.editor.undo()")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 0"
        )
        record(
            "phase5_one_undo_restores_the_exact_pre_batch_map",
            page.evaluate("JSON.stringify(window.__processMapFlow.editor.processMap)")
                == map_before_batch
            and page.locator(".pm-required-summary").get_attribute("data-required-placed") == "0",
        )
        page.screenshot(
            path=str(OUT_DIR / "process_flow_required_parts.png"),
            full_page=False,
        )
        page.get_by_role("button", name="Next required part").click()
        record(
            "required_part_navigation_moves_one_stable_tree_focus",
            page.locator(".pm-tree-row.agent-required-current").count() == 1
            and page.locator(
                ".pm-tree-row[data-occurrence-id='part-a-2'].agent-required-current"
            ).count() == 1,
        )
        page.locator(".tab[data-tab='drawing']").click()
        page.locator(".tab[data-tab='training']").click()
        page.wait_for_selector("[data-process-flow-editor='true']")
        record(
            "required_part_result_survives_process_map_remount",
            page.locator(".pm-tree-row.agent-required").count() == 2
            and page.locator(".pm-required-summary").get_attribute("data-required-total") == "2",
        )
        _expand(page, "module-a")
        record(
            "assemblies_and_subassemblies_expand_independently",
            page.locator(".pm-tree-row[data-occurrence-id='part-a-1']").count() == 1
            and page.locator(".pm-node").count() == 0,
        )

        viewport_box = page.locator(".pm-viewport").bounding_box()
        assert viewport_box is not None
        first_target = {"x": 330.0, "y": 260.0}
        _drag_tree_item(page, "part-a-1", first_target["x"], first_target["y"])
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 1")
        first_id = page.evaluate("window.__processMapFlow.editor.processMap.canvasNodes[0].nodeId")
        first_box = page.locator(f".pm-node[data-node-id='{first_id}']").bounding_box()
        assert first_box is not None
        record(
            "tree_drop_creates_card_at_release_position",
            abs((first_box["x"] + first_box["width"] / 2) - (viewport_box["x"] + first_target["x"])) < 12
            and abs((first_box["y"] + first_box["height"] / 2) - (viewport_box["y"] + first_target["y"])) < 12,
            {"card": first_box, "viewport": viewport_box, "target": first_target},
        )
        record(
            "placing_required_part_updates_progress_and_completion_state",
            page.locator(".pm-required-summary").get_attribute("data-required-placed") == "1"
            and page.locator(".pm-required-summary").get_attribute("data-required-remaining") == "1"
            and page.locator(
                ".pm-tree-row[data-occurrence-id='part-a-1'].agent-required-complete"
            ).count() == 1
            and page.locator(
                ".pm-tree-row[data-occurrence-id='part-a-1'] .pm-tree-required-complete"
            ).count() == 1,
        )
        page.get_by_role("button", name="Clear required-part highlights").click()
        record(
            "clearing_required_parts_keeps_placed_cards_and_normal_tree_state",
            page.locator(".pm-required-summary:visible").count() == 0
            and page.locator(".pm-tree-row.agent-required").count() == 0
            and page.locator(".pm-node").count() == 1,
        )
        _expand(page, "module-a")
        record(
            "placed_tree_occurrence_is_marked",
            page.locator(".pm-tree-row[data-occurrence-id='part-a-1'] .pm-tree-placed").count() == 1,
        )
        compact_card = page.evaluate(
            """nodeId => {
                const node = document.querySelector(`.pm-node[data-node-id="${nodeId}"]`);
                const card = node && node.querySelector('.pm-node-card');
                const strip = card && card.querySelector('.train-diagram-thumb-strip');
                const thumb = strip && strip.querySelector('.train-diagram-thumb');
                return node && card ? {
                    width: node.offsetWidth,
                    height: node.offsetHeight,
                    clientWidth: card.clientWidth,
                    clientHeight: card.clientHeight,
                    scrollWidth: card.scrollWidth,
                    scrollHeight: card.scrollHeight,
                    previewTrigger: !!card.querySelector('.pm-preview-trigger'),
                    singlePreviewUsesRow: !!strip && !!thumb
                        && strip.classList.contains('single')
                        && thumb.offsetWidth >= strip.clientWidth - 2,
                } : null;
            }""",
            first_id,
        )
        record(
            "placed_cards_use_compact_geometry_without_clipping_content",
            compact_card is not None
            and compact_card["width"] == 270
            and compact_card["height"] == 146
            and compact_card["scrollWidth"] <= compact_card["clientWidth"] + 1
            and compact_card["scrollHeight"] <= compact_card["clientHeight"] + 1
            and compact_card["previewTrigger"] is True
            and compact_card["singlePreviewUsesRow"] is True,
            compact_card,
        )

        page.get_by_role(
            "button", name="Ask Sage to analyze the saved process flow"
        ).click()
        deadline = time.time() + 15
        while not analysis_requests and time.time() < deadline:
            page.wait_for_timeout(50)
        analysis_payload = analysis_requests[-1] if analysis_requests else {}
        analysis_attachments = (
            analysis_payload.get("inspection_context", {}).get("attachments", {})
        )
        process_map_reference = analysis_attachments.get("process_map", {})
        record(
            "analyze_saves_dirty_map_before_one_sage_turn",
            len(analysis_requests) == 1
            and store["putCount"] == 1
            and [event.get("kind") for event in store["events"][-2:]]
            == ["save", "agent"]
            and page.evaluate("window.__processMapFlow.editor.dirty") is False,
            {"events": store["events"], "requests": len(analysis_requests)},
        )
        record(
            "analyze_sends_identity_and_whitelisted_live_state_not_browser_graph",
            {
                key: process_map_reference.get(key)
                for key in ("productId", "mapId", "revision")
            } == {
                "productId": "racing-bike",
                "mapId": "default",
                "revision": "rev-2",
            }
            and set(process_map_reference) == {
                "productId", "mapId", "revision", "state", "receipts"
            }
            and set(process_map_reference.get("state", {})) == {
                "dirty", "conflict", "editable", "selection", "agentFocus",
                "activeProposal"
            }
            and process_map_reference["state"]["dirty"] is False
            and process_map_reference["state"]["conflict"] is False
            and process_map_reference["state"]["editable"] is True
            and process_map_reference["state"]["agentFocus"] is None
            and process_map_reference["state"]["activeProposal"] is None
            and process_map_reference.get("receipts") == []
            and analysis_attachments.get("session", {}).get("active_mode") == "training"
            and "process_map_graph" not in json.dumps(analysis_payload)
            and "process_map_digest" not in json.dumps(analysis_payload),
            process_map_reference,
        )
        page.evaluate(
            """() => {
                if (window._agentPanel && window._agentPanel.classList.contains('open')
                    && window._toggleAgentPanel) {
                    window._toggleAgentPanel();
                }
            }"""
        )
        page.wait_for_timeout(400)

        page.get_by_role(
            "button", name="Ask Sage to analyze card and wire layout"
        ).click()
        deadline = time.time() + 15
        while len(analysis_requests) < 2 and time.time() < deadline:
            page.wait_for_timeout(50)
        layout_payload = analysis_requests[-1] if len(analysis_requests) >= 2 else {}
        layout_reference = (
            layout_payload.get("inspection_context", {})
            .get("attachments", {})
            .get("process_map", {})
        )
        record(
            "layout_analysis_is_one_read_only_saved_revision_turn",
            len(analysis_requests) == 2
            and store["putCount"] == 1
            and {
                key: layout_reference.get(key)
                for key in ("productId", "mapId", "revision")
            } == {
                "productId": "racing-bike",
                "mapId": "default",
                "revision": "rev-2",
            }
            and set(layout_reference) == {
                "productId", "mapId", "revision", "state", "receipts"
            }
            and layout_reference.get("state", {}).get("dirty") is False
            and layout_reference.get("state", {}).get("conflict") is False
            and layout_reference.get("receipts") == []
            and "Analyze only the spatial layout" in layout_payload.get("message", "")
            and "Do not change the map" in layout_payload.get("message", "")
            and "process_map_graph" not in json.dumps(layout_payload)
            and "spatial_scene" not in json.dumps(layout_payload),
            {
                "requests": len(analysis_requests),
                "putCount": store["putCount"],
                "reference": layout_reference,
            },
        )
        page.evaluate(
            """() => {
                if (window._agentPanel && window._agentPanel.classList.contains('open')
                    && window._toggleAgentPanel) {
                    window._toggleAgentPanel();
                }
            }"""
        )
        page.wait_for_timeout(400)

        page.evaluate("window.__processMapEditorBeforePreview = window.__processMapFlow.editor")
        first_card = page.locator(f".pm-node[data-node-id='{first_id}'] .pm-node-card")
        first_card_select_target = first_card.locator(".train-diagram-card-title")
        first_card_select_target.click()
        page.wait_for_selector(".pm-card-toolbar")
        record(
            "selecting_card_opens_actions_without_opening_preview",
            page.locator(".pm-card-toolbar").count() == 1
            and page.locator("#trainUniquePreviewShell.open").count() == 0,
        )
        record(
            "context_toolbar_prioritizes_frequent_card_actions",
            page.locator(".pm-card-toolbar [data-card-command='add-step']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='edit-label']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='edit-note']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='preview']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='delete']").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='orientation']").count() == 0
            and page.locator(".pm-card-toolbar [data-card-command='port-order']").count() == 0,
        )

        page.locator(".pm-card-toolbar [data-card-command='edit-label']").click()
        label_field = page.locator(".pm-card-toolbar [data-card-editor-field='label']")
        label_field.fill("Primary seat shell")
        label_field.press("Enter")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).labelOverride === 'Primary seat shell'",
            arg=first_id,
        )
        record(
            "edit_label_updates_only_the_placed_card",
            "Primary seat shell" in first_card.inner_text()
            and page.locator(".pm-tree-row[data-occurrence-id='part-a-1'] .pm-tree-name").inner_text()
            == "Repeated Part A",
        )

        page.locator(".pm-card-toolbar [data-card-command='edit-note']").click()
        note_field = page.locator(".pm-card-toolbar [data-card-editor-field='note']")
        note_field.fill("Verify the seating surface before the inspection step.")
        note_field.press("Control+Enter")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).note === "
            "'Verify the seating surface before the inspection step.'",
            arg=first_id,
        )
        record(
            "card_note_is_visible_and_persisted_in_map_state",
            page.locator(f".pm-node[data-node-id='{first_id}'] .pm-node-note-indicator").count() == 1
            and page.locator(".pm-card-toolbar [data-card-command='edit-note']").get_attribute("aria-pressed") == "true",
        )

        page.locator(".pm-card-toolbar [data-context-command='references']").click()
        page.wait_for_selector(".pm-card-toolbar-editor[data-editor-mode='references']")
        page.locator("[data-reference-kind]").select_option("machine")
        page.locator("[data-reference-field='name']").fill("Five-axis machining center")
        page.locator("[data-reference-field='identifier']").fill("MC-01")
        page.get_by_role("button", name="Attach reference").click()
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).referenceIds.length === 1",
            arg=first_id,
        )
        record(
            "card_context_can_attach_machine_reference",
            page.locator(
                f".pm-node[data-node-id='{first_id}'] .pm-reference-badge-machine"
            ).inner_text() == "M 1"
            and page.evaluate(
                "window.__processMapFlow.editor.processMap.referenceCatalog[0].identifier"
            ) == "MC-01",
        )
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        page.wait_for_timeout(500)
        page.screenshot(
            path=str(OUT_DIR / "process_flow_card_references_light.png"),
            full_page=False,
        )
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
        page.get_by_role("button", name="Close reference editor").click()

        page.locator(".pm-card-toolbar [data-card-command='add-step']").select_option("inspection")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 2"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        connected_step_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeKind === 'process_step').nodeId"
        )
        record(
            "add_connected_step_creates_card_and_precedence_edge_together",
            page.evaluate(
                """({ sourceId, stepId }) => {
                    const map = window.__processMapFlow.editor.processMap;
                    return map.canvasEdges.some(edge => edge.from.nodeId === sourceId
                        && edge.to.nodeId === stepId && edge.kind === 'precedence');
                }""",
                {"sourceId": first_id, "stepId": connected_step_id},
            ),
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 0"
        )
        record(
            "one_undo_removes_connected_step_and_its_edge",
            page.locator(f".pm-node[data-node-id='{first_id}']").count() == 1,
        )
        first_card_select_target.click()
        page.wait_for_selector(".pm-card-toolbar")
        page.screenshot(
            path=str(OUT_DIR / "process_flow_card_toolbar.png"),
            full_page=False,
        )

        toolbar_themes = {}
        for theme in ("light", "dark"):
            page.evaluate(
                "theme => document.documentElement.setAttribute('data-theme', theme)",
                theme,
            )
            page.wait_for_timeout(80)
            geometry = _toolbar_geometry(page, first_id)
            toolbar_themes[theme] = {
                "backgroundColor": geometry["backgroundColor"],
                "color": geometry["color"],
                "borderColor": geometry["borderColor"],
            }
            page.screenshot(
                path=str(OUT_DIR / f"process_flow_card_toolbar_{theme}.png"),
                full_page=False,
            )
        record(
            "card_toolbar_uses_readable_theme_tokens_in_both_modes",
            toolbar_themes["light"] != toolbar_themes["dark"]
            and all(
                values["backgroundColor"] not in ("rgba(0, 0, 0, 0)", "transparent")
                and values["color"] not in ("rgba(0, 0, 0, 0)", "transparent")
                for values in toolbar_themes.values()
            ),
            toolbar_themes,
        )
        page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")

        page.emulate_media(reduced_motion="reduce")
        reduced_animation = _toolbar_geometry(page, first_id)["animationName"]
        page.emulate_media(reduced_motion="no-preference")
        record(
            "card_toolbar_honors_reduced_motion",
            reduced_animation == "none",
            reduced_animation,
        )

        scale_geometry = {}
        for scale in (0.28, 1.6):
            _position_card_in_viewport(page, first_id, 0.5, 0.5, scale)
            geometry = _toolbar_geometry(page, first_id)
            scale_geometry[str(scale)] = geometry
        record(
            "card_toolbar_tracks_at_minimum_and_maximum_zoom",
            all(
                geometry["placement"].startswith(("top", "bottom"))
                and geometry["horizontalCenterError"] < 5
                and geometry["withinViewport"]
                and not geometry["overlapsInput"]
                and not geometry["overlapsOutput"]
                for geometry in scale_geometry.values()
            ),
            scale_geometry,
        )

        node_size = page.evaluate(
            "({ width: InspectorProProcessMap.NODE_WIDTH, height: InspectorProProcessMap.NODE_HEIGHT })"
        )
        inset_x = (node_size["width"] / 2 + 6) / viewport_box["width"]
        inset_y = (node_size["height"] / 2 + 6) / viewport_box["height"]
        edge_targets = {
            "top": (0.5, inset_y),
            "right": (1 - inset_x, 0.5),
            "bottom": (0.5, 1 - inset_y),
            "left": (inset_x, 0.5),
        }
        edge_geometry = {}
        for edge_name, (x_ratio, y_ratio) in edge_targets.items():
            _position_card_in_viewport(page, first_id, x_ratio, y_ratio, 1.0)
            edge_geometry[edge_name] = _toolbar_geometry(page, first_id)
        record(
            "flip_and_shift_keep_toolbar_inside_every_viewport_edge",
            all(
                geometry["withinViewport"]
                and geometry["onScreen"]
                and not geometry["overlapsInput"]
                and not geometry["overlapsOutput"]
                for geometry in edge_geometry.values()
            )
            and edge_geometry["top"]["placement"].startswith("bottom")
            and edge_geometry["bottom"]["placement"].startswith("top"),
            edge_geometry,
        )

        page.get_by_role("button", name="Fit flow to viewport").click()
        page.wait_for_timeout(160)
        page.locator(".pm-viewport").click(position={"x": 16, "y": 16})
        page.wait_for_function("!document.querySelector('.pm-card-toolbar')")
        record(
            "outside_canvas_click_dismisses_card_toolbar",
            page.locator(".ip-floating-surface").count() == 0,
        )
        first_card_select_target.click()
        page.wait_for_selector(".pm-card-toolbar")

        drag_state_before = page.evaluate(
            """nodeId => ({
                position: structuredClone(window.__processMapFlow.editor.processMap.canvasNodes
                    .find(node => node.nodeId === nodeId).position),
                undoDepth: window.__processMapFlow.editor.history.undoStack.length,
            })""",
            first_id,
        )
        card_before_drag = first_card.bounding_box()
        drag_handle_before = first_card_select_target.bounding_box()
        toolbar_before_drag = page.locator(".pm-card-toolbar").bounding_box()
        assert card_before_drag is not None and drag_handle_before is not None and toolbar_before_drag is not None
        page.mouse.move(
            drag_handle_before["x"] + drag_handle_before["width"] / 2,
            drag_handle_before["y"] + drag_handle_before["height"] / 2,
        )
        page.mouse.down()
        page.mouse.move(
            drag_handle_before["x"] + drag_handle_before["width"] / 2 + 64,
            drag_handle_before["y"] + drag_handle_before["height"] / 2 + 38,
            steps=7,
        )
        page.mouse.up()
        page.wait_for_timeout(100)
        card_after_drag = first_card.bounding_box()
        toolbar_after_drag = page.locator(".pm-card-toolbar").bounding_box()
        drag_state_after = page.evaluate(
            """nodeId => ({
                position: structuredClone(window.__processMapFlow.editor.processMap.canvasNodes
                    .find(node => node.nodeId === nodeId).position),
                undoDepth: window.__processMapFlow.editor.history.undoStack.length,
            })""",
            first_id,
        )
        assert card_after_drag is not None and toolbar_after_drag is not None
        record(
            "card_toolbar_tracks_selected_card_during_drag",
            abs((card_after_drag["x"] - card_before_drag["x"])
                - (toolbar_after_drag["x"] - toolbar_before_drag["x"])) < 8
            and abs((card_after_drag["y"] - card_before_drag["y"])
                    - (toolbar_after_drag["y"] - toolbar_before_drag["y"])) < 8
            and drag_state_after["position"] != drag_state_before["position"]
            and drag_state_after["undoDepth"] == drag_state_before["undoDepth"] + 1,
            {
                "cardBefore": card_before_drag,
                "cardAfter": card_after_drag,
                "toolbarBefore": toolbar_before_drag,
                "toolbarAfter": toolbar_after_drag,
                "stateBefore": drag_state_before,
                "stateAfter": drag_state_after,
            },
        )
        if drag_state_after["undoDepth"] > drag_state_before["undoDepth"]:
            page.get_by_role("button", name="Undo process-map edit").click()
            page.wait_for_timeout(160)
        else:
            page.evaluate("window.__processMapFlow.editor.renderGraph({ fit: false })")
        first_card_select_target.click()
        page.wait_for_selector(".pm-card-toolbar")

        page.evaluate(
            """() => {
                window.__pmToolbarPreviewOverlap = false;
                if (window.__pmToolbarPreviewObserver) {
                    window.__pmToolbarPreviewObserver.disconnect();
                }
                const observer = new MutationObserver(() => {
                    const shell = document.getElementById('trainUniquePreviewShell');
                    if (shell && shell.classList.contains('open')
                        && document.querySelector('.pm-card-toolbar')) {
                        window.__pmToolbarPreviewOverlap = true;
                    }
                });
                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: ['class'],
                });
                window.__pmToolbarPreviewObserver = observer;
            }"""
        )
        page.locator(".pm-card-toolbar [data-card-command='preview']").click()
        page.wait_for_selector("#trainUniquePreviewShell.open .train-unique-preview-viewer canvas")
        page.wait_for_function(
            "() => { const el = document.querySelector('#trainUniquePreviewShell.open .train-unique-preview-viewer-status'); return el && !el.textContent.toLowerCase().includes('loading'); }",
            timeout=20_000,
        )
        preview_status = page.locator(
            "#trainUniquePreviewShell.open .train-unique-preview-viewer-status"
        ).inner_text()
        page.screenshot(path=str(OUT_DIR / "process_flow_part_3d_preview.png"), full_page=False)
        record(
            "flow_part_card_opens_existing_interactive_3d_viewer",
            page.locator("#trainUniquePreviewBackdrop.open").count() == 1
            and page.locator("#trainUniquePreviewShell.open canvas").count() == 1
            and "interactive 3d" in preview_status.lower(),
            preview_status,
        )
        record(
            "preview_command_closes_toolbar_before_modal_opens",
            page.locator(".pm-card-toolbar").count() == 0
            and page.evaluate("window.__pmToolbarPreviewOverlap === false"),
        )
        page.evaluate(
            """() => {
                if (window.__pmToolbarPreviewObserver) {
                    window.__pmToolbarPreviewObserver.disconnect();
                    window.__pmToolbarPreviewObserver = null;
                }
            }"""
        )
        page.keyboard.press("Escape")
        page.wait_for_function(
            "!document.getElementById('trainUniquePreviewShell').classList.contains('open')"
        )
        page.wait_for_timeout(350)
        record(
            "closing_3d_preview_returns_to_unchanged_flow_canvas",
            page.evaluate(
                "window.__processMapFlow.editor === window.__processMapEditorBeforePreview"
                " && window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            ),
        )

        direct_preview_state = page.evaluate(
            """nodeId => {
                const editor = window.__processMapFlow.editor;
                const node = editor.processMap.canvasNodes.find(item => item.nodeId === nodeId);
                return {
                    position: structuredClone(node.position),
                    undoDepth: editor.history.undoStack.length,
                };
            }""",
            first_id,
        )
        first_card.locator(".pm-preview-trigger").click()
        page.wait_for_selector("#trainUniquePreviewShell.open .train-unique-preview-viewer canvas")
        page.wait_for_function(
            "() => { const el = document.querySelector('#trainUniquePreviewShell.open .train-unique-preview-viewer-status'); return el && !el.textContent.toLowerCase().includes('loading'); }",
            timeout=20_000,
        )
        preview_canvas = page.locator("#trainUniquePreviewShell.open .train-unique-preview-viewer canvas")
        canvas_box = preview_canvas.bounding_box()
        assert canvas_box is not None
        before_orbit = preview_canvas.screenshot()
        canvas_box = preview_canvas.bounding_box()
        assert canvas_box is not None
        before_camera = page.evaluate(
            "trainingState.uniqueItemPreviewViewer.camera.position.toArray()"
        )
        orbit_start = {
            "x": canvas_box["x"] + canvas_box["width"] * 0.46,
            "y": canvas_box["y"] + canvas_box["height"] * 0.48,
        }
        page.mouse.move(
            orbit_start["x"],
            orbit_start["y"],
        )
        page.mouse.down()
        page.mouse.move(
            canvas_box["x"] + canvas_box["width"] * 0.66,
            canvas_box["y"] + canvas_box["height"] * 0.38,
            steps=8,
        )
        page.mouse.up()
        after_orbit = before_orbit
        orbit_deadline = time.time() + 1.5
        while after_orbit == before_orbit and time.time() < orbit_deadline:
            page.wait_for_timeout(100)
            after_orbit = preview_canvas.screenshot()
        after_direct_preview = page.evaluate(
            """nodeId => {
                const editor = window.__processMapFlow.editor;
                const node = editor.processMap.canvasNodes.find(item => item.nodeId === nodeId);
                return {
                    position: structuredClone(node.position),
                    undoDepth: editor.history.undoStack.length,
                };
            }""",
            first_id,
        )
        after_camera = page.evaluate(
            "trainingState.uniqueItemPreviewViewer.camera.position.toArray()"
        )
        camera_moved = any(
            abs(float(before) - float(after)) > 0.0001
            for before, after in zip(before_camera, after_camera)
        )
        record(
            "card_thumbnail_opens_rotatable_3d_preview_without_moving_the_card",
            camera_moved
            and after_direct_preview == direct_preview_state
            and page.locator(".pm-card-toolbar").count() == 0,
            {
                "pixelsChanged": before_orbit != after_orbit,
                "cameraMoved": camera_moved,
                "cameraBefore": before_camera,
                "cameraAfter": after_camera,
                "before": direct_preview_state,
                "after": after_direct_preview,
            },
        )
        page.keyboard.press("Escape")
        page.wait_for_function(
            "!document.getElementById('trainUniquePreviewShell').classList.contains('open')"
        )
        page.wait_for_timeout(350)
        first_card_select_target.click()
        page.wait_for_selector(".pm-card-toolbar")
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('.pm-card-toolbar')")
        record(
            "escape_dismisses_card_toolbar_and_restores_card_focus",
            first_card.evaluate("card => document.activeElement === card"),
        )

        _drag_tree_item(page, "part-a-1", 520, 320)
        record(
            "duplicate_occurrence_drop_selects_without_copying",
            page.evaluate("window.__processMapFlow.editor.processMap.canvasNodes.length") == 1
            and "already on the map" in page.locator(".pm-editor-status").inner_text().lower(),
        )
        _drag_tree_item(page, "part-a-2", 430, 380)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")
        record(
            "same_part_number_with_distinct_occurrences_can_be_placed",
            page.evaluate(
                "new Set(window.__processMapFlow.editor.processMap.canvasNodes.map(n => n.sourceOccurrenceId)).size"
            ) == 2,
        )

        page.mouse.move(viewport_box["x"] + 80, viewport_box["y"] + viewport_box["height"] - 60)
        page.mouse.down(button="middle")
        page.mouse.move(viewport_box["x"] + 150, viewport_box["y"] + viewport_box["height"] - 105, steps=6)
        page.mouse.up(button="middle")
        page.mouse.move(viewport_box["x"] + viewport_box["width"] / 2, viewport_box["y"] + viewport_box["height"] / 2)
        page.mouse.wheel(0, -360)
        _expand(page, "module-b")
        transformed_target = {"x": viewport_box["width"] - 240, "y": viewport_box["height"] - 220}
        _drag_tree_item(page, "part-b", transformed_target["x"], transformed_target["y"])
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 3")
        part_b_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(n => n.sourceOccurrenceId === 'part-b').nodeId"
        )
        part_b_box = page.locator(f".pm-node[data-node-id='{part_b_id}']").bounding_box()
        assert part_b_box is not None
        record(
            "drop_coordinates_remain_correct_after_pan_and_zoom",
            abs((part_b_box["x"] + part_b_box["width"] / 2) - (viewport_box["x"] + transformed_target["x"])) < 14
            and abs((part_b_box["y"] + part_b_box["height"] / 2) - (viewport_box["y"] + transformed_target["y"])) < 14,
        )

        page.locator(
            f".pm-node[data-node-id='{part_b_id}'] .train-diagram-card-title"
        ).click()
        page.wait_for_selector(".pm-card-toolbar")
        page.locator(".pm-card-toolbar [data-card-command='delete']").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")
        record(
            "deleting_card_keeps_tree_source_available",
            page.locator(".pm-tree-row[data-occurrence-id='part-b']").count() == 1
            and page.locator(".pm-tree-row[data-occurrence-id='part-b'] .pm-tree-placed").count() == 0,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 3")

        page.get_by_role("button", name="Add an operation to the center of the process map").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 4")
        page.locator(".pm-type-select").select_option("inspection")
        process_step_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(n => n.nodeKind === 'process_step').nodeId"
        )
        record(
            "authored_process_steps_remain_separate_from_product_tree",
            page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'process_step' && n.processType === 'inspection').length"
            ) == 1,
        )

        canvas_ids = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'product_occurrence').slice(0, 2).map(n => n.nodeId)"
        )
        _drag_connection(page, canvas_ids[0], canvas_ids[1])
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 1")
        trunk_edge_id = page.evaluate("window.__processMapFlow.editor.processMap.canvasEdges[0].edgeId")
        path_before_orientation = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        page.locator(".pm-port-orientation-select").select_option("vertical")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrientation === 'vertical'",
            arg=canvas_ids[1],
        )
        vertical_node = page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
        vertical_box = vertical_node.bounding_box()
        input_box = vertical_node.locator(":scope > .pm-port-in").bounding_box()
        output_box = vertical_node.locator(":scope > .pm-port-out").bounding_box()
        path_after_orientation = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        page.wait_for_timeout(120)
        vertical_toolbar_geometry = _toolbar_geometry(page, canvas_ids[1])
        record(
            "selected_card_ports_switch_from_left_right_to_top_bottom",
            vertical_node.evaluate("node => node.classList.contains('pm-node-ports-vertical')")
            and vertical_box is not None
            and input_box is not None
            and output_box is not None
            and abs((input_box["x"] + input_box["width"] / 2)
                    - (vertical_box["x"] + vertical_box["width"] / 2)) < 2
            and abs((output_box["x"] + output_box["width"] / 2)
                    - (vertical_box["x"] + vertical_box["width"] / 2)) < 2
            and abs((input_box["y"] + input_box["height"] / 2) - vertical_box["y"]) < 2
            and abs((output_box["y"] + output_box["height"] / 2)
                    - (vertical_box["y"] + vertical_box["height"])) < 2
            and path_after_orientation != path_before_orientation,
            {
                "node": vertical_box,
                "input": input_box,
                "output": output_box,
                "pathBefore": path_before_orientation,
                "pathAfter": path_after_orientation,
            },
        )
        record(
            "orientation_aware_toolbar_avoids_vertical_ports",
            vertical_toolbar_geometry["placement"].startswith(("right", "left"))
            and vertical_toolbar_geometry["verticalCenterError"] < 5
            and vertical_toolbar_geometry["withinViewport"]
            and not vertical_toolbar_geometry["overlapsInput"]
            and not vertical_toolbar_geometry["overlapsOutput"],
            vertical_toolbar_geometry,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "nodeId => !window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrientation",
            arg=canvas_ids[1],
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrientation === 'vertical'",
            arg=canvas_ids[1],
        )
        record(
            "card_port_orientation_is_one_undoable_edit",
            page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
            .evaluate("node => node.classList.contains('pm-node-ports-vertical')"),
        )
        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        path_before_order = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        order_select = page.locator(".pm-port-order-select")
        order_labels = order_select.locator("option").all_text_contents()
        order_select.select_option("output_first")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'output_first'",
            arg=canvas_ids[1],
        )
        reversed_node = page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
        reversed_box = reversed_node.bounding_box()
        reversed_input_box = reversed_node.locator(":scope > .pm-port-in").bounding_box()
        reversed_output_box = reversed_node.locator(":scope > .pm-port-out").bounding_box()
        path_after_order = page.locator(
            f".pm-edge[data-edge-id='{trunk_edge_id}']"
        ).get_attribute("d")
        record(
            "vertical_card_can_swap_input_bottom_and_output_top",
            order_labels == ["Input: top", "Input: bottom"]
            and reversed_node.evaluate(
                "node => node.classList.contains('pm-node-port-order-output_first')"
            )
            and reversed_box is not None
            and reversed_input_box is not None
            and reversed_output_box is not None
            and abs((reversed_input_box["y"] + reversed_input_box["height"] / 2)
                    - (reversed_box["y"] + reversed_box["height"])) < 2
            and abs((reversed_output_box["y"] + reversed_output_box["height"] / 2)
                    - reversed_box["y"]) < 2
            and path_after_order != path_before_order,
            {
                "labels": order_labels,
                "node": reversed_box,
                "input": reversed_input_box,
                "output": reversed_output_box,
                "pathBefore": path_before_order,
                "pathAfter": path_after_order,
            },
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "nodeId => !window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder",
            arg=canvas_ids[1],
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'output_first'",
            arg=canvas_ids[1],
        )
        record(
            "card_port_order_is_one_undoable_edit",
            page.locator(f".pm-node[data-node-id='{canvas_ids[1]}']")
            .evaluate("node => node.classList.contains('pm-node-port-order-output_first')"),
        )
        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        page.locator(".pm-port-order-select").select_option("input_first")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'input_first'",
            arg=canvas_ids[1],
        )
        _drag_connection_to_edge(page, process_step_id, trunk_edge_id, 0.995)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 2")
        record(
            "drop_near_wire_endpoint_reuses_existing_node",
            page.evaluate(
                """({ sourceId, targetId }) => {
                    const map = window.__processMapFlow.editor.processMap;
                    return !map.canvasNodes.some(node => node.nodeKind === 'junction')
                        && map.canvasEdges.some(edge => edge.from.nodeId === sourceId && edge.to.nodeId === targetId);
                }""",
                {"sourceId": process_step_id, "targetId": canvas_ids[1]},
            ),
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 1")
        preview = _drag_connection_to_edge(page, part_b_id, trunk_edge_id)
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 3"
        )
        record(
            "wire_target_highlights_and_shows_preview_before_drop",
            preview == {"dot": 1, "highlight": 1},
            preview,
        )
        junction_id = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(n => n.nodeKind === 'junction').nodeId"
        )
        record(
            "junction_selection_never_opens_card_toolbar",
            page.locator(".pm-card-toolbar").count() == 0,
        )
        topology = page.evaluate(
            """({ sourceId, junctionId, trunkId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    originalRemoved: !map.canvasEdges.some(edge => edge.edgeId === trunkId),
                    branch: map.canvasEdges.some(edge => edge.from.nodeId === sourceId && edge.to.nodeId === junctionId),
                    incoming: map.canvasEdges.filter(edge => edge.to.nodeId === junctionId).length,
                    outgoing: map.canvasEdges.filter(edge => edge.from.nodeId === junctionId).length,
                    logicalTrunkSegments: map.canvasEdges.filter(edge => edge.logicalConnectionId === trunkId).length,
                };
            }""",
            {"sourceId": part_b_id, "junctionId": junction_id, "trunkId": trunk_edge_id},
        )
        record(
            "drop_on_wire_creates_persistent_directed_junction_topology",
            topology == {
                "originalRemoved": True,
                "branch": True,
                "incoming": 2,
                "outgoing": 1,
                "logicalTrunkSegments": 2,
            }
            and page.locator(f".pm-junction[data-node-id='{junction_id}']").count() == 1,
            topology,
        )

        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        undo_topology = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].edgeId"
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 3"
        )
        record(
            "junction_split_is_one_atomic_undo_and_redo_action",
            undo_topology == trunk_edge_id,
        )

        branch_edge_id = page.evaluate(
            """({ sourceId, junctionId }) => window.__processMapFlow.editor.processMap.canvasEdges
                .find(edge => edge.from.nodeId === sourceId && edge.to.nodeId === junctionId).edgeId""",
            {"sourceId": part_b_id, "junctionId": junction_id},
        )
        page.locator(f".pm-edge-hit[data-edge-id='{branch_edge_id}']").focus()
        page.keyboard.press("Enter")
        page.get_by_role("button", name="Delete selected card, connection, or group").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        collapsed = page.evaluate(
            """({ fromId, toId }) => {
                const map = window.__processMapFlow.editor.processMap;
                const edge = map.canvasEdges[0];
                return !map.canvasNodes.some(node => node.nodeKind === 'junction')
                    && edge.from.nodeId === fromId && edge.to.nodeId === toId;
            }""",
            {"fromId": canvas_ids[0], "toId": canvas_ids[1]},
        )
        record("deleting_branch_preserves_and_collapses_original_trunk", collapsed)
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 3"
        )

        _drag_connection_to_junction(page, process_step_id, junction_id)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 4")
        record(
            "dropping_near_existing_junction_reuses_it",
            page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.filter(n => n.nodeKind === 'junction').length"
            ) == 1,
        )

        page.get_by_role("button", name="Add an operation to the center of the process map").click()
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 6")
        second_step_id = page.evaluate(
            """existingId => window.__processMapFlow.editor.processMap.canvasNodes
                .find(node => node.nodeKind === 'process_step' && node.nodeId !== existingId).nodeId""",
            process_step_id,
        )
        page.get_by_role("button", name="Fit flow to viewport").click()
        page.wait_for_timeout(160)
        _drag_connection_from_junction(page, junction_id, second_step_id)
        page.wait_for_function("window.__processMapFlow.editor.processMap.canvasEdges.length === 5")
        record(
            "junction_can_start_an_additional_wire",
            page.evaluate(
                """({ junctionId, targetId }) => window.__processMapFlow.editor.processMap.canvasEdges
                    .some(edge => edge.from.nodeId === junctionId && edge.to.nodeId === targetId)""",
                {"junctionId": junction_id, "targetId": second_step_id},
            ),
        )

        junction_before = page.evaluate(
            """junctionId => ({
                position: window.__processMapFlow.editor.processMap.canvasNodes.find(node => node.nodeId === junctionId).position,
                paths: Array.from(document.querySelectorAll('.pm-edge[data-edge-id]'))
                    .filter(path => {
                        const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(item => item.edgeId === path.dataset.edgeId);
                        return edge && (edge.from.nodeId === junctionId || edge.to.nodeId === junctionId);
                    }).map(path => path.getAttribute('d')),
            })""",
            junction_id,
        )
        junction_box = page.locator(f".pm-junction[data-node-id='{junction_id}']").bounding_box()
        assert junction_box is not None
        page.mouse.move(junction_box["x"] + junction_box["width"] / 2, junction_box["y"] + junction_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(junction_box["x"] + junction_box["width"] / 2 + 60, junction_box["y"] + junction_box["height"] / 2 + 45, steps=8)
        page.mouse.up()
        junction_after = page.evaluate(
            """junctionId => ({
                position: window.__processMapFlow.editor.processMap.canvasNodes.find(node => node.nodeId === junctionId).position,
                paths: Array.from(document.querySelectorAll('.pm-edge[data-edge-id]'))
                    .filter(path => {
                        const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(item => item.edgeId === path.dataset.edgeId);
                        return edge && (edge.from.nodeId === junctionId || edge.to.nodeId === junctionId);
                    }).map(path => path.getAttribute('d')),
            })""",
            junction_id,
        )
        record(
            "moving_junction_updates_all_attached_wires",
            junction_after["position"] != junction_before["position"]
            and junction_after["paths"] != junction_before["paths"],
            {"before": junction_before, "after": junction_after},
        )

        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", canvas_ids[1])
        page.locator(".pm-port-order-select").select_option("output_first")
        page.wait_for_function(
            "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === nodeId).portOrder === 'output_first'",
            arg=canvas_ids[1],
        )

        trunk_segment_id = page.evaluate(
            "logicalId => window.__processMapFlow.editor.processMap.canvasEdges"
            ".find(edge => edge.logicalConnectionId === logicalId).edgeId",
            trunk_edge_id,
        )
        page.locator(f".pm-edge-hit[data-edge-id='{trunk_segment_id}']").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector(f".pm-edge-toolbar[data-edge-id='{trunk_segment_id}']")
        page.locator(".pm-edge-toolbar [data-card-command='edge-label']").click()
        edge_label_field = page.locator("[data-card-editor-field='edge-label']")
        edge_label_field.fill("Inspection release")
        edge_label_field.press("Enter")
        page.wait_for_function(
            "edgeId => window.InspectorProProcessMap.logicalEdgeLabel("
            "window.__processMapFlow.editor.processMap, edgeId) === 'Inspection release'",
            arg=trunk_segment_id,
        )
        page.locator(".pm-edge-toolbar [data-context-command='references']").click()
        page.wait_for_selector(".pm-card-toolbar-editor[data-editor-mode='references']")
        page.locator("[data-reference-kind]").select_option("standard")
        page.locator("[data-reference-field='name']").fill("Dimensioning and tolerancing")
        page.locator("[data-reference-field='identifier']").fill("ASME Y14.5")
        page.locator("[data-reference-field='revision']").fill("2018")
        page.locator("[data-reference-field='clause']").fill("7.5")
        page.get_by_role("button", name="Attach reference").click()
        page.wait_for_function(
            "logicalId => window.__processMapFlow.editor.processMap.canvasEdges"
            ".filter(edge => edge.logicalConnectionId === logicalId)"
            ".every(edge => Array.isArray(edge.referenceIds) && edge.referenceIds.length === 1)",
            arg=trunk_edge_id,
        )
        record(
            "wire_context_propagates_standard_across_logical_segments",
            page.evaluate(
                "logicalId => { const edges = window.__processMapFlow.editor.processMap.canvasEdges"
                ".filter(edge => edge.logicalConnectionId === logicalId);"
                " return edges.length === 2 && edges.every(edge => edge.referenceIds.length === 1); }",
                trunk_edge_id,
            )
            and page.locator(".pm-edge-context-label").filter(
                has_text="Inspection release | Std 1"
            ).count() == 1,
        )

        group_setup = page.evaluate(
            """nodeId => {
                const editor = window.__processMapFlow.editor;
                editor.addCanvasGroup();
                const runtime = window.InspectorProProcessMap;
                const group = editor.processMap.canvasGroups.at(-1);
                const node = editor.processMap.canvasNodes.find(item => item.nodeId === nodeId);
                let next = runtime.resizeGroup(editor.processMap, group.groupId, {
                    position: { x: node.position.x - 90, y: node.position.y - 75 },
                    size: { width: 560, height: 340 },
                });
                next = runtime.setGroupMembers(next, group.groupId, [nodeId]);
                editor.commitMutation(next);
                editor.selectGroup(group.groupId);
                return { groupId: group.groupId, nodeId };
            }""",
            first_id,
        )
        group_id = group_setup["groupId"]
        page.wait_for_selector(f".pm-group-frame[data-group-id='{group_id}']")
        page.wait_for_selector(f".pm-group-toolbar[data-group-id='{group_id}']")
        group_member_count = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        )
        page.evaluate(
            "nodeId => window.__processMapFlow.editor.select(nodeId, { openToolbar: false })",
            first_id,
        )
        group_picker = page.get_by_label("Select group frame")
        group_picker.select_option(group_id)
        page.wait_for_function(
            "groupId => window.__processMapFlow.editor.selectedGroupId === groupId",
            arg=group_id,
        )
        record(
            "ribbon_group_picker_selects_frame_and_enables_delete",
            page.locator(f".pm-group-frame[data-group-id='{group_id}'].selected").count() == 1
            and not page.get_by_role(
                "button", name="Delete selected card, connection, or group"
            ).is_disabled()
            and page.locator(
                "[data-process-map-command='processSelectGroup'] img.ribbon-process-icon"
            ).count() == 1,
        )
        page.get_by_role(
            "button", name="Delete selected card, connection, or group"
        ).click()
        page.wait_for_function(
            "groupId => !window.__processMapFlow.editor.processMap.canvasGroups"
            ".some(group => group.groupId === groupId)",
            arg=group_id,
        )
        group_delete_kept_members = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        ) == group_member_count
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "groupId => window.__processMapFlow.editor.processMap.canvasGroups"
            ".some(group => group.groupId === groupId)",
            arg=group_id,
        )
        record(
            "group_picker_delete_removes_only_frame_and_undo_restores_it",
            group_delete_kept_members
            and page.locator(f".pm-group-frame[data-group-id='{group_id}']").count() == 1,
        )
        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.wait_for_selector(f".pm-group-toolbar[data-group-id='{group_id}']")
        record(
            "group_layer_is_below_edges_and_nodes_with_click_through_body",
            page.evaluate(
                """groupId => {
                    const editor = window.__processMapFlow.editor;
                    const order = Array.from(editor.world.children).map(item => item.className.baseVal || item.className);
                    const frame = editor.groupLayer.querySelector(`[data-group-id="${groupId}"]`);
                    const header = frame.querySelector('.pm-group-header');
                    return order[0] === 'pm-group-layer'
                        && order[1] === 'pm-edge-layer'
                        && order[2] === 'pm-node-layer'
                        && getComputedStyle(frame).pointerEvents === 'none'
                        && getComputedStyle(header).pointerEvents === 'auto';
                }""",
                group_id,
            ),
        )
        record(
            "group_selection_uses_one_context_toolbar_with_frequent_actions",
            page.locator(".ip-floating-surface").count() == 1
            and page.locator(".pm-group-toolbar [data-group-command='rename']").count() == 1
            and page.locator(".pm-group-toolbar .pm-group-color-select").count() == 1
            and page.locator(".pm-group-toolbar .pm-group-toolbar-move-only").count() == 1
            and page.locator(".pm-group-toolbar [data-group-command='delete']").count() == 1,
        )
        page.locator(".pm-group-toolbar [data-group-command='rename']").click()
        page.locator(".pm-group-toolbar .pm-card-toolbar-field").fill("Final inspection cell")
        page.get_by_role("button", name="Save group label").click()
        page.locator(".pm-group-toolbar .pm-group-color-select").select_option("teal")
        record(
            "group_toolbar_renames_and_recolors_through_undoable_mutations",
            page.evaluate(
                """groupId => {
                    const group = window.__processMapFlow.editor.processMap.canvasGroups
                        .find(item => item.groupId === groupId);
                    return group.label === 'Final inspection cell' && group.colorKey === 'teal';
                }""",
                group_id,
            )
            and page.locator(
                f".pm-group-frame[data-group-id='{group_id}'].pm-group-color-teal"
            ).count() == 1,
        )

        before_group_move = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                    undoDepth: window.__processMapFlow.editor.history.undoStack.length,
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        group_header = page.locator(f".pm-group-frame[data-group-id='{group_id}'] .pm-group-header")
        header_box = group_header.bounding_box()
        assert header_box is not None
        page.mouse.move(header_box["x"] + header_box["width"] / 2, header_box["y"] + 12)
        page.mouse.down()
        page.mouse.move(header_box["x"] + header_box["width"] / 2 + 80, header_box["y"] + 62, steps=8)
        page.mouse.up()
        after_group_move = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                    undoDepth: window.__processMapFlow.editor.history.undoStack.length,
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        group_dx = after_group_move["group"]["x"] - before_group_move["group"]["x"]
        group_dy = after_group_move["group"]["y"] - before_group_move["group"]["y"]
        record(
            "group_header_drag_moves_frame_and_members_as_one_history_entry",
            abs((after_group_move["node"]["x"] - before_group_move["node"]["x"]) - group_dx) < 1
            and abs((after_group_move["node"]["y"] - before_group_move["node"]["y"]) - group_dy) < 1
            and after_group_move["undoDepth"] == before_group_move["undoDepth"] + 1,
            {"before": before_group_move, "after": after_group_move},
        )

        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.wait_for_selector(".pm-group-toolbar .pm-group-toolbar-move-only")
        page.locator(".pm-group-toolbar .pm-group-toolbar-move-only").click()
        frame_only_before = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        header_box = group_header.bounding_box()
        assert header_box is not None
        page.mouse.move(header_box["x"] + header_box["width"] / 2, header_box["y"] + 12)
        page.mouse.down()
        page.mouse.move(header_box["x"] + header_box["width"] / 2 + 55, header_box["y"] + 42, steps=6)
        page.mouse.up()
        frame_only_after = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        record(
            "group_toolbar_frame_only_mode_leaves_member_coordinates_unchanged",
            frame_only_after["group"] != frame_only_before["group"]
            and frame_only_after["node"] == frame_only_before["node"],
            {"before": frame_only_before, "after": frame_only_after},
        )

        page.evaluate("window.__processMapFlow.editor.fit()")
        page.wait_for_timeout(150)
        size_before = page.evaluate(
            "groupId => structuredClone(window.__processMapFlow.editor.processMap.canvasGroups.find(item => item.groupId === groupId).size)",
            group_id,
        )
        resize_handle = page.locator(
            f".pm-group-frame[data-group-id='{group_id}'] .pm-group-resize-se"
        )
        resize_box = resize_handle.bounding_box()
        assert resize_box is not None
        resize_hit = page.evaluate(
            """point => {
                const target = document.elementFromPoint(point.x, point.y);
                const viewport = window.__processMapFlow.editor.viewport.getBoundingClientRect();
                return {
                    tag: target ? target.tagName : null,
                    className: target ? target.className : null,
                    x: point.x,
                    y: point.y,
                    viewport: {
                        x: viewport.x,
                        y: viewport.y,
                        right: viewport.right,
                        bottom: viewport.bottom,
                    },
                };
            }""",
            {"x": resize_box["x"] + 6, "y": resize_box["y"] + 6},
        )
        page.mouse.move(resize_box["x"] + 6, resize_box["y"] + 6)
        page.mouse.down()
        resize_interaction = page.evaluate(
            "window.__processMapFlow.editor.interaction && window.__processMapFlow.editor.interaction.mode"
        )
        page.mouse.move(resize_box["x"] + 86, resize_box["y"] + 56, steps=6)
        page.mouse.up()
        size_after = page.evaluate(
            "groupId => structuredClone(window.__processMapFlow.editor.processMap.canvasGroups.find(item => item.groupId === groupId).size)",
            group_id,
        )
        record(
            "selected_group_resizes_from_canvas_handle",
            size_after["width"] > size_before["width"]
            and size_after["height"] > size_before["height"],
            {
                "before": size_before,
                "after": size_after,
                "hit": resize_hit,
                "interaction": resize_interaction,
            },
        )

        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.wait_for_selector(".pm-group-toolbar .pm-group-toolbar-move-only")
        move_only_button = page.locator(".pm-group-toolbar .pm-group-toolbar-move-only")
        if move_only_button.get_attribute("aria-pressed") == "true":
            move_only_button.click()
        alt_move_before = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        group_header = page.locator(f".pm-group-frame[data-group-id='{group_id}'] .pm-group-header")
        header_box = group_header.bounding_box()
        assert header_box is not None
        alt_drag_point = group_header.evaluate(
            """header => {
                const rect = header.getBoundingClientRect();
                const y = rect.top + Math.min(12, rect.height / 2);
                for (let x = rect.left + 8; x <= rect.right - 8; x += 8) {
                    const target = document.elementFromPoint(x, y);
                    if (target && target.closest('.pm-group-header') === header) return { x, y };
                }
                return { x: rect.left + 8, y };
            }"""
        )
        alt_drag_hit = page.evaluate(
            """point => {
                const target = document.elementFromPoint(point.x, point.y);
                return {
                    tag: target && target.tagName,
                    className: target && target.className,
                    groupId: target && target.closest('[data-group-id]')
                        ? target.closest('[data-group-id]').getAttribute('data-group-id') : null,
                };
            }""",
            alt_drag_point,
        )
        page.keyboard.down("Alt")
        page.mouse.move(alt_drag_point["x"], alt_drag_point["y"])
        page.mouse.down()
        alt_drag_interaction = page.evaluate(
            """() => {
                const interaction = window.__processMapFlow.editor.interaction;
                return interaction && {
                    mode: interaction.mode,
                    groupId: interaction.groupId,
                    withMembers: interaction.withMembers,
                };
            }"""
        )
        page.mouse.move(alt_drag_point["x"] + 28, alt_drag_point["y"] + 18, steps=5)
        page.mouse.up()
        page.keyboard.up("Alt")
        alt_move_after = page.evaluate(
            """({ groupId, nodeId }) => {
                const map = window.__processMapFlow.editor.processMap;
                return {
                    group: structuredClone(map.canvasGroups.find(item => item.groupId === groupId).position),
                    node: structuredClone(map.canvasNodes.find(item => item.nodeId === nodeId).position),
                };
            }""",
            {"groupId": group_id, "nodeId": first_id},
        )
        record(
            "alt_drag_moves_group_frame_without_members",
            alt_move_after["group"] != alt_move_before["group"]
            and alt_move_after["node"] == alt_move_before["node"],
            {
                "before": alt_move_before,
                "after": alt_move_after,
                "hit": alt_drag_hit,
                "interaction": alt_drag_interaction,
            },
        )

        overlap_group_id = page.evaluate(
            """({ groupId, nodeId }) => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                const outer = editor.processMap.canvasGroups.find(item => item.groupId === groupId);
                editor.addCanvasGroup();
                const inner = editor.processMap.canvasGroups.at(-1);
                let next = runtime.resizeGroup(editor.processMap, inner.groupId, {
                    position: { x: outer.position.x + 90, y: outer.position.y + 70 },
                    size: { width: 420, height: 250 },
                });
                next = runtime.moveNode(next, nodeId, {
                    x: outer.position.x - 500,
                    y: outer.position.y + 25,
                });
                editor.commitMutation(next);
                return inner.groupId;
            }""",
            {"groupId": group_id, "nodeId": process_step_id},
        )
        page.evaluate("window.__processMapFlow.editor.fit()")
        page.wait_for_timeout(150)
        overlap_frame = page.locator(f".pm-group-frame[data-group-id='{overlap_group_id}']")
        overlap_box = overlap_frame.bounding_box()
        step_card = page.locator(f".pm-node[data-node-id='{process_step_id}'] .pm-node-card")
        step_box = step_card.bounding_box()
        assert overlap_box is not None and step_box is not None
        overlap_target = page.evaluate(
            """groupId => {
                const frame = document.querySelector(`.pm-group-frame[data-group-id="${groupId}"]`);
                const rect = frame.getBoundingClientRect();
                const fractions = [0.2, 0.5, 0.8];
                for (const y of fractions) {
                    for (const x of fractions) {
                        const point = { left: rect.left + rect.width * x, top: rect.top + rect.height * y };
                        const hit = document.elementFromPoint(point.left, point.top);
                        if (!hit || !hit.closest('.pm-node, .pm-junction')) {
                            return { x: point.left, y: point.top };
                        }
                    }
                }
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
            }""",
            overlap_group_id,
        )
        join_facts = page.evaluate(
            """({ nodeId, outerId, innerId, start, target }) => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                const groups = editor.processMap.canvasGroups;
                const targetWorld = editor.clientToWorld(target.x, target.y);
                const startHit = document.elementFromPoint(start.x, start.y);
                return {
                    startNodeId: startHit && startHit.closest('.pm-node')
                        ? startHit.closest('.pm-node').dataset.nodeId
                        : null,
                    outerContains: runtime.groupContainsPoint(
                        groups.find(item => item.groupId === outerId), targetWorld
                    ),
                    innerContains: runtime.groupContainsPoint(
                        groups.find(item => item.groupId === innerId), targetWorld
                    ),
                };
            }""",
            {
                "nodeId": process_step_id,
                "outerId": group_id,
                "innerId": overlap_group_id,
                "start": {
                    "x": step_box["x"] + step_box["width"] / 2,
                    "y": step_box["y"] + step_box["height"] / 2,
                },
                "target": overlap_target,
            },
        )
        page.mouse.move(step_box["x"] + step_box["width"] / 2, step_box["y"] + step_box["height"] / 2)
        page.mouse.down()
        join_action = page.evaluate(
            """() => {
                const action = window.__processMapFlow.editor.interaction;
                return action && {
                    mode: action.mode,
                    nodeId: action.nodeId,
                };
            }"""
        )
        page.mouse.move(
            step_box["x"] + step_box["width"] / 2 + 12,
            step_box["y"] + step_box["height"] / 2 + 8,
            steps=2,
        )
        page.mouse.move(overlap_target["x"], overlap_target["y"], steps=8)
        page.mouse.up()
        overlap_membership = page.evaluate(
            """({ outerId, innerId, nodeId }) => {
                const groups = window.__processMapFlow.editor.processMap.canvasGroups;
                const outer = groups.find(item => item.groupId === outerId);
                const inner = groups.find(item => item.groupId === innerId);
                return {
                    outer: outer.memberNodeIds.includes(nodeId),
                    inner: inner.memberNodeIds.includes(nodeId),
                    nodeAfter: structuredClone(
                        window.__processMapFlow.editor.processMap.canvasNodes
                            .find(item => item.nodeId === nodeId).position
                    ),
                };
            }""",
            {"outerId": group_id, "innerId": overlap_group_id, "nodeId": process_step_id},
        )
        record(
            "pointer_up_in_overlap_joins_only_smallest_group",
            join_facts["startNodeId"] == process_step_id
            and join_facts["outerContains"] is True
            and join_facts["innerContains"] is True
            and join_action == {"mode": "node", "nodeId": process_step_id}
            and overlap_membership["outer"] is False
            and overlap_membership["inner"] is True,
            {"membership": overlap_membership, "facts": join_facts, "action": join_action},
        )

        outside_point = page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                const rect = editor.viewport.getBoundingClientRect();
                const candidates = [
                    { x: rect.left + 70, y: rect.top + 70 },
                    { x: rect.right - 70, y: rect.top + 70 },
                    { x: rect.left + 70, y: rect.bottom - 70 },
                    { x: rect.right - 70, y: rect.bottom - 70 },
                ];
                return candidates.find(point => {
                    const world = editor.clientToWorld(point.x, point.y);
                    const hit = document.elementFromPoint(point.x, point.y);
                    return !editor.processMap.canvasGroups.some(group => runtime.groupContainsPoint(group, world))
                        && (!hit || !hit.closest('.pm-node, .pm-junction'));
                });
            }"""
        )
        assert outside_point is not None
        step_box = page.locator(f".pm-node[data-node-id='{process_step_id}'] .pm-node-card").bounding_box()
        assert step_box is not None
        page.mouse.move(step_box["x"] + step_box["width"] / 2, step_box["y"] + step_box["height"] / 2)
        page.mouse.down()
        leave_action = page.evaluate(
            """() => {
                const action = window.__processMapFlow.editor.interaction;
                return action && { mode: action.mode, nodeId: action.nodeId };
            }"""
        )
        page.mouse.move(
            step_box["x"] + step_box["width"] / 2 + 12,
            step_box["y"] + step_box["height"] / 2 + 8,
            steps=2,
        )
        page.mouse.move(outside_point["x"], outside_point["y"], steps=8)
        page.mouse.up()
        record(
            "pointer_up_outside_groups_removes_membership",
            leave_action == {"mode": "node", "nodeId": process_step_id}
            and page.evaluate(
                """nodeId => !window.__processMapFlow.editor.processMap.canvasGroups
                    .some(group => group.memberNodeIds.includes(nodeId))""",
                process_step_id,
            ),
        )
        page.evaluate(
            """groupId => {
                const editor = window.__processMapFlow.editor;
                editor.commitMutation(window.InspectorProProcessMap.deleteGroup(editor.processMap, groupId));
                editor.selectGroup(null);
            }""",
            overlap_group_id,
        )

        theme_group_styles = {}
        for theme in ("light", "dark"):
            page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
            theme_group_styles[theme] = page.locator(
                f".pm-group-frame[data-group-id='{group_id}']"
            ).evaluate(
                "el => ({ background: getComputedStyle(el).backgroundColor, border: getComputedStyle(el).borderColor })"
            )
        record(
            "group_palette_is_visible_in_light_and_dark_themes",
            all(
                style["background"] not in ("rgba(0, 0, 0, 0)", "transparent")
                and style["border"] not in ("rgba(0, 0, 0, 0)", "transparent")
                for style in theme_group_styles.values()
            ),
            theme_group_styles,
        )

        page.evaluate("groupId => window.__processMapFlow.editor.selectGroup(groupId)", group_id)
        page.locator(".pm-group-toolbar [data-group-command='delete']").click()
        record(
            "deleting_group_keeps_member_cards_and_undo_restores_frame",
            page.locator(f".pm-node[data-node-id='{first_id}']").count() == 1
            and page.locator(f".pm-group-frame[data-group-id='{group_id}']").count() == 0,
        )
        page.evaluate("window.__processMapFlow.editor.undo()")
        page.wait_for_selector(f".pm-group-frame[data-group-id='{group_id}']")

        def suggestion_edge(suggestion_id: str, edge_id: str, source: str, target: str) -> dict:
            return {
                "suggestionId": suggestion_id,
                "ruleId": "synthetic_sequence",
                "ruleVersion": "1.0.0",
                "confidence": "high",
                "edge": {
                    "edgeId": edge_id,
                    "logicalConnectionId": edge_id,
                    "from": {"nodeId": source, "port": "out"},
                    "to": {"nodeId": target, "port": "in"},
                    "kind": "precedence",
                },
                "provenance": [{"source": "authored_precedence_pattern"}],
                "explanation": f"Connect {source} to {target} from reviewed sequence evidence.",
                "validation": {"wouldCreateCycle": False, "duplicateOfExisting": False},
                "affectedIds": [source, target],
            }

        store["suggestions"] = [
            suggestion_edge(
                "pms-smoke-b-output",
                "pm-e-suggest-b-output",
                canvas_ids[1],
                second_step_id,
            ),
            suggestion_edge(
                "pms-smoke-a-inspection",
                "pm-e-suggest-a-inspection",
                canvas_ids[0],
                process_step_id,
            ),
            {
                "suggestionId": "pms-smoke-resource",
                "ruleId": "resource_contention",
                "ruleVersion": "1.0.0",
                "confidence": "medium",
                "annotation": {"kind": "resource_contention", "referenceId": "machine-1"},
                "provenance": [{"source": "process_reference"}],
                "explanation": "Two steps share the same machining resource.",
                "validation": {"wouldCreateCycle": False, "duplicateOfExisting": False},
                "affectedIds": [canvas_ids[0], process_step_id],
            },
        ]

        page.screenshot(
            path=str(OUT_DIR / "process_flow_wire_references_dark.png"),
            full_page=False,
        )
        page.get_by_role("button", name="Save process map").click()
        page.wait_for_function("window.__processMapFlow.editor.dirty === false")
        record(
            "save_persists_only_placed_nodes_and_canvas_edges",
            store["putCount"] == 2
            and len(store["map"]["canvasNodes"]) == 6
            and len(store["map"]["canvasEdges"]) == 5
            and len([node for node in store["map"]["canvasNodes"] if node.get("nodeKind") == "junction"]) == 1
            and len([node for node in store["map"]["canvasNodes"] if node.get("portOrientation") == "vertical"]) == 1
            and len([node for node in store["map"]["canvasNodes"] if node.get("portOrder") == "output_first"]) == 1
            and any(
                node.get("nodeId") == first_id
                and node.get("labelOverride") == "Primary seat shell"
                and node.get("note") == "Verify the seating surface before the inspection step."
                and len(node.get("referenceIds", [])) == 1
                for node in store["map"]["canvasNodes"]
            )
            and len(store["map"].get("referenceCatalog", [])) == 2
            and store["map"].get("layoutVersion") == 3
            and len(store["map"].get("canvasGroups", [])) == 1
            and store["map"]["canvasGroups"][0].get("label") == "Final inspection cell"
            and first_id in store["map"]["canvasGroups"][0].get("memberNodeIds", [])
            and len([
                edge for edge in store["map"]["canvasEdges"]
                if edge.get("logicalConnectionId") == trunk_edge_id
                and len(edge.get("referenceIds", [])) == 1
            ]) == 2
            and "occurrences" not in store["map"],
        )

        page.wait_for_function(
            "window.__processMapFlow.editor.suggestions.length === 3"
            " && window.__processMapFlow.editor.suggestionsRevision === 'rev-3'"
        )
        record(
            "saved_revision_renders_only_connection_suggestions_as_dashed_ghosts",
            page.locator(".pm-edge-ghost").count() == 2
            and page.locator(".pm-ghost-edge-hit").count() == 2
            and "3" in page.get_by_role(
                "button", name="Review evidence-backed process-flow suggestions"
            ).inner_text(),
        )
        page.screenshot(
            path=str(OUT_DIR / "process_flow_suggestions_dark.png"),
            full_page=False,
        )
        ghost_midpoint = page.locator(".pm-ghost-edge-hit").first.evaluate(
            """path => {
                const local = path.getPointAtLength(path.getTotalLength() / 2);
                const matrix = path.getScreenCTM();
                const screen = new DOMPoint(local.x, local.y).matrixTransform(matrix);
                return { x: screen.x, y: screen.y };
            }"""
        )
        page.mouse.click(ghost_midpoint["x"], ghost_midpoint["y"])
        page.wait_for_selector(".pm-suggestion-panel:not([hidden])")
        record(
            "ghost_connection_opens_its_evidence_review_surface",
            page.locator(".pm-suggestion-item.focused").count() == 1
            and page.locator(".pm-suggestion-provenance").filter(
                has_text="authored precedence pattern"
            ).count() >= 1,
        )

        page.locator(
            ".pm-suggestion-item[data-suggestion-id='pms-smoke-resource']"
        ).get_by_role("button", name="Hide this exact evidence-backed suggestion").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.dismissedSuggestions"
            ".includes('pms-smoke-resource')"
        )
        record(
            "dismissal_removes_only_exact_suggestion_and_is_undoable_map_state",
            page.locator(".pm-edge-ghost").count() == 2
            and page.evaluate("window.__processMapFlow.editor.dirty") is True
            and page.evaluate("window.__processMapFlow.editor.history.undoStack.length") == 1,
        )
        page.get_by_role("button", name="Save process map").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.dirty === false"
            " && window.__processMapFlow.editor.suggestions.length === 2"
        )
        record(
            "dismissal_persists_and_server_does_not_return_it_for_new_revision",
            store["map"].get("dismissedSuggestions") == ["pms-smoke-resource"]
            and all(
                item.get("suggestionId") != "pms-smoke-resource"
                for item in page.evaluate("window.__processMapFlow.editor.suggestions")
            ),
        )

        page.get_by_role("button", name="Accept every currently valid connection suggestion").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges.length === 7"
        )
        record(
            "batch_accept_is_one_atomic_validated_mutation_and_clears_stale_ghosts",
            page.locator(".pm-edge-ghost").count() == 0
            and page.evaluate("window.__processMapFlow.editor.history.undoStack.length") == 1
            and page.evaluate("window.__processMapFlow.editor.dirty") is True,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges.length === 5"
            " && window.__processMapFlow.editor.dirty === false"
            " && window.__processMapFlow.editor.suggestions.length === 2"
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges.length === 7"
        )
        record(
            "one_undo_and_redo_restore_complete_batch_topology",
            page.evaluate("window.__processMapFlow.editor.processMap.canvasEdges.length") == 7,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges.length === 5"
            " && window.__processMapFlow.editor.dirty === false"
        )

        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", first_id)
        page.wait_for_selector(".pm-card-toolbar")
        page.evaluate(
            "() => window.__processMapFlow.editor.applyNodeNote('Temporary conflicting edit')"
        )
        page.wait_for_function("window.__processMapFlow.editor.dirty === true")
        store["conflictNext"] = True
        page.get_by_role("button", name="Save process map").click()
        page.wait_for_function("window.__processMapFlow.editor.conflict === true")
        record(
            "revision_conflict_closes_and_locks_context_toolbar",
            page.locator(".ip-floating-surface").count() == 0
            and "newer saved revision" in page.locator(".pm-editor-status").inner_text().lower(),
        )
        page.get_by_role("button", name="Reload the latest saved process map").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.conflict === false"
            " && window.__processMapFlow.editor.dirty === false"
        )
        record(
            "conflict_reload_restores_saved_state_without_toolbar_residue",
            page.locator(".ip-floating-surface").count() == 0
            and page.evaluate(
                "nodeId => window.__processMapFlow.editor.processMap.canvasNodes"
                ".find(node => node.nodeId === nodeId).note === "
                "'Verify the seating surface before the inspection step.'",
                first_id,
            ),
        )

        page.reload(wait_until="networkidle", timeout=60_000)
        _open_process_flow(page)
        record(
            "saved_placements_and_connections_survive_reload",
            page.locator(".pm-node").count() == 5
            and page.locator(".pm-junction").count() == 1
            and page.evaluate("window.__processMapFlow.editor.processMap.canvasEdges.length") == 5
            and page.locator(".pm-node-ports-vertical").count() == 1
            and page.locator(".pm-node-port-order-output_first").count() == 1
            and page.locator(f".pm-group-frame[data-group-id='{group_id}']").count() == 1
            and page.locator(f".pm-node[data-node-id='{first_id}'] .pm-node-note-indicator").count() == 1
            and page.locator(
                f".pm-node[data-node-id='{first_id}'] .pm-reference-badge-machine"
            ).count() == 1
            and page.locator(".pm-edge-context-label").filter(
                has_text="Inspection release | Std 1"
            ).count() == 1
            and "Primary seat shell" in page.locator(
                f".pm-node[data-node-id='{first_id}'] .pm-node-card"
            ).inner_text(),
        )

        page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", first_id)
        page.wait_for_selector(".pm-card-toolbar")
        page.evaluate(
            "window.__pmToolbarManagers = [window.__processMapFlow.editor.cardToolbarManager]"
        )
        churn_ok = True
        for _index in range(3):
            page.locator(".tab[data-tab='drawing']").click()
            page.wait_for_selector(".tab.active[data-tab='drawing']")
            page.wait_for_timeout(80)
            churn_ok = churn_ok and page.locator(".ip-floating-surface").count() == 0
            churn_ok = churn_ok and page.evaluate(
                "window.__pmToolbarManagers.every(manager => !manager.isOpen())"
            )

            page.locator(".tab[data-tab='training']").click()
            page.wait_for_selector(".tab.active[data-tab='training']")
            _ensure_process_flow_editor(page)
            page.evaluate("nodeId => window.__processMapFlow.editor.select(nodeId)", first_id)
            page.wait_for_selector(".pm-card-toolbar")
            page.evaluate(
                "window.__pmToolbarManagers.push(window.__processMapFlow.editor.cardToolbarManager)"
            )
            churn_ok = churn_ok and page.locator(".ip-floating-surface").count() == 1
            churn_ok = churn_ok and page.evaluate(
                "window.__pmToolbarManagers.slice(0, -1).every(manager => !manager.isOpen())"
                " && window.__pmToolbarManagers.at(-1).isOpen()"
            )
        record(
            "rapid_tab_remount_churn_leaves_only_current_surface_active",
            churn_ok,
        )

        page.locator(".tab[data-tab='drawing']").click()
        page.wait_for_selector(".tab.active[data-tab='drawing']")
        page.wait_for_timeout(80)
        record(
            "tab_change_destroys_toolbar_without_dom_or_manager_residue",
            page.locator(".ip-floating-surface").count() == 0
            and page.evaluate(
                "window.__pmToolbarManagers.every(manager => !manager.isOpen())"
            ),
        )

        page.locator(".tab[data-tab='training']").click()
        page.wait_for_selector(".tab.active[data-tab='training']")
        _ensure_process_flow_editor(page)

        type_select = page.locator("#trainingTypeRibbonSelect")
        type_select.select_option("troubleshooting")
        page.wait_for_selector("[data-training-ribbon-command='start']")
        record(
            "training_workflow_switch_replaces_process_map_ribbon_immediately",
            page.locator("#trainingProcessMapRibbonHost").count() == 0
            and page.locator("[data-process-map-command]").count() == 0
            and page.locator("[data-training-ribbon-command='start']").count() == 1
            and page.locator("[data-training-ribbon-command='explode']").count() == 0
            and page.locator("[data-training-product-structure-diagram]").count() == 0,
        )
        page.locator("#trainingTypeRibbonSelect").select_option("assembly")
        page.wait_for_selector("#trainingProcessMapRibbonHost [data-process-map-command='processSave']")
        expected_process_commands = {
            "processUndo", "processRedo", "processDelete", "processStep",
            "processGroup", "processCleanUp", "processJunction", "processSuggestions", "processAnalyze", "processAnalyzeLayout", "processZoomOut",
            "processZoomIn", "processFit", "3dmodel", "processSave", "processClear",
            "processSelectGroup",
        }
        actual_process_commands = set(
            page.locator("#trainingProcessMapRibbonHost [data-process-map-command]")
            .evaluate_all("buttons => buttons.map(button => button.dataset.processMapCommand)")
        )
        record(
            "process_map_ribbon_replaces_generic_training_commands",
            page.locator("[data-training-ribbon-command]").count() == 0
            and expected_process_commands.issubset(actual_process_commands)
            and "processStructure" not in actual_process_commands
            and page.locator("#trainingTypeRibbonSelect option:checked").inner_text() == "Process Map"
            and page.locator("[data-training-product-structure-diagram]").count() == 0
            and page.locator("[data-process-map-command='processBack']:visible").count() == 0
            and page.locator("[data-process-map-command='processReload']:visible").count() == 0,
            sorted(actual_process_commands),
        )

        premium_icon_state = page.evaluate(
            """() => {
                const icons = Array.from(document.querySelectorAll(
                    '#trainingProcessMapRibbonHost .ribbon-process-icon'
                ));
                return {
                    count: icons.length,
                    loaded: icons.every(icon => icon.complete && icon.naturalWidth > 0),
                    sources: icons.map(icon => icon.getAttribute('src')),
                };
            }"""
        )
        record(
            "process_map_ribbon_uses_loaded_premium_svg_family",
            premium_icon_state["count"] >= 16
            and premium_icon_state["loaded"]
            and all(
                source.startswith("/static/assets/process-map-ribbon-icons/svg/")
                and source.endswith(".svg")
                for source in premium_icon_state["sources"]
            ),
            premium_icon_state,
        )

        baseline_logic_fingerprint = page.evaluate(
            "window.InspectorProProcessMap.mapFingerprint(window.__processMapFlow.editor.processMap)"
        )
        junction_toggle = page.locator(".pm-ribbon-split-toggle")
        junction_toggle.click()
        junction_choices = page.locator(".pm-junction-menu-item").evaluate_all(
            "items => items.map(item => item.dataset.junctionType)"
        )
        record(
            "add_junction_split_menu_exposes_stage_parallel_merge_and_split",
            junction_choices == ["operation_stage", "parallel_and", "merge", "split"],
            junction_choices,
        )
        page.locator(".pm-junction-menu-item[data-junction-type='operation_stage']").click()
        page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                const node = editor.processMap.canvasNodes.find(
                    item => item.nodeId === editor.selectedNodeId
                );
                return node && node.nodeKind === 'process_step'
                    && node.name === 'New Operation / Stage';
            }"""
        )
        stage_id = page.evaluate("window.__processMapFlow.editor.selectedNodeId")

        toolbar_layout = page.locator(".pm-card-toolbar").evaluate(
            """toolbar => {
                const controls = Array.from(toolbar.children).filter(element =>
                    !element.hidden
                    && element.matches('button, select')
                );
                const rectangles = controls.map(element => {
                    const rect = element.getBoundingClientRect();
                    return {
                        command: element.dataset.cardCommand
                            || element.dataset.contextCommand || element.textContent.trim(),
                        left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                    };
                });
                const overlaps = [];
                for (let first = 0; first < rectangles.length; first += 1) {
                    for (let second = first + 1; second < rectangles.length; second += 1) {
                        const a = rectangles[first];
                        const b = rectangles[second];
                        if (a.left < b.right && a.right > b.left
                            && a.top < b.bottom && a.bottom > b.top) {
                            overlaps.push([a.command, b.command]);
                        }
                    }
                }
                return { rectangles, overlaps };
            }"""
        )
        record(
            "stage_context_toolbar_commands_have_distinct_hit_areas",
            toolbar_layout["overlaps"] == []
            and len(toolbar_layout["rectangles"]) >= 7,
            toolbar_layout,
        )

        page.get_by_role("button", name="Edit card label").click()
        page.wait_for_selector(".pm-card-toolbar-editor[data-editor-mode='label']")
        editor_containment = page.locator(".pm-card-toolbar").evaluate(
            """toolbar => {
                const outer = toolbar.getBoundingClientRect();
                const editor = toolbar.querySelector('.pm-card-toolbar-editor').getBoundingClientRect();
                const actions = Array.from(toolbar.querySelectorAll(
                    '.pm-card-toolbar-editor-actions button'
                )).map(button => {
                    const rect = button.getBoundingClientRect();
                    return {
                        label: button.textContent.trim(),
                        left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                    };
                });
                const contained = [editor].concat(actions).every(rect =>
                    rect.left >= outer.left - 0.5 && rect.right <= outer.right + 0.5
                    && rect.top >= outer.top - 0.5 && rect.bottom <= outer.bottom + 0.5
                );
                return {
                    contained,
                    outer: { left: outer.left, top: outer.top, right: outer.right, bottom: outer.bottom },
                    editor: { left: editor.left, top: editor.top, right: editor.right, bottom: editor.bottom },
                    actions,
                };
            }"""
        )
        record(
            "inline_label_editor_and_actions_stay_inside_floating_surface",
            editor_containment["contained"]
            and [item["label"] for item in editor_containment["actions"]] == ["Cancel", "Save"],
            editor_containment,
        )
        page.get_by_role("button", name="Cancel editing").click()

        stage_port_layout = page.evaluate(
            """({ stageId, upperId, lowerId }) => {
                const editor = window.__processMapFlow.editor;
                window.__pmStagePortOriginalMap = window.InspectorProProcessMap.cloneMap(
                    editor.processMap
                );
                window.__pmStagePortOriginalTransform = { ...editor.transform };
                const positions = {
                    [upperId]: { x: 80, y: 90 },
                    [lowerId]: { x: 80, y: 330 },
                    [stageId]: { x: 540, y: 210 },
                };
                let next = window.InspectorProProcessMap.cloneMap(editor.processMap);
                next.canvasNodes = next.canvasNodes.filter(node => positions[node.nodeId])
                    .map(node => ({
                        ...node,
                        position: positions[node.nodeId],
                        portOrientation: 'horizontal',
                        portOrder: 'input_first',
                    }));
                next.canvasEdges = [];
                next.canvasGroups = [];
                next = window.InspectorProProcessMap.addEdge(next, {
                    edgeId: 'smoke-upper-stage',
                    logicalConnectionId: 'smoke-upper-stage',
                    from: { nodeId: upperId, port: 'out' },
                    to: { nodeId: stageId, port: 'in' },
                    kind: 'precedence',
                });
                next = window.InspectorProProcessMap.addEdge(next, {
                    edgeId: 'smoke-lower-stage',
                    logicalConnectionId: 'smoke-lower-stage',
                    from: { nodeId: lowerId, port: 'out' },
                    to: { nodeId: stageId, port: 'in' },
                    kind: 'precedence',
                });
                editor.processMap = next;
                editor.renderGraph({ fit: false });
                editor.fit();
                const ports = Array.from(document.querySelectorAll(
                    `.pm-node[data-node-id="${stageId}"] .pm-port-in`
                )).map(port => {
                    const rect = port.getBoundingClientRect();
                    return {
                        edgeId: port.dataset.edgeId,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                    };
                }).sort((left, right) => left.y - right.y || left.x - right.x);
                const geometries = ['smoke-upper-stage', 'smoke-lower-stage'].map(edgeId => {
                    const geometry = editor.edgeGeometries[edgeId];
                    return {
                        edgeId,
                        endpoint: geometry && geometry.points[geometry.points.length - 1],
                        slot: editor.inputPortLayout.byEdge[edgeId],
                    };
                });
                return { ports, geometries };
            }""",
            {
                "stageId": stage_id,
                "upperId": first_id,
                "lowerId": part_b_id,
            },
        )
        record(
            "operation_stage_renders_one_distinct_anchor_per_incoming_wire",
            len(stage_port_layout["ports"]) == 2
            and stage_port_layout["ports"][0]["edgeId"] != stage_port_layout["ports"][1]["edgeId"]
            and abs(stage_port_layout["ports"][0]["y"] - stage_port_layout["ports"][1]["y"]) > 12
            and {
                item["slot"]["index"] for item in stage_port_layout["geometries"]
            } == {0, 1}
            and len({item["endpoint"]["y"] for item in stage_port_layout["geometries"]}) == 2,
            stage_port_layout,
        )
        page.screenshot(
            path=str(OUT_DIR / "process_flow_stage_multi_input_toolbar_fixed.png"),
            full_page=False,
        )
        page.evaluate(
            """stageId => {
                const editor = window.__processMapFlow.editor;
                editor.processMap = window.__pmStagePortOriginalMap;
                editor.transform = window.__pmStagePortOriginalTransform;
                delete window.__pmStagePortOriginalMap;
                delete window.__pmStagePortOriginalTransform;
                editor.renderGraph({ fit: false });
                editor.select(stageId);
            }""",
            stage_id,
        )
        page.get_by_role("button", name="Edit manufacturing details for this process step").click()
        page.get_by_label("Description", exact=True).fill(
            "Install both lower panels before the upper fairing."
        )
        page.get_by_label("Duration").fill("12 min")
        page.get_by_label("Torque / requirements").fill("10 N m")
        page.get_by_label("Inspection requirements").fill("Verify flushness.")
        page.get_by_role("button", name="Save manufacturing details").click()
        page.wait_for_function(
            """nodeId => {
                const node = window.__processMapFlow.editor.processMap.canvasNodes.find(
                    item => item.nodeId === nodeId
                );
                return node && node.properties && node.properties.duration === '12 min'
                    && node.properties.torqueRequirements === '10 N m';
            }""",
            arg=stage_id,
        )
        stage_properties = page.evaluate(
            """nodeId => window.__processMapFlow.editor.processMap.canvasNodes.find(
                item => item.nodeId === nodeId
            ).properties""",
            stage_id,
        )
        record(
            "operation_stage_edits_manufacturing_details_on_native_node",
            stage_properties == {
                "description": "Install both lower panels before the upper fairing.",
                "duration": "12 min",
                "torqueRequirements": "10 N m",
                "inspectionRequirements": "Verify flushness.",
            },
            stage_properties,
        )
        page.locator(".pm-viewport").focus()
        page.keyboard.press("Control+c")
        before_paste_count = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        )
        page.keyboard.press("Control+v")
        page.wait_for_function(
            "count => window.__processMapFlow.editor.processMap.canvasNodes.length === count + 1",
            arg=before_paste_count,
        )
        pasted_stage_state = page.evaluate(
            """originalId => {
                const editor = window.__processMapFlow.editor;
                const selected = Array.from(editor.selectedNodeIds);
                const copy = editor.processMap.canvasNodes.find(
                    node => selected.includes(node.nodeId) && node.nodeId !== originalId
                );
                return copy && {
                    nodeKind: copy.nodeKind,
                    processType: copy.processType,
                    properties: copy.properties,
                };
            }""",
            stage_id,
        )
        record(
            "operation_stage_copy_paste_preserves_authored_details",
            pasted_stage_state is not None
            and pasted_stage_state["nodeKind"] == "process_step"
            and pasted_stage_state["processType"] == "operation"
            and pasted_stage_state["properties"] == stage_properties,
            pasted_stage_state,
        )
        page.screenshot(
            path=str(OUT_DIR / "process_flow_operation_stage_premium_icons.png"),
            full_page=False,
        )
        for _ in range(3):
            page.evaluate("window.__processMapFlow.editor.undo()")
            page.wait_for_timeout(30)

        semantic_results = {}
        for junction_type in ("parallel_and", "merge", "split"):
            junction_toggle.click()
            page.locator(
                f".pm-junction-menu-item[data-junction-type='{junction_type}']"
            ).click()
            page.wait_for_function(
                """expected => {
                    const editor = window.__processMapFlow.editor;
                    const node = editor.processMap.canvasNodes.find(
                        item => item.nodeId === editor.selectedNodeId
                    );
                    return node && node.nodeKind === 'junction'
                        && node.junctionType === expected;
                }""",
                arg=junction_type,
            )
            semantic_results[junction_type] = page.evaluate(
                """() => {
                    const editor = window.__processMapFlow.editor;
                    const node = editor.processMap.canvasNodes.find(
                        item => item.nodeId === editor.selectedNodeId
                    );
                    const element = document.querySelector(
                        `.pm-junction[data-node-id="${node.nodeId}"]`
                    );
                    return {
                        type: node.junctionType,
                        renderedClass: element.className,
                        ariaLabel: element.getAttribute('aria-label'),
                    };
                }"""
            )
            page.evaluate("window.__processMapFlow.editor.undo()")
            page.wait_for_timeout(30)
        record(
            "semantic_junction_choices_create_distinct_native_nodes",
            all(
                result["type"] == junction_type
                and f"pm-junction-type-{junction_type}" in result["renderedClass"]
                and result["ariaLabel"]
                for junction_type, result in semantic_results.items()
            ),
            semantic_results,
        )

        page.get_by_role("button", name="Add the last-used operation stage or junction type").click()
        page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                const node = editor.processMap.canvasNodes.find(
                    item => item.nodeId === editor.selectedNodeId
                );
                return node && node.junctionType === 'split';
            }"""
        )
        page.evaluate("window.__processMapFlow.editor.undo()")
        page.wait_for_timeout(30)
        record(
            "add_junction_main_action_reuses_last_selected_type_and_undo_restores_map",
            page.evaluate(
                "window.InspectorProProcessMap.mapFingerprint(window.__processMapFlow.editor.processMap)"
            ) == baseline_logic_fingerprint,
        )
        page.screenshot(path=str(OUT_DIR / "process_flow_source_tree_authored.png"), full_page=False)

        map_select = page.get_by_label("Process map", exact=True)
        map_action = page.get_by_label("Process map action", exact=True)
        action_values = map_action.locator("option").evaluate_all(
            "options => options.map(option => option.value)"
        )
        record(
            "map_manager_exposes_frequent_identity_actions",
            map_select.count() == 1
            and {"create", "duplicate", "rename", "save-template", "archive"}
            .issubset(set(action_values)),
            action_values,
        )
        management_layout = page.evaluate(
            """() => {
                const rect = selector => {
                    const element = document.querySelector(selector);
                    if (!element) return null;
                    const value = element.getBoundingClientRect();
                    return { x: value.x, y: value.y, right: value.right,
                        bottom: value.bottom, width: value.width, height: value.height };
                };
                const overlaps = (a, b) => !(a.right <= b.x || b.right <= a.x
                    || a.bottom <= b.y || b.bottom <= a.y);
                const ribbon = rect('#contextRibbon');
                const host = rect('#trainingProcessMapRibbonHost');
                const manager = rect('.pm-map-manager');
                const editing = rect('[data-process-map-ribbon-group="editing"]');
                const editor = rect('.pm-editor');
                const workspace = rect('.pm-workspace');
                const ribbonElement = document.querySelector('#contextRibbon');
                return {
                    ribbon, host, manager, editing, editor, workspace,
                    managerOverlapsEditing: overlaps(manager, editing),
                    contained: host.x >= ribbon.x && host.right <= ribbon.right
                        && host.y >= ribbon.y && host.bottom <= ribbon.bottom,
                    fitsWithoutHorizontalScroll:
                        ribbonElement.scrollWidth <= ribbonElement.clientWidth + 2,
                    internalToolbarCount:
                        document.querySelectorAll('.pm-editor > .pm-toolbar').length,
                    reclaimedHeight: Math.abs(workspace.y - editor.y) <= 1,
                };
            }"""
        )
        record(
            "process_map_commands_use_main_ribbon_and_reclaim_viewport_height",
            management_layout["contained"]
            and not management_layout["managerOverlapsEditing"]
            and management_layout["fitsWithoutHorizontalScroll"]
            and management_layout["internalToolbarCount"] == 0
            and management_layout["reclaimedHeight"]
            and management_layout["manager"]["width"] >= 120,
            management_layout,
        )

        default_node_count = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        )
        default_edge_count = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasEdges.length"
        )
        page.once("dialog", lambda dialog: dialog.accept("Manufacturing Demo Copy"))
        map_action.select_option("duplicate")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.mapId !== 'default'"
            " && window.__processMapFlow.editor.processMap.displayName === 'Manufacturing Demo Copy'"
        )
        duplicate_id = page.evaluate("window.__processMapFlow.editor.processMap.mapId")
        duplicate_saved_node_count = page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        )
        record(
            "duplicate_creates_an_independent_named_map",
            duplicate_saved_node_count == default_node_count
            and page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasEdges.length"
            ) == default_edge_count
            and len(store.get("namedMaps", {})) == 1
            and store["map"]["mapId"] == "default",
            {"mapId": duplicate_id, "nodes": duplicate_saved_node_count},
        )

        page.once("dialog", lambda dialog: dialog.accept("Pilot Review Flow"))
        map_action.select_option("rename")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.displayName === 'Pilot Review Flow'"
        )
        record(
            "rename_updates_the_named_map_and_catalog",
            "Pilot Review Flow" in map_select.locator(
                f"option[value='{duplicate_id}']"
            ).inner_text()
            and store["namedMaps"][duplicate_id]["map"]["displayName"] == "Pilot Review Flow",
        )

        page.get_by_role(
            "button", name="Add an operation to the center of the process map"
        ).click()
        page.wait_for_function("window.__processMapFlow.editor.dirty === true")
        page.once("dialog", lambda dialog: dialog.dismiss())
        map_select.select_option("default")
        page.wait_for_timeout(200)
        record(
            "dirty_map_switch_can_be_cancelled_without_losing_work",
            page.evaluate("window.__processMapFlow.editor.processMap.mapId") == duplicate_id
            and page.evaluate("window.__processMapFlow.editor.dirty") is True,
        )
        page.once("dialog", lambda dialog: dialog.accept())
        map_select.select_option("default")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.mapId === 'default'"
            " && window.__processMapFlow.editor.dirty === false"
        )
        record(
            "confirmed_map_switch_discards_only_unsaved_local_edits",
            len(store["namedMaps"][duplicate_id]["map"]["canvasNodes"])
            == duplicate_saved_node_count
            and page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == default_node_count,
        )

        map_select.select_option(duplicate_id)
        page.wait_for_function(
            "mapId => window.__processMapFlow.editor.processMap.mapId === mapId",
            arg=duplicate_id,
        )
        page.once("dialog", lambda dialog: dialog.accept("Reusable Inspection Cell"))
        map_action.select_option("save-template")
        page.wait_for_function(
            "document.querySelector('[aria-label=\"Process map action\"]')"
            ".querySelector('option[value^=\"from-template:\"]') !== null"
        )
        template_id = next(iter(store["templates"]))
        template = store["templates"][template_id]
        template_node_ids = {
            node["nodeId"] for node in template["skeleton"].get("canvasNodes", [])
        }
        record(
            "save_as_template_strips_product_occurrences",
            bool(template_node_ids)
            and all(
                node.get("nodeKind") != "product_occurrence"
                for node in template["skeleton"].get("canvasNodes", [])
            )
            and map_action.locator(
                f"option[value='from-template:{template_id}']"
            ).count() == 1,
            {"templateId": template_id, "nodes": len(template_node_ids)},
        )

        page.once("dialog", lambda dialog: dialog.accept("Inspection Cell Instance"))
        map_action.select_option(f"from-template:{template_id}")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.displayName === 'Inspection Cell Instance'"
        )
        template_instance_id = page.evaluate("window.__processMapFlow.editor.processMap.mapId")
        instantiated_node_ids = set(page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.map(node => node.nodeId)"
        ))
        record(
            "template_instance_is_product_neutral_with_fresh_graph_ids",
            bool(instantiated_node_ids)
            and template_node_ids.isdisjoint(instantiated_node_ids)
            and page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes"
                ".every(node => node.nodeKind !== 'product_occurrence')"
            ),
            {"mapId": template_instance_id, "nodes": len(instantiated_node_ids)},
        )

        map_select.select_option("default")
        page.wait_for_function("window.__processMapFlow.editor.processMap.mapId === 'default'")
        map_select.select_option(template_instance_id)
        page.wait_for_function(
            "mapId => window.__processMapFlow.editor.processMap.mapId === mapId",
            arg=template_instance_id,
        )
        record(
            "template_instance_survives_map_switch_round_trip",
            set(page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.map(node => node.nodeId)"
            )) == instantiated_node_ids,
        )

        page.once("dialog", lambda dialog: dialog.accept())
        map_action.select_option("archive")
        page.wait_for_function("window.__processMapFlow.editor.processMap.mapId === 'default'")
        record(
            "archive_returns_to_default_and_removes_map_from_switcher",
            store["namedMaps"][template_instance_id]["map"]["status"] == "archived"
            and map_select.locator(
                f"option[value='{template_instance_id}']"
            ).count() == 0,
        )

        page.once("dialog", lambda dialog: dialog.accept("Blank Pilot Map"))
        map_action.select_option("create")
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.displayName === 'Blank Pilot Map'"
            " && window.__processMapFlow.editor.processMap.canvasNodes.length === 0"
        )
        blank_map_id = page.evaluate("window.__processMapFlow.editor.processMap.mapId")
        record(
            "new_map_starts_blank_and_is_independently_registered",
            blank_map_id not in {"default", duplicate_id, template_instance_id}
            and page.locator(".pm-empty-state:visible").count() == 1
            and map_select.locator(f"option[value='{blank_map_id}']").count() == 1,
            blank_map_id,
        )
        management_theme_styles = {}
        for theme in ("light", "dark"):
            page.evaluate(
                "theme => document.documentElement.setAttribute('data-theme', theme)",
                theme,
            )
            management_theme_styles[theme] = map_select.evaluate(
                "el => ({ background: getComputedStyle(el).backgroundColor, "
                "color: getComputedStyle(el).color, border: getComputedStyle(el).borderColor })"
            )
            page.screenshot(
                path=str(OUT_DIR / f"process_flow_map_management_{theme}.png"),
                full_page=False,
            )
        record(
            "map_management_controls_are_readable_in_both_themes",
            all(
                style["background"] not in ("rgba(0, 0, 0, 0)", "transparent")
                and style["color"] != style["background"]
                and style["border"] not in ("rgba(0, 0, 0, 0)", "transparent")
                for style in management_theme_styles.values()
            ),
            management_theme_styles,
        )
        clear_command = page.locator("[data-process-map-command='processClear']")
        clear_initially_disabled = clear_command.is_disabled()
        source_occurrence_count = page.evaluate(
            "window.__processMapFlow.editor.productStructure.occurrences.length"
        )
        page.get_by_role(
            "button", name="Add an operation to the center of the process map"
        ).click()
        page.get_by_role(
            "button", name="Add a grouping frame to the center of the process map"
        ).click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            " && window.__processMapFlow.editor.processMap.canvasGroups.length === 1"
        )
        page.once("dialog", lambda dialog: dialog.accept())
        clear_command.click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 0"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 0"
            " && window.__processMapFlow.editor.processMap.canvasGroups.length === 0"
        )
        record(
            "clear_map_command_empties_viewport_without_touching_source_tree",
            clear_initially_disabled
            and clear_command.is_disabled()
            and page.locator(
                "[data-process-map-command='processClear'] img.ribbon-process-icon"
            ).count() == 1
            and page.locator(".pm-empty-state:visible").count() == 1
            and page.evaluate(
                "window.__processMapFlow.editor.productStructure.occurrences.length"
            ) == source_occurrence_count,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            " && window.__processMapFlow.editor.processMap.canvasGroups.length === 1"
        )
        page.get_by_role("button", name="Redo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 0"
            " && window.__processMapFlow.editor.processMap.canvasGroups.length === 0"
        )
        record(
            "clear_map_is_one_atomic_undoable_and_redoable_edit",
            page.locator(".pm-empty-state:visible").count() == 1,
        )

        page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const runtime = window.InspectorProProcessMap;
                let next = editor.processMap;
                [
                    { nodeId: 'marquee-a', name: 'Marquee A', position: { x: 80, y: 100 } },
                    { nodeId: 'marquee-b', name: 'Marquee B', position: { x: 500, y: 100 } },
                    { nodeId: 'marquee-c', name: 'Marquee C', position: { x: 940, y: 500 } },
                ].forEach(spec => {
                    next = runtime.addCanvasNode(next, {
                        nodeId: spec.nodeId,
                        nodeKind: 'process_step',
                        processType: 'operation',
                        name: spec.name,
                        position: spec.position,
                    });
                });
                next = runtime.addEdge(next, {
                    edgeId: 'marquee-edge-a-b',
                    from: { nodeId: 'marquee-a', port: 'out' },
                    to: { nodeId: 'marquee-b', port: 'in' },
                    kind: 'precedence',
                });
                editor.commitMutation(next);
                editor.transform = { x: 40, y: 40, scale: 0.8 };
                editor.applyTransform();
            }
            """
        )
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
            " && document.querySelectorAll('.pm-node').length === 3"
        )
        select_mode = page.locator(".pm-canvas-mode-button[data-canvas-mode='select']")
        pan_mode = page.locator(".pm-canvas-mode-button[data-canvas-mode='pan']")
        record(
            "canvas_exposes_cursor_and_hand_modes_with_select_as_default",
            select_mode.count() == 1
            and pan_mode.count() == 1
            and select_mode.get_attribute("aria-pressed") == "true"
            and pan_mode.get_attribute("aria-pressed") == "false",
        )

        pan_mode.click()
        pan_before = page.evaluate(
            """
            () => ({
                transform: { ...window.__processMapFlow.editor.transform },
                positions: window.__processMapFlow.editor.processMap.canvasNodes
                    .map(node => ({ nodeId: node.nodeId, position: { ...node.position } })),
            })
            """
        )
        viewport_box = page.locator(".pm-viewport").bounding_box()
        pan_start = {
            "x": viewport_box["x"] + viewport_box["width"] - 130,
            "y": viewport_box["y"] + 90,
        }
        page.mouse.move(pan_start["x"], pan_start["y"])
        page.mouse.down()
        page.mouse.move(pan_start["x"] - 65, pan_start["y"] + 45, steps=6)
        page.mouse.up()
        pan_after = page.evaluate(
            """
            () => ({
                transform: { ...window.__processMapFlow.editor.transform },
                positions: window.__processMapFlow.editor.processMap.canvasNodes
                    .map(node => ({ nodeId: node.nodeId, position: { ...node.position } })),
            })
            """
        )
        record(
            "hand_mode_pans_without_moving_process_cards",
            pan_after["transform"] != pan_before["transform"]
            and pan_after["positions"] == pan_before["positions"]
            and pan_mode.get_attribute("aria-pressed") == "true",
            {"before": pan_before, "after": pan_after},
        )
        page.locator(".pm-node[data-node-id='marquee-a'] .pm-node-card").click()
        record(
            "hand_mode_click_does_not_select_or_edit_a_card",
            page.evaluate(
                "window.__processMapFlow.editor.selectedNodeIds.size === 0"
                " && window.__processMapFlow.editor.selectedEdgeIds.size === 0"
            ),
        )

        select_mode.click()
        page.locator(".pm-viewport").focus()
        page.keyboard.down("Space")
        temporary_pan = page.evaluate(
            "window.__processMapFlow.editor._effectiveCanvasInteractionMode()"
        )
        page.keyboard.up("Space")
        restored_mode = page.evaluate(
            "window.__processMapFlow.editor._effectiveCanvasInteractionMode()"
        )
        record(
            "space_temporarily_activates_pan_without_changing_selected_mode",
            temporary_pan == "pan"
            and restored_mode == "select"
            and select_mode.get_attribute("aria-pressed") == "true",
            {"during": temporary_pan, "after": restored_mode},
        )

        page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                editor.transform = { x: 40, y: 40, scale: 0.8 };
                editor.applyTransform();
            }
            """
        )
        first_box = page.locator(".pm-node[data-node-id='marquee-a']").bounding_box()
        second_box = page.locator(".pm-node[data-node-id='marquee-b']").bounding_box()
        selection_start = {
            "x": min(first_box["x"], second_box["x"]) - 18,
            "y": min(first_box["y"], second_box["y"]) - 18,
        }
        selection_end = {
            "x": max(first_box["x"] + first_box["width"], second_box["x"] + second_box["width"]) + 18,
            "y": max(first_box["y"] + first_box["height"], second_box["y"] + second_box["height"]) + 18,
        }
        page.mouse.move(selection_start["x"], selection_start["y"])
        page.mouse.down()
        page.mouse.move(selection_end["x"], selection_end["y"], steps=10)
        marquee_visible_during_drag = page.locator(".pm-selection-marquee:visible").count() == 1
        page.mouse.up()
        marquee_selection = page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                return {
                    nodeIds: Array.from(editor.selectedNodeIds).sort(),
                    edgeIds: Array.from(editor.selectedEdgeIds).sort(),
                    groupId: editor.selectedGroupId,
                    deleteDisabled: editor.deleteButton.disabled,
                };
            }
            """
        )
        page.screenshot(
            path=str(OUT_DIR / "process_flow_marquee_selection.png"),
            full_page=False,
        )
        record(
            "cursor_marquee_selects_every_touched_card_and_wire_but_no_group",
            marquee_visible_during_drag
            and marquee_selection["nodeIds"] == ["marquee-a", "marquee-b"]
            and marquee_selection["edgeIds"] == ["marquee-edge-a-b"]
            and marquee_selection["groupId"] is None
            and not marquee_selection["deleteDisabled"]
            and page.locator(".pm-node.selected").count() == 2
            and page.locator(".pm-edge.selected[data-edge-id='marquee-edge-a-b']").count() == 1,
            marquee_selection,
        )

        history_before_delete = page.evaluate(
            "window.__processMapFlow.editor.history.undoStack.length"
        )
        page.locator("[data-process-map-command='processDelete']").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 0"
        )
        deletion_result = page.evaluate(
            """
            () => ({
                nodeIds: window.__processMapFlow.editor.processMap.canvasNodes
                    .map(node => node.nodeId),
                historyDepth: window.__processMapFlow.editor.history.undoStack.length,
            })
            """
        )
        record(
            "delete_removes_the_full_marquee_selection_in_one_history_step",
            deletion_result["nodeIds"] == ["marquee-c"]
            and deletion_result["historyDepth"] == history_before_delete + 1,
            deletion_result,
        )
        page.get_by_role("button", name="Undo process-map edit").click()
        page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        record(
            "one_undo_restores_the_complete_marquee_deletion",
            page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes"
                ".map(node => node.nodeId).sort().join(',')"
            ) == "marquee-a,marquee-b,marquee-c",
        )
        context.close()

        # -- Multi-occurrence source-tree selection and atomic drag/drop --

        multi_store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        multi_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        multi_page = multi_context.new_page()
        _install_cached_three_route(multi_page)
        multi_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(multi_page, multi_store)
        _install_synthetic_map_management_routes(multi_page, multi_store)
        _install_synthetic_suggestion_route(multi_page, multi_store)
        def multi_status_handler(enabled: bool):
            def handler(route) -> None:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "enabled": enabled}),
                )

            return handler

        for status_route, enabled in (
            ("process-map-spatial-placement-status", True),
            ("process-map-spatial-analysis-status", True),
            ("process-map-auto-routing-status", False),
            ("process-map-agent-layout-write-status", False),
        ):
            multi_page.route(
                f"**/api/training/{status_route}",
                multi_status_handler(enabled),
            )
        multi_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(multi_page)
        _expand(multi_page, "module-a")
        _expand(multi_page, "module-b")

        part_a_1_row = multi_page.locator(
            ".pm-tree-row[data-occurrence-id='part-a-1']"
        )
        part_a_2_row = multi_page.locator(
            ".pm-tree-row[data-occurrence-id='part-a-2']"
        )
        part_b_row = multi_page.locator(
            ".pm-tree-row[data-occurrence-id='part-b']"
        )
        part_a_1_row.click(modifiers=["Control"])
        part_a_2_row.click(modifiers=["Control"])
        part_b_row.click(modifiers=["Control"])
        selected_before_toggle = multi_page.evaluate(
            "Array.from(window.__processMapFlow.editor.selectedOccurrenceIds).sort()"
        )
        part_a_2_row.click(modifiers=["Control"])
        selected_after_toggle = multi_page.evaluate(
            "Array.from(window.__processMapFlow.editor.selectedOccurrenceIds).sort()"
        )
        part_a_2_row.click(modifiers=["Control"])
        part_a_1_row.click()
        selected_after_plain_click = multi_page.evaluate(
            "Array.from(window.__processMapFlow.editor.selectedOccurrenceIds).sort()"
        )
        part_a_2_row.click(modifiers=["Control"])
        part_b_row.click(modifiers=["Control"])
        record(
            "ctrl_click_toggles_tree_occurrences_and_plain_click_resets_selection",
            selected_before_toggle == ["part-a-1", "part-a-2", "part-b"]
            and selected_after_toggle == ["part-a-1", "part-b"]
            and selected_after_plain_click == ["part-a-1"]
            and multi_page.locator(".pm-tree-row.selected").count() == 3
            and multi_page.locator(".pm-structure-tree").get_attribute(
                "aria-multiselectable"
            ) == "true",
            {
                "beforeToggle": selected_before_toggle,
                "afterToggle": selected_after_toggle,
                "afterPlainClick": selected_after_plain_click,
            },
        )

        multi_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const grouped = InspectorProProcessMap.addGroup(editor.processMap, {
                    groupId: 'multi-drop-group',
                    label: 'Multi-drop group',
                    colorKey: 'blue',
                    collapsed: false,
                    position: { x: -50, y: 0 },
                    size: { width: 900, height: 650 },
                    memberNodeIds: [],
                });
                editor.commitMutation(grouped);
                editor.transform = { x: 40, y: 30, scale: 1.2 };
                editor.applyTransform();
                editor.structureTree.addEventListener('dragstart', event => {
                    window.__multiTreeDragPayload = event.dataTransfer.getData(
                        'application/x-inspectorpro-occurrences'
                    );
                }, { once: true });
            }
            """
        )
        history_before_multi_drop = multi_page.evaluate(
            "window.__processMapFlow.editor.history.undoStack.length"
        )
        multi_viewport = multi_page.locator(".pm-viewport")
        world_drop = {"x": 300.0, "y": 250.0}
        transform = multi_page.evaluate(
            "({ ...window.__processMapFlow.editor.transform })"
        )
        multi_target = {
            "x": transform["x"] + world_drop["x"] * transform["scale"],
            "y": transform["y"] + world_drop["y"] * transform["scale"],
        }
        multi_page.keyboard.down("Control")
        part_a_1_row.drag_to(
            multi_viewport,
            target_position=multi_target,
            force=True,
        )
        multi_page.keyboard.up("Control")
        multi_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
        )
        multi_drop_state = multi_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const nodes = editor.processMap.canvasNodes;
                const group = editor.processMap.canvasGroups.find(
                    item => item.groupId === 'multi-drop-group'
                );
                const overlaps = (left, right) => (
                    left.position.x < right.position.x + InspectorProProcessMap.NODE_WIDTH
                    && left.position.x + InspectorProProcessMap.NODE_WIDTH > right.position.x
                    && left.position.y < right.position.y + InspectorProProcessMap.NODE_HEIGHT
                    && left.position.y + InspectorProProcessMap.NODE_HEIGHT > right.position.y
                );
                return {
                    sourceIds: nodes.map(node => node.sourceOccurrenceId).sort(),
                    nodeIds: nodes.map(node => node.nodeId).sort(),
                    groupMembers: group.memberNodeIds.slice().sort(),
                    selectedCanvasNodes: Array.from(editor.selectedNodeIds).sort(),
                    selectedTreeOccurrences: Array.from(editor.selectedOccurrenceIds).sort(),
                    historyDepth: editor.history.undoStack.length,
                    overlaps: nodes.some((node, index) => nodes.slice(index + 1).some(
                        other => overlaps(node, other)
                    )),
                    payload: JSON.parse(window.__multiTreeDragPayload || '[]'),
                };
            }
            """
        )
        record(
            "ctrl_drag_places_selected_occurrences_as_one_non_overlapping_grouped_batch",
            multi_drop_state["sourceIds"] == ["part-a-1", "part-a-2", "part-b"]
            and multi_drop_state["groupMembers"] == multi_drop_state["nodeIds"]
            and multi_drop_state["selectedCanvasNodes"] == multi_drop_state["nodeIds"]
            and multi_drop_state["selectedTreeOccurrences"]
            == ["part-a-1", "part-a-2", "part-b"]
            and multi_drop_state["historyDepth"] == history_before_multi_drop + 1
            and multi_drop_state["overlaps"] is False
            and multi_drop_state["payload"] == ["part-a-1", "part-a-2", "part-b"],
            multi_drop_state,
        )
        multi_page.screenshot(
            path=str(OUT_DIR / "process_flow_multi_tree_drop.png"),
            full_page=False,
        )

        multi_page.get_by_role("button", name="Undo process-map edit").click()
        multi_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 0"
        )
        record(
            "one_undo_removes_the_complete_multi_occurrence_drop",
            multi_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasGroups[0]"
                ".memberNodeIds.length === 0"
            ),
        )
        multi_page.get_by_role("button", name="Redo process-map edit").click()
        multi_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
        )
        multi_page.get_by_role("button", name="Save process map").click()
        multi_page.wait_for_function("!window.__processMapFlow.editor.dirty")
        multi_page.reload(wait_until="networkidle")
        _open_process_flow(multi_page)
        multi_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
        )
        record(
            "multi_occurrence_drop_survives_save_and_reload_with_group_membership",
            multi_page.evaluate(
                """
                () => {
                    const map = window.__processMapFlow.editor.processMap;
                    const nodeIds = map.canvasNodes.map(node => node.nodeId).sort();
                    const group = map.canvasGroups.find(
                        item => item.groupId === 'multi-drop-group'
                    );
                    return group && JSON.stringify(group.memberNodeIds.slice().sort())
                        === JSON.stringify(nodeIds);
                }
                """
            ),
        )

        _expand(multi_page, "module-a")
        _expand(multi_page, "module-b")
        for occurrence_id in ("part-a-1", "part-a-2", "part-b"):
            multi_page.locator(
                f".pm-tree-row[data-occurrence-id='{occurrence_id}']"
            ).click(modifiers=["Control"])
        duplicate_history = multi_page.evaluate(
            "window.__processMapFlow.editor.history.undoStack.length"
        )
        _drag_tree_item(multi_page, "part-a-1", 400, 400)
        record(
            "repeating_a_multi_drop_selects_existing_cards_without_duplicates",
            multi_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
                " && window.__processMapFlow.editor.selectedNodeIds.size === 3"
                " && window.__processMapFlow.editor.history.undoStack.length === 0"
            )
            and duplicate_history == 0
            and "already on the map"
            in multi_page.locator(".pm-editor-status").inner_text().lower(),
        )
        multi_context.close()

        # -- Ctrl-drag duplicates cards without moving the source --

        duplicate_store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        duplicate_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        duplicate_page = duplicate_context.new_page()
        _install_cached_three_route(duplicate_page)
        duplicate_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(duplicate_page, duplicate_store)
        _install_synthetic_map_management_routes(duplicate_page, duplicate_store)
        _install_synthetic_suggestion_route(duplicate_page, duplicate_store)
        duplicate_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(duplicate_page)
        duplicate_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                let map = InspectorProProcessMap.addCanvasNode(editor.processMap, {
                    nodeId: 'duplicate-stage-source',
                    nodeKind: 'process_step',
                    processType: 'operation',
                    name: 'Install repeated bracket',
                    note: 'Use fixture A',
                    properties: { duration: '6 min' },
                    position: { x: 100, y: 80 },
                });
                map = InspectorProProcessMap.addCanvasNode(map, {
                    nodeId: 'duplicate-part-source',
                    nodeKind: 'product_occurrence',
                    sourceOccurrenceId: 'part-a-1',
                    itemIdSnapshot: 'RB-003',
                    nameSnapshot: 'Repeated Part A',
                    position: { x: 100, y: 360 },
                });
                editor.commitMutation(map);
                editor.history.clear();
            }
            """
        )

        def ctrl_drag_canvas_card(node_id: str, dx: float, dy: float) -> dict:
            card = duplicate_page.locator(
                f".pm-node[data-node-id='{node_id}'] .pm-node-card"
            )
            bounds = card.bounding_box()
            assert bounds is not None
            start_x = bounds["x"] + bounds["width"] / 2
            start_y = bounds["y"] + bounds["height"] / 2
            duplicate_page.keyboard.down("Control")
            duplicate_page.mouse.move(start_x, start_y)
            duplicate_page.mouse.down()
            duplicate_page.mouse.move(start_x + dx / 2, start_y + dy / 2, steps=3)
            ghost_visible = duplicate_page.locator(
                ".pm-duplicate-drag-ghost"
            ).count() == 1
            duplicate_page.mouse.move(start_x + dx, start_y + dy, steps=3)
            duplicate_page.mouse.up()
            duplicate_page.keyboard.up("Control")
            return {"ghostVisible": ghost_visible, "sourceBounds": bounds}

        stage_source_before = duplicate_page.evaluate(
            "({ ...window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === 'duplicate-stage-source').position })"
        )
        stage_drag = ctrl_drag_canvas_card("duplicate-stage-source", 380, 40)
        duplicate_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
        )
        stage_duplicate_state = duplicate_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const source = editor.processMap.canvasNodes.find(
                    node => node.nodeId === 'duplicate-stage-source'
                );
                const copy = editor.processMap.canvasNodes.find(
                    node => node.nodeKind === 'process_step'
                        && node.nodeId !== 'duplicate-stage-source'
                );
                return {
                    sourcePosition: source.position,
                    copy,
                    selected: Array.from(editor.selectedNodeIds),
                    historyDepth: editor.history.undoStack.length,
                    ghostCount: document.querySelectorAll('.pm-duplicate-drag-ghost').length,
                };
            }
            """
        )
        record(
            "ctrl_drag_duplicates_a_stage_without_moving_the_source",
            stage_drag["ghostVisible"]
            and stage_duplicate_state["sourcePosition"] == stage_source_before
            and stage_duplicate_state["copy"]["name"] == "Install repeated bracket"
            and stage_duplicate_state["copy"]["note"] == "Use fixture A"
            and stage_duplicate_state["copy"]["properties"] == {"duration": "6 min"}
            and stage_duplicate_state["selected"] == [stage_duplicate_state["copy"]["nodeId"]]
            and stage_duplicate_state["historyDepth"] == 1
            and stage_duplicate_state["ghostCount"] == 0,
            stage_duplicate_state,
        )
        duplicate_page.get_by_role("button", name="Undo process-map edit").click()
        duplicate_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 2"
        )
        duplicate_page.get_by_role("button", name="Redo process-map edit").click()
        duplicate_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 3"
        )
        record(
            "one_undo_and_redo_round_trips_the_ctrl_drag_duplicate",
            duplicate_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes"
                ".filter(node => node.nodeKind === 'process_step').length === 2"
            ),
        )

        part_source_before = duplicate_page.evaluate(
            "({ ...window.__processMapFlow.editor.processMap.canvasNodes"
            ".find(node => node.nodeId === 'duplicate-part-source').position })"
        )
        product_drag = ctrl_drag_canvas_card("duplicate-part-source", 380, 20)
        duplicate_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
        )
        product_duplicate_state = duplicate_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const products = editor.processMap.canvasNodes.filter(
                    node => node.nodeKind === 'product_occurrence'
                );
                return {
                    sourcePosition: products.find(
                        node => node.nodeId === 'duplicate-part-source'
                    ).position,
                    occurrenceIds: products.map(node => node.sourceOccurrenceId).sort(),
                    nodeIds: products.map(node => node.nodeId),
                    selected: Array.from(editor.selectedNodeIds),
                    historyDepth: editor.history.undoStack.length,
                };
            }
            """
        )
        record(
            "ctrl_drag_product_copy_uses_the_next_matching_physical_occurrence",
            product_drag["ghostVisible"]
            and product_duplicate_state["sourcePosition"] == part_source_before
            and product_duplicate_state["occurrenceIds"] == ["part-a-1", "part-a-2"]
            and product_duplicate_state["selected"][0]
                in product_duplicate_state["nodeIds"]
            and product_duplicate_state["historyDepth"] == 2,
            product_duplicate_state,
        )
        before_refused_copy = duplicate_page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.length"
        )
        refused_drag = ctrl_drag_canvas_card("duplicate-part-source", 0, 180)
        record(
            "ctrl_drag_refuses_to_duplicate_one_physical_occurrence_twice",
            refused_drag["ghostVisible"] is False
            and duplicate_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == before_refused_copy
            and "no additional unplaced occurrence"
                in duplicate_page.locator(".pm-editor-status").inner_text().lower(),
        )
        duplicate_page.get_by_role("button", name="Save process map").click()
        duplicate_page.wait_for_function("!window.__processMapFlow.editor.dirty")
        duplicate_page.reload(wait_until="networkidle")
        _open_process_flow(duplicate_page)
        record(
            "ctrl_drag_duplicates_survive_save_and_reload",
            duplicate_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
                " && window.__processMapFlow.editor.processMap.canvasNodes"
                ".filter(node => node.nodeKind === 'product_occurrence').length === 2"
            ),
        )
        duplicate_page.screenshot(
            path=str(OUT_DIR / "process_flow_ctrl_drag_duplicate.png"),
            full_page=False,
        )
        duplicate_context.close()

        # -- Phase 3: deterministic incremental placement and ghost previews --

        spatial_store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        spatial_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        spatial_page = spatial_context.new_page()
        _install_cached_three_route(spatial_page)
        spatial_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(spatial_page, spatial_store)
        _install_synthetic_map_management_routes(spatial_page, spatial_store)
        _install_synthetic_suggestion_route(spatial_page, spatial_store)
        spatial_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(spatial_page)

        def placement_plan_state():
            return spatial_page.evaluate(
                """() => {
                    const editor = window.__processMapFlow.editor;
                    return {
                        hasPlan: !!editor.placementPlan,
                        candidateCount: editor.placementPlan
                            ? editor.placementPlan.candidates.length : 0,
                        activeIndex: editor.placementPlan ? editor.placementPlan.activeIndex : null,
                        nodeCount: editor.processMap.canvasNodes.length,
                        dirty: editor.dirty,
                    };
                }"""
            )

        _expand(spatial_page, "module-a")
        _expand(spatial_page, "module-b")
        _drag_tree_item(spatial_page, "part-a-1", 300, 240)
        spatial_page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 1")
        record(
            "phase3_new_unplaced_occurrence_starts_with_no_card",
            spatial_page.locator(".pm-node[data-node-id]").count() == 1
            and spatial_page.locator(".pm-placement-ghost").count() == 0,
        )

        suggest_button = spatial_page.locator(
            ".pm-tree-row[data-occurrence-id='part-a-2'] .pm-tree-suggest-position"
        )
        assert suggest_button.count() == 1
        before_click_nodes = placement_plan_state()["nodeCount"]
        suggest_button.click()
        spatial_page.wait_for_selector(".pm-placement-ghost")
        after_ghost_state = placement_plan_state()
        record(
            "phase3_no_card_exists_before_acceptance",
            after_ghost_state["hasPlan"]
            and after_ghost_state["nodeCount"] == before_click_nodes,
            after_ghost_state,
        )
        ghost_box = spatial_page.locator(".pm-placement-ghost").bounding_box()
        ghost_viewport_box = spatial_page.locator(".pm-viewport").bounding_box()
        ghost_visible = (
            ghost_box is not None
            and ghost_viewport_box is not None
            and ghost_box["x"] >= ghost_viewport_box["x"]
            and ghost_box["y"] >= ghost_viewport_box["y"]
            and ghost_box["x"] + ghost_box["width"]
                <= ghost_viewport_box["x"] + ghost_viewport_box["width"]
            and ghost_box["y"] + ghost_box["height"]
                <= ghost_viewport_box["y"] + ghost_viewport_box["height"]
        )
        record(
            "phase3_ghost_preview_screenshot",
            ghost_visible
            and spatial_page.locator(".pm-placement-ghost-metrics").count() == 1,
            {
                "ghost": ghost_box,
                "viewport": ghost_viewport_box,
                "metrics": spatial_page.locator(".pm-placement-ghost-metrics").inner_text(),
            },
        )
        spatial_page.screenshot(path=str(OUT_DIR / "process_flow_placement_ghost_light.png"))

        ghost_box_before_zoom = spatial_page.locator(".pm-placement-ghost").bounding_box()
        node_box_before_zoom = spatial_page.locator(".pm-node[data-node-id]").first.bounding_box()
        viewport_box = spatial_page.locator(".pm-viewport").bounding_box()
        zoom_point = {
            "x": viewport_box["x"] + viewport_box["width"] / 2,
            "y": viewport_box["y"] + viewport_box["height"] / 2,
        }
        spatial_page.mouse.move(zoom_point["x"], zoom_point["y"])
        spatial_page.mouse.wheel(0, -240)
        spatial_page.wait_for_timeout(150)
        ghost_box_after_zoom = spatial_page.locator(".pm-placement-ghost").bounding_box()
        node_box_after_zoom = spatial_page.locator(".pm-node[data-node-id]").first.bounding_box()
        ghost_scale = (
            ghost_box_after_zoom["width"] / ghost_box_before_zoom["width"]
            if ghost_box_before_zoom["width"]
            else 0
        )
        node_scale = (
            node_box_after_zoom["width"] / node_box_before_zoom["width"]
            if node_box_before_zoom["width"]
            else 0
        )
        record(
            "phase3_ghost_follows_pan_and_zoom",
            spatial_page.evaluate("!!window.__processMapFlow.editor.placementPlan")
            and abs(ghost_scale - node_scale) < 0.02
            and abs(ghost_scale - 1.0) > 0.01,
            {"ghostScale": ghost_scale, "nodeScale": node_scale},
        )

        state_before_alt = placement_plan_state()
        map_json_before_alt = spatial_page.evaluate(
            "JSON.stringify(window.__processMapFlow.editor.processMap)"
        )
        if state_before_alt["candidateCount"] > 1:
            alt_button = spatial_page.get_by_role("button", name="Cycle to the next suggested position")
            alt_button.click()
            spatial_page.wait_for_timeout(150)
            state_after_alt = placement_plan_state()
            map_json_after_alt = spatial_page.evaluate(
                "JSON.stringify(window.__processMapFlow.editor.processMap)"
            )
            record(
                "phase3_alternative_changes_preview_but_not_map_state",
                state_after_alt["activeIndex"] != state_before_alt["activeIndex"]
                and state_after_alt["nodeCount"] == state_before_alt["nodeCount"]
                and state_after_alt["dirty"] == state_before_alt["dirty"]
                and map_json_after_alt == map_json_before_alt
                and spatial_page.locator(".pm-placement-ghost").count() == 1,
                {"before": state_before_alt, "after": state_after_alt},
            )
        else:
            record("phase3_alternative_changes_preview_but_not_map_state", True, "single_candidate_only")

        dirty_before_dismiss = placement_plan_state()["dirty"]
        dismiss_button = spatial_page.get_by_role(
            "button", name="Discard this suggestion without changing the map"
        )
        dismiss_button.click()
        spatial_page.wait_for_function("!window.__processMapFlow.editor.placementPlan")
        dismiss_state = placement_plan_state()
        record(
            "phase3_dismiss_leaves_map_unchanged",
            spatial_page.locator(".pm-placement-ghost").count() == 0
            and dismiss_state["nodeCount"] == before_click_nodes
            and dismiss_state["dirty"] == dirty_before_dismiss,
            dismiss_state,
        )

        suggest_button.click()
        spatial_page.wait_for_selector(".pm-placement-ghost")
        tampered_accept = spatial_page.evaluate(
            """async () => {
                const editor = window.__processMapFlow.editor;
                const candidate = editor.placementPlan.candidates[editor.placementPlan.activeIndex];
                candidate.position = { x: 123456, y: -98765 };
                const accepted = await editor.acceptPlacementPlan();
                return {
                    accepted,
                    nodeCount: editor.processMap.canvasNodes.length,
                    hasPlan: !!editor.placementPlan,
                };
            }"""
        )
        record(
            "phase3_accept_rejects_candidate_geometry_not_returned_by_fresh_planner",
            tampered_accept["accepted"] is False
            and tampered_accept["nodeCount"] == before_click_nodes
            and tampered_accept["hasPlan"] is False,
            tampered_accept,
        )

        suggest_button.click()
        spatial_page.wait_for_selector(".pm-placement-ghost")
        candidate_position = spatial_page.evaluate(
            "() => { const editor = window.__processMapFlow.editor; "
            "const plan = editor.placementPlan; "
            "return plan.candidates[plan.activeIndex].position; }"
        )
        accept_button = spatial_page.get_by_role("button", name="Place the card at this position")
        accept_button.click()
        spatial_page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")
        accepted_state = spatial_page.evaluate(
            """() => {
                const nodes = window.__processMapFlow.editor.processMap.canvasNodes;
                const placed = nodes.find(n => n.sourceOccurrenceId === 'part-a-2');
                return placed ? { position: placed.position, historyDepth:
                    window.__processMapFlow.editor.history.undoStack.length } : null;
            }"""
        )
        record(
            "phase3_accept_creates_one_card_at_exact_candidate_position",
            accepted_state is not None
            and accepted_state["position"]["x"] == candidate_position["x"]
            and accepted_state["position"]["y"] == candidate_position["y"]
            and spatial_page.locator(".pm-placement-ghost").count() == 0,
            {"accepted": accepted_state, "candidate": candidate_position},
        )

        spatial_page.get_by_role("button", name="Undo process-map edit").click()
        spatial_page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 1")
        record(
            "phase3_undo_removes_the_entire_accepted_placement",
            spatial_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.some(n => n.sourceOccurrenceId === 'part-a-2')"
            ) is False,
        )

        # Re-accept so the map has two placed cards for the lock scenario.
        suggest_button.click()
        spatial_page.wait_for_selector(".pm-placement-ghost")
        spatial_page.get_by_role("button", name="Place the card at this position").click()
        spatial_page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")

        placed_node_ids = spatial_page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.map(n => n.nodeId)"
        )
        # The placement preview may pan just enough to reveal the accepted
        # candidate, so exercise locking on that newly visible card.
        lock_target_id = placed_node_ids[-1]
        spatial_page.wait_for_timeout(300)
        spatial_page.locator(f".pm-node[data-node-id='{lock_target_id}'] .pm-node-card").click(
            position={"x": 8, "y": 8}
        )
        spatial_page.wait_for_selector(
            f".pm-node[data-node-id='{lock_target_id}'].selected"
        )
        spatial_page.wait_for_selector("button[aria-label='Lock card position']", state="visible")
        spatial_page.get_by_role("button", name="Lock card position").click()
        spatial_page.wait_for_function(
            f"window.__processMapFlow.editor.processMap.canvasNodes"
            f".find(n => n.nodeId === '{lock_target_id}').locked === true"
        )
        record(
            "phase3_locked_card_shows_visible_lock_state",
            spatial_page.locator(f".pm-node[data-node-id='{lock_target_id}'].position-locked").count() == 1
            and spatial_page.locator(
                f".pm-node[data-node-id='{lock_target_id}'] .pm-node-lock-indicator"
            ).count() == 1,
        )
        position_before_drag = spatial_page.evaluate(
            f"window.__processMapFlow.editor.processMap.canvasNodes"
            f".find(n => n.nodeId === '{lock_target_id}').position"
        )
        locked_box = spatial_page.locator(f".pm-node[data-node-id='{lock_target_id}']").bounding_box()
        spatial_page.mouse.move(
            locked_box["x"] + locked_box["width"] / 2, locked_box["y"] + locked_box["height"] / 2
        )
        spatial_page.mouse.down()
        spatial_page.mouse.move(locked_box["x"] + 220, locked_box["y"] + 160, steps=6)
        spatial_page.mouse.up()
        position_after_drag = spatial_page.evaluate(
            f"window.__processMapFlow.editor.processMap.canvasNodes"
            f".find(n => n.nodeId === '{lock_target_id}').position"
        )
        record(
            "phase3_locked_cards_cannot_be_moved_by_manual_drag_or_planning",
            position_before_drag == position_after_drag
            and spatial_page.locator(
                f".pm-node[data-node-id='{lock_target_id}'] .pm-card-toolbar-suggest"
            ).count() == 0,
            {"before": position_before_drag, "after": position_after_drag},
        )

        spatial_page.get_by_role("button", name="Save process map").click()
        spatial_page.wait_for_function("!window.__processMapFlow.editor.dirty")
        spatial_page.reload(wait_until="networkidle")
        _open_process_flow(spatial_page)
        spatial_page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 2")
        reload_state = spatial_page.evaluate(
            f"""() => {{
                const node = window.__processMapFlow.editor.processMap.canvasNodes
                    .find(n => n.nodeId === '{lock_target_id}');
                return node ? node.locked === true : false;
            }}"""
        )
        record(
            "phase3_save_reload_preserves_placement_and_lock_state",
            reload_state is True
            and spatial_page.evaluate("window.__processMapFlow.editor.processMap.canvasNodes.length") == 2,
        )

        for theme in ("light", "dark"):
            spatial_page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
            lock_colors = spatial_page.locator(
                f".pm-node[data-node-id='{lock_target_id}'] .pm-node-lock-indicator"
            ).evaluate(
                "el => { const s = getComputedStyle(el); "
                "return { color: s.color, background: s.backgroundColor }; }"
            )
            record(
                f"phase3_lock_indicator_readable_in_{theme}_theme",
                lock_colors["color"] != lock_colors["background"],
                lock_colors,
            )
        spatial_page.screenshot(path=str(OUT_DIR / "process_flow_placement_lock_dark.png"))
        spatial_page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")

        _expand(spatial_page, "module-b")
        rapid_errors_before = len(report["page_errors"])
        for _ in range(4):
            spatial_page.locator(
                ".pm-tree-row[data-occurrence-id='part-b'] .pm-tree-suggest-position"
            ).click()
            spatial_page.wait_for_selector(".pm-placement-ghost")
            spatial_page.get_by_role(
                "button", name="Discard this suggestion without changing the map"
            ).click()
            spatial_page.wait_for_function("!window.__processMapFlow.editor.placementPlan")
        record(
            "phase3_rapid_plan_dismiss_churn_leaves_no_orphan_overlays",
            spatial_page.locator(".pm-placement-ghost").count() == 0
            and spatial_page.locator(".pm-placement-ghost-toolbar").count() == 0
            and len(report["page_errors"]) == rapid_errors_before,
        )

        spatial_context.close()

        # -- Phase 4: obstacle-aware orthogonal routing and shared geometry --

        routing_store = {
            "map": _synthetic_routing_process_map(),
            "structure": _synthetic_structure(),
            "revision": "route-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        routing_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        routing_page = routing_context.new_page()
        _install_cached_three_route(routing_page)
        routing_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(routing_page, routing_store)
        _install_synthetic_map_management_routes(routing_page, routing_store)
        _install_synthetic_suggestion_route(routing_page, routing_store)
        routing_page.route(
            "**/api/training/process-map-spatial-placement-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        routing_page.route(
            "**/api/training/process-map-auto-routing-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": True}),
            ),
        )
        routing_page.route(
            "**/api/training/process-map-agent-layout-write-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        routing_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(routing_page)
        routing_page.wait_for_function(
            "window.__processMapFlow.editor.autoRoutingEnabled === true"
        )
        connection_legend = routing_page.locator(".pm-connection-legend")
        legend_state = {
            "text": connection_legend.inner_text(),
            "items": connection_legend.locator(".pm-connection-legend-item").count(),
            "routeControls": routing_page.locator(
                ".pm-edge-route-mode-button"
            ).count(),
            "routeMode": routing_page.locator(
                ".pm-edge-route-mode-button[data-edge-route-mode='bezier_legacy']"
            ).get_attribute("data-edge-route-mode"),
        }
        record(
            "connection_legend_distinguishes_applied_and_unapplied_proposals",
            legend_state["items"] == 4
            and "Applied connection" in legend_state["text"]
            and "Agent proposal" in legend_state["text"]
            and "Route preview" in legend_state["text"]
            and "Route needs review" in legend_state["text"]
            and legend_state["routeControls"] == 3
            and legend_state["routeMode"] == "bezier_legacy",
            legend_state,
        )

        initial_route_state = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const edge = editor.processMap.canvasEdges.find(item => item.edgeId === 'route-edge');
                const visible = document.querySelector(".pm-edge[data-edge-id='route-edge']");
                return {
                    hasRouting: !!edge.routing,
                    path: visible ? visible.getAttribute('d') : '',
                    historyDepth: editor.history.undoStack.length,
                };
            }
            """
        )
        record(
            "phase4_flag_on_preserves_legacy_curve_until_user_previews_route",
            not initial_route_state["hasRouting"]
            and " C " in initial_route_state["path"],
            initial_route_state,
        )

        routing_page.evaluate("window.__processMapFlow.editor.selectEdge('route-edge')")
        routing_page.get_by_role(
            "button", name="Preview an obstacle-aware orthogonal route"
        ).click()
        routing_page.wait_for_function("!!window.__processMapFlow.editor.routePlan")
        route_preview_state = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const edge = editor.processMap.canvasEdges.find(item => item.edgeId === 'route-edge');
                const preview = document.querySelector('.pm-edge-route-preview');
                return {
                    mapStillLegacy: !edge.routing,
                    previewPath: preview ? preview.getAttribute('d') : '',
                    sourceDimmed: document.querySelector(
                        ".pm-edge[data-edge-id='route-edge']"
                    ).classList.contains('route-preview-source'),
                    mapFingerprint: window.InspectorProProcessMap.mapFingerprint(editor.processMap),
                };
            }
            """
        )
        routing_page.screenshot(path=str(OUT_DIR / "process_flow_route_preview_light.png"))
        record(
            "phase4_route_is_a_nonmutating_orthogonal_ghost_before_acceptance",
            route_preview_state["mapStillLegacy"]
            and " L " in route_preview_state["previewPath"]
            and route_preview_state["sourceDimmed"],
            route_preview_state,
        )

        routing_page.get_by_role(
            "button", name="Apply the previewed obstacle-aware route"
        ).click()
        routing_page.wait_for_function(
            "!window.__processMapFlow.editor.routePlan"
            " && window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
            ".mode === 'orthogonal_auto'"
        )
        accepted_route_state = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const edge = editor.processMap.canvasEdges.find(item => item.edgeId === 'route-edge');
                const visible = document.querySelector(".pm-edge[data-edge-id='route-edge']");
                const hit = document.querySelector(".pm-edge-hit[data-edge-id='route-edge']");
                const scene = window.InspectorProProcessMapSpatial.compileSpatialScene(
                    editor.processMap, { contract: editor._spatialContractCache }
                );
                const diagnostics = window.InspectorProProcessMapSpatial.diagnoseSpatialScene(
                    scene, { contract: editor._spatialContractCache }
                );
                return {
                    mode: edge.routing.mode,
                    routerVersion: edge.routing.routerVersion,
                    fingerprint: edge.routing.obstacleFingerprint,
                    waypoints: edge.routing.waypoints,
                    visiblePath: visible ? visible.getAttribute('d') : '',
                    hitPath: hit ? hit.getAttribute('d') : '',
                    historyDepth: editor.history.undoStack.length,
                    edgeNodeIntersections: diagnostics.metrics.edgeNodeIntersections,
                    staleToolbarCount: document.querySelectorAll(
                        "[data-card-command='accept-route'], [data-card-command='dismiss-route']"
                    ).length,
                };
            }
            """
        )
        record(
            "phase4_accept_commits_one_safe_route_with_matching_visible_and_hit_geometry",
            accepted_route_state["mode"] == "orthogonal_auto"
            and accepted_route_state["routerVersion"] == 1
            and accepted_route_state["historyDepth"] == initial_route_state["historyDepth"] + 1
            and accepted_route_state["visiblePath"] == accepted_route_state["hitPath"]
            and " L " in accepted_route_state["visiblePath"]
            and accepted_route_state["edgeNodeIntersections"] == 0
            and accepted_route_state["staleToolbarCount"] == 0,
            accepted_route_state,
        )

        routing_page.get_by_role("button", name="Undo process-map edit").click()
        routing_page.wait_for_function(
            "!window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
        )
        route_removed_by_undo = routing_page.evaluate(
            "document.querySelector(\".pm-edge[data-edge-id='route-edge']\").getAttribute('d')"
        )
        routing_page.get_by_role("button", name="Redo process-map edit").click()
        routing_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
            ".mode === 'orthogonal_auto'"
        )
        redone_route = routing_page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
        )
        record(
            "phase4_route_apply_is_one_atomic_undo_redo_step",
            " C " in route_removed_by_undo
            and redone_route["obstacleFingerprint"] == accepted_route_state["fingerprint"]
            and redone_route["waypoints"] == accepted_route_state["waypoints"],
            {"undoPath": route_removed_by_undo, "redoRoute": redone_route},
        )

        reroute_committed = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const moved = window.InspectorProProcessMap.moveNode(
                    editor.processMap, 'route-obstacle', { x: 480, y: 520 }
                );
                return editor.commitMutation(moved);
            }
            """
        )
        routing_page.wait_for_function(
            f"window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
            f".obstacleFingerprint !== '{accepted_route_state['fingerprint']}'"
        )
        refreshed_route = routing_page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
        )
        record(
            "phase4_geometry_mutation_invalidates_and_refreshes_auto_route",
            reroute_committed is True
            and refreshed_route["obstacleFingerprint"] != accepted_route_state["fingerprint"],
            refreshed_route,
        )

        routing_page.get_by_role("button", name="Save process map").click()
        routing_page.wait_for_function("!window.__processMapFlow.editor.dirty")
        routing_page.reload(wait_until="networkidle")
        _open_process_flow(routing_page)
        routing_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
            ".mode === 'orthogonal_auto'"
        )
        reloaded_route_state = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const visible = document.querySelector(".pm-edge[data-edge-id='route-edge']");
                const hit = document.querySelector(".pm-edge-hit[data-edge-id='route-edge']");
                return {
                    routing: editor.processMap.canvasEdges[0].routing,
                    dirty: editor.dirty,
                    visiblePath: visible ? visible.getAttribute('d') : '',
                    hitPath: hit ? hit.getAttribute('d') : '',
                };
            }
            """
        )
        record(
            "phase4_save_reload_restores_routed_geometry_without_dirtying_map",
            reloaded_route_state["routing"]["mode"] == "orthogonal_auto"
            and reloaded_route_state["routing"]["obstacleFingerprint"]
                == refreshed_route["obstacleFingerprint"]
            and reloaded_route_state["dirty"] is False
            and reloaded_route_state["visiblePath"] == reloaded_route_state["hitPath"],
            reloaded_route_state,
        )

        routing_page.evaluate("window.__processMapFlow.editor.selectEdge('route-edge')")
        routing_page.get_by_role(
            "button", name="Use a curved Bezier connection"
        ).click()
        routing_page.wait_for_function(
            "!window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
        )
        curved_route_state = routing_page.evaluate(
            """
            () => ({
                path: document.querySelector(
                    ".pm-edge[data-edge-id='route-edge']"
                ).getAttribute('d'),
                historyDepth: window.__processMapFlow.editor.history.undoStack.length,
            })
            """
        )
        record(
            "selected_orthogonal_connection_can_switch_back_to_curve",
            " C " in curved_route_state["path"],
            curved_route_state,
        )
        routing_page.get_by_role("button", name="Undo process-map edit").click()
        routing_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
            ".mode === 'orthogonal_auto'"
        )

        routing_page.get_by_role("button", name="New connections: Orthogonal").click()
        routing_page.wait_for_function(
            "window.__processMapFlow.editor.newEdgeRouteMode === 'orthogonal_auto'"
            " && !window.__processMapFlow.editor.newEdgeRoutingLoading"
        )
        routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const next = window.InspectorProProcessMap.addCanvasNode(
                    editor.processMap,
                    {
                        nodeId: 'route-new-target',
                        nodeKind: 'process_step',
                        processType: 'output',
                        name: 'New routed output',
                        position: { x: 900, y: 580 },
                        portOrientation: 'horizontal',
                        portOrder: 'input_first',
                    }
                );
                editor.commitMutation(next);
            }
            """
        )
        _drag_connection(routing_page, "route-obstacle", "route-new-target")
        routing_page.wait_for_function(
            """
            () => {
                const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(
                    item => item.from.nodeId === 'route-obstacle'
                        && item.to.nodeId === 'route-new-target'
                );
                return edge && edge.routing && edge.routing.mode === 'orthogonal_auto';
            }
            """
        )
        new_orthogonal_connection = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const edge = editor.processMap.canvasEdges.find(
                    item => item.from.nodeId === 'route-obstacle'
                        && item.to.nodeId === 'route-new-target'
                );
                const path = document.querySelector(
                    `.pm-edge[data-edge-id="${edge.edgeId}"]`
                );
                return {
                    mode: edge.routing.mode,
                    path: path && path.getAttribute('d'),
                    preference: editor.newEdgeRouteMode,
                };
            }
            """
        )
        record(
            "new_connection_style_toggle_creates_orthogonal_manual_connections",
            new_orthogonal_connection["mode"] == "orthogonal_auto"
            and new_orthogonal_connection["preference"] == "orthogonal_auto"
            and " L " in new_orthogonal_connection["path"],
            new_orthogonal_connection,
        )

        routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                let next = window.InspectorProProcessMap.addCanvasNode(
                    editor.processMap,
                    {
                        nodeId: 'route-sketch-source',
                        nodeKind: 'process_step',
                        processType: 'operation',
                        name: 'Manual route source',
                        position: { x: 120, y: 760 },
                        portOrientation: 'horizontal',
                        portOrder: 'input_first',
                    }
                );
                next = window.InspectorProProcessMap.addCanvasNode(
                    next,
                    {
                        nodeId: 'route-sketch-target',
                        nodeKind: 'process_step',
                        processType: 'output',
                        name: 'Manual route target',
                        position: { x: 980, y: 760 },
                        portOrientation: 'horizontal',
                        portOrder: 'input_first',
                    }
                );
                editor.commitMutation(next);
                editor.fit();
            }
            """
        )
        routing_page.get_by_role(
            "button", name="Sketch connection with fixed points"
        ).click()
        routing_page.wait_for_function(
            "window.__processMapFlow.editor.newEdgeRouteMode === 'polyline_manual'"
        )
        sketch_history_before = routing_page.evaluate(
            "window.__processMapFlow.editor.history.undoStack.length"
        )
        _sketch_connection(
            routing_page,
            "route-sketch-source",
            "route-sketch-target",
        )
        routing_page.wait_for_function(
            """
            () => {
                const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(
                    item => item.from.nodeId === 'route-sketch-source'
                        && item.to.nodeId === 'route-sketch-target'
                );
                return edge && edge.routing && edge.routing.mode === 'polyline_manual'
                    && edge.routing.waypoints.length === 2;
            }
            """
        )
        manual_edge_state = routing_page.evaluate(
            """
            () => {
                const editor = window.__processMapFlow.editor;
                const edge = editor.processMap.canvasEdges.find(
                    item => item.from.nodeId === 'route-sketch-source'
                        && item.to.nodeId === 'route-sketch-target'
                );
                const path = document.querySelector(
                    `.pm-edge[data-edge-id="${edge.edgeId}"]`
                );
                return {
                    edgeId: edge.edgeId,
                    routing: edge.routing,
                    path: path && path.getAttribute('d'),
                    historyDepth: editor.history.undoStack.length,
                    sketchActive: !!editor.wireSketch,
                };
            }
            """
        )
        record(
            "manual_wire_sketch_commits_fixed_points_as_one_diagonal_polyline",
            manual_edge_state["routing"]["mode"] == "polyline_manual"
            and len(manual_edge_state["routing"]["waypoints"]) == 2
            and "obstacleFingerprint" not in manual_edge_state["routing"]
            and manual_edge_state["historyDepth"] == sketch_history_before + 1
            and manual_edge_state["sketchActive"] is False
            and " L " in manual_edge_state["path"],
            manual_edge_state,
        )

        routing_page.get_by_role("button", name="Undo process-map edit").click()
        routing_page.wait_for_function(
            """
            () => !window.__processMapFlow.editor.processMap.canvasEdges.some(
                item => item.from.nodeId === 'route-sketch-source'
                    && item.to.nodeId === 'route-sketch-target'
            )
            """
        )
        routing_page.get_by_role("button", name="Redo process-map edit").click()
        routing_page.wait_for_function(
            f"""() => window.__processMapFlow.editor.processMap.canvasEdges.some(
                item => item.edgeId === '{manual_edge_state["edgeId"]}'
                    && item.routing && item.routing.mode === 'polyline_manual'
            )"""
        )
        record(
            "manual_wire_sketch_undo_and_redo_restore_the_complete_route",
            routing_page.evaluate(
                f"""() => {{
                    const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(
                        item => item.edgeId === '{manual_edge_state["edgeId"]}'
                    );
                    return edge && edge.routing.waypoints.length === 2;
                }}"""
            ) is True,
        )

        routing_page.evaluate(
            f"window.__processMapFlow.editor.selectEdge('{manual_edge_state['edgeId']}')"
        )
        routing_page.wait_for_selector(".pm-edge-waypoint")
        routing_page.evaluate(
            "window.__processMapFlow.editor._closeCardToolbar('waypoint_test', false)"
        )
        waypoint_history_before = routing_page.evaluate(
            "window.__processMapFlow.editor.history.undoStack.length"
        )
        waypoint_before = routing_page.evaluate(
            f"""() => window.__processMapFlow.editor.processMap.canvasEdges.find(
                edge => edge.edgeId === '{manual_edge_state["edgeId"]}'
            ).routing.waypoints[0]"""
        )
        waypoint_handle = routing_page.locator(
            ".pm-edge-waypoint[data-waypoint-index='0']"
        )
        waypoint_handle.hover()
        waypoint_box = waypoint_handle.bounding_box()
        assert waypoint_box is not None
        routing_page.mouse.move(
            waypoint_box["x"] + waypoint_box["width"] / 2,
            waypoint_box["y"] + waypoint_box["height"] / 2,
        )
        routing_page.mouse.down()
        routing_page.mouse.move(
            waypoint_box["x"] + waypoint_box["width"] / 2 + 42,
            waypoint_box["y"] + waypoint_box["height"] / 2 - 26,
            steps=5,
        )
        routing_page.mouse.up()
        routing_page.wait_for_function(
            f"""() => {{
                const point = window.__processMapFlow.editor.processMap.canvasEdges.find(
                    edge => edge.edgeId === '{manual_edge_state["edgeId"]}'
                ).routing.waypoints[0];
                return point.x !== {waypoint_before["x"]} || point.y !== {waypoint_before["y"]};
            }}"""
        )
        moved_waypoint_state = routing_page.evaluate(
            f"""() => {{
                const editor = window.__processMapFlow.editor;
                return {{
                    point: editor.processMap.canvasEdges.find(
                        edge => edge.edgeId === '{manual_edge_state["edgeId"]}'
                    ).routing.waypoints[0],
                    historyDepth: editor.history.undoStack.length,
                }};
            }}"""
        )
        record(
            "selected_manual_route_exposes_draggable_persisted_waypoints",
            moved_waypoint_state["point"] != waypoint_before
            and moved_waypoint_state["historyDepth"] == waypoint_history_before + 1,
            {"before": waypoint_before, "after": moved_waypoint_state},
        )

        insertion_point = _edge_screen_point(
            routing_page,
            manual_edge_state["edgeId"],
            0.55,
        )
        routing_page.mouse.dblclick(insertion_point["x"], insertion_point["y"])
        routing_page.wait_for_function(
            f"""() => window.__processMapFlow.editor.processMap.canvasEdges.find(
                edge => edge.edgeId === '{manual_edge_state["edgeId"]}'
            ).routing.waypoints.length === 3"""
        )
        record(
            "double_clicking_manual_route_segment_inserts_a_fixed_point",
            routing_page.locator(".pm-edge-waypoint").count() == 3,
        )

        removable = routing_page.locator(
            ".pm-edge-waypoint[data-waypoint-index='1']"
        )
        removable.evaluate("(element) => element.focus()")
        routing_page.keyboard.press("Delete")
        routing_page.wait_for_function(
            f"""() => window.__processMapFlow.editor.processMap.canvasEdges.find(
                edge => edge.edgeId === '{manual_edge_state["edgeId"]}'
            ).routing.waypoints.length === 2"""
        )
        record(
            "delete_removes_only_the_selected_manual_route_point",
            routing_page.evaluate(
                f"""() => window.__processMapFlow.editor.processMap.canvasEdges.find(
                    edge => edge.edgeId === '{manual_edge_state["edgeId"]}'
                ).routing.waypoints.length"""
            ) == 2,
        )

        cancellation_before = routing_page.evaluate(
            "window.InspectorProProcessMap.mapFingerprint("
            "window.__processMapFlow.editor.processMap)"
        )
        source_box = routing_page.locator(
            ".pm-node[data-node-id='route-sketch-source'] .pm-port-out"
        ).bounding_box()
        viewport_box = routing_page.locator(".pm-viewport").bounding_box()
        assert source_box is not None and viewport_box is not None
        routing_page.locator(
            ".pm-node[data-node-id='route-sketch-source'] .pm-port-out"
        ).dispatch_event(
            "pointerdown",
            {
                "button": 0,
                "clientX": source_box["x"] + source_box["width"] / 2,
                "clientY": source_box["y"] + source_box["height"] / 2,
                "pointerId": 601,
            },
        )
        routing_page.locator(".pm-viewport").dispatch_event(
            "pointerdown",
            {
                "button": 0,
                "clientX": viewport_box["x"] + viewport_box["width"] / 2,
                "clientY": viewport_box["y"] + viewport_box["height"] - 80,
                "pointerId": 602,
            },
        )
        routing_page.locator(".pm-viewport").focus()
        routing_page.keyboard.press("Backspace")
        routing_page.keyboard.press("Escape")
        cancellation_after = routing_page.evaluate(
            """
            () => ({
                fingerprint: window.InspectorProProcessMap.mapFingerprint(
                    window.__processMapFlow.editor.processMap
                ),
                sketchActive: !!window.__processMapFlow.editor.wireSketch,
                pendingPaths: document.querySelectorAll('.pm-edge-sketch-pending').length,
            })
            """
        )
        record(
            "backspace_and_escape_cancel_manual_wire_without_mutating_map",
            cancellation_after["fingerprint"] == cancellation_before
            and cancellation_after["sketchActive"] is False
            and cancellation_after["pendingPaths"] == 0,
            cancellation_after,
        )

        routing_page.get_by_role("button", name="Save process map").click()
        routing_page.wait_for_function("!window.__processMapFlow.editor.dirty")
        routing_page.reload(wait_until="networkidle")
        _open_process_flow(routing_page)
        routing_page.wait_for_function(
            f"""() => {{
                const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(
                    item => item.edgeId === '{manual_edge_state["edgeId"]}'
                );
                return edge && edge.routing && edge.routing.mode === 'polyline_manual'
                    && edge.routing.waypoints.length === 2;
            }}"""
        )
        record(
            "manual_route_waypoints_survive_save_and_reload",
            routing_page.evaluate(
                f"""() => {{
                    const edge = window.__processMapFlow.editor.processMap.canvasEdges.find(
                        item => item.edgeId === '{manual_edge_state["edgeId"]}'
                    );
                    return !('obstacleFingerprint' in edge.routing);
                }}"""
            ) is True,
        )
        routing_page.screenshot(
            path=str(OUT_DIR / "process_flow_manual_wire_sketch.png")
        )
        routing_context.close()

        # -- Phase 5: spatialized semantic suggestions and next-card ghosts --

        phase5_map = _synthetic_process_map()
        phase5_map["layoutVersion"] = 3
        phase5_map["canvasNodes"] = [
            {
                "nodeId": "phase5-anchor",
                "nodeKind": "product_occurrence",
                "sourceOccurrenceId": "part-a-1",
                "nameSnapshot": "Repeated Part A",
                "position": {"x": 80, "y": 240},
            },
            {
                "nodeId": "phase5-obstacle",
                "nodeKind": "process_step",
                "processType": "inspection",
                "name": "Unrelated inspection",
                "position": {"x": 480, "y": 190},
            },
            {
                "nodeId": "phase5-target",
                "nodeKind": "process_step",
                "processType": "output",
                "name": "Target output",
                "position": {"x": 900, "y": 240},
            },
        ]
        phase5_map["canvasEdges"] = []
        phase5_map["canvasGroups"] = []
        phase5_connection_id = "pms-phase5-browser-connection"
        phase5_placement_id = "pms-phase5-browser-placement"
        phase5_store = {
            "map": phase5_map,
            "structure": _synthetic_structure(),
            "revision": "phase5-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
            "spatializeSuggestions": True,
            "suggestions": [
                {
                    "suggestionId": phase5_connection_id,
                    "ruleId": "synthetic_sequence",
                    "ruleVersion": "1.0.0",
                    "evidenceFingerprint": "phase5-evidence-connection",
                    "confidence": "high",
                    "edge": {
                        "edgeId": "phase5-connection-edge",
                        "logicalConnectionId": "phase5-connection-edge",
                        "from": {"nodeId": "phase5-anchor", "port": "out"},
                        "to": {"nodeId": "phase5-target", "port": "in"},
                        "kind": "precedence",
                    },
                    "provenance": [{"source": "authored_precedence_pattern"}],
                    "explanation": "Connect the reviewed operation to its output.",
                    "validation": {"wouldCreateCycle": False, "duplicateOfExisting": False},
                    "affectedIds": ["phase5-anchor", "phase5-target"],
                },
                {
                    "suggestionId": phase5_placement_id,
                    "ruleId": "synthetic_next_card",
                    "ruleVersion": "1.0.0",
                    "evidenceFingerprint": "phase5-evidence-placement",
                    "confidence": "high",
                    "placement": {
                        "sourceOccurrenceId": "part-a-2",
                        "nameSnapshot": "Repeated Part A",
                        "itemIdSnapshot": "RB-003",
                        "anchorNodeId": "phase5-anchor",
                        "connectionDirection": "outgoing",
                        "edgeKind": "precedence",
                        "edgeId": "phase5-placement-edge",
                    },
                    "provenance": [{"source": "authored_precedence_pattern"}],
                    "explanation": "Place the next reviewed sibling occurrence.",
                    "validation": {"wouldCreateCycle": False, "duplicateOfExisting": False},
                    "affectedIds": ["phase5-anchor", "part-a-2"],
                },
            ],
        }
        phase5_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        phase5_page = phase5_context.new_page()
        _install_cached_three_route(phase5_page)
        phase5_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(phase5_page, phase5_store)
        _install_synthetic_map_management_routes(phase5_page, phase5_store)
        _install_synthetic_suggestion_route(phase5_page, phase5_store)
        for status_url in (
            "**/api/training/process-map-spatial-placement-status",
            "**/api/training/process-map-auto-routing-status",
            "**/api/training/process-map-agent-layout-write-status",
        ):
            phase5_page.route(
                status_url,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "enabled": True}),
                ),
            )
        phase5_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(phase5_page)
        phase5_page.wait_for_function(
            "window.__processMapFlow.editor.suggestions.length === 2"
        )
        record(
            "phase5_spatialized_connection_and_next_card_are_preview_only",
            phase5_page.locator(".pm-edge-ghost.spatialized").count() == 1
            and phase5_page.locator(".pm-semantic-placement-ghost").count() == 1
            and phase5_page.locator(".pm-semantic-placement-ghost-wire").count() == 1
            and phase5_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 3
            and phase5_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasEdges.length"
            ) == 0
            and phase5_page.evaluate("window.__processMapFlow.editor.dirty") is False,
        )
        spatial_ghost_paths = phase5_page.evaluate(
            """() => Array.from(document.querySelectorAll(
                '.pm-edge-ghost.spatialized, .pm-semantic-placement-ghost-wire'
            )).map(path => path.getAttribute('d'))"""
        )
        record(
            "phase5_ghost_wires_use_exact_orthogonal_proposals",
            len(spatial_ghost_paths) == 2
            and all(" C " not in path and " L " in path for path in spatial_ghost_paths),
            spatial_ghost_paths,
        )
        phase5_page.screenshot(
            path=str(OUT_DIR / "process_flow_spatialized_suggestions.png"),
            full_page=False,
        )
        phase5_page.get_by_role(
            "button", name="Review evidence-backed process-flow suggestions"
        ).click()
        phase5_page.wait_for_selector(".pm-suggestion-panel:not([hidden])")
        record(
            "phase5_unplaced_semantic_target_is_labeled_as_a_next_card",
            phase5_page.locator(
                f".pm-suggestion-item[data-suggestion-id='{phase5_placement_id}']"
            ).filter(has_text="Next card").count() == 1,
        )
        stale_result = phase5_page.evaluate(
            f"""async () => {{
                const editor = window.__processMapFlow.editor;
                const suggestion = editor.suggestions.find(
                    item => item.suggestionId === '{phase5_placement_id}'
                );
                suggestion.spatialProposal.proposalId = 'tampered-proposal';
                const before = JSON.stringify(editor.processMap);
                const accepted = await editor.acceptSuggestion('{phase5_placement_id}');
                return {{ accepted, before, after: JSON.stringify(editor.processMap),
                    suggestionCount: editor.suggestions.length }};
            }}"""
        )
        record(
            "phase5_stale_geometry_is_discarded_without_mutation",
            stale_result["accepted"] is False
            and stale_result["before"] == stale_result["after"]
            and stale_result["suggestionCount"] == 0,
            stale_result,
        )
        phase5_page.evaluate("window.__processMapFlow.editor.loadSuggestions()")
        phase5_page.wait_for_function(
            "window.__processMapFlow.editor.suggestions.length === 2"
        )
        phase5_page.evaluate(
            f"window.__processMapFlow.editor.acceptSuggestion('{phase5_placement_id}')"
        )
        phase5_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 4"
            " && window.__processMapFlow.editor.processMap.canvasEdges.length === 1"
        )
        accepted_phase5 = phase5_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const edge = editor.processMap.canvasEdges[0];
                return {
                    historyDepth: editor.history.undoStack.length,
                    dirty: editor.dirty,
                    edgeRouting: edge.routing,
                    addedOccurrence: editor.processMap.canvasNodes.some(
                        node => node.sourceOccurrenceId === 'part-a-2'
                    ),
                };
            }"""
        )
        record(
            "phase5_accept_next_card_commits_card_and_wire_atomically",
            accepted_phase5["historyDepth"] == 1
            and accepted_phase5["dirty"] is True
            and accepted_phase5["addedOccurrence"] is True
            and accepted_phase5["edgeRouting"]["mode"] == "orthogonal_auto"
            and phase5_page.locator(".pm-semantic-placement-ghost").count() == 0,
            accepted_phase5,
        )
        phase5_page.evaluate("window.__processMapFlow.editor.undo()")
        record(
            "phase5_one_undo_removes_both_the_suggested_card_and_wire",
            phase5_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 3
            and phase5_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasEdges.length"
            ) == 0,
        )
        phase5_context.close()

        phase6_store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "phase6-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
            "spatialEvents": [],
        }
        phase6_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        phase6_page = phase6_context.new_page()
        _install_cached_three_route(phase6_page)
        phase6_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(phase6_page, phase6_store)
        _install_synthetic_map_management_routes(phase6_page, phase6_store)
        _install_synthetic_suggestion_route(phase6_page, phase6_store)
        _install_synthetic_spatial_proposal_routes(phase6_page, phase6_store)
        for status_url in (
            "**/api/training/process-map-spatial-placement-status",
            "**/api/training/process-map-auto-routing-status",
            "**/api/training/process-map-agent-layout-write-status",
        ):
            phase6_page.route(
                status_url,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "enabled": True}),
                ),
            )
        phase6_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(phase6_page)
        proposal_result = phase6_page.evaluate(
            """async () => await window._trainRequestManagedSpatialProposal(
                'propose_process_map_node_placement',
                { targetKind: 'product_occurrence', occurrenceId: 'part-a-1' }
            )"""
        )
        record(
            "phase6_agent_proposal_is_exact_preview_without_map_mutation",
            proposal_result.get("ok") is True
            and proposal_result.get("previewPendingApproval") is True
            and phase6_page.locator(".pm-managed-proposal-ghost").count() == 1
            and phase6_page.locator(".pm-managed-proposal-review:not([hidden])").count() == 1
            and phase6_page.locator(".pm-empty-state:visible").count() == 0
            and phase6_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 0
            and phase6_page.evaluate("window.__processMapFlow.editor.dirty") is False,
            proposal_result,
        )
        phase6_page.screenshot(
            path=str(OUT_DIR / "process_flow_agent_proposal_preview.png"),
            full_page=False,
        )
        phase6_page.locator(".pm-managed-proposal-dismiss").click()
        record(
            "phase6_dismiss_leaves_saved_map_byte_identical",
            phase6_page.locator(".pm-managed-proposal-ghost").count() == 0
            and phase6_page.locator(".pm-managed-proposal-review:not([hidden])").count() == 0
            and phase6_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 0
            and phase6_page.evaluate("window.__processMapFlow.editor.dirty") is False,
        )
        phase6_page.evaluate(
            """async () => await window._trainRequestManagedSpatialProposal(
                'propose_process_map_node_placement',
                { targetKind: 'product_occurrence', occurrenceId: 'part-a-1' }
            )"""
        )
        phase6_page.locator(".pm-managed-proposal-approve").click()
        phase6_page.wait_for_function(
            "window.__processMapFlow.editor.processMap.canvasNodes.length === 1"
            " && window.__processMapFlow.editor.revision === 'phase6-rev-2'"
        )
        applied_phase6 = phase6_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                return {
                    dirty: editor.dirty,
                    historyDepth: editor.history.undoStack.length,
                    nodeIds: editor.processMap.canvasNodes.map(node => node.nodeId),
                    proposalVisible: !!editor.managedProposalPlan,
                };
            }"""
        )
        spatial_events = phase6_store["spatialEvents"]
        approval_event = next(
            (item for item in spatial_events if item["kind"] == "approval"), None
        )
        apply_event = next(
            (item for item in spatial_events if item["kind"] == "apply"), None
        )
        record(
            "phase6_approval_applies_one_bound_diff_and_one_receipt",
            applied_phase6["dirty"] is False
            and applied_phase6["historyDepth"] == 1
            and applied_phase6["nodeIds"] == ["pmn-agent-browser"]
            and applied_phase6["proposalVisible"] is False
            and approval_event is not None
            and apply_event is not None
            and phase6_page.locator("#toastContainer .toast.success").filter(
                has_text="Placed Repeated Part A."
            ).count() == 1
            and approval_event["body"].get("spatialBindingHash") == "b" * 64
            and apply_event["body"].get("spatialBindingHash") == "b" * 64
            and approval_event["body"].get("idempotencyKey")
                == apply_event["body"].get("idempotencyKey"),
            {"editor": applied_phase6, "events": spatial_events},
        )
        phase6_page.evaluate("window.__processMapFlow.editor.undo()")
        record(
            "phase6_one_undo_restores_the_preproposal_map",
            phase6_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 0
            and phase6_page.evaluate("window.__processMapFlow.editor.dirty") is True,
        )
        phase6_context.close()

        semantic_store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "semantic-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
            "semanticEvents": [],
            "builderWriteEnabled": True,
            "semanticProposalDelaySeconds": 3.4,
        }
        semantic_requests: list[dict] = []
        semantic_context = browser.new_context(
            viewport={"width": 1600, "height": 1000}
        )
        semantic_page = semantic_context.new_page()
        _install_cached_three_route(semantic_page)
        semantic_page.on(
            "pageerror", lambda error: report["page_errors"].append(str(error))
        )
        _install_synthetic_process_map_route(semantic_page, semantic_store)
        _install_synthetic_map_management_routes(semantic_page, semantic_store)
        _install_synthetic_suggestion_route(semantic_page, semantic_store)
        _install_synthetic_semantic_proposal_routes(
            semantic_page, semantic_store
        )
        _install_synthetic_agent_route(
            semantic_page, semantic_store, semantic_requests
        )
        for status_url in (
            "**/api/training/process-map-spatial-placement-status",
            "**/api/training/process-map-spatial-analysis-status",
            "**/api/training/process-map-auto-routing-status",
            "**/api/training/process-map-agent-layout-write-status",
            "**/api/training/process-map-semantic-generation-status",
        ):
            semantic_page.route(
                status_url,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "enabled": True}),
                ),
            )
        semantic_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(semantic_page)
        semantic_plan = {
            "schemaVersion": 1,
            "planId": "browser-module-a-plan",
            "scope": {
                "assemblyOccurrenceId": "module-a",
                "label": "Module A",
            },
            "requiredOccurrences": [
                {"occurrenceId": "part-a-1", "quantity": 1},
                {"occurrenceId": "part-a-2", "quantity": 1},
            ],
            "operations": [
                {
                    "id": "op-join-module-a",
                    "operationType": "operation",
                    "label": "Join Module A parts",
                    "inputs": [
                        {"ref": "part-a-1", "type": "occurrence"},
                        {"ref": "part-a-2", "type": "occurrence"},
                    ],
                    "output": {"ref": "module-a", "type": "occurrence"},
                    "branchId": "main",
                    "stageIndex": 1,
                    "knowledgeStatus": "inferred",
                    "evidence": [
                        {
                            "sourceType": "domain_heuristic",
                            "sourceRef": "browser-fixture",
                            "supports": "candidate-operation",
                        }
                    ],
                    "properties": {},
                }
            ],
            "intermediateResults": [],
            "junctions": [
                {
                    "id": "junction-module-a",
                    "junctionType": "parallel_and",
                    "inputs": ["part-a-1", "part-a-2"],
                    "outputs": ["op-join-module-a"],
                    "knowledgeStatus": "inferred",
                    "evidence": [
                        {
                            "sourceType": "domain_heuristic",
                            "sourceRef": "browser-fixture",
                            "supports": "candidate-flow-topology",
                        }
                    ],
                }
            ],
            "branches": [{"id": "main", "label": "Main"}],
            "evidence": [],
            "assumptions": [
                {
                    "id": "review-sequence",
                    "text": "Review the proposed assembly sequence.",
                }
            ],
            "layoutHints": [
                {
                    "ref": "op-join-module-a",
                    "branchId": "main",
                    "stageIndex": 1,
                }
            ],
            "unresolvedQuestions": [],
        }
        semantic_page.unroute("**/api/agent/chat")
        _install_synthetic_semantic_agent_route(
            semantic_page,
            semantic_plan,
            semantic_requests,
        )
        semantic_dialogs: list[str] = []

        def dismiss_unexpected_semantic_dialog(dialog) -> None:
            semantic_dialogs.append(dialog.message)
            dialog.dismiss()

        semantic_page.on("dialog", dismiss_unexpected_semantic_dialog)
        short_generation_prompt = (
            "Build and visually validate a complete Tricycle Assembly process "
            "map. Show one ghost preview and wait for my approval. Do not commit it."
        )
        semantic_page.evaluate(
            "prompt => window._agentContextSendPrompt(prompt)",
            short_generation_prompt,
        )
        semantic_page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow
                    && window.__processMapFlow.editor;
                const messages = Array.from(document.querySelectorAll(
                    '.agent-msg.assistant'
                ));
                return !!(editor && editor.managedProposalPlan)
                    && messages.some(message => message.textContent.includes(
                        'Prepared one complete ghost preview'
                    ));
            }""",
            timeout=30_000,
        )
        semantic_result = semantic_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const proposal = editor.managedProposalPlan;
                const activeTab = document.querySelector(
                    '.tab[aria-selected="true"]'
                );
                const messages = Array.from(document.querySelectorAll(
                    '.agent-msg.assistant'
                ));
                return {
                    ok: !!proposal,
                    previewPendingApproval: !!proposal,
                    semanticBindingHash: proposal && proposal.semanticBindingHash,
                    createdIds: proposal && proposal.createdIds,
                    activeTab: activeTab && activeTab.dataset.tab,
                    assistantText: messages.length
                        ? messages[messages.length - 1].textContent.trim()
                        : '',
                };
            }"""
        )
        semantic_page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                return !!(reveal && reveal.active)
                    && reveal.visibleNodeIds.size > 0
                    && reveal.visibleNodeIds.size < reveal.nodeIds.length
                    && reveal.visibleEdgeIds.size > 0
                    && reveal.visibleEdgeIds.size < reveal.edgeIds.length;
            }""",
            timeout=5_000,
        )
        semantic_progressive_state = semantic_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                window.__semanticProposalForReducedMotion = JSON.parse(
                    JSON.stringify(editor.managedProposalPlan)
                );
                return {
                    status: editor.getAgentState().activeProposal.reveal.status,
                    visibleNodeCount: reveal.visibleNodeIds.size,
                    totalNodeCount: reveal.nodeIds.length,
                    visibleEdgeCount: reveal.visibleEdgeIds.size,
                    totalEdgeCount: reveal.edgeIds.length,
                    pendingElementCount: document.querySelectorAll(
                        '[data-managed-proposal-reveal-state="pending"]'
                    ).length,
                    approveDisabled: document.querySelector(
                        '.pm-managed-proposal-approve'
                    ).disabled,
                    showAllVisible: !document.querySelector(
                        '.pm-managed-proposal-show-all'
                    ).hidden,
                    savedNodeCount: editor.processMap.canvasNodes.length,
                    dirty: editor.dirty,
                };
            }"""
        )
        semantic_page.wait_for_timeout(100)
        semantic_page.screenshot(
            path=str(OUT_DIR / "process_flow_semantic_progressive_build.png"),
            full_page=False,
        )
        record(
            "semantic_generation_progressively_reveals_validated_preview",
            semantic_progressive_state["status"] == "building"
            and 0 < semantic_progressive_state["visibleNodeCount"]
                < semantic_progressive_state["totalNodeCount"]
            and semantic_progressive_state["visibleEdgeCount"]
                > 0
            and semantic_progressive_state["visibleEdgeCount"]
                < semantic_progressive_state["totalEdgeCount"]
            and semantic_progressive_state["pendingElementCount"] > 0
            and semantic_progressive_state["approveDisabled"] is True
            and semantic_progressive_state["showAllVisible"] is True
            and semantic_progressive_state["savedNodeCount"] == 0
            and semantic_progressive_state["dirty"] is False,
            semantic_progressive_state,
        )
        semantic_page.locator(".pm-managed-proposal-show-all").click()
        semantic_page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                return !!(reveal && reveal.completed && !reveal.active)
                    && reveal.visibleNodeIds.size === reveal.nodeIds.length
                    && reveal.visibleEdgeIds.size === reveal.edgeIds.length
                    && !document.querySelector(
                        '.pm-managed-proposal-approve'
                    ).disabled;
            }"""
        )
        semantic_show_all_state = semantic_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                return {
                    status: editor.getAgentState().activeProposal.reveal.status,
                    skipped: reveal.skipped,
                    revealedElementCount: document.querySelectorAll(
                        '[data-managed-proposal-reveal-state="revealed"]'
                    ).length,
                    expectedElementCount:
                        reveal.nodeIds.length + reveal.edgeIds.length,
                    showAllHidden: document.querySelector(
                        '.pm-managed-proposal-show-all'
                    ).hidden,
                    savedNodeCount: editor.processMap.canvasNodes.length,
                    dirty: editor.dirty,
                };
            }"""
        )
        record(
            "semantic_generation_show_all_finishes_without_committing",
            semantic_show_all_state["status"] == "complete"
            and semantic_show_all_state["skipped"] is True
            and semantic_show_all_state["revealedElementCount"]
                == semantic_show_all_state["expectedElementCount"]
            and semantic_show_all_state["showAllHidden"] is True
            and semantic_show_all_state["savedNodeCount"] == 0
            and semantic_show_all_state["dirty"] is False,
            semantic_show_all_state,
        )
        semantic_page.locator(".pm-managed-proposal-dismiss").click()
        semantic_page.wait_for_function(
            "() => !window.__processMapFlow.editor.managedProposalPlan"
        )
        reopened_for_natural_reveal = semantic_page.evaluate(
            """() => window.__processMapFlow.editor.showManagedProposal(
                window.__semanticProposalForReducedMotion
            )"""
        )
        semantic_page.wait_for_function(
            """() => {
                const reveal =
                    window.__processMapFlow.editor.managedProposalReveal;
                return !!(reveal && reveal.active);
            }"""
        )
        semantic_page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                return !!(reveal && reveal.completed && !reveal.active)
                    && reveal.visibleNodeIds.size === reveal.nodeIds.length
                    && reveal.visibleEdgeIds.size === reveal.edgeIds.length;
            }""",
            timeout=10_000,
        )
        semantic_natural_reveal_state = semantic_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                return {
                    completed: reveal.completed,
                    skipped: !!reveal.skipped,
                    pendingElementCount: document.querySelectorAll(
                        '[data-managed-proposal-reveal-state="pending"]'
                    ).length,
                    approveDisabled: document.querySelector(
                        '.pm-managed-proposal-approve'
                    ).disabled,
                    savedNodeCount: editor.processMap.canvasNodes.length,
                    dirty: editor.dirty,
                };
            }"""
        )
        record(
            "semantic_generation_naturally_completes_before_approval",
            reopened_for_natural_reveal is True
            and semantic_natural_reveal_state["completed"] is True
            and semantic_natural_reveal_state["skipped"] is False
            and semantic_natural_reveal_state["pendingElementCount"] == 0
            and semantic_natural_reveal_state["approveDisabled"] is False
            and semantic_natural_reveal_state["savedNodeCount"] == 0
            and semantic_natural_reveal_state["dirty"] is False,
            semantic_natural_reveal_state,
        )
        semantic_page.wait_for_function(
            """() => document.querySelectorAll(
                '.pm-managed-proposal-wire'
            ).length === 4"""
        )
        semantic_page.wait_for_function(
            """() => {
                const viewport = document.querySelector('.pm-viewport')
                    .getBoundingClientRect();
                return Array.from(document.querySelectorAll(
                    '.pm-managed-proposal-wire'
                )).every(path => {
                    const rect = path.getBoundingClientRect();
                    return path.getTotalLength() > 20
                        && rect.right >= viewport.left
                        && rect.left <= viewport.right
                        && rect.bottom >= viewport.top
                        && rect.top <= viewport.bottom;
                });
            }""",
            timeout=10_000,
        )
        semantic_preview_geometry = semantic_page.evaluate(
            """() => {
                const viewport = document.querySelector('.pm-viewport')
                    .getBoundingClientRect();
                const wires = Array.from(document.querySelectorAll(
                    '.pm-managed-proposal-wire'
                ));
                const visibleWires = wires.filter(path => {
                    const rect = path.getBoundingClientRect();
                    return path.getTotalLength() > 20
                        && rect.right >= viewport.left
                        && rect.left <= viewport.right
                        && rect.bottom >= viewport.top
                        && rect.top <= viewport.bottom;
                });
                const svg = document.querySelector(
                    '.pm-placement-ghost-wire-layer'
                );
                return {
                    wireCount: wires.length,
                    visibleWireCount: visibleWires.length,
                    junctionCount: document.querySelectorAll(
                        '.pm-managed-proposal-junction'
                    ).length,
                    svgWidth: Number(svg.getAttribute('width')),
                    svgHeight: Number(svg.getAttribute('height')),
                    viewBox: svg.getAttribute('viewBox'),
                };
            }"""
        )
        record(
            "semantic_generation_shows_one_complete_non_mutating_preview",
            semantic_result.get("ok") is True
            and semantic_result.get("previewPendingApproval") is True
            and semantic_result.get("semanticBindingHash") == "c" * 64
            and len(semantic_result.get("createdIds", {}).get("nodeIds", [])) == 5
            and semantic_result.get("activeTab") == "training"
            and "Prepared one complete ghost preview"
                in semantic_result.get("assistantText", "")
            and "reduced opacity" not in semantic_result.get("assistantText", "")
            and semantic_dialogs == []
            and semantic_page.locator(".pm-managed-proposal-ghost").count() == 4
            and semantic_preview_geometry["junctionCount"] == 1
            and semantic_preview_geometry["wireCount"] == 4
            and semantic_preview_geometry["visibleWireCount"] == 4
            and semantic_preview_geometry["svgWidth"] > 1000
            and semantic_preview_geometry["svgHeight"] > 300
            and semantic_preview_geometry["viewBox"]
            and semantic_page.locator(".pm-managed-proposal-review:not([hidden])").count() == 1
            and semantic_page.locator(
                ".pm-managed-proposal-visual:not([hidden])"
            ).count() == 1
            and "Visual validation applied 2 inferred corrections."
            in semantic_page.locator(".pm-managed-proposal-copy").inner_text()
            and semantic_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 0
            and semantic_page.evaluate("window.__processMapFlow.editor.dirty") is False
            and "coordinates" not in json.dumps(
                semantic_store["semanticEvents"][0]["body"].get(
                    "semanticPlan", {}
                )
            ),
            {
                "result": semantic_result,
                "events": semantic_store["semanticEvents"],
                "geometry": semantic_preview_geometry,
                "dialogs": semantic_dialogs,
            },
        )
        semantic_page.locator(".pm-managed-proposal-dismiss").click()
        semantic_page.wait_for_function(
            "() => !window.__processMapFlow.editor.managedProposalPlan"
        )
        semantic_page.emulate_media(reduced_motion="reduce")
        reopened_for_reduced_motion = semantic_page.evaluate(
            """() => window.__processMapFlow.editor.showManagedProposal(
                window.__semanticProposalForReducedMotion
            )"""
        )
        semantic_reduced_motion_state = semantic_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const reveal = editor.managedProposalReveal;
                return {
                    reopened: !!editor.managedProposalPlan,
                    active: reveal && reveal.active,
                    completed: reveal && reveal.completed,
                    reducedMotion: reveal && reveal.reducedMotion,
                    pendingElementCount: document.querySelectorAll(
                        '[data-managed-proposal-reveal-state="pending"]'
                    ).length,
                    approveDisabled: document.querySelector(
                        '.pm-managed-proposal-approve'
                    ).disabled,
                    showAllHidden: document.querySelector(
                        '.pm-managed-proposal-show-all'
                    ).hidden,
                    savedNodeCount: editor.processMap.canvasNodes.length,
                };
            }"""
        )
        record(
            "semantic_generation_reduced_motion_shows_complete_preview",
            reopened_for_reduced_motion is True
            and semantic_reduced_motion_state["reopened"] is True
            and semantic_reduced_motion_state["active"] is False
            and semantic_reduced_motion_state["completed"] is True
            and semantic_reduced_motion_state["reducedMotion"] is True
            and semantic_reduced_motion_state["pendingElementCount"] == 0
            and semantic_reduced_motion_state["approveDisabled"] is False
            and semantic_reduced_motion_state["showAllHidden"] is True
            and semantic_reduced_motion_state["savedNodeCount"] == 0,
            semantic_reduced_motion_state,
        )
        semantic_page.locator(".pm-managed-proposal-approve").click()
        semantic_page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                return editor.processMap.canvasNodes.length === 5
                    && editor.processMap.canvasEdges.length === 4
                    && editor.revision === 'semantic-rev-2'
                    && !editor.managedProposalPlan;
            }""",
            timeout=15_000,
        )
        semantic_page.evaluate(
            "window._agentContextSendPrompt('Summarize the committed map receipt.')"
        )
        semantic_page.wait_for_function(
            "() => document.querySelectorAll('.agent-msg.assistant').length > 0"
        )
        receipt_attachment = (
            semantic_requests[-1]
            .get("inspection_context", {})
            .get("attachments", {})
            .get("process_map", {})
            .get("receipts", [])
        )
        semantic_events = semantic_store["semanticEvents"]
        record(
            "semantic_approval_is_bound_atomic_and_returns_receipt_to_sage",
            [item["kind"] for item in semantic_events]
                == ["proposal", "approval", "apply"]
            and all(
                item["body"].get("semanticBindingHash") == "c" * 64
                for item in semantic_events[1:]
            )
            and len(receipt_attachment) == 1
            and receipt_attachment[0].get("receiptId") == "semantic-receipt"
            and receipt_attachment[0].get("revision") == "semantic-rev-2"
            and len(
                receipt_attachment[0].get("createdIds", {}).get("nodeIds", [])
            ) == 5,
            {
                "events": semantic_events,
                "receipts": receipt_attachment,
            },
        )
        semantic_context.close()

        phase7_store = {
            "map": _synthetic_phase7_arrangement_map(),
            "structure": _synthetic_structure(),
            "revision": "phase7-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        phase7_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        phase7_page = phase7_context.new_page()
        phase7_telemetry: list[dict] = []
        _install_cached_three_route(phase7_page)
        phase7_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(phase7_page, phase7_store)
        _install_synthetic_map_management_routes(phase7_page, phase7_store)
        _install_synthetic_suggestion_route(phase7_page, phase7_store)
        _install_spatial_telemetry_route(phase7_page, phase7_telemetry)
        for status_url in (
            "**/api/training/process-map-spatial-analysis-status",
            "**/api/training/process-map-spatial-placement-status",
            "**/api/training/process-map-auto-routing-status",
            "**/api/training/process-map-agent-layout-write-status",
        ):
            phase7_page.route(
                status_url,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "enabled": True}),
                ),
            )
        phase7_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(phase7_page)
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.spatialPlacementEnabled === true"
        )
        clean_button = phase7_page.locator(
            "[data-process-map-command='processCleanUp']"
        )
        phase7_initial = phase7_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                return {
                    fingerprint: window.InspectorProProcessMap.mapFingerprint(editor.processMap),
                    lockedPosition: {...editor.processMap.canvasNodes.find(node => node.nodeId === 'c').position},
                    historyDepth: editor.history.undoStack.length,
                    dirty: editor.dirty,
                };
            }"""
        )
        clean_button.click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan !== null"
        )
        phase7_preview = phase7_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const state = editor.arrangementPlan;
                return {
                    scope: state.plan.scope.kind,
                    planId: state.plan.planId,
                    moveIds: state.plan.moves.map(move => move.nodeId).sort(),
                    beforeHard: state.plan.metricsBefore.hardViolationCount,
                    afterHard: state.plan.metricsAfter.hardViolationCount,
                    fingerprint: window.InspectorProProcessMap.mapFingerprint(editor.processMap),
                    historyDepth: editor.history.undoStack.length,
                    dirty: editor.dirty,
                };
            }"""
        )
        record(
            "phase7_full_map_cleanup_is_preview_only_and_preserves_locked_cards",
            phase7_preview["scope"] == "full_map"
            and phase7_preview["planId"] == "pm-arr-773a2993e219cf2e"
            and "c" not in phase7_preview["moveIds"]
            and phase7_preview["beforeHard"] > phase7_preview["afterHard"]
            and phase7_preview["fingerprint"] == phase7_initial["fingerprint"]
            and phase7_preview["historyDepth"] == phase7_initial["historyDepth"]
            and phase7_preview["dirty"] is False
            and phase7_page.locator("[data-arrangement-ghost]").count()
                == len(phase7_preview["moveIds"])
            and phase7_page.locator(".pm-arrangement-accept").count() == 1,
            phase7_preview,
        )
        phase7_page.emulate_media(reduced_motion="reduce")
        reduced_motion_state = phase7_page.evaluate(
            """() => {
                const ghost = document.querySelector('.pm-arrangement-ghost');
                const style = ghost ? getComputedStyle(ghost) : null;
                const status = document.querySelector('.pm-editor-status');
                return {
                    transition: style && style.transitionDuration,
                    animation: style && style.animationName,
                    live: status && status.getAttribute('aria-live'),
                    atomic: status && status.getAttribute('aria-atomic'),
                    busy: document.querySelector('[data-process-flow-editor]')
                        .getAttribute('aria-busy'),
                };
            }"""
        )
        record(
            "phase8_cleanup_preview_honors_reduced_motion_and_live_status",
            reduced_motion_state["transition"] in {"0s", "0s, 0s"}
            and reduced_motion_state["animation"] == "none"
            and reduced_motion_state["live"] == "polite"
            and reduced_motion_state["atomic"] == "true"
            and reduced_motion_state["busy"] is None,
            reduced_motion_state,
        )
        phase7_page.evaluate(
            "document.documentElement.setAttribute('data-theme', 'light')"
        )
        phase7_page.screenshot(
            path=str(OUT_DIR / "process_flow_phase8_cleanup_preview_light.png"),
            full_page=False,
        )
        phase7_page.evaluate(
            "document.documentElement.setAttribute('data-theme', 'dark')"
        )
        phase7_page.screenshot(
            path=str(OUT_DIR / "process_flow_phase8_cleanup_preview_dark.png"),
            full_page=False,
        )
        phase7_page.emulate_media(reduced_motion="no-preference")
        phase7_page.locator(".pm-arrangement-accept").click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan === null"
        )
        phase7_applied = phase7_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                return {
                    historyDepth: editor.history.undoStack.length,
                    dirty: editor.dirty,
                    lockedPosition: {...editor.processMap.canvasNodes.find(node => node.nodeId === 'c').position},
                    fingerprint: window.InspectorProProcessMap.mapFingerprint(editor.processMap),
                };
            }"""
        )
        record(
            "phase7_apply_is_one_undoable_mutation_and_locked_position_is_exact",
            phase7_applied["historyDepth"] == phase7_initial["historyDepth"] + 1
            and phase7_applied["dirty"] is True
            and phase7_applied["lockedPosition"] == phase7_initial["lockedPosition"]
            and phase7_applied["fingerprint"] != phase7_initial["fingerprint"],
            phase7_applied,
        )
        phase7_page.evaluate("window.__processMapFlow.editor.undo()")
        record(
            "phase7_one_undo_restores_exact_precleanup_map",
            phase7_page.evaluate(
                "window.InspectorProProcessMap.mapFingerprint(window.__processMapFlow.editor.processMap)"
            ) == phase7_initial["fingerprint"],
        )

        phase7_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                const original = editor._ensureSpatialContract.bind(editor);
                editor.__phase8OriginalEnsureSpatialContract = original;
                editor._ensureSpatialContract = () => new Promise((resolve, reject) => {
                    setTimeout(() => original().then(resolve, reject), 350);
                });
            }"""
        )
        clean_button.click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlanning === true"
        )
        cancellation_busy_state = phase7_page.evaluate(
            """() => ({
                label: document.querySelector(
                    '[data-process-map-command="processCleanUp"] .ribbon-btn-label'
                ).textContent,
                ariaBusy: document.querySelector('[data-process-flow-editor]')
                    .getAttribute('aria-busy'),
                status: document.querySelector('.pm-editor-status').textContent,
            })"""
        )
        clean_button.click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlanning === false"
        )
        phase7_page.wait_for_timeout(450)
        record(
            "phase8_cleanup_is_cancelable_and_superseded_result_never_lands",
            cancellation_busy_state["label"] == "Cancel"
            and cancellation_busy_state["ariaBusy"] == "true"
            and "Planning a cleaner layout" in cancellation_busy_state["status"]
            and phase7_page.evaluate(
                "window.__processMapFlow.editor.arrangementPlan === null"
            )
            and phase7_page.locator("[data-arrangement-ghost]").count() == 0
            and phase7_page.evaluate(
                "window.InspectorProProcessMap.mapFingerprint(window.__processMapFlow.editor.processMap)"
            ) == phase7_initial["fingerprint"],
            cancellation_busy_state,
        )
        phase7_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                editor._ensureSpatialContract = editor.__phase8OriginalEnsureSpatialContract;
                delete editor.__phase8OriginalEnsureSpatialContract;
            }"""
        )

        phase7_page.evaluate(
            "window.__processMapFlow.editor.setGraphSelection(['a', 'b'], [])"
        )
        record(
            "phase7_selected_cards_switch_command_to_selection_scope",
            clean_button.locator(".ribbon-btn-label").inner_text() == "Clean Selection",
        )
        clean_button.click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan !== null"
        )
        selection_preview = phase7_page.evaluate(
            """() => {
                const state = window.__processMapFlow.editor.arrangementPlan;
                return {
                    scope: state.plan.scope.kind,
                    nodeIds: state.plan.scope.nodeIds,
                    moves: state.plan.moves.map(move => move.nodeId),
                };
            }"""
        )
        record(
            "phase7_selection_cleanup_moves_only_requested_unlocked_cards",
            selection_preview["scope"] == "selection"
            and selection_preview["nodeIds"] == ["a", "b"]
            and set(selection_preview["moves"]).issubset({"a", "b"}),
            selection_preview,
        )
        phase7_page.locator(".pm-arrangement-dismiss").click()
        record(
            "phase7_dismiss_keeps_map_and_history_unchanged",
            phase7_page.evaluate(
                "window.InspectorProProcessMap.mapFingerprint(window.__processMapFlow.editor.processMap)"
            ) == phase7_initial["fingerprint"]
            and phase7_page.evaluate(
                "window.__processMapFlow.editor.history.undoStack.length"
            ) == phase7_initial["historyDepth"],
        )

        clean_button.click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan !== null"
        )
        stale_before = phase7_page.evaluate(
            "window.__processMapFlow.editor.history.undoStack.length"
        )
        phase7_page.evaluate(
            "window.__processMapFlow.editor.processMap.canvasNodes.find(node => node.nodeId === 'a').position.x += 1"
        )
        phase7_page.locator(".pm-arrangement-accept").click()
        phase7_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan === null"
        )
        record(
            "phase7_stale_preview_fails_closed_without_committing",
            phase7_page.evaluate(
                "window.__processMapFlow.editor.history.undoStack.length"
            ) == stale_before
            and "changed since this cleanup" in phase7_page.evaluate(
                "window.__processMapFlow.editor.operationError"
            ),
        )
        phase7_page.wait_for_timeout(150)
        arrangement_outcomes = {
            event.get("outcome") for event in phase7_telemetry
            if event.get("operation") == "arrangement"
        }
        telemetry_keys: set[str] = set()

        def collect_telemetry_keys(value) -> None:
            if isinstance(value, dict):
                telemetry_keys.update(str(key) for key in value)
                for child in value.values():
                    collect_telemetry_keys(child)
            elif isinstance(value, list):
                for child in value:
                    collect_telemetry_keys(child)

        collect_telemetry_keys(phase7_telemetry)
        record(
            "phase8_spatial_telemetry_records_outcomes_without_geometry_or_labels",
            {"previewed", "accepted", "dismissed", "cancelled", "stale"}
                .issubset(arrangement_outcomes)
            and not {
                "position", "positions", "point", "points", "route", "routes",
                "waypoints", "label", "labels", "name", "note", "description",
            }.intersection(telemetry_keys),
            {
                "eventCount": len(phase7_telemetry),
                "arrangementOutcomes": sorted(arrangement_outcomes),
                "keys": sorted(telemetry_keys),
            },
        )
        phase7_context.close()

        phase7_group_store = {
            "map": _synthetic_phase7_arrangement_map(grouped=True),
            "structure": _synthetic_structure(),
            "revision": "phase7-group-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        phase7_group_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        phase7_group_page = phase7_group_context.new_page()
        _install_cached_three_route(phase7_group_page)
        phase7_group_page.on(
            "pageerror", lambda error: report["page_errors"].append(str(error))
        )
        _install_synthetic_process_map_route(phase7_group_page, phase7_group_store)
        _install_synthetic_map_management_routes(phase7_group_page, phase7_group_store)
        _install_synthetic_suggestion_route(phase7_group_page, phase7_group_store)
        phase7_group_page.route(
            "**/api/training/process-map-spatial-placement-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": True}),
            ),
        )
        phase7_group_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(phase7_group_page)
        phase7_group_page.wait_for_function(
            "window.__processMapFlow.editor.spatialPlacementEnabled === true"
        )
        phase7_group_initial = phase7_group_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                return {
                    group: JSON.stringify(editor.processMap.canvasGroups[0]),
                    lockedPosition: {...editor.processMap.canvasNodes.find(node => node.nodeId === 'c').position},
                };
            }"""
        )
        phase7_group_page.evaluate(
            "window.__processMapFlow.editor.selectGroup('g')"
        )
        group_clean_button = phase7_group_page.locator(
            "[data-process-map-command='processCleanUp']"
        )
        record(
            "phase7_selected_group_switches_command_to_group_scope",
            group_clean_button.locator(".ribbon-btn-label").inner_text() == "Clean Group",
        )
        group_clean_button.click()
        phase7_group_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan !== null"
        )
        group_preview = phase7_group_page.evaluate(
            """() => {
                const state = window.__processMapFlow.editor.arrangementPlan;
                return {scope: state.plan.scope, planId: state.plan.planId};
            }"""
        )
        phase7_group_page.locator(".pm-arrangement-accept").click()
        phase7_group_page.wait_for_function(
            "window.__processMapFlow.editor.arrangementPlan === null"
        )
        group_applied = phase7_group_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                return {
                    group: JSON.stringify(editor.processMap.canvasGroups[0]),
                    lockedPosition: {...editor.processMap.canvasNodes.find(node => node.nodeId === 'c').position},
                    historyDepth: editor.history.undoStack.length,
                };
            }"""
        )
        record(
            "phase7_group_cleanup_preserves_frame_and_locked_member",
            group_preview["scope"].get("kind") == "group"
            and group_preview["scope"].get("groupId") == "g"
            and group_preview["scope"].get("nodeIds") == ["a", "b", "c"]
            and group_preview["planId"] == "pm-arr-6ff5b6a0ac8cf727"
            and group_applied["group"] == phase7_group_initial["group"]
            and group_applied["lockedPosition"] == phase7_group_initial["lockedPosition"]
            and group_applied["historyDepth"] == 1,
            {"preview": group_preview, "applied": group_applied},
        )
        phase7_group_context.close()

        routing_off_store = {
            "map": _synthetic_routing_process_map(),
            "structure": _synthetic_structure(),
            "revision": "route-off-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        routing_off_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        routing_off_page = routing_off_context.new_page()
        _install_cached_three_route(routing_off_page)
        routing_off_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        _install_synthetic_process_map_route(routing_off_page, routing_off_store)
        _install_synthetic_map_management_routes(routing_off_page, routing_off_store)
        _install_synthetic_suggestion_route(routing_off_page, routing_off_store)
        routing_off_page.route(
            "**/api/training/process-map-spatial-placement-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        routing_off_page.route(
            "**/api/training/process-map-auto-routing-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        routing_off_page.route(
            "**/api/training/process-map-agent-layout-write-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        routing_off_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(routing_off_page)
        routing_off_page.evaluate("window.__processMapFlow.editor.selectEdge('route-edge')")
        routing_off_legacy_path = routing_off_page.locator(
            ".pm-edge[data-edge-id='route-edge']"
        ).get_attribute("d")
        record(
            "phase4_flag_off_preserves_legacy_geometry_and_exposes_no_route_command",
            " C " in routing_off_legacy_path
            and routing_off_page.locator(".pm-edge-toolbar-route").count() == 0
            and not routing_off_page.evaluate(
                "!!window.__processMapFlow.editor.processMap.canvasEdges[0].routing"
            ),
            routing_off_legacy_path,
        )
        routing_off_context.close()

        # Flag-off: candidate generation UI must not appear at all.
        flag_off_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        flag_off_page = flag_off_context.new_page()
        _install_cached_three_route(flag_off_page)
        flag_off_page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        flag_off_store = {
            "map": _synthetic_process_map(),
            "structure": _synthetic_structure(),
            "revision": "rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
        }
        _install_synthetic_process_map_route(flag_off_page, flag_off_store)
        _install_synthetic_map_management_routes(flag_off_page, flag_off_store)
        _install_synthetic_suggestion_route(flag_off_page, flag_off_store)
        _install_synthetic_spatial_proposal_routes(flag_off_page, flag_off_store)
        flag_off_page.route(
            "**/api/training/process-map-spatial-placement-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        flag_off_page.route(
            "**/api/training/process-map-spatial-analysis-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        flag_off_page.route(
            "**/api/training/process-map-auto-routing-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        flag_off_page.route(
            "**/api/training/process-map-agent-layout-write-status",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "enabled": False}),
            ),
        )
        flag_off_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(flag_off_page)
        flag_off_page.evaluate(
            """async () => await window._trainRequestManagedSpatialProposal(
                'propose_process_map_node_placement',
                { targetKind: 'product_occurrence', occurrenceId: 'part-a-1' }
            )"""
        )
        record(
            "phase6_agent_write_flag_off_keeps_preview_read_only",
            flag_off_page.locator(".pm-managed-proposal-ghost").count() == 1
            and flag_off_page.locator(".pm-managed-proposal-approve").is_disabled()
            and flag_off_page.evaluate(
                "window.__processMapFlow.editor.processMap.canvasNodes.length"
            ) == 0
            and not any(
                event["kind"] in {"approval", "apply"}
                for event in flag_off_store.get("spatialEvents", [])
            ),
            flag_off_store.get("spatialEvents", []),
        )
        flag_off_page.locator(".pm-managed-proposal-dismiss").click()
        _expand(flag_off_page, "module-a")
        _drag_tree_item(flag_off_page, "part-a-1", 300, 240)
        flag_off_page.wait_for_function("window.__processMapFlow.editor.processMap.canvasNodes.length === 1")
        record(
            "phase3_flag_off_hides_suggest_position_controls_entirely",
            flag_off_page.locator(".pm-tree-suggest-position").count() == 0
            and flag_off_page.locator(".pm-card-toolbar-suggest").count() == 0,
        )
        record(
            "phase8_analysis_flag_off_disables_layout_analysis_fail_closed",
            flag_off_page.locator(
                "[data-process-map-command='processAnalyzeLayout']"
            ).is_disabled()
            and flag_off_page.evaluate(
                "window.__processMapFlow.editor.analyzeLayout()"
            ) is False,
        )
        flag_off_context.close()

        metadata_store = {
            "map": _synthetic_routing_process_map(),
            "structure": _synthetic_structure(),
            "revision": "metadata-rev-1",
            "findings": [],
            "putCount": 0,
            "events": [],
            "builderWriteEnabled": True,
        }
        metadata_context = browser.new_context(viewport={"width": 1600, "height": 1000})
        metadata_page = metadata_context.new_page()
        _install_cached_three_route(metadata_page)
        metadata_page.on(
            "pageerror", lambda error: report["page_errors"].append(str(error))
        )
        _install_synthetic_process_map_route(metadata_page, metadata_store)
        _install_synthetic_map_management_routes(metadata_page, metadata_store)
        _install_synthetic_suggestion_route(metadata_page, metadata_store)
        _install_synthetic_metadata_proposal_routes(metadata_page, metadata_store)
        metadata_chat_requests: list[dict] = []
        _install_synthetic_metadata_chat_stream(
            metadata_page, metadata_chat_requests
        )
        for status_path in (
            "process-map-spatial-placement-status",
            "process-map-spatial-analysis-status",
            "process-map-auto-routing-status",
            "process-map-agent-layout-write-status",
        ):
            metadata_page.route(
                "**/api/training/" + status_path,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"success": True, "enabled": False}),
                ),
            )
        metadata_page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        _open_process_flow(metadata_page)
        metadata_page.wait_for_function(
            "window.__processMapFlow.editor.managedProposalWriteEnabled === true"
        )
        metadata_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                editor.commitMutation(window.InspectorProProcessMap.moveNode(
                    editor.processMap,
                    'route-obstacle',
                    {x: 520, y: 210}
                ));
                window._selectAgent('deviation-analyst');
                window._agentContextSendPrompt(
                    'Fill the missing card requirements, resources, route names, '
                    + 'and routing requirements for this Front Wheel & Brake process map. '
                    + 'Preserve existing authored values and report anything that cannot be matched.'
                );
            }"""
        )
        metadata_page.wait_for_selector(
            ".pm-managed-proposal-review:not([hidden])", timeout=10_000
        )
        metadata_page.wait_for_function(
            """() => Array.from(document.querySelectorAll('.agent-msg.assistant'))
                .some(element => element.textContent.includes('requirements preview'))"""
        )
        metadata_preview = metadata_page.evaluate(
            """() => {
                const editor = window.__processMapFlow.editor;
                return {
                    referenceCount: (editor.processMap.referenceCatalog || []).length,
                    processPlanImportCount: (editor.processMap.processPlanImports || []).length,
                    agentLayoutWriteEnabled: editor.agentLayoutWriteEnabled,
                    managedProposalWriteEnabled: editor.managedProposalWriteEnabled,
                };
            }"""
        )
        metadata_assistant_text = metadata_page.locator(
            ".agent-msg.assistant"
        ).last.inner_text()
        metadata_review_copy = metadata_page.locator(
            ".pm-managed-proposal-copy"
        ).inner_text()
        record(
            "demo_metadata_preview_is_illustrative_and_non_mutating",
            len(metadata_chat_requests) == 1
            and metadata_page.locator(".pm-managed-proposal-ghost").count() == 1
            and "Demo data is not production-approved" in metadata_review_copy
            and "I prepared a requirements preview" in metadata_assistant_text
            and "No response from agent" not in metadata_assistant_text
            and metadata_preview["referenceCount"] == 0
            and metadata_preview["processPlanImportCount"] == 0
            and metadata_store["putCount"] == 1
            and metadata_store["events"][-1]["kind"] == "save",
            {
                "assistant": metadata_assistant_text,
                "review": metadata_review_copy,
                "state": metadata_preview,
                "requests": len(metadata_chat_requests),
                "mapEvents": metadata_store["events"],
            },
        )
        record(
            "demo_metadata_approval_depends_on_builder_not_spatial_write",
            metadata_preview["managedProposalWriteEnabled"] is True
            and metadata_preview["agentLayoutWriteEnabled"] is False
            and not metadata_page.locator(".pm-managed-proposal-approve").is_disabled(),
            metadata_preview,
        )
        metadata_page.locator(".pm-managed-proposal-approve").click()
        metadata_page.wait_for_function(
            """() => {
                const editor = window.__processMapFlow.editor;
                return (editor.processMap.referenceCatalog || []).length === 3
                    && !editor.managedProposalPlan;
            }""",
            timeout=15_000,
        )
        metadata_applied = metadata_page.evaluate(
            """() => {
                const map = window.__processMapFlow.editor.processMap;
                const node = map.canvasNodes.find(item => item.nodeId === 'route-source');
                const edge = map.canvasEdges.find(item => item.edgeId === 'route-edge');
                return {
                    nodeReferenceIds: node.referenceIds,
                    edgeReferenceIds: edge.referenceIds,
                    edgeLabel: edge.label,
                    referenceCount: map.referenceCatalog.length,
                    processPlanImportCount: map.processPlanImports.length,
                };
            }"""
        )
        metadata_events = metadata_store.get("metadataEvents", [])
        record(
            "demo_metadata_single_approval_persists_native_map_state",
            metadata_applied == {
                "nodeReferenceIds": ["demo-machine", "demo-node-requirement"],
                "edgeReferenceIds": ["demo-route-requirement"],
                "edgeLabel": "Install demo component",
                "referenceCount": 3,
                "processPlanImportCount": 1,
            }
            and [event["kind"] for event in metadata_events]
                == ["proposal", "approval", "apply"]
            and all(
                "spatialBindingHash" not in event["body"]
                for event in metadata_events[1:]
            ),
            {"map": metadata_applied, "events": metadata_events},
        )
        metadata_page.evaluate(
            "window.__processMapFlow.editor.select('route-source')"
        )
        metadata_page.locator(".pm-card-toolbar-references").click()
        record(
            "demo_metadata_is_visible_in_existing_requirement_ui",
            metadata_page.locator(".pm-reference-demo").count() == 2
            and metadata_page.locator(
                ".pm-node[data-node-id='route-source'] .pm-reference-badge-demo"
            ).count() == 1,
            {
                "demoRows": metadata_page.locator(".pm-reference-demo").count(),
                "demoBadges": metadata_page.locator(
                    ".pm-node[data-node-id='route-source'] .pm-reference-badge-demo"
                ).count(),
            },
        )
        metadata_page.evaluate(
            "window.__processMapFlow.editor.selectEdge('route-edge')"
        )
        metadata_page.locator(".pm-card-toolbar-references").click()
        record(
            "demo_route_requirement_is_visible_in_connection_editor",
            metadata_page.locator(".pm-reference-demo").count() == 1
            and metadata_page.evaluate(
                """() => {
                    const edge = window.__processMapFlow.editor.processMap.canvasEdges
                        .find(item => item.edgeId === 'route-edge');
                    return edge && edge.label === 'Install demo component';
                }"""
            ),
            {
                "demoRows": metadata_page.locator(".pm-reference-demo").count(),
                "edgeLabel": metadata_applied["edgeLabel"],
            },
        )
        metadata_page.screenshot(
            path=str(OUT_DIR / "process_flow_demo_metadata_light.png"),
            full_page=True,
        )
        metadata_context.close()

        record("no_browser_page_errors", not report["page_errors"], report["page_errors"])
        browser.close()

    output_path = OUT_DIR / "process_flow_editor_smoke.json"
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [name for name, value in report["checks"].items() if not value["ok"]]
    print(f"Wrote {output_path}")
    if failed:
        print("Failed checks: " + ", ".join(failed), file=sys.stderr)
        return 1
    print(f"Process-flow smoke: {len(report['checks'])}/{len(report['checks'])} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
