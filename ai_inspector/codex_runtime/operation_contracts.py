"""Focused, authoritative operation contracts without the whole authoring catalog."""
from copy import deepcopy

from .edit_schemas import array, obj


def tool_spec(schema):
    names = [row["properties"]["op"]["const"]
             for row in schema["properties"]["operations"]["items"]["oneOf"]]
    return {"name": "inspect_facility_operation_contracts", "description":
        "Read exact input schemas for up to three editing operations before constructing a new batch. "
        "Includes all required fields, enums and reachable definitions. This does not stage or change anything. "
        "Use op (not type), floorMarking (not marking), placement, and surface exactly as defined. "
        "Placement scale must be 1; never resize real equipment to hide a dimensional mismatch.",
        "input_schema": obj({"operations": array({"enum": names}, 3, 1, uniqueItems=True)})}


def contracts(schema, names):
    variants = {row["properties"]["op"]["const"]: row
                for row in schema["properties"]["operations"]["items"]["oneOf"]}
    selected = [deepcopy(variants[name]) for name in names if name in variants][:3]
    definitions = {}

    def visit(value):
        if isinstance(value, dict):
            target = value.get("$ref", "")
            if target.startswith("#/$defs/") and target[8:] not in definitions:
                definitions[target[8:]] = deepcopy(schema["$defs"][target[8:]])
                visit(definitions[target[8:]])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(selected)
    return {"type": "object", "properties": {"operations": array({"oneOf": selected}, 50, 1)},
            "required": ["operations"], "additionalProperties": False, "$defs": definitions}
