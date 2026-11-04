"""Floor-plan import, artifact store (docs/facility-floor-plan-import-plan.md, sections 4 and 10).

Per tenant and site (decal_images.scope_directory), under <layout root>/floor-plans/<scope>/:

    sources/<sha256>.dxf              the uploaded bytes, exactly as received
    geometry/<sha256>.json            the reader's geometry (floor_plan_reader), named by its own digest
    geometry/<sha256>.manifest.json   the same without the entities: what the import panel shows first
    imports/<importId>.json           which source, which geometry, which reader; display name and size
    conversions/<conversionId>.json   a conversion staged for review (floor_plan_proposals): its drawing, alignment,
                                      layer roles and settings, each candidate with the drawing entities it came from
                                      and the native id it gets, and the digest of the operations proposed
    uploads/, jobs/                   an upload or a parse in progress (removed when it ends, swept after an hour)

Every artifact is written atomically and never rewritten: a digest names one content for good, and the same file
read by the same reader version is the same import (floor_plan_references.import_id_for), so importing it again
returns the stored result without reading it again. Nothing here changes a layout. A layout points at an import
through extensions.facilityFloorPlanReferences, and `require_reference_artifacts` refuses a change that points at an
import this site does not have. Original file names are display metadata only.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .decal_images import scope_directory
from .errors import FacilityLayoutError, FacilityNotFoundError, FacilityValidationError
from .floor_plan_references import clean_label, import_id_for, layout_references
from .repository import _native_fs_path

LOGGER = logging.getLogger(__name__)
STORE_FOLDER = "floor-plans"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PARALLEL_PARSES = 2
MAX_WAITING_PARSES = 4
QUEUE_WAIT_SECONDS = 60.0
STALE_SECONDS = 3600.0
IMPORT_ID = re.compile(r"fpi-[a-f0-9]{32}")
CONVERSION_ID = re.compile(r"fpc-[a-f0-9]{32}")


def _too_large() -> FacilityLayoutError:
    return FacilityLayoutError("floor_plan_too_large", f"The drawing is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)}"
                               " MB, more than the import supports.", status_code=413)


def scope_folder(root, principal, site_id) -> Path:
    return scope_directory(Path(root), principal, site_id)


def _path(folder, *parts) -> Path:
    return Path(_native_fs_path(Path(folder).joinpath(*parts)))


def source_path(folder, digest: str) -> Path:
    return _path(folder, "sources", digest + ".dxf")


def geometry_path(folder, digest: str) -> Path:
    return _path(folder, "geometry", digest + ".json")


def manifest_path(folder, digest: str) -> Path:
    return _path(folder, "geometry", digest + ".manifest.json")


def record_path(folder, import_id: str) -> Path:
    return _path(folder, "imports", import_id + ".json")


def conversion_path(folder, conversion_id: str) -> Path:
    return _path(folder, "conversions", conversion_id + ".json")


def parser_version() -> str:
    """The reader's identity as stored with each import: the ezdxf release and this adapter's version."""
    from importlib import metadata

    from .floor_plan_reader import ADAPTER_VERSION
    try:
        version = metadata.version("ezdxf")
    except metadata.PackageNotFoundError:
        raise FacilityLayoutError("floor_plan_reader_missing", "The DXF reader (ezdxf) is not installed on this "
                                  "computer, so drawings cannot be imported.", status_code=503) from None
    return f"ezdxf-{version}+a{ADAPTER_VERSION}"


def clean_source_name(raw: str) -> str:
    """A file name to show: the last path part, printable, at most 120 characters; never used as a path."""
    name = str(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    try:
        return clean_label(name, "file name")
    except ValueError:
        return "drawing.dxf"


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="fp-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Upload:
    """A DXF arriving in chunks, written into the scope's uploads folder and hashed on the way; refused as soon as it
    passes the size limit."""

    def __init__(self, folder: Path, limit: int = MAX_UPLOAD_BYTES):
        uploads = _path(folder, "uploads")
        uploads.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="upload-", suffix=".part", dir=uploads)
        self.path = Path(name)
        self._stream = os.fdopen(fd, "wb")
        self._digest = sha256()
        self.size = 0
        self.limit = limit

    def write(self, chunk: bytes) -> None:
        if self.size + len(chunk) > self.limit:
            raise _too_large()
        self._stream.write(chunk)
        self._digest.update(chunk)
        self.size += len(chunk)

    def finish(self) -> str:
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        return self._digest.hexdigest()

    def discard(self) -> None:
        try:
            self._stream.close()
        except OSError:
            pass
        self.path.unlink(missing_ok=True)


class _Gate:
    """One parse per principal at a time, at most MAX_PARALLEL_PARSES at once, at most MAX_WAITING_PARSES queued."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active: set[tuple[str, str]] = set()
        self.waiting = 0
        self.slots = threading.BoundedSemaphore(MAX_PARALLEL_PARSES)


