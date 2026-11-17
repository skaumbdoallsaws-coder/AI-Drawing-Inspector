"""Live registration of authored assets (docs/sage-basic-shapes-plan.md, BS2).

`install(root, built)` puts a model from shape_families.build_asset into the shared private library: the GLB under
generated/industrial_assets/authored/ and its entry at the end of the private catalog, after a backup of the
catalog (the last few are kept in authored/catalog-backups/). The catalog is never re-serialised (plan rule 8): the entry is spliced into the "assets" array in the
file's own style (compact, or indented with its own line endings), summary.total is bumped, and the result must
parse to the old catalog plus the entry before it replaces the file. The host then binds the entry the way a fresh
start would (LocalFacilityLayoutHost.register_authored_asset), so no restart is needed.

Other writers: this module and tools/factory02_light_models.py hold CatalogLock (an OS lock on catalog.json.lock
beside the catalog) from their read to their replace. Each write goes through its own temporary file (replace_file),
and the catalog is compared with what was read once more just before the replace, so a catalog changed meanwhile by a
writer that takes no lock is left as it is.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import time
from typing import Any, Mapping

from .primitives import verify
from .shape_families import FOLDER

CATALOG = Path("generated/industrial_assets/local_library/catalog.json")   # the host's PRIVATE_ASSET_MANIFEST
BACKUPS = Path(FOLDER) / "catalog-backups"
KEEP_BACKUPS = 10
LOCK = threading.Lock()   # one registration at a time in this process
LOCK_WAIT = 10.0          # seconds to wait for another process's registration
_WHITESPACE = " \t\r\n"


def _skip(text: str, index: int) -> int:
    while index < len(text) and text[index] in _WHITESPACE:
        index += 1
    return index


def _object_spans(text: str, start: int) -> dict[str, tuple[int, int]]:
    """Each key of the JSON object at text[start] ('{') with the span of its value."""
    decoder = json.JSONDecoder()
    if text[start] != "{":
        raise ValueError("Not a JSON object")
    spans, index = {}, _skip(text, start + 1)
    if text[index] == "}":
        return spans
    while True:
        key, index = decoder.raw_decode(text, index)
        index = _skip(text, index)
        if text[index] != ":":
            raise ValueError("Malformed JSON object")
        index = _skip(text, index + 1)
        _value, end = decoder.raw_decode(text, index)
        spans[key] = (index, end)
        index = _skip(text, end)
        if text[index] == "}":
            return spans
        if text[index] != ",":
            raise ValueError("Malformed JSON object")
        index = _skip(text, index + 1)


def appended(original: bytes, entry: dict) -> bytes:
    """The catalog bytes with `entry` added at the end of its assets and summary.total bumped; every other byte
    stays as it was. Raises ValueError when the catalog is not an object with an assets array."""
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    text = original[len(bom):].decode("utf-8")
    before = json.loads(text)
    start = _skip(text, 0)
    spans = _object_spans(text, start)
    if "assets" not in spans or text[spans["assets"][0]] != "[":
        raise ValueError("The catalog has no assets array")
    first, end = spans["assets"]
    close = end - 1                     # the "]"
    stop = close
    while text[stop - 1] in _WHITESPACE:
        stop -= 1                       # just after the last asset
    newline = "\r\n" if "\r\n" in text else "\n"
    lead = text[first + 1:_skip(text, first + 1)]   # what comes before the first asset: its line break and indent
    compact = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if stop == first + 1:               # no assets yet
        insert = compact
    elif "\n" not in lead:
        insert = "," + lead + compact
    else:
        indent = lead.rsplit("\n", 1)[1]
        line = text.rfind("\n", 0, first) + 1
        base = len(text[line:first]) - len(text[line:first].lstrip(" "))
        unit = max(1, len(indent) - base)
        body = json.dumps(entry, sort_keys=True, indent=unit, ensure_ascii=True)
        insert = "," + newline + indent + (newline + indent).join(body.split("\n"))
    result = text[:stop] + insert + text[stop:]
    expected = dict(before)
    expected["assets"] = [*before["assets"], entry]
    total = len(expected["assets"])
    summary_span = _object_spans(result, start).get("summary")
    if summary_span and result[summary_span[0]] == "{":
        total_span = _object_spans(result, summary_span[0]).get("total")
        if total_span and isinstance(before["summary"].get("total"), int):
            result = result[:total_span[0]] + str(total) + result[total_span[1]:]
            expected["summary"] = {**before["summary"], "total": total}
    if json.loads(result) != expected:
        raise ValueError("The catalog could not be extended in place")
    return bom + result.encode("utf-8")


class CatalogLock:
    """The catalog's lock across processes: an exclusive OS lock on a file beside it (catalog.json.lock), held by
    the catalog's writers from their read to their replace. The system lets go of it when the process holding it
    stops, so a crash mid-write leaves nothing to clear; the file stays."""

    def __init__(self, catalog: Path):
        self.path = catalog.with_name(catalog.name + ".lock")
        self.handle = None

    def __enter__(self):
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                _lock(handle)
                break
            except OSError:
                if time.monotonic() > deadline:
                    os.close(handle)
                    raise ValueError("Another process is adding to the asset catalog; nothing was added. "
                                     "Try again.") from None
                time.sleep(0.05)
        self.handle = handle
        return self

    def __exit__(self, *_exc) -> None:
        try:
            _unlock(self.handle)
        finally:
            os.close(self.handle)
            self.handle = None


if os.name == "nt":
    import msvcrt

    def _lock(handle: int) -> None:
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)      # the first byte; raises OSError while another holds it

    def _unlock(handle: int) -> None:
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)


def _temporary(path: Path, data: bytes) -> Path:
    """DATA in a new temporary file of its own beside PATH, with PATH's permissions (mkstemp makes it 0600)."""
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.chmod(name, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)
    except BaseException:
        os.unlink(name)
        raise
    return Path(name)


