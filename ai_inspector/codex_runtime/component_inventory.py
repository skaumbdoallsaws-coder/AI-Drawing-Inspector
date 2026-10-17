"""Inspect only catalog-owned local GLB material slots in renderer traversal order."""
from hashlib import sha256
import math
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ai_inspector.industrial_assets.artifacts import _parse_glb_chunks
from .policy import PilotError

MAX_BYTES = 128 * 1024 * 1024


def tool_specs():
    return [{"name": "inspect_facility_components", "description":
        "Read real mesh/material keys, names, colors and local bounds from a saved placement's catalog GLB. "
        "Use returned mN-sN keys and visualSha256 for set_component_materials; never invent seat/frame roles if names are ambiguous. "
        "Keys follow the renderer's active-scene mesh traversal and are representation-specific. "
        "Does not inspect arbitrary paths or change the model.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["placementId"],
            "properties": {"placementId": {"type": "string", "minLength": 1, "maxLength": 128},
                "representation": {"enum": ["overview", "detail"]},
                "query": {"type": "string", "maxLength": 120},
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
                "pageSize": {"type": "integer", "minimum": 1, "maximum": 50}}}}]


def catalog_visual_path(value, root):
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise PilotError("codex_visual_unavailable", "This catalog visual is not a supported local GLB.", 422)
    relative = Path(unquote(parsed.path).lstrip("/"))
    if relative.is_absolute() or ".." in relative.parts or "\\" in parsed.path or ":" in str(relative):
        raise PilotError("codex_visual_unavailable", "This catalog visual is not a supported local GLB.", 422)
    root = Path(root).resolve()
    allowed = (root / "generated").resolve()
    path = root / relative
    if not path.resolve().is_relative_to(allowed) or path.suffix.lower() != ".glb":
        raise PilotError("codex_visual_unavailable", "Material inspection supports catalog GLBs in the application's generated asset store.", 422)
    current = path
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise PilotError("codex_visual_unavailable", "Linked asset paths are not supported for material inspection.", 422)
        current = current.parent
    return path