_GATE = _Gate()


def _busy() -> FacilityLayoutError:
    return FacilityLayoutError("floor_plan_import_busy", "Another drawing you sent is still being read; wait for it "
                               "to finish.", status_code=429)


def _queue_full() -> FacilityLayoutError:
    return FacilityLayoutError("floor_plan_import_queue_full", "Several drawings are being read right now; try again "
                               "in a minute.", status_code=503)


def check_not_busy(principal) -> None:
    """Refuse a second upload from the same person before its bytes are read."""
    with _GATE.lock:
        if (principal.tenant_id, principal.principal_id) in _GATE.active:
            raise _busy()


@contextmanager
def _parse_slot(principal):
    key = (principal.tenant_id, principal.principal_id)
    with _GATE.lock:
        if key in _GATE.active:
            raise _busy()
        if _GATE.waiting >= MAX_WAITING_PARSES:
            raise _queue_full()
        _GATE.active.add(key)
        _GATE.waiting += 1
    waiting, acquired = True, False
    try:
        acquired = _GATE.slots.acquire(timeout=QUEUE_WAIT_SECONDS)
        with _GATE.lock:
            _GATE.waiting -= 1
            waiting = False
        if not acquired:
            raise _queue_full()
        yield
    finally:
        if acquired:
            _GATE.slots.release()
        with _GATE.lock:
            if waiting:
                _GATE.waiting -= 1
            _GATE.active.discard(key)


class _SourceLocks:
    """One lock per stored source (scope folder and digest): everything one source's import writes (the source, its
    geometry, its record) is written by one request at a time, so two people sending the same file never both read
    it, and a failed attempt never removes what another one stored. (One server process uses a store.)"""

    def __init__(self):
        self.lock = threading.Lock()
        self.held: dict[tuple[str, str], list] = {}  # key -> [lock, requests using it]

    @contextmanager
    def hold(self, folder: Path, digest: str):
        key = (str(folder), digest)
        with self.lock:
            entry = self.held.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            if not entry[0].acquire(timeout=QUEUE_WAIT_SECONDS):
                raise _queue_full()
            try:
                yield
            finally:
                entry[0].release()
        finally:
            with self.lock:
                entry[1] -= 1
                if not entry[1]:
                    del self.held[key]


_SOURCES = _SourceLocks()


def _sweep(folder: Path) -> None:
    """Remove uploads and parse folders left behind by a stopped server."""
    cutoff = time.time() - STALE_SECONDS
    for kind in ("uploads", "jobs"):
        parent = _path(folder, kind)
        if not parent.is_dir():
            continue
        for entry in parent.iterdir():
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
            except OSError:
                continue


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None


