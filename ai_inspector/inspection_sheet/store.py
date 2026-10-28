"""Where an assembly's inspection-sheet values and built PDFs live:

    <root>/<assembly>/values.json                       every provided or recorded value, with its source
    <root>/<assembly>/documents/<revision>/<file>.pdf   each built sheet, plus manifest.json
    <root>/<assembly>/returned/<time>.json              each filled copy given back, and its conformance
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .document import VALUE_SOURCES

_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")
_TRUE = {"true", "yes", "y", "1", "x", "on", "checked", "pass", "ok"}
_FALSE = {"false", "no", "n", "0", "off", "", "fail"}
MAX_VALUE_LENGTH = 200


class InspectionSheetStoreError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".tmp-inspection-sheet-{uuid.uuid4().hex}{path.suffix}")
    try:
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class InspectionSheetStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = threading.Lock()

    def _directory(self, assembly_number: str) -> Path:
        value = str(assembly_number or "").strip()
        if _SAFE_RE.fullmatch(value) is None:
            raise InspectionSheetStoreError("invalid assembly number")
        return self.root / value.lower()

    def values(self, assembly_number: str) -> Dict[str, Dict[str, Any]]:
        path = self._directory(assembly_number) / "values.json"
        try:
            payload = json.loads(path.read_text("utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise InspectionSheetStoreError("the stored inspection-sheet values are unreadable") from exc
        return dict(payload.get("values") or {})

    def set_values(
        self,
        assembly_number: str,
        updates: Iterable[Mapping[str, Any]],
        fields: Iterable[Mapping[str, Any]],
        *,
        source: str,
    ) -> Dict[str, Any]:
        """Store values for fields the current sheet defines. An empty value clears the field. Signatures are never
        set this way: they are made in the PDF. Returns what was set, cleared and refused (with the reason)."""
        if source not in VALUE_SOURCES:
            raise InspectionSheetStoreError(f"unknown value source: {source}")
        known = {field["name"]: field for field in fields}
        result: Dict[str, Any] = {"set": [], "cleared": [], "refused": []}
        with self._lock:
            stored = self.values(assembly_number)
            for update in updates:
                name = str(update.get("name") or "")
                field = known.get(name)
                if field is None:
                    result["refused"].append({"name": name, "reason": "the inspection sheet has no such field"})
                    continue
                if field["kind"] == "signature":
                    result["refused"].append({"name": name, "reason": "signatures are made in the PDF"})
                    continue
                raw = update.get("value")
                if field["kind"] == "checkbox":
                    text = str(raw).strip().lower() if raw is not None else ""
                    if isinstance(raw, bool):
                        value: Any = raw
                    elif text in _TRUE:
                        value = True
                    elif text in _FALSE:
                        value = False
                    else:
                        result["refused"].append({"name": name, "reason": "a checkbox takes yes or no"})
                        continue
                else:
                    value = " ".join(str(raw if raw is not None else "").split())
                    if len(value) > MAX_VALUE_LENGTH:
                        result["refused"].append({"name": name, "reason": "the value is too long"})
                        continue
                if value in ("", None) or value is False:  # an unticked box is no value, not a "no"
                    # A returned copy never clears: an older PDF must not erase what the user said since.
                    if source != "returned_pdf" and stored.pop(name, None) is not None:
                        result["cleared"].append(name)
                    continue
                if name in stored and stored[name].get("value") == value:
                    continue  # unchanged: keep where it first came from
                entry = {"value": value, "source": source, "at": _now()}
                if update.get("quote"):
                    entry["quote"] = str(update["quote"])[:400]
                stored[name] = entry
                result["set"].append(name)
            if result["set"] or result["cleared"]:
                payload = {"schemaVersion": 1, "assemblyNumber": str(assembly_number), "values": stored}
                _write_atomic(self._directory(assembly_number) / "values.json",
                              json.dumps(payload, indent=1, sort_keys=True).encode("utf-8"))
        return result

    def save_document(self, assembly_number: str, document: Mapping[str, Any], pdf: bytes, *,
                      pages: int, built_at: str) -> Dict[str, Any]:
        revision = str(document["documentRevision"])
        folder = self._directory(assembly_number) / "documents" / revision
        filename = f"{str(assembly_number).lower()}-inspection-sheet.pdf"
        _write_atomic(folder / filename, pdf)
        manifest = {"documentRevision": revision, "assemblyNumber": str(assembly_number), "builtAt": built_at,
                    "pages": pages, "file": filename, "summary": document["summary"],
                    "openFields": document["openFields"]}
        _write_atomic(folder / "manifest.json", json.dumps(manifest, indent=1).encode("utf-8"))
        return manifest

    def document_path(self, assembly_number: str, revision: str) -> Optional[Path]:
        if _REVISION_RE.fullmatch(str(revision or "")) is None:
            return None
        folder = self._directory(assembly_number) / "documents" / revision
        path = folder / f"{str(assembly_number).lower()}-inspection-sheet.pdf"
        return path if path.is_file() else None

    def manifest(self, assembly_number: str, revision: str) -> Optional[Dict[str, Any]]:
        if _REVISION_RE.fullmatch(str(revision or "")) is None:
            return None
        path = self._directory(assembly_number) / "documents" / revision / "manifest.json"
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def save_return(self, assembly_number: str, record: Mapping[str, Any]) -> None:
        folder = self._directory(assembly_number) / "returned"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        payload = json.dumps(record, indent=1).encode("utf-8")
        _write_atomic(folder / f"{stamp}.json", payload)
        _write_atomic(folder / "last.json", payload)

    def last_return(self, assembly_number: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads((self._directory(assembly_number) / "returned" / "last.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None
