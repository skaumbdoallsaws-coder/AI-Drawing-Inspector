"""Review-PDF export for work-instruction documents."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Dict, Mapping
import uuid

from ai_inspector.operations_manual.exports import (
    OperationsManualExportError,
    build_prototype_docx_bytes,
    build_prototype_pdf_bytes,
    prototype_export_readiness,
)


class WorkInstructionExportError(RuntimeError):
    pass


_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$")
_EXPORT_LOCK = threading.RLock()
_DOCX_RENDERER_VERSION = "work-instructions-docx-v1"


def _safe(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if _SAFE_RE.fullmatch(text) is None:
        raise WorkInstructionExportError(f"invalid {label}")
    return text


def _filesystem_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".tmp-work-instruction-{uuid.uuid4().hex}{path.suffix}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(_filesystem_path(temporary), flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(_filesystem_path(temporary), _filesystem_path(path))
    finally:
        try:
            os.unlink(_filesystem_path(temporary))
        except FileNotFoundError:
            pass


def _document_directory(
    root: str | Path, assembly_number: str, document_revision: str
) -> Path:
    base = Path(root).resolve()
    directory = (
        base
        / _safe(assembly_number, "assembly number").lower()
        / "documents"
        / _safe(document_revision, "document revision")
    ).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise WorkInstructionExportError("invalid export path") from exc
    return directory


def review_export_readiness(document: Mapping[str, Any]) -> Dict[str, Any]:
    if not bool((document.get("releaseGate") or {}).get("reviewPdfAllowed")):
        return {
            "status": "BLOCKED",
            "pendingPages": [],
            "requiredCaptureCount": 0,
        }
    return prototype_export_readiness(document)


def store_review_pdf(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    readiness = review_export_readiness(document)
    if readiness["status"] != "READY":
        raise WorkInstructionExportError(
            f"capture {readiness['requiredCaptureCount']} technical figure(s) before export"
        )
    try:
        payload = build_prototype_pdf_bytes(root, assembly_number, document)
    except OperationsManualExportError as exc:
        raise WorkInstructionExportError(str(exc)) from exc
    revision = _safe(document.get("documentRevision"), "document revision")
    directory = _document_directory(root, assembly_number, revision)
    filename = f"{_safe(assembly_number, 'assembly number')}-assembly-work-instructions.pdf"
    path = directory / filename
    metadata_path = directory / "review-pdf.json"
    with _EXPORT_LOCK:
        _write_atomic(path, payload)
        digest = hashlib.sha256(payload).hexdigest()
        artifact = {
            "status": "ready",
            "artifactClass": "prototype_review",
            "controlledRelease": False,
            "documentRevision": revision,
            "mimeType": "application/pdf",
            "filename": filename,
            "byteCount": len(payload),
            "sha256": digest,
            "pageCount": int(document.get("pageCount") or 0),
            "url": (
                f"/api/work-instructions/{assembly_number}/documents/"
                f"{revision}/pdf"
            ),
        }
        _write_atomic(
            metadata_path,
            (
                json.dumps(
                    artifact,
                    ensure_ascii=True,
                    sort_keys=True,
                    indent=2,
                    separators=(",", ": "),
                    allow_nan=False,
                )
                + "\n"
            ).encode("ascii"),
        )
    return artifact


def store_review_docx(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    readiness = review_export_readiness(document)
    if readiness["status"] != "READY":
        raise WorkInstructionExportError(
            f"capture {readiness['requiredCaptureCount']} technical figure(s) before export"
        )
    try:
        payload = build_prototype_docx_bytes(root, assembly_number, document)
    except OperationsManualExportError as exc:
        raise WorkInstructionExportError(str(exc)) from exc
    revision = _safe(document.get("documentRevision"), "document revision")
    directory = _document_directory(root, assembly_number, revision)
    filename = f"{_safe(assembly_number, 'assembly number')}-assembly-work-instructions.docx"
    path = directory / filename
    metadata_path = directory / "review-docx.json"
    with _EXPORT_LOCK:
        _write_atomic(path, payload)
        digest = hashlib.sha256(payload).hexdigest()
        artifact = {
            "status": "ready",
            "artifactClass": "prototype_review",
            "controlledRelease": False,
            "documentRevision": revision,
            "mimeType": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            "filename": filename,
            "byteCount": len(payload),
            "sha256": digest,
            "pageCount": int(document.get("pageCount") or 0),
            "rendererVersion": _DOCX_RENDERER_VERSION,
            "url": (
                f"/api/work-instructions/{assembly_number}/documents/"
                f"{revision}/docx"
            ),
        }
        _write_atomic(
            metadata_path,
            (
                json.dumps(
                    artifact,
                    ensure_ascii=True,
                    sort_keys=True,
                    indent=2,
                    separators=(",", ": "),
                    allow_nan=False,
                )
                + "\n"
            ).encode("ascii"),
        )
    return artifact


def review_export_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
) -> Path:
    directory = _document_directory(root, assembly_number, document_revision)
    metadata_path = directory / "review-pdf.json"
    if not os.path.isfile(_filesystem_path(metadata_path)):
        raise WorkInstructionExportError("work-instruction review PDF not found")
    try:
        with open(_filesystem_path(metadata_path), "r", encoding="ascii") as handle:
            artifact = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkInstructionExportError("work-instruction PDF metadata is invalid") from exc
    path = directory / _safe(artifact.get("filename"), "filename")
    if not os.path.isfile(_filesystem_path(path)):
        raise WorkInstructionExportError("work-instruction review PDF not found")
    return Path(_filesystem_path(path))


def review_docx_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
) -> Path:
    directory = _document_directory(root, assembly_number, document_revision)
    metadata_path = directory / "review-docx.json"
    if not os.path.isfile(_filesystem_path(metadata_path)):
        raise WorkInstructionExportError("work-instruction review DOCX not found")
    try:
        with open(_filesystem_path(metadata_path), "r", encoding="ascii") as handle:
            artifact = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkInstructionExportError("work-instruction DOCX metadata is invalid") from exc
    path = directory / _safe(artifact.get("filename"), "filename")
    if not os.path.isfile(_filesystem_path(path)):
        raise WorkInstructionExportError("work-instruction review DOCX not found")
    return Path(_filesystem_path(path))
