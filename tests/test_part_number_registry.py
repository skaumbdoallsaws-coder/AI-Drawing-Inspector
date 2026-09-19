from __future__ import annotations

import pytest

from ai_inspector.parts_manual.catalog import build_occurrence_catalog
from ai_inspector.parts_manual.part_numbers import (
    PartNumberRegistryError,
    apply_part_number_registry,
    registered_part_numbers,
    validate_part_number_registry,
)


SOURCE_HASH = "1" * 64


def _registry(part_number: str = "1030036") -> dict:
    return {
        "schemaVersion": 1,
        "assignments": [
            {
                "partNumber": part_number,
                "description": "Bell",
                "productId": "tricycle",
                "sourcePath": "SWPR-Tricycle_Bell.SLDPRT",
                "sourceHash": SOURCE_HASH,
                "sourceItemIds": ["item-bell"],
                "libraryEntryStatus": "number_assigned",
            }
        ],
    }


def _profile(*, existing_part_number: str | None = None) -> dict:
    properties = {}
    if existing_part_number:
        properties["PartNo"] = existing_part_number
    return {
        "assemblyKnowledge": {"sourceRevision": "a" * 64},
        "components": [
            {
                "name": "SWPR-Tricycle_Bell-1",
                "type": "Part",
                "kind": "part",
                "itemId": "item-bell",
                "sourceHash": SOURCE_HASH,
                "partDataKey": "SWPR-Tricycle_Bell.SLDPRT",
                "referencedFileName": "SWPR-Tricycle_Bell.SLDPRT",
                "properties": properties,
            }
        ],
        "partDataCache": {
            "SWPR-Tricycle_Bell.SLDPRT": {
                "identity": {
                    "partNumber": existing_part_number or "SWPR-Tricycle_Bell",
                    "description": "Bell",
                    "customProperties": {
                        "PartNo": existing_part_number or "SWPR-Tricycle_Bell",
                        "Description": "Bell",
                    },
                }
            }
        },
    }


def test_registry_assignment_becomes_the_engineering_bom_identity() -> None:
    profile = _profile()
    report = apply_part_number_registry(profile, _registry(), product_id="tricycle")
    catalog = build_occurrence_catalog("tricycle", profile)
    part = catalog["occurrences"][0]

    assert report["appliedPartNumbers"] == ["1030036"]
    assert report["unmatchedPartNumbers"] == []
    assert part["engineeringPartNumber"] == "1030036"
    assert part["displayPartNumber"] == "1030036"
    assert part["partNumberSource"] == "component_property"
    assert catalog["sourceRevision"] == "a" * 64
    assert profile["partNumberRegistryRevision"]


def test_registry_never_overwrites_an_existing_engineering_number() -> None:
    profile = _profile(existing_part_number="7654321")
    report = apply_part_number_registry(profile, _registry(), product_id="tricycle")
    catalog = build_occurrence_catalog("tricycle", profile)
    part = catalog["occurrences"][0]

    assert report["appliedPartNumbers"] == []
    assert report["preservedPartNumbers"] == ["7654321"]
    assert part["engineeringPartNumber"] == "7654321"


def test_configured_parts_compare_against_pre_application_cache_snapshot() -> None:
    profile = {
        "components": [
            {
                "name": "Shaft-1",
                "type": "Part",
                "itemId": "item-shaft-short",
                "referencedFileName": "Shaft.SLDPRT",
                "partDataKey": "Shaft.SLDPRT",
                "activeConfiguration": "Short",
            },
            {
                "name": "Shaft-2",
                "type": "Part",
                "itemId": "item-shaft-long",
                "referencedFileName": "Shaft.SLDPRT",
                "partDataKey": "Shaft.SLDPRT",
                "activeConfiguration": "Long",
            },
        ],
        "partDataCache": {"Shaft.SLDPRT": {"identity": {}}},
    }
    registry = {
        "schemaVersion": 1,
        "assignments": [
            {
                "partNumber": "1030201",
                "description": "Shaft - Short",
                "productId": "configured-product",
                "sourcePath": "Shaft.SLDPRT",
                "sourceHash": "1" * 64,
                "sourceItemIds": ["item-shaft-short"],
                "libraryEntryStatus": "number_assigned",
            },
            {
                "partNumber": "1030202",
                "description": "Shaft - Long",
                "productId": "configured-product",
                "sourcePath": "Shaft.SLDPRT",
                "sourceHash": "2" * 64,
                "sourceItemIds": ["item-shaft-long"],
                "libraryEntryStatus": "number_assigned",
            },
        ],
    }

    report = apply_part_number_registry(
        profile, registry, product_id="configured-product"
    )

    assert report["appliedPartNumbers"] == ["1030201", "1030202"]
    assert report["preservedPartNumbers"] == []
    assert [
        row["properties"]["PartNo"] for row in profile["components"]
    ] == ["1030201", "1030202"]


def test_registry_reserves_numbers_and_rejects_conflicting_sources() -> None:
    registry = _registry()
    assert registered_part_numbers(registry) == {"1030036"}

    registry["assignments"].append(
        {
            **registry["assignments"][0],
            "productId": "another-product",
            "sourceHash": "2" * 64,
            "sourcePath": "Another.SLDPRT",
        }
    )
    with pytest.raises(PartNumberRegistryError, match="more than one source"):
        validate_part_number_registry(registry)
