"""Curated industrial-library assemblies exposed to Assembly workflows.

Facility planning may use lightweight assets that are not suitable for product
documentation.  This registry is deliberately opt-in: only assemblies with a
validated extraction, a component-aware GLB, and authored manual-planning
semantics are promoted into the Assembly and Documentation workflows.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping


DOCUMENTATION_LIBRARY_REGISTRY_SCHEMA_VERSION = 1
DEFAULT_DOCUMENTATION_LIBRARY_REGISTRY = (
    Path(__file__).with_name("documentation_assembly_registry.json")
)


class DocumentationLibraryRegistryError(ValueError):
    """Raised when a curated Documentation assembly registration is invalid."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _definition_item_id(asset_id: str, source_path: str, configuration: str) -> str:
    payload = json.dumps(
        {
            "assetId": asset_id,
            "configuration": configuration or "Default",
            "sourcePath": source_path.replace("\\", "/").casefold(),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return f"item-{hashlib.sha256(payload).hexdigest()[:24]}"


def _resolve_project_asset(
    project_root: Path,
    relative_value: Any,
    *,
    field: str,
) -> Path:
    relative = Path(_text(relative_value))
    if not _text(relative_value) or relative.is_absolute():
        raise DocumentationLibraryRegistryError(
            f"{field} must be a project-relative path."
        )
    project_root = project_root.resolve()
    industrial_root = (project_root / "generated" / "industrial_assets").resolve()
    resolved = (project_root / relative).resolve()
    try:
        resolved.relative_to(industrial_root)
    except ValueError as exc:
        raise DocumentationLibraryRegistryError(
            f"{field} must remain under generated/industrial_assets."
        ) from exc
    if not resolved.is_file():
        raise DocumentationLibraryRegistryError(
            f"{field} does not exist: {relative.as_posix()}"
        )
    return resolved


def _validate_manual_planning(value: Any, *, assembly_number: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentationLibraryRegistryError(
            f"{assembly_number} manualPlanning must be an object."
        )
    groups = value.get("groups")
    if not isinstance(groups, list) or not groups:
        raise DocumentationLibraryRegistryError(
            f"{assembly_number} manualPlanning.groups must be a non-empty array."
        )

    normalized_groups = []
    names: set[str] = set()
    subassembly_refs: set[str] = set()
    direct_part_refs: set[str] = set()
    remaining_group_index = None
    for index, raw_group in enumerate(groups):
        if not isinstance(raw_group, Mapping):
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} manual group {index + 1} must be an object."
            )
        name = _text(raw_group.get("name"))
        if not name or len(name) > 120:
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} manual group {index + 1} has an invalid name."
            )
        name_key = name.casefold()
        if name_key in names:
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} repeats manual group name {name!r}."
            )
        names.add(name_key)

        normalized_subassemblies = sorted(
            {_text(item) for item in raw_group.get("subassemblyReferences") or [] if _text(item)}
        )
        normalized_direct_parts = sorted(
            {_text(item) for item in raw_group.get("directPartReferences") or [] if _text(item)}
        )
        for reference in normalized_subassemblies:
            key = reference.casefold()
            if key in subassembly_refs:
                raise DocumentationLibraryRegistryError(
                    f"{assembly_number} assigns subassembly {reference!r} more than once."
                )
            subassembly_refs.add(key)
        for reference in normalized_direct_parts:
            key = reference.casefold()
            if key in direct_part_refs:
                raise DocumentationLibraryRegistryError(
                    f"{assembly_number} assigns direct part {reference!r} more than once."
                )
            direct_part_refs.add(key)

        include_remaining = bool(raw_group.get("includeRemaining", False))
        if include_remaining:
            if remaining_group_index is not None:
                raise DocumentationLibraryRegistryError(
                    f"{assembly_number} may define only one includeRemaining group."
                )
            remaining_group_index = index
        if not normalized_subassemblies and not normalized_direct_parts and not include_remaining:
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} manual group {name!r} has no membership rule."
            )
        normalized_groups.append(
            {
                "name": name,
                "subassemblyReferences": normalized_subassemblies,
                "directPartReferences": normalized_direct_parts,
                "includeRemaining": include_remaining,
            }
        )

    if remaining_group_index is not None and remaining_group_index != len(groups) - 1:
        raise DocumentationLibraryRegistryError(
            f"{assembly_number} includeRemaining group must be last."
        )
    return {"groups": normalized_groups}


