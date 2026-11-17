"""Composition preflight and copied-input contract; stdlib only, no geometry decode.

Stable keys deliberately match component_inventory (covered by a parity test).
The worker never opens catalog paths: it receives fixed basenames and pinned bytes.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import math
import struct

from .budgets import INCLUDE_BYTES, TOTAL_INCLUDE_BYTES, estimate
from .errors import ModelBuildError, require
from .imports import module
from .schema import PATTERNS

MANIFEST_BYTES = 64 * 1024
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def entries(recipe):
    def visit(items, path, ancestors):
        for i, entry in enumerate(items):
            location = f"{path}[{i}]"
            if "include" in entry:
                yield entry, location, ancestors
            elif "group" in entry:
                yield from visit(entry["group"], location + ".group", (*ancestors, entry))
    return list(visit(recipe["entries"], "$.entries", ()))


def encode_name(name):
    # Once the encoded path is longer than 512, inventory uses @node instead.
    # Avoid expanding a hostile multi-megabyte node name just to discard it.
    return "".join(chr(c) if c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
                   else f"%{c:02X}" for c in name.encode("utf-8")[:513])


def image_size(data):
    """Header-only allocation estimate. The limited reader validates/decompresses later."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33 and data[12:16] == b"IHDR":
        return struct.unpack_from(">II", data, 16)
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset < len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            marker = data[offset]
            offset += 1
            if marker in (0xd9, 0xda):
                break
            length = struct.unpack_from(">H", data, offset)[0]
            if length < 2 or offset+length > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2):
                height, width = struct.unpack_from(">HH", data, offset+3)
                return width, height
            offset += length
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X" and len(data) >= 30:
            return int.from_bytes(data[24:27], "little")+1, int.from_bytes(data[27:30], "little")+1
        if data[12:16] == b"VP8L" and len(data) >= 25 and data[20] == 0x2f:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3fff)+1, ((bits >> 14) & 0x3fff)+1
        if data[12:16] == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack_from("<HH", data, 26)
            return w & 0x3fff, h & 0x3fff
    raise ValueError("Unsupported image header")


