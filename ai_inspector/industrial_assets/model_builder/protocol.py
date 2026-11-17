"""Bounded worker output, validated without numpy, Pillow, or application parents."""
from copy import deepcopy
from hashlib import sha256
import re
import struct

from .budgets import copies, estimate, panel_pixels, MAX_PRINT_PIXELS, MAX_TEXTURE_PIXELS
from .errors import json_bytes, parse_json
from .imports import module
from .job_io import read_bytes
from .recipe import ENGINE_VERSION, portable_recipe
from .print_contract import png_dimensions

# This is a full worker record, NOT the later <=48 KiB MCP summary. At most four
# instance prefixes per expanded component, with <=512-character part keys.
RESULT_BYTES = 16 * 1024 * 1024
GLB_BYTES = 30 * 1024 * 1024
KEYS = {"schemaVersion", "kind", "engineVersion", "recipeSha256", "allowedSha256", "outputSha256", "outputBytes",
        "dimensions", "catalogDimensions", "shift", "triangles", "parts", "partMap", "materials", "images",
        "surfaces", "footprint", "lints", "warnings", "budgets", "provenance"}
LINT_FIELDS = {"size_mismatch": {"dimensions"}, "floor_shift": {"shift", "baseHeight"},
               "floating_part": set(), "front_check": {"facing"}, "coplanar_overlap": set(),
                "generic_name": set(), "heavy": {"triangles"}, "tiny_part": set(), "fit_exceeded": {"dimensions"},
                "print_small_text": {"item", "capHeightMm"}, "print_clipped": {"item"}}
checks = module("protocol")
_ok, _int, _num, _keys, _list, _vector = (
    checks._ok, checks._int, checks._num, checks._keys, checks._list, checks._vector)
ModelImportError = module("errors").ModelImportError


def digest(value):
    return sha256(json_bytes(value)).hexdigest()


def text(value, maximum):
    _ok(type(value) is str and 0 < len(value) <= maximum and all(ord(c) >= 32 for c in value))


def provenance(recipe):
    portable, metadata = portable_recipe(recipe)
    return {"generator": ENGINE_VERSION, "hangHeight": recipe["hangHeight"], "sizeBasis": portable["sizeBasis"],
            "sources": metadata["sources"], "sitePrivate": {"references": metadata["references"]}}


def make_result(build, allowed):
    value = {"schemaVersion": 1, "kind": "build", "engineVersion": ENGINE_VERSION,
             "recipeSha256": digest(build.recipe), "allowedSha256": digest(allowed),
             "outputSha256": sha256(build.glb).hexdigest(), "outputBytes": len(build.glb),
             "dimensions": build.dimensions, "catalogDimensions": build.catalog_dimensions, "shift": build.shift,
             "triangles": build.triangles,
             "parts": [{"key": p.key, "name": p.name, "material": p.material, "triangles": len(p.indices)}
                       for p in build.model.parts],
              "partMap": build.part_map, "materials": build.model.materials,
              "images": [{"entryId": key, "width": p.width, "height": p.height, "mimeType": "image/png",
                          "bytes": len(p.data), "sha256": sha256(p.data).hexdigest()} for key, p in build.prints.items()],
              "surfaces": build.surfaces,
             "footprint": build.footprint, "lints": build.lints, "warnings": build.warnings,
             "budgets": build.budgets, "provenance": build.provenance}
    return validate_result(value, build.recipe, allowed)


def panels(recipe):
    result = {}
    def visit(entries):
        for entry in entries:
            if "group" in entry:
                visit(entry["group"])
            elif entry.get("shape") == "panel":
                result[entry["id"]] = entry
    visit(recipe["entries"])
    return result


def _images(images, recipe):
    expected, seen, pixels = panels(recipe), set(), 0
    _list(images, 8)
    for image in images:
        _keys(image, {"entryId", "width", "height", "mimeType", "bytes", "sha256"})
        key = image["entryId"]
        _ok(isinstance(key, str) and key in expected and key not in seen)
        seen.add(key)
        _int(image["width"], 1, 1024)
        _int(image["height"], 1, 1024)
        _ok((image["width"], image["height"]) == panel_pixels(expected[key]))
        pixels += image["width"]*image["height"]
        _ok(image["mimeType"] == "image/png")
        _int(image["bytes"], 1, image["width"]*image["height"]*4+65536)
        _ok(isinstance(image["sha256"], str) and re.fullmatch("[0-9a-f]{64}", image["sha256"]))
    _ok(seen == set(expected) and pixels <= MAX_PRINT_PIXELS and pixels <= MAX_TEXTURE_PIXELS)