def _color(rgb):
    def srgb(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Invalid material color")
        return round(255 * (12.92*value if value <= .0031308 else 1.055*value**(1/2.4)-.055))
    if not isinstance(rgb, list) or len(rgb) != 4:
        raise ValueError("Invalid material color")
    return "#" + "".join(f"{srgb(value):02x}" for value in rgb[:3])


def material_slots(document):
    if any(document.get(key) for key in ("skins", "animations", "extensionsRequired")):
        raise PilotError("codex_component_format_unsupported", "This visual needs renderer-side component inspection.", 422)
    nodes, meshes = document.get("nodes", []), document.get("meshes", [])
    materials, accessors = document.get("materials", []), document.get("accessors", [])
    scenes = document.get("scenes", [])
    scene = document.get("scene", 0)
    if type(scene) is not int or not 0 <= scene < len(scenes):
        raise ValueError("Missing active scene")
    slots, visited = [], set()
    def indexed(rows, index):
        if not isinstance(rows, list) or type(index) is not int or not 0 <= index < len(rows):
            raise ValueError("Invalid GLB index")
        return rows[index]
    def visit(index, ancestors):
        if type(index) is not int or not 0 <= index < len(nodes) or index in ancestors or index in visited or len(ancestors) > 128:
            raise ValueError("Invalid scene hierarchy")
        visited.add(index)
        node = indexed(nodes, index)
        if "mesh" in node:
            mesh = indexed(meshes, node["mesh"])
            for primitive in mesh["primitives"]:
                if type(primitive.get("mode", 4)) is not int or not 0 <= primitive.get("mode", 4) <= 6:
                    raise ValueError("Invalid primitive mode")
                if primitive.get("mode", 4) not in (4, 5, 6):
                    continue  # THREE.Points/Line objects do not receive material slot keys.
                material = indexed(materials, primitive["material"]) if "material" in primitive else {}
                pbr = material.get("pbrMetallicRoughness", {})
                accessor = indexed(accessors, primitive["attributes"]["POSITION"])
                label = str(node.get("name") or mesh.get("name") or "Mesh " + str(len(slots)+1))
                label += " / " + str(material.get("name") or "Material 1")
                slots.append({"key": f"m{len(slots)}-s0", "label": label[:240],
                    "color": _color(pbr.get("baseColorFactor", [1, 1, 1, 1])),
                    "roughness": pbr.get("roughnessFactor", 1), "metalness": pbr.get("metallicFactor", 1),
                    "localBounds": {"minimum": accessor.get("min"), "maximum": accessor.get("max")}})
                if len(slots) > 100000:
                    raise ValueError("Too many material slots")
        for child in node.get("children", []):
            visit(child, ancestors | {index})
    for index in scenes[scene].get("nodes", []):
        visit(index, set())
    return slots


def resolve_component_inventory(runtime, principal, reference, placement_id, representation, *, project_root=None):
    """Unpaged authority for one exact saved occurrence; no model-selected path."""
    from .facility_tools import read_bound_layout
    saved = read_bound_layout(runtime, principal, reference)
    placement = next((p for p in saved["layout"]["placements"] if p["placementId"] == placement_id), None)
    if placement is None:
        raise PilotError("codex_placement_unavailable", "The placement does not exist in this saved layout.", 404)
    entries = runtime.asset_catalog_provider(principal, reference["siteId"])
    entry = next((a for a in entries if a.get("assetId") == placement["assetId"]
                  and a.get("assetDefinitionRevision") == placement["assetDefinitionRevision"]), None)
    if representation not in ("overview", "detail"):
        raise PilotError("codex_visual_unavailable", "Choose an overview or detail visual.", 422)
    visual = (entry or {}).get(representation) or (entry or {}).get("representations", {}).get(representation)
    if not isinstance(visual, dict) or not isinstance(visual.get("path"), str):
        raise PilotError("codex_visual_unavailable", "This exact asset revision has no supported local visual for component inspection.", 404)
    try:
        path = catalog_visual_path(visual["path"], project_root or Path(__file__).resolve().parents[2])
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES+1)
        if len(data) > MAX_BYTES:
            raise ValueError("Visual exceeds the component inspection budget")
        document, _, _ = _parse_glb_chunks(data)
        slots = material_slots(document)
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError) as exc:
        raise PilotError("codex_component_inspection_failed", "This visual could not be inspected safely; use the manual Component Materials tool.", 422) from exc
    read_bound_layout(runtime, principal, reference)
    return {"identity": dict(reference), "placementId": placement["placementId"], "assetId": placement["assetId"],
            "assetDefinitionRevision": placement["assetDefinitionRevision"], "representation": representation,
            "visualSha256": sha256(data).hexdigest(), "componentRolesVerified": False, "slots": slots,
            "readOnly": True}


def inspect_components(runtime, principal, reference, arguments):
    from .facility_tools import read_bound_layout
    saved = read_bound_layout(runtime, principal, reference)
    placement = next((p for p in saved["layout"]["placements"] if p["placementId"] == arguments["placementId"]), None)
    if placement is None:
        raise PilotError("codex_placement_unavailable", "The placement does not exist in this saved layout.", 404)
    representation = arguments.get("representation", placement.get("componentMaterials", {}).get("representation", "overview"))
    resolver = runtime.service.component_inventory_resolver
    if resolver is None:
        raise PilotError("codex_visual_unavailable", "Component inspection is not configured for this host.", 422)
    inventory = resolver(principal, reference, placement["placementId"], representation)
    slots = inventory["slots"]
    overrides = {item["key"]: item for item in placement.get("componentMaterials", {}).get("overrides", [])
                 if placement["componentMaterials"]["representation"] == representation}
    for slot in slots:
        if slot["key"] in overrides:
            slot["savedOverride"] = overrides[slot["key"]]
    query = arguments.get("query", "").casefold()
    matches = [slot for slot in slots if query in (slot["label"]+" "+slot["key"]).casefold()]
    offset, size = arguments.get("offset", 0), arguments.get("pageSize", 20)
    end = min(len(matches), offset+size)
    return {**inventory,
            "slots": matches[offset:end], "total": len(matches), "nextOffset": end if end < len(matches) else None,
            "readOnly": True}
