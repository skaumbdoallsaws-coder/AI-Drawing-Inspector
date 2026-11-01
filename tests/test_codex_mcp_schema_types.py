"""Tool schemas published over MCP state a type on every node (strict providers such as Kimi's require it)."""
from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from ai_inspector.codex_runtime.assisted_tools import artifact_specs, contract_spec, edit_tool_specs
from ai_inspector.codex_runtime.facility_tools import tool_specs
from ai_inspector.codex_runtime.mcp_bridge import explicit_types

TYPED = ("type", "$ref", "anyOf", "oneOf", "allOf")


def untyped_nodes(schema, path="input", out=None):
    out = [] if out is None else out
    if not isinstance(schema, dict):
        return out
    if not any(key in schema for key in TYPED):
        out.append(path)
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        for name, sub in (schema.get(key) or {}).items():
            untyped_nodes(sub, f"{path}.{key}.{name}", out)
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for index, sub in enumerate(schema.get(key) or []):
            untyped_nodes(sub, f"{path}.{key}[{index}]", out)
    for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames"):
        if isinstance(schema.get(key), dict):
            untyped_nodes(schema[key], f"{path}.{key}", out)
    return out


def test_enum_and_const_nodes_state_their_type():
    typed = explicit_types({"type": "object", "properties": {
        "view": {"enum": ["plan", "zones"]}, "angle": {"enum": [0, 90, 180]},
        "scale": {"enum": [0.5, 1]}, "flag": {"const": True}, "maybe": {"enum": ["a", None]},
        "angles": {"type": "array", "items": {"enum": [0, 90]}}}})
    props = typed["properties"]
    assert props["view"]["type"] == "string"
    assert props["angle"]["type"] == "integer"
    assert props["scale"]["type"] == "number"
    assert props["flag"]["type"] == "boolean"
    assert props["maybe"]["type"] == ["null", "string"]
    assert props["angles"]["items"]["type"] == "integer"


def test_properties_named_like_keywords_are_left_alone():
    schema = {"type": "object", "properties": {"const": {"type": "string"}, "enum": {"type": "string"}}}
    typed = explicit_types(schema)
    assert set(typed["properties"]) == {"const", "enum"}
    assert typed["properties"]["const"] == {"type": "string"}
    assert schema == {"type": "object", "properties": {"const": {"type": "string"}, "enum": {"type": "string"}}}


def test_forbidden_properties_are_dropped_only_where_the_object_is_closed():
    closed = explicit_types({"type": "object", "properties": {"a": {"type": "string"}, "b": False},
                             "additionalProperties": False})
    assert set(closed["properties"]) == {"a"}
    probe = {"a": "x", "b": 1}
    assert not Draft202012Validator(closed).is_valid(probe)
    open_object = explicit_types({"type": "object", "properties": {"b": False}})
    assert open_object["properties"]["b"] is False


def test_constraint_branches_take_the_type_of_the_value_they_constrain():
    typed = explicit_types({"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                            "anyOf": [{"required": ["a"]}, {"required": ["b"]}],
                            "allOf": [{"if": {"not": {"required": ["a"]}}, "then": {"properties": {"b": {"minLength": 1}}}}]})
    assert [branch["type"] for branch in typed["anyOf"]] == ["object", "object"]
    rule = typed["allOf"][0]
    assert rule["type"] == "object" and rule["if"]["type"] == "object" and rule["then"]["type"] == "object"
    assert untyped_nodes({**typed, "allOf": [{**rule, "then": {**rule["then"], "properties": {}}}]}) == []


def test_every_published_tool_schema_is_typed_valid_and_accepts_the_same_calls():
    editing = edit_tool_specs()
    specs = [*tool_specs(), *editing, *artifact_specs(), contract_spec(editing[0]["input_schema"])]
    for spec in specs:
        typed = explicit_types(spec["input_schema"])
        Draft202012Validator.check_schema(typed)
        assert untyped_nodes(typed) == [], spec["name"]
        assert "false" not in json.dumps({k: v for k, v in typed.items() if k != "additionalProperties"}).replace(
            '"additionalProperties": false', ""), spec["name"]
    schema = editing[0]["input_schema"]
    original = Draft202012Validator({"$defs": schema.get("$defs", {}), **schema["properties"]["operations"]["items"]})
    typed_items = explicit_types(schema)["properties"]["operations"]["items"]
    typed = Draft202012Validator({"$defs": schema.get("$defs", {}), **typed_items})
    samples = [
        {"op": "set_scene", "scene": {"version": 1, "sceneId": "presentation-light"}},
        {"op": "set_scene", "scene": {"version": 1, "adjustments": {"lights": False}}},
        {"op": "set_scene", "scene": None},
        {"op": "set_scene", "scene": {"version": 1, "sceneId": "not-a-scene"}},
        {"op": "set_appearance", "placementIds": ["pl-a"], "appearance": {"appearanceId": "wood-oak"}},
        {"op": "set_appearance", "placementIds": ["pl-a"], "color": "#112233"},
        {"op": "set_appearance", "placementIds": []},
        {"op": "no_such_op"},
    ]
    for sample in samples:
        assert original.is_valid(sample) == typed.is_valid(sample), sample
