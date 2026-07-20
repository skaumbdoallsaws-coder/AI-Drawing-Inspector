"""Load, validate, and query assembly functional relationship graphs.

The graph records normal product function and qualitative interface
requirements. Inspection dimensions, tolerances, and measured values stay in
their own evidence providers and are joined to this graph at reasoning time.
"""

from __future__ import annotations

import copy
import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


_SCHEMA_VERSION = "1.0"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_UNIT_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?\s*(?:mm|cm|m|in|inch|inches|deg|rpm)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "body",
        "dimension",
        "from",
        "in",
        "of",
        "on",
        "part",
        "the",
        "through",
        "to",
        "with",
    }
)

_TOP_KEYS = {
    "schema_version",
    "graph_id",
    "version",
    "assembly",
    "source_evidence",
    "component_types",
    "component_instances",
    "external_entities",
    "interfaces",
    "coverage",
}
_ASSEMBLY_KEYS = {"part_number", "name", "configuration"}
_SOURCE_KEYS = {"source_id", "type", "path", "sha256", "authority"}
_COMPONENT_TYPE_KEYS = {
    "part_number",
    "name",
    "description",
    "mobility",
    "functional_roles",
    "functional_features",
}
_FEATURE_KEYS = {"feature_ref", "label", "semantic_tags", "aliases", "source_refs"}
_INSTANCE_KEYS = {
    "instance_id",
    "source_component_name",
    "part_number",
    "parent_instance_id",
    "kind",
    "occurrence_key",
}
_EXTERNAL_KEYS = {
    "entity_id",
    "name",
    "presence",
    "functional_roles",
    "functional_features",
    "evidence_refs",
}
_INTERFACE_KEYS = {
    "interface_id",
    "pattern_id",
    "name",
    "interface_type",
    "participants",
    "functions",
    "relative_motion",
    "transfer_modes",
    "qualitative_requirements",
    "evidence",
    "confidence",
    "review_status",
}
_PARTICIPANT_KEYS = {"participant_id", "part_number", "feature_refs", "role"}
_MOTION_KEYS = {"type", "allowed", "constrained"}
_EVIDENCE_KEYS = {"source_ref", "locator", "classification", "claim"}
_COVERAGE_KEYS = {
    "physical_instance_count",
    "covered_instance_count",
    "uncovered_instance_ids",
    "organizational_instance_count",
    "external_entity_count",
}

_SOURCE_TYPES = frozenset(
    {"assembly_extract", "part_profile", "motion_summary", "engineering_review"}
)
_AUTHORITIES = frozenset(
    {"cad_structure", "cad_constraint", "curated_profile", "validated_motion", "reviewed_inference"}
)
_MOBILITY = frozenset({"fixed", "rotating", "reciprocating", "oscillating", "carried"})
_INSTANCE_KINDS = frozenset({"physical", "organizational"})
_EXTERNAL_PRESENCE = frozenset({"present", "absent_from_extract", "unresolved"})
_INTERFACE_TYPES = frozenset(
    {
        "revolute_support",
        "split_journal_bearing",
        "bolted_clamp",
        "floating_pin_bearing",
        "oscillating_pin_bearing",
        "axial_guidance_clearance",
        "prismatic_guidance_clearance",
        "ring_retention",
        "sliding_seal",
        "dynamic_clearance_envelope",
        "structural_mount",
        "torque_output",
    }
)
_MOTION_TYPES = frozenset(
    {
        "fixed",
        "revolute",
        "oscillating_revolute",
        "prismatic",
        "limited_axial_float",
        "sliding_contact",
        "non_contact_dynamic",
        "external_unknown",
    }
)
_REVIEW_STATES = frozenset({"verified", "reviewed_inference", "needs_confirmation"})
_EVIDENCE_CLASSES = frozenset(
    {"cad_mate", "assembly_hierarchy", "part_profile", "motion_package", "engineering_inference"}
)
_PARTICIPANT_ROLES = frozenset(
    {
        "axial_locator",
        "bearing_half",
        "clamp_body",
        "clearance_boundary",
        "clearance_member",
        "driven_interface",
        "fastener",
        "guide",
        "guided_member",
        "journal",
        "load_path",
        "oscillating_member",
        "retained_member",
        "retainer",
        "rotating_member",
        "sealing_member",
        "sealing_surface",
        "support",
    }
)
_FORBIDDEN_DATA_KEYS = frozenset(
    {
        "dimension",
        "dimensions",
        "nominal",
        "measured",
        "measurement",
        "tolerance",
        "upper_limit",
        "lower_limit",
        "diameter_mm",
        "radius_mm",
        "length_mm",
        "clearance_mm",
    }
)


