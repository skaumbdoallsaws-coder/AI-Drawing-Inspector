"""Create Process Map source catalogs from loaded assembly profiles."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from .repository import canonical_process_map_bytes, process_map_revision
from .schema_v3 import (
    PROCESS_MAP_LAYOUT_VERSION,
    PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
    PRODUCT_STRUCTURE_SCHEMA_VERSION,
    validate_product_structure,
)
from .validate import has_structural_errors


_SAFE_PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_BOOTSTRAP_LOCK = threading.RLock()


class AssemblyProcessMapCatalogError(ValueError):
    """Raised when a loaded assembly cannot produce a safe Process Map catalog."""


def process_map_product_id_for_assembly(assembly_number: Any) -> str:
    """Return a deterministic repository-safe ID without conflating aliases."""
    raw = str(assembly_number or "").strip()
    if not raw:
        raise AssemblyProcessMapCatalogError("assembly number is required")
    if _SAFE_PRODUCT_ID_RE.fullmatch(raw):
        return raw
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-") or "assembly"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _display_name(profile: Mapping[str, Any], assembly_number: str) -> str:
    identity = profile.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    custom = identity.get("customProperties")
    custom = custom if isinstance(custom, Mapping) else {}
    for value in (
        identity.get("description"),
        custom.get("Description"),
        custom.get("DESCRIPTION"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return assembly_number.replace("_", " ").replace("-", " ").strip() or assembly_number


def _stable_occurrence_id(*parts: Any) -> str:
    material = "\0".join(str(part or "") for part in parts)
    return "occ-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _component_item_id(
    component: Mapping[str, Any],
    part_cache: Mapping[str, Any],
) -> Optional[str]:
    properties = component.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    for key in ("PartNo", "PART_NUMBER", "partNumber", "ID"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    cache_key = str(
        component.get("partDataKey")
        or component.get("referencedFileName")
        or ""
    )
    cached = part_cache.get(cache_key) or part_cache.get(cache_key.lower())
    cached = cached if isinstance(cached, Mapping) else {}
    identity = cached.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    custom = identity.get("customProperties")
    custom = custom if isinstance(custom, Mapping) else {}
    for value in (
        custom.get("PartNo"),
        custom.get("PART_NUMBER"),
        identity.get("partNumber"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()

    source = str(component.get("referencedFileName") or cache_key).strip()
    stem = Path(source).stem.strip()
    return stem or None


def product_structure_from_assembly_profile(
    profile: Mapping[str, Any],
    *,
    assembly_number: str,
    product_id: Optional[str] = None,
) -> dict[str, Any]:
    """Translate the generic Assembly-tab profile into a placement source tree."""
    if not isinstance(profile, Mapping):
        raise AssemblyProcessMapCatalogError("assembly profile must be an object")
    safe_product_id = product_id or process_map_product_id_for_assembly(assembly_number)
    product_name = _display_name(profile, assembly_number)
    root_id = _stable_occurrence_id(assembly_number, "root")
    root = {
        "occurrenceId": root_id,
        "parentOccurrenceId": None,
        "itemId": assembly_number,
        "name": product_name,
        "kind": "assembly",
        "level": 0,
        "partIds": [],
        "partNames": [],
        "sourceOccurrenceId": root_id,
    }

    raw_cache = profile.get("partDataCache")
    raw_cache = raw_cache if isinstance(raw_cache, Mapping) else {}
    part_cache = {
        str(key): value
        for key, value in raw_cache.items()
        if isinstance(value, Mapping)
    }
    part_cache.update({
        str(key).lower(): value
        for key, value in raw_cache.items()
        if isinstance(value, Mapping)
    })

    components = profile.get("components")
    components = components if isinstance(components, list) else []
    prepared: list[dict[str, Any]] = []
    signature_counts: dict[str, int] = {}
    used_ids = {root_id}
    assembly_ids_by_name: dict[str, str] = {}

    for index, raw_component in enumerate(components):
        if not isinstance(raw_component, Mapping):
            continue
        component = copy.deepcopy(dict(raw_component))
        component_type = str(component.get("type") or "Part").strip().lower()
        parent_name = str(component.get("parentName") or "").strip()
        raw_level = component.get("level")
        if (
            component_type == "assembly"
            and isinstance(raw_level, int)
            and raw_level == 0
            and not parent_name
        ):
            assembly_ids_by_name[str(component.get("name") or "")] = root_id
            continue

        name = str(
            component.get("name")
            or component.get("referencedFileName")
            or f"Component {index + 1}"
        ).strip()
        source = str(component.get("referencedFileName") or "").strip()
        configuration = str(
            component.get("configuration")
            or component.get("activeConfiguration")
            or ""
        ).strip()
        signature = "\0".join((name, source, configuration))
        ordinal = signature_counts.get(signature, 0)
        signature_counts[signature] = ordinal + 1
        occurrence_id = str(component.get("sourceOccurrenceId") or "").strip()
        if not occurrence_id or occurrence_id in used_ids:
            occurrence_id = _stable_occurrence_id(
                assembly_number,
                name,
                source,
                configuration,
                ordinal,
            )
        used_ids.add(occurrence_id)
        kind = "subassembly" if component_type == "assembly" else "part"
        item_id = _component_item_id(component, part_cache)
        prepared.append({
            "raw": component,
            "occurrenceId": occurrence_id,
            "name": name,
            "kind": kind,
            "itemId": item_id,
            "parentName": parent_name,
        })
        if kind == "subassembly":
            assembly_ids_by_name.setdefault(name, occurrence_id)

    occurrences = [root]
    level_by_id = {root_id: 0}
    for item in prepared:
        raw = item["raw"]
        parent_id = assembly_ids_by_name.get(item["parentName"], root_id)
        level = level_by_id.get(parent_id, 0) + 1
        raw_level = raw.get("level")
        if isinstance(raw_level, int) and raw_level > 0:
            level = raw_level
        level_by_id[item["occurrenceId"]] = level
        part_ids = (
            [item["itemId"]]
            if item["kind"] == "part" and item["itemId"]
            else []
        )
        occurrence = {
            "occurrenceId": item["occurrenceId"],
            "parentOccurrenceId": parent_id,
            "itemId": item["itemId"],
            "name": item["name"],
            "kind": item["kind"],
            "level": level,
            "partIds": part_ids,
            "partNames": [item["name"]] if item["kind"] == "part" else [],
            "sourceOccurrenceId": item["occurrenceId"],
        }
        source_path = str(raw.get("referencedFileName") or "").strip()
        if source_path:
            occurrence["sourcePath"] = source_path
        if raw.get("configuration") is not None:
            occurrence["configuration"] = raw.get("configuration")
        if isinstance(raw.get("transform"), Mapping):
            occurrence["transform"] = copy.deepcopy(raw["transform"])
        occurrence["state"] = {
            "suppressed": bool(
                raw.get("suppressed")
                or raw.get("isSuppressed")
                or str(raw.get("state") or "").lower() == "suppressed"
            )
        }
        occurrences.append(occurrence)

    structure = {
        "schemaVersion": PRODUCT_STRUCTURE_SCHEMA_VERSION,
        "productId": safe_product_id,
        "productName": product_name,
        "occurrences": occurrences,
    }
    findings = validate_product_structure(structure)
    if has_structural_errors(findings):
        raise AssemblyProcessMapCatalogError(
            f"assembly profile produced an invalid product structure: {findings}"
        )
    return structure


def product_structure_from_assembly_knowledge(
    source: Mapping[str, Any],
    *,
    product_id: str,
    product_name: str,
) -> dict[str, Any]:
    """Translate an Assembly Knowledge Package's occurrence tree losslessly."""
    occurrences = []
    raw_occurrences = source.get("occurrences")
    raw_occurrences = raw_occurrences if isinstance(raw_occurrences, list) else []
    for raw in raw_occurrences:
        if not isinstance(raw, Mapping):
            continue
        occurrence_id = str(raw.get("occurrenceId") or "").strip()
        if not occurrence_id:
            continue
        kind = str(raw.get("kind") or "part").strip().lower()
        item_id = raw.get("itemId")
        name = str(raw.get("name") or occurrence_id)
        occurrence = {
            "occurrenceId": occurrence_id,
            "parentOccurrenceId": raw.get("parentOccurrenceId"),
            "itemId": item_id,
            "name": name,
            "kind": kind,
            "level": int(raw.get("level") or 0),
            "partIds": (
                [item_id]
                if kind == "part" and isinstance(item_id, str) and item_id
                else []
            ),
            "partNames": [name] if kind == "part" else [],
            "sourceOccurrenceId": str(
                raw.get("sourceOccurrenceId") or occurrence_id
            ),
        }
        for key in (
            "configuration",
            "quantity",
            "sourceHash",
            "sourceId",
            "sourcePath",
            "state",
            "transform",
            "properties",
        ):
            if key in raw:
                occurrence[key] = copy.deepcopy(raw[key])
        occurrences.append(occurrence)
    structure = {
        "schemaVersion": PRODUCT_STRUCTURE_SCHEMA_VERSION,
        "productId": product_id,
        "productName": product_name,
        "occurrences": occurrences,
    }
    findings = validate_product_structure(structure)
    if has_structural_errors(findings):
        raise AssemblyProcessMapCatalogError(
            f"assembly package produced an invalid product structure: {findings}"
        )
    return structure


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def ensure_assembly_process_map_product(
    training_root: Path,
    *,
    assembly_number: str,
    profile: Mapping[str, Any],
    package_structure: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Ensure one loaded assembly has a catalog and an initially blank map.

    Existing product structures and maps are never replaced. The generated
    files only establish the same repository contract used by authored maps.
    """
    product_id = process_map_product_id_for_assembly(assembly_number)
    product_name = _display_name(profile, assembly_number)
    if package_structure is not None:
        structure = product_structure_from_assembly_knowledge(
            package_structure,
            product_id=product_id,
            product_name=product_name,
        )
    else:
        structure = product_structure_from_assembly_profile(
            profile,
            assembly_number=assembly_number,
            product_id=product_id,
        )

    root = training_root.resolve()
    product_dir = (root / product_id).resolve()
    try:
        product_dir.relative_to(root)
    except ValueError as exc:
        raise AssemblyProcessMapCatalogError(
            "process-map product escaped the training root"
        ) from exc

    stem = product_id.replace("-", "_")
    structure_path = product_dir / f"{stem}_product_structure.json"
    legacy_path = product_dir / f"{stem}_process_map_working_draft.json"
    unique_items_path = product_dir / f"{stem}_unique_items.json"
    registry_path = product_dir / "process_maps" / "registry.json"

    with _BOOTSTRAP_LOCK:
        product_dir.mkdir(parents=True, exist_ok=True)
        if structure_path.is_file():
            existing = json.loads(structure_path.read_text(encoding="utf-8-sig"))
            findings = validate_product_structure(existing)
            if has_structural_errors(findings):
                raise AssemblyProcessMapCatalogError(
                    f"existing product structure is invalid: {findings}"
                )
            structure = existing
        else:
            _write_atomic(structure_path, canonical_process_map_bytes(structure))

        structure_revision = process_map_revision(structure)
        legacy_candidates = [
            path
            for path in product_dir.glob("*_process_map*.json")
            if ".backup-" not in path.name
            and ".tmp-" not in path.name
            and "_approved_baseline" not in path.stem
        ]
        if not registry_path.is_file() and not legacy_candidates:
            process_map = {
                "schemaVersion": PROCESS_MAP_PLACEMENT_SCHEMA_VERSION,
                "productId": product_id,
                "productName": structure.get("productName") or product_name,
                "sourceStructureRevision": structure_revision,
                "layoutVersion": PROCESS_MAP_LAYOUT_VERSION,
                "canvasNodes": [],
                "canvasEdges": [],
                "canvasGroups": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
            }
            _write_atomic(legacy_path, canonical_process_map_bytes(process_map))

        if not unique_items_path.is_file():
            unique_items = {
                "schemaVersion": 1,
                "productId": product_id,
                "items": [
                    {
                        "partId": occurrence.get("itemId"),
                        "displayName": occurrence.get("name"),
                        "sourceOccurrenceId": occurrence.get("occurrenceId"),
                    }
                    for occurrence in structure.get("occurrences", [])
                    if isinstance(occurrence, Mapping)
                    and occurrence.get("kind") == "part"
                    and occurrence.get("itemId")
                ],
            }
            _write_atomic(
                unique_items_path,
                canonical_process_map_bytes(unique_items),
            )

    return {
        "productId": product_id,
        "productName": structure.get("productName") or product_name,
        "structureRevision": process_map_revision(structure),
        "occurrenceCount": len(structure.get("occurrences") or []),
        "assets": {
            "productStructure": structure_path.name,
            "legacyMap": legacy_path.name,
            "uniqueItems": unique_items_path.name,
        },
    }
