"""Sage on Codex in the 3D Model tab: the part shown in the 3D view, its CAD features, finishes on the part, its
features and their faces, Smart Dimensions on its faces, and highlighting features in the view.

The Assembly tab's tools do the work (documentation_tools.py): the part's appearance is kept as an assembly's is, with
the part's CAD features (one mesh each in its GLB) where an assembly's parts are. Here the arguments and the results
say feature, so Sage never has to translate."""
from __future__ import annotations

from .documentation_tools import AXES, DocumentationGateway, _appearance_tool_specs, _dimension_tool_specs
from .policy import PilotError

# The Assembly tool each part tool runs; the others are the part's own.
RUNS = {
    "list_appearances": "list_appearances",
    "list_part_faces": "list_part_faces",
    "set_part_appearance": "set_assembly_appearance",
    "measure_part": "measure_assembly",
    "place_part_dimensions": "place_assembly_dimensions",
    "remove_part_dimensions": "remove_assembly_dimensions",
}
HIGHLIGHT_TOOLS = ("highlight_part_features",)
PART_NAMES = ("inspect_part",) + HIGHLIGHT_TOOLS + tuple(RUNS)

# Keys renamed between the part's words and the Assembly tools' (in both directions).
_IN = {"feature": "part", "features": "parts"}
_OUT = {"part": "feature", "parts": "features", "partCount": "featureCount", "assemblyNumber": "partNumber",
        "machineBounds": "partBounds"}
# What a message from an Assembly tool says, as it is said about a part.
_WORDS = (
    ("the part names list_appearances gives", "the feature names inspect_part gives"),
    ("Use the part names", "Use the feature names"),
    ("is not a part of", "is not a feature of"),
    ("Not parts of", "Not features of"),
    ("Not a part of", "Not a feature of"),
    ("measure_assembly", "measure_part"),
    ("set_assembly_appearance", "set_part_appearance"),
    ("when the assembly is shown in the Assembly tab", "when the part is shown in the 3D Model tab"),
    ("the Assembly tab", "the 3D Model tab"),
    ("Assembly view", "3D Model view"),
)
NOTES = {
    "list_appearances": "Features, where each sits in the part and the finishes on it now. A finish on a feature goes "
                        "on that feature's faces; a face's finish wins over its feature's, a feature's over the whole "
                        "part's.",
    "list_part_faces": "The largest faces of the feature, largest first (at most 40). Give a face as feature, mesh "
                       "and face.",
    "set_part_appearance": "The 3D Model view shows the finishes after your reply.",
    "measure_part": "Values as the 3D view shows them: 2 decimals, a diameter with its sign, angles in degrees. A "
                    "face is given as feature, mesh and face from list_part_faces.",
    "place_part_dimensions": "The 3D Model view draws them beside the part after your reply; the user can drag their "
                             "text or delete them. They are reference dimensions and change nothing on the model.",
}
# The feature model's faces are smooth patches until the exporter writes CAD faces for parts.
APPROXIMATE = (" This part's model has no CAD faces: its faces are smooth patches (marked approximate), so a curved "
               "face can be split in two or merged with a neighbour.")


