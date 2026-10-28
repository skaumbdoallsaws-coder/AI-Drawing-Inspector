"""Read-only listing of the bundled Facility appearance, scene and decal libraries."""
from ai_inspector.facility_layout.appearance_library import library_summary, load_library

NAME = "list_facility_library"


def tool_specs():
    library = load_library()
    return [{"name": NAME, "description":
        "List finishes (appearances), viewport scenes or safety-sign decals that ship with InspectorPro. "
        "Use an appearanceId with set_appearance (whole objects) or set_component_materials (one part), and a "
        "sceneId with set_scene. Finishes are visual only: they never change mass, strength or engineering material. "
        "Wood and stone finishes are visual representations, not certified species. Decals are placed from the app's "
        "Appearances, Scenes and Decals panel.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["kind"], "properties": {
            "kind": {"enum": ["appearances", "scenes", "decals"]},
            "category": {"enum": sorted(library["categories"])},
            "query": {"type": "string", "maxLength": 80},
            "limit": {"type": "integer", "minimum": 1, "maximum": 60}}}}]


def list_library(arguments):
    kind = arguments["kind"]
    rows = library_summary(kind, arguments.get("query", ""), arguments.get("category"), arguments.get("limit", 40))
    result = {"kind": kind, "libraryVersion": load_library()["libraryVersion"], "count": len(rows), "items": rows}
    if kind == "appearances":
        result["adjustments"] = ("color, roughness, metalness, opacity, textureStrength (0-1); sizeMeters "
                                 "(texture tile size); rotationDegrees; offsetMeters [u, v]; mapping box|cylindrical|uv; "
                                 "grain part|length|width|height (part: along each part's own long side; otherwise the object axis the grain or brushing follows)")
    return result
