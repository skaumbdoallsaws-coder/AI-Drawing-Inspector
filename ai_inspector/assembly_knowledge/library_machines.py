"""Library machines opened as assemblies (docs/specification-sheet-slots-plan.md, SS5).

The industrial asset library (``generated/industrial_assets/local_library/catalog.json``) holds hundreds of
machine models: a display name, a category, overall dimensions and a coloured GLB whose nodes are the model's
bodies. Opening one describes it to the app as an assembly: one part occurrence per named body, the GLB as its
3D model, and a source revision that changes with the GLB. Only the Specification Sheet is offered for them: a
library model has bodies, not numbered parts.

The machines the user opened are kept in a small registry file, so they load with the library after a restart.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Dict, Iterable, List, Mapping, Optional


LIBRARY_CATALOG = Path("generated/industrial_assets/local_library/catalog.json")
REGISTRY_SCHEMA_VERSION = 1
LIBRARY_MACHINE_SOURCE = "library_machine"
ASSET_ID_RE = re.compile(r"^asset-[a-z0-9][a-z0-9-]{0,118}$")
# Walls, floors and people are not products with a data sheet.
NOT_MACHINES = frozenset({"Building Structures", "Building Elements", "People"})
BODIES_NOT_PARTS = "a library model has bodies, not numbered parts"
MAX_BODIES = 400
# Facility models carry the floor area kept clear around a machine as a body; it is not part of the machine.
ZONE_BODY_RE = re.compile(r"buffer[\s_-]*zone|keep[\s_-]*out|clearance[\s_-]*zone|safety[\s_-]*zone", re.I)

_CATALOG_CACHE: Dict[Any, Dict[str, Dict[str, Any]]] = {}
_HASH_CACHE: Dict[Any, str] = {}


class LibraryMachineError(ValueError):
    """Raised when a library machine is unknown or its model cannot be read."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def library_catalog(project_root: str | Path) -> Dict[str, Dict[str, Any]]:
    """The library's machines by asset id, with the GLB resolved inside the project (missing models left out)."""
    project_root = Path(project_root).resolve()
    path = project_root / LIBRARY_CATALOG
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _CATALOG_CACHE:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        industrial_root = (project_root / "generated" / "industrial_assets").resolve()
        entries: Dict[str, Dict[str, Any]] = {}
        for row in (raw.get("assets") if isinstance(raw, Mapping) else None) or []:
            if not isinstance(row, Mapping):
                continue
            asset_id = _text(row.get("assetId"))
            artifact = _text(row.get("artifact"))
            if not ASSET_ID_RE.match(asset_id) or not artifact.lower().endswith(".glb") or asset_id in entries:
                continue
            model = (project_root / artifact).resolve()
            try:
                model.relative_to(industrial_root)
            except ValueError:
                continue
            if not model.is_file():
                continue
            dimensions = row.get("dimensions") if isinstance(row.get("dimensions"), Mapping) else {}
            entries[asset_id] = {
                "assetId": asset_id,
                "displayName": _text(row.get("displayName")) or asset_id,
                "category": _text(row.get("category")) or "Other",
                "description": _text(row.get("description")),
                "tags": [_text(tag) for tag in row.get("tags") or [] if _text(tag)][:12],
                "dimensions": {axis: float(dimensions[axis]) for axis in ("width", "depth", "height")
                               if isinstance(dimensions.get(axis), (int, float))},
                "sourceKind": _text((row.get("source") or {}).get("kind")) if isinstance(row.get("source"),
                                                                                       Mapping) else "",
                "model": model,
            }
        _CATALOG_CACHE.clear()
        _CATALOG_CACHE[key] = entries
    return _CATALOG_CACHE[key]


def _summary(entry: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: entry[key] for key in ("assetId", "displayName", "category", "description", "tags", "dimensions")}


def search_library_machines(project_root: str | Path, query: str = "", *, category: Optional[str] = None,
                            limit: int = 12, include_all: bool = False) -> List[Dict[str, Any]]:
    """Machines whose name, tags, description or category hold every word of the query, best match first."""
    words = [word for word in re.split(r"[^a-z0-9]+", _text(query).lower()) if word]
    wanted = _text(category).casefold()
    scored = []
    for entry in library_catalog(project_root).values():
        if not include_all and entry["category"] in NOT_MACHINES:
            continue
        if wanted and entry["category"].casefold() != wanted:
            continue
        name = entry["displayName"].lower()
        name += " " + re.sub(r"[^a-z0-9]+", "", name)  # "Fork Lift" also matches forklift
        tags = " ".join(entry["tags"]).lower()
        rest = f"{entry['description']} {entry['category']} {entry['assetId']}".lower()
        score = 0
        for word in words:
            points = 3 * (word in name) + 2 * (word in tags) + (word in rest)
            if not points:
                break
            score += points
        else:
            scored.append((-score, entry["displayName"].lower(), entry))
    scored.sort(key=lambda item: item[:2])
    return [_summary(entry) for _score, _name, entry in scored[:max(1, min(int(limit), 50))]]