def _rename(value, names):
    if isinstance(value, dict):
        return {names.get(key, key): _rename(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [_rename(item, names) for item in value]
    return value


def _reword(text):
    for old, new in _WORDS:
        text = text.replace(old, new)
    return text


def _specs_by_name():
    return {spec["name"]: spec for spec in _appearance_tool_specs() + _dimension_tool_specs()}


def _feature_face_schema():
    return {"type": "object", "properties": {
        "feature": {"type": "string", "minLength": 1, "maxLength": 160},
        "mesh": {"type": "integer", "minimum": 0, "maximum": 4999},
        "face": {"type": "integer", "minimum": 0}},
        "required": ["feature", "face"], "additionalProperties": False}


def tool_specs():
    assembly = _specs_by_name()
    finish = assembly["set_assembly_appearance"]["input_schema"]["properties"]["assignments"]["items"]["properties"]
    face = _feature_face_schema()
    faces = {"type": "array", "minItems": 1, "maxItems": 2, "items": face}
    units = {"type": "string", "enum": ["mm", "in"]}
    names = {"type": "array", "minItems": 1, "maxItems": 60, "items": {"type": "string", "minLength": 1,
                                                                       "maxLength": 160}}
    return [
        {"name": "inspect_part", "description":
            "Read the part shown in the 3D Model tab: its number and name, its CAD features (the feature id the other "
            "tools take, its name, kind, colour in the feature view and the parameters the CAD export read, such as "
            "an extrusion's depth or a hole's diameter), its mass, material and size when the export has them, the "
            "finishes and dimensions on it, the faces the user selected and the features highlighted now. Call this "
            "first. No edits.",
         "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "highlight_part_features", "description":
            "Highlight features of the part in the 3D Model view right after your reply, as the app's feature "
            "highlight does: the features named (by the feature ids inspect_part gives) in their feature colour, "
            "the rest of the part faded. clear: true ends the highlight and shows the part as it was. A highlight "
            "stays until the next one, a clear, or the user's own highlight.",
         "read_only": False,
         "input_schema": {"type": "object", "properties": {"features": names, "clear": {"type": "boolean"}},
                          "additionalProperties": False}},
        dict(assembly["list_appearances"], description=
            "Read the finishes you can put on the part (paints, powder coats, metals, plastics, rubber, glass ...: "
            "id, label, colour, roughness, metalness), the part's features with where each sits (centre and size in "
            "metres, once the 3D view has shown it), and the finishes set now. With query, only finishes matching "
            "those words. No edits."),
        {"name": "list_part_faces", "description":
            "Read the faces of one feature of the part as the 3D view measured them (its largest 40, largest first): "
            "each face's mesh and face numbers, kind (plane, cylinder, cone, sphere, torus or other), area in m2, "
            "centre in metres and the side of the part it looks toward; and the faces the user selected in the view "
            "now. Without feature, only the selection. With side, kind or minAreaM2, only those faces. No edits.",
         "input_schema": {"type": "object", "properties": {
             "feature": {"type": "string", "minLength": 1, "maxLength": 160},
             **{key: value for key, value in assembly["list_part_faces"]["input_schema"]["properties"].items()
                if key != "part"}},
             "additionalProperties": False}},
        {"name": "set_part_appearance", "description":
            "Put finishes on the part now, on the server: one for the whole part, any for features and any for faces "
            "(a face's finish wins over its feature's, a feature's over the whole part's). Each assignment is a "
            "finish id from list_appearances, optionally with a colour (#rrggbb), roughness, metalness or opacity of "
            "its own, or remove: true to take a finish off. clear: true removes every finish first. Features are the "
            "ids inspect_part gives; faces are a feature with the mesh and face numbers list_part_faces gives (the "
            "user's selected faces among them). The 3D Model view shows the result after your reply.",
         "read_only": False,
         "input_schema": {"type": "object", "properties": {
             "clear": {"type": "boolean"},
             "assignments": {"type": "array", "maxItems": 20, "items": {
                 "type": "object", "properties": {
                     "target": {"type": "string", "enum": ["whole", "features", "faces"]},
                     "features": {"type": "array", "minItems": 1, "maxItems": 200,
                                  "items": {"type": "string", "minLength": 1, "maxLength": 160}},
                     "faces": {"type": "array", "minItems": 1, "maxItems": 100, "items": face},
                     **{key: finish[key] for key in ("appearanceId", "color", "roughness", "metalness", "opacity",
                                                     "remove")}},
                 "required": ["target"], "additionalProperties": False}}},
             "additionalProperties": False}},
        {"name": "measure_part", "description":
            "Measure faces of the part now, as the 3D view's Smart Dimension does, from the faces the view listed "
            "(list_part_faces: feature, mesh and face numbers) or the user selected. One face gives its own size: a "
            "cylinder or hole its diameter, a ball its diameter. Two faces give the distance between them when they "
            "are parallel, else the angle between them. Flat, cylindrical and spherical faces only. Values in mm "
            "(or in) and degrees, as the view shows them. Also lists the dimensions on the part now. No edits.",
         "input_schema": {"type": "object", "properties": {
             "measurements": {"type": "array", "maxItems": 12, "items": {
                 "type": "object", "properties": {"faces": faces}, "required": ["faces"],
                 "additionalProperties": False}},
             "units": units},
             "additionalProperties": False}},
        {"name": "place_part_dimensions", "description":
            "Put dimensions on the part now, on the server, as the user would with Smart Dimension: each names one "
            "or two faces (as measure_part takes them) and optionally a label. Each is measured first, and faces "
            "that give no dimension (a flat face alone) are refused. The 3D Model view draws them after your reply. "
            "They are reference dimensions: they change nothing on the model. units sets mm or in. Dimensions "
            "already on the part stay unless replace is true.",
         "read_only": False,
         "input_schema": {"type": "object", "properties": {
             "replace": {"type": "boolean"},
             "units": units,
             "dimensions": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
                 "type": "object", "properties": {
                     "faces": faces,
                     "label": {"type": "string", "maxLength": 80}},
                 "required": ["faces"], "additionalProperties": False}}},
             "required": ["dimensions"], "additionalProperties": False}},
        dict(assembly["remove_assembly_dimensions"], name="remove_part_dimensions", description=
            "Take dimensions off the part now, on the server: the dimIds measure_part lists, or all: true."),
    ]


