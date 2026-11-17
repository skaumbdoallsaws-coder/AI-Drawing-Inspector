"""Convert kernel components into the import writer's Model/Part shape."""
from collections import OrderedDict
from copy import deepcopy

import numpy as np

from .imports import module


def material_key(component):
    entry = component.entry
    if component.role == "include":
        return component.include_material_key
    if component.role == "print":
        return "print:" + entry["id"]
    if component.role == "back":
        return "back:" + entry["material"] + ":" + entry["back"]
    return entry["material"]


def material_value(component, recipe, image_indices):
    entry = component.entry
    if component.include_material is not None:
        result = deepcopy(component.include_material)
        for key in ("texture", "emissiveTexture"):
            if result.get(key) is not None:
                source = result[key]["image"]
                result[key]["image"] = image_indices[f"include:{entry['id']}:{source}"]
        return result
    value = deepcopy(recipe["materials"][component.include_material_key if component.role == "include" else entry["material"]])
    result = module("materials").default_material()
    color = module("transforms").linear_color
    if component.role == "print":
        from .errors import require
        require("finish" not in value, component.path + ".material",
                "Printed front materials cannot have a default finish", "print_invalid")
        value["color"] = "#ffffff"
        result.update(artwork=True, texture={"image": image_indices[entry["id"]], "wrapS": 33071, "wrapT": 33071})
        if value["lit"] > 0:
            result["emissiveTexture"] = dict(result["texture"])
    elif component.role == "back":
        value["color"] = entry["back"]
        value["lit"] = 0
    result.update(name=material_key(component), baseColor=color(value["color"]) + [value["opacity"]],
                  roughness=value["roughness"], metalness=value["metalness"],
                  emissive=[v*value["lit"] for v in color(value["color"])],
                  alphaMode="BLEND" if value["opacity"] < 1 else "OPAQUE")
    if "finish" in value:
        result["defaultFinish"] = deepcopy(value["finish"])
    return result


def encode_name(name):
    return "".join(chr(c) if c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
                   else f"%{c:02X}" for c in name.encode("utf-8"))


def to_model(components, recipe, prints, includes=None):
    api = module("model")
    image_indices = {entry_id: i for i, entry_id in enumerate(prints)}
    images = [api.ModelImage(p.data, "image/png", p.width, p.height, p.width, p.height) for p in prints.values()]
    for entry_id, item in (includes or {}).items():
        used = sorted({m[key]["image"] for m in item["materials"].values() for key in ("texture", "emissiveTexture")
                       if m.get(key) is not None})
        for source in used:
            image_indices[f"include:{entry_id}:{source}"] = len(images)
            images.append(item["model"].images[source])
    materials, material_indices, groups = [], {}, OrderedDict()
    for component in components:
        key = material_key(component)
        if key not in material_indices:
            material_indices[key] = len(materials)
            materials.append(material_value(component, recipe, image_indices))
        group = (component.output_name or component.entry["name"], key)
        groups.setdefault(group, []).append(component)
    parts, entries, instances, node_ordinals, include_maps = [], {}, {}, {}, {}
    node_indices = {name: i for i, name in enumerate(sorted({name for name, _ in groups}))}
    for (name, material), batch in sorted(groups.items()):
        primitive = node_ordinals.get(name, 0)
        node_ordinals[name] = primitive+1
        key = f"p:{encode_name(name)}#{primitive}"
        if len(key) > 512:  # component_inventory.part_key, without importing the application.
            key = f"p:@{node_indices[name]}#{primitive}"
        positions, normals, uv, indices, offset = [], [], [], [], 0
        any_uv = any(c.mesh.uv is not None for c in batch)
        for component in batch:
            mesh = component.mesh
            # Flat normals retain sharp box edges; manifold checks use welded positions.
            triangles = mesh.positions[mesh.indices]
            normal = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
            normal /= np.linalg.norm(normal, axis=1)[:, None]
            points = triangles.reshape(-1, 3)
            positions.append(points)
            normals.append(mesh.normals[mesh.indices].reshape(-1, 3) if mesh.normals is not None
                           else np.repeat(normal, 3, axis=0))
            if any_uv:
                uv.append(mesh.uv[mesh.indices].reshape(-1, 2) if mesh.uv is not None else np.zeros((len(points), 2)))
            indices.append(np.arange(offset, offset+len(points), dtype=np.uint32).reshape(-1, 3))
            offset += len(points)
            for entry_id in (*component.ancestors, component.entry["id"]):
                entries.setdefault(entry_id, set()).add(key)
            if component.include_key is not None:
                include_maps.setdefault(component.entry["id"], {})[component.include_key] = key
            segments = component.instance.split("/")
            for length in range(1, len(segments)+1):
                instances.setdefault("/".join(segments[:length]), set()).add(key)
        parts.append(api.Part(key, name, name, name, material_indices[material],
                              np.concatenate(positions).astype(np.float32), np.concatenate(normals).astype(np.float32),
                              np.concatenate(uv).astype(np.float32) if any_uv else None, np.concatenate(indices)))
    model = api.Model(recipe["name"], "recipe", 0, "", "model-builder-1", parts, materials, images, {})
    mapping = {"entries": {k: sorted(v) for k, v in sorted(entries.items())},
               "instances": {k: sorted(v) for k, v in sorted(instances.items())}}
    return model, mapping, include_maps, list(image_indices)