def artifact_info(payload, path="$.include"):
    """Bounded scene inventory and upper bounds, before numpy/Pillow allocation.

    This is not a substitute for the reader's accessor, geometry or image checks.
    Even assets over the build triangle budget can be inspected without expansion.
    """
    try:
        require(isinstance(payload, bytes) and len(payload) <= INCLUDE_BYTES, path,
                "Include exceeds 8 MiB", "budget_exceeded")
        container = module("containers").open_container(payload)
        doc = container.document
        require(container.format == "glb" and not doc.get("skins") and not doc.get("animations"), path,
                "Includes require a static self-contained GLB", "include_invalid")
        nodes, meshes, accessors = doc.get("nodes", []), doc.get("meshes", []), doc.get("accessors", [])
        materials, images = doc.get("materials", []), doc.get("images", [])
        require(len(nodes) <= 4096 and len(meshes) <= 4096 and len(materials) <= 64 and len(images) <= 32,
                path, "Include resource tables exceed their limits", "budget_exceeded")
        def indexed(values, index):
            if type(index) is not int or not 0 <= index < len(values):
                raise ValueError("Invalid resource index")
            return values[index]
        roots = indexed(doc["scenes"], doc.get("scene", 0)).get("nodes", [])
        seen, parts, serial, print_images = set(), [], [0], set()
        clean = module("validation").clean_text
        def visit(children, prefix, depth):
            if depth > 64 or len(children) > 4096:
                raise ValueError("Invalid hierarchy")
            names = [indexed(nodes, i).get("name") for i in children]
            names = [n if isinstance(n, str) and n else None for n in names]
            counts, ordinals = Counter(names), Counter()
            for index, name in zip(children, names):
                if index in seen:
                    raise ValueError("Repeated or cyclic node")
                seen.add(index)
                node = nodes[index]
                segment = (encode_name(name) + (f"~{ordinals[name]}" if counts[name] > 1 else "")) if name else f"@{index}"
                ordinals[name] += 1
                node_path = ("x"*513 if len(prefix) > 512 else prefix + "/" + segment) if prefix else segment
                if "mesh" in node:
                    mesh = indexed(meshes, node["mesh"])
                    for ordinal, primitive in enumerate(mesh["primitives"]):
                        import_key = f"p{serial[0]}"
                        serial[0] += 1
                        if serial[0] > 4096:
                            raise ValueError("Too many primitives")
                        mode = primitive.get("mode", 4)
                        if type(mode) is not int or not 0 <= mode <= 6:
                            raise ValueError("Invalid primitive mode")
                        if mode < 4:
                            continue
                        accessor = indexed(accessors, primitive.get("indices", primitive["attributes"]["POSITION"]))
                        count = accessor["count"]
                        if type(count) is not int or not 3 <= count <= 90_000_000:
                            raise ValueError("Invalid accessor count")
                        triangles = count // 3 if mode == 4 else count-2
                        material_index = primitive.get("material", -1)
                        raw = indexed(materials, material_index) if material_index != -1 else {}
                        extras = module("extended_materials").read_extras(raw)
                        key = f"p:{node_path}#{ordinal}"
                        if len(key) > 512:
                            key = f"p:@{index}#{ordinal}"
                        part_name = clean(node.get("name"), 512) or clean(raw.get("name")) or clean(mesh.get("name")) or import_key
                        pbr = raw.get("pbrMetallicRoughness", {})
                        legacy = raw.get("extensions", {}).get("KHR_materials_pbrSpecularGlossiness", {})
                        textured = any(v is not None for v in (pbr.get("baseColorTexture"), raw.get("emissiveTexture"),
                                      raw.get("normalTexture"), raw.get("occlusionTexture"), pbr.get("metallicRoughnessTexture"),
                                      legacy.get("diffuseTexture"), legacy.get("specularGlossinessTexture")))
                        if extras.get("artwork"):
                            for texture in (pbr.get("baseColorTexture"), raw.get("emissiveTexture"), legacy.get("diffuseTexture")):
                                if texture is not None:
                                    source = indexed(doc.get("textures", []), texture["index"])["source"]
                                    indexed(images, source)
                                    print_images.add(source)
                        parts.append({"key": key, "importKey": import_key, "name": part_name,
                                      "node": clean(node.get("name")), "mesh": clean(mesh.get("name")),
                                      "material": clean(raw.get("name")), "materialIndex": material_index,
                                      "triangles": triangles, "artwork": extras.get("artwork", False),
                                      "textured": textured, "extras": extras})
                visit(node.get("children", []), node_path, depth+1)
        visit(roots, "", 0)
        if not parts:
            raise ValueError("No triangle primitives")
        sizes = []
        for image in images:
            if "uri" in image:
                raise ValueError("External image")
            view = indexed(doc.get("bufferViews", []), image["bufferView"])
            offset, length = view.get("byteOffset", 0), view["byteLength"]
            if (view.get("buffer", 0) != 0 or type(offset) is not int or type(length) is not int
                    or offset < 0 or length <= 0 or offset+length > len(container.binary or b"")):
                raise ValueError("Invalid image buffer")
            width, height = image_size(container.binary[offset:offset+length])
            if not 1 <= width <= 8192 or not 1 <= height <= 8192:
                raise ValueError("Image dimensions exceed limit")
            sizes.append([width, height])
        pixels = sum(w*h for w, h in sizes)
        printed = sum(p["artwork"] for p in parts)
        return {"parts": parts, "imageSizes": sizes,
                "stats": {"bytes": len(payload), "triangles": sum(p["triangles"] for p in parts),
                          "primitives": len(parts), "materials": len({(p["name"], p["materialIndex"]) for p in parts}),
                          "texturePixels": pixels, "printedPanels": printed,
                          "printPixels": sum(sizes[i][0]*sizes[i][1] for i in print_images)}}
    except ModelBuildError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError, UnicodeError,
            struct.error, module("errors").ModelImportError):
        raise ModelBuildError("include_invalid", path, "Include is not a supported static GLB") from None


def validate_manifest(record, entry, path):
    required = {"id", "assetId", "revision", "artifactSha256", "sourceToCanonical", "attribution", "hasSurfaces"}
    require(type(record) is dict and set(record) == required, path, "Invalid includes manifest", "job_invalid")
    for target, source in (("id", "id"), ("assetId", "include"), ("revision", "revision"), ("artifactSha256", "artifactSha256")):
        require(record[target] == entry[source], path + "." + source, "Include manifest identity changed", "include_mismatch")
    matrix = record["sourceToCanonical"]
    require(type(matrix) is list and len(matrix) == 16 and all(type(v) in (int, float) and math.isfinite(v)
            and abs(v) <= 1e9 for v in matrix) and matrix[3::4] == [0, 0, 0, 1], path,
            "sourceToCanonical must be a finite affine column-major matrix", "include_invalid")
    a, b, c, d, e, f, g, h, i = (matrix[j] for j in (0, 4, 8, 1, 5, 9, 2, 6, 10))
    require(abs(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)) > 1e-15, path,
            "sourceToCanonical must be invertible", "include_invalid")
    require(type(record["hasSurfaces"]) is bool, path, "Invalid support-surface flag", "job_invalid")
    credit = record["attribution"]
    if credit is not None:
        fields = {"title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl", "licenseClass", "changes", "statedBy"}
        require(type(credit) is dict and not set(credit)-fields and credit.get("licenseClass") in ("cc-by", "cc-by-sa"),
                path, "Invalid include credit", "include_licence")
        require(all(type(v) is str and len(v) <= (600 if k == "changes" else 300)
                    and all(ord(c) >= 32 for c in v) for k, v in credit.items()), path,
                "Invalid include credit text", "include_licence")
        for field in ("authorUrl", "sourceUrl", "licenseUrl"):
            if credit.get(field):
                require(module("licence").https_url(credit[field]) == credit[field], path,
                        "Invalid include credit URL", "include_licence")