def _materials(materials, allowed, images, recipe):
    _list(materials, 64)
    _ok(bool(materials))
    required = {"name", "baseColor", "texture", "alphaMode", "alphaCutoff", "emissive",
                "doubleSided", "roughness", "metalness", "unlit"}
    optional = {"defaultFinish", "artwork", "finishGroup", "emissiveTexture"}
    for material in materials:
        _ok(type(material) is dict and required <= set(material) <= required | optional)
        text(material["name"], 120)
        _vector(material["baseColor"], 4, 0, 1)
        _vector(material["emissive"], 3, 0, 1)
        for key in ("roughness", "metalness", "alphaCutoff"):
            _num(material[key], 0, 1)
        _ok(material["alphaMode"] in ("OPAQUE", "MASK", "BLEND"))
        for key in ("doubleSided", "unlit", "artwork"):
            if key in material:
                _ok(type(material[key]) is bool)
        if material["name"].startswith("print:"):
            key = material["name"][6:]
            entry = panels(recipe)[key]
            authored = recipe["materials"][entry["material"]]
            texture = material["texture"]
            _keys(texture, {"image", "wrapS", "wrapT"})
            _int(texture["image"], 0, len(images)-1)
            _ok(texture["wrapS"] == texture["wrapT"] == 33071 and images[texture["image"]]["entryId"] == key)
            _ok(material.get("artwork") is True and "defaultFinish" not in material)
            _ok(material["baseColor"] == [1, 1, 1, authored["opacity"]] and not material["unlit"])
            _ok(material["emissive"] == [authored["lit"]]*3)
            _ok(material.get("emissiveTexture") == (texture if authored["lit"] > 0 else None))
        else:
            # Composition extends this contract in MB3. Only authored prints can
            # introduce image references in MB2.
            _ok(material["texture"] is None and material.get("emissiveTexture") is None)
        if "finishGroup" in material:
            text(material["finishGroup"], 120)
        if "defaultFinish" in material:
            finish = material["defaultFinish"]
            _ok(type(finish) is dict and {"appearanceId"} <= set(finish) <=
                {"appearanceId", "color", "roughness", "metalness"})
            _ok(finish["appearanceId"] in allowed["appearanceIds"])
            if "color" in finish:
                _ok(isinstance(finish["color"], str) and re.fullmatch("#[0-9a-f]{6}", finish["color"]))
            for key in ("roughness", "metalness"):
                if key in finish:
                    _num(finish[key], 0, 1)


def _parts_and_map(value, recipe):
    parts, materials = value["parts"], value["materials"]
    _list(parts, 400)
    _ok(bool(parts))
    keys = set()
    by_name_material = {}
    node_indices = {name: i for i, name in enumerate(sorted({p["name"] for p in parts}))}
    ordinals = {}
    for part in parts:
        _keys(part, {"key", "name", "material", "triangles"})
        text(part["key"], 512)
        text(part["name"], 80)
        _int(part["material"], 0, len(materials)-1)
        _int(part["triangles"], 1, 60000)
        name, material_name = part["name"], materials[part["material"]]["name"]
        # Same name/path encoding as component_inventory, without importing it.
        encoded = "".join(chr(c) if c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
                          else f"%{c:02X}" for c in name.encode("utf-8"))
        ordinal = ordinals.get(name, 0)
        ordinals[name] = ordinal+1
        key = f"p:{encoded}#{ordinal}"
        if len(key) > 512:
            key = f"p:@{node_indices[name]}#{ordinal}"
        _ok(part["key"] == key and key not in keys and (name, material_name) not in by_name_material)
        keys.add(key)
        by_name_material[name, material_name] = key
    _ok(sum(p["triangles"] for p in parts) == value["triangles"])
    _ok(len(parts) == value["budgets"]["primitives"])
    _keys(value["partMap"], {"entries", "instances"})
    expected_entries = {}
    def entries(items):
        result = set()
        for entry in items:
            if "group" in entry:
                selected = entries(entry["group"])
            else:
                material_names = (["back:"+entry["material"]+":"+entry["back"], "print:"+entry["id"]]
                                  if entry["shape"] == "panel" else [entry["material"]])
                selected = {by_name_material[entry["name"], material] for material in material_names}
            expected_entries[entry["id"]] = sorted(selected)
            result.update(selected)
        return result
    _ok(entries(recipe["entries"]) == keys)
    _ok(value["partMap"]["entries"] == expected_entries)
    expected_instances = {}
    def instances(items, prefix=""):
        for entry in items:
            for index in range(copies(entry)):
                key = prefix + entry["id"] + f"[{index}]"
                expected_instances[key] = expected_entries[entry["id"]]
                if "group" in entry:
                    instances(entry["group"], key + "/")
    instances(recipe["entries"])
    _ok(len(expected_instances) <= 12000 and value["partMap"]["instances"] == expected_instances)