class PartGateway(DocumentationGateway):
    """The tools of one 3D Model tab turn, over the part the chat request carries (bound as assemblyNumber)."""

    def __init__(self, host, principal, binding, **kwargs):
        from jsonschema import Draft202012Validator
        kwargs["workspace"] = "part"
        super().__init__(host, principal, binding, **kwargs)
        self.specs = tool_specs()
        self.validators = {spec["name"]: Draft202012Validator(spec["input_schema"]) for spec in self.specs}

    def _assembly(self):
        try:
            return self.host.assembly(self.binding["assemblyNumber"])
        except LookupError as exc:
            raise PilotError("part_model_unavailable", "The part shown has no feature model, so Sage cannot work "
                             "on it here.", 409) from exc

    def _require_assembly(self):
        if not self.binding["assemblyNumber"]:
            raise PilotError("part_required", "No part is shown. Open a part in the 3D Model tab and ask again.", 409)
        return self.binding["assemblyNumber"]

    def _read_data(self, name, arguments):
        if name == "inspect_part":
            return self._inspect_part()
        if name == "highlight_part_features":
            return self._highlight_part_features(arguments)
        if name not in RUNS:
            raise PilotError("codex_tool_denied", "This tool is not available in the 3D Model tab.", 403)
        arguments = _rename(arguments, _IN)
        for item in arguments.get("assignments") or []:
            if item.get("target") == "features":
                item["target"] = "parts"
        try:
            data = getattr(self, "_" + RUNS[name])(arguments)
        except PilotError as error:
            raise PilotError(error.code, _reword(str(error)), error.status_code) from None
        data = _rename(data, _OUT)
        for key in ("measurements", "placed"):
            for row in data.get(key) or []:
                if isinstance(row, dict) and row.get("error"):
                    row["error"] = _reword(row["error"])
        if name in NOTES:
            data["note"] = NOTES[name] + (APPROXIMATE if name == "list_part_faces" and data.get("faces")
                                          and any(row.get("approximate") for row in data["faces"]) else "")
        if name == "list_appearances" and data.get("axes"):
            data["axes"] = AXES.replace("machine", "part") if "Metres" in data["axes"] else \
                "Feature positions appear once the 3D Model view has shown this part."
        return data

    # -- the part's own reads ------------------------------------------------------------------------------------
    def _inspect_part(self):
        part_number = self._require_assembly()
        summary = self._assembly()
        document = self.host.assembly_appearance(part_number)
        reader = getattr(self.host, "part_features", None)
        features = list(reader(part_number) or [])[:120] if reader else []
        physical = getattr(self.host, "part_physical", None)
        geometry = self._geometry(part_number)
        out = {"readOnly": True, "partNumber": part_number, "name": summary.get("name") or part_number,
               "featureCount": summary.get("featureCount", len(features)), "features": features,
               "finishes": _rename(self._finishes_now(part_number), _OUT),
               "dimensionCount": len(document.get("dimensions") or []),
               "selectedFaces": _rename(self._selected_faces(part_number), _OUT),
               "highlightedNow": list((geometry.get("view") or {}).get("parts") or [])
               if (geometry.get("view") or {}).get("shown") == "group" else [],
               "note": "Highlight features: highlight_part_features. Finishes: list_appearances, then "
                       "set_part_appearance. A feature's faces and the user's selected faces: list_part_faces. "
                       "Sizes, distances and angles: measure_part; dimensions on the part: place_part_dimensions."}
        if physical:
            out["physical"] = physical(part_number)
        return out

    # -- the 3D view: features highlighted after the reply -------------------------------------------------------
    def _highlight_part_features(self, arguments):
        part_number = self._require_assembly()
        features = self.host.assembly_parts(part_number)
        names = list(dict.fromkeys(arguments.get("features") or []))
        if arguments.get("clear"):
            if names:
                raise PilotError("highlight_clear_with_features", "Give features to highlight, or clear: true, not "
                                 "both.", 422)
            self.queued = [call for call in self.queued if call["name"] not in ("highlight_features",
                                                                                "clear_feature_highlights")]
            self.queued.append({"name": "clear_feature_highlights", "args": {}})
            return {"queued": True, "runsAfterReply": True, "clears": True,
                    "note": "The 3D Model view shows the part as it was after your reply."}
        if not names:
            raise PilotError("highlight_nothing", "Give features (the ids inspect_part gives), or clear: true.", 422)
        # A feature named as the view names it, or by its name (Boss-Extrude1).
        by_name = {label.casefold(): key for key, label in features.items()}
        chosen, unknown = [], []
        for name in names:
            key = name if name in features else by_name.get(name.casefold())
            (chosen if key else unknown).append(key or name)
        if unknown:
            listed = ", ".join(map(repr, unknown[:5]))
            raise PilotError("highlight_unknown_feature", f"Not features of {part_number}: {listed}. Use the feature "
                             "ids inspect_part gives.", 422)
        self.queued = [call for call in self.queued if call["name"] not in ("highlight_features",
                                                                            "clear_feature_highlights")]
        self.queued.append({"name": "highlight_features", "args": {"feature_ids": list(dict.fromkeys(chosen))}})
        return {"queued": True, "runsAfterReply": True,
                "highlights": [{"feature": key, "name": features[key]} for key in dict.fromkeys(chosen)],
                "note": "The 3D Model view highlights them after your reply. Say what it will show, not that it is "
                        "shown."}