def load_documentation_library_sources(
    project_root: str | Path,
    registry_path: str | Path = DEFAULT_DOCUMENTATION_LIBRARY_REGISTRY,
) -> Dict[str, Dict[str, Any]]:
    """Load validated, opt-in industrial assemblies for standard workflows."""
    project_root = Path(project_root).resolve()
    registry_path = Path(registry_path)
    if not registry_path.is_absolute():
        registry_path = (project_root / registry_path).resolve()
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentationLibraryRegistryError(
            f"Unable to read Documentation assembly registry {registry_path}: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise DocumentationLibraryRegistryError(
            "Documentation assembly registry must be an object."
        )
    if raw.get("schemaVersion") != DOCUMENTATION_LIBRARY_REGISTRY_SCHEMA_VERSION:
        raise DocumentationLibraryRegistryError(
            f"Unsupported Documentation assembly registry schema {raw.get('schemaVersion')!r}."
        )
    assemblies = raw.get("assemblies")
    if not isinstance(assemblies, list):
        raise DocumentationLibraryRegistryError(
            "Documentation assembly registry assemblies must be an array."
        )

    resolved: Dict[str, Dict[str, Any]] = {}
    for index, row in enumerate(assemblies):
        if not isinstance(row, Mapping):
            raise DocumentationLibraryRegistryError(
                f"Documentation assembly registration {index + 1} must be an object."
            )
        assembly_number = _text(row.get("assemblyNumber"))
        asset_id = _text(row.get("assetId"))
        if not assembly_number or not asset_id:
            raise DocumentationLibraryRegistryError(
                f"Documentation assembly registration {index + 1} requires assemblyNumber and assetId."
            )
        if assembly_number in resolved:
            raise DocumentationLibraryRegistryError(
                f"Duplicate Documentation assembly number {assembly_number!r}."
            )

        profile_path = _resolve_project_asset(
            project_root, row.get("profilePath"), field=f"{assembly_number}.profilePath"
        )
        model_path = _resolve_project_asset(
            project_root, row.get("modelPath"), field=f"{assembly_number}.modelPath"
        )
        catalog_path = profile_path.with_name("catalog-entry.json")
        if not catalog_path.is_file():
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} is missing catalog-entry.json beside its extraction."
            )
        try:
            catalog_entry = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
            profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DocumentationLibraryRegistryError(
                f"Unable to read {assembly_number} source data: {exc}"
            ) from exc
        if not isinstance(catalog_entry, Mapping) or not isinstance(profile, Mapping):
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} source data must contain JSON objects."
            )
        source = catalog_entry.get("source")
        source = source if isinstance(source, Mapping) else {}
        if _text(catalog_entry.get("assetId")) != asset_id:
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} assetId does not match catalog-entry.json."
            )
        if _text(source.get("kind")).casefold() != "assembly":
            raise DocumentationLibraryRegistryError(
                f"{assembly_number} catalog source must be an assembly."
            )

        profile = copy.deepcopy(dict(profile))
        identity = profile.get("identity")
        identity = dict(identity) if isinstance(identity, Mapping) else {}
        identity["assemblyNumber"] = assembly_number
        identity["description"] = _text(row.get("description")) or _text(
            catalog_entry.get("displayName")
        ) or assembly_number
        identity["revision"] = _text(row.get("revision")) or None
        profile["identity"] = identity
        components = profile.get("components")
        if isinstance(components, list):
            for component in components:
                if not isinstance(component, dict):
                    continue
                raw_kind = _text(
                    component.get("kind") or component.get("type")
                ).casefold()
                if raw_kind != "part" or _text(component.get("itemId")):
                    continue
                source_path = _text(
                    component.get("referencedFileName")
                    or component.get("partDataKey")
                )
                configuration = _text(
                    component.get("configuration")
                    or component.get("activeConfiguration")
                ) or "Default"
                component["itemId"] = _definition_item_id(
                    asset_id, source_path, configuration
                )
        profile["manualPlanning"] = _validate_manual_planning(
            row.get("manualPlanning"), assembly_number=assembly_number
        )
        profile["industrialLibraryAsset"] = {
            "assetId": asset_id,
            "displayName": _text(row.get("displayName"))
            or _text(catalog_entry.get("displayName"))
            or assembly_number,
            "sourceSha256": _text(source.get("sha256")),
        }
        resolved[assembly_number] = {
            "productId": assembly_number,
            "assetId": asset_id,
            "source": "industrial_asset_library",
            "profile": profile,
            "assets": {"model": model_path},
        }
    return resolved


__all__ = [
    "DEFAULT_DOCUMENTATION_LIBRARY_REGISTRY",
    "DOCUMENTATION_LIBRARY_REGISTRY_SCHEMA_VERSION",
    "DocumentationLibraryRegistryError",
    "load_documentation_library_sources",
]