def _lints(value, recipe):
    _list(value["lints"], 20*len(LINT_FIELDS))
    counts = {}
    for item in value["lints"]:
        _ok(type(item) is dict and isinstance(item.get("code"), str) and item["code"] in LINT_FIELDS)
        code = item["code"]
        _keys(item, {"code", "entryIds", "instances"} | LINT_FIELDS[code])
        counts[code] = counts.get(code, 0)+1
        _ok(counts[code] <= 20)
        for field, choices in (("entryIds", value["partMap"]["entries"]), ("instances", value["partMap"]["instances"])):
            _list(item[field], 2)
            _ok(all(isinstance(v, str) and v in choices for v in item[field]))
            _ok(item[field] == sorted(set(item[field])))
        if "dimensions" in item:
            _list(item["dimensions"], 3)
            _ok(bool(item["dimensions"]) and set(item["dimensions"]) <= {"width", "height", "depth"})
        if code == "floor_shift":
            _vector(item["shift"], 3, -30, 30)
            _num(item["baseHeight"], 0, 3)
            _ok(item["shift"] == value["shift"] and item["baseHeight"] == recipe["hangHeight"])
        if code == "front_check":
            _vector(item["facing"], 3, -1, 1)
        if code == "heavy":
            _ok(type(item["triangles"]) is int and item["triangles"] == value["triangles"] > 20000)
        if code in ("print_small_text", "print_clipped"):
            _ok(len(item["entryIds"]) == len(item["instances"]) == 1)
            entry = panels(recipe)[item["entryIds"][0]]
            _int(item["item"], 0, len(entry["print"]["items"])-1)
            if code == "print_small_text":
                _ok("text" in entry["print"]["items"][item["item"]])
                _num(item["capHeightMm"], 0, 6)
    _list(value["warnings"], 20)
    for warning in value["warnings"]:
        text(warning, 300)


def validate_result(value, recipe, allowed):
    try:
        _ok(len(json_bytes(value)) <= RESULT_BYTES)
        _keys(value, KEYS)
        _ok(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1
            and value["kind"] == "build" and value["engineVersion"] == ENGINE_VERSION)
        _ok(value["recipeSha256"] == digest(recipe) and value["allowedSha256"] == digest(allowed))
        _ok(isinstance(value["outputSha256"], str) and re.fullmatch("[0-9a-f]{64}", value["outputSha256"]))
        _int(value["outputBytes"], 1, GLB_BYTES)
        for name in ("dimensions", "catalogDimensions"):
            _keys(value[name], {"width", "height", "depth"})
            for size in value[name].values():
                _num(size, 1e-8, 30)
        _ok(value["catalogDimensions"] == dict(value["dimensions"],
                                               height=recipe["hangHeight"]+value["dimensions"]["height"]))
        _vector(value["shift"], 3, -30, 30)
        _int(value["triangles"], 1, 60000)
        _ok(json_bytes(value["budgets"]) == json_bytes(estimate(recipe))
            and value["triangles"] == value["budgets"]["triangles"])
        _ok(json_bytes(value["provenance"]) == json_bytes(provenance(recipe)))
        _images(value["images"], recipe)
        _materials(value["materials"], allowed, value["images"], recipe)
        _parts_and_map(value, recipe)
        support_recipe = deepcopy(recipe)
        for surface in support_recipe["surfaces"]:
            surface["height"] += value["shift"][1]
            surface["rect"] = [v+value["shift"][0 if i % 2 == 0 else 2] for i, v in enumerate(surface["rect"])]
            _ok(surface["height"] >= recipe["hangHeight"]-1e-7)
        prepare = module("prepare_protocol")
        prepare._surfaces({"recipe": support_recipe, "dimensions": value["catalogDimensions"],
                           "surfaces": value["surfaces"]})
        # Footprint points come from float32 Part arrays; size is measured from
        # float64 kernel components. Allow float32 rounding at the +/-15 m cap.
        prepare._footprint(dict(value, dimensions=dict(value["dimensions"],
            width=value["dimensions"]["width"]+4e-6, depth=value["dimensions"]["depth"]+4e-6)))
        _lints(value, recipe)
        return value
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError, RecursionError, ModelImportError):
        raise ModelImportError("model_worker_failed") from None


def read_result(job, recipe, allowed):
    try:
        value = validate_result(parse_json(read_bytes(job, "result.json", RESULT_BYTES), RESULT_BYTES), recipe, allowed)
        payload = read_bytes(job, "model.glb", GLB_BYTES)
        _ok(len(payload) == value["outputBytes"] and sha256(payload).hexdigest() == value["outputSha256"])
        return value, payload
    except (OSError, ValueError, KeyError, TypeError, ModelImportError):
        raise ModelImportError("model_worker_failed") from None


