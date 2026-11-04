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

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time

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
