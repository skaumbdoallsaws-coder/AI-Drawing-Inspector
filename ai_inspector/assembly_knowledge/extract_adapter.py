"""Bridge package v1 to canonical Assembly Knowledge Package adapter."""

from __future__ import annotations

import copy
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .identity import (
    finding_id,
    item_id,
    mate_id,
    normalize_configuration,
    normalize_occurrence_path,
    occurrence_id,
)
from .manifest import (
    canonical_json_sha256,
    make_package_id,
    package_revision,
    sha256_file,
    stable_id,
)
from .schema import validate_package_documents


BRIDGE_PACKAGE_MAJOR_VERSION = 1
ADAPTER_VERSION = "1.0.0"
ZERO_SHA256 = "0" * 64


class ExtractionAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class AdaptedAssemblyPackage:
    documents: Mapping[str, Mapping[str, Any]]
    source_paths: Mapping[str, Path]
    findings: Sequence[Mapping[str, Any]]

    @property
    def package_id(self) -> str:
        return str(self.documents["package.json"]["packageId"])

    @property
    def source_revision(self) -> str:
        return str(self.documents["package.json"]["sourceRevision"])

    @property
    def package_revision(self) -> str:
        return str(self.documents["package.json"]["packageRevision"])


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtractionAdapterError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExtractionAdapterError(f"JSON root must be an object: {path}")
    return value


def _bridge_major(value: Any) -> int:
    text = str(value or "").strip()
    try:
        return int(text.split(".", 1)[0])
    except (TypeError, ValueError) as exc:
        raise ExtractionAdapterError(
            f"Invalid bridge package schemaVersion: {value!r}"
        ) from exc


def _typed_finding(
    severity: str,
    code: str,
    message: str,
    *,
    subject_refs: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    subjects = sorted(set(str(item) for item in subject_refs if item))
    evidence = sorted(set(str(item) for item in evidence_refs if item))
    normalized_details = dict(details or {})
    result: Dict[str, Any] = {
        "findingId": finding_id(
            code,
            subject_refs=subjects,
            evidence_refs=evidence,
            details=normalized_details,
        ),
        "severity": severity,
        "code": code,
        "message": message,
    }
    if subjects:
        result["subjectRefs"] = subjects
    if evidence:
        result["evidenceRefs"] = evidence
    if normalized_details:
        result["details"] = normalized_details
    return result


def _source_index(source_root: Path) -> Mapping[str, List[Path]]:
    index: Dict[str, List[Path]] = defaultdict(list)
    for path in source_root.rglob("*"):
        if path.is_file():
            index[path.name.lower()].append(path.resolve())
    return index


def _resolve_component_source(
    component: Mapping[str, Any],
    *,
    source_root: Path,
    file_index: Mapping[str, List[Path]],
) -> Path:
    explicit = component.get("referencedPath")
    if isinstance(explicit, str) and explicit.strip():
        candidate = Path(explicit)
        if not candidate.is_absolute():
            candidate = source_root / candidate
        if candidate.is_file():
            return candidate.resolve()
    filename = str(component.get("referencedFileName") or "").strip()
    matches = file_index.get(filename.lower(), [])
    if not filename or not matches:
        raise ExtractionAdapterError(
            f"Referenced component source is missing: {filename or '<unknown>'}"
        )
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches[:4])
        raise ExtractionAdapterError(
            f"Referenced component source is ambiguous for {filename}: {joined}"
        )
    return matches[0]


def _relative_source_path(path: Path, source_root: Path) -> str:
    try:
        return path.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError as exc:
        raise ExtractionAdapterError(
            f"Source path escapes the selected source root: {path}"
        ) from exc


def _source_record(path: Path, source_root: Path, kind: str) -> Tuple[Dict[str, Any], str]:
    digest = sha256_file(path)
    relative = _relative_source_path(path, source_root)
    source_id = stable_id(
        "source",
        {"kind": kind, "path": relative.lower(), "sha256": digest},
        digest_length=20,
    )
    return (
        {
            "sourceId": source_id,
            "path": relative,
            "sha256": digest,
            "size": path.stat().st_size,
            "kind": kind,
            "available": True,
        },
        source_id,
    )


