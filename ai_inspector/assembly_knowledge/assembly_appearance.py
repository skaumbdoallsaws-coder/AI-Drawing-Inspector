"""An assembly's appearance: finishes from the appearance library on the whole machine or on its parts
(docs/assembly-appearance-plan.md), a lighting scene, and safety signs or imported logos on its parts
(docs/assembly-signs-scenes-plan.md). One document per assembly, shared by the Assembly tab and every document, so
the machine looks the same wherever it is shown or captured.

A finish is a library appearance with optional colour, roughness, metalness and opacity overrides. A part's finish
wins over the whole machine's. A sign is a library sign (ISO 7010) or an imported image on one part: either on a
side of that part (front, back, left, right, top, bottom in the viewer's axes, at a spot across and up that side),
which the viewer finds on the part's surface, or at an exact point on one of the part's meshes. The revision changes
with any finish, the scene or any sign, so a capture taken before is stale.

Dimensions (docs/assembly-smart-dimension-plan.md) are kept here too, with the units they are shown in, but outside the
revision: the Specification Sheet picture never shows them. They have a revision of their own.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from ai_inspector.facility_layout.appearance_library import load_library, normalize_overrides

ASSEMBLY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_PARTS = 400
# What the Assembly viewer draws of a finish (it has no texture coordinates; a textured finish shows its colour).
OVERRIDES = ("color", "roughness", "metalness", "opacity")
SIDES = ("front", "back", "left", "right", "top", "bottom")
MAX_SIGNS = 60
MAX_IMAGES = 40
SIGN_ID = re.compile(r"sg-[a-z0-9]{6,16}")
IMAGE_ID = re.compile(r"[0-9a-f]{64}")
DEFAULT_SIGN_WIDTH = 0.3
# Faces of parts (docs/assembly-face-selection-plan.md): finishes on faces, the faces the user selected, and the
# viewer's list of each part's largest faces.
MAX_FACES = 400
MAX_SELECTION = 50
MAX_REPORT_FACES = 40
FACE_KINDS = ("plane", "cylinder", "cone", "sphere", "torus", "other")
FACE_STATUSES = ("drawn", "face_missing", "part_missing")
# Smart Dimension (docs/assembly-smart-dimension-plan.md).
MAX_DIMENSIONS = 100
DIMENSION_ID = re.compile(r"dm-[a-z0-9]{6,16}")
DIMENSION_ENTITIES = ("face", "edge", "vertex")
DIMENSION_KINDS = ("length", "distance", "diameter", "radius", "angle")
DIMENSION_STATUSES = ("drawn", "dimension_missing", "part_missing")
DIMENSION_UNITS = ("mm", "in")
SIGN_STATUSES = ("placed", "no_surface", "no_fit", "part_missing", "image_missing", "face_missing")
_KEEP = object()


class AssemblyAppearanceError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: Any, label: str, low: float, high: float, places: int = 4) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise AssemblyAppearanceError(f"{label} must be a number from {low:g} to {high:g}")
    return round(float(value), places)


def _vector(value: Any, label: str) -> list:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise AssemblyAppearanceError(f"{label} must be three numbers")
    return [_number(item, label, -1e4, 1e4, 6) for item in value]


def finish(value: Any, label: str = "finish") -> Dict[str, Any]:
    """A library appearance and the overrides the viewer draws, validated."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be an object with an appearanceId")
    appearance_id = value.get("appearanceId")
    if appearance_id not in load_library()["appearances"]:
        raise AssemblyAppearanceError(f"{label}: {appearance_id!r} is not in the appearance library")
    if load_library()["appearances"][appearance_id].get("emission"):
        raise AssemblyAppearanceError(f"{label}: {appearance_id!r} is a Lights finish, which glows only in the "
                                      "Facility 3D view; pick a paint, plastic or metal for an assembly")
    try:
        overrides = normalize_overrides({key: value[key] for key in OVERRIDES if value.get(key) is not None})
    except ValueError as error:
        raise AssemblyAppearanceError(f"{label}: {error}") from None
    return {"appearanceId": appearance_id, **overrides}


def scene(value: Any) -> Optional[Dict[str, str]]:
    """A library scene by id; Classic (the viewer's own light) or nothing is no scene."""
    scene_id = value.get("sceneId") if isinstance(value, Mapping) else value
    if scene_id in (None, "", "classic"):
        return None
    if scene_id not in load_library()["scenes"]:
        raise AssemblyAppearanceError(f"{scene_id!r} is not a scene in the library")
    return {"sceneId": str(scene_id)}


def new_sign_id() -> str:
    return "sg-" + secrets.token_hex(5)