def prepare_sources(recipe, sources=None):
    sources = sources or {}
    expected = entries(recipe)
    require(set(sources) == {entry["id"] for entry, _, _ in expected}, "$.includes",
            "Provide the pinned catalog artifact for every include", "include_missing")
    result, attribution = {}, None
    for entry, path, ancestors in expected:
        item = sources[entry["id"]]
        record, payload = item["manifest"], item["payload"]
        validate_manifest(record, entry, path)
        require(isinstance(payload, bytes) and sha256(payload).hexdigest() == entry["artifactSha256"],
                path + ".artifactSha256", "Copied include hash differs from its pin", "include_mismatch")
        for group in ancestors:
            require(not any(group.get("scatter", {}).get("sizeJitter", [])), path,
                    "Includes keep their real size; enclosing scatter cannot use sizeJitter", "include_invalid")
        if record["attribution"] is not None:
            require(attribution is None, path, "Only one attributed include is supported in the whole chain", "include_licence")
            attribution = deepcopy(record["attribution"])
        info = artifact_info(payload, path)
        plans = planned_parts(entry, info, path)
        # Recolor can split two same-named source primitives that shared a material.
        # Count the planned output materials, before any geometry is decoded.
        info["stats"]["materials"] = len({(p["outputName"], p["materialKey"]) for p in plans})
        result[entry["id"]] = {"manifest": deepcopy(record), "payload": payload, "info": info}
    estimate(recipe, include_stats={k: v["info"]["stats"] for k, v in result.items()})
    return result, attribution


def planned_parts(entry, info, path):
    """Resolve selectors against source identities, then choose output identities."""
    parts = deepcopy(info["parts"])
    for part in parts:
        part["outputName"] = entry["name"] + ": " + part["name"]
        require(len(part["outputName"]) <= 512, path + ".name", "Prefixed part name exceeds 512 characters", "include_invalid")
        part["materialKey"] = f"include:{entry['id']}:{part['materialIndex']}"
        part["replacement"] = None
    for i, rule in enumerate(entry["recolor"]):
        selector, where = rule["select"], f"{path}.recolor[{i}].select"
        if isinstance(selector, str):
            chosen = [p for p in parts if p["key"] == selector]
        else:
            field, value = next(iter(selector.items()))
            chosen = [p for p in parts if field == "all" or p["importKey" if field == "part" else field] == value]
        require(bool(chosen), where, "No included part matches the selector", "recolor_invalid")
        require(not any(p["artwork"] or p["textured"] for p in chosen), where,
                "Printed or textured parts cannot be recolored", "recolor_invalid")
        for part in chosen:
            part["materialKey"] = part["replacement"] = rule["material"]
    return parts


def read_sources(job, recipe):
    from .job_io import directory, names, read_bytes, read_json
    folder = directory(job / "includes")
    wanted = entries(recipe)
    if not wanted:
        require(not names(folder, 0), "$.includes", "Unexpected include files", "job_invalid")
        return {}
    require(names(folder, 4) == {"manifest.json", *(f"{i}.glb" for i in range(len(wanted)))},
            "$.includes", "Missing or unexpected include files", "include_missing")
    manifest = read_json(folder, "manifest.json", MANIFEST_BYTES)
    require(type(manifest) is list and len(manifest) == len(wanted), "$.includes", "Invalid include list", "job_invalid")
    result, total = {}, 0
    for i, (entry, path, _) in enumerate(wanted):
        validate_manifest(manifest[i], entry, path)
        payload = read_bytes(folder, f"{i}.glb", INCLUDE_BYTES)
        total += len(payload)
        require(total <= TOTAL_INCLUDE_BYTES, path, "Includes exceed 16 MiB", "budget_exceeded")
        require(sha256(payload).hexdigest() == entry["artifactSha256"], path + ".artifactSha256",
                "Copied include hash differs from its pin", "include_mismatch")
        result[entry["id"]] = {"manifest": manifest[i], "payload": payload}
    return result
