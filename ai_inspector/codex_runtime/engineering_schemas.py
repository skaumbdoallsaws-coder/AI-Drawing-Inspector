"""Closed, bounded wire schemas for two saved-facility fact workflows."""
from copy import deepcopy


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def array(items, maximum=50):
    return {"type": "array", "items": items, "maxItems": maximum}


ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
REVISION = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TEXT = {"type": "string", "maxLength": 512}
COUNT = {"type": "integer", "minimum": 0}
BOOL = {"type": "boolean"}
REFERENCE = obj({"siteId": ID, "layoutId": ID, "revision": REVISION})
ACTOR_CLASS = {"type": "string", "enum": ["pedestrian", "vehicle"]}
ACTOR = obj({"actorPlacementId": ID, "label": TEXT, "actorClass": ACTOR_CLASS,
             "movementProgramId": {"anyOf": [ID, {"type": "null"}]},
             "missingSemantics": array({"type": "string", "enum": [
                 "movement_program", "ordered_stops", "published_vehicle_profile"]}, 3)})
ANCHOR = obj({**{key: TEXT for key in (
    "navigationAnchorId", "anchorKind", "ownerKind", "ownerId", "ownerLabel",
    "interactionKind", "positionAuthority", "reviewStatus")},
    "actorClasses": array(ACTOR_CLASS, 2)})
PROGRAM = obj({**{key: TEXT for key in (
    "movementProgramId", "actorPlacementId", "actorLabel", "loopMode", "reviewStatus")},
    "actorClass": ACTOR_CLASS, "orderedAnchorIds": array(ID, 256),
    "requiredRouteIds": array(ID, 256), "forbiddenZoneIds": array(ID, 256),
    "manualOverrideCount": COUNT})
HANDOFF = obj({key: TEXT for key in (
    "handoffProgramId", "sourceMovementProgramId", "targetMovementProgramId",
    "sourceAnchorId", "targetAnchorId", "sequencePolicy", "timingAuthority", "reviewStatus")})
NAVIGATION = obj({
    "schemaVersion": TEXT, "contractVersion": TEXT,
    "counts": obj({key: COUNT for key in ("actors", "anchors", "movementPrograms", "handoffPrograms")}),
    "actors": array(ACTOR), "anchors": array(ANCHOR), "movementPrograms": array(PROGRAM),
    "handoffPrograms": array(HANDOFF), "truncated": BOOL,
    "qualification": {"type": "string", "maxLength": 4096}, "canonicalBytes": COUNT,
})
BINDING = obj({
    "processBindingId": ID, "productId": ID, "processMapId": ID, "processMapRevision": REVISION,
    "processNodeIds": array(ID, 5000), "processEdgeIds": array(ID, 5000),
    "placementIds": array(ID, 5000), "routeIds": array(ID, 2000),
    "bindingRole": {"type": "string", "enum": [
        "resource", "material_flow", "operator_flow", "inspection", "storage", "staging"]},
})
PROCESS = obj({
    "records": array(BINDING, 20), "returnedCount": COUNT, "totalCount": COUNT,
    "nextOffset": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": 5000}, {"type": "null"}]},
})


def result_schema(workflow, payload):
    success = obj({"ok": {"const": True}, "data": obj({
        "workflow": {"const": workflow}, "document": REFERENCE,
        "readOnly": {"const": True}, "savedLayoutOnly": {"const": True},
        "facts": payload,
    })})
    failure = obj({"ok": {"const": False}, "error": obj({"code": TEXT, "message": TEXT})})
    return {"type": "object", "oneOf": [success, failure]}


WORKFLOWS = {
    "facility_navigation": {
        "name": "observe_navigation_context",
        "description": (
            "Read saved-layout actors, anchors, movement programs, handoffs and missing semantics. "
            "Coordinate-free authored facts, not a path solution or safety/compliance finding. No edits."),
        "input_schema": obj({"query": {"type": "string", "maxLength": 160},
                             "actorClass": ACTOR_CLASS,
                             "maximumRecords": {"type": "integer", "minimum": 1, "maximum": 50}}, []),
        "output_schema": result_schema("facility_navigation", NAVIGATION),
    },
    "facility_process_routes": {
        "name": "inspect_saved_process_bindings",
        "description": (
            "Read saved-layout Process Map revision references, node/edge IDs, placement IDs and route IDs. "
            "These are authored bindings, not live Process Map content or validated route geometry. No edits."),
        "input_schema": obj({
            "ids": {**array(ID, 20), "minItems": 1, "uniqueItems": True},
            "processMapId": ID,
            "pageSize": {"type": "integer", "minimum": 1, "maximum": 20},
            "offset": {"type": "integer", "minimum": 0, "maximum": 5000},
        }, []),
        "output_schema": result_schema("facility_process_routes", PROCESS),
    },
}


def tool_specs(workflow=None):
    """Inventory only; a gateway exposes exactly one selected workflow."""
    if workflow is None:
        return deepcopy(list(WORKFLOWS.values()))
    if workflow not in WORKFLOWS:
        raise ValueError("Unknown engineering workflow.")
    return [deepcopy(WORKFLOWS[workflow])]