def _whole(value: Any, label: str, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < high:
        raise AssemblyAppearanceError(f"{label} must be a whole number from 0 to {high - 1}")
    return value


def fingerprint(value: Any, label: str = "fingerprint") -> Dict[str, Any]:
    """A face's area (m2), centre and average direction in its mesh's own coordinates, as the viewer measured
    them: what finds the face again when a new export numbers the faces differently."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be {{area, center, normal}} as the viewer measured the face")
    normal = _vector(value.get("normal"), f"{label} normal")
    if any(abs(item) > 1.01 for item in normal):
        raise AssemblyAppearanceError(f"{label} normal must be a direction (each part at most 1)")
    return {"area": _number(value.get("area"), f"{label} area", 0, 1e6, 12),
            "center": _vector(value.get("center"), f"{label} center"), "normal": [round(item, 4) for item in normal]}


def face_reference(value: Any, label: str = "face") -> Dict[str, Any]:
    """Which face of a part: the copy of the part it was picked on (mesh, its place in the part's mesh list), the
    face's number there and its fingerprint. approximate: the model has no CAD faces, the face is a smooth patch."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be {{mesh, face, fingerprint}}")
    result = {"mesh": _whole(value.get("mesh", 0), f"{label}: mesh", 5000),
              "face": _whole(value.get("face"), f"{label}: face", 10_000_000),
              "fingerprint": fingerprint(value.get("fingerprint"), f"{label}: fingerprint")}
    if value.get("approximate"):
        result["approximate"] = True
    return result


def new_dimension_id() -> str:
    return "dm-" + secrets.token_hex(5)


def _face_part(value: Any, label: str) -> Dict[str, Any]:
    """A face of a dimension's entity: its number and fingerprint (approximate on a model without CAD faces)."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be {{face, fingerprint}}")
    result = {"face": _whole(value.get("face"), f"{label}: face", 10_000_000),
              "fingerprint": fingerprint(value.get("fingerprint"), f"{label}: fingerprint")}
    if value.get("approximate"):
        result["approximate"] = True
    return result


def dimension_entity(value: Any, *, parts: Iterable[str], label: str = "entity") -> Dict[str, Any]:
    """What a dimension measures from: a face (number + fingerprint), an edge (its two faces, the second null
    where it borders nothing) or a vertex (its point), on one copy of a part, with the spot it was picked at in that
    mesh's coordinates."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be an object")
    kind = value.get("type")
    if kind not in DIMENSION_ENTITIES:
        raise AssemblyAppearanceError(f"{label}: type must be one of {', '.join(DIMENSION_ENTITIES)}")
    part = str(value.get("part") or "")
    if part not in set(parts):
        raise AssemblyAppearanceError(f"{label}: {part!r} is not a part of this assembly")
    row: Dict[str, Any] = {"type": kind, "part": part, "mesh": _whole(value.get("mesh", 0), f"{label}: mesh", 5000)}
    if value.get("at") is not None:
        row["at"] = _vector(value["at"], f"{label}: at")
    if kind == "face":
        row.update(_face_part(value, label))
    elif kind == "edge":
        faces = value.get("faces")
        if not isinstance(faces, (list, tuple)) or len(faces) != 2 or faces[0] is None:
            raise AssemblyAppearanceError(f"{label}: an edge needs faces [face, face or null]")
        row["faces"] = [_face_part(faces[0], f"{label} faces[0]"),
                        None if faces[1] is None else _face_part(faces[1], f"{label} faces[1]")]
    elif "at" not in row:
        raise AssemblyAppearanceError(f"{label}: a vertex needs its point (at)")
    return row


def dimension(value: Any, *, parts: Iterable[str], label: str = "dimension") -> Dict[str, Any]:
    """One dimension: one or two entities, where its text sits (in the first entity's mesh coordinates; null puts
    it beside the dimension) and an optional label."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be an object")
    dimension_id = str(value.get("dimId") or new_dimension_id())
    if not DIMENSION_ID.fullmatch(dimension_id):
        raise AssemblyAppearanceError(f"{label}: dimId must look like dm-1a2b3c4d5e")
    entities = value.get("entities")
    if not isinstance(entities, (list, tuple)) or not 1 <= len(entities) <= 2:
        raise AssemblyAppearanceError(f"{label}: entities must list one or two entities")
    row: Dict[str, Any] = {"dimId": dimension_id,
                           "entities": [dimension_entity(item, parts=parts, label=f"{label} entities[{index}]")
                                        for index, item in enumerate(entities)],
                           "text": None if value.get("text") is None else _vector(value["text"], f"{label}: text")}
    if isinstance(value.get("label"), str) and value["label"].strip():
        row["label"] = value["label"].strip()[:80]
    return row


def dimensions_revision(document: Mapping[str, Any]) -> str:
    """Changes with any dimension or the units; empty while there is neither."""
    rows, units = document.get("dimensions") or [], document.get("dimensionUnits") or "mm"
    if not rows and units == "mm":
        return ""
    canonical = json.dumps({"dimensions": rows, "units": units}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _exact_surface(value: Any, label: str) -> Optional[Dict[str, Any]]:
    """The exact surface the viewer measured a face on, in the view's axes: a plane (point, normal), a cylinder
    (point on its axis, axis, radius) or a sphere (center, radius). None for anything else."""
    if not isinstance(value, Mapping):
        return None
    kind = value.get("kind")

    def direction(name: str) -> list:
        vector = _vector(value.get(name), f"{label}: {name}")
        length = math.sqrt(sum(item * item for item in vector))
        if not 0.99 <= length <= 1.01:
            raise AssemblyAppearanceError(f"{label}: {name} must be a direction")
        return vector

    if kind == "plane":
        return {"kind": "plane", "point": _vector(value.get("point"), f"{label}: point"), "normal": direction("normal")}
    if kind == "cylinder":
        return {"kind": "cylinder", "point": _vector(value.get("point"), f"{label}: point"), "axis": direction("axis"),
                "radius": _number(value.get("radius"), f"{label}: radius", 0, 1e4, 7)}
    if kind == "sphere":
        return {"kind": "sphere", "center": _vector(value.get("center"), f"{label}: center"),
                "radius": _number(value.get("radius"), f"{label}: radius", 0, 1e4, 7)}
    return None


def face_key(row: Mapping[str, Any]) -> str:
    """The key the viewer reports a face finish under: part#mesh:face."""
    return f"{row['part']}#{row.get('mesh', 0)}:{row['face']}"


def face_finish(value: Any, *, parts: Iterable[str], label: str = "face") -> Dict[str, Any]:
    """A finish on one face of a part (on every copy of the part), validated."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be {{part, mesh, face, fingerprint, finish}}")
    part = str(value.get("part") or "")
    if part not in set(parts):
        raise AssemblyAppearanceError(f"{label}: {part!r} is not a part of this assembly")
    return {"part": part, **face_reference(value, label), "finish": finish(value.get("finish"), f"{label} finish")}


def sign(value: Any, *, parts: Iterable[str], images: Mapping[str, Any], label: str = "sign") -> Dict[str, Any]:
    """One sign on one part, validated. A library sign (decalId) or an imported image (imageId)."""
    if not isinstance(value, Mapping):
        raise AssemblyAppearanceError(f"{label} must be an object")
    decal_id, image_id = value.get("decalId"), value.get("imageId")
    if bool(decal_id) == bool(image_id):
        raise AssemblyAppearanceError(f"{label} needs a decalId (a library sign) or an imageId (an imported image)")
    if decal_id:
        row = load_library()["decals"].get(decal_id)
        if not row:
            raise AssemblyAppearanceError(f"{label}: {decal_id!r} is not a sign in the library")
        name, default_width = row["label"], float(row.get("widthMeters") or DEFAULT_SIGN_WIDTH)
    else:
        if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id) or image_id not in images:
            raise AssemblyAppearanceError(f"{label}: {image_id!r} is not an image imported for this assembly")
        name, default_width = images[image_id].get("label") or "Image", DEFAULT_SIGN_WIDTH
    part = str(value.get("part") or "")
    if part not in set(parts):
        raise AssemblyAppearanceError(f"{label}: {part!r} is not a part of this assembly")
    side = value.get("side", "front")
    if side not in SIDES:
        raise AssemblyAppearanceError(f"{label}: side must be one of {', '.join(SIDES)}")
    sign_id = value.get("signId") or new_sign_id()
    if not isinstance(sign_id, str) or not SIGN_ID.fullmatch(sign_id):
        raise AssemblyAppearanceError(f"{label}: signId must look like sg-1a2b3c4d5e")
    result = {
        "signId": sign_id,
        **({"decalId": decal_id} if decal_id else {"imageId": image_id}),
        "label": str(value.get("label") or name).strip()[:80] or name,
        "part": part,
        "side": side,
        "across": _number(value.get("across", 0.5), f"{label}: across", 0, 1),
        "up": _number(value.get("up", 0.5), f"{label}: up", 0, 1),
        "widthMeters": _number(value.get("widthMeters", default_width), f"{label}: widthMeters", 0.02, 3),
        "rotationDegrees": _number(value.get("rotationDegrees", 0), f"{label}: rotationDegrees", -180, 180, 2),
    }
    anchor = value.get("anchor")
    if anchor is not None:
        if not isinstance(anchor, Mapping) or set(anchor) - {"mesh", "point", "normal"}:
            raise AssemblyAppearanceError(f"{label}: anchor is {{mesh, point, normal}} on one of the part's meshes")
        mesh = anchor.get("mesh", 0)
        if isinstance(mesh, bool) or not isinstance(mesh, int) or not 0 <= mesh < 5000:
            raise AssemblyAppearanceError(f"{label}: anchor mesh must be the index of one of the part's meshes")
        normal = _vector(anchor.get("normal"), f"{label}: anchor normal")
        if sum(item * item for item in normal) < 1e-8:
            raise AssemblyAppearanceError(f"{label}: anchor normal must not be zero")
        result["anchor"] = {"mesh": mesh, "point": _vector(anchor.get("point"), f"{label}: anchor point"),
                            "normal": normal}
    if value.get("face") is not None:
        # On one face of the part: the viewer keeps the sign inside it.
        result["face"] = face_reference(value["face"], f"{label}: face")
    return result


def resolved(value: Mapping[str, Any]) -> Dict[str, Any]:
    """What the viewer draws: the library row with the overrides. Glass (transmission) is drawn as transparency."""
    row = load_library()["appearances"][value["appearanceId"]]
    drawn = {"appearanceId": row["appearanceId"], "label": row["label"], "category": row["category"],
             "textured": bool(row.get("texture"))}
    for key in OVERRIDES:
        drawn[key] = value.get(key, row.get(key))
    transmission = float(row.get("transmission") or 0)
    if transmission and value.get("opacity") is None:
        drawn["opacity"] = round(min(1.0, (1 - 0.75 * transmission) + 0.3 * float(drawn["roughness"] or 0)), 3)
    return drawn


def image_url(image_id: str) -> str:
    return f"/api/assembly-appearance-images/{image_id}.png"


def resolved_scene(value: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The scene's light for the viewer: the library preset, with its lighting file when it has one."""
    if not value:
        return None
    library = load_library()
    row = library["scenes"].get(value.get("sceneId"))
    if not row:
        return None
    environment = library["environments"].get(row.get("environment") or "")
    drawn = {key: row.get(key) for key in ("sceneId", "label", "description", "environment", "environmentIntensity",
                                           "background", "ambient", "directional", "exposure")}
    drawn["environmentUrl"] = f"/static/facility_library/{environment['file']}" if environment else None
    return drawn


def resolved_sign(value: Mapping[str, Any], images: Mapping[str, Any]) -> Dict[str, Any]:
    """A sign with its picture's address and proportions (width over height) for the viewer."""
    drawn = dict(value)
    if value.get("decalId"):
        row = load_library()["decals"].get(value["decalId"]) or {}
        drawn.update({"code": row.get("code"), "group": row.get("group"), "aspect": row.get("aspect") or 1,
                      "url": f"/static/facility_library/{row['file']}" if row.get("file") else None})
    else:
        image = images.get(value.get("imageId")) or {}
        drawn.update({"code": None, "group": "image", "aspect": image.get("aspect") or 1,
                      "url": image_url(value["imageId"])})
    return drawn


def empty(assembly_number: str) -> Dict[str, Any]:
    return {"version": 1, "assemblyNumber": assembly_number, "whole": None, "parts": {}, "faces": [], "scene": None,
            "signs": [], "images": {}, "dimensions": [], "dimensionUnits": "mm"}


def revision(document: Mapping[str, Any]) -> str:
    """Empty when nothing is assigned, so an assembly without an appearance keeps its captures. An assembly with
    finishes only keeps the revision it had before scenes, signs and face finishes existed."""
    whole, parts = document.get("whole"), document.get("parts") or {}
    scene_value, signs = document.get("scene"), document.get("signs") or []
    faces = document.get("faces") or []
    if not whole and not parts and not scene_value and not signs and not faces:
        return ""
    payload: Dict[str, Any] = {"whole": whole, "parts": parts}
    if scene_value:
        payload["scene"] = scene_value
    if signs:
        payload["signs"] = signs
    if faces:
        payload["faces"] = faces
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def view(document: Mapping[str, Any]) -> Dict[str, Any]:
    """The document with each finish, the scene and each sign resolved for the viewer, and its revision."""
    whole = document.get("whole")
    images = document.get("images") or {}
    faces = document.get("faces") or []
    return {"assemblyNumber": document.get("assemblyNumber"), "revision": revision(document),
            "whole": resolved(whole) if whole else None,
            "parts": {key: resolved(value) for key, value in (document.get("parts") or {}).items()},
            "faces": [{**row, "finish": resolved(row["finish"])} for row in faces],
            "assigned": {"whole": whole, "parts": document.get("parts") or {}, "faces": faces},
            "scene": resolved_scene(document.get("scene")),
            "signs": [resolved_sign(row, images) for row in document.get("signs") or []],
            "images": [{"imageId": key, **value, "url": image_url(key)} for key, value in images.items()],
            "dimensions": list(document.get("dimensions") or []),
            "dimensionUnits": document.get("dimensionUnits") or "mm",
            "dimensionsRevision": dimensions_revision(document),
            "updatedAt": document.get("updatedAt")}


class AssemblyAppearanceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, assembly_number: str) -> Path:
        if not ASSEMBLY_ID.fullmatch(str(assembly_number or "")):
            raise AssemblyAppearanceError("not a valid assembly number")
        return self.root / f"{assembly_number}.json"

    @staticmethod
    def _atomic(path: Path, payload: bytes, prefix: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=prefix)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read(self, assembly_number: str) -> Dict[str, Any]:
        path = self._path(assembly_number)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return empty(assembly_number)
        if not isinstance(data, Mapping) or data.get("version") != 1:
            return empty(assembly_number)
        return {**empty(assembly_number), "whole": data.get("whole") or None, "parts": dict(data.get("parts") or {}),
                "faces": list(data.get("faces") or []),
                "scene": data.get("scene") or None, "signs": list(data.get("signs") or []),
                "images": dict(data.get("images") or {}),
                "dimensions": list(data.get("dimensions") or []),
                "dimensionUnits": data.get("dimensionUnits") if data.get("dimensionUnits") in DIMENSION_UNITS else "mm",
                "updatedAt": data.get("updatedAt"), "by": data.get("by")}

    def _save(self, document: Dict[str, Any]) -> Dict[str, Any]:
        path = self._path(document["assemblyNumber"])
        if not any(document.get(key) for key in ("whole", "parts", "faces", "scene", "signs", "images", "dimensions")) \
                and document.get("dimensionUnits", "mm") == "mm":
            path.unlink(missing_ok=True)
            return empty(document["assemblyNumber"])
        self._atomic(path, json.dumps(document, indent=1, sort_keys=True).encode("utf-8"), ".appearance-")
        return document

    def write(self, assembly_number: str, whole: Any, parts: Mapping[str, Any], *, part_numbers: Iterable[str],
              by: str, scene_value: Any = _KEEP, signs: Any = _KEEP, faces: Any = _KEEP) -> Dict[str, Any]:
        """Replace the finishes (and the face finishes, the scene or the signs when given). Part keys must be the
        assembly's part numbers. Imported images stay."""
        known = set(part_numbers)
        if not isinstance(parts, Mapping):
            raise AssemblyAppearanceError("parts must map part numbers to finishes")
        if len(parts) > MAX_PARTS:
            raise AssemblyAppearanceError(f"at most {MAX_PARTS} parts can have their own finish")
        unknown = sorted(str(key) for key in parts if key not in known)
        if unknown:
            raise AssemblyAppearanceError(f"not parts of {assembly_number}: {', '.join(unknown[:8])}")
        current = self.read(assembly_number)
        document = {**empty(assembly_number), "whole": finish(whole, "whole") if whole else None,
                    "parts": {str(key): finish(value, str(key)) for key, value in sorted(parts.items())},
                    "faces": current["faces"] if faces is _KEEP else self._faces(faces, known),
                    "scene": current["scene"] if scene_value is _KEEP else scene(scene_value),
                    "signs": current["signs"] if signs is _KEEP else self._signs(signs, known, current["images"]),
                    "images": current["images"], "dimensions": current["dimensions"],
                    "dimensionUnits": current["dimensionUnits"], "updatedAt": _now(), "by": by}
        return self._save(document)

    @staticmethod
    def _signs(signs: Any, known: Iterable[str], images: Mapping[str, Any]) -> list:
        if not isinstance(signs, (list, tuple)):
            raise AssemblyAppearanceError("signs must be a list")
        if len(signs) > MAX_SIGNS:
            raise AssemblyAppearanceError(f"at most {MAX_SIGNS} signs fit on one assembly")
        known = set(known)
        rows = [sign(value, parts=known, images=images, label=f"signs[{index}]") for index, value in enumerate(signs)]
        ids = [row["signId"] for row in rows]
        if len(set(ids)) != len(ids):
            raise AssemblyAppearanceError("each sign needs its own signId")
        return rows

    @staticmethod
    def _faces(faces: Any, known: Iterable[str]) -> list:
        if not isinstance(faces, (list, tuple)):
            raise AssemblyAppearanceError("faces must be a list")
        if len(faces) > MAX_FACES:
            raise AssemblyAppearanceError(f"at most {MAX_FACES} faces can have their own finish")
        known = set(known)
        rows = [face_finish(value, parts=known, label=f"faces[{index}]") for index, value in enumerate(faces)]
        keys = [face_key(row) for row in rows]
        if len(set(keys)) != len(keys):
            raise AssemblyAppearanceError("each face can have one finish (a face is listed twice)")
        return rows

    def set_dimensions(self, assembly_number: str, dimensions: Any, *, units: Any = _KEEP,
                       part_numbers: Iterable[str], by: str) -> Dict[str, Any]:
        """Replace the dimensions on the assembly (and the units they are shown in, when given)."""
        if not isinstance(dimensions, (list, tuple)):
            raise AssemblyAppearanceError("dimensions must be a list")
        if len(dimensions) > MAX_DIMENSIONS:
            raise AssemblyAppearanceError(f"at most {MAX_DIMENSIONS} dimensions fit on one assembly")
        known = set(part_numbers)
        rows = [dimension(value, parts=known, label=f"dimensions[{index}]") for index, value in enumerate(dimensions)]
        ids = [row["dimId"] for row in rows]
        if len(set(ids)) != len(ids):
            raise AssemblyAppearanceError("each dimension needs its own dimId")
        current = self.read(assembly_number)
        if units is not _KEEP and units not in DIMENSION_UNITS:
            raise AssemblyAppearanceError(f"units must be one of {', '.join(DIMENSION_UNITS)}")
        return self._save({**current, "dimensions": rows,
                           "dimensionUnits": current["dimensionUnits"] if units is _KEEP else units,
                           "updatedAt": _now(), "by": by})

    def set_scene(self, assembly_number: str, value: Any, *, by: str) -> Dict[str, Any]:
        current = self.read(assembly_number)
        return self._save({**current, "scene": scene(value), "updatedAt": _now(), "by": by})

    def set_signs(self, assembly_number: str, signs: Any, *, part_numbers: Iterable[str], by: str) -> Dict[str, Any]:
        """Replace the signs on the assembly."""
        current = self.read(assembly_number)
        rows = self._signs(signs, part_numbers, current["images"])
        return self._save({**current, "signs": rows, "updatedAt": _now(), "by": by})

    def assign(self, assembly_number: str, *, finish_value: Optional[Mapping[str, Any]], whole: bool = False,
               parts: Iterable[str] = (), part_numbers: Iterable[str], by: str) -> Dict[str, Any]:
        """Set (or clear, with no finish) the whole machine's finish and/or some parts' finishes."""
        current = self.read(assembly_number)
        new_whole = current["whole"]
        new_parts = dict(current["parts"])
        if whole:
            new_whole = finish_value
        for key in parts:
            if finish_value:
                new_parts[str(key)] = finish_value
            else:
                new_parts.pop(str(key), None)
        return self.write(assembly_number, new_whole, new_parts, part_numbers=part_numbers, by=by)

    def clear(self, assembly_number: str, *, by: str) -> Dict[str, Any]:
        """Back to the viewer's own look: no finish, scene or sign. Imported images and dimensions stay."""
        current = self.read(assembly_number)
        return self._save({**empty(assembly_number), "images": current["images"], "dimensions": current["dimensions"],
                           "dimensionUnits": current["dimensionUnits"], "updatedAt": _now(), "by": by})

    # ---- Imported images (logos) ---------------------------------------------------------------------------------

    def image_path(self, image_id: str) -> Path:
        if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
            raise AssemblyAppearanceError("not a valid image id")
        return self.root / "images" / f"{image_id}.png"

    def add_image(self, assembly_number: str, png: bytes, *, label: str, width: int, height: int,
                  by: str) -> Dict[str, Any]:
        """Keep a normalized PNG (content-addressed, shared by every assembly) and list it on this assembly."""
        current = self.read(assembly_number)
        image_id = hashlib.sha256(png).hexdigest()
        if image_id not in current["images"] and len(current["images"]) >= MAX_IMAGES:
            raise AssemblyAppearanceError(f"at most {MAX_IMAGES} images can be imported for one assembly")
        path = self.image_path(image_id)
        if not path.exists():
            self._atomic(path, png, ".image-")
        images = dict(current["images"])
        images[image_id] = {"label": (str(label or "").strip() or "Image")[:80],
                            "aspect": round(max(1, int(width)) / max(1, int(height)), 4),
                            "width": int(width), "height": int(height)}
        self._save({**current, "images": images, "updatedAt": _now(), "by": by})
        return {"imageId": image_id, **images[image_id], "url": image_url(image_id)}

    # ---- What the viewer measured (part positions, whether each sign found a surface) ------------------------------

    def _geometry_path(self, assembly_number: str) -> Path:
        self._path(assembly_number)
        return self.root / "geometry" / f"{assembly_number}.json"

    def read_geometry(self, assembly_number: str) -> Dict[str, Any]:
        try:
            data = json.loads(self._geometry_path(assembly_number).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_geometry(self, assembly_number: str, report: Any, *, part_numbers: Iterable[str]) -> Dict[str, Any]:
        """The viewer's measurements of the loaded model: each part's centre and size in metres, the machine's
        bounds, where each sign landed, whether each face finish was drawn, and the faces the user selected. Not
        part of the revision: it describes the model, not the appearance. A report without parts (the view was
        exploded or moving) keeps the parts measured before; one without a selection keeps the selection."""
        if not isinstance(report, Mapping):
            raise AssemblyAppearanceError("the geometry report must be an object")
        known = set(part_numbers)
        stored = self.read_geometry(assembly_number)
        previous = stored if report.get("parts") is None else {}
        parts_in = report.get("parts") or {}
        if not isinstance(parts_in, Mapping) or len(parts_in) > 2000:
            raise AssemblyAppearanceError("parts must map part numbers to {center, size}")
        parts = {}
        for key, value in parts_in.items():
            if key not in known or not isinstance(value, Mapping):
                continue
            parts[str(key)] = {"center": _vector(value.get("center"), f"{key} center"),
                               "size": [abs(item) for item in _vector(value.get("size"), f"{key} size")]}
        if previous:
            parts = {key: value for key, value in (previous.get("parts") or {}).items() if key in known}
        bounds = (previous.get("bounds") if previous else report.get("bounds")) or {}
        if not isinstance(bounds, Mapping):
            raise AssemblyAppearanceError("bounds must be {min, max}")
        signs_in = report.get("signs") or {}
        if not isinstance(signs_in, Mapping) or len(signs_in) > MAX_SIGNS:
            raise AssemblyAppearanceError("signs must map sign ids to where they landed")
        signs = {}
        for key, value in signs_in.items():
            if not SIGN_ID.fullmatch(str(key)) or not isinstance(value, Mapping):
                continue
            status = value.get("status")
            if status not in SIGN_STATUSES:
                continue
            row = {"status": status}
            if isinstance(value.get("widthMeters"), (int, float)) and not isinstance(value.get("widthMeters"), bool):
                row["widthMeters"] = _number(value["widthMeters"], "widthMeters", 0, 10)
            if value.get("point") is not None:
                row["point"] = _vector(value["point"], "point")
            if isinstance(value.get("face"), int) and not isinstance(value.get("face"), bool):
                row["face"] = _whole(value["face"], "face", 10_000_000)
            signs[str(key)] = row
        faces_in = report.get("faces") or {}
        if not isinstance(faces_in, Mapping) or len(faces_in) > MAX_FACES:
            raise AssemblyAppearanceError("faces must map face keys to whether the finish was drawn")
        faces = {}
        for key, value in faces_in.items():
            if not isinstance(key, str) or len(key) > 240 or not isinstance(value, Mapping) \
                    or value.get("status") not in FACE_STATUSES:
                continue
            row = {"status": value["status"]}
            for name in ("face", "copies"):
                if isinstance(value.get(name), int) and not isinstance(value.get(name), bool):
                    row[name] = _whole(value[name], name, 10_000_000)
            faces[key] = row
        dimensions_in = report.get("dimensions") or {}
        if not isinstance(dimensions_in, Mapping) or len(dimensions_in) > MAX_DIMENSIONS:
            raise AssemblyAppearanceError("dimensions must map dimension ids to what the view drew")
        dimensions = {}
        for key, value in dimensions_in.items():
            if not DIMENSION_ID.fullmatch(str(key)) or not isinstance(value, Mapping) \
                    or value.get("status") not in DIMENSION_STATUSES:
                continue
            row = {"status": value["status"]}
            if value.get("kind") in DIMENSION_KINDS and isinstance(value.get("value"), (int, float)) \
                    and not isinstance(value.get("value"), bool) and math.isfinite(value["value"]):
                row["kind"] = value["kind"]
                row["value"] = round(float(value["value"]), 9)
                if isinstance(value.get("text"), str):
                    row["text"] = value["text"][:40]
            dimensions[str(key)] = row
        if report.get("selection") is None:
            selection = list(stored.get("selection") or [])
        else:
            selection = self._selection(report.get("selection"), known)
        # What the view shows: the whole machine, or a group of parts on its own (show_assembly_parts), exploded
        # or not.
        view_in = report.get("view")
        view = None
        if isinstance(view_in, Mapping) and view_in.get("shown") in ("all", "group"):
            view = {"shown": view_in["shown"], "exploded": bool(view_in.get("exploded"))}
            if view["shown"] == "group":
                shown = view_in.get("parts") if isinstance(view_in.get("parts"), list) else []
                view["parts"] = [str(key) for key in shown[:400] if str(key) in known]
                if isinstance(view_in.get("label"), str) and view_in["label"].strip():
                    view["label"] = view_in["label"].strip()[:120]
        document = {"assemblyNumber": assembly_number, "parts": parts,
                    "bounds": {"min": _vector(bounds.get("min"), "bounds min"),
                               "max": _vector(bounds.get("max"), "bounds max")} if bounds else None,
                    "signs": signs, "faces": faces, "selection": selection, "dimensions": dimensions,
                    "view": view, "revision": str(report.get("revision") or "")[:32], "reportedAt": _now()}
        self._atomic(self._geometry_path(assembly_number),
                     json.dumps(document, indent=1, sort_keys=True).encode("utf-8"), ".geometry-")
        return document

    @staticmethod
    def _face_row(value: Any, label: str) -> Dict[str, Any]:
        """A face as the viewer describes it: its reference, kind, area, centre in the view's axes (assembled),
        the side it looks toward, and the feature and radius the CAD gives."""
        if not isinstance(value, Mapping):
            raise AssemblyAppearanceError(f"{label} must be an object")
        row = face_reference(value, label)
        kind = value.get("kind") or "other"
        row["kind"] = kind if kind in FACE_KINDS else "other"
        row["areaM2"] = _number(value.get("areaM2", row["fingerprint"]["area"]), f"{label}: areaM2", 0, 1e6, 8)
        if value.get("center") is not None:
            row["center"] = _vector(value["center"], f"{label}: center")
        if value.get("side") in SIDES:
            row["side"] = value["side"]
        if isinstance(value.get("feature"), str) and value["feature"].strip():
            row["feature"] = value["feature"].strip()[:80]
        if isinstance(value.get("radiusM"), (int, float)) and not isinstance(value.get("radiusM"), bool) \
                and value["radiusM"] > 0:
            row["radiusM"] = _number(value["radiusM"], f"{label}: radiusM", 0, 1e4, 6)
        surface = _exact_surface(value.get("geometry"), f"{label}: geometry")
        if surface:
            row["geometry"] = surface
        return row

    def _selection(self, value: Any, known: Iterable[str]) -> list:
        if not isinstance(value, (list, tuple)) or len(value) > MAX_SELECTION:
            raise AssemblyAppearanceError(f"selection must list at most {MAX_SELECTION} faces")
        known = set(known)
        rows = []
        for index, item in enumerate(value):
            if not isinstance(item, Mapping) or str(item.get("part") or "") not in known:
                continue
            rows.append({"part": str(item["part"]), **self._face_row(item, f"selection[{index}]")})
        return rows

    # ---- The viewer's list of each part's faces (docs/assembly-face-selection-plan.md) -----------------------------

    def _face_report_path(self, assembly_number: str) -> Path:
        self._path(assembly_number)
        return self.root / "geometry" / f"{assembly_number}.faces.json"

    def read_face_report(self, assembly_number: str) -> Dict[str, Any]:
        try:
            data = json.loads(self._face_report_path(assembly_number).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_face_report(self, assembly_number: str, report: Any, *, part_numbers: Iterable[str]) -> Dict[str, Any]:
        """Each part's largest faces (at most 40) as the viewer measured them on the loaded model, assembled."""
        if not isinstance(report, Mapping) or not isinstance(report.get("parts"), Mapping) \
                or len(report["parts"]) > 2000:
            raise AssemblyAppearanceError("the face report must be {parts: {part: {faceCount, copies, faces}}}")
        known = set(part_numbers)
        parts = {}
        for key, value in report["parts"].items():
            if key not in known or not isinstance(value, Mapping) or not isinstance(value.get("faces"), list):
                continue
            rows = [self._face_row(item, f"{key} faces[{index}]")
                    for index, item in enumerate(value["faces"][:MAX_REPORT_FACES])]
            entry = {"faceCount": _whole(value.get("faceCount", len(rows)), f"{key} faceCount", 10_000_000),
                     "copies": _whole(value.get("copies", 1), f"{key} copies", 5000), "faces": rows}
            if value.get("approximate"):
                entry["approximate"] = True
            parts[str(key)] = entry
        document = {"assemblyNumber": assembly_number, "parts": parts, "reportedAt": _now()}
        self._atomic(self._face_report_path(assembly_number),
                     json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8"), ".faces-")
        return document


def part_numbers(catalog: Mapping[str, Any]) -> Dict[str, str]:
    """The assembly's part numbers (the viewer's part keys) with a name for each: the CAD description when the CAD
    gives one, otherwise the body's own name (a library machine's bodies)."""
    names: Dict[str, str] = {}
    for row in catalog.get("occurrences") or []:
        if not isinstance(row, Mapping) or row.get("kind") != "part" or not row.get("partNumber") \
                or row.get("suppressed"):
            continue
        described = row.get("description") if row.get("descriptionSource") == "component_property" else None
        names.setdefault(str(row["partNumber"]), str(described or row.get("name") or row["partNumber"])[:80])
    return names


__all__ = [
    "AssemblyAppearanceError",
    "AssemblyAppearanceStore",
    "FACE_KINDS",
    "SIDES",
    "dimension",
    "dimension_entity",
    "dimensions_revision",
    "face_finish",
    "face_key",
    "face_reference",
    "finish",
    "new_dimension_id",
    "new_sign_id",
    "part_numbers",
    "resolved",
    "revision",
    "scene",
    "sign",
    "view",
]
