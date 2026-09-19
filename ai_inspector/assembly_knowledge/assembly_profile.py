"""Adapter from Assembly Knowledge Packages to the legacy Assembly-tab profile."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping


def _humanize(value: Any) -> str:
    text = Path(str(value or "")).stem
    text = re.sub(r"^SWPR[-_ ]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[A-Za-z0-9 -]+?[_-](?=[A-Z][a-z])", "", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _assembly_name(product_id: str, root: Mapping[str, Any]) -> str:
    properties = root.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    custom = properties.get("customProperties")
    custom = custom if isinstance(custom, Mapping) else {}
    for value in (
        properties.get("description"),
        custom.get("Description"),
        custom.get("Title"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    label = re.sub(r"[-_]+", " ", product_id).strip().title()
    return label if label.lower().endswith("assembly") else f"{label} Assembly"


def _first_occurrence_colors(
    visual_manifest: Mapping[str, Any],
) -> Dict[str, str]:
    colors: Dict[str, str] = {}
    views = visual_manifest.get("views")
    if not isinstance(views, list):
        return colors
    for view in views:
        if not isinstance(view, Mapping):
            continue
        legend = view.get("colorLegend")
        if not isinstance(legend, Mapping):
            continue
        for color, occurrence_id in legend.items():
            if (
                isinstance(color, str)
                and isinstance(occurrence_id, str)
                and occurrence_id not in colors
            ):
                colors[occurrence_id] = color.upper()
    return colors


def build_legacy_assembly_profile(
    documents: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Build the in-memory shape consumed by the existing Assembly tab.

    The package documents remain authoritative. This adapter only translates
    occurrence, mate, and visual metadata for the established viewer APIs.
    """
    package = documents["package.json"]
    product_structure = documents["product_structure.json"]
    interface_graph = documents["interface_graph.json"]
    visual_manifest = documents["visual_manifest.json"]

    product_id = str(package["productId"])
    occurrences = product_structure.get("occurrences")
    occurrences = occurrences if isinstance(occurrences, list) else []
    occurrence_by_id = {
        str(item.get("occurrenceId")): item
        for item in occurrences
        if isinstance(item, Mapping) and item.get("occurrenceId")
    }
    root_id = product_structure.get("rootOccurrenceId")
    root = occurrence_by_id.get(str(root_id), {})

    components = []
    part_data_cache: Dict[str, Dict[str, Any]] = {}
    occurrence_colors = _first_occurrence_colors(visual_manifest)
    part_colors: Dict[str, str] = {}
    unique_part_paths = set()
    subassembly_count = 0

    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            continue
        occurrence_id = str(occurrence.get("occurrenceId") or "")
        if occurrence_id == str(root_id):
            continue
        kind = str(occurrence.get("kind") or "")
        if kind in {"assembly", "subassembly"}:
            subassembly_count += 1
        source_path = str(occurrence.get("sourcePath") or "")
        props = occurrence.get("properties")
        props = props if isinstance(props, Mapping) else {}
        referenced_file = str(props.get("referencedFileName") or source_path)
        part_key = referenced_file or source_path or occurrence_id
        part_number = Path(part_key).stem
        description = _humanize(part_key) or str(occurrence.get("name") or part_number)

        if kind == "part":
            unique_part_paths.add(part_key.lower())
            if part_key not in part_data_cache:
                part_data_cache[part_key] = {
                    "identity": {
                        "partNumber": part_number,
                        "description": description,
                        "descriptionSource": "cad_filename",
                        "customProperties": {
                            "PartNo": part_number,
                            "Description": description,
                        },
                    }
                }
            color = occurrence_colors.get(occurrence_id)
            if color and part_key not in part_colors:
                part_colors[part_key] = color

        components.append(
            {
                "name": str(occurrence.get("name") or occurrence_id),
                "occurrenceId": occurrence_id,
                "sourceOccurrenceId": occurrence_id,
                "parentOccurrenceId": occurrence.get("parentOccurrenceId"),
                "itemId": occurrence.get("itemId"),
                "type": "Assembly" if kind in {"assembly", "subassembly"} else "Part",
                "kind": kind,
                "level": occurrence.get("level"),
                "configuration": occurrence.get("configuration"),
                "referencedFileName": referenced_file,
                "partDataKey": part_key,
                "transform": occurrence.get("transform") or {},
                "suppressed": bool(
                    (occurrence.get("state") or {}).get("suppressed", False)
                ),
                "sourceHash": occurrence.get("sourceHash"),
                "properties": dict(props),
            }
        )

    mates = []
    mate_relationships = []
    mate_type_counts: Counter[str] = Counter()
    for mate in interface_graph.get("mates") or []:
        if not isinstance(mate, Mapping):
            continue
        refs = [
            str(value)
            for value in mate.get("occurrenceRefs") or []
            if str(value)
        ]
        names = [
            str(occurrence_by_id.get(ref, {}).get("name") or ref)
            for ref in refs
        ]
        mate_type = str(mate.get("type") or "Unknown")
        mate_type_counts[mate_type] += 1
        entities = mate.get("entities")
        entities = entities if isinstance(entities, list) else []

        def legacy_entity(index: int) -> Dict[str, Any]:
            source = (
                entities[index]
                if index < len(entities) and isinstance(entities[index], Mapping)
                else {}
            )
            return {
                "componentName": names[index] if index < len(names) else "",
                "entityType": source.get("entityType"),
                "geometryType": source.get("geometryType"),
                "point": source.get("point") or [],
                "direction": source.get("direction") or [],
                "radius": source.get("radius"),
            }

        legacy_mate = {
            "mateId": mate.get("mateId"),
            "name": mate.get("displayName") or mate.get("mateId"),
            "type": mate_type,
            "alignment": mate.get("alignment"),
            "distance": mate.get("distance"),
            "angle": mate.get("angle"),
            "suppressed": bool(mate.get("suppressed", False)),
            "entity1": legacy_entity(0),
            "entity2": legacy_entity(1),
            "sourceOccurrenceIds": refs,
        }
        mates.append(legacy_mate)
        mate_relationships.append(
            {
                "mateId": mate.get("mateId"),
                "mateName": mate.get("displayName") or mate.get("mateId"),
                "mateType": mate_type,
                "parts": names,
            }
        )

    name = _assembly_name(product_id, root)
    return {
        "fileName": str(root.get("sourcePath") or f"{product_id}.SLDASM"),
        "identity": {
            "assemblyNumber": product_id,
            "description": name,
            "revision": package.get("sourceRevision"),
            "customProperties": {
                "PartNo": product_id,
                "Description": name,
            },
        },
        "statistics": {
            "totalComponents": len(components),
            "uniquePartCount": len(unique_part_paths),
            "subAssemblyCount": subassembly_count,
            "totalMates": len(mates),
            "resolvedCount": sum(
                1
                for occurrence in occurrences
                if isinstance(occurrence, Mapping)
                and bool((occurrence.get("state") or {}).get("resolved", False))
            ),
            "lightweightCount": sum(
                1
                for occurrence in occurrences
                if isinstance(occurrence, Mapping)
                and bool((occurrence.get("state") or {}).get("lightweight", False))
            ),
            "suppressedCount": sum(
                1
                for occurrence in occurrences
                if isinstance(occurrence, Mapping)
                and bool((occurrence.get("state") or {}).get("suppressed", False))
            ),
            "mateTypeCounts": dict(sorted(mate_type_counts.items())),
        },
        "components": components,
        "mates": mates,
        "mateRelationships": mate_relationships,
        "explodeSteps": [],
        "assemblyFeatures": [],
        "partColorMapping": part_colors,
        "partDataCache": part_data_cache,
        "assemblyKnowledge": {
            "packageId": package.get("packageId"),
            "packageRevision": package.get("packageRevision"),
            "sourceRevision": package.get("sourceRevision"),
            "readiness": package.get("readiness"),
            "productionEligible": package.get("productionEligible"),
        },
    }
