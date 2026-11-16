"""Deterministic self-contained textured GLB output for the authored catalog."""
import struct

import numpy as np

from .model import Model
from .recipe import MODEL_IMPORT_ENGINE_VERSION
from .transforms import triangle_budget
from .validation import json_bytes, require

GLB_BYTES = 30 * 1024 * 1024


def write_glb(model: Model, *, generator=MODEL_IMPORT_ENGINE_VERSION, grouped=False, extended_materials=False) -> bytes:
    triangle_budget(model.parts)
    require(isinstance(generator, str) and 0 < len(generator) <= 128, "gltf_invalid")
    document = {"asset": {"version": "2.0", "generator": generator},
                "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [], "materials": [],
                "accessors": [], "bufferViews": [], "buffers": [], "images": [], "textures": [], "samplers": []}
    blob = bytearray()
    def view(data, target=None):
        blob.extend(b"\0" * (-len(blob) % 4))
        item = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            item["target"] = target
        blob.extend(data)
        require(len(blob) <= GLB_BYTES, "model_output_too_large")
        document["bufferViews"].append(item)
        return len(document["bufferViews"]) - 1
    accessor_ids, mesh_ids = {}, {}
    def accessor(values, kind, component, target, position=False):
        values = np.ascontiguousarray(values, dtype="<u4" if component == 5125 else "<f4")
        data = values.tobytes()
        key = (kind, component, target, position, data)
        if key in accessor_ids:
            return accessor_ids[key]
        item = {"bufferView": view(data, target), "componentType": component,
                "count": len(values), "type": kind}
        if position:
            item.update(min=values.min(axis=0).astype(float).tolist(), max=values.max(axis=0).astype(float).tolist())
        document["accessors"].append(item)
        accessor_ids[key] = len(document["accessors"]) - 1
        return accessor_ids[key]
    image_map, texture_map, material_map, extensions = {}, {}, {}, set()
    def texture_id(texture):
        key = (texture["image"], texture["wrapS"], texture["wrapT"])
        if key not in texture_map:
            source = texture["image"]
            if source not in image_map:
                image = model.images[source]
                require(image.mime_type in {"image/png", "image/jpeg"} and max(image.width, image.height) <= 2048,
                        "image_unsafe")
                image_map[source] = len(document["images"])
                document["images"].append({"bufferView": view(image.data), "mimeType": image.mime_type})
            index = len(document["textures"])
            document["samplers"].append({"wrapS": key[1], "wrapT": key[2], "magFilter": 9729, "minFilter": 9987})
            document["textures"].append({"source": image_map[source], "sampler": index})
            texture_map[key] = index
        return texture_map[key]
    def material_id(part):
        material = model.materials[part.material]
        key = (json_bytes(material), part.name, part.uv0 is not None)
        if key not in material_map:
            pbr = {"baseColorFactor": material["baseColor"], "roughnessFactor": material["roughness"],
                   "metallicFactor": material["metalness"]}
            if material["texture"] is not None and part.uv0 is not None:
                pbr["baseColorTexture"] = {"index": texture_id(material["texture"]), "texCoord": 0}
            strength = max(1, max(material["emissive"]))
            item = {"name": part.name, "pbrMetallicRoughness": pbr, "alphaMode": material["alphaMode"],
                    "alphaCutoff": material["alphaCutoff"], "doubleSided": material["doubleSided"],
                    "emissiveFactor": [v / strength for v in material["emissive"]],
                    "extras": {"facilityAuthoredFinish": True, "facilityMaterialRole": part.name}}
            if extended_materials:
                from .extended_materials import write_extras
                item["extras"].update(write_extras(material))
                if material.get("emissiveTexture") is not None and part.uv0 is not None:
                    item["emissiveTexture"] = {"index": texture_id(material["emissiveTexture"]), "texCoord": 0}
                if grouped and material.get("name"):
                    item["name"] = f"{part.name} ({material['name']})"
            if strength > 1:
                item.setdefault("extensions", {})["KHR_materials_emissive_strength"] = {"emissiveStrength": strength}
                extensions.add("KHR_materials_emissive_strength")
            if material["unlit"]:
                item.setdefault("extensions", {})["KHR_materials_unlit"] = {}
                extensions.add("KHR_materials_unlit")
            material_map[key] = len(document["materials"])
            document["materials"].append(item)
        return material_map[key]
    grouped_meshes = {}
    for part in (_group_parts(model) if grouped else model.parts):
        attributes = {"POSITION": accessor(part.positions, "VEC3", 5126, 34962, True)}
        if part.normals is not None:
            attributes["NORMAL"] = accessor(part.normals, "VEC3", 5126, 34962)
        if part.uv0 is not None:
            attributes["TEXCOORD_0"] = accessor(part.uv0, "VEC2", 5126, 34962)
        indices = accessor(part.indices.reshape(-1), "SCALAR", 5125, 34963)
        material = material_id(part)
        if grouped:
            if part.name not in grouped_meshes:
                grouped_meshes[part.name] = len(document["meshes"])
                document["meshes"].append({"name": part.name, "primitives": []})
                document["scenes"][0]["nodes"].append(len(document["nodes"]))
                document["nodes"].append({"name": part.name, "mesh": grouped_meshes[part.name]})
            document["meshes"][grouped_meshes[part.name]]["primitives"].append(
                {"attributes": attributes, "indices": indices, "mode": 4, "material": material})
            continue
        mesh_key = (part.name, tuple(attributes.items()), indices, material)
        if mesh_key not in mesh_ids:
            mesh_ids[mesh_key] = len(document["meshes"])
            document["meshes"].append({"name": part.name, "primitives": [
                {"attributes": attributes, "indices": indices, "mode": 4, "material": material}]})
        document["scenes"][0]["nodes"].append(len(document["nodes"]))
        document["nodes"].append({"name": part.name, "mesh": mesh_ids[mesh_key]})
    if extensions:
        document["extensionsUsed"] = sorted(extensions)
    for key in ("images", "textures", "samplers"):
        if not document[key]:
            del document[key]
    blob.extend(b"\0" * (-len(blob) % 4))
    document["buffers"] = [{"byteLength": len(blob)}]
    encoded = json_bytes(document)
    encoded += b" " * (-len(encoded) % 4)
    total = 12 + 8 + len(encoded) + 8 + len(blob)
    require(total <= GLB_BYTES, "model_output_too_large")
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(encoded), b"JSON") + encoded
            + struct.pack("<I4s", len(blob), b"BIN\0") + bytes(blob))


def _group_parts(model):
    """One primitive per (node name, material); enabled only for builder output."""
    from collections import OrderedDict
    from dataclasses import replace
    groups = OrderedDict()
    for part in model.parts:
        groups.setdefault((part.name, json_bytes(model.materials[part.material])), []).append(part)
    for parts in groups.values():
        if len(parts) == 1:
            yield parts[0]
            continue
        positions, normals, uvs, indices, offset = [], [], [], [], 0
        has_normals = all(p.normals is not None for p in parts)
        has_uv = any(p.uv0 is not None for p in parts)
        for part in parts:
            positions.append(part.positions)
            indices.append(part.indices + offset)
            offset += len(part.positions)
            if has_normals:
                normals.append(part.normals)
            if has_uv:
                uvs.append(part.uv0 if part.uv0 is not None else np.zeros((len(part.positions), 2), dtype=np.float32))
        yield replace(parts[0], positions=np.concatenate(positions), indices=np.concatenate(indices),
                      normals=np.concatenate(normals) if has_normals else None,
                      uv0=np.concatenate(uvs) if has_uv else None)