def validate_glb_metadata(document, result, *, payload=None):
    """Bind the part map and material metadata to the flat grouped GLB we return."""
    try:
        _ok(document["asset"]["generator"] == ENGINE_VERSION)
        expected = {}
        for part in result["parts"]:
            expected.setdefault(part["name"], []).append(part)
        _ok(len(document["nodes"]) == len(document["meshes"]) == len(expected))
        _ok(len(document["materials"]) == result["budgets"]["materials"])
        _ok(document["scene"] == 0 and document["scenes"] == [{"nodes": list(range(len(expected)))}])
        image_bindings = {}
        def texture(info, source):
            _keys(info, {"index", "texCoord"})
            _ok(type(info["texCoord"]) is int and info["texCoord"] == 0)
            _int(info["index"], 0, len(document["textures"])-1)
            record = document["textures"][info["index"]]
            _keys(record, {"source", "sampler"})
            _int(record["source"], 0, len(document["images"])-1)
            _int(record["sampler"], 0, len(document["samplers"])-1)
            _ok(document["samplers"][record["sampler"]] == {"wrapS": source["wrapS"], "wrapT": source["wrapT"],
                                                          "magFilter": 9729, "minFilter": 9987})
            prior = image_bindings.setdefault(source["image"], record["source"])
            _ok(prior == record["source"])
            return info
        for index, (name, parts) in enumerate(expected.items()):
            _ok(document["nodes"][index] == {"name": name, "mesh": index})
            mesh = document["meshes"][index]
            _ok(mesh["name"] == name and len(mesh["primitives"]) == len(parts))
            for primitive, part in zip(mesh["primitives"], parts):
                accessor = document["accessors"][primitive["indices"]]
                _ok(primitive["mode"] == 4 and accessor["type"] == "SCALAR"
                    and accessor["count"] == 3*part["triangles"])
                source = result["materials"][part["material"]]
                actual = document["materials"][primitive["material"]]
                _ok(actual["name"] == f"{name} ({source['name']})")
                extras = {"facilityAuthoredFinish": True, "facilityMaterialRole": name,
                          **module("extended_materials").write_extras(source)}
                _ok(actual["extras"] == extras)
                expected_pbr = {"baseColorFactor": source["baseColor"],
                                "roughnessFactor": source["roughness"], "metallicFactor": source["metalness"]}
                if source["texture"] is not None:
                    _ok("TEXCOORD_0" in primitive["attributes"])
                    expected_pbr["baseColorTexture"] = texture(actual["pbrMetallicRoughness"]["baseColorTexture"], source["texture"])
                _ok(actual["pbrMetallicRoughness"] == expected_pbr)
                if source.get("emissiveTexture") is not None:
                    _ok(texture(actual["emissiveTexture"], source["emissiveTexture"]) == expected_pbr["baseColorTexture"])
                else:
                    _ok("emissiveTexture" not in actual)
                for source_key, target in (("alphaMode", "alphaMode"), ("alphaCutoff", "alphaCutoff"),
                                           ("doubleSided", "doubleSided"), ("emissive", "emissiveFactor")):
                    _ok(actual[target] == source[source_key])
                _ok(actual.get("extensions", {}) == ({"KHR_materials_unlit": {}} if source["unlit"] else {}))
        count = len(result["images"])
        for name in ("images", "textures", "samplers"):
            _ok(len(document.get(name, [])) == count)
        _ok(set(image_bindings) == set(range(count)) and len(set(image_bindings.values())) == count)
        if count:
            _ok(isinstance(payload, bytes) and len(payload) <= GLB_BYTES)
            json_size = struct.unpack_from("<I", payload, 12)[0]
            binary_size, binary_kind = struct.unpack_from("<I4s", payload, 20+json_size)
            binary_start = 28+json_size
            _ok(binary_kind == b"BIN\0" and binary_start+binary_size == len(payload))
            for source_index, glb_index in image_bindings.items():
                record, expected_image = document["images"][glb_index], result["images"][source_index]
                _keys(record, {"bufferView", "mimeType"})
                _ok(record["mimeType"] == "image/png")
                _int(record["bufferView"], 0, len(document["bufferViews"])-1)
                view = document["bufferViews"][record["bufferView"]]
                _keys(view, {"buffer", "byteOffset", "byteLength"})
                _ok(type(view["buffer"]) is int and view["buffer"] == 0)
                _int(view["byteOffset"], 0, binary_size)
                _int(view["byteLength"], 1, binary_size-view["byteOffset"])
                start = binary_start+view["byteOffset"]
                data = payload[start:start+view["byteLength"]]
                _ok(len(data) == expected_image["bytes"] and sha256(data).hexdigest() == expected_image["sha256"])
                _ok(png_dimensions(data) == (expected_image["width"], expected_image["height"]))
    except (ValueError, KeyError, IndexError, TypeError, struct.error, ModelImportError):
        raise ModelImportError("model_worker_failed") from None
