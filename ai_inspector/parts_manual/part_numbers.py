"""Durable engineering part-number assignments for assembly components."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Mapping, MutableMapping


REGISTRY_SCHEMA_VERSION = 1
PART_NUMBER_REGISTRY_FILENAME = "part_number_registry.json"

_PART_NUMBER_RE = re.compile(r"^\d{7}$")
_SOURCE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LIBRARY_ENTRY_STATUSES = frozenset({"number_assigned", "complete"})


class PartNumberRegistryError(ValueError):
    """Raised when the durable part-number registry is invalid."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _cad_token(value: Any) -> str:
    stem = Path(_text(value)).stem
    stem = re.sub(r"-\d+$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem.casefold())


def _source_path_key(value: Any) -> str:
    return _text(value).replace("\\", "/").casefold()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def validate_part_number_registry(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a library part-number registry."""
    if not isinstance(raw, Mapping):
        raise PartNumberRegistryError("Part-number registry must be an object.")
    if raw.get("schemaVersion") != REGISTRY_SCHEMA_VERSION:
        raise PartNumberRegistryError(
            f"Unsupported part-number registry schema: {raw.get('schemaVersion')!r}."
        )
    assignments = raw.get("assignments")
    if not isinstance(assignments, list):
        raise PartNumberRegistryError("Part-number registry assignments must be a list.")

    normalized = []
    source_to_number: Dict[tuple[str, str], str] = {}
    number_to_source: Dict[str, tuple[str, str]] = {}
    for index, row in enumerate(assignments):
        if not isinstance(row, Mapping):
            raise PartNumberRegistryError(f"Assignment {index + 1} must be an object.")
        part_number = _text(row.get("partNumber"))
        product_id = _text(row.get("productId"))
        source_path = _text(row.get("sourcePath"))
        source_hash = _text(row.get("sourceHash")).casefold()
        description = _text(row.get("description"))
        status = _text(row.get("libraryEntryStatus")) or "number_assigned"
        if not _PART_NUMBER_RE.fullmatch(part_number):
            raise PartNumberRegistryError(
                f"Assignment {index + 1} has invalid seven-digit part number {part_number!r}."
            )
        if not product_id:
            raise PartNumberRegistryError(f"Assignment {part_number} is missing productId.")
        if not source_path:
            raise PartNumberRegistryError(f"Assignment {part_number} is missing sourcePath.")
        if not _SOURCE_HASH_RE.fullmatch(source_hash):
            raise PartNumberRegistryError(f"Assignment {part_number} has an invalid sourceHash.")
        if not description:
            raise PartNumberRegistryError(f"Assignment {part_number} is missing description.")
        if status not in _LIBRARY_ENTRY_STATUSES:
            raise PartNumberRegistryError(
                f"Assignment {part_number} has unsupported libraryEntryStatus {status!r}."
            )

        source_key = (product_id.casefold(), source_hash)
        previous_number = source_to_number.get(source_key)
        if previous_number and previous_number != part_number:
            raise PartNumberRegistryError(
                f"Source {source_path!r} is assigned to both {previous_number} and {part_number}."
            )
        previous_source = number_to_source.get(part_number)
        if previous_source and previous_source != source_key:
            raise PartNumberRegistryError(
                f"Part number {part_number} is assigned to more than one source."
            )
        source_to_number[source_key] = part_number
        number_to_source[part_number] = source_key

        item_ids = sorted(
            {
                _text(value)
                for value in row.get("sourceItemIds") or []
                if _text(value)
            }
        )
        normalized_row = {
            "partNumber": part_number,
            "description": description,
            "productId": product_id,
            "sourcePath": source_path,
            "sourceHash": source_hash,
            "sourceItemIds": item_ids,
            "libraryEntryStatus": status,
        }
        for optional_key in ("assignedAt", "assignedBy", "assignmentReason"):
            optional_value = _text(row.get(optional_key))
            if optional_value:
                normalized_row[optional_key] = optional_value
        normalized.append(normalized_row)

    normalized.sort(key=lambda item: item["partNumber"])
    return {
        "schemaVersion": REGISTRY_SCHEMA_VERSION,
        "assignments": normalized,
    }


def load_part_number_registry(path: str | Path) -> Dict[str, Any]:
    """Load the registry, returning an empty valid registry when absent."""
    registry_path = Path(path)
    if not registry_path.is_file():
        return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "assignments": []}
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PartNumberRegistryError(
            f"Unable to read part-number registry {registry_path}: {exc}"
        ) from exc
    return validate_part_number_registry(raw)


def registered_part_numbers(registry: Mapping[str, Any]) -> set[str]:
    """Return all numbers reserved by a validated registry."""
    normalized = validate_part_number_registry(registry)
    return {row["partNumber"] for row in normalized["assignments"]}


def part_number_registry_revision(
    registry: Mapping[str, Any],
    *,
    product_id: str | None = None,
) -> str | None:
    """Hash the assignments that can affect a product's published identity."""
    normalized = validate_part_number_registry(registry)
    product_key = _text(product_id).casefold()
    rows = [
        row
        for row in normalized["assignments"]
        if not product_key or row["productId"].casefold() == product_key
    ]
    return _canonical_sha256(rows) if rows else None


def _engineering_part_number(
    component: Mapping[str, Any],
    cache_row: Mapping[str, Any],
) -> str | None:
    properties = component.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    custom = properties.get("customProperties")
    custom = custom if isinstance(custom, Mapping) else {}
    identity = cache_row.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    identity_custom = identity.get("customProperties")
    identity_custom = identity_custom if isinstance(identity_custom, Mapping) else {}
    candidates = (
        properties.get("PartNo"),
        properties.get("PART_NUMBER"),
        custom.get("PartNo"),
        custom.get("PART_NUMBER"),
        identity_custom.get("PartNo"),
        identity_custom.get("PART_NUMBER"),
        identity.get("partNumber"),
    )
    cad_tokens = {
        _cad_token(component.get("partDataKey")),
        _cad_token(component.get("referencedFileName")),
        _cad_token(component.get("name")),
    }
    for candidate in candidates:
        value = _text(candidate)
        if value and value.casefold() != "not specified" and _cad_token(value) not in cad_tokens:
            return value
    return None


def apply_part_number_registry(
    profile: MutableMapping[str, Any],
    registry: Mapping[str, Any],
    *,
    product_id: str,
) -> Dict[str, Any]:
    """Apply authoritative assignments to an in-memory assembly profile.

    Existing engineering identities win. CAD filenames and occurrence names do
    not: those are presentation/source identities, not engineering numbers.
    """
    normalized = validate_part_number_registry(registry)
    product_key = _text(product_id).casefold()
    assignments = [
        row
        for row in normalized["assignments"]
        if row["productId"].casefold() == product_key
    ]
    if not assignments:
        return {
            "productId": product_id,
            "registryRevision": None,
            "assignmentCount": 0,
            "appliedPartNumbers": [],
            "preservedPartNumbers": [],
            "unmatchedPartNumbers": [],
        }

    by_hash = {row["sourceHash"]: row for row in assignments}
    by_path = {_source_path_key(row["sourcePath"]): row for row in assignments}
    by_item_id = {
        item_id: row
        for row in assignments
        for item_id in row.get("sourceItemIds") or []
    }
    part_data_cache = profile.get("partDataCache")
    if not isinstance(part_data_cache, MutableMapping):
        part_data_cache = {}
        profile["partDataCache"] = part_data_cache
    original_part_data_cache = copy.deepcopy(part_data_cache)

    applied: set[str] = set()
    preserved: set[str] = set()
    matched_assignments: set[str] = set()
    components = profile.get("components")
    components = components if isinstance(components, list) else []
    for component in components:
        if not isinstance(component, MutableMapping):
            continue
        raw_kind = _text(component.get("kind") or component.get("type")).casefold()
        if raw_kind not in {"part"}:
            continue
        assignment = (
            by_hash.get(_text(component.get("sourceHash")).casefold())
            or by_item_id.get(_text(component.get("itemId")))
            or by_path.get(
                _source_path_key(
                    component.get("referencedFileName")
                    or component.get("partDataKey")
                )
            )
        )
        if not assignment:
            continue
        matched_assignments.add(assignment["partNumber"])

        part_key = _text(
            component.get("partDataKey")
            or component.get("referencedFileName")
            or assignment["sourcePath"]
        )
        cache_row = part_data_cache.get(part_key)
        if not isinstance(cache_row, MutableMapping):
            cache_row = {}
            part_data_cache[part_key] = cache_row
        original_cache_row = original_part_data_cache.get(part_key)
        original_cache_row = (
            original_cache_row if isinstance(original_cache_row, Mapping) else {}
        )
        existing = _engineering_part_number(component, original_cache_row)
        if existing and existing != assignment["partNumber"]:
            preserved.add(existing)
            continue

        properties = component.get("properties")
        properties = dict(properties) if isinstance(properties, Mapping) else {}
        property_custom = properties.get("customProperties")
        property_custom = (
            dict(property_custom) if isinstance(property_custom, Mapping) else {}
        )
        properties["PartNo"] = assignment["partNumber"]
        property_custom["PartNo"] = assignment["partNumber"]
        property_custom.setdefault("Description", assignment["description"])
        properties["customProperties"] = property_custom
        component["properties"] = properties
        component["partNumberAssignment"] = {
            "source": "library_registry",
            "partNumber": assignment["partNumber"],
            "libraryEntryStatus": assignment["libraryEntryStatus"],
        }

        identity = cache_row.get("identity")
        identity = dict(identity) if isinstance(identity, Mapping) else {}
        identity_custom = identity.get("customProperties")
        identity_custom = (
            dict(identity_custom) if isinstance(identity_custom, Mapping) else {}
        )
        identity["partNumber"] = assignment["partNumber"]
        if (
            not _text(identity.get("description"))
            or _text(identity.get("descriptionSource")) == "cad_filename"
        ):
            identity["description"] = assignment["description"]
            identity["descriptionSource"] = "library_registry"
        identity_custom["PartNo"] = assignment["partNumber"]
        if identity.get("descriptionSource") == "library_registry":
            identity_custom["Description"] = assignment["description"]
        else:
            identity_custom.setdefault("Description", assignment["description"])
        identity["customProperties"] = identity_custom
        cache_row["identity"] = identity
        applied.add(assignment["partNumber"])

    revision = part_number_registry_revision(normalized, product_id=product_id)
    profile["partNumberRegistryRevision"] = revision
    profile["partNumberRegistry"] = {
        "schemaVersion": REGISTRY_SCHEMA_VERSION,
        "revision": revision,
        "assignmentCount": len(assignments),
    }
    return {
        "productId": product_id,
        "registryRevision": revision,
        "assignmentCount": len(assignments),
        "appliedPartNumbers": sorted(applied),
        "preservedPartNumbers": sorted(preserved),
        "unmatchedPartNumbers": sorted(
            {row["partNumber"] for row in assignments} - matched_assignments
        ),
    }
