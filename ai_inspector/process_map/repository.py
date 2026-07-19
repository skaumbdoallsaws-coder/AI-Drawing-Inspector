"""Revision-aware process-map asset repository."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema_v3 import (
    PROCESS_MAP_LAYOUT_VERSION,
    PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
    migrate_to_placement_map,
    product_structure_from_legacy,
    validate_placement_map,
    validate_product_structure,
)
from .validate import has_structural_errors


_PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAP_ID_RE = re.compile(r"^(?:default|pm-[0-9a-f]{8})$")
_WRITE_LOCK = threading.RLock()
PROCESS_MAP_REGISTRY_VERSION = 1
PROCESS_MAP_STATUSES = frozenset({"draft", "active", "template", "archived"})
MAX_MAP_DISPLAY_NAME_LENGTH = 120
MAX_ASSOCIATION_VALUE_LENGTH = 160


class ProcessMapAssetError(RuntimeError):
    """Base error for process-map storage operations."""


class ProcessMapNotFoundError(ProcessMapAssetError):
    pass


class ProcessMapConflictError(ProcessMapAssetError):
    def __init__(self, current_revision: str):
        super().__init__("process map revision conflict")
        self.current_revision = current_revision


class ProcessMapSourceConflictError(ProcessMapAssetError):
    def __init__(self, current_revision: str):
        super().__init__("product structure revision conflict")
        self.current_revision = current_revision


class ProcessMapValidationError(ProcessMapAssetError):
    def __init__(self, findings: List[Dict[str, Any]]):
        super().__init__("process map failed validation")
        self.findings = findings


class ProcessMapWriteError(ProcessMapAssetError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _replace_file(source: Path, destination: Path) -> None:
    for attempt in range(6):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.stem}.tmp-",
            suffix=path.suffix,
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_file(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise ProcessMapWriteError(f"failed to write process-map asset: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


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


def _process_maps_directory(product_dir: Path) -> Path:
    return product_dir / "process_maps"


def _registry_asset(product_dir: Path) -> Path:
    return _process_maps_directory(product_dir) / "registry.json"


def _validate_map_id(map_id: str) -> str:
    value = map_id.strip() if isinstance(map_id, str) else ""
    if not _MAP_ID_RE.fullmatch(value):
        raise ProcessMapNotFoundError("unknown process map")
    return value


def _named_process_map_asset(product_dir: Path, map_id: str) -> Path:
    safe_map_id = _validate_map_id(map_id)
    directory = _process_maps_directory(product_dir).resolve()
    candidate = (directory / f"{safe_map_id}.json").resolve()
    try:
        candidate.relative_to(directory)
    except ValueError as exc:
        raise ProcessMapNotFoundError("process-map asset escaped map directory") from exc
    return candidate


def _identity_validation_error(code: str, message: str) -> ProcessMapValidationError:
    return ProcessMapValidationError(
        [{"severity": "error", "code": code, "message": message}]
    )


def _normalized_display_name(value: Any, fallback: str) -> str:
    candidate = value.strip() if isinstance(value, str) else ""
    if not candidate:
        candidate = fallback.strip()
    if not candidate or len(candidate) > MAX_MAP_DISPLAY_NAME_LENGTH:
        raise _identity_validation_error(
            "invalid_map_display_name",
            f"Process-map displayName must contain 1 to {MAX_MAP_DISPLAY_NAME_LENGTH} characters.",
        )
    return candidate


def _normalized_association(value: Any, product_id: str) -> Dict[str, str]:
    association = value if isinstance(value, dict) else {}
    supplied_product_id = association.get("productId")
    if supplied_product_id not in (None, "", product_id):
        raise _identity_validation_error(
            "association_product_mismatch",
            "Process-map association.productId must match the product route.",
        )
    normalized: Dict[str, str] = {"productId": product_id}
    for key in ("assemblyId", "configuration"):
        raw = association.get(key)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > MAX_ASSOCIATION_VALUE_LENGTH:
            raise _identity_validation_error(
                "invalid_map_association",
                f"Process-map association.{key} must contain at most {MAX_ASSOCIATION_VALUE_LENGTH} characters.",
            )
        normalized[key] = raw.strip()
    return normalized


def _normalized_status(value: Any, fallback: str = "draft") -> str:
    candidate = value.strip() if isinstance(value, str) else fallback
    if candidate not in PROCESS_MAP_STATUSES:
        raise _identity_validation_error(
            "invalid_map_status",
            "Process-map status must be draft, active, template, or archived.",
        )
    return candidate


def _stamp_map_identity(
    process_map: Dict[str, Any],
    *,
    map_id: str,
    product_id: str,
    display_name: str,
    association: Dict[str, str],
    status: str,
    created_at: str,
    updated_at: str,
) -> Dict[str, Any]:
    stamped = deepcopy(process_map)
    stamped.pop("revision", None)
    stamped["mapId"] = map_id
    stamped["productId"] = product_id
    stamped["displayName"] = display_name
    stamped["association"] = association
    stamped["status"] = status
    stamped["createdAt"] = created_at
    stamped["updatedAt"] = updated_at
    return stamped


def _map_summary(process_map: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mapId": str(process_map.get("mapId") or ""),
        "displayName": str(process_map.get("displayName") or ""),
        "association": deepcopy(process_map.get("association") or {}),
        "status": str(process_map.get("status") or "draft"),
        "createdAt": str(process_map.get("createdAt") or ""),
        "updatedAt": str(process_map.get("updatedAt") or ""),
    }


def _read_json_object(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProcessMapAssetError(f"cannot read process-map asset '{path.name}': {exc}") from exc
    if not isinstance(value, dict):
        raise ProcessMapAssetError(f"process-map asset '{path.name}' must contain a JSON object")
    return value


def _product_structure_asset(product_dir: Path, product_id: str) -> Path:
    product_stem = product_id.replace("-", "_")
    return product_dir / f"{product_stem}_product_structure.json"


def _load_product_structure(
    product_dir: Path,
    product_id: str,
    stored_process_map: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]], Path, bool]:
    asset = _product_structure_asset(product_dir, product_id)
    if asset.is_file():
        structure = _read_json_object(asset)
        return structure, validate_product_structure(structure), asset, True
    structure, findings = product_structure_from_legacy(stored_process_map, product_id)
    return structure, findings, asset, False


def _known_product_part_ids(product_dir: Path) -> Optional[set[str]]:
    manifests = sorted(product_dir.glob("*_unique_items.json"))
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


def _read_registry(product_dir: Path) -> Dict[str, Any]:
    path = _registry_asset(product_dir)
    if not path.is_file():
        raise ProcessMapNotFoundError("product has no process-map registry")
    registry = _read_json_object(path)
    if registry.get("registryVersion") != PROCESS_MAP_REGISTRY_VERSION:
        raise ProcessMapAssetError("unsupported process-map registry version")
    default_map_id = registry.get("defaultMapId")
    maps = registry.get("maps")
    if not isinstance(default_map_id, str) or not _MAP_ID_RE.fullmatch(default_map_id):
        raise ProcessMapAssetError("process-map registry has an invalid defaultMapId")
    if not isinstance(maps, list):
        raise ProcessMapAssetError("process-map registry maps must be an array")
    seen: set[str] = set()
    for summary in maps:
        map_id = summary.get("mapId") if isinstance(summary, dict) else None
        if not isinstance(map_id, str) or not _MAP_ID_RE.fullmatch(map_id) or map_id in seen:
            raise ProcessMapAssetError("process-map registry contains invalid map identities")
        seen.add(map_id)
    if default_map_id not in seen:
        raise ProcessMapAssetError("process-map registry defaultMapId is not registered")
    return registry


def _write_registry(product_dir: Path, registry: Dict[str, Any]) -> None:
    _write_bytes_atomic(_registry_asset(product_dir), canonical_process_map_bytes(registry))


def _registry_with_summary(
    registry: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    updated = deepcopy(registry)
    map_id = summary["mapId"]
    maps = [
        item for item in updated.get("maps", [])
        if isinstance(item, dict) and item.get("mapId") != map_id
    ]
    maps.append(deepcopy(summary))
    maps.sort(key=lambda item: str(item.get("mapId") or ""))
    updated["maps"] = maps
    return updated


def _registry_scan_findings(
    product_dir: Path,
    registry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    directory = _process_maps_directory(product_dir)
    registered = {
        item.get("mapId")
        for item in registry.get("maps", [])
        if isinstance(item, dict) and isinstance(item.get("mapId"), str)
    }
    scanned: set[str] = set()
    findings: List[Dict[str, Any]] = []
    if directory.is_dir():
        for asset in sorted(directory.glob("*.json")):
            if asset.name == "registry.json" or ".backup-" in asset.name or ".tmp-" in asset.name:
                continue
            if _MAP_ID_RE.fullmatch(asset.stem):
                scanned.add(asset.stem)
            else:
                findings.append(
                    {
                        "severity": "warning",
                        "code": "unrecognized_map_asset",
                        "message": f"Unrecognized process-map asset '{asset.name}' is not registered.",
                    }
                )
    for map_id in sorted(registered - scanned):
        findings.append(
            {
                "severity": "warning",
                "code": "registered_map_missing",
                "mapId": map_id,
                "message": f"Registered process map '{map_id}' has no asset.",
            }
        )
    for map_id in sorted(scanned - registered):
        findings.append(
            {
                "severity": "warning",
                "code": "unregistered_map_asset",
                "mapId": map_id,
                "message": f"Process-map asset '{map_id}' is not registered.",
            }
        )
    return findings


def _ensure_registry(
    training_root: Path,
    product_id: str,
) -> tuple[Path, Dict[str, Any]]:
    with _WRITE_LOCK:
        product_dir = _resolve_product_directory(training_root, product_id)
        registry_path = _registry_asset(product_dir)
        if registry_path.is_file():
            return product_dir, _read_registry(product_dir)

        map_directory = _process_maps_directory(product_dir)
        existing_named_assets = list(map_directory.glob("*.json")) if map_directory.is_dir() else []
        if existing_named_assets:
            raise ProcessMapAssetError(
                "process-map registry is missing for an existing named-map directory"
            )

        legacy_asset = resolve_process_map_asset(training_root, product_id)
        stored = _read_json_object(legacy_asset)
        structure, structure_findings, structure_asset, structure_persisted = _load_product_structure(
            product_dir,
            product_id,
            stored,
        )
        if has_structural_errors(structure_findings):
            raise ProcessMapValidationError(structure_findings)
        structure_revision = process_map_revision(structure)
        migrated, migration_findings = migrate_to_placement_map(
            stored,
            product_id=product_id,
            structure_revision=structure_revision,
            product_structure=structure,
        )
        occurrence_ids = {
            occurrence.get("occurrenceId")
            for occurrence in structure.get("occurrences", [])
            if isinstance(occurrence, dict) and isinstance(occurrence.get("occurrenceId"), str)
        }
        findings = structure_findings + migration_findings + validate_placement_map(
            migrated,
            occurrence_ids,
        )
        if has_structural_errors(findings):
            raise ProcessMapValidationError(findings)

        now = _utc_now()
        fallback_name = str(
            migrated.get("productName")
            or product_id.replace("-", " ").title()
        ) + " Process Map"
        adopted = _stamp_map_identity(
            migrated,
            map_id="default",
            product_id=product_id,
            display_name=_normalized_display_name(migrated.get("displayName"), fallback_name),
            association=_normalized_association(migrated.get("association"), product_id),
            status=_normalized_status(migrated.get("status"), "active"),
            created_at=now,
            updated_at=now,
        )
        default_asset = _named_process_map_asset(product_dir, "default")
        registry = {
            "registryVersion": PROCESS_MAP_REGISTRY_VERSION,
            "defaultMapId": "default",
            "legacyAssetName": legacy_asset.name,
            "maps": [_map_summary(adopted)],
        }
        created_structure = False
        try:
            if not structure_persisted:
                _write_bytes_atomic(structure_asset, canonical_process_map_bytes(structure))
                created_structure = True
            _write_bytes_atomic(default_asset, canonical_process_map_bytes(adopted))
            _write_registry(product_dir, registry)
        except ProcessMapAssetError:
            try:
                default_asset.unlink(missing_ok=True)
                if created_structure:
                    structure_asset.unlink(missing_ok=True)
                if map_directory.is_dir() and not any(map_directory.iterdir()):
                    map_directory.rmdir()
            except OSError:
                pass
            raise
        return product_dir, registry


def _registered_map_summary(registry: Dict[str, Any], map_id: str) -> Dict[str, Any]:
    safe_map_id = _validate_map_id(map_id)
    for summary in registry.get("maps", []):
        if isinstance(summary, dict) and summary.get("mapId") == safe_map_id:
            return summary
    raise ProcessMapNotFoundError("process map not found")


def _load_registered_process_map(
    product_dir: Path,
    product_id: str,
    map_id: str,
    registry: Dict[str, Any],
) -> Dict[str, Any]:
    safe_map_id = _validate_map_id(map_id)
    _registered_map_summary(registry, safe_map_id)
    asset = _named_process_map_asset(product_dir, safe_map_id)
    if not asset.is_file():
        raise ProcessMapNotFoundError("process map not found")
    stored = _read_json_object(asset)
    if stored.get("mapId") != safe_map_id:
        raise ProcessMapAssetError("stored process-map identity does not match its asset name")
    if stored.get("productId") != product_id:
        raise ProcessMapAssetError("stored process-map product does not match its registry")
    _normalized_display_name(stored.get("displayName"), "")
    _normalized_association(stored.get("association"), product_id)
    _normalized_status(stored.get("status"))
    for key in ("createdAt", "updatedAt"):
        if not isinstance(stored.get(key), str) or not stored[key].strip():
            raise ProcessMapAssetError(f"stored process map is missing server-owned {key}")

    structure, structure_findings, _structure_asset, _persisted = _load_product_structure(
        product_dir,
        product_id,
        stored,
    )
    structure_revision = process_map_revision(structure)
    migrated, migration_findings = migrate_to_placement_map(
        stored,
        product_id=product_id,
        structure_revision=structure_revision,
        product_structure=structure,
    )
    occurrence_ids = {
        occurrence.get("occurrenceId")
        for occurrence in structure.get("occurrences", [])
        if isinstance(occurrence, dict) and isinstance(occurrence.get("occurrenceId"), str)
    }
    findings = (
        structure_findings
        + migration_findings
        + validate_placement_map(migrated, occurrence_ids)
    )
    return {
        "map": migrated,
        "revision": process_map_revision(stored),
        "findings": findings,
        "assetName": asset.name,
        "productStructure": structure,
        "structureRevision": structure_revision,
        "defaultMapId": registry["defaultMapId"],
        "registryFindings": _registry_scan_findings(product_dir, registry),
    }


def load_named_process_map(
    training_root: Path,
    product_id: str,
    map_id: str,
) -> Dict[str, Any]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    return _load_registered_process_map(product_dir, product_id, map_id, registry)


def load_process_map(training_root: Path, product_id: str) -> Dict[str, Any]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    result = _load_registered_process_map(
        product_dir,
        product_id,
        registry["defaultMapId"],
        registry,
    )
    legacy_asset_name = registry.get("legacyAssetName")
    if isinstance(legacy_asset_name, str) and legacy_asset_name:
        result["canonicalAssetName"] = result["assetName"]
        result["assetName"] = legacy_asset_name
        result["findings"] = [
            {
                "severity": "info",
                "code": "legacy_map_adopted",
                "message": "The legacy process map is served through the registered default-map identity.",
            }
        ] + result["findings"]
    return result


def list_process_maps(
    training_root: Path,
    product_id: str,
    *,
    include_archived: bool = False,
) -> Dict[str, Any]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    findings = _registry_scan_findings(product_dir, registry)
    maps: List[Dict[str, Any]] = []
    for registered in registry.get("maps", []):
        if not isinstance(registered, dict):
            continue
        map_id = registered.get("mapId")
        if not isinstance(map_id, str):
            continue
        asset = _named_process_map_asset(product_dir, map_id)
        if not asset.is_file():
            continue
        stored = _read_json_object(asset)
        summary = _map_summary(stored)
        if not include_archived and summary["status"] == "archived":
            continue
        summary["revision"] = process_map_revision(stored)
        summary["isDefault"] = map_id == registry["defaultMapId"]
        maps.append(summary)
    maps.sort(key=lambda item: (str(item.get("displayName") or "").lower(), item["mapId"]))
    return {
        "registryVersion": registry["registryVersion"],
        "defaultMapId": registry["defaultMapId"],
        "maps": maps,
        "findings": findings,
    }


def load_product_structure(training_root: Path, product_id: str) -> Dict[str, Any]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    default_asset = _named_process_map_asset(product_dir, registry["defaultMapId"])
    stored = _read_json_object(default_asset)
    structure, findings, structure_asset, persisted = _load_product_structure(
        product_dir,
        product_id,
        stored,
    )
    return {
        "productStructure": structure,
        "structureRevision": process_map_revision(structure),
        "findings": findings,
        "assetName": structure_asset.name,
        "persisted": persisted,
    }


def _new_map_id(product_dir: Path, registry: Dict[str, Any]) -> str:
    registered = {
        item.get("mapId")
        for item in registry.get("maps", [])
        if isinstance(item, dict)
    }
    for _attempt in range(64):
        map_id = f"pm-{secrets.token_hex(4)}"
        if map_id not in registered and not _named_process_map_asset(product_dir, map_id).exists():
            return map_id
    raise ProcessMapWriteError("could not allocate a unique process-map identity")


def _blank_process_map(
    product_id: str,
    product_structure: Dict[str, Any],
    structure_revision: str,
) -> Dict[str, Any]:
    return {
        "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
        "productId": product_id,
        "productName": str(product_structure.get("productName") or product_id),
        "sourceStructureRevision": structure_revision,
        "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
        "canvasNodes": [],
        "canvasEdges": [],
        "canvasGroups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }


def create_process_map(
    training_root: Path,
    product_id: str,
    *,
    display_name: Optional[str] = None,
    duplicate_of: Optional[str] = None,
    association: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    with _WRITE_LOCK:
        product_dir, registry = _ensure_registry(training_root, product_id)
        default_loaded = _load_registered_process_map(
            product_dir,
            product_id,
            registry["defaultMapId"],
            registry,
        )
        if duplicate_of:
            source = _load_registered_process_map(
                product_dir,
                product_id,
                duplicate_of,
                registry,
            )["map"]
            body = deepcopy(source)
            fallback_name = str(source.get("displayName") or "Process Map") + " Copy"
            source_association = source.get("association")
        else:
            body = _blank_process_map(
                product_id,
                default_loaded["productStructure"],
                default_loaded["structureRevision"],
            )
            fallback_name = "Untitled Process Map"
            source_association = None

        map_id = _new_map_id(product_dir, registry)
        now = _utc_now()
        created = _stamp_map_identity(
            body,
            map_id=map_id,
            product_id=product_id,
            display_name=_normalized_display_name(display_name, fallback_name),
            association=_normalized_association(
                association if association is not None else source_association,
                product_id,
            ),
            status="draft",
            created_at=now,
            updated_at=now,
        )
        occurrence_ids = {
            item.get("occurrenceId")
            for item in default_loaded["productStructure"].get("occurrences", [])
            if isinstance(item, dict) and isinstance(item.get("occurrenceId"), str)
        }
        findings = validate_placement_map(created, occurrence_ids)
        if has_structural_errors(findings):
            raise ProcessMapValidationError(findings)

        asset = _named_process_map_asset(product_dir, map_id)
        next_registry = _registry_with_summary(registry, _map_summary(created))
        try:
            _write_bytes_atomic(asset, canonical_process_map_bytes(created))
            _write_registry(product_dir, next_registry)
        except ProcessMapAssetError:
            try:
                asset.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return _load_registered_process_map(
            product_dir,
            product_id,
            map_id,
            next_registry,
        )


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


def _save_registered_process_map(
    training_root: Path,
    product_id: str,
    map_id: str,
    process_map: Dict[str, Any],
    base_revision: str,
) -> Dict[str, Any]:
    with _WRITE_LOCK:
        product_dir, registry = _ensure_registry(training_root, product_id)
        safe_map_id = _validate_map_id(map_id)
        _registered_map_summary(registry, safe_map_id)
        asset = _named_process_map_asset(product_dir, safe_map_id)
        if not asset.is_file():
            raise ProcessMapNotFoundError("process map not found")
        stored = _read_json_object(asset)
        current_revision = process_map_revision(stored)
        supplied_revision = base_revision.strip() if isinstance(base_revision, str) else ""
        if supplied_revision != current_revision:
            raise ProcessMapConflictError(current_revision)

        supplied_map_id = process_map.get("mapId")
        if supplied_map_id not in (None, safe_map_id):
            raise _identity_validation_error(
                "map_id_immutable",
                "Process-map mapId is immutable and must match the map route.",
            )
        supplied_product_id = process_map.get("productId")
        if supplied_product_id not in (None, product_id):
            raise _identity_validation_error(
                "map_product_immutable",
                "Process-map productId is immutable and must match the product route.",
            )
        created_at = stored.get("createdAt")
        if not isinstance(created_at, str) or not created_at.strip():
            raise ProcessMapAssetError("stored process map is missing server-owned createdAt")
        next_status = _normalized_status(
            process_map.get("status"),
            str(stored.get("status") or "draft"),
        )
        if safe_map_id == registry["defaultMapId"] and next_status == "archived":
            raise _identity_validation_error(
                "default_map_cannot_be_archived",
                "The default process map cannot be archived.",
            )
        stamped = _stamp_map_identity(
            process_map,
            map_id=safe_map_id,
            product_id=product_id,
            display_name=_normalized_display_name(
                process_map.get("displayName"),
                str(stored.get("displayName") or "Process Map"),
            ),
            association=_normalized_association(
                process_map.get("association", stored.get("association")),
                product_id,
            ),
            status=next_status,
            created_at=created_at,
            updated_at=_utc_now(),
        )

        structure, structure_findings, structure_asset, structure_persisted = _load_product_structure(
            product_dir,
            product_id,
            stored,
        )
        structure_revision = process_map_revision(structure)
        supplied_structure_revision = stamped.get("sourceStructureRevision")
        if supplied_structure_revision != structure_revision:
            raise ProcessMapSourceConflictError(structure_revision)
        occurrence_ids = {
            occurrence.get("occurrenceId")
            for occurrence in structure.get("occurrences", [])
            if isinstance(occurrence, dict) and isinstance(occurrence.get("occurrenceId"), str)
        }
        findings = structure_findings + validate_placement_map(stamped, occurrence_ids)
        if has_structural_errors(findings):
            raise ProcessMapValidationError(findings)

        if stamped.get("schemaVersion") != PROCESS_MAP_PLACEMENT_SCHEMA_VERSION:
            raise ProcessMapValidationError(
                [
                    {
                        "severity": "error",
                        "code": "unsupported_schema_version",
                        "message": (
                            "Only placement-only process-map schema "
                            f"{PROCESS_MAP_PLACEMENT_SCHEMA_VERSION} can be saved."
                        ),
                    }
                ]
        )

        try:
            payload = canonical_process_map_bytes(stamped)
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
        try:
            if not structure_persisted:
                _write_bytes_atomic(structure_asset, canonical_process_map_bytes(structure))
            shutil.copy2(asset, backup)
            _write_bytes_atomic(asset, payload)
            next_registry = _registry_with_summary(registry, _map_summary(stamped))
            try:
                _write_registry(product_dir, next_registry)
            except ProcessMapAssetError:
                try:
                    shutil.copy2(backup, asset)
                except OSError:
                    pass
                raise
            _prune_backups(asset)
        except ProcessMapAssetError:
            raise
        except OSError as exc:
            raise ProcessMapWriteError(f"failed to write process-map asset: {exc}") from exc

        return {
            "map": stamped,
            "revision": process_map_revision(stamped),
            "findings": findings,
            "assetName": asset.name,
            "backupName": backup.name,
            "productStructure": structure,
            "structureRevision": structure_revision,
            "defaultMapId": registry["defaultMapId"],
            "registryFindings": _registry_scan_findings(product_dir, next_registry),
        }


def save_named_process_map(
    training_root: Path,
    product_id: str,
    map_id: str,
    process_map: Dict[str, Any],
    base_revision: str,
) -> Dict[str, Any]:
    result = _save_registered_process_map(
        training_root,
        product_id,
        map_id,
        process_map,
        base_revision,
    )
    product_dir, registry = _ensure_registry(training_root, product_id)
    if _validate_map_id(map_id) == registry["defaultMapId"]:
        mirror_backup = _sync_legacy_default_mirror(
            training_root,
            product_id,
            result["map"],
        )
        if mirror_backup:
            result["legacyMirrorBackupName"] = mirror_backup
    return result


def _sync_legacy_default_mirror(
    training_root: Path,
    product_id: str,
    process_map: Dict[str, Any],
) -> Optional[str]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    legacy_asset_name = registry.get("legacyAssetName")
    if not isinstance(legacy_asset_name, str) or not legacy_asset_name:
        return None
    candidate = (product_dir / legacy_asset_name).resolve()
    try:
        candidate.relative_to(product_dir.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    backup = _backup_path(candidate)
    try:
        shutil.copy2(candidate, backup)
        _write_bytes_atomic(candidate, canonical_process_map_bytes(process_map))
        _prune_backups(candidate)
    except (OSError, ProcessMapAssetError):
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return backup.name


def save_process_map(
    training_root: Path,
    product_id: str,
    process_map: Dict[str, Any],
    base_revision: str,
) -> Dict[str, Any]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    result = _save_registered_process_map(
        training_root,
        product_id,
        registry["defaultMapId"],
        process_map,
        base_revision,
    )
    mirror_backup = _sync_legacy_default_mirror(training_root, product_id, result["map"])
    legacy_asset_name = registry.get("legacyAssetName")
    if isinstance(legacy_asset_name, str) and legacy_asset_name:
        result["canonicalAssetName"] = result["assetName"]
        result["assetName"] = legacy_asset_name
    if mirror_backup:
        result["canonicalBackupName"] = result["backupName"]
        result["backupName"] = mirror_backup
    return result


def archive_process_map(
    training_root: Path,
    product_id: str,
    map_id: str,
    base_revision: str,
) -> Dict[str, Any]:
    product_dir, registry = _ensure_registry(training_root, product_id)
    safe_map_id = _validate_map_id(map_id)
    if safe_map_id == registry["defaultMapId"]:
        raise _identity_validation_error(
            "default_map_cannot_be_archived",
            "The default process map cannot be archived.",
        )
    loaded = _load_registered_process_map(
        product_dir,
        product_id,
        safe_map_id,
        registry,
    )
    archived = deepcopy(loaded["map"])
    archived["status"] = "archived"
    return _save_registered_process_map(
        training_root,
        product_id,
        safe_map_id,
        archived,
        base_revision,
    )
