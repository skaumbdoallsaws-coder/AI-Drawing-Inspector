"""Canonical assembly occurrence catalog for illustrated parts manuals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ai_inspector.assembly_knowledge.identity import occurrence_id
from ai_inspector.assembly_knowledge.manifest import stable_id


def _cad_identity_token(value: Any) -> str:
    stem = Path(str(value or "").strip()).stem
    stem = re.sub(r"-\d+$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem.casefold())


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def assembly_source_revision(
    assembly_number: str,
    assembly_data: Mapping[str, Any],
) -> str:
    """Return the authoritative package revision or a deterministic legacy hash."""
    knowledge = assembly_data.get("assemblyKnowledge")
    if isinstance(knowledge, Mapping):
        source_revision = str(knowledge.get("sourceRevision") or "").strip().lower()
        if len(source_revision) == 64 and all(ch in "0123456789abcdef" for ch in source_revision):
            return source_revision

    identity = assembly_data.get("identity")
    components = assembly_data.get("components")
    part_cache = assembly_data.get("partDataCache")
    manual_planning = assembly_data.get("manualPlanning")
    return _canonical_sha256(
        {
            "assemblyNumber": str(assembly_number),
            "identity": identity if isinstance(identity, Mapping) else {},
            "components": components if isinstance(components, list) else [],
            "partDataCache": part_cache if isinstance(part_cache, Mapping) else {},
            "manualPlanning": (
                manual_planning if isinstance(manual_planning, Mapping) else {}
            ),
        }
    )


def _legend_index(part_color_legend: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for row in part_color_legend:
        old_key = str(row.get("old_key") or "").strip().lower()
        if old_key:
            result[old_key] = row
            result[Path(old_key).stem.lower()] = row
    return result


def _humanize_cad_name(value: str) -> str:
    stem = Path(str(value or "")).stem
    stem = re.sub(r"_(?:am|tfm)$", "", stem, flags=re.IGNORECASE)
    if "_" in stem:
        stem = stem.rsplit("_", 1)[-1]
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    stem = " ".join(stem.split()).strip()
    # CAD filenames commonly accumulate short numeric revision/copy suffixes
    # (for example Grip2 or Fork2). Keep the raw identity separately, but do
    # not publish that implementation suffix as the customer description.
    suffix = re.fullmatch(r"(.{3,}?)(\d{1,2})", stem)
    if suffix and any(character.isalpha() for character in suffix.group(1)):
        stem = suffix.group(1).rstrip()
    return stem or "Component"


def _first_identity_value(
    candidates: Sequence[tuple[Any, str]],
) -> tuple[str, str]:
    for value, source in candidates:
        text = str(value or "").strip()
        if text:
            return text, source
    return "", "unknown"


def _part_identity(
    component: Mapping[str, Any],
    *,
    part_data_cache: Mapping[str, Any],
    legend_by_key: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    part_key = str(
        component.get("partDataKey")
        or component.get("referencedFileName")
        or ""
    ).strip()
    cache_row = part_data_cache.get(part_key)
    if not isinstance(cache_row, Mapping):
        cache_row = part_data_cache.get(part_key.lower())
    cache_row = cache_row if isinstance(cache_row, Mapping) else {}
    identity = cache_row.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    custom = identity.get("customProperties")
    custom = custom if isinstance(custom, Mapping) else {}
    properties = component.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    property_custom = properties.get("customProperties")
    property_custom = property_custom if isinstance(property_custom, Mapping) else {}
    legend = legend_by_key.get(part_key.lower()) or legend_by_key.get(Path(part_key).stem.lower()) or {}

    part_number, part_number_source = _first_identity_value(
        (
            (properties.get("PartNo"), "component_property"),
            (properties.get("PART_NUMBER"), "component_property"),
            (properties.get("ID"), "component_property"),
            (property_custom.get("PartNo"), "component_property"),
            (property_custom.get("PART_NUMBER"), "component_property"),
            (custom.get("PartNo"), "cad_custom_property"),
            (custom.get("PART_NUMBER"), "cad_custom_property"),
            (identity.get("partNumber"), "assembly_knowledge"),
            (legend.get("part_number"), "library_metadata"),
            (Path(part_key).stem, "cad_filename"),
            (component.get("name"), "cad_occurrence_name"),
        )
    )
    description, description_source = _first_identity_value(
        (
            (properties.get("DESCRIPTION"), "component_property"),
            (properties.get("Description"), "component_property"),
            (property_custom.get("DESCRIPTION"), "component_property"),
            (property_custom.get("Description"), "component_property"),
            (custom.get("DESCRIPTION"), "cad_custom_property"),
            (custom.get("Description"), "cad_custom_property"),
            (identity.get("description"), "assembly_knowledge"),
            (legend.get("description"), "library_metadata"),
        )
    )
    if not description:
        description = _humanize_cad_name(part_key or str(component.get("name") or ""))
        description_source = "cad_filename"
    candidate_token = _cad_identity_token(part_number)
    cad_identity_tokens = {
        _cad_identity_token(part_key),
        _cad_identity_token(component.get("name")),
        _cad_identity_token(component.get("referencedFileName")),
    }
    if (
        part_number_source in {"component_property", "cad_custom_property"}
        and candidate_token
        and candidate_token in cad_identity_tokens
    ):
        part_number_source = "cad_identity_fallback"
    raw_cad_description_tokens = {
        _cad_identity_token(Path(value).stem.rsplit("_", 1)[-1])
        for value in (
            part_key,
            component.get("referencedFileName"),
            component.get("name"),
        )
        if value
    }
    if (
        part_number_source == "cad_identity_fallback"
        and description_source in {"component_property", "cad_custom_property"}
        and _cad_identity_token(description) in raw_cad_description_tokens
    ):
        normalized_description = _humanize_cad_name(description)
        if normalized_description != description:
            description = normalized_description
            description_source = f"{description_source}_normalized"
    engineering_part_number = (
        part_number
        if part_number_source
        not in {"cad_filename", "cad_occurrence_name", "cad_identity_fallback", "unknown"}
        else None
    )
    return {
        "partKey": part_key,
        "partNumber": part_number or "Unknown",
        "engineeringPartNumber": engineering_part_number,
        "displayPartNumber": engineering_part_number or "Not specified",
        "partNumberSource": part_number_source,
        "description": description,
        "descriptionSource": description_source,
        "internalComponentName": str(component.get("name") or "").strip(),
    }


def build_occurrence_catalog(
    assembly_number: str,
    assembly_data: Mapping[str, Any],
    part_color_legend: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Normalize legacy and Assembly Knowledge components into one identity model."""
    source_revision = assembly_source_revision(assembly_number, assembly_data)
    raw_components = assembly_data.get("components")
    raw_components = raw_components if isinstance(raw_components, list) else []
    part_data_cache = assembly_data.get("partDataCache")
    part_data_cache = part_data_cache if isinstance(part_data_cache, Mapping) else {}
    legend_by_key = _legend_index(part_color_legend)

    root_occurrence_id = occurrence_id(
        root_source_revision=source_revision,
        configuration="Default",
        occurrence_path=str(assembly_number),
    )
    rows: List[Dict[str, Any]] = []
    occurrence_by_name: Dict[str, str] = {}
    seen_ids = set()

    for index, raw in enumerate(raw_components):
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or f"Component-{index + 1}").strip()
        configuration = str(
            raw.get("configuration")
            or raw.get("activeConfiguration")
            or "Default"
        ).strip() or "Default"
        source_occurrence_id = str(
            raw.get("sourceOccurrenceId")
            or raw.get("occurrenceId")
            or ""
        ).strip()
        canonical_occurrence_id = source_occurrence_id or occurrence_id(
            root_source_revision=source_revision,
            configuration=configuration,
            occurrence_path=name,
        )
        if canonical_occurrence_id in seen_ids:
            canonical_occurrence_id = occurrence_id(
                root_source_revision=source_revision,
                configuration=configuration,
                occurrence_path=f"{name}~{index + 1}",
            )
        seen_ids.add(canonical_occurrence_id)
        occurrence_by_name[name] = canonical_occurrence_id

        identity = _part_identity(
            raw,
            part_data_cache=part_data_cache,
            legend_by_key=legend_by_key,
        )
        raw_kind = str(raw.get("kind") or raw.get("type") or "part").strip().lower()
        kind = "subassembly" if raw_kind in {"assembly", "subassembly"} else "part"
        supplied_definition_id = str(raw.get("itemId") or raw.get("sourceItemId") or "").strip()
        definition_id = supplied_definition_id or stable_id(
            "item",
            {
                "configuration": configuration,
                "partKey": identity["partKey"].lower(),
                "partNumber": identity["partNumber"],
            },
            digest_length=24,
        )
        transform = raw.get("transform")
        transform = transform if isinstance(transform, Mapping) else {}
        translation = raw.get("translation")
        if not isinstance(translation, list):
            translation = transform.get("translation")
        state = raw.get("state")
        state = state if isinstance(state, Mapping) else {}
        rows.append(
            {
                "occurrenceId": canonical_occurrence_id,
                "sourceOccurrenceId": source_occurrence_id or None,
                "definitionId": definition_id,
                "name": name,
                "kind": kind,
                "level": int(
                    raw.get("level")
                    if isinstance(raw.get("level"), (int, float))
                    and not isinstance(raw.get("level"), bool)
                    else 1
                ),
                "parentName": str(raw.get("parentName") or "").strip() or None,
                "parentOccurrenceId": str(raw.get("parentOccurrenceId") or "").strip() or None,
                "partDataKey": identity["partKey"],
                "referencedFileName": str(
                    raw.get("referencedFileName") or identity["partKey"]
                ).strip(),
                "partNumber": identity["partNumber"],
                "engineeringPartNumber": identity["engineeringPartNumber"],
                "displayPartNumber": identity["displayPartNumber"],
                "partNumberSource": identity["partNumberSource"],
                "description": identity["description"],
                "descriptionSource": identity["descriptionSource"],
                "internalComponentName": identity["internalComponentName"],
                "configuration": configuration,
                "translation": list(translation) if isinstance(translation, list) else None,
                "rotation": transform.get("rotation"),
                "scale": transform.get("scale", 1.0),
                "suppressed": bool(
                    raw.get("isSuppressed")
                    or raw.get("suppressed")
                    or state.get("suppressed")
                ),
                "hidden": bool(raw.get("isHidden") or state.get("hidden")),
            }
        )

    for row in rows:
        if not row["parentOccurrenceId"]:
            row["parentOccurrenceId"] = occurrence_by_name.get(
                str(row.get("parentName") or "")
            ) or root_occurrence_id
        row.pop("parentName", None)

    return {
        "assemblyNumber": str(assembly_number),
        "sourceRevision": source_revision,
        "rootOccurrenceId": root_occurrence_id,
        "occurrences": rows,
        "manualPlanning": (
            dict(assembly_data.get("manualPlanning"))
            if isinstance(assembly_data.get("manualPlanning"), Mapping)
            else None
        ),
    }


