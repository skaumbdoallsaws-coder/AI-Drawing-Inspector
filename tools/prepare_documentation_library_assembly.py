"""Assign durable service-part identities to a curated Documentation assembly.

This is an explicit preparation step, not runtime inference.  One engineering
part number is assigned per stable CAD definition (source file + active
configuration), while repeated occurrences retain one BOM identity and quantity.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_inspector.assembly_knowledge.library_registry import (  # noqa: E402
    load_documentation_library_sources,
)
from ai_inspector.parts_manual.catalog import build_occurrence_catalog  # noqa: E402
from ai_inspector.parts_manual.part_numbers import (  # noqa: E402
    PART_NUMBER_REGISTRY_FILENAME,
    load_part_number_registry,
    validate_part_number_registry,
)


_SEVEN_DIGIT_NUMBER = re.compile(r"(?<!\d)(\d{7})(?!\d)")
_ACRONYMS = {
    "a02": "A02",
    "a2": "A2",
    "bdi": "BDI",
    "mmle": "MMLE",
    "ptn": "PTN",
    "sw": "SW",
}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _reserved_part_numbers(library_root: Path, registry: Mapping[str, Any]) -> set[str]:
    reserved = {
        str(row.get("partNumber") or "")
        for row in registry.get("assignments") or []
        if _SEVEN_DIGIT_NUMBER.fullmatch(str(row.get("partNumber") or ""))
    }
    if not library_root.is_dir():
        return reserved
    for path in library_root.rglob("*"):
        reserved.update(_SEVEN_DIGIT_NUMBER.findall(path.name))
        if path.is_file() and path.suffix.casefold() == ".json":
            try:
                reserved.update(
                    _SEVEN_DIGIT_NUMBER.findall(
                        path.read_text(encoding="utf-8-sig", errors="ignore")
                    )
                )
            except OSError:
                continue
    return reserved


def _next_numbers(
    reserved: set[str],
    *,
    prefix: str,
    count: int,
) -> Iterable[str]:
    if not prefix.isdigit() or len(prefix) >= 7:
        raise ValueError("prefix must contain 1 to 6 digits")
    width = 7 - len(prefix)
    matching = sorted(
        int(value)
        for value in reserved
        if value.startswith(prefix) and value.isdigit() and len(value) == 7
    )
    candidate = (matching[-1] + 1) if matching else int(prefix + "0" * width) + 1
    upper = int(prefix + "9" * width)
    emitted = 0
    while emitted < count and candidate <= upper:
        value = str(candidate).zfill(7)
        candidate += 1
        if value in reserved:
            continue
        reserved.add(value)
        emitted += 1
        yield value
    if emitted != count:
        raise ValueError(f"No room for {count} assignments in the {prefix} series")


def _title_description(value: str) -> str:
    words = []
    for raw_word in " ".join(str(value or "").replace("_", " ").split()).split(" "):
        key = raw_word.casefold()
        if key in _ACRONYMS:
            words.append(_ACRONYMS[key])
        elif any(character.isdigit() for character in raw_word):
            words.append(raw_word.upper())
        else:
            words.append(raw_word.capitalize())
    return " ".join(words).strip() or "Component"


def build_assignments(
    *,
    assembly_number: str,
    profile: Mapping[str, Any],
    registry: Mapping[str, Any],
    library_root: Path,
    prefix: str,
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    catalog = build_occurrence_catalog(assembly_number, profile)
    active_parts = [
        row
        for row in catalog.get("occurrences") or []
        if row.get("kind") == "part" and not row.get("suppressed")
    ]
    by_definition: Dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    definitions_by_path: Dict[str, set[str]] = defaultdict(set)
    for row in active_parts:
        definition_id = str(row.get("definitionId") or "")
        source_path = str(row.get("referencedFileName") or "")
        if definition_id and source_path:
            by_definition[definition_id].append(row)
            definitions_by_path[source_path.casefold()].add(definition_id)

    normalized = validate_part_number_registry(registry)
    existing_rows = list(normalized["assignments"])
    existing_item_ids = {
        str(item_id): row
        for row in existing_rows
        if str(row.get("productId") or "").casefold() == assembly_number.casefold()
        for item_id in row.get("sourceItemIds") or []
    }
    pending = [
        definition_id
        for definition_id in sorted(by_definition)
        if definition_id not in existing_item_ids
        and not any(
            str(row.get("engineeringPartNumber") or "").strip()
            for row in by_definition[definition_id]
        )
    ]
    reserved = _reserved_part_numbers(library_root, normalized)
    assigned_numbers = iter(
        _next_numbers(reserved, prefix=prefix, count=len(pending))
    )
    new_rows: list[Dict[str, Any]] = []
    for definition_id in pending:
        rows = by_definition[definition_id]
        representative = rows[0]
        source_path = str(representative.get("referencedFileName") or "")
        description = Counter(
            str(row.get("description") or "Component") for row in rows
        ).most_common(1)[0][0]
        description = _title_description(description)
        configuration = str(representative.get("configuration") or "Default")
        if len(definitions_by_path[source_path.casefold()]) > 1:
            description = f"{description} - {configuration}"
        part_number = next(assigned_numbers)
        new_rows.append(
            {
                "partNumber": part_number,
                "description": description,
                "productId": assembly_number,
                "sourcePath": source_path,
                "sourceHash": _canonical_sha256(
                    {
                        "assemblyNumber": assembly_number,
                        "configuration": configuration,
                        "definitionId": definition_id,
                        "sourcePath": source_path.replace("\\", "/").casefold(),
                    }
                ),
                "sourceItemIds": [definition_id],
                "libraryEntryStatus": "number_assigned",
                "assignedAt": date.today().isoformat(),
                "assignedBy": "InspectorPro",
                "assignmentReason": (
                    "No trusted engineering identity existed for this CAD definition."
                ),
            }
        )

    report = {
        "assemblyNumber": assembly_number,
        "activeOccurrenceCount": len(active_parts),
        "definitionCount": len(by_definition),
        "existingAssignmentCount": len(by_definition) - len(pending),
        "newAssignmentCount": len(new_rows),
        "firstAssignedPartNumber": new_rows[0]["partNumber"] if new_rows else None,
        "lastAssignedPartNumber": new_rows[-1]["partNumber"] if new_rows else None,
    }
    return existing_rows + new_rows, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", required=True)
    parser.add_argument("--prefix", default="1030")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    sources = load_documentation_library_sources(PROJECT_ROOT)
    if args.assembly not in sources:
        parser.error(f"assembly {args.assembly!r} is not in the Documentation registry")
    registry_path = PROJECT_ROOT / "400S_Sorted_Library" / PART_NUMBER_REGISTRY_FILENAME
    registry = load_part_number_registry(registry_path)
    assignments, report = build_assignments(
        assembly_number=args.assembly,
        profile=sources[args.assembly]["profile"],
        registry=registry,
        library_root=registry_path.parent,
        prefix=args.prefix,
    )
    updated = validate_part_number_registry(
        {"schemaVersion": 1, "assignments": assignments}
    )
    if args.apply and report["newAssignmentCount"]:
        registry_path.write_text(
            json.dumps(updated, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({**report, "applied": bool(args.apply)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
