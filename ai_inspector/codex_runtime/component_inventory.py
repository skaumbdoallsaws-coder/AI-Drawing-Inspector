"""Inspect only catalog-owned local GLB material slots in renderer traversal order."""
from hashlib import sha256
import math
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ai_inspector.industrial_assets.artifacts import _parse_glb_chunks
from .policy import PilotError

MAX_BYTES = 128 * 1024 * 1024
# The 3D view gives every plain part this neutral finish instead of the model file's own
# material (static/index.html passes neutralAssetColor 0x657b8c; roughness and metalness follow
# the viewer's visual settings, 0.7 and 0.04 by default). tests/test_codex_component_inventory.py
# keeps these in step with the renderer.
VIEWER_NEUTRAL = {"color": "#657b8c", "roughness": 0.7, "metalness": 0.04}
COLOR_NOTE = ("modelColor, modelRoughness and modelMetalness are stored in the model file and are often NOT what "
              "the 3D view shows. `shown` is what the view shows and why. To leave a part as it is, leave it out "
              "of set_component_materials; never restate a color to keep a part unchanged.")


def tool_specs():
    return [{"name": "inspect_facility_components", "description":
        "Read real mesh/material keys, names, local bounds and colors from a saved placement's catalog GLB. "
        "Each part reports `shown` (the color the 3D view shows and why) beside the model file's own values "
        "(modelColor etc.), which the view usually replaces with a neutral finish. "
        "Use the returned stable p:... keys and visualSha256 for set_component_materials; never invent seat/frame roles "
        "if names are ambiguous. Keys follow the model's node names (legacyKey is the older traversal-order key). "
        "To leave a part unchanged, leave it out of set_component_materials. "
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
                slot = {"key": f"m{len(slots)}-s0", "label": label[:240],
                    "modelColor": _color(pbr.get("baseColorFactor", [1, 1, 1, 1])),
                    "modelRoughness": pbr.get("roughnessFactor", 1), "modelMetalness": pbr.get("metallicFactor", 1),
                    "localBounds": {"minimum": accessor.get("min"), "maximum": accessor.get("max")}}
                extras = material.get("extras") if isinstance(material.get("extras"), dict) else {}
                if extras.get("facilityAuthoredFinish") is True:
                    slot["authoredFinish"] = True
                if extras.get("facilityArtwork") is True and pbr.get("baseColorTexture") is not None:
                    slot["printedArtwork"] = True
                slots.append(slot)
                if len(slots) > 100000:
                    raise ValueError("Too many material slots")
        for child in node.get("children", []):
            visit(child, ancestors | {index})
    for index in scenes[scene].get("nodes", []):
        visit(index, set())
    paths = node_paths(document)
    for slot, (node_index, primitive_index) in zip(slots, _slot_origins(document)):
        slot["legacyKey"] = slot["key"]
        slot["key"] = part_key(paths[node_index], node_index, primitive_index)
    return slots


def part_key(path, node_index, primitive_index):
    key = f"p:{path}#{primitive_index}"
    # Very deep or long-named assemblies fall back to the node index so every key stays valid.
    return key if len(key) <= 512 else f"p:@{node_index}#{primitive_index}"


def _encode_name(name):
    """Percent-encode every UTF-8 byte outside [A-Za-z0-9._-]; must match the renderer's encoder."""
    return "".join(chr(byte) if (48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte in b"._-")
                   else f"%{byte:02X}" for byte in name.encode("utf-8"))


def node_paths(document):
    """Stable part path for every node reachable from the active scene (see component_materials.py)."""
    nodes, scenes = document.get("nodes", []), document.get("scenes", [])
    roots = scenes[document.get("scene", 0)].get("nodes", [])
    paths = {}

    def segments(children):
        names = [nodes[i].get("name") if isinstance(nodes[i].get("name"), str) and nodes[i].get("name") else None
                 for i in children]
        counts, seen = {}, {}
        for name in names:
            if name is not None:
                counts[name] = counts.get(name, 0) + 1
        for index, name in zip(children, names):
            if name is None:
                yield index, f"@{index}"
                continue
            ordinal = seen.get(name, 0)
            seen[name] = ordinal + 1
            yield index, _encode_name(name) + (f"~{ordinal}" if counts[name] > 1 else "")

    def visit(children, prefix):
        for index, segment in segments(children):
            if index in paths:
                continue
            paths[index] = segment if not prefix else prefix + "/" + segment
            visit(nodes[index].get("children", []), paths[index])

    visit(roots, "")
    return paths


def _slot_origins(document):
    """(node, primitive) for each slot, in the same order material_slots() emits them."""
    nodes, meshes = document.get("nodes", []), document.get("meshes", [])
    scenes = document.get("scenes", [])
    origins, visited = [], set()

    def visit(index):
        if index in visited:
            return
        visited.add(index)
        node = nodes[index]
        if "mesh" in node:
            for primitive_index, primitive in enumerate(meshes[node["mesh"]]["primitives"]):
                if primitive.get("mode", 4) in (4, 5, 6):
                    origins.append((index, primitive_index))
        for child in node.get("children", []):
            visit(child)
    for index in scenes[document.get("scene", 0)].get("nodes", []):
        visit(index)
    return origins


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
    config = placement.get("componentMaterials") or {}
    same = config.get("representation") == representation
    # As the renderer does: stable p: keys apply to either visual, older m... keys only to their own.
    overrides = {item["key"]: item for item in config.get("overrides", []) if same or not re.match(r"m\d", item["key"])}
    for slot in slots:
        saved_override = overrides.get(slot["key"]) or (overrides.get(slot.get("legacyKey")) if same else None)
        if saved_override:
            slot["savedOverride"] = saved_override
        slot["shown"] = shown_finish(slot, placement, saved["layout"])
    query = arguments.get("query", "").casefold()
    matches = [slot for slot in slots if query in (slot["label"]+" "+slot["key"]).casefold()]
    offset, size = arguments.get("offset", 0), arguments.get("pageSize", 20)
    end = min(len(matches), offset+size)
    return {**inventory, "colorNote": COLOR_NOTE,
            "slots": matches[offset:end], "total": len(matches), "nextOffset": end if end < len(matches) else None,
            "readOnly": True}


def _finish(value, layout, kind):
    """A library or custom finish with its adjustments, resolved as static/facility_layout_library.js does."""
    from ai_inspector.facility_layout.appearance_library import custom_appearances, load_library
    custom = custom_appearances(layout).get(value["appearanceId"])
    base = load_library()["appearances"].get(custom["baseAppearanceId"] if custom else value["appearanceId"])
    if base is None:
        return {"source": f"{kind}: {value['appearanceId']} (not in the library)"}
    sources = (value, custom or {}, base)  # the nearest adjustment wins
    return {**{key: next(row[key] for row in sources if row.get(key) is not None) for key in ("color", "roughness", "metalness")},
            "source": f"{kind}: {(custom or base)['label']}"}


def shown_finish(slot, placement, layout):
    """What the 3D view shows for one part, in the renderer's order of precedence."""
    override = slot.get("savedOverride")
    if override and override.get("appearanceId"):
        return _finish(override, layout, "part override")
    if override:
        return {**{key: override[key] for key in ("color", "roughness", "metalness")}, "source": "part override"}
    if slot.get("printedArtwork"):
        return {"source": "printed artwork (an image); object finishes and colors leave it as it is"}
    appearance = placement.get("appearance") or {}
    if appearance.get("appearanceId"):
        return _finish(appearance, layout, "object finish")
    if slot.get("authoredFinish"):
        return {"color": slot["modelColor"], "roughness": slot["modelRoughness"], "metalness": slot["modelMetalness"],
                "source": "the model's own finish, which the view keeps"}
    if appearance.get("color"):
        return {**VIEWER_NEUTRAL, "color": appearance["color"], "source": "object color"}
    return {**VIEWER_NEUTRAL, "source": "the view's neutral finish for plain parts; the model file's color is not shown"}
