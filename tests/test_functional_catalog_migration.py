from __future__ import annotations

import json
from pathlib import Path

from ai_inspector.assembly_knowledge.functional_catalog import (
    adapt_functional_catalog,
    catalog_inventory,
    catalog_parity_report,
    functional_catalog_migration_matrix,
    lookup_functional_terms,
    reconstruct_functional_catalog,
)
from ai_inspector.assembly_knowledge.validation import (
    validate_assembly_knowledge_package,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = (
    ROOT / "ai_inspector" / "product_intelligence" / "catalogs" / "100001.json"
)


def _graph() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="ascii"))


def test_catalog_inventory_covers_every_behavior_bearing_collection() -> None:
    assert catalog_inventory(_graph()) == {
        "componentTypes": 8,
        "componentInstances": 43,
        "interfaces": 40,
        "externalEntities": 2,
        "sourceEvidence": 10,
        "functionalRoles": 33,
        "functionalFeatures": 35,
        "semanticTags": 109,
        "aliases": 116,
        "componentMobilityValues": 8,
        "externalPresenceValues": 2,
    }


def test_migration_matrix_is_lossless_and_has_no_unmapped_source_fields() -> None:
    matrix = functional_catalog_migration_matrix(_graph())
    assert matrix["unmappedSourceFields"] == []
    assert matrix["freeFormNarrativeMappings"] == []
    assert {item["sourceField"] for item in matrix["mappings"]} == set(_graph())
    assert all(item["lossPolicy"] == "lossless_structured" for item in matrix["mappings"])


def test_catalog_round_trip_and_all_runtime_contexts_have_exact_parity() -> None:
    source = _graph()
    documents = adapt_functional_catalog(source, repo_root=ROOT)
    reconstructed = reconstruct_functional_catalog(documents)
    report = catalog_parity_report(source, reconstructed)

    assert reconstructed == source
    assert report["exactGraphParity"] is True
    assert report["inventoryParity"] is True
    assert report["contextParity"] is True
    assert len(report["contextCases"]) == 8
    assert all(item["passed"] for item in report["contextCases"])
    assert report["passed"] is True
    assert not [
        item
        for item in validate_assembly_knowledge_package(documents)
        if item["severity"] == "error"
    ]


def test_every_alias_and_semantic_tag_remains_searchable_after_round_trip() -> None:
    source = _graph()
    documents = adapt_functional_catalog(source, repo_root=ROOT)
    reconstructed = reconstruct_functional_catalog(documents)

    checked_aliases = 0
    checked_tags = 0
    for collection, identifier_field in (
        ("component_types", "part_number"),
        ("external_entities", "entity_id"),
    ):
        for entity in source[collection]:
            entity_ref = entity[identifier_field]
            for feature in entity.get("functional_features", []):
                feature_ref = feature["feature_ref"]
                for alias in feature.get("aliases", []):
                    checked_aliases += 1
                    matches = lookup_functional_terms(reconstructed, alias)
                    assert any(
                        item["entityRef"] == entity_ref
                        and item["featureRef"] == feature_ref
                        for item in matches
                    ), (entity_ref, feature_ref, alias, matches)
                for tag in feature.get("semantic_tags", []):
                    checked_tags += 1
                    matches = lookup_functional_terms(
                        reconstructed, str(tag).replace("_", " ")
                    )
                    assert any(
                        item["entityRef"] == entity_ref
                        and item["featureRef"] == feature_ref
                        for item in matches
                    ), (entity_ref, feature_ref, tag, matches)

    assert checked_aliases == 116
    assert checked_tags == 109

