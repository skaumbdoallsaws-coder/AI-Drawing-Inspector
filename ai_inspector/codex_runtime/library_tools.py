"""Read-only listing of the bundled Facility appearance, scene and decal libraries."""
from ai_inspector.facility_layout.appearance_library import library_summary, load_library

NAME = "list_facility_library"


def tool_specs():
    library = load_library()
    return [{"name": NAME, "description":
        "List finishes (appearances), viewport scenes or safety-sign decals that ship with InspectorPro. "
        "Use an appearanceId with set_appearance (whole objects) or set_component_materials (one part), and a "
        "sceneId with set_scene. Finishes are visual only: they never change mass, strength or engineering material. "
        "Wood and stone finishes are visual representations, not certified species. Lights finishes (category "
        "lights: LED and warm white, exit green, beacon, alarm, signal and stack-light colors) glow like a "
        "switched-on lamp; their emission is the glow color, and emission.pattern marks the beacon that turns, the "
        "alarm that strobes and the signal that blinks (the others are steady). Any of them can blink, strobe or turn "
        "instead: add pattern and periodSeconds to that use of the finish. For accent lighting that slowly changes "
        "color, add pattern cycle with periodSeconds (2-60 s per loop) and cycleColors (2-8 colors; default violet, "
        "blue, cyan, magenta). Put one on a lamp's lens or a sign face with "
        "set_component_materials, or on a whole small fitting with set_appearance; it lights no other surface. "
        "The outdoor ones (Pole light LED, Wall light LED, Dock light LED) have emission.beamAngleDegrees: in the "
        "evening scene a lamp with one also shows a soft beam down to the ground and a pool of light where it lands. "
        "Accent spot LED (emission.accent) is for an adjustable spot aimed at a wall, a picture or an object: in the "
        "evening scene it lights what its lens faces, as placed, within about 8 m (no beam or pool is drawn). "
        "Bollard light warm and Lantern warm (emission.low) are low outdoor lights (a bollard or path light; a "
        "lantern or a festoon string hung from a pergola or set on a table): in the evening scene each throws a pool "
        "of light on the ground below it from any height, with no beam; a string's bulbs share one light's output. "
        "Garden uplight warm (emission.uplight) is an accent spot "
        "whose lens faces up: at the foot of a palm, a plant or a wall it lights it from below within about 8 m. "
        "The pole light, the wall light and the rotating beacons come lit: their model gives the lens its Lights "
        "finish (Pole light LED, Wall light LED, Beacon amber), with no step from you, although their catalog "
        "descriptions still say to give it one. A stack light comes with its green lamp on (Stack light green, "
        "steady); a finish on its amber or red lamp turns the green off. To give a new fitting a lens finish of its "
        "own (Dock light LED over a dock door, a strobing Alarm red beacon), read its parts with "
        "inspect_facility_components {assetId}, give its place_asset a placementId and put set_component_materials "
        "for that placementId after it in the same preview; for a saved fitting, inspect it by placementId. "
        "Decals are placed from the app's Appearances, Scenes and Decals panel.",
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
        result["adjustments"] = ("color (on a Lights finish: the light's color, lit and unlit), pattern "
                                 "steady|blink|strobe|rotate with periodSeconds 0.5-10, or cycle with periodSeconds "
                                 "2-60 and cycleColors (2-8 '#rrggbb', eased through one loop per period; the default "
                                 "is violet, blue, cyan, magenta) (Lights finishes only; none for steady), roughness, "
                                 "metalness, opacity, "
                                 "textureStrength (0-1); sizeMeters "
                                 "(texture tile size); rotationDegrees; offsetMeters [u, v]; mapping box|cylindrical|uv; "
                                 "grain part|length|width|height (part: along each part's own long side; otherwise the object axis the grain or brushing follows)")
    return result