class FunctionalRelationshipError(ValueError):
    """Raised when a functional relationship graph cannot be trusted."""


@dataclass(frozen=True)
class FunctionalValidationReport:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    coverage: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "coverage": copy.deepcopy(dict(self.coverage)),
        }


def _strict_keys(value: Any, expected: set[str], path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return False
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        errors.append(f"{path} missing keys: {', '.join(missing)}")
    if unknown:
        errors.append(f"{path} unknown keys: {', '.join(unknown)}")
    return not missing and not unknown


def _string(value: Any, path: str, errors: list[str], *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-empty string")
        return ""
    text = value.strip()
    if identifier and not _ID_RE.fullmatch(text):
        errors.append(f"{path} is not a valid identifier: {text!r}")
    return text


def _string_list(value: Any, path: str, errors: list[str], *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        errors.append(f"{path} must be {'a non-empty' if nonempty else 'an'} array")
        return []
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{path}[{index}] must be a non-empty string")
            continue
        result.append(item.strip())
    if len(result) != len(set(result)):
        errors.append(f"{path} contains duplicate values")
    return result


def _walk_forbidden_content(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_DATA_KEYS:
                errors.append(f"{path}.{key} embeds inspection or dimensional data")
            _walk_forbidden_content(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden_content(item, f"{path}[{index}]", errors)
    elif isinstance(value, str) and _UNIT_VALUE_RE.search(value):
        errors.append(f"{path} embeds a dimensional value; keep it in engineering evidence")


def _assembly_component_part_numbers(assembly_data: Mapping[str, Any]) -> dict[str, str | None]:
    cache = assembly_data.get("partDataCache")
    cache = cache if isinstance(cache, dict) else {}
    key_to_part: dict[str, str] = {}
    for key, raw in cache.items():
        identity = raw.get("identity") if isinstance(raw, dict) else {}
        identity = identity if isinstance(identity, dict) else {}
        custom = identity.get("customProperties")
        custom = custom if isinstance(custom, dict) else {}
        part_number = str(custom.get("PartNo") or identity.get("partNumber") or "").strip()
        if part_number:
            key_to_part[str(key).lower()] = part_number
    result: dict[str, str | None] = {}
    for component in assembly_data.get("components") or []:
        if not isinstance(component, dict) or not component.get("name"):
            continue
        if component.get("type") != "Part":
            result[str(component["name"])] = None
            continue
        key = str(component.get("partDataKey") or component.get("referencedFileName") or "").lower()
        result[str(component["name"])] = key_to_part.get(key)
    return result


def validate_functional_relationship_graph(
    graph: Mapping[str, Any],
    *,
    assembly_data: Mapping[str, Any] | None = None,
) -> FunctionalValidationReport:
    """Validate structure, ontology, coverage, and optional CAD identity parity."""
    errors: list[str] = []
    warnings: list[str] = []
    if not _strict_keys(graph, _TOP_KEYS, "graph", errors):
        return FunctionalValidationReport(False, tuple(errors), (), {})
    if graph.get("schema_version") != _SCHEMA_VERSION:
        errors.append(f"graph.schema_version must be {_SCHEMA_VERSION}")
    _string(graph.get("graph_id"), "graph.graph_id", errors, identifier=True)
    _string(graph.get("version"), "graph.version", errors)
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(graph.get("version") or "")):
        errors.append("graph.version must be semantic version text")

    assembly = graph.get("assembly")
    if _strict_keys(assembly, _ASSEMBLY_KEYS, "graph.assembly", errors):
        _string(assembly.get("part_number"), "graph.assembly.part_number", errors, identifier=True)
        _string(assembly.get("name"), "graph.assembly.name", errors)
        _string(assembly.get("configuration"), "graph.assembly.configuration", errors)

    source_ids: set[str] = set()
    sources = graph.get("source_evidence")
    if not isinstance(sources, list) or not sources:
        errors.append("graph.source_evidence must be a non-empty array")
        sources = []
    for index, source in enumerate(sources):
        path = f"graph.source_evidence[{index}]"
        if not _strict_keys(source, _SOURCE_KEYS, path, errors):
            continue
        source_id = _string(source.get("source_id"), f"{path}.source_id", errors, identifier=True)
        if source_id in source_ids:
            errors.append(f"duplicate source_id: {source_id}")
        source_ids.add(source_id)
        if source.get("type") not in _SOURCE_TYPES:
            errors.append(f"{path}.type is not registered")
        if source.get("authority") not in _AUTHORITIES:
            errors.append(f"{path}.authority is not registered")
        _string(source.get("path"), f"{path}.path", errors)
        if not _SHA256_RE.fullmatch(str(source.get("sha256") or "")):
            errors.append(f"{path}.sha256 must be a lowercase SHA-256 digest")

    component_types = graph.get("component_types")
    if not isinstance(component_types, list) or not component_types:
        errors.append("graph.component_types must be a non-empty array")
        component_types = []
    type_by_part: dict[str, Mapping[str, Any]] = {}
    features_by_part: dict[str, set[str]] = {}
    for index, component_type in enumerate(component_types):
        path = f"graph.component_types[{index}]"
        if not _strict_keys(component_type, _COMPONENT_TYPE_KEYS, path, errors):
            continue
        pn = _string(component_type.get("part_number"), f"{path}.part_number", errors, identifier=True)
        if pn in type_by_part:
            errors.append(f"duplicate component type part_number: {pn}")
        type_by_part[pn] = component_type
        _string(component_type.get("name"), f"{path}.name", errors)
        _string(component_type.get("description"), f"{path}.description", errors)
        if component_type.get("mobility") not in _MOBILITY:
            errors.append(f"{path}.mobility is not registered")
        _string_list(component_type.get("functional_roles"), f"{path}.functional_roles", errors)
        features = component_type.get("functional_features")
        if not isinstance(features, list) or not features:
            errors.append(f"{path}.functional_features must be a non-empty array")
            features = []
        feature_refs: set[str] = set()
        for feature_index, feature in enumerate(features):
            feature_path = f"{path}.functional_features[{feature_index}]"
            if not _strict_keys(feature, _FEATURE_KEYS, feature_path, errors):
                continue
            ref = _string(feature.get("feature_ref"), f"{feature_path}.feature_ref", errors, identifier=True)
            if ref in feature_refs:
                errors.append(f"duplicate functional feature: {ref}")
            feature_refs.add(ref)
            _string(feature.get("label"), f"{feature_path}.label", errors)
            _string_list(feature.get("semantic_tags"), f"{feature_path}.semantic_tags", errors)
            _string_list(feature.get("aliases"), f"{feature_path}.aliases", errors)
            refs = _string_list(feature.get("source_refs"), f"{feature_path}.source_refs", errors)
            for ref_source in refs:
                if ref_source not in source_ids:
                    errors.append(f"{feature_path}.source_refs contains unknown source: {ref_source}")
        features_by_part[pn] = feature_refs

    instances = graph.get("component_instances")
    if not isinstance(instances, list) or not instances:
        errors.append("graph.component_instances must be a non-empty array")
        instances = []
    instance_by_id: dict[str, Mapping[str, Any]] = {}
    physical_ids: set[str] = set()
    organizational_ids: set[str] = set()
    for index, instance in enumerate(instances):
        path = f"graph.component_instances[{index}]"
        if not _strict_keys(instance, _INSTANCE_KEYS, path, errors):
            continue
        instance_id = _string(instance.get("instance_id"), f"{path}.instance_id", errors, identifier=True)
        if instance_id in instance_by_id:
            errors.append(f"duplicate component instance: {instance_id}")
        instance_by_id[instance_id] = instance
        _string(instance.get("source_component_name"), f"{path}.source_component_name", errors)
        kind = instance.get("kind")
        if kind not in _INSTANCE_KINDS:
            errors.append(f"{path}.kind is not registered")
        part_number = instance.get("part_number")
        if kind == "physical":
            if not isinstance(part_number, str) or part_number not in type_by_part:
                errors.append(f"{path}.part_number must resolve to a component type")
            physical_ids.add(instance_id)
        else:
            if part_number is not None:
                errors.append(f"{path}.part_number must be null for organizational nodes")
            organizational_ids.add(instance_id)
        parent = instance.get("parent_instance_id")
        if parent is not None and not isinstance(parent, str):
            errors.append(f"{path}.parent_instance_id must be a string or null")
        _string(instance.get("occurrence_key"), f"{path}.occurrence_key", errors)
    for instance_id, instance in instance_by_id.items():
        parent = instance.get("parent_instance_id")
        if parent is not None and parent not in instance_by_id:
            errors.append(f"instance {instance_id} references unknown parent: {parent}")

    external_entities = graph.get("external_entities")
    if not isinstance(external_entities, list):
        errors.append("graph.external_entities must be an array")
        external_entities = []
    external_by_id: dict[str, Mapping[str, Any]] = {}
    external_features: dict[str, set[str]] = {}
    for index, entity in enumerate(external_entities):
        path = f"graph.external_entities[{index}]"
        if not _strict_keys(entity, _EXTERNAL_KEYS, path, errors):
            continue
        entity_id = _string(entity.get("entity_id"), f"{path}.entity_id", errors, identifier=True)
        if entity_id in external_by_id or entity_id in instance_by_id:
            errors.append(f"duplicate external entity: {entity_id}")
        external_by_id[entity_id] = entity
        _string(entity.get("name"), f"{path}.name", errors)
        if entity.get("presence") not in _EXTERNAL_PRESENCE:
            errors.append(f"{path}.presence is not registered")
        _string_list(entity.get("functional_roles"), f"{path}.functional_roles", errors)
        refs = _string_list(entity.get("evidence_refs"), f"{path}.evidence_refs", errors)
        for source_ref in refs:
            if source_ref not in source_ids:
                errors.append(f"{path}.evidence_refs contains unknown source: {source_ref}")
        features = entity.get("functional_features")
        if not isinstance(features, list) or not features:
            errors.append(f"{path}.functional_features must be a non-empty array")
            features = []
        refs_for_entity: set[str] = set()
        for feature_index, feature in enumerate(features):
            feature_path = f"{path}.functional_features[{feature_index}]"
            if not _strict_keys(feature, _FEATURE_KEYS, feature_path, errors):
                continue
            ref = _string(feature.get("feature_ref"), f"{feature_path}.feature_ref", errors, identifier=True)
            if ref in refs_for_entity:
                errors.append(f"duplicate external functional feature: {ref}")
            refs_for_entity.add(ref)
            _string(feature.get("label"), f"{feature_path}.label", errors)
            _string_list(feature.get("semantic_tags"), f"{feature_path}.semantic_tags", errors)
            _string_list(feature.get("aliases"), f"{feature_path}.aliases", errors)
            feature_sources = _string_list(feature.get("source_refs"), f"{feature_path}.source_refs", errors)
            for source_ref in feature_sources:
                if source_ref not in source_ids:
                    errors.append(f"{feature_path}.source_refs contains unknown source: {source_ref}")
        external_features[entity_id] = refs_for_entity

    interfaces = graph.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces:
        errors.append("graph.interfaces must be a non-empty array")
        interfaces = []
    interface_ids: set[str] = set()
    covered: set[str] = set()
    for index, interface in enumerate(interfaces):
        path = f"graph.interfaces[{index}]"
        if not _strict_keys(interface, _INTERFACE_KEYS, path, errors):
            continue
        interface_id = _string(interface.get("interface_id"), f"{path}.interface_id", errors, identifier=True)
        if interface_id in interface_ids:
            errors.append(f"duplicate interface_id: {interface_id}")
        interface_ids.add(interface_id)
        _string(interface.get("pattern_id"), f"{path}.pattern_id", errors, identifier=True)
        _string(interface.get("name"), f"{path}.name", errors)
        if interface.get("interface_type") not in _INTERFACE_TYPES:
            errors.append(f"{path}.interface_type is not registered")
        participants = interface.get("participants")
        if not isinstance(participants, list) or len(participants) < 2:
            errors.append(f"{path}.participants must contain at least two entries")
            participants = []
        participant_ids: set[str] = set()
        for participant_index, participant in enumerate(participants):
            participant_path = f"{path}.participants[{participant_index}]"
            if not _strict_keys(participant, _PARTICIPANT_KEYS, participant_path, errors):
                continue
            participant_id = _string(
                participant.get("participant_id"),
                f"{participant_path}.participant_id",
                errors,
                identifier=True,
            )
            if participant_id in participant_ids:
                errors.append(f"{path} repeats participant: {participant_id}")
            participant_ids.add(participant_id)
            feature_refs = _string_list(
                participant.get("feature_refs"), f"{participant_path}.feature_refs", errors
            )
            if participant.get("role") not in _PARTICIPANT_ROLES:
                errors.append(f"{participant_path}.role is not registered")
            if participant_id in instance_by_id:
                expected_part = instance_by_id[participant_id].get("part_number")
                if participant.get("part_number") != expected_part:
                    errors.append(f"{participant_path}.part_number does not match its instance")
                if participant_id in physical_ids:
                    covered.add(participant_id)
                    valid_features = features_by_part.get(str(expected_part), set())
                    for feature_ref in feature_refs:
                        if feature_ref not in valid_features:
                            errors.append(
                                f"{participant_path}.feature_refs contains unknown feature: {feature_ref}"
                            )
            elif participant_id in external_by_id:
                if participant.get("part_number") is not None:
                    errors.append(f"{participant_path}.part_number must be null for external entities")
                for feature_ref in feature_refs:
                    if feature_ref not in external_features.get(participant_id, set()):
                        errors.append(
                            f"{participant_path}.feature_refs contains unknown external feature: {feature_ref}"
                        )
            else:
                errors.append(f"{participant_path}.participant_id does not resolve")
        _string_list(interface.get("functions"), f"{path}.functions", errors)
        motion = interface.get("relative_motion")
        if _strict_keys(motion, _MOTION_KEYS, f"{path}.relative_motion", errors):
            if motion.get("type") not in _MOTION_TYPES:
                errors.append(f"{path}.relative_motion.type is not registered")
            _string_list(motion.get("allowed"), f"{path}.relative_motion.allowed", errors)
            _string_list(motion.get("constrained"), f"{path}.relative_motion.constrained", errors)
        _string_list(interface.get("transfer_modes"), f"{path}.transfer_modes", errors)
        _string_list(
            interface.get("qualitative_requirements"),
            f"{path}.qualitative_requirements",
            errors,
        )
        evidence = interface.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{path}.evidence must be a non-empty array")
            evidence = []
        for evidence_index, item in enumerate(evidence):
            evidence_path = f"{path}.evidence[{evidence_index}]"
            if not _strict_keys(item, _EVIDENCE_KEYS, evidence_path, errors):
                continue
            if item.get("source_ref") not in source_ids:
                errors.append(f"{evidence_path}.source_ref does not resolve")
            _string(item.get("locator"), f"{evidence_path}.locator", errors)
            if item.get("classification") not in _EVIDENCE_CLASSES:
                errors.append(f"{evidence_path}.classification is not registered")
            _string(item.get("claim"), f"{evidence_path}.claim", errors)
        confidence = interface.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            errors.append(f"{path}.confidence must be a number")
        elif not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
            errors.append(f"{path}.confidence must be between zero and one")
        if interface.get("review_status") not in _REVIEW_STATES:
            errors.append(f"{path}.review_status is not registered")

    computed_coverage = {
        "physical_instance_count": len(physical_ids),
        "covered_instance_count": len(physical_ids & covered),
        "uncovered_instance_ids": sorted(physical_ids - covered),
        "organizational_instance_count": len(organizational_ids),
        "external_entity_count": len(external_by_id),
    }
    declared_coverage = graph.get("coverage")
    if _strict_keys(declared_coverage, _COVERAGE_KEYS, "graph.coverage", errors):
        if declared_coverage != computed_coverage:
            errors.append("graph.coverage does not match computed graph coverage")
    if computed_coverage["uncovered_instance_ids"]:
        errors.append("physical component instances are missing functional interfaces")

    if assembly_data is not None:
        source_components = _assembly_component_part_numbers(assembly_data)
        graph_components = {
            str(instance.get("source_component_name")): instance.get("part_number")
            for instance in instances
            if isinstance(instance, dict)
        }
        missing = sorted(set(source_components) - set(graph_components))
        extra = sorted(set(graph_components) - set(source_components))
        if missing:
            errors.append("graph omits assembly component names: " + ", ".join(missing))
        if extra:
            errors.append("graph contains component names absent from assembly: " + ", ".join(extra))
        for name in sorted(set(source_components) & set(graph_components)):
            if source_components[name] != graph_components[name]:
                errors.append(
                    f"component part-number mismatch for {name}: "
                    f"{graph_components[name]!r} != {source_components[name]!r}"
                )

    _walk_forbidden_content(graph, "graph", errors)
    return FunctionalValidationReport(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        coverage=computed_coverage,
    )


class FunctionalRelationshipRegistry:
    """Read-through cache for version-controlled functional graph catalogs."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parent / "catalogs"
        self._cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def path_for(self, assembly_number: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", str(assembly_number or ""))
        if not safe:
            raise FunctionalRelationshipError("invalid assembly number")
        return self.root / f"{safe}.json"

    def load(
        self,
        assembly_number: str,
        *,
        assembly_data: Mapping[str, Any] | None = None,
        strict: bool = True,
    ) -> tuple[dict[str, Any], FunctionalValidationReport]:
        path = self.path_for(assembly_number)
        try:
            stat = path.stat()
        except OSError as exc:
            raise FunctionalRelationshipError(f"functional graph not found for {assembly_number}") from exc
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        with self._lock:
            cached = self._cache.get(str(path))
            if cached and cached[0] == signature:
                graph = copy.deepcopy(cached[1])
            else:
                try:
                    raw = path.read_bytes()
                    graph = json.loads(raw.decode("ascii"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise FunctionalRelationshipError(f"invalid functional graph {path}: {exc}") from exc
                if not isinstance(graph, dict):
                    raise FunctionalRelationshipError(f"functional graph {path} must be an object")
                self._cache[str(path)] = (signature, copy.deepcopy(graph))
        report = validate_functional_relationship_graph(graph, assembly_data=assembly_data)
        if strict and not report.ok:
            raise FunctionalRelationshipError("; ".join(report.errors))
        return graph, report


def _normalized_words(value: Any) -> list[str]:
    return [word for word in _WORD_RE.findall(str(value or "").lower()) if word not in _STOP_WORDS]


def _feature_index(graph: Mapping[str, Any], part_number: str) -> dict[str, Mapping[str, Any]]:
    for component_type in graph.get("component_types") or []:
        if isinstance(component_type, dict) and str(component_type.get("part_number")) == str(part_number):
            return {
                str(feature.get("feature_ref")): feature
                for feature in component_type.get("functional_features") or []
                if isinstance(feature, dict) and feature.get("feature_ref")
            }
    return {}


def _characteristic_id(row: Mapping[str, Any], index: int) -> str:
    for key in ("char_number", "characteristic_number", "number", "id", "balloon"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return str(index + 1)


def _match_feature(
    graph: Mapping[str, Any], part_number: str, row: Mapping[str, Any]
) -> dict[str, Any] | None:
    features = _feature_index(graph, part_number)
    if not features:
        return None
    description = str(row.get("description") or row.get("name") or row.get("feature") or "")
    text = " ".join(_normalized_words(description))
    text_words = set(text.split())
    declared_refs = {
        str(value)
        for key in ("functional_feature_ref", "feature_ref", "semantic_feature_ref")
        for value in ([row.get(key)] if row.get(key) not in (None, "") else [])
    }
    declared_cad = {
        str(value)
        for key in ("cad_feature_id", "cad_feature_ids", "highlight_target_ids")
        for value in (
            row.get(key) if isinstance(row.get(key), list) else [row.get(key)]
        )
        if value not in (None, "")
    }
    feature_kind = str(row.get("fit_feature_kind") or "").strip().lower()
    scored: list[tuple[float, str, list[str]]] = []
    for feature_ref, feature in features.items():
        score = 0.0
        basis: list[str] = []
        if feature_ref in declared_refs:
            score += 20.0
            basis.append("explicit functional feature reference")
        source_refs = set(str(value) for value in feature.get("source_refs") or [])
        if declared_cad & source_refs:
            score += 16.0
            basis.append("shared CAD feature reference")
        aliases = [str(feature.get("label") or ""), *(feature.get("aliases") or [])]
        for alias in aliases:
            alias_words = _normalized_words(alias)
            if not alias_words:
                continue
            alias_text = " ".join(alias_words)
            if alias_text and alias_text in text:
                score = max(score, 9.0 + min(len(alias_words), 4) * 0.5)
                basis.append(f"description matches alias '{alias}'")
                continue
            overlap = len(set(alias_words) & text_words)
            if overlap:
                coverage = overlap / len(set(alias_words))
                if coverage >= 0.75:
                    score = max(score, 4.0 + coverage * 3.0)
                    basis.append(f"description token match '{alias}'")
        semantic_tags = {str(value).lower() for value in feature.get("semantic_tags") or []}
        if feature_kind and feature_kind in semantic_tags:
            score += 2.5
            basis.append(f"feature kind {feature_kind}")
        if score > 0:
            scored.append((score, feature_ref, list(dict.fromkeys(basis))))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    score, feature_ref, basis = scored[0]
    if score < 5.0:
        return None
    feature = features[feature_ref]
    return {
        "feature_ref": feature_ref,
        "label": feature.get("label"),
        "semantic_tags": copy.deepcopy(feature.get("semantic_tags") or []),
        "score": round(score, 3),
        "basis": basis,
    }


def _participant_summary(
    participant: Mapping[str, Any],
    *,
    instances: Mapping[str, Mapping[str, Any]],
    component_types: Mapping[str, Mapping[str, Any]],
    external: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    participant_id = str(participant.get("participant_id") or "")
    if participant_id in instances:
        part_number = str(participant.get("part_number") or "")
        component_type = component_types.get(part_number, {})
        return {
            "part_number": part_number,
            "name": component_type.get("name") or participant_id,
            "role": participant.get("role"),
            "external": False,
            "presence": "present",
        }
    entity = external.get(participant_id, {})
    return {
        "part_number": None,
        "name": entity.get("name") or participant_id,
        "role": participant.get("role"),
        "external": True,
        "presence": entity.get("presence") or "unresolved",
    }


def _compact_patterns(
    graph: Mapping[str, Any],
    interfaces: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    instances = {
        str(item.get("instance_id")): item
        for item in graph.get("component_instances") or []
        if isinstance(item, dict)
    }
    component_types = {
        str(item.get("part_number")): item
        for item in graph.get("component_types") or []
        if isinstance(item, dict)
    }
    external = {
        str(item.get("entity_id")): item
        for item in graph.get("external_entities") or []
        if isinstance(item, dict)
    }
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for interface in interfaces:
        grouped.setdefault(str(interface.get("pattern_id") or interface.get("interface_id")), []).append(interface)
    result = []
    for pattern_id, rows in grouped.items():
        first = rows[0]
        participants: list[dict[str, Any]] = []
        seen_participants: set[tuple[Any, ...]] = set()
        for row in rows:
            for participant in row.get("participants") or []:
                if not isinstance(participant, dict):
                    continue
                summary = _participant_summary(
                    participant,
                    instances=instances,
                    component_types=component_types,
                    external=external,
                )
                key = (
                    summary.get("part_number"),
                    summary.get("name"),
                    summary.get("role"),
                    summary.get("external"),
                )
                if key not in seen_participants:
                    seen_participants.add(key)
                    participants.append(summary)
        missing_external = sorted(
            {
                str(participant["name"])
                for participant in participants
                if participant.get("external") and participant.get("presence") != "present"
            }
        )
        result.append(
            {
                "pattern_id": pattern_id,
                "name": first.get("name"),
                "interface_type": first.get("interface_type"),
                "instance_count": len(rows),
                "participants": participants,
                "functions": copy.deepcopy(first.get("functions") or []),
                "relative_motion": copy.deepcopy(first.get("relative_motion") or {}),
                "transfer_modes": copy.deepcopy(first.get("transfer_modes") or []),
                "qualitative_requirements": copy.deepcopy(
                    first.get("qualitative_requirements") or []
                ),
                "confidence": min(float(row.get("confidence") or 0.0) for row in rows),
                "review_status": first.get("review_status"),
                "missing_external_evidence": missing_external,
                "evidence_refs": sorted(
                    {
                        str(item.get("source_ref"))
                        for row in rows
                        for item in row.get("evidence") or []
                        if isinstance(item, dict) and item.get("source_ref")
                    }
                ),
            }
        )
    result.sort(key=lambda row: (str(row["pattern_id"]), str(row["name"])))
    return result


def build_functional_context(
    graph: Mapping[str, Any],
    *,
    part_number: str | None = None,
    fai_characteristics: Iterable[Mapping[str, Any]] | None = None,
    max_patterns: int = 16,
) -> dict[str, Any]:
    """Build compact prompt/API context and deterministic FAI feature joins."""
    part_number = str(part_number or "").strip()
    all_interfaces = [item for item in graph.get("interfaces") or [] if isinstance(item, dict)]
    if part_number:
        relevant_interfaces = [
            interface
            for interface in all_interfaces
            if any(
                isinstance(participant, dict)
                and str(participant.get("part_number") or "") == part_number
                for participant in interface.get("participants") or []
            )
        ]
    else:
        relevant_interfaces = all_interfaces
    compact = _compact_patterns(graph, relevant_interfaces)[:max_patterns]

    affected: list[dict[str, Any]] = []
    seen_affected: set[tuple[str, str]] = set()
    for index, raw in enumerate(fai_characteristics or []):
        if not isinstance(raw, Mapping):
            continue
        status = str(raw.get("status") or raw.get("computed_status") or "").upper()
        if status not in {"FAIL", "WARN"}:
            continue
        match = _match_feature(graph, part_number, raw)
        if not match:
            continue
        characteristic_id = _characteristic_id(raw, index)
        matched_interfaces = []
        for interface in relevant_interfaces:
            if any(
                isinstance(participant, dict)
                and str(participant.get("part_number") or "") == part_number
                and match["feature_ref"] in (participant.get("feature_refs") or [])
                for participant in interface.get("participants") or []
            ):
                matched_interfaces.append(interface)
        for pattern in _compact_patterns(graph, matched_interfaces):
            key = (characteristic_id, str(pattern["pattern_id"]))
            if key in seen_affected:
                continue
            seen_affected.add(key)
            direct_rows = [
                row
                for row in matched_interfaces
                if str(row.get("pattern_id")) == str(pattern["pattern_id"])
            ]
            bridge_ids = {
                str(participant.get("participant_id"))
                for row in direct_rows
                for participant in row.get("participants") or []
                if isinstance(participant, dict)
                and str(participant.get("part_number") or "") != part_number
                and str(participant.get("participant_id") or "").startswith("instance:")
            }
            adjacent_rows = [
                row
                for row in all_interfaces
                if row not in direct_rows
                and any(
                    isinstance(participant, dict)
                    and str(participant.get("participant_id") or "") in bridge_ids
                    for participant in row.get("participants") or []
                )
            ]
            affected.append(
                {
                    "characteristic_id": characteristic_id,
                    "controlled_feature": copy.deepcopy(match),
                    "interface": pattern,
                    "adjacent_interfaces": _compact_patterns(graph, adjacent_rows)[:4],
                    "join_classification": "deterministic_semantic_match",
                    "inference_boundary": (
                        "The join identifies normal function and qualitative requirements only; "
                        "the deviation consequence still depends on the separate FAI evidence."
                    ),
                }
            )

    provenance = []
    for item in affected:
        interface = item["interface"]
        evidence_refs = interface.get("evidence_refs") or []
        provenance.append(
            {
                "evidence_id": (
                    f"functional.{graph.get('assembly', {}).get('part_number')}."
                    f"{interface.get('pattern_id')}"
                ),
                "classification": "product_function_fact"
                if interface.get("review_status") == "verified"
                else "reviewed_engineering_inference",
                "value": interface.get("name"),
                "source_refs": evidence_refs,
                "based_on": [
                    f"fai.{item['characteristic_id']}.controlled_feature",
                    *[f"source.{source_ref}" for source_ref in evidence_refs],
                ],
            }
        )

    assembly = graph.get("assembly") if isinstance(graph.get("assembly"), dict) else {}
    coverage = graph.get("coverage") if isinstance(graph.get("coverage"), dict) else {}
    return {
        "functional_relationship_summary": {
            "graph_id": graph.get("graph_id"),
            "graph_version": graph.get("version"),
            "assembly_number": assembly.get("part_number"),
            "assembly_name": assembly.get("name"),
            "inspected_part_number": part_number or None,
            "interface_pattern_count": len(compact),
            "physical_instance_count": coverage.get("physical_instance_count"),
            "covered_instance_count": coverage.get("covered_instance_count"),
            "external_entities": [
                {
                    "entity_id": item.get("entity_id"),
                    "name": item.get("name"),
                    "presence": item.get("presence"),
                }
                for item in graph.get("external_entities") or []
                if isinstance(item, dict)
            ],
        },
        "functional_relationships": compact,
        "affected_functional_interfaces": affected,
        "functional_relationship_provenance": provenance,
    }
