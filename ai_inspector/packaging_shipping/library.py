"""Choosing an existing InspectorPro part or assembly as the packaged product. Read-only.

The inspection library is the folder the application resolves as its library directory. A part is a
SOLIDWORKS extraction record `<part>.json` with its model `<part>_colored.glb`; an assembly is
`assemblies/<assembly>_assembly.json` with `assemblies/<assembly>_colored.glb`. Only entries with an
extracted model are listed. Only the configuration that was active at extraction has geometry, so the
other recorded configurations are shown but cannot be chosen.

A request names an entry, its revision, its configuration and the record digest the user was shown.
The browser never supplies paths, files, dimensions or masses, and nothing here writes to the library.
Library masses are not imported (an extraction can use a default density): the product mass stays unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .service import PackagingError

FORMAT = "inspectorpro-inspection-library/v1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REVISION = re.compile(r"^[A-Za-z0-9._-]{0,16}$")
MAX_RECORD_BYTES = 64 * 1024 * 1024
MAX_LISTED = 500
# Mesh envelopes come out slightly inside SOLIDWORKS boxes (tessellation, loose boxes): up to 1.52 mm on
# the real library checked 2026-11-06. Unit errors and wrong models are far outside this.
BOUNDS_TOLERANCE_M, BOUNDS_TOLERANCE_RATIO = 0.002, 0.02
MODEL_SUFFIX = "_colored.glb"
RECORD_SUFFIX = {"part": ".json", "assembly": "_assembly.json"}
LABEL = {"part": "Part", "assembly": "Assembly"}
NOTICE = ("Parts and assemblies with an extracted 3D model. Only the configuration that was active at extraction "
          "has geometry. Library masses are not imported; enter a measured mass or a documented estimate.")


def _unavailable():
    return PackagingError("library_entry_not_found", "This library entry is not available.", 404)


def _changed():
    return PackagingError("library_source_changed",
                          "This library entry changed after it was listed. Open the library again and choose it.", 409)


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _read(path, limit, too_large):
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise too_large
    return data


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _extracted_bounds(record):
    """The SOLIDWORKS bounding box, only when the record states SI units."""
    units, physical = record.get("units"), record.get("physical")
    if not isinstance(units, dict) or not str(units.get("internalSystem", "")).strip().upper().startswith("SI"):
        return None
    box = physical.get("boundingBox") if isinstance(physical, dict) else None
    if not isinstance(box, dict):
        return None
    values = [box.get(key) for key in ("length", "width", "height")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 < v <= 5 for v in values):
        return None
    return [float(v) for v in values]


def _configurations(kind, record):
    listed = record.get("configurations") if kind == "part" else None
    found, active_seen = [], False
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 160)
        if not name or any(c["name"] == name for c in found):
            continue
        active = item.get("isActive") is True and not active_seen
        active_seen |= active
        found.append({"name": name, "active": active, "available": active})
    if not active_seen:
        # Assemblies (and parts without a configuration list) record no configuration name: the model is as extracted.
        found = [{"name": "", "active": True, "available": True}] + [dict(c, active=False, available=False) for c in found]
    return found


@dataclass(frozen=True)
class LibraryModel:
    entry: dict
    configuration: str
    model: bytes
    model_sha256: str


class InspectionLibrary:
    def __init__(self, root, *, max_model_bytes):
        self.root = Path(root)
        self.max_model_bytes = max_model_bytes
        self._cache = {}

    def _folder(self, kind):
        return self.root if kind == "part" else self.root / "assemblies"

    def _paths(self, kind, entry_id):
        if kind not in RECORD_SUFFIX or not isinstance(entry_id, str) or not IDENTIFIER.fullmatch(entry_id):
            raise _unavailable()
        folder = self._folder(kind)
        return folder / (entry_id + RECORD_SUFFIX[kind]), folder / (entry_id + MODEL_SUFFIX)

    def _entry(self, kind, entry_id, *, fresh=False):
        record_path, model_path = self._paths(kind, entry_id)
        try:
            if _linked(record_path) or _linked(model_path):  # Entries never lead outside their folder.
                raise _unavailable()
            record_stat, model_stat = record_path.stat(), model_path.stat()
        except OSError:
            raise _unavailable() from None
        stamp = (record_stat.st_mtime_ns, record_stat.st_size, model_stat.st_mtime_ns, model_stat.st_size)
        cached = self._cache.get((kind, entry_id))
        if cached and cached[0] == stamp and not fresh:
            return cached[1]
        try:
            raw = _read(record_path, MAX_RECORD_BYTES,
                        PackagingError("library_record_invalid", "This library record is too large to read.", 422))
            record = json.loads(raw)
        except OSError:
            raise _unavailable() from None
        except ValueError:
            raise PackagingError("library_record_invalid", "This library record could not be read.", 422) from None
        if not isinstance(record, dict) or not isinstance(record.get("identity"), dict):
            raise PackagingError("library_record_invalid", "This library record has no identity.", 422)
        identity = record["identity"]
        revision = _text(identity.get("revision"), 32)
        reason = ""
        if not REVISION.fullmatch(revision):
            reason, revision = "The revision label is not supported for packaging.", ""
        elif model_stat.st_size > self.max_model_bytes:
            reason = f"The 3D model is larger than the {self.max_model_bytes // (1024 * 1024)} MiB import limit."
        entry = {"kind": kind, "id": entry_id, "revision": revision,
                 "name": _text(identity.get("description"), 160) or _text(record.get("fileName"), 160) or entry_id,
                 "configurations": _configurations(kind, record), "record_sha256": hashlib.sha256(raw).hexdigest(),
                 "extracted_bounds_m": _extracted_bounds(record) if kind == "part" else None,
                 "model_bytes": model_stat.st_size, "importable": not reason, "reason": reason}
        self._cache[(kind, entry_id)] = (stamp, entry)
        return entry

    def entries(self, kind=None, query=""):
        kinds = [kind] if kind in RECORD_SUFFIX else list(RECORD_SUFFIX)
        needle = _text(query, 160).lower()
        found, truncated = [], False
        for each in kinds:
            folder = self._folder(each)
            try:
                if not folder.is_dir():
                    continue
                names = sorted(p.name for p in folder.iterdir() if p.name.endswith(MODEL_SUFFIX))
            except OSError:
                continue
            for name in names:
                entry_id = name[:-len(MODEL_SUFFIX)]
                if not IDENTIFIER.fullmatch(entry_id):
                    continue
                try:
                    entry = self._entry(each, entry_id)
                except PackagingError as exc:
                    if exc.code == "library_entry_not_found":
                        continue  # A model without its record is not a library entry.
                    entry = {"kind": each, "id": entry_id, "revision": "", "name": entry_id, "configurations": [],
                             "record_sha256": "", "extracted_bounds_m": None, "model_bytes": 0,
                             "importable": False, "reason": exc.message}
                if needle and needle not in (entry["id"] + " " + entry["name"]).lower():
                    continue
                if len(found) == MAX_LISTED:
                    truncated = True
                    break
                found.append(entry)
        return {"entries": found, "truncated": truncated, "notice": NOTICE}

    def model(self, kind, entry_id, revision, configuration, record_sha256):
        entry = self._entry(kind, entry_id, fresh=True)
        if entry["record_sha256"] != record_sha256 or entry["revision"] != revision:
            raise _changed()
        choice = next((c for c in entry["configurations"] if c["name"] == configuration), None)
        if choice is None:
            raise PackagingError("library_configuration_unknown", "This configuration is not recorded for the library entry.", 404)
        if not choice["available"]:
            raise PackagingError("library_configuration_not_extracted",
                                 f"Only the configuration that was active at extraction has geometry. Make {configuration} "
                                 f"active in SOLIDWORKS, extract the {kind} again, then choose it here.", 409)
        if not entry["importable"]:
            raise PackagingError("library_model_unavailable", entry["reason"], 413 if "import limit" in entry["reason"] else 422)
        _, model_path = self._paths(kind, entry_id)
        try:
            data = _read(model_path, self.max_model_bytes, PackagingError("library_model_unavailable", entry["reason"] or
                         "The 3D model is larger than the import limit.", 413))
        except OSError:
            raise _unavailable() from None
        if self._entry(kind, entry_id, fresh=True)["record_sha256"] != record_sha256:
            raise _changed()  # The record moved while the model was read.
        return LibraryModel(entry, configuration, data, hashlib.sha256(data).hexdigest())

    @staticmethod
    def source_metadata(chosen, metadata):
        """The stored source: the isolated import of the library model, bound to the library entry it came from."""
        entry = chosen.entry
        dims, bounds = sorted(metadata["dimensions_m"], reverse=True), entry["extracted_bounds_m"]
        what = f"InspectorPro library {entry['kind']} GLB" + (f", configuration {chosen.configuration}" if chosen.configuration else "")
        if bounds is not None:
            expected = sorted(bounds, reverse=True)
            differences = [a - b for a, b in zip(dims, expected)]
            if any(abs(d) > max(BOUNDS_TOLERANCE_M, b * BOUNDS_TOLERANCE_RATIO) for d, b in zip(differences, expected)):
                raise PackagingError("library_geometry_mismatch", "The library model's size does not match its extracted "
                                     "SOLIDWORKS bounding box, so it was not imported. Extract it again.", 422)
            evidence = (f"{what}: bounding envelope of the model. It agrees with the extracted SOLIDWORKS bounding box "
                        f"(largest difference {max(abs(d) for d in differences) * 1000:.2f} mm).")
        else:
            evidence = f"{what}: bounding envelope of the model. The extraction records no bounding box to cross-check; confirm against source CAD."
        reference = {"format": FORMAT, "kind": entry["kind"], "id": entry["id"], "revision": entry["revision"],
                     "configuration": chosen.configuration, "record_sha256": entry["record_sha256"], "model_sha256": chosen.model_sha256}
        name = f"{LABEL[entry['kind']]} {entry['id']}" + (f" rev {entry['revision']}" if entry["revision"] else "")
        if entry["name"] != entry["id"]:
            name += f" - {entry['name']}"
        if chosen.configuration:
            name += f" ({chosen.configuration})"
        revision = hashlib.sha256(json.dumps(reference, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {**metadata, "name": name[:160], "source_revision": revision, "library": reference,
                "extracted_bounds_m": bounds, "geometry_evidence": evidence, "mass_basis": "unknown", "mass_kg": None}

    def status(self, reference):
        """Whether a stored library source still matches the library: current, changed or unavailable."""
        try:
            entry = self._entry(reference["kind"], reference["id"], fresh=True)
            _, model_path = self._paths(reference["kind"], reference["id"])
            digest = hashlib.sha256(_read(model_path, self.max_model_bytes, _changed())).hexdigest()
        except (PackagingError, OSError, KeyError, TypeError):
            return {"status": "unavailable", "message": "The library entry is no longer available. The imported copy is unchanged."}
        same = (entry["record_sha256"], entry["revision"], digest) == (
            reference.get("record_sha256"), reference.get("revision"), reference.get("model_sha256"))
        return ({"status": "current", "message": "The imported copy matches the library entry."} if same else
                {"status": "changed", "message": "The library entry changed after import. Import it again to use the new version."})