def build_scoped_bom(
    occurrences: Iterable[Mapping[str, Any]],
    occurrence_ids: Iterable[str],
    *,
    item_assignments: Iterable[Mapping[str, Any]] = (),
) -> List[Dict[str, Any]]:
    """Aggregate selected occurrences by definition without losing traceability."""
    occurrence_by_id = {
        str(row.get("occurrenceId")): row
        for row in occurrences
        if isinstance(row, Mapping) and row.get("occurrenceId")
    }
    selected_ids = list(dict.fromkeys(str(value) for value in occurrence_ids if value))
    unknown = [value for value in selected_ids if value not in occurrence_by_id]
    if unknown:
        raise ValueError("Unknown occurrence IDs: " + ", ".join(unknown[:8]))

    assignment_by_definition = {
        str(row.get("definitionId")): int(row.get("itemNumber"))
        for row in item_assignments
        if isinstance(row, Mapping)
        and row.get("definitionId")
        and isinstance(row.get("itemNumber"), int)
        and int(row.get("itemNumber")) > 0
    }
    grouped: Dict[str, Dict[str, Any]] = {}
    for occurrence_id_value in selected_ids:
        row = occurrence_by_id[occurrence_id_value]
        if row.get("kind") != "part" or row.get("suppressed"):
            continue
        definition_id = str(row.get("definitionId") or "")
        if not definition_id:
            continue
        target = grouped.setdefault(
            definition_id,
            {
                "definitionId": definition_id,
                "partNumber": str(row.get("partNumber") or "Unknown"),
                "engineeringPartNumber": row.get("engineeringPartNumber"),
                "displayPartNumber": str(row.get("displayPartNumber") or "Not specified"),
                "partNumberSource": str(row.get("partNumberSource") or "unknown"),
                "description": str(row.get("description") or ""),
                "descriptionSource": str(row.get("descriptionSource") or "unknown"),
                "configuration": str(row.get("configuration") or "Default"),
                "quantity": 0,
                "occurrenceIds": [],
            },
        )
        target["quantity"] += 1
        target["occurrenceIds"].append(occurrence_id_value)

    ordered = sorted(
        grouped.values(),
        key=lambda row: (
            assignment_by_definition.get(str(row["definitionId"]), 10**9),
            str(row["partNumber"]).lower(),
            str(row["description"]).lower(),
            str(row["definitionId"]),
        ),
    )
    used = set(assignment_by_definition.values())
    next_item = 1
    for row in ordered:
        definition_id = str(row["definitionId"])
        item_number = assignment_by_definition.get(definition_id)
        if item_number is None:
            while next_item in used:
                next_item += 1
            item_number = next_item
            used.add(item_number)
            next_item += 1
        row["item"] = item_number
        row["occurrenceIds"] = sorted(row["occurrenceIds"])
    return sorted(ordered, key=lambda row: int(row["item"]))