def replace_file(path: Path, data: bytes, *, unchanged: bytes | None = None) -> None:
    """Replace PATH with DATA through a temporary file; with `unchanged`, only while PATH still holds those bytes,
    compared once more just before the replace."""
    temp = _temporary(path, data)
    try:
        if unchanged is not None and path.read_bytes() != unchanged:
            raise ValueError("The catalog changed while the asset was being added; nothing was added")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def install(root: str | Path, built: dict) -> dict:
    """Writes the model and, when the catalog lacks it, appends its entry after a backup.

    Returns {assetId, added, modelWritten, backup}. An asset already in the catalog keeps its entry; its model is
    written only when the file is missing.
    """
    root = Path(root).resolve()
    entry, payload = built["entry"], built["payload"]
    if entry["assetId"] != built["assetId"] or not entry["artifact"].startswith(FOLDER + "/"):
        raise ValueError("Only models from shape_families.build_asset go into the authored library")
    verify(payload, entry["dimensions"])
    model = (root / entry["artifact"]).resolve()
    if root / FOLDER not in model.parents:
        raise ValueError("The model path leaves the authored folder")
    catalog = root / CATALOG
    with LOCK, CatalogLock(catalog):
        original = catalog.read_bytes()
        known = {item.get("assetId") for item in json.loads(original.decode("utf-8-sig"))["assets"]}
        written = False
        if entry["assetId"] not in known or not model.is_file():
            if not model.is_file() or model.read_bytes() != payload:
                model.parent.mkdir(parents=True, exist_ok=True)
                replace_file(model, payload)
                written = True
        if entry["assetId"] in known:
            return {"assetId": entry["assetId"], "added": False, "modelWritten": written, "backup": None}
        updated = appended(original, entry)
        backups = root / BACKUPS
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"catalog-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        backup.write_bytes(original)
        for old in sorted(backups.glob("catalog-*.json"))[:-KEEP_BACKUPS]:
            old.unlink()
        replace_file(catalog, updated, unchanged=original)
    return {"assetId": entry["assetId"], "added": True, "modelWritten": written,
            "backup": backup.relative_to(root).as_posix()}


BUNDLE_FILES = {"model.glb": 30 * 1024 * 1024, "thumbnail.webp": 64 * 1024,
                "CREDITS.txt": 16 * 1024, "bundle.json": 64 * 1024}
BUNDLE_FOLDER = Path(FOLDER) / "imports"


def _bundle_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _bundle_object(payload: bytes) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate bundle field")
            value[key] = item
        return value
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite bundle value")))
    if not isinstance(value, dict):
        raise ValueError("The bundle manifest must be an object")
    return value


