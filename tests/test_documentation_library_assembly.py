from __future__ import annotations

import copy
from pathlib import Path

from ai_inspector.assembly_knowledge.library_registry import (
    load_documentation_library_sources,
)
from ai_inspector.parts_manual.catalog import (
    assembly_source_revision,
    build_occurrence_catalog,
)
from ai_inspector.parts_manual.part_numbers import (
    apply_part_number_registry,
    load_part_number_registry,
)
from ai_inspector.parts_manual.planner import compile_manual_structure_proposal


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source() -> dict:
    return load_documentation_library_sources(PROJECT_ROOT)["MMLE-50D"]


def test_mmle_is_a_curated_component_aware_documentation_assembly() -> None:
    source = _source()
    profile = source["profile"]
    part_components = [row for row in profile["components"] if row["type"] == "Part"]

    assert source["source"] == "industrial_asset_library"
    assert source["assets"]["model"].stat().st_size > 1_000_000
    assert profile["identity"]["assemblyNumber"] == "MMLE-50D"
    assert profile["identity"]["description"] == "MMLE-50D Electric Mobile Lift"
    assert profile["identity"]["revision"] == "A"
    assert len(part_components) == 206
    assert len({row["itemId"] for row in part_components}) == 70

    shaft_tubes = [
        row
        for row in part_components
        if row["referencedFileName"].endswith("SHAFT TUBE.SLDPRT")
    ]
    by_configuration = {
        row["activeConfiguration"]: row["itemId"] for row in shaft_tubes
    }
    assert len(by_configuration) == 6
    assert len(set(by_configuration.values())) == 6


def test_mmle_authored_service_plan_is_complete_and_conflict_free() -> None:
    profile = _source()["profile"]
    catalog = build_occurrence_catalog("MMLE-50D", profile)
    plan = {
        "schemaVersion": 1,
        "assemblyNumber": "MMLE-50D",
        "sourceRevision": catalog["sourceRevision"],
        "title": "MMLE-50D Illustrated Parts Manual",
        "sections": [],
        "itemAssignments": [],
        "exclusions": [],
    }

    proposal = compile_manual_structure_proposal(
        catalog=catalog,
        plan=plan,
        plan_revision="f" * 64,
    )

    assert proposal["strategy"] == "library_manual_profile"
    assert proposal["summary"] == {
        "candidateCount": 10,
        "readyCount": 10,
        "conflictCount": 0,
        "alreadyAuthoredCount": 0,
        "unassignedCount": 0,
        "eligibleOccurrenceCount": 206,
        "coveredOccurrenceCount": 206,
        "coveragePercent": 100.0,
    }
    assert [row["name"] for row in proposal["candidates"]] == [
        "Lift Platform Assembly",
        "Lift Mechanism Assembly",
        "Hydraulic Cylinder Assembly",
        "Hydraulic Power Pack Assembly",
        "Right Swivel Caster and Brake Assembly",
        "Left Swivel Caster and Brake Assembly",
        "Rigid Caster Assembly",
        "Caster Support Structure",
        "Battery and Control Assembly",
        "Base Frame and Covers Assembly",
    ]
    memberships = [set(row["occurrenceIds"]) for row in proposal["candidates"]]
    assert sum(len(value) for value in memberships) == 206
    assert not any(
        memberships[left] & memberships[right]
        for left in range(len(memberships))
        for right in range(left + 1, len(memberships))
    )


def test_mmle_registry_assigns_every_configured_definition_a_distinct_number() -> None:
    profile = _source()["profile"]
    registry = load_part_number_registry(
        PROJECT_ROOT / "400S_Sorted_Library" / "part_number_registry.json"
    )
    report = apply_part_number_registry(profile, registry, product_id="MMLE-50D")
    catalog = build_occurrence_catalog("MMLE-50D", profile)
    parts = [
        row
        for row in catalog["occurrences"]
        if row["kind"] == "part" and not row["suppressed"]
    ]

    assert report["assignmentCount"] == 70
    assert len(report["appliedPartNumbers"]) == 70
    assert report["preservedPartNumbers"] == []
    assert report["unmatchedPartNumbers"] == []
    assert all(row["engineeringPartNumber"] for row in parts)
    assert len({row["definitionId"] for row in parts}) == 70
    assert len({row["engineeringPartNumber"] for row in parts}) == 70

    shaft_descriptions = {
        row["configuration"]: row["description"]
        for row in parts
        if row["referencedFileName"].endswith("SHAFT TUBE.SLDPRT")
    }
    assert shaft_descriptions["10"] == "Shaft Tube - 10"
    assert shaft_descriptions["205MM"] == "Shaft Tube - 205MM"


def test_manual_planning_changes_assembly_source_revision() -> None:
    profile = _source()["profile"]
    changed = copy.deepcopy(profile)
    changed["manualPlanning"]["groups"][0]["name"] = "Changed Platform"

    assert assembly_source_revision("MMLE-50D", profile) != assembly_source_revision(
        "MMLE-50D", changed
    )