def _glb_document(path: str | Path) -> Dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise LibraryMachineError(f"{Path(path).name} is not a binary glTF model")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A:
        raise LibraryMachineError(f"{Path(path).name} has no JSON chunk")
    return json.loads(data[20:20 + length])


def glb_zone_bodies(path: str | Path) -> List[str]:
    """Named nodes that are a clearance zone around the machine, not the machine."""
    return sorted({_text(node.get("name")) for node in _glb_document(path).get("nodes") or []
                   if isinstance(node, Mapping) and ZONE_BODY_RE.search(_text(node.get("name")))})


def glb_body_names(path: str | Path) -> List[str]:
    """The model's bodies as the Assembly viewer names them: each node holding a mesh, by its own name (the
    viewer's loader keeps node names as written). A body whose name is empty or shared is left to the viewer's
    whole-model fallback; a clearance-zone body is not the machine."""
    names = [_text(node.get("name")) for node in _glb_document(path).get("nodes") or []
             if isinstance(node, Mapping) and "mesh" in node and not ZONE_BODY_RE.search(_text(node.get("name")))]
    counts: Dict[str, int] = {}
    for name in names:
        counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
    return [name for name in names if name and counts[name.casefold()] == 1][:MAX_BODIES]


def model_sha256(path: str | Path) -> str:
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _HASH_CACHE:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        _HASH_CACHE[key] = digest.hexdigest()
    return _HASH_CACHE[key]


def library_machine_profile(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """The machine described as an assembly profile: identity, category, dimensions and one part per body."""
    model = Path(entry["model"])
    bodies = glb_body_names(model) or [entry["displayName"]]
    zones = glb_zone_bodies(model)
    sha = model_sha256(model)
    components = [{
        "name": name, "referencedFileName": name, "partDataKey": name, "type": "Part", "kind": "part",
        "level": 1, "parentName": None, "isSuppressed": False, "configuration": "Default",
    } for name in bodies]
    return {
        "identity": {"assemblyNumber": entry["assetId"], "description": entry["displayName"], "revision": None,
                     "modelSha256": sha},
        "libraryMachine": {**_summary(entry), "modelSha256": sha, "bodyCount": len(bodies),
                           "sourceKind": entry.get("sourceKind"), "zoneBodies": zones},
        "statistics": {"totalComponents": len(components), "uniquePartCount": len(components),
                       "subAssemblyCount": 0, "totalMates": 0},
        "components": components,
        "mates": [],
        "mateRelationships": [],
        "partDataCache": {},
    }


class LibraryMachineRegistry:
    """The machines the user opened, in order: ``{"schemaVersion": 1, "machines": [{"assetId", "openedAt"}]}``."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def ids(self) -> List[str]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = raw.get("machines") if isinstance(raw, Mapping) else None
        return [row["assetId"] for row in rows or []
                if isinstance(row, Mapping) and ASSET_ID_RE.match(_text(row.get("assetId")))]

    def add(self, asset_id: str) -> bool:
        if not ASSET_ID_RE.match(asset_id):
            raise LibraryMachineError("not a library asset id")
        ids = self.ids()
        if asset_id in ids:
            return False
        rows = [{"assetId": value} for value in ids]
        rows.append({"assetId": asset_id, "openedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps({"schemaVersion": REGISTRY_SCHEMA_VERSION, "machines": rows}, indent=2),
                             encoding="utf-8")
        temporary.replace(self.path)
        return True


def library_machine_source(project_root: str | Path, asset_id: str) -> Dict[str, Any]:
    entry = library_catalog(project_root).get(asset_id)
    if entry is None:
        raise LibraryMachineError(f"{asset_id[:80]} is not in the machine library")
    return {"productId": asset_id, "assetId": asset_id, "source": LIBRARY_MACHINE_SOURCE,
            "profile": library_machine_profile(entry), "assets": {"model": Path(entry["model"])}}


def load_library_machine_sources(project_root: str | Path, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """The opened machines as prepared sources; one that left the library or cannot be read is skipped."""
    sources: Dict[str, Dict[str, Any]] = {}
    for asset_id in ids:
        try:
            sources[asset_id] = library_machine_source(project_root, asset_id)
        except (LibraryMachineError, OSError, ValueError):
            continue
    return sources


def is_library_machine(assembly_data: Any) -> bool:
    return isinstance(assembly_data, Mapping) and isinstance(assembly_data.get("libraryMachine"), Mapping)


__all__ = [
    "BODIES_NOT_PARTS",
    "LIBRARY_MACHINE_SOURCE",
    "LibraryMachineError",
    "LibraryMachineRegistry",
    "glb_body_names",
    "glb_zone_bodies",
    "is_library_machine",
    "library_catalog",
    "library_machine_profile",
    "library_machine_source",
    "load_library_machine_sources",
    "search_library_machines",
]
