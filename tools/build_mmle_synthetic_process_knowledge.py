"""Build the MMLE-50D synthetic process-evidence package deterministically."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ai_inspector.assembly_knowledge.evidence import EVIDENCE_COMPILER_VERSION
from ai_inspector.assembly_knowledge.manifest import (
    canonical_json_sha256,
    refresh_package_revision,
    sha256_file,
    stable_id,
)
from ai_inspector.assembly_knowledge.repository import AssemblyKnowledgeRepository
from ai_inspector.assembly_knowledge.validation import (
    validate_assembly_knowledge_package,
)


PRODUCT_ID = "mmle-50d-497533f6"
ASSEMBLY_NUMBER = "MMLE-50D"
CONFIGURATION = "Default"
ADAPTER_VERSION = "mmle-synthetic-process-1.1.0"
SOURCE_DIR = Path("docs/process-map/mmle-50d-synthetic")
STRUCTURE_PATH = Path(
    "generated/training/mmle-50d-497533f6/"
    "mmle_50d_497533f6_product_structure.json"
)
REGISTRY_PATH = Path(
    "ai_inspector/assembly_knowledge/documentation_assembly_registry.json"
)
EXTRACT_PATH = Path(
    "generated/industrial_assets/local_library/mobile-lift-mmle-50d/"
    "extracted.json"
)
SOURCE_FILES = {
    "routing": SOURCE_DIR / "assembly-routing.json",
    "stage_details": SOURCE_DIR / "stage-details.json",
    "inspection_plan": SOURCE_DIR / "in-process-inspection-plan.json",
    "test_procedure": SOURCE_DIR / "functional-test-procedure.json",
    "resource_register": SOURCE_DIR / "resource-register.json",
    "assumption_register": SOURCE_DIR / "process-assumptions.json",
    "work_instruction": SOURCE_DIR / "work-instruction-stage-03.json",
}
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class SyntheticProcessKnowledgeError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _source_id(path: Path) -> str:
    return stable_id("source", {"path": path.as_posix()}, digest_length=20)


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    subject_refs: Iterable[str] = (),
) -> dict[str, Any]:
    refs = sorted(set(str(item) for item in subject_refs if item))
    result: dict[str, Any] = {
        "findingId": stable_id(
            "finding",
            {"code": code, "message": message, "subjectRefs": refs},
            digest_length=20,
        ),
        "severity": severity,
        "code": code,
        "message": message,
    }
    if refs:
        result["subjectRefs"] = refs
    return result


def _source_record(root: Path, path: Path, kind: str) -> dict[str, Any]:
    absolute = (root / path).resolve()
    if not absolute.is_file():
        raise SyntheticProcessKnowledgeError(f"Source is missing: {path.as_posix()}")
    return {
        "sourceId": _source_id(path),
        "path": path.as_posix(),
        "sha256": sha256_file(absolute),
        "size": absolute.stat().st_size,
        "kind": kind,
        "available": True,
    }


def _basename(value: Any) -> str:
    return Path(str(value or "").replace("\\", "/")).name.casefold()


def _registry_groups(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    assemblies = registry.get("assemblies")
    assemblies = assemblies if isinstance(assemblies, list) else []
    record = next(
        (
            item
            for item in assemblies
            if isinstance(item, Mapping)
            and str(item.get("assemblyNumber") or "").strip() == ASSEMBLY_NUMBER
        ),
        None,
    )
    if not isinstance(record, Mapping):
        raise SyntheticProcessKnowledgeError("MMLE-50D registry entry was not found.")
    planning = record.get("manualPlanning")
    groups = planning.get("groups") if isinstance(planning, Mapping) else None
    if not isinstance(groups, list) or not groups:
        raise SyntheticProcessKnowledgeError("MMLE-50D functional groups are missing.")
    return [copy.deepcopy(dict(item)) for item in groups if isinstance(item, Mapping)]


def _assign_leaf_groups(
    structure: Mapping[str, Any],
    groups: list[Mapping[str, Any]],
    *,
    fallback_group: str,
) -> dict[str, list[str]]:
    occurrences = [
        item
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping) and item.get("occurrenceId")
    ]
    by_id = {str(item["occurrenceId"]): item for item in occurrences}
    root_ids = [
        str(item["occurrenceId"])
        for item in occurrences
        if item.get("parentOccurrenceId") is None
    ]
    if len(root_ids) != 1:
        raise SyntheticProcessKnowledgeError("Product structure requires one root occurrence.")
    root_id = root_ids[0]
    known_names = {str(item.get("name")) for item in groups}
    if fallback_group not in known_names:
        raise SyntheticProcessKnowledgeError("Routing fallback group is not registered.")

    subassembly_owner: dict[str, str] = {}
    direct_owner: dict[str, str] = {}
    for group in groups:
        name = str(group.get("name") or "").strip()
        for source in group.get("subassemblyReferences", []) or []:
            key = _basename(source)
            previous = subassembly_owner.setdefault(key, name)
            if previous != name:
                raise SyntheticProcessKnowledgeError(
                    f"Subassembly source {source} belongs to multiple groups."
                )
        for source in group.get("directPartReferences", []) or []:
            key = _basename(source)
            previous = direct_owner.setdefault(key, name)
            if previous != name:
                raise SyntheticProcessKnowledgeError(
                    f"Direct part source {source} belongs to multiple groups."
                )

    assigned = {name: [] for name in sorted(known_names)}
    leaves = [item for item in occurrences if item.get("kind") == "part"]
    for leaf in sorted(leaves, key=lambda item: str(item["occurrenceId"])):
        occurrence_id = str(leaf["occurrenceId"])
        ancestor_groups: list[str] = []
        parent_id = leaf.get("parentOccurrenceId")
        visited: set[str] = set()
        while isinstance(parent_id, str) and parent_id and parent_id not in visited:
            visited.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                raise SyntheticProcessKnowledgeError(
                    f"Occurrence {occurrence_id} has an unknown ancestor."
                )
            owner = subassembly_owner.get(_basename(parent.get("sourcePath")))
            if owner:
                ancestor_groups.append(owner)
            parent_id = parent.get("parentOccurrenceId")
        unique_ancestors = list(dict.fromkeys(ancestor_groups))
        if len(unique_ancestors) > 1:
            raise SyntheticProcessKnowledgeError(
                f"Occurrence {occurrence_id} resolves to multiple functional groups."
            )
        if unique_ancestors:
            owner = unique_ancestors[0]
        elif leaf.get("parentOccurrenceId") == root_id:
            owner = direct_owner.get(_basename(leaf.get("sourcePath")), fallback_group)
        else:
            owner = fallback_group
        assigned[owner].append(occurrence_id)

    covered = [item for rows in assigned.values() for item in rows]
    leaf_ids = {str(item["occurrenceId"]) for item in leaves}
    if len(covered) != len(set(covered)) or set(covered) != leaf_ids:
        raise SyntheticProcessKnowledgeError(
            "Functional-group assignment must cover every leaf occurrence exactly once."
        )
    return assigned


def _canonical_occurrences(
    structure: Mapping[str, Any],
    *,
    source_revision: str,
    extract_record: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    raw_rows = [
        item
        for item in structure.get("occurrences", [])
        if isinstance(item, Mapping) and item.get("occurrenceId")
    ]
    roots = [item for item in raw_rows if item.get("parentOccurrenceId") is None]
    if len(roots) != 1:
        raise SyntheticProcessKnowledgeError("Product structure requires one root.")
    root_id = str(roots[0]["occurrenceId"])
    result = []
    for raw in raw_rows:
        transform = raw.get("transform") if isinstance(raw.get("transform"), Mapping) else {}
        rotation = transform.get("rotation")
        translation = transform.get("translation")
        source_item_id = str(raw.get("itemId") or raw["occurrenceId"])
        item_id = (
            source_item_id
            if IDENTIFIER_RE.fullmatch(source_item_id)
            else stable_id("item", {"sourceItemId": source_item_id}, digest_length=20)
        )
        row = {
            "occurrenceId": str(raw["occurrenceId"]),
            "sourceOccurrenceId": str(
                raw.get("sourceOccurrenceId") or raw["occurrenceId"]
            ),
            "parentOccurrenceId": raw.get("parentOccurrenceId"),
            "itemId": item_id,
            "name": str(raw.get("name") or raw["occurrenceId"]),
            "kind": str(raw.get("kind") or "part"),
            "level": int(raw.get("level") or 0),
            "sourceId": str(extract_record["sourceId"]),
            "sourcePath": str(extract_record["path"]),
            "sourceHash": str(extract_record["sha256"]),
            "configuration": str(raw.get("configuration") or CONFIGURATION),
            "quantity": 1,
            "state": {
                "resolved": True,
                "lightweight": False,
                "suppressed": bool((raw.get("state") or {}).get("suppressed")),
                "hidden": None,
                "virtual": False,
            },
            "transform": {
                "translation": list(translation) if isinstance(translation, list) and len(translation) == 3 else [0.0, 0.0, 0.0],
                "rotation": list(rotation) if isinstance(rotation, list) and len(rotation) == 9 else [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "scale": float(transform.get("scale") or 1.0),
            },
            "properties": {
                "catalogSourcePath": str(raw.get("sourcePath") or ""),
                "catalogItemId": source_item_id,
                "syntheticProcessEvidence": True,
            },
        }
        quaternion = transform.get("quaternion")
        if isinstance(quaternion, list) and len(quaternion) == 4:
            row["transform"]["quaternion"] = list(quaternion)
        result.append(row)
    return root_id, result


def _evidence_entry(
    source_record: Mapping[str, Any],
    source_type: str,
    document: Mapping[str, Any],
    *,
    subject_refs: Iterable[str],
) -> dict[str, Any]:
    evidence_id = stable_id(
        "evidence",
        {
            "sourceId": source_record["sourceId"],
            "sourceHash": source_record["sha256"],
            "sourceType": source_type,
        },
        digest_length=24,
    )
    return {
        "evidenceId": evidence_id,
        "sourceType": source_type,
        "authority": "authored",
        "subjectRefs": sorted(set(str(item) for item in subject_refs if item)),
        "sourceRefs": [str(source_record["sourceId"])],
        "details": {
            "documentId": str(document.get("documentId")),
            "revision": str(document.get("revision")),
            "evidenceClass": "SYNTHETIC_DEMO",
            "title": str(document.get("title")),
        },
    }


def _claim(
    operation: Mapping[str, Any],
    evidence_refs: list[str],
    assumption_ids: list[str],
) -> dict[str, Any]:
    claim_id = stable_id(
        "claim",
        {
            "operationId": operation["operationId"],
            "evidenceRefs": evidence_refs,
            "revision": "A",
        },
        digest_length=24,
    )
    return {
        "claimId": claim_id,
        "subjectRef": str(operation["operationId"]),
        "predicate": "candidate_operation_family",
        "objectRefs": [str(operation["outputRef"])],
        "value": {
            "label": str(operation["label"]),
            "description": str(operation["description"]),
            "evidenceClass": "SYNTHETIC_DEMO",
        },
        "knowledgeStatus": "authored",
        "authority": "authored",
        "evidenceRefs": evidence_refs,
        "assumptionIds": assumption_ids,
        "generatedBy": {
            "kind": "user",
            "generatorId": "mmle-synthetic-process-fixture-builder",
            "version": ADAPTER_VERSION,
        },
        "reviewStatus": "confirmed",
    }


def _validated_work_instruction_benchmarks(
    document: Mapping[str, Any],
    *,
    known_stage_ids: set[str],
    known_resource_ids: set[str],
) -> list[dict[str, Any]]:
    if str(document.get("evidenceClass") or "") != "SYNTHETIC_DEMO_CONTROLLED":
        raise SyntheticProcessKnowledgeError(
            "Work-instruction benchmark evidence must remain synthetic-demo controlled."
        )
    authorization = document.get("authorization")
    if not isinstance(authorization, Mapping):
        raise SyntheticProcessKnowledgeError(
            "Work-instruction benchmark authorization is missing."
        )
    if (
        authorization.get("approvedForSyntheticDemonstration") is not True
        or authorization.get("manufacturingApproval") is not False
        or authorization.get("controlledReleaseAuthority") is not False
    ):
        raise SyntheticProcessKnowledgeError(
            "Work-instruction benchmark authority must be demo-only and non-production."
        )
    document_id = str(document.get("documentId") or "").strip()
    revision = str(document.get("revision") or "").strip()
    if not document_id or not revision:
        raise SyntheticProcessKnowledgeError(
            "Work-instruction benchmark identity and revision are required."
        )

    stages = document.get("stages")
    if not isinstance(stages, list) or not stages:
        raise SyntheticProcessKnowledgeError(
            "Work-instruction benchmark requires at least one stage."
        )
    result: list[dict[str, Any]] = []
    seen_stage_ids: set[str] = set()
    seen_operation_ids: set[str] = set()
    seen_gate_ids: set[str] = set()
    for raw_stage in stages:
        if not isinstance(raw_stage, Mapping):
            raise SyntheticProcessKnowledgeError(
                "Work-instruction benchmark stages must be objects."
            )
        stage = copy.deepcopy(dict(raw_stage))
        stage_id = str(stage.get("stageOperationId") or "").strip()
        if stage_id not in known_stage_ids or stage_id in seen_stage_ids:
            raise SyntheticProcessKnowledgeError(
                "Work-instruction benchmark stage identity is unknown or duplicated."
            )
        seen_stage_ids.add(stage_id)
        if str(stage.get("benchmarkStatus") or "") != (
            "approved_for_synthetic_demonstration"
        ):
            raise SyntheticProcessKnowledgeError(
                f"Work-instruction benchmark stage {stage_id} is not demo-approved."
            )
        operations = stage.get("operationPages")
        if not isinstance(operations, list) or not operations:
            raise SyntheticProcessKnowledgeError(
                f"Work-instruction benchmark stage {stage_id} has no operation pages."
            )
        stage_operation_ids = {
            str(item.get("operationId") or "")
            for item in operations
            if isinstance(item, Mapping)
        }
        if "" in stage_operation_ids or len(stage_operation_ids) != len(operations):
            raise SyntheticProcessKnowledgeError(
                f"Work-instruction benchmark stage {stage_id} has invalid operation IDs."
            )
        predecessor_refs = {
            str(ref)
            for item in operations
            if isinstance(item, Mapping)
            for ref in item.get("predecessorOperationIds", [])
        }
        if predecessor_refs - stage_operation_ids:
            raise SyntheticProcessKnowledgeError(
                f"Work-instruction benchmark stage {stage_id} has unknown predecessors."
            )
        roots = [
            str(item.get("operationId"))
            for item in operations
            if isinstance(item, Mapping)
            and not item.get("predecessorOperationIds")
        ]
        sinks = sorted(stage_operation_ids - predecessor_refs)
        if len(roots) != 1 or len(sinks) != 1:
            raise SyntheticProcessKnowledgeError(
                f"Work-instruction benchmark stage {stage_id} requires one entry and one exit."
            )
        for item in operations:
            if not isinstance(item, Mapping):
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction benchmark stage {stage_id} has a non-object operation."
                )
            operation_id = str(item.get("operationId") or "")
            if operation_id in seen_operation_ids:
                raise SyntheticProcessKnowledgeError(
                    "Work-instruction benchmark operation IDs must be package-unique."
                )
            seen_operation_ids.add(operation_id)
            if not str(item.get("sequenceLabel") or "").strip() or not str(
                item.get("title") or ""
            ).strip():
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} requires a label and title."
                )
            resource_refs = {str(ref) for ref in item.get("resourceRefs", [])}
            if resource_refs - known_resource_ids:
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} has an unknown resource."
                )
            parts = item.get("parts")
            if not isinstance(parts, list) or not parts:
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} requires part references."
                )
            for part in parts:
                if (
                    not isinstance(part, Mapping)
                    or not str(part.get("partNumber") or "").strip()
                    or int(part.get("quantity") or 0) <= 0
                    or not str(part.get("role") or "").strip()
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction operation {operation_id} has an invalid part reference."
                    )
            for field in (
                "actions",
                "keyPoints",
                "specifications",
                "qualityChecks",
                "safetyControls",
            ):
                if not isinstance(item.get(field), list) or not item[field]:
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction operation {operation_id} requires {field}."
                    )
            for specification in item["specifications"]:
                if (
                    not isinstance(specification, Mapping)
                    or not str(specification.get("specificationId") or "").strip()
                    or not str(specification.get("label") or "").strip()
                    or not str(specification.get("value") or "").strip()
                    or not str(specification.get("sourceLocator") or "").startswith(
                        f"{document_id} Rev {revision}"
                    )
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction operation {operation_id} has an untraceable specification."
                    )
            for check in item["qualityChecks"]:
                if (
                    not isinstance(check, Mapping)
                    or not str(check.get("checkId") or "").strip()
                    or not str(check.get("method") or "").strip()
                    or not str(check.get("criterion") or "").strip()
                    or not str(check.get("recordField") or "").strip()
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction operation {operation_id} has an invalid quality check."
                    )
            record = item.get("recordRequirement")
            if (
                not isinstance(record, Mapping)
                or not str(record.get("recordId") or "").strip()
                or not isinstance(record.get("fields"), list)
                or not record["fields"]
            ):
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} requires a record definition."
                )
            transition_gate = item.get("transitionGate")
            if operation_id not in sinks and transition_gate is not None:
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} defines a gate before the benchmark exit."
                )
            if operation_id in sinks:
                if not isinstance(transition_gate, Mapping):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction benchmark exit {operation_id} requires a transition gate."
                    )
                gate_id = str(transition_gate.get("gateId") or "").strip()
                if not gate_id or gate_id in seen_gate_ids:
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction benchmark exit {operation_id} has an invalid gate ID."
                    )
                seen_gate_ids.add(gate_id)
                target_stage_id = str(
                    transition_gate.get("targetStageOperationId") or ""
                ).strip()
                if (
                    target_stage_id not in known_stage_ids
                    or target_stage_id == stage_id
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction gate {gate_id} targets an invalid stage."
                    )
                required_check_ids = transition_gate.get("requiredCheckIds")
                check_ids = {
                    str(check.get("checkId") or "")
                    for check in item["qualityChecks"]
                    if isinstance(check, Mapping)
                }
                if (
                    not isinstance(required_check_ids, list)
                    or not required_check_ids
                    or len(required_check_ids) != len(set(required_check_ids))
                    or {str(value) for value in required_check_ids} != check_ids
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction gate {gate_id} must require every exit quality check exactly once."
                    )
                if str(transition_gate.get("requiredRecordId") or "") != str(
                    record.get("recordId") or ""
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction gate {gate_id} is not bound to its operation record."
                    )
                if (
                    transition_gate.get("satisfiedState")
                    != "eligible_for_main_integration"
                    or transition_gate.get("failureState")
                    != "hold_for_engineering_review"
                    or transition_gate.get("blocking") is not True
                ):
                    raise SyntheticProcessKnowledgeError(
                        f"Work-instruction gate {gate_id} has unsafe transition semantics."
                    )
            scene = item.get("scene")
            if not isinstance(scene, Mapping):
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} requires a CAD scene."
                )
            if str(scene.get("cameraPreset") or "") not in {
                "front",
                "right",
                "top",
                "isometric",
            } or str(scene.get("pose") or "") not in {"assembled", "exploded"}:
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} has an invalid CAD scene."
                )
            explode_factor = float(scene.get("explodeFactor") or 0.0)
            if explode_factor < 0.0 or explode_factor > 1.0:
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} has an invalid explode factor."
                )
            visible = {str(value) for value in scene.get("visiblePartNumbers", [])}
            focus = {str(value) for value in scene.get("focusPartNumbers", [])}
            callouts = {str(value) for value in scene.get("calloutPartNumbers", [])}
            if not visible or not focus or not callouts or not focus <= visible or not callouts <= visible:
                raise SyntheticProcessKnowledgeError(
                    f"Work-instruction operation {operation_id} has inconsistent scene targets."
                )
        stage["authorization"] = copy.deepcopy(dict(authorization))
        stage["documentId"] = document_id
        stage["documentRevision"] = revision
        result.append(stage)
    return result


def build_documents(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    structure = _load_json(root / STRUCTURE_PATH)
    registry = _load_json(root / REGISTRY_PATH)
    routing = _load_json(root / SOURCE_FILES["routing"])
    source_documents = {
        key: _load_json(root / path) for key, path in SOURCE_FILES.items()
    }
    extract_record = _source_record(root, EXTRACT_PATH, "assembly")
    synthetic_records = {
        key: _source_record(root, path, key) for key, path in SOURCE_FILES.items()
    }
    all_source_records = [extract_record, *synthetic_records.values()]
    source_revision = canonical_json_sha256(
        [
            {
                "path": item["path"],
                "sha256": item["sha256"],
                "kind": item["kind"],
            }
            for item in sorted(all_source_records, key=lambda item: item["path"])
        ]
    )
    root_id, occurrences = _canonical_occurrences(
        structure,
        source_revision=source_revision,
        extract_record=extract_record,
    )
    groups = _registry_groups(registry)
    assigned = _assign_leaf_groups(
        structure,
        groups,
        fallback_group=str(routing["fallbackGroup"]),
    )

    requirements = {
        str(item["requirementId"]): item
        for source_key in ("inspection_plan", "test_procedure")
        for item in source_documents[source_key].get("requirements", [])
    }
    resources = {
        str(item["resourceId"]): item
        for item in source_documents["resource_register"].get("resources", [])
    }
    assumptions = [
        {
            **item,
            "status": "open",
            "subjectRefs": [root_id],
        }
        for item in source_documents["assumption_register"].get("assumptions", [])
    ]
    unresolved_questions = [
        {
            **item,
            "status": "open",
            "subjectRefs": [root_id],
        }
        for item in source_documents["assumption_register"].get(
            "unresolvedQuestions", []
        )
    ]
    assumption_ids = [str(item["id"]) for item in assumptions]

    operation_ids = {str(item["operationId"]) for item in routing["operations"]}
    work_instruction_benchmarks = _validated_work_instruction_benchmarks(
        source_documents["work_instruction"],
        known_stage_ids=operation_ids,
        known_resource_ids=set(resources),
    )
    work_instruction_subjects = {
        str(stage["stageOperationId"])
        for stage in work_instruction_benchmarks
    }
    for stage in work_instruction_benchmarks:
        for operation in stage["operationPages"]:
            work_instruction_subjects.add(str(operation["operationId"]))
            work_instruction_subjects.update(
                str(row["specificationId"])
                for row in operation["specifications"]
            )
            work_instruction_subjects.update(
                str(row["checkId"])
                for row in operation["qualityChecks"]
            )
    stage_detail_source = source_documents["stage_details"]
    stage_detail_steps = {
        str(step["stepId"])
        for stage in stage_detail_source.get("stages", [])
        for step in stage.get("suboperations", [])
    }
    evidence_sources = [
        _evidence_entry(
            synthetic_records["routing"],
            "work_instruction",
            source_documents["routing"],
            subject_refs=[*operation_ids, root_id],
        ),
        _evidence_entry(
            synthetic_records["stage_details"],
            "work_instruction",
            stage_detail_source,
            subject_refs=[*operation_ids, *stage_detail_steps, root_id],
        ),
        _evidence_entry(
            synthetic_records["inspection_plan"],
            "procedure",
            source_documents["inspection_plan"],
            subject_refs=[*requirements, root_id],
        ),
        _evidence_entry(
            synthetic_records["test_procedure"],
            "procedure",
            source_documents["test_procedure"],
            subject_refs=["req-functional-test", root_id],
        ),
        _evidence_entry(
            synthetic_records["resource_register"],
            "user_statement",
            source_documents["resource_register"],
            subject_refs=[*resources, root_id],
        ),
        _evidence_entry(
            synthetic_records["assumption_register"],
            "user_statement",
            source_documents["assumption_register"],
            subject_refs=[*assumption_ids, root_id],
        ),
        _evidence_entry(
            synthetic_records["work_instruction"],
            "work_instruction",
            source_documents["work_instruction"],
            subject_refs=[*work_instruction_subjects, root_id],
        ),
    ]
    evidence_by_source = {
        item["sourceRefs"][0]: item for item in evidence_sources
    }
    routing_evidence = evidence_by_source[synthetic_records["routing"]["sourceId"]]
    stage_detail_evidence = evidence_by_source[
        synthetic_records["stage_details"]["sourceId"]
    ]
    inspection_evidence = evidence_by_source[
        synthetic_records["inspection_plan"]["sourceId"]
    ]
    test_evidence = evidence_by_source[
        synthetic_records["test_procedure"]["sourceId"]
    ]
    work_instruction_evidence = evidence_by_source[
        synthetic_records["work_instruction"]["sourceId"]
    ]

    operations = []
    claims = []
    intermediate_results = []
    assigned_to_operation: list[str] = []
    for source in routing["operations"]:
        operation = copy.deepcopy(dict(source))
        input_refs = sorted(
            occurrence_id
            for group_name in operation.pop("inputGroups", [])
            for occurrence_id in assigned.get(str(group_name), [])
        )
        assigned_to_operation.extend(input_refs)
        output_ref = (
            root_id
            if operation.get("outputRef") == "ROOT_ASSEMBLY"
            else str(operation["outputRef"])
        )
        operation["outputRef"] = output_ref
        operation["inputRefs"] = input_refs
        requirement_refs = [str(item) for item in operation.get("requirementRefs", [])]
        resource_refs = [str(item) for item in operation.get("resourceRefs", [])]
        unknown_requirements = sorted(set(requirement_refs) - set(requirements))
        unknown_resources = sorted(set(resource_refs) - set(resources))
        if unknown_requirements or unknown_resources:
            raise SyntheticProcessKnowledgeError(
                f"Operation {operation['operationId']} has unresolved process references."
            )
        evidence_refs = [routing_evidence["evidenceId"]]
        if requirement_refs:
            evidence_refs.append(inspection_evidence["evidenceId"])
        if "req-functional-test" in requirement_refs:
            evidence_refs[-1] = test_evidence["evidenceId"]
        evidence_refs = sorted(set(evidence_refs))
        stage_assumptions = ["assumption-synthetic-routing"]
        if input_refs:
            stage_assumptions.extend(
                ["assumption-module-build", "assumption-visible-configuration"]
            )
        description = str(operation.get("description") or "")
        if resource_refs:
            names = ", ".join(str(resources[item]["name"]) for item in resource_refs)
            description = f"{description} Illustrative resources: {names}."
        inspection_text = " ".join(
            str(requirements[item]["text"]) for item in requirement_refs
        )
        operation.update(
            {
                "knowledgeStatus": "authored",
                "authority": "authored",
                "reviewStatus": "confirmed",
                "evidenceRefs": evidence_refs,
                "evidenceSourceType": "work_instruction",
                "assumptionIds": sorted(set(stage_assumptions)),
                "properties": {
                    "description": description[:2000],
                    **(
                        {"inspectionRequirements": inspection_text[:1000]}
                        if inspection_text
                        else {}
                    ),
                    "constraints": (
                        "SYNTHETIC DEMO sequence; not approved for production."
                    ),
                },
            }
        )
        claim = _claim(operation, evidence_refs, operation["assumptionIds"])
        operation["claimId"] = claim["claimId"]
        claims.append(claim)
        operations.append(operation)
        if output_ref != root_id:
            intermediate_results.append(
                {
                    "intermediateResultId": output_ref,
                    "label": str(operation["label"]) + " result",
                }
            )

    leaf_ids = {
        str(item["occurrenceId"])
        for item in occurrences
        if item.get("kind") == "part"
    }
    if len(assigned_to_operation) != len(set(assigned_to_operation)):
        raise SyntheticProcessKnowledgeError("A leaf occurrence is consumed twice.")
    if set(assigned_to_operation) != leaf_ids:
        missing = sorted(leaf_ids - set(assigned_to_operation))
        raise SyntheticProcessKnowledgeError(
            f"Process routing does not cover every leaf occurrence: {missing[:8]}"
        )

    operations_by_id = {
        str(item["operationId"]): item for item in operations
    }
    output_producers = {
        str(item["outputRef"]): str(item["operationId"])
        for item in operations
        if item.get("outputRef") != root_id
    }
    stage_occurrence_cache: dict[str, set[str]] = {}

    def stage_occurrences(
        operation_id: str,
        stack: tuple[str, ...] = (),
    ) -> set[str]:
        if operation_id in stage_occurrence_cache:
            return set(stage_occurrence_cache[operation_id])
        if operation_id in stack:
            raise SyntheticProcessKnowledgeError(
                "High-level process routing contains a precedence cycle."
            )
        operation = operations_by_id.get(operation_id)
        if operation is None:
            raise SyntheticProcessKnowledgeError(
                f"Stage detail references unknown operation {operation_id}."
            )
        result = {
            str(ref)
            for ref in operation.get("inputRefs", [])
            if str(ref) in leaf_ids
        }
        for ref in operation.get("inputRefs", []):
            producer = output_producers.get(str(ref))
            if producer:
                result.update(stage_occurrences(producer, stack + (operation_id,)))
        for predecessor in operation.get("predecessorOperationIds", []):
            result.update(
                stage_occurrences(str(predecessor), stack + (operation_id,))
            )
        stage_occurrence_cache[operation_id] = set(result)
        return result

    source_stages = stage_detail_source.get("stages", [])
    if not isinstance(source_stages, list):
        raise SyntheticProcessKnowledgeError("Stage details must contain a stages array.")
    source_stage_ids = [str(item.get("stageOperationId")) for item in source_stages]
    if len(source_stage_ids) != len(set(source_stage_ids)):
        raise SyntheticProcessKnowledgeError("Stage detail operation IDs must be unique.")
    if set(source_stage_ids) != set(operations_by_id):
        raise SyntheticProcessKnowledgeError(
            "Every high-level operation requires exactly one stage-detail record."
        )

    stage_details = []
    stage_detail_operation_count = 0
    for source_stage in source_stages:
        stage_id = str(source_stage["stageOperationId"])
        source_steps = source_stage.get("suboperations", [])
        if not isinstance(source_steps, list) or not source_steps:
            raise SyntheticProcessKnowledgeError(
                f"Stage {stage_id} requires at least one detailed suboperation."
            )
        step_by_id = {str(item.get("stepId")): item for item in source_steps}
        if len(step_by_id) != len(source_steps) or not all(step_by_id):
            raise SyntheticProcessKnowledgeError(
                f"Stage {stage_id} has duplicate or missing step IDs."
            )
        predecessor_refs = {
            str(ref)
            for item in source_steps
            for ref in item.get("predecessorStepIds", [])
        }
        unknown_predecessors = sorted(predecessor_refs - set(step_by_id))
        if unknown_predecessors:
            raise SyntheticProcessKnowledgeError(
                f"Stage {stage_id} has unknown predecessors: {unknown_predecessors}."
            )
        roots = [
            str(item["stepId"])
            for item in source_steps
            if not item.get("predecessorStepIds")
        ]
        sinks = sorted(set(step_by_id) - predecessor_refs)
        if len(roots) != 1 or len(sinks) != 1:
            raise SyntheticProcessKnowledgeError(
                f"Stage {stage_id} requires one entry step and one result step."
            )
        visited: set[str] = set()

        def visit_step(step_id: str, stack: tuple[str, ...] = ()) -> None:
            if step_id in visited:
                return
            if step_id in stack:
                raise SyntheticProcessKnowledgeError(
                    f"Stage {stage_id} contains a suboperation cycle."
                )
            for predecessor in step_by_id[step_id].get(
                "predecessorStepIds", []
            ):
                visit_step(str(predecessor), stack + (step_id,))
            visited.add(step_id)

        for step_id in step_by_id:
            visit_step(step_id)
        required_occurrences = sorted(stage_occurrences(stage_id))
        if not required_occurrences:
            raise SyntheticProcessKnowledgeError(
                f"Stage {stage_id} does not resolve to assembly occurrences."
            )
        detail_operations = []
        detail_intermediates = []
        for source_step in source_steps:
            step = copy.deepcopy(dict(source_step))
            step_id = str(step.pop("stepId"))
            predecessor_ids = [
                str(item) for item in step.pop("predecessorStepIds", [])
            ]
            requirement_refs = [
                str(item) for item in step.get("requirementRefs", [])
            ]
            resource_refs = [str(item) for item in step.get("resourceRefs", [])]
            if set(requirement_refs) - set(requirements):
                raise SyntheticProcessKnowledgeError(
                    f"Detailed step {step_id} has an unknown requirement."
                )
            if set(resource_refs) - set(resources):
                raise SyntheticProcessKnowledgeError(
                    f"Detailed step {step_id} has an unknown resource."
                )
            output_ref = (
                root_id if step_id == sinks[0] else f"state-{step_id}"
            )
            evidence_refs = [stage_detail_evidence["evidenceId"]]
            if requirement_refs:
                requirement_evidence = (
                    test_evidence
                    if "req-functional-test" in requirement_refs
                    else inspection_evidence
                )
                evidence_refs.append(requirement_evidence["evidenceId"])
            operation = {
                "operationId": step_id,
                "label": str(step["label"]),
                "description": str(step["description"]),
                "operationType": str(step.get("operationType") or "operation"),
                "inputRefs": (
                    list(required_occurrences) if step_id == roots[0] else []
                ),
                "outputRef": output_ref,
                "predecessorOperationIds": predecessor_ids,
                "resourceRefs": resource_refs,
                "requirementRefs": requirement_refs,
                "knowledgeStatus": "authored",
                "authority": "authored",
                "reviewStatus": "confirmed",
                "evidenceRefs": sorted(set(evidence_refs)),
                "evidenceSourceType": "work_instruction",
                "assumptionIds": ["assumption-synthetic-routing"],
                "properties": {
                    "description": str(step["description"])[:2000],
                    **(
                        {
                            "inspectionRequirements": " ".join(
                                str(requirements[item]["text"])
                                for item in requirement_refs
                            )[:1000]
                        }
                        if requirement_refs
                        else {}
                    ),
                    "constraints": (
                        "SYNTHETIC DEMO sequence; not approved for production."
                    ),
                },
            }
            claim = _claim(
                operation,
                operation["evidenceRefs"],
                operation["assumptionIds"],
            )
            operation["claimId"] = claim["claimId"]
            claims.append(claim)
            detail_operations.append(operation)
            if output_ref != root_id:
                detail_intermediates.append(
                    {
                        "intermediateResultId": output_ref,
                        "label": str(step["label"]) + " result",
                    }
                )
        detail_record = {
            "stageOperationId": stage_id,
            "detailMapLabel": str(source_stage["detailMapLabel"]),
            "resultLabel": str(source_stage["resultLabel"]),
            "presentation": {
                "mode": "stage_detail",
                "showOccurrenceInputs": False,
            },
            "requiredOccurrenceIds": required_occurrences,
            "branches": [],
            "intermediateResults": detail_intermediates,
            "operationFamilies": detail_operations,
        }
        detail_record["stageDetailHash"] = canonical_json_sha256(detail_record)
        stage_details.append(detail_record)
        stage_detail_operation_count += len(detail_operations)
        operations_by_id[stage_id].update(
            {
                "stageDetailAvailable": True,
                "stageDetailStepCount": len(detail_operations),
                "stageDetailHash": detail_record["stageDetailHash"],
            }
        )

    evidence_fingerprint = canonical_json_sha256(
        {
            "compilerVersion": EVIDENCE_COMPILER_VERSION,
            "sourceRevision": source_revision,
            "sources": sorted(evidence_sources, key=lambda item: item["evidenceId"]),
        }
    )
    warning = _finding(
        "warning",
        "synthetic_demo_process_evidence",
        "Process sequence, resources, and inspection intent are synthetic demo evidence and are not approved for production.",
        subject_refs=[root_id],
    )
    visual_warning = _finding(
        "info",
        "visual_evidence_not_required_for_synthetic_process_demo",
        "The synthetic planning package does not include separate process evidence images.",
        subject_refs=[root_id],
    )
    source_manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "rootAssembly": extract_record,
        "configuration": {"active": CONFIGURATION, "available": [CONFIGURATION]},
        "sources": sorted(all_source_records, key=lambda item: item["path"]),
        "extractor": {
            "name": "InspectorPro Process Map Synthetic Fixture Builder",
            "version": ADAPTER_VERSION,
            "adapterVersion": ADAPTER_VERSION,
            "packageSchemaVersion": "1",
            "solidWorksVersion": "source-extraction",
        },
        "sourceRevision": source_revision,
        "preflightFingerprint": canonical_json_sha256(
            {"sourceRevision": source_revision, "productId": PRODUCT_ID}
        ),
        "findings": [warning],
    }
    package_id = stable_id(
        "akp",
        {"productId": PRODUCT_ID, "purpose": "synthetic-process-demo-v1"},
        digest_length=24,
    )
    documents: dict[str, dict[str, Any]] = {
        "source_manifest.json": source_manifest,
        "product_structure.json": {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "sourceRevision": source_revision,
            "configuration": CONFIGURATION,
            "rootOccurrenceId": root_id,
            "occurrences": occurrences,
        },
        "interface_graph.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "mates": [],
            "interfaces": [],
        },
        "geometry_summary.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "occurrences": [
                {
                    "occurrenceId": item["occurrenceId"],
                    "bounds": {},
                    "massProperties": {},
                    "featureSummary": {},
                    "candidateInterfaces": [],
                }
                for item in occurrences
            ],
            "findings": [],
        },
        "visual_manifest.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "views": [],
            "contactSheets": [],
            "findings": [visual_warning],
        },
        "functional_context.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "evidenceFingerprint": evidence_fingerprint,
            "claims": [],
            "relationships": [],
        },
        "process_candidates.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "evidenceFingerprint": evidence_fingerprint,
            "claims": claims,
            "presentation": copy.deepcopy(routing["presentation"]),
            "branches": copy.deepcopy(routing["branches"]),
            "intermediateResults": intermediate_results,
            "operationFamilies": operations,
            "stageDetails": stage_details,
            "workInstructionBenchmarks": [
                {
                    **copy.deepcopy(stage),
                    "sourceRef": SOURCE_FILES[
                        "work_instruction"
                    ].as_posix(),
                    "evidenceRef": work_instruction_evidence["evidenceId"],
                    "evidenceClass": "SYNTHETIC_DEMO_CONTROLLED",
                    "benchmarkHash": canonical_json_sha256(stage),
                }
                for stage in work_instruction_benchmarks
            ],
            "assumptions": assumptions,
            "unresolvedQuestions": unresolved_questions,
            "requirements": [
                {
                    **copy.deepcopy(item),
                    "sourceRef": (
                        SOURCE_FILES["test_procedure"].as_posix()
                        if item["requirementId"] == "req-functional-test"
                        else SOURCE_FILES["inspection_plan"].as_posix()
                    ),
                    "evidenceClass": "SYNTHETIC_DEMO",
                }
                for item in requirements.values()
            ],
            "resources": [
                {
                    **copy.deepcopy(item),
                    "sourceRef": SOURCE_FILES["resource_register"].as_posix(),
                    "evidenceClass": "SYNTHETIC_DEMO",
                }
                for item in resources.values()
            ],
        },
        "evidence_catalog.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "evidenceFingerprint": evidence_fingerprint,
            "sources": evidence_sources,
        },
        "unresolved.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "findings": [warning],
            "assumptions": assumptions,
            "questions": unresolved_questions,
        },
        "review_receipt.json": {
            "schemaVersion": 1,
            "sourceRevision": source_revision,
            "packageRevision": "0" * 64,
            "events": [],
        },
        "package.json": {
            "schemaVersion": 1,
            "packageId": package_id,
            "productId": PRODUCT_ID,
            "sourceRevision": source_revision,
            "packageRevision": "0" * 64,
            "extractorVersion": ADAPTER_VERSION,
            "adapterVersion": ADAPTER_VERSION,
            "bridgePackageSchemaVersion": "1",
            "enrichmentPolicyVersion": "synthetic-demo-v1",
            "promptVersion": "none-deterministic-fixture",
            "modelProvider": None,
            "modelId": None,
            "readiness": "planning_ready",
            "productionEligible": False,
            "documentHashes": {},
            "assetHashes": {},
        },
    }
    documents = refresh_package_revision(documents, asset_hashes={})
    errors = [
        item
        for item in validate_assembly_knowledge_package(documents)
        if item.get("severity") == "error"
    ]
    if errors:
        summary = "; ".join(
            f"{item.get('document', '')}{item.get('path', '')} "
            f"{item.get('code')}: {item.get('message')}"
            for item in errors[:12]
        )
        raise SyntheticProcessKnowledgeError(summary)
    return documents, {
        "groupCount": len(assigned),
        "leafOccurrenceCount": len(leaf_ids),
        "operationCount": len(operations),
        "stageDetailCount": len(stage_details),
        "stageDetailOperationCount": stage_detail_operation_count,
        "workInstructionBenchmarkStageCount": len(work_instruction_benchmarks),
        "workInstructionBenchmarkOperationCount": sum(
            len(stage["operationPages"])
            for stage in work_instruction_benchmarks
        ),
        "unresolvedQuestionCount": len(unresolved_questions),
    }


def write_package(root: Path) -> dict[str, Any]:
    documents, summary = build_documents(root)
    repository = AssemblyKnowledgeRepository(root / "generated/training")
    package = documents["package.json"]
    package_id = str(package["packageId"])
    existing = {
        item["packageId"]: item
        for item in repository.list_packages(PRODUCT_ID)
    }.get(package_id)
    if existing and existing["packageRevision"] == package["packageRevision"]:
        revision = str(package["packageRevision"])
        changed = False
    else:
        revision = repository.write(
            documents,
            base_revision=(str(existing["packageRevision"]) if existing else None),
        )
        changed = True
    source_status = repository.bind_source_root(PRODUCT_ID, package_id, root)
    return {
        "productId": PRODUCT_ID,
        "packageId": package_id,
        "packageRevision": revision,
        "sourceRevision": package["sourceRevision"],
        "readiness": package["readiness"],
        "productionEligible": package["productionEligible"],
        "changed": changed,
        "sourceStatus": source_status,
        **summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.check:
        documents, summary = build_documents(root)
        result = {
            **summary,
            "packageId": documents["package.json"]["packageId"],
            "packageRevision": documents["package.json"]["packageRevision"],
            "sourceRevision": documents["package.json"]["sourceRevision"],
            "readiness": documents["package.json"]["readiness"],
            "productionEligible": documents["package.json"]["productionEligible"],
        }
    else:
        result = write_package(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
