"""Validate the complete node graph, budget instances, then flatten the selected scene."""
import numpy as np

from .materials import default_material, transform_uv
from .model import Part
from .validation import clean_text, integer, mapping, reference, require, sequence, vector, warn


def _matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        require(not any(key in node for key in ("translation", "rotation", "scale")))
        matrix = np.array(vector(node["matrix"], 16)).reshape(4, 4).T
        require(bool(np.allclose(matrix[3], [0, 0, 0, 1], rtol=0, atol=1e-9)))
    else:
        translation = vector(node.get("translation", [0, 0, 0]), 3)
        scale = vector(node.get("scale", [1, 1, 1]), 3)
        x, y, z, w = vector(node.get("rotation", [0, 0, 0, 1]), 4)
        length = np.linalg.norm([x, y, z, w])
        require(bool(np.isfinite(length)) and abs(length - 1) <= 1e-3)
        x, y, z, w = np.array([x, y, z, w]) / length
        rotation = np.array([[1 - 2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                             [2*(x*y+z*w), 1 - 2*(x*x+z*z), 2*(y*z-x*w)],
                             [2*(x*z-y*w), 2*(y*z+x*w), 1 - 2*(x*x+y*y)]])
        matrix = np.eye(4)
        matrix[:3, :3] = rotation @ np.diag(scale)
        matrix[:3, 3] = translation
    require(bool(np.isfinite(matrix).all()))
    sign, log_det = np.linalg.slogdet(matrix[:3, :3])
    require(sign != 0 and bool(np.isfinite(log_det)))
    return matrix


def _meshes(document, accessors, limits):
    meshes = sequence(document.get("meshes", []), limits.nodes)
    for mesh in meshes:
        mesh = mapping(mesh)
        require("weights" not in mesh, "gltf_feature_unsupported")
        primitives = sequence(mesh.get("primitives"), limits.primitives)
        require(bool(primitives))
        for primitive in primitives:
            primitive = mapping(primitive)
            require("targets" not in primitive, "gltf_feature_unsupported")
            attrs = mapping(primitive.get("attributes"))
            require("POSITION" in attrs and len(attrs) <= 64)
            count = accessors.item(attrs["POSITION"]).count
            require(count <= limits.vertices, "gltf_too_complex")
            for index in attrs.values():
                require(accessors.item(index).count == count)
            mode = integer(primitive.get("mode", 4), 0, 6)
            index_count = accessors.item(primitive["indices"]).count if "indices" in primitive else count
            if mode == 4:
                require(index_count % 3 == 0)
            if mode >= 4:
                require(index_count >= 3)
    return meshes


def _graph(document, meshes, limits):
    nodes = sequence(document.get("nodes", []), limits.nodes)
    matrices, parents, children = [], [0] * len(nodes), []
    for node in nodes:
        node = mapping(node)
        require("skin" not in node and "weights" not in node, "gltf_feature_unsupported")
        if "mesh" in node:
            reference(node["mesh"], meshes)
        child_ids = sequence(node.get("children", []), limits.nodes)
        require(len(set(integer(c) for c in child_ids)) == len(child_ids))
        for child in child_ids:
            reference(child, nodes)
            parents[child] += 1
            require(parents[child] <= 1)
        children.append(child_ids)
        matrices.append(_matrix(node))
    # Check disconnected nodes as well. Cached subtree height keeps this O(nodes).
    states, heights = [0] * len(nodes), [0] * len(nodes)

    def visit(index, depth):
        require(depth <= limits.depth, "gltf_too_complex")
        require(states[index] != 1)
        if states[index] == 2:
            require(depth + heights[index] - 1 <= limits.depth, "gltf_too_complex")
            return heights[index]
        states[index] = 1
        height = 1 + max((visit(child, depth + 1) for child in children[index]), default=0)
        states[index], heights[index] = 2, height
        return height

    for index in range(len(nodes)):
        visit(index, 1)
    scenes = sequence(document.get("scenes", []), limits.nodes)
    require(bool(scenes), "model_empty")
    for scene in scenes:
        roots = sequence(mapping(scene).get("nodes", []), limits.nodes)
        require(len(set(integer(i) for i in roots)) == len(roots))
        for index in roots:
            reference(index, nodes)
            require(parents[index] == 0)
    scene = scenes[reference(document.get("scene", 0), scenes)]
    return nodes, matrices, children, scene.get("nodes", [])


def _instances(nodes, matrices, children, roots):
    stack = [(index, np.eye(4)) for index in reversed(roots)]
    while stack:
        index, parent = stack.pop()
        with np.errstate(over="ignore", invalid="ignore"):
            world = parent @ matrices[index]
        require(bool(np.isfinite(world).all()))
        sign, log_det = np.linalg.slogdet(world[:3, :3])
        require(sign != 0 and bool(np.isfinite(log_det)))
        yield nodes[index], world
        stack.extend((child, world) for child in reversed(children[index]))


def _triangles(index: np.ndarray, mode: int) -> np.ndarray:
    if mode == 4:
        return index.reshape(-1, 3).copy()
    if mode == 5:
        result = np.column_stack((index[:-2], index[1:-1], index[2:])).copy()
        result[1::2, :2] = result[1::2, 1::-1]
        return result
    return np.column_stack((np.repeat(index[0], len(index) - 2), index[1:-1], index[2:]))


def _float_array(value) -> np.ndarray:
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.asarray(value, dtype=np.float32)
    require(bool(np.isfinite(result).all()))
    return np.ascontiguousarray(result)


def flatten(document, accessors, materials, limits, quantized, warnings) -> list[Part]:
    require(not document.get("skins"), "gltf_feature_unsupported")
    meshes = _meshes(document, accessors, limits)
    nodes, matrices, children, roots = _graph(document, meshes, limits)
    instances = list(_instances(nodes, matrices, children, roots))
    vertices = triangles = primitive_count = 0
    for node, _ in instances:
        if "mesh" not in node:
            continue
        for primitive in meshes[node["mesh"]]["primitives"]:
            primitive_count += 1
            count = accessors.item(primitive["attributes"]["POSITION"]).count
            vertices += count
            count = accessors.item(primitive["indices"]).count if "indices" in primitive else count
            mode = primitive.get("mode", 4)
            triangles += count // 3 if mode == 4 else max(0, count - 2) if mode in (5, 6) else 0
            require(primitive_count <= limits.primitives and vertices <= limits.vertices
                    and triangles <= limits.triangles, "gltf_too_complex")
    parts, default_index, primitive_index = [], None, 0
    for node, world in instances:
        if "mesh" not in node:
            continue
        mesh = meshes[node["mesh"]]
        for primitive in mesh["primitives"]:
            key = "p" + str(primitive_index)
            primitive_index += 1
            attrs, mode = primitive["attributes"], primitive.get("mode", 4)
            count = accessors.item(attrs["POSITION"]).count
            indices = (accessors.index_array(primitive["indices"], count) if "indices" in primitive
                       else np.arange(count, dtype=np.uint32))
            if mode < 4:
                warn(warnings, "Point and line primitives were omitted.")
                continue
            if "material" in primitive:
                material_index = reference(primitive["material"], materials)
            else:
                if default_index is None:
                    require(len(materials) < limits.materials, "gltf_too_complex")
                    default_index = len(materials)
                    materials.append(default_material())
                material_index = default_index
            positions = accessors.attribute(attrs["POSITION"], "POSITION", quantized)
            with np.errstate(over="ignore", invalid="ignore"):
                positions = positions @ world[:3, :3].T + world[:3, 3]
            normals = None
            if "NORMAL" in attrs:
                normals = accessors.attribute(attrs["NORMAL"], "NORMAL", quantized)
                try:
                    with np.errstate(over="ignore", invalid="ignore"):
                        normals = normals @ np.linalg.inv(world[:3, :3])
                        lengths = np.linalg.norm(normals, axis=1)
                        require(bool(np.isfinite(lengths).all()) and bool((lengths > 0).all()))
                        normals = normals / lengths[:, None]
                except np.linalg.LinAlgError:
                    require(False)
            uv = (accessors.attribute(attrs["TEXCOORD_0"], "TEXCOORD_0", quantized)
                  if "TEXCOORD_0" in attrs else None)
            material = materials[material_index]
            if uv is not None:
                uv = transform_uv(uv, material["texture"])
            elif material["texture"]:
                warn(warnings, "A textured part has no UV0; its texture cannot be shown.")
            for semantic, index in attrs.items():
                if semantic not in {"POSITION", "NORMAL", "TEXCOORD_0"}:
                    accessors.attribute(index, semantic, quantized)
                    warn(warnings, "Additional vertex attributes were omitted.")
            faces = _triangles(indices, mode)
            if np.linalg.slogdet(world[:3, :3])[0] < 0:
                faces[:, [1, 2]] = faces[:, [2, 1]]
            parts.append(Part(key, material["name"] or clean_text(mesh.get("name")) or key,
                              clean_text(node.get("name")), clean_text(mesh.get("name")), material_index,
                              _float_array(positions), None if normals is None else _float_array(normals),
                              None if uv is None else _float_array(uv), np.ascontiguousarray(faces, dtype=np.uint32)))
    require(bool(parts), "model_empty")
    return parts