def _component_paths(
    components: Sequence[Mapping[str, Any]],
    *,
    root_name: str,
) -> Mapping[str, str]:
    by_name: Dict[str, Mapping[str, Any]] = {}
    for component in components:
        name = str(component.get("name") or "").strip()
        if not name:
            raise ExtractionAdapterError("Every component occurrence requires a name.")
        if name in by_name:
            raise ExtractionAdapterError(f"Duplicate component occurrence name: {name}")
        by_name[name] = component

    paths: Dict[str, str] = {}
    visiting = set()

    def resolve(name: str) -> str:
        if name in paths:
            return paths[name]
        if name in visiting:
            raise ExtractionAdapterError(f"Component parent cycle includes {name}.")
        visiting.add(name)
        component = by_name[name]
        parent_name = str(component.get("parentName") or "").strip()
        if parent_name:
            if parent_name not in by_name:
                raise ExtractionAdapterError(
                    f"Unknown parent component {parent_name} for {name}."
                )
            parent_path = resolve(parent_name)
        else:
            parent_path = root_name
        paths[name] = normalize_occurrence_path(name, parent_path=parent_path)
        visiting.remove(name)
        return paths[name]

    for name in sorted(by_name):
        resolve(name)
    return paths


def _finite_list(value: Any, expected: int) -> Optional[List[float]]:
    if not isinstance(value, list) or len(value) != expected:
        return None
    result = []
    for item in value:
        if (
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
        ):
            return None
        result.append(float(item))
    return result


