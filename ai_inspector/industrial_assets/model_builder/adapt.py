"""Convert kernel components into the import writer's Model/Part shape."""
from collections import OrderedDict
from copy import deepcopy

import numpy as np

from .imports import module


def material_key(component):
    entry = component.entry
    if component.role == "print":
        return "print:" + entry["id"]
    if component.role == "back":
        return "back:" + entry["material"] + ":" + entry["back"]
    return entry["material"]


def material_value(component, recipe):
    entry = component.entry
    value = deepcopy(recipe["materials"][entry["material"]])
    result = module("materials").default_material()
    color = module("transforms").linear_color
    if component.role == "print":
        value["color"] = entry["print"]["background"]
        value.pop("finish", None)
        result["artwork"] = True
        # MB2 replaces this flat color with a texture and neutral white factor.
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


def to_model(components, recipe):
    api = module("model")
    materials, material_indices, groups = [], {}, OrderedDict()
    for component in components:
        key = material_key(component)
        if key not in material_indices:
            material_indices[key] = len(materials)
            materials.append(material_value(component, recipe))
        group = (component.entry["name"], key)
        groups.setdefault(group, []).append(component)
    parts, entries, instances, node_ordinals = [], {}, {}, {}
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
            normals.append(np.repeat(normal, 3, axis=0))
            if any_uv:
                uv.append(mesh.uv[mesh.indices].reshape(-1, 2) if mesh.uv is not None else np.zeros((len(points), 2)))
            indices.append(np.arange(offset, offset+len(points), dtype=np.uint32).reshape(-1, 3))
            offset += len(points)
            for entry_id in (*component.ancestors, component.entry["id"]):
                entries.setdefault(entry_id, set()).add(key)
            segments = component.instance.split("/")
            for length in range(1, len(segments)+1):
                instances.setdefault("/".join(segments[:length]), set()).add(key)
        parts.append(api.Part(key, name, name, name, material_indices[material],
                              np.concatenate(positions).astype(np.float32), np.concatenate(normals).astype(np.float32),
                              np.concatenate(uv).astype(np.float32) if any_uv else None, np.concatenate(indices)))
    model = api.Model(recipe["name"], "recipe", 0, "", "model-builder-1", parts, materials, [], {})
    mapping = {"entries": {k: sorted(v) for k, v in sorted(entries.items())},
               "instances": {k: sorted(v) for k, v in sorted(instances.items())}}
    return model, mapping
