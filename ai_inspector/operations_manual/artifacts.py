"""Revision-bound draft figure captures for operations-manual pages."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
from typing import Any, Dict, Iterable, Mapping
import uuid

from ai_inspector.parts_manual.artifacts import (
    PartsManualRenderArtifactError,
    validate_balloon_manifest,
)


class OperationsManualArtifactError(RuntimeError):
    pass


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,160}$")


def _safe(value: str, field: str) -> str:
    result = str(value or "").strip()
    if _SAFE_ID_RE.fullmatch(result) is None:
        raise OperationsManualArtifactError(f"invalid {field}")
    return result


def _render_directory(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
) -> Path:
    base = Path(root).resolve()
    directory = (
        base
        / _safe(assembly_number, "assembly number").lower()
        / "renders"
        / _safe(document_revision, "document revision")
    ).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise OperationsManualArtifactError("invalid render path") from exc
    return directory


def _png_size(payload: bytes) -> tuple[int, int]:
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise OperationsManualArtifactError("draft figure must be a PNG image")
    width, height = struct.unpack(">II", payload[16:24])
    if width < 1200 or height < 900:
        raise OperationsManualArtifactError(
            "draft figure must be at least 1200 x 900 pixels"
        )
    if width > 10000 or height > 10000:
        raise OperationsManualArtifactError("draft figure dimensions are excessive")
    return int(width), int(height)


def _filesystem_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved.lstrip("\\")
    return "\\\\?\\" + resolved


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".tmp-operations-render-{uuid.uuid4().hex}{path.suffix}"
    )
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


def store_draft_render_artifact(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
    page_id: str,
    payload: bytes,
    *,
    source_revision: str,
    manual_plan_revision: str,
    balloons: Iterable[Mapping[str, Any]] | None = None,
    api_route: str = "operations-manual",
) -> Dict[str, Any]:
    document_revision = str(document.get("documentRevision") or "")
    if source_revision != str(document.get("sourceRevision") or ""):
        raise OperationsManualArtifactError("draft capture source revision is stale")
    if manual_plan_revision != str(document.get("manualPlanRevision") or ""):
        raise OperationsManualArtifactError("draft capture plan revision is stale")
    page = next(
        (
            row
            for row in document.get("pages") or []
            if isinstance(row, Mapping) and str(row.get("pageId") or "") == page_id
        ),
        None,
    )
    if page is None or not isinstance(page.get("renderRequest"), Mapping):
        raise OperationsManualArtifactError("draft page has no CAD figure request")
    validated_balloons: list[Dict[str, Any]] = []
    if balloons is not None:
        try:
            validated_balloons = validate_balloon_manifest(
                page["renderRequest"], balloons
            )
        except PartsManualRenderArtifactError as exc:
            raise OperationsManualArtifactError(str(exc)) from exc
    width, height = _png_size(payload)
    directory = _render_directory(root, assembly_number, document_revision)
    safe_page = _safe(page_id, "page ID")
    image_path = directory / f"{safe_page}.png"
    metadata_path = directory / f"{safe_page}.json"
    digest = hashlib.sha256(payload).hexdigest()
    route = str(api_route or "").strip()
    if route not in {
        "operations-manual",
        "specification-sheet",
        "work-instructions",
    }:
        raise OperationsManualArtifactError("invalid draft render API route")
    artifact = {
        "status": "ready",
        "draftOnly": True,
        "acceptedForControlledPublication": False,
        "documentRevision": document_revision,
        "sourceRevision": source_revision,
        "manualPlanRevision": manual_plan_revision,
        "pageId": page_id,
        "widthPx": width,
        "heightPx": height,
        "sha256": digest,
        "balloons": validated_balloons,
        "calloutManifestValidated": balloons is not None,
        "url": (
            f"/api/{route}/{assembly_number}/renders/"
            f"{document_revision}/{page_id}"
        ),
    }
    _write_atomic(image_path, payload)
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
    return copy.deepcopy(artifact)


def attach_draft_render_artifacts(
    root: str | Path,
    assembly_number: str,
    document: Mapping[str, Any],
) -> Dict[str, Any]:
    result = copy.deepcopy(dict(document))
    revision = str(result.get("documentRevision") or "")
    try:
        directory = _render_directory(root, assembly_number, revision)
    except OperationsManualArtifactError:
        return result
    for page in result.get("pages") or []:
        request = page.get("renderRequest") if isinstance(page, dict) else None
        if not isinstance(request, dict):
            continue
        metadata_path = directory / f"{page.get('pageId')}.json"
        image_path = directory / f"{page.get('pageId')}.png"
        if not os.path.isfile(_filesystem_path(metadata_path)) or not os.path.isfile(
            _filesystem_path(image_path)
        ):
            continue
        try:
            with open(_filesystem_path(metadata_path), "r", encoding="ascii") as handle:
                artifact = json.load(handle)
            with open(_filesystem_path(image_path), "rb") as handle:
                image_digest = hashlib.sha256(handle.read()).hexdigest()
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            artifact.get("documentRevision") == revision
            and artifact.get("sha256") == image_digest
        ):
            request_contract = request.get("image")
            request["image"] = {
                **(
                    copy.deepcopy(dict(request_contract))
                    if isinstance(request_contract, Mapping)
                    else {}
                ),
                **artifact,
            }
    return result


def draft_render_path(
    root: str | Path,
    assembly_number: str,
    document_revision: str,
    page_id: str,
) -> Path:
    path = _render_directory(root, assembly_number, document_revision) / (
        _safe(page_id, "page ID") + ".png"
    )
    filesystem_path = _filesystem_path(path)
    if not os.path.isfile(filesystem_path):
        raise OperationsManualArtifactError("draft render artifact not found")
    return Path(filesystem_path)
