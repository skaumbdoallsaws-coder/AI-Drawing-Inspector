"""Revision-aware process-map asset repository."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .validate import has_structural_errors, migrate_process_map, validate_process_map


_PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WRITE_LOCK = threading.RLock()


class ProcessMapAssetError(RuntimeError):
    """Base error for process-map storage operations."""


class ProcessMapNotFoundError(ProcessMapAssetError):
    pass


class ProcessMapConflictError(ProcessMapAssetError):
    def __init__(self, current_revision: str):
        super().__init__("process map revision conflict")
        self.current_revision = current_revision


class ProcessMapValidationError(ProcessMapAssetError):
    def __init__(self, findings: List[Dict[str, Any]]):
        super().__init__("process map failed validation")
        self.findings = findings


class ProcessMapWriteError(ProcessMapAssetError):
    pass


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def canonical_process_map_bytes(process_map: Any) -> bytes:
    text = json.dumps(
        process_map,
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
        allow_nan=False,
    )
    return (text + "\n").encode("ascii")


def process_map_revision(process_map: Any) -> str:
    return hashlib.sha256(canonical_process_map_bytes(process_map)).hexdigest()


def _resolve_product_directory(training_root: Path, product_id: str) -> Path:
    if not _PRODUCT_ID_RE.fullmatch(product_id or ""):
        raise ProcessMapNotFoundError("unknown process-map product")
    root = training_root.resolve()
    candidate = (root / product_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProcessMapNotFoundError("unknown process-map product") from exc
    if not candidate.is_dir():
        raise ProcessMapNotFoundError("unknown process-map product")
    return candidate


def resolve_process_map_asset(training_root: Path, product_id: str) -> Path:
    product_dir = _resolve_product_directory(training_root, product_id)
    candidates = sorted(
        path
        for path in product_dir.glob("*_process_map*.json")
        if ".backup-" not in path.name
        and ".tmp-" not in path.name
        and "_approved_baseline" not in path.stem
    )
    if not candidates:
        raise ProcessMapNotFoundError("product has no process-map asset")
    product_stem = product_id.replace("-", "_")
    preferred_names = [
        f"{product_stem}_process_map.json",
        f"{product_stem}_process_map_working_draft.json",
    ]
    for preferred_name in preferred_names:
        preferred = [path for path in candidates if path.name == preferred_name]
        if len(preferred) == 1:
            candidates = preferred
            break
    else:
        working_drafts = [path for path in candidates if "_working_draft" in path.stem]
        if len(working_drafts) == 1:
            candidates = working_drafts
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ProcessMapAssetError(f"product has ambiguous process-map assets: {names}")
    asset = candidates[0].resolve()
    try:
        asset.relative_to(product_dir)
    except ValueError as exc:
        raise ProcessMapNotFoundError("process-map asset escaped product directory") from exc
    return asset


def _read_json_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProcessMapAssetError(f"cannot read process-map asset '{path.name}': {exc}") from exc
    if not isinstance(value, dict):
        raise ProcessMapAssetError(f"process-map asset '{path.name}' must contain a JSON object")
    return value


def _known_product_part_ids(product_dir: Path) -> Optional[set[str]]:
    manifests = sorted(product_dir.glob("*_unique_items.json"))
    if not manifests:
        return None
    known: set[str] = set()
    for manifest in manifests:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            part_id = item.get("partId") if isinstance(item, dict) else None
            if isinstance(part_id, str) and part_id.strip():
                known.add(part_id.strip())
    for manifest in sorted(product_dir.glob("*part*_manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        colors = data.get("colors") if isinstance(data, dict) else None
        if isinstance(colors, dict):
            known.update(
                part_id.strip()
                for part_id in colors
                if isinstance(part_id, str) and part_id.strip()
            )
    return known or None


def load_process_map(training_root: Path, product_id: str) -> Dict[str, Any]:
    asset = resolve_process_map_asset(training_root, product_id)
    stored = _read_json_object(asset)
    migrated, migration_findings = migrate_process_map(stored)
    findings = migration_findings + validate_process_map(
        migrated,
        _known_product_part_ids(asset.parent),
    )
    return {
        "map": migrated,
        "revision": process_map_revision(stored),
        "findings": findings,
        "assetName": asset.name,
    }


def _backup_path(asset: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return asset.with_name(f"{asset.stem}.backup-{stamp}{asset.suffix}")


def _backup_retention_limit() -> int:
    raw = (os.getenv("INSPECTORPRO_PROCESS_MAP_BACKUP_LIMIT") or "20").strip()
    try:
        return max(1, min(200, int(raw)))
    except ValueError:
        return 20


def _prune_backups(asset: Path) -> None:
    backups = sorted(
        asset.parent.glob(f"{asset.stem}.backup-*{asset.suffix}"),
        key=lambda path: path.name,
        reverse=True,
    )
    for old_backup in backups[_backup_retention_limit():]:
        try:
            old_backup.unlink()
        except OSError:
            pass


def save_process_map(
    training_root: Path,
    product_id: str,
    process_map: Dict[str, Any],
    base_revision: str,
) -> Dict[str, Any]:
    with _WRITE_LOCK:
        asset = resolve_process_map_asset(training_root, product_id)
        stored = _read_json_object(asset)
        current_revision = process_map_revision(stored)
        supplied_revision = base_revision.strip() if isinstance(base_revision, str) else ""
        if supplied_revision != current_revision:
            raise ProcessMapConflictError(current_revision)

        findings = validate_process_map(
            process_map,
            _known_product_part_ids(asset.parent),
        )
        if has_structural_errors(findings):
            raise ProcessMapValidationError(findings)

        try:
            payload = canonical_process_map_bytes(process_map)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ProcessMapValidationError(
                [
                    {
                        "severity": "error",
                        "code": "map_not_serializable",
                        "message": f"Process map cannot be serialized as canonical ASCII JSON: {exc}",
                    }
                ]
            ) from exc

        backup = _backup_path(asset)
        temp_path: Optional[Path] = None
        try:
            shutil.copy2(asset, backup)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{asset.stem}.tmp-",
                suffix=asset.suffix,
                dir=str(asset.parent),
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_file(temp_path, asset)
            temp_path = None
            _prune_backups(asset)
        except OSError as exc:
            raise ProcessMapWriteError(f"failed to write process-map asset: {exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return {
            "map": process_map,
            "revision": process_map_revision(process_map),
            "findings": findings,
            "assetName": asset.name,
            "backupName": backup.name,
        }