def _validate_bundle(entry: dict, files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Freeze and verify all incoming data before the first filesystem mutation."""
    from ai_inspector.facility_layout.private_catalog import private_asset_spec
    from .model_import.credit import credits_text
    from .model_import.identity import asset_identity, SEMANTIC_FIELDS

    private_asset_spec(entry)
    asset_id = entry["assetId"]
    if not re.fullmatch(r"asset-import-[a-z0-9-]{1,40}-[0-9a-f]{24}", asset_id):
        raise ValueError("Only model-import asset IDs go into an imported bundle")
    expected_path = (BUNDLE_FOLDER / asset_id / "model.glb").as_posix()
    if entry["artifact"] != expected_path:
        raise ValueError("The imported model must use its own bundle folder")
    if entry["sourceToCanonical"] != [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]:
        raise ValueError("Imported models must already be in the canonical frame")
    if not isinstance(files, Mapping) or set(files) != set(BUNDLE_FILES):
        raise ValueError("A bundle needs model.glb, thumbnail.webp, CREDITS.txt and bundle.json")
    frozen = dict(files)
    for name, maximum in BUNDLE_FILES.items():
        if not isinstance(frozen[name], bytes) or not 0 < len(frozen[name]) <= maximum:
            raise ValueError(f"Bundle file {name} must be bounded non-empty bytes")
    verified = verify(frozen["model.glb"], entry["dimensions"])
    if verified["triangles"] > 250000:
        raise ValueError("The imported model exceeds 250000 output triangles")
    thumbnail = frozen["thumbnail.webp"]
    if (len(thumbnail) < 20 or thumbnail[:4] != b"RIFF" or thumbnail[8:12] != b"WEBP"
            or int.from_bytes(thumbnail[4:8], "little") + 8 != len(thumbnail)):
        raise ValueError("The bundle thumbnail must be a bounded WebP file")
    if "attribution" not in entry or frozen["CREDITS.txt"] != credits_text(entry["attribution"]).encode("utf-8"):
        raise ValueError("The bundle credit must match its catalog attribution")
    manifest = _bundle_object(frozen["bundle.json"])
    if (set(manifest) != {"schemaVersion", "assetId", "identity", "files"}
            or type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1
            or manifest["assetId"] != asset_id):
        raise ValueError("The bundle manifest identity is invalid")
    hashes = {name: {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
              for name, data in frozen.items() if name != "bundle.json"}
    if manifest["files"] != hashes:
        raise ValueError("The bundle manifest file hashes or sizes differ")
    identity = manifest["identity"]
    if (not isinstance(identity, dict) or set(identity) != {"engine", "source", "recipe", "model", "entry"}
            or not isinstance(identity["engine"], str) or not 1 <= len(identity["engine"]) <= 128
            or not isinstance(identity["source"], str) or not re.fullmatch(r"[0-9a-f]{64}", identity["source"])
            or identity["model"] != hashes["model.glb"]["sha256"]
            or not isinstance(identity["recipe"], dict) or not isinstance(identity["recipe"].get("name"), str)
            or not all(key in entry for key in SEMANTIC_FIELDS)
            or identity["entry"] != {key: entry[key] for key in SEMANTIC_FIELDS}):
        raise ValueError("The bundle identity does not describe this model and entry")
    expected = asset_identity({"engineVersion": identity["engine"], "sourceSha256": identity["source"],
                               "recipe": identity["recipe"], "outputSha256": identity["model"]}, entry)
    if expected["assetId"] != asset_id or expected["identity"] != identity:
        raise ValueError("The bundle assetId does not match its complete identity")
    frozen["bundle.json"] = _bundle_json(manifest)
    _bundle_json(entry)  # Reject non-JSON/NaN metadata before writing a folder.
    return frozen


def _bundle_conflict(asset_id: str) -> None:
    from ai_inspector.facility_layout.errors import FacilityLayoutError
    raise FacilityLayoutError("asset_identity_conflict", f"The existing bundle for {asset_id} differs.",
                              status_code=409)


def _same_bundle(folder: Path, files: Mapping[str, bytes], asset_id: str, *, manifest_limit=None) -> None:
    """No repair or overwrite on reuse: even a missing/corrupted file is a conflict."""
    if not folder.is_dir() or folder.is_symlink() or {p.name for p in folder.iterdir()} != set(files):
        _bundle_conflict(asset_id)
    for name, payload in files.items():
        file = folder / name
        if file.is_symlink() or not file.is_file():
            _bundle_conflict(asset_id)
        if name == "bundle.json":
            if file.stat().st_size > (manifest_limit or BUNDLE_FILES[name]):
                _bundle_conflict(asset_id)
            try:
                identical = _bundle_json(_bundle_object(file.read_bytes())) == payload
            except (ValueError, UnicodeError, RecursionError):
                identical = False
            if not identical:
                _bundle_conflict(asset_id)
        elif file.stat().st_size != len(payload) or sha256(file.read_bytes()).digest() != sha256(payload).digest():
            _bundle_conflict(asset_id)


def _dispatch_bundle(entry, files):
    """Missing kind is a legacy import; its validator and bytes stay unchanged."""
    from . import model_builder_bundle as builds
    payload = files.get("bundle.json") if isinstance(files, Mapping) else None
    if not isinstance(payload, bytes) or not 0 < len(payload) <= builds.FILES["bundle.json"]:
        raise ValueError("The bundle manifest is invalid")
    value = _bundle_object(payload)
    kind = value.get("kind", "import")
    if kind == "build":
        try:
            frozen = builds.validate_bundle(entry, files)
        except builds.module("errors").ModelImportError as error:
            raise ValueError("The built bundle failed validation") from error
        return frozen, builds.FOLDER, builds.FILES["bundle.json"]
    if kind != "import":
        raise ValueError("Unknown model bundle kind")
    if "kind" not in value:
        return _validate_bundle(entry, files), BUNDLE_FOLDER, BUNDLE_FILES["bundle.json"]
    # Explicit import kinds use exactly the existing import validator as well.
    if len(payload) > BUNDLE_FILES["bundle.json"]:
        raise ValueError("The import manifest exceeds its size limit")
    legacy = dict(value)
    legacy.pop("kind")
    candidate = dict(files, **{"bundle.json": _bundle_json(legacy)})
    frozen = _validate_bundle(entry, candidate)
    frozen["bundle.json"] = _bundle_json(value)
    return frozen, BUNDLE_FOLDER, BUNDLE_FILES["bundle.json"]


def install_bundle(root: str | Path, entry: dict, files: Mapping[str, bytes]) -> dict[str, Any]:
    """Publish immutable model bytes before their entry, reusing exact orphans.

    Legacy/import files map the four BUNDLE_FILES names to bytes. bundle.json is
    {schemaVersion: 1, assetId, identity: <D6 identity.asset_identity(...)["identity"]>,
     files: {<each of the other three names>: {sha256, bytes}}}.
    Its own hash is intentionally excluded. Returns the same receipt keys as install.
    Build manifests dispatch to model_builder_bundle's separate validator/folder.
    The caller performs layout.edit and draft-scope authorization before calling.
    """
    from ai_inspector.facility_layout.errors import FacilityLayoutError

    root = Path(root).resolve()
    entry = deepcopy(entry)
    try:
        frozen, bundle_folder, manifest_limit = _dispatch_bundle(entry, files)
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as error:
        raise FacilityLayoutError("asset_bundle_invalid", str(error)) from None
    asset_id = entry["assetId"]
    folder = root / bundle_folder / asset_id
    catalog = root / CATALOG
    with LOCK, CatalogLock(catalog):
        # Resolve only while publication is serialized. On Windows, resolving a
        # missing path while another installer renames it can yield a transient
        # non-canonical result, incorrectly rejecting an identical bundle.
        if folder.resolve() != folder or root not in folder.parents:
            raise FacilityLayoutError("asset_bundle_invalid", "The bundle path leaves its authored folder.")
        original = catalog.read_bytes()
        payload = json.loads(original.decode("utf-8-sig"))
        if (not isinstance(payload, dict) or payload.get("schemaVersion") != 1
                or not isinstance(payload.get("assets"), list)
                or any(not isinstance(item, dict) for item in payload["assets"])):
            raise FacilityLayoutError("asset_bundle_invalid", "The private catalog format is invalid.")
        known = [item for item in payload["assets"] if item.get("assetId") == asset_id]
        if known:
            if len(known) != 1 or _bundle_json(known[0]) != _bundle_json(entry):
                _bundle_conflict(asset_id)
            _same_bundle(folder, frozen, asset_id, manifest_limit=manifest_limit)
            return {"assetId": asset_id, "added": False, "modelWritten": False, "backup": None}
        # Check that catalog publication is possible before staging any files.
        updated = appended(original, entry)
        written = False
        if folder.exists() or folder.is_symlink():
            _same_bundle(folder, frozen, asset_id, manifest_limit=manifest_limit)
        else:
            folder.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix="." + asset_id + "-", dir=folder.parent))
            try:
                for name, data in frozen.items():
                    (temporary / name).write_bytes(data)
                temporary.rename(folder)
                written = True
            finally:
                # Only our fresh staging directory is ever removed, never a published bundle.
                if temporary.exists():
                    if temporary.is_symlink() or temporary.resolve().parent != folder.parent.resolve():
                        raise FacilityLayoutError("asset_bundle_invalid", "The bundle staging path changed.")
                    shutil.rmtree(temporary)
        backups = root / BACKUPS
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"catalog-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        backup.write_bytes(original)
        for old in sorted(backups.glob("catalog-*.json"))[:-KEEP_BACKUPS]:
            old.unlink()
        replace_file(catalog, updated, unchanged=original)
    return {"assetId": asset_id, "added": True, "modelWritten": written,
            "backup": backup.relative_to(root).as_posix()}