def _complete_record(folder: Path, import_id: str) -> dict | None:
    """The import record, if it and both of its geometry files are stored."""
    if not isinstance(import_id, str) or not IMPORT_ID.fullmatch(import_id):
        return None
    record = _read_json(record_path(folder, import_id))
    if not isinstance(record, dict) or record.get("importId") != import_id:
        return None
    digest = record.get("geometrySha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        return None
    if not geometry_path(folder, digest).is_file() or not manifest_path(folder, digest).is_file():
        return None
    return record


def _not_found() -> FacilityNotFoundError:
    return FacilityNotFoundError("floor_plan_import_missing", "That imported drawing was not found for this site.")


def load_import(root, principal, site_id, import_id) -> dict:
    """{"import": record, "manifest": manifest} of a stored import of this principal's tenant and site."""
    folder = scope_folder(root, principal, site_id)
    record = _complete_record(folder, import_id)
    if record is None:
        raise _not_found()
    manifest = _read_json(manifest_path(folder, record["geometrySha256"]))
    if not isinstance(manifest, dict):
        raise _not_found()
    return {"import": record, "manifest": manifest}


def artifact_file(root, principal, site_id, import_id, kind: str) -> tuple[Path, dict]:
    """(path, record) of an import's "geometry" or "source" file."""
    folder = scope_folder(root, principal, site_id)
    record = _complete_record(folder, import_id)
    if record is None:
        raise _not_found()
    path = (geometry_path(folder, record["geometrySha256"]) if kind == "geometry"
            else source_path(folder, record["sourceSha256"]))
    if not path.is_file():
        raise _not_found()
    return path, record


def import_drawing(root, principal, site_id, upload_path, source_sha256: str, size: int, source_name: str, *,
                   parse=None) -> dict:
    """Store and read an uploaded DXF (UPLOAD_PATH, already hashed and size-checked; this call consumes it). Returns
    {"import": record, "manifest": manifest, "reused": bool}; raises FacilityLayoutError with the reader's code."""
    from . import floor_plan_worker

    parse = parse or floor_plan_worker.parse_dxf
    folder = scope_folder(root, principal, site_id)
    try:
        version = parser_version()
        import_id = import_id_for(source_sha256, version)
        existing = _complete_record(folder, import_id)
        if existing is None:
            with _parse_slot(principal), _SOURCES.hold(folder, source_sha256):
                existing = _complete_record(folder, import_id)  # read by someone else while this one waited
                if existing is None:
                    record = _parse_and_store(folder, parse, Path(upload_path), source_sha256, size, source_name,
                                              version, import_id)
                    return {"import": record, "manifest": _read_json(manifest_path(folder, record["geometrySha256"])),
                            "reused": False}
        source = source_path(folder, source_sha256)
        if not source.is_file():  # stored once and lost since: the same bytes put it back
            with _SOURCES.hold(folder, source_sha256):
                if not source.is_file():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(upload_path, source)
        return {"import": existing, "manifest": _read_json(manifest_path(folder, existing["geometrySha256"])),
                "reused": True}
    finally:
        Path(upload_path).unlink(missing_ok=True)


def _parse_and_store(folder, parse, upload_path, source_sha256, size, source_name, version, import_id) -> dict:
    """Read the upload and publish the source, its geometry and the import record, the record last. Called with the
    source's lock held. If any step fails, what this attempt published is removed again (what was stored before is
    kept), so the store never has an import record without its files nor files that no record names."""
    from .floor_plan_worker import FloorPlanParseError

    _sweep(folder)
    published: list[Path] = []
    job = None
    try:
        source = source_path(folder, source_sha256)
        if not source.is_file():
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(upload_path, source)
            published.append(source)
        job = _path(folder, "jobs", uuid.uuid4().hex)
        job.mkdir(parents=True)
        try:
            result = parse(source, job, source_sha256=source_sha256)
        except FloorPlanParseError as error:
            tail = str(error.details.get("stderrTail", ""))[-500:]
            LOGGER.warning("Floor-plan import %s failed: %s %s", import_id, error.code, tail)
            details = {key: value for key, value in error.details.items() if key in ("seconds", "peakMemoryBytes")}
            raise FacilityLayoutError(error.code, error.message, status_code=error.status_code,
                                      details=details) from None
        produced = Path(result["geometryPath"])
        digest = _file_sha256(produced)
        for made, target in ((produced, geometry_path(folder, digest)),
                             (Path(result["manifestPath"]), manifest_path(folder, digest))):
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                os.replace(made, target)
                published.append(target)
        record = {
            "importId": import_id,
            "sourceSha256": source_sha256,
            "geometrySha256": digest,
            "parserVersion": version,
            "sourceName": source_name,
            "bytes": int(size),
            "createdAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "parseSeconds": result.get("seconds"),
            "peakMemoryBytes": result.get("peakMemoryBytes"),
        }
        _write_atomic(record_path(folder, import_id), json.dumps(record, separators=(",", ":")).encode("utf-8"))
        return record
    except BaseException:
        for path in reversed(published):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Floor-plan import %s: could not remove %s after a failure", import_id, path.name)
        raise
    finally:
        if job is not None:
            shutil.rmtree(job, ignore_errors=True)


def store_conversion(root, principal, site_id, record: dict) -> None:
    """Keep a staged conversion's record. Its id is a digest of everything it was made from, so the same conversion
    writes the same bytes and a stored record is left as it is; a record that differs is replaced (a proposal bound to
    the old one then fails its check and is converted again, never applied from a record that does not match)."""
    conversion_id = record.get("conversionId")
    if not isinstance(conversion_id, str) or not CONVERSION_ID.fullmatch(conversion_id):
        raise ValueError("A conversion record needs its fpc- id.")
    target = conversion_path(scope_folder(root, principal, site_id), conversion_id)
    data = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    try:
        if target.read_bytes() == data:
            return
        LOGGER.warning("Floor-plan conversion %s: the stored record differs and is replaced", conversion_id)
    except OSError:
        pass
    _write_atomic(target, data)


def load_conversion(root, principal, site_id, conversion_id) -> dict | None:
    """A staged conversion's record of this principal's tenant and site, or None."""
    if not isinstance(conversion_id, str) or not CONVERSION_ID.fullmatch(conversion_id):
        return None
    value = _read_json(conversion_path(scope_folder(root, principal, site_id), conversion_id))
    return value if isinstance(value, dict) and value.get("conversionId") == conversion_id else None


def stored_import(root, principal, site_id, import_id) -> dict | None:
    """The import record if it and its geometry are stored for this principal's tenant and site, else None."""
    return _complete_record(scope_folder(root, principal, site_id), import_id)


def require_reference_artifacts(root, principal, site_id, before, after) -> None:
    """Refuse a layout change that adds a floor-plan reference, or points one at another drawing, unless that import
    is stored for this tenant and site with exactly that geometry. References the change leaves as they were are not
    checked again, so a lost artifact never blocks unrelated edits."""
    previous = layout_references(before)
    folder = None
    for reference_id, reference in layout_references(after).items():
        old = previous.get(reference_id)
        keys = ("sourceSha256", "geometrySha256", "parserVersion")
        if old is not None and all(old.get(key) == reference.get(key) for key in keys):
            continue
        try:
            import_id = import_id_for(reference["sourceSha256"], reference["parserVersion"])
        except (KeyError, TypeError, AttributeError, UnicodeEncodeError):
            continue  # a malformed reference: layout validation reports it
        folder = folder or scope_folder(root, principal, site_id)
        record = _complete_record(folder, import_id)
        if record is None or record.get("geometrySha256") != reference.get("geometrySha256"):
            raise FacilityValidationError(
                "floor_plan_artifact_missing",
                "The imported drawing this underlay shows is not stored for this site. Import the DXF again.",
                details={"referenceId": reference_id})


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FacilityValidationError("invalid_floor_plan_alignment", f"{name} must be a finite number.")
    return float(value)


def _point(value, keys, name: str) -> tuple[float, float]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise FacilityValidationError("invalid_floor_plan_alignment",
                                      f"{name} must have exactly {keys[0]} and {keys[1]}.")
    return _number(value[keys[0]], f"{name}.{keys[0]}"), _number(value[keys[1]], f"{name}.{keys[1]}")


def compute_alignment(manifest: dict, body) -> dict:
    """An alignment from control points or one known distance, without saving anything.

    {"controlPoints": [{"source": {"u", "v"}, "target": {"x", "z"}}, ...], "scale": "declared" | "fit"}: drawing
    points (absolute drawing units) and where they belong (layout meters). "declared" (the default when the drawing
    declares its unit) holds the unit's scale: a rigid fit. "fit" lets the points set the scale. Instead of "scale",
    "metersPerDrawingUnit": n holds that scale (a unit the user chose, or one calibrated earlier).
    {"distance": {"a": {"u", "v"}, "b": {"u", "v"}, "meters": n}}: the scale that makes A to B that long."""
    from . import floor_plan_alignment as alignment

    if not isinstance(body, dict) or not body \
            or not set(body) <= {"controlPoints", "scale", "metersPerDrawingUnit", "distance"} \
            or ("distance" in body) == ("controlPoints" in body) \
            or ("scale" in body and "metersPerDrawingUnit" in body) \
            or ("distance" in body and len(body) > 1):
        raise FacilityValidationError("invalid_floor_plan_alignment",
                                      "Send controlPoints (with a scale or a held metersPerDrawingUnit) or one "
                                      "distance.")
    declared = (manifest.get("units") or {}).get("metersPerUnit")
    try:
        if "distance" in body:
            distance = body["distance"]
            if not isinstance(distance, dict) or set(distance) != {"a", "b", "meters"}:
                raise FacilityValidationError("invalid_floor_plan_alignment", "distance must have exactly a, b and "
                                                                              "meters.")
            a, b = _point(distance["a"], ("u", "v"), "distance.a"), _point(distance["b"], ("u", "v"), "distance.b")
            scale = alignment.scale_for_distance(a, b, _number(distance["meters"], "distance.meters"))
            result = {"metersPerDrawingUnit": scale}
            if declared:
                result["scaleRatio"] = scale / declared
            return result
        controls = body["controlPoints"]
        if not isinstance(controls, list):
            raise FacilityValidationError("invalid_floor_plan_alignment", "controlPoints must be a list.")
        pairs = []
        for index, control in enumerate(controls):
            if not isinstance(control, dict) or set(control) != {"source", "target"}:
                raise FacilityValidationError("invalid_floor_plan_alignment",
                                              f"controlPoints[{index}] must have exactly source and target.")
            pairs.append((_point(control["source"], ("u", "v"), f"controlPoints[{index}].source"),
                          _point(control["target"], ("x", "z"), f"controlPoints[{index}].target")))
        if "metersPerDrawingUnit" in body:
            mode, held = "held", _number(body["metersPerDrawingUnit"], "metersPerDrawingUnit")
        else:
            mode = body.get("scale", "declared" if declared else "fit")
            if mode not in ("declared", "fit"):
                raise FacilityValidationError("invalid_floor_plan_alignment", "scale must be declared or fit.")
            if mode == "declared" and not declared:
                raise FacilityValidationError("floor_plan_units_unresolved", "The drawing does not declare its unit; "
                                                                             "fit the scale from the points instead.")
            held = declared if mode == "declared" else None
        origin = manifest.get("origin") or [0.0, 0.0]
        fitted = alignment.fit(pairs, source_origin=(float(origin[0]), float(origin[1])), meters_per_unit=held)
    except ValueError as exc:
        raise FacilityValidationError("invalid_floor_plan_alignment", str(exc)) from None
    return {
        "alignment": {"sourceOrigin": fitted["sourceOrigin"], "metersPerDrawingUnit": fitted["metersPerDrawingUnit"],
                      "rotationDegrees": fitted["rotationDegrees"], "translationMeters": fitted["translationMeters"]},
        "scale": mode,
        "residualsMeters": fitted["residualsMeters"],
        "rmsMeters": fitted["rmsMeters"],
        "maxResidualMeters": fitted["maxResidualMeters"],
        "impliedMetersPerDrawingUnit": fitted["impliedMetersPerDrawingUnit"],
        "scaleRatio": fitted["scaleRatio"],
    }
