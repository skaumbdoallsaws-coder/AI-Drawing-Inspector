"""Stable keys of flat grouped builder output, without numpy or application imports."""
from .include_contract import encode_name


def output_keys(document):
    result, names = set(), set()
    nodes, meshes = document.get("nodes", []), document.get("meshes", [])
    if not 1 <= len(nodes) <= 400 or len(nodes) != len(meshes):
        raise ValueError("Invalid grouped builder scene")
    if document.get("scene") != 0 or document.get("scenes") != [{"nodes": list(range(len(nodes)))}]:
        raise ValueError("Invalid grouped builder roots")
    for i, node in enumerate(nodes):
        if set(node) != {"name", "mesh"} or node["mesh"] != i or not isinstance(node["name"], str) or node["name"] in names:
            raise ValueError("Invalid builder node")
        names.add(node["name"])
        for j, _ in enumerate(meshes[i]["primitives"]):
            key = f"p:{encode_name(node['name'])}#{j}"
            result.add(key if len(key) <= 512 else f"p:@{i}#{j}")
    if not 1 <= len(result) <= 400:
        raise ValueError("Invalid builder primitive count")
    return result
