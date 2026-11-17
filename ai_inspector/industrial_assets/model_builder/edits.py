"""Small, all-or-nothing edits to a portable builder recipe."""
from copy import deepcopy

from .errors import ModelBuildError, require
from .recipe import normalize_recipe


def _entry(entries, wanted):
    for index, value in enumerate(entries):
        if value["id"] == wanted:
            return entries, index, value
        if "group" in value:
            found = _entry(value["group"], wanted)
            if found is not None:
                return found
    return None


def _fields(value, operation, path):
    changed = False
    if "set" in operation:
        fields = operation["set"]
        require(type(fields) is dict and bool(fields), path + ".set", "Expected a nonempty field map")
        value.update(deepcopy(fields))
        changed = True
    if "unset" in operation:
        fields = operation["unset"]
        require(type(fields) is list and bool(fields) and all(type(field) is str and field for field in fields)
                and len(set(fields)) == len(fields), path + ".unset", "Expected distinct field names")
        for field in fields:
            require(field in value, path + ".unset", "The field is not present: " + field)
            del value[field]
        changed = True
    require(changed, path, "The edit needs set or unset")


def apply_edits(recipe, edits, *, allowed_categories, allowed_appearance_ids):
    require(type(edits) is list and 1 <= len(edits) <= 40, "$.edits", "Use 1-40 edits")
    result = deepcopy(recipe)
    for index, operation in enumerate(edits):
        path = f"$.edits[{index}]"
        require(type(operation) is dict and type(operation.get("op")) is str,
                path, "Expected an edit operation")
        kind = operation["op"]
        if kind in {"update", "remove"}:
            require(set(operation) <= ({"op", "id", "set", "unset"} if kind == "update" else {"op", "id"})
                    and type(operation.get("id")) is str, path, "Invalid entry edit")
            found = _entry(result["entries"], operation["id"])
            require(found is not None, path + ".id", "Unknown entry id: " + operation["id"])
            parent, at, value = found
            if kind == "remove":
                parent.pop(at)
            else:
                _fields(value, operation, path)
        elif kind == "add":
            require(set(operation) <= {"op", "entry", "into", "after"} and type(operation.get("entry")) is dict,
                    path, "Invalid add edit")
            entries = result["entries"]
            if "into" in operation:
                require(type(operation["into"]) is str, path + ".into", "Expected a group id")
                found = _entry(entries, operation["into"])
                require(found is not None and "group" in found[2], path + ".into", "Unknown group id")
                entries = found[2]["group"]
            at = len(entries)
            if "after" in operation:
                require(type(operation["after"]) is str, path + ".after", "Expected an entry id")
                found = _entry(entries, operation["after"])
                require(found is not None and found[0] is entries, path + ".after", "After must name a sibling")
                at = found[1] + 1
            entries.insert(at, deepcopy(operation["entry"]))
        elif kind == "material":
            require(set(operation) <= {"op", "name", "set", "unset", "remove"}
                    and type(operation.get("name")) is str, path, "Invalid material edit")
            name = operation["name"]
            materials = result["materials"]
            if operation.get("remove") is True:
                require(set(operation) == {"op", "name", "remove"} and name in materials,
                        path + ".name", "Unknown material")
                del materials[name]
            else:
                require("remove" not in operation, path + ".remove", "Use remove true or omit it")
                material = materials.setdefault(name, {}) if "set" in operation else materials.get(name)
                require(material is not None, path + ".name", "Unknown material")
                _fields(material, operation, path)
        elif kind == "top":
            require(set(operation) <= {"op", "set", "unset"}, path, "Invalid top edit")
            fields = set(operation.get("set", {})) | set(operation.get("unset", []))
            require(not fields & {"entries", "materials", "references"}, path,
                    "Use entry or material edits; references arrive in the reference phase")
            _fields(result, operation, path)
        else:
            raise ModelBuildError("schema_invalid", path + ".op", "Unknown edit operation")
    return normalize_recipe(result, allowed_categories=allowed_categories,
                            allowed_appearance_ids=allowed_appearance_ids)