def _transform(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    translation = _finite_list(value.get("translation"), 3)
    rotation = _finite_list(value.get("rotation"), 9)
    scale = value.get("scale")
    if (
        translation is None
        or rotation is None
        or isinstance(scale, bool)
        or not isinstance(scale, (int, float))
        or not math.isfinite(float(scale))
    ):
        return None
    result: Dict[str, Any] = {
        "translation": translation,
        "rotation": rotation,
        "scale": float(scale),
    }
    quaternion = _finite_list(value.get("quaternion"), 4)
    if quaternion is not None:
        result["quaternion"] = quaternion
    return result


def _component_state(component: Mapping[str, Any]) -> Dict[str, Optional[bool]]:
    raw_state = str(component.get("state") or "").strip().lower()
    hidden = component.get("isHidden")
    return {
        "resolved": (
            True
            if raw_state == "resolved"
            else False
            if raw_state in {"lightweight", "fullylightweight", "suppressed"}
            else None
        ),
        "lightweight": bool(component.get("isLightweight")),
        "suppressed": bool(component.get("isSuppressed")),
        "hidden": hidden if isinstance(hidden, bool) else None,
        "virtual": bool(component.get("isVirtual")),
    }


def _entity_vector(value: Any) -> List[float]:
    result = _finite_list(value, 3)
    return result or []


def _normalized_entity(
    raw: Mapping[str, Any],
    *,
    occurrence_by_alias: Mapping[str, str],
) -> Dict[str, Any]:
    alias = str(raw.get("componentName") or "").strip()
    occurrence_ref = occurrence_by_alias.get(alias)
    if occurrence_ref is None:
        raise ExtractionAdapterError(
            f"Mate entity references unknown occurrence: {alias or '<empty>'}"
        )
    radius = raw.get("radius", 0.0)
    if (
        isinstance(radius, bool)
        or not isinstance(radius, (int, float))
        or not math.isfinite(float(radius))
    ):
        radius = 0.0
    return {
        "occurrenceRef": occurrence_ref,
        "entityType": str(raw.get("entityType") or "Unknown"),
        "geometryType": (
            str(raw["geometryType"]) if raw.get("geometryType") is not None else None
        ),
        "point": _entity_vector(raw.get("point")),
        "direction": _entity_vector(raw.get("direction")),
        "radius": float(radius),
    }


def _normalized_mate_identity(
    mate: Mapping[str, Any],
    entities: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    participants = sorted(
        (
            {
                "direction": [round(float(x), 12) for x in entity["direction"]],
                "entityType": entity["entityType"],
                "geometryType": entity["geometryType"],
                "occurrenceRef": entity["occurrenceRef"],
                "point": [round(float(x), 12) for x in entity["point"]],
                "radius": round(float(entity["radius"]), 12),
            }
            for entity in entities
        ),
        key=lambda item: canonical_json_sha256(item),
    )
    return {
        "alignment": str(mate.get("alignment") or "Unknown"),
        "angle": round(float(mate.get("angle") or 0.0), 12),
        "distance": round(float(mate.get("distance") or 0.0), 12),
        "entities": participants,
        "flipped": bool(mate.get("isFlipped")),
        "type": str(mate.get("type") or "Unknown"),
    }


def _make_initial_documents(
    *,
    product_id: str,
    bridge_manifest: Mapping[str, Any],
    bridge_assembly: Mapping[str, Any],
    root_assembly: Path,
    source_root: Path,
    active_configuration: Optional[str],
) -> Tuple[Dict[str, Dict[str, Any]], Mapping[str, Path], List[Dict[str, Any]]]:
    components = bridge_assembly.get("components")
    mates = bridge_assembly.get("mates")
    if not isinstance(components, list) or not isinstance(mates, list):
        raise ExtractionAdapterError("Bridge assembly must contain components and mates arrays.")

    file_index = _source_index(source_root)
    root_record, root_source_id = _source_record(
        root_assembly.resolve(), source_root, "assembly"
    )
    source_records: Dict[str, Dict[str, Any]] = {root_source_id: root_record}
    source_paths: Dict[str, Path] = {root_source_id: root_assembly.resolve()}
    component_source_ids: Dict[str, str] = {}
    for raw_component in components:
        if not isinstance(raw_component, dict):
            raise ExtractionAdapterError("Every bridge component must be an object.")
        source_path = _resolve_component_source(
            raw_component,
            source_root=source_root,
            file_index=file_index,
        )
        kind = (
            "assembly"
            if str(raw_component.get("type") or "").lower() == "assembly"
            else "part"
        )
        source_record, source_id = _source_record(source_path, source_root, kind)
        source_records[source_id] = source_record
        source_paths[source_id] = source_path
        component_source_ids[str(raw_component.get("name"))] = source_id

    manifest_config = (
        bridge_manifest.get("sourceDocument", {}).get("configurationName")
        if isinstance(bridge_manifest.get("sourceDocument"), dict)
        else None
    )
    configuration = normalize_configuration(
        active_configuration
        or manifest_config
        or bridge_assembly.get("activeConfiguration")
    )
    available_configs = bridge_assembly.get("configurations")
    if not isinstance(available_configs, list):
        available_configs = [configuration]
    else:
        available_configs = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in available_configs
            if str(item.get("name") if isinstance(item, dict) else item).strip()
        ]
        if configuration not in available_configs:
            available_configs.append(configuration)

    source_revision_payload = {
        "configuration": configuration,
        "productId": product_id,
        "sources": [
            {
                "kind": record["kind"],
                "path": record["path"].lower(),
                "sha256": record["sha256"],
                "size": record["size"],
            }
            for record in sorted(source_records.values(), key=lambda item: item["path"].lower())
        ],
    }
    source_revision = canonical_json_sha256(source_revision_payload)
    findings: List[Dict[str, Any]] = []

    bridge_warnings = bridge_manifest.get("validation", {}).get("warnings", [])
    if isinstance(bridge_warnings, list):
        for warning in bridge_warnings:
            findings.append(
                _typed_finding(
                    "warning",
                    "bridge_extraction_warning",
                    str(warning),
                )
            )
    if manifest_config in (None, "") and active_configuration is not None:
        findings.append(
            _typed_finding(
                "warning",
                "bridge_configuration_override",
                "The bridge package omitted active configuration; the trusted caller supplied it.",
                details={"configuration": configuration},
            )
        )

    root_path = root_assembly.stem
    root_occurrence_id = occurrence_id(
        root_source_revision=root_record["sha256"],
        configuration=configuration,
        occurrence_path=root_path,
    )
    occurrences: List[Dict[str, Any]] = [
        {
            "occurrenceId": root_occurrence_id,
            "sourceOccurrenceId": root_occurrence_id,
            "parentOccurrenceId": None,
            "itemId": item_id(
                source_hash=root_record["sha256"],
                configuration=configuration,
            ),
            "name": root_assembly.stem,
            "kind": "assembly",
            "level": 0,
            "sourceId": root_source_id,
            "sourcePath": root_record["path"],
            "sourceHash": root_record["sha256"],
            "configuration": configuration,
            "quantity": 1,
            "state": {
                "resolved": True,
                "lightweight": False,
                "suppressed": False,
                "hidden": False,
                "virtual": False,
            },
            "transform": {
                "translation": [0.0, 0.0, 0.0],
                "rotation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "scale": 1.0,
                "quaternion": [0.0, 0.0, 0.0, 1.0],
            },
            "properties": copy.deepcopy(bridge_assembly.get("identity") or {}),
        }
    ]

    component_paths = _component_paths(components, root_name=root_path)
    occurrence_by_alias: Dict[str, str] = {
        root_assembly.stem: root_occurrence_id,
        root_assembly.name: root_occurrence_id,
    }
    assembly_identity = bridge_assembly.get("identity")
    if isinstance(assembly_identity, dict):
        assembly_number = str(assembly_identity.get("assemblyNumber") or "").strip()
        if assembly_number:
            occurrence_by_alias[assembly_number] = root_occurrence_id
    component_by_name = {
        str(component.get("name")): component for component in components
    }
    pending_occurrence_records: Dict[str, Dict[str, Any]] = {}
    for name, component in component_by_name.items():
        source_id = component_source_ids[name]
        source = source_records[source_id]
        component_configuration = normalize_configuration(
            component.get("activeConfiguration") or configuration
        )
        path = component_paths[name]
        occurrence_ref = occurrence_id(
            root_source_revision=root_record["sha256"],
            configuration=configuration,
            occurrence_path=path,
        )
        occurrence_by_alias[name] = occurrence_ref
        raw_transform = _transform(component.get("transform"))
        if raw_transform is None:
            findings.append(
                _typed_finding(
                    "warning",
                    "component_transform_unavailable",
                    f"Transform is unavailable for occurrence {name}.",
                    subject_refs=[occurrence_ref],
                )
            )
        if component.get("isHidden") is None:
            findings.append(
                _typed_finding(
                    "info",
                    "component_hidden_state_unavailable",
                    f"Hidden state is unavailable for occurrence {name}.",
                    subject_refs=[occurrence_ref],
                )
            )
        kind = (
            "subassembly"
            if str(component.get("type") or "").lower() == "assembly"
            else "part"
        )
        pending_occurrence_records[name] = {
            "occurrenceId": occurrence_ref,
            "sourceOccurrenceId": occurrence_ref,
            "parentOccurrenceId": None,
            "itemId": item_id(
                source_hash=source["sha256"],
                configuration=component_configuration,
            ),
            "name": name,
            "kind": kind,
            "level": int(component.get("level") or 1),
            "sourceId": source_id,
            "sourcePath": source["path"],
            "sourceHash": source["sha256"],
            "configuration": component_configuration,
            "quantity": 1,
            "state": _component_state(component),
            "transform": raw_transform,
            "properties": {
                "partDataKey": component.get("partDataKey"),
                "referencedFileName": component.get("referencedFileName"),
                "sourceOccurrencePath": path,
            },
        }
    for name, record in pending_occurrence_records.items():
        parent_alias = str(component_by_name[name].get("parentName") or "").strip()
        record["parentOccurrenceId"] = (
            occurrence_by_alias[parent_alias] if parent_alias else root_occurrence_id
        )
        occurrences.append(record)
    occurrences.sort(key=lambda item: (int(item["level"]), str(item["occurrenceId"])))
    occurrences = [
        next(item for item in occurrences if item["occurrenceId"] == root_occurrence_id)
    ] + [
        item for item in occurrences if item["occurrenceId"] != root_occurrence_id
    ]

    normalized_mates = []
    for index, raw_mate in enumerate(mates):
        if not isinstance(raw_mate, dict):
            raise ExtractionAdapterError("Every bridge mate must be an object.")
        entities = [
            _normalized_entity(
                raw_mate.get("entity1") or {},
                occurrence_by_alias=occurrence_by_alias,
            ),
            _normalized_entity(
                raw_mate.get("entity2") or {},
                occurrence_by_alias=occurrence_by_alias,
            ),
        ]
        normalized_identity = _normalized_mate_identity(raw_mate, entities)
        identity_fingerprint = canonical_json_sha256(normalized_identity)
        has_geometry = any(
            entity["geometryType"]
            or entity["point"]
            or entity["direction"]
            or entity["radius"] != 0.0
            for entity in entities
        )
        normalized_mates.append(
            {
                "raw": raw_mate,
                "entities": entities,
                "identity": normalized_identity,
                "identityFingerprint": identity_fingerprint,
                "identityStrength": "strong" if has_geometry else "weak",
                "inputIndex": index,
            }
        )
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in normalized_mates:
        buckets[item["identityFingerprint"]].append(item)

    canonical_mates = []
    for fingerprint in sorted(buckets):
        bucket = sorted(
            buckets[fingerprint],
            key=lambda item: (
                str(item["raw"].get("name") or ""),
                int(item["inputIndex"]),
            ),
        )
        for ordinal, item in enumerate(bucket):
            raw_mate = item["raw"]
            mate_ref = mate_id(item["identity"], collision_ordinal=ordinal)
            canonical_mates.append(
                {
                    "mateId": mate_ref,
                    "displayName": str(raw_mate.get("name") or "Unnamed mate"),
                    "type": str(raw_mate.get("type") or "Unknown"),
                    "occurrenceRefs": sorted(
                        entity["occurrenceRef"] for entity in item["entities"]
                    ),
                    "suppressed": bool(raw_mate.get("isSuppressed")),
                    "alignment": str(raw_mate.get("alignment") or "Unknown"),
                    "distance": float(raw_mate.get("distance") or 0.0),
                    "angle": float(raw_mate.get("angle") or 0.0),
                    "entities": item["entities"],
                    "identityStrength": item["identityStrength"],
                }
            )
            if item["identityStrength"] == "weak":
                findings.append(
                    _typed_finding(
                        "warning",
                        "weak_mate_identity",
                        f"Mate {raw_mate.get('name') or mate_ref} lacks persistent entity geometry.",
                        subject_refs=[mate_ref],
                        details={"displayName": raw_mate.get("name")},
                    )
                )
    canonical_mates.sort(key=lambda item: item["mateId"])

    interface_buckets: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for mate in canonical_mates:
        refs = tuple(sorted(mate["occurrenceRefs"]))
        if len(refs) == 2:
            interface_buckets[(refs[0], refs[1])].append(mate["mateId"])
    interfaces = []
    for occurrence_pair, mate_refs in sorted(interface_buckets.items()):
        interfaces.append(
            {
                "interfaceId": stable_id(
                    "interface",
                    {
                        "mateRefs": sorted(mate_refs),
                        "occurrenceRefs": list(occurrence_pair),
                    },
                    digest_length=24,
                ),
                "occurrenceRefs": list(occurrence_pair),
                "mateRefs": sorted(mate_refs),
                "geometryRefs": [],
                "status": "derived",
            }
        )

    extractor = bridge_manifest.get("extractor") or {}
    source_manifest = {
        "schemaVersion": 1,
        "productId": product_id,
        "rootAssembly": root_record,
        "configuration": {
            "active": configuration,
            "available": sorted(set(available_configs)),
        },
        "sources": sorted(source_records.values(), key=lambda item: item["path"].lower()),
        "extractor": {
            "name": str(extractor.get("name") or "InspectorPro.SolidWorksExtractor"),
            "version": str(extractor.get("version") or "unknown"),
            "adapterVersion": ADAPTER_VERSION,
            "packageSchemaVersion": str(bridge_manifest.get("schemaVersion")),
            "solidWorksVersion": str(bridge_manifest.get("swVersion") or "unknown"),
        },
        "sourceRevision": source_revision,
        "preflightFingerprint": canonical_json_sha256(source_revision_payload),
        "findings": sorted(findings, key=lambda item: item["findingId"]),
    }
    product_structure = {
        "schemaVersion": 1,
        "productId": product_id,
        "sourceRevision": source_revision,
        "configuration": configuration,
        "rootOccurrenceId": root_occurrence_id,
        "occurrences": occurrences,
    }
    interface_graph = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "mates": canonical_mates,
        "interfaces": interfaces,
    }
    geometry_findings = [
        _typed_finding(
            "warning",
            "geometry_enrichment_pending",
            "Bounds, mass properties, and feature summaries require deterministic enrichment.",
        )
    ]
    geometry_summary = {
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
        "findings": geometry_findings,
    }
    evidence_fingerprint = canonical_json_sha256(
        {
            "interfaces": interfaces,
            "occurrences": [
                {
                    "itemId": item["itemId"],
                    "occurrenceId": item["occurrenceId"],
                    "parentOccurrenceId": item["parentOccurrenceId"],
                }
                for item in occurrences
            ],
            "sourceRevision": source_revision,
        }
    )
    visual_manifest = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "views": [],
        "contactSheets": [],
        "findings": [
            _typed_finding(
                "warning",
                "visual_evidence_pending",
                "Visual evidence has not been generated.",
            )
        ],
    }
    functional_context = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "claims": [],
        "relationships": [],
    }
    process_candidates = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "claims": [],
        "branches": [],
        "intermediateResults": [],
        "operationFamilies": [],
        "assumptions": [],
        "unresolvedQuestions": [],
    }
    evidence_catalog = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "sources": [],
    }
    unresolved = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "findings": sorted(
            findings + geometry_findings + visual_manifest["findings"],
            key=lambda item: item["findingId"],
        ),
        "assumptions": [],
        "questions": [],
    }
    review_receipt = {
        "schemaVersion": 1,
        "sourceRevision": source_revision,
        "packageRevision": ZERO_SHA256,
        "events": [],
    }
    documents: Dict[str, Dict[str, Any]] = {
        "source_manifest.json": source_manifest,
        "product_structure.json": product_structure,
        "interface_graph.json": interface_graph,
        "geometry_summary.json": geometry_summary,
        "visual_manifest.json": visual_manifest,
        "functional_context.json": functional_context,
        "process_candidates.json": process_candidates,
        "evidence_catalog.json": evidence_catalog,
        "unresolved.json": unresolved,
        "review_receipt.json": review_receipt,
    }
    return documents, source_paths, findings


def adapt_bridge_package(
    package_dir: str | Path,
    *,
    source_root: str | Path,
    root_assembly: str | Path,
    product_id: str,
    active_configuration: Optional[str] = None,
) -> AdaptedAssemblyPackage:
    package_path = Path(package_dir).resolve()
    manifest_path = package_path / "manifest.json"
    assembly_path = package_path / "assembly" / "assembly.json"
    bridge_manifest = _load_json(manifest_path)
    bridge_assembly = _load_json(assembly_path)
    if bridge_manifest.get("kind") != "assembly":
        raise ExtractionAdapterError("Bridge package kind must be assembly.")
    if _bridge_major(bridge_manifest.get("schemaVersion")) != BRIDGE_PACKAGE_MAJOR_VERSION:
        raise ExtractionAdapterError(
            f"Unsupported bridge package major version: {bridge_manifest.get('schemaVersion')}"
        )
    sha_index = bridge_manifest.get("sha256Index")
    if isinstance(sha_index, dict):
        for relative, expected in sha_index.items():
            target = (package_path / str(relative)).resolve()
            try:
                target.relative_to(package_path)
            except ValueError as exc:
                raise ExtractionAdapterError(
                    f"Bridge package hash path escapes package root: {relative}"
                ) from exc
            if not target.is_file() or sha256_file(target) != str(expected).lower():
                raise ExtractionAdapterError(
                    f"Bridge package hash mismatch: {relative}"
                )

    source_root_path = Path(source_root).resolve()
    root_assembly_path = Path(root_assembly).resolve()
    if not root_assembly_path.is_file():
        raise ExtractionAdapterError(f"Root assembly does not exist: {root_assembly}")
    try:
        root_assembly_path.relative_to(source_root_path)
    except ValueError as exc:
        raise ExtractionAdapterError(
            "Root assembly must remain inside the selected source root."
        ) from exc

    documents, source_paths, findings = _make_initial_documents(
        product_id=product_id,
        bridge_manifest=bridge_manifest,
        bridge_assembly=bridge_assembly,
        root_assembly=root_assembly_path,
        source_root=source_root_path,
        active_configuration=active_configuration,
    )
    source_revision = documents["source_manifest.json"]["sourceRevision"]
    package_index: Dict[str, Any] = {
        "schemaVersion": 1,
        "packageId": make_package_id(
            product_id,
            source_revision,
            documents["source_manifest.json"]["configuration"]["active"],
            ADAPTER_VERSION,
        ),
        "productId": product_id,
        "sourceRevision": source_revision,
        "packageRevision": ZERO_SHA256,
        "extractorVersion": documents["source_manifest.json"]["extractor"]["version"],
        "adapterVersion": ADAPTER_VERSION,
        "bridgePackageSchemaVersion": str(bridge_manifest.get("schemaVersion")),
        "enrichmentPolicyVersion": "economy-v1",
        "promptVersion": "none",
        "modelProvider": None,
        "modelId": None,
        "readiness": "structure_ready",
        "productionEligible": False,
        "documentHashes": {},
        "assetHashes": {},
    }
    revision = package_revision(package_index, documents, {})
    documents["review_receipt.json"]["packageRevision"] = revision
    package_index["packageRevision"] = revision
    package_index["documentHashes"] = {
        name: canonical_json_sha256(document)
        for name, document in sorted(documents.items())
    }
    documents["package.json"] = package_index

    schema_findings = validate_package_documents(documents)
    errors = [
        item for item in schema_findings if item.get("severity") == "error"
    ]
    if errors:
        preview = "; ".join(
            f"{item.get('document')} {item.get('path')}: {item.get('message')}"
            for item in errors[:8]
        )
        raise ExtractionAdapterError(f"Canonical adapter produced invalid data: {preview}")
    return AdaptedAssemblyPackage(
        documents=documents,
        source_paths=source_paths,
        findings=tuple(findings),
    )


def verify_sources_unchanged(
    adapted: AdaptedAssemblyPackage,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    source_manifest = adapted.documents["source_manifest.json"]
    records = {
        str(item["sourceId"]): item for item in source_manifest.get("sources", [])
    }
    for source_id, path in adapted.source_paths.items():
        record = records.get(source_id)
        if record is None or not path.is_file():
            findings.append(
                _typed_finding(
                    "error",
                    "source_missing_after_extraction",
                    f"Source disappeared after extraction: {path.name}.",
                    subject_refs=[source_id],
                )
            )
            continue
        current_hash = sha256_file(path)
        if current_hash != record.get("sha256"):
            findings.append(
                _typed_finding(
                    "error",
                    "source_changed_during_preparation",
                    f"Source changed during preparation: {record.get('path')}.",
                    subject_refs=[source_id],
                )
            )
    return sorted(findings, key=lambda item: item["findingId"])
