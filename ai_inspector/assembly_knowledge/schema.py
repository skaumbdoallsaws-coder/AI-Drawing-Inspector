"""Strict schema validation for Assembly Knowledge Package documents."""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION = 1
KNOWLEDGE_STATUSES = frozenset({"derived", "inferred", "authored", "unknown"})
AUTHORITIES = frozenset(
    {"approved", "authored", "illustrative", "supporting", "untrusted"}
)
READINESS_LEVELS = frozenset(
    {"structure_ready", "function_ready", "planning_ready", "production_ready"}
)
REVIEW_STATUSES = frozenset(
    {"pending", "confirmed", "edited", "rejected", "unknown", "deferred"}
)
OCCURRENCE_KINDS = frozenset({"assembly", "subassembly", "part"})
SOURCE_TYPES = frozenset(
    {
        "assembly_structure",
        "mate_relationship",
        "geometry",
        "property",
        "visual",
        "domain_heuristic",
        "user_statement",
        "procedure",
        "work_instruction",
        "standard",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PACKAGE_ID_RE = re.compile(r"^akp-[a-f0-9]{8,64}$")

Finding = Dict[str, Any]
Validator = Callable[[Any, str, List[Finding]], None]


class AssemblyKnowledgeSchemaError(ValueError):
    def __init__(self, findings: Sequence[Finding]):
        self.findings = list(findings)
        message = "; ".join(
            f"{item.get('path', '$')}: {item.get('message', 'invalid value')}"
            for item in self.findings[:8]
        )
        super().__init__(message or "assembly knowledge schema validation failed")


def _finding(
    findings: List[Finding],
    path: str,
    code: str,
    message: str,
    *,
    severity: str = "error",
) -> None:
    findings.append(
        {"severity": severity, "code": code, "path": path, "message": message}
    )


def _object(value: Any, path: str, findings: List[Finding]) -> bool:
    if not isinstance(value, dict):
        _finding(findings, path, "expected_object", "Value must be an object.")
        return False
    return True


def _list(value: Any, path: str, findings: List[Finding]) -> bool:
    if not isinstance(value, list):
        _finding(findings, path, "expected_array", "Value must be an array.")
        return False
    return True


def _string(
    value: Any,
    path: str,
    findings: List[Finding],
    *,
    allow_empty: bool = False,
    maximum: int = 2000,
) -> bool:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value) > maximum
    ):
        qualifier = "a string" if allow_empty else "a non-empty string"
        _finding(
            findings,
            path,
            "invalid_string",
            f"Value must be {qualifier} of at most {maximum} characters.",
        )
        return False
    return True


def _identifier(value: Any, path: str, findings: List[Finding]) -> bool:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _finding(
            findings,
            path,
            "invalid_identifier",
            "Value must be a stable identifier of at most 160 characters.",
        )
        return False
    return True


def _sha256(value: Any, path: str, findings: List[Finding]) -> bool:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _finding(
            findings,
            path,
            "invalid_sha256",
            "Value must be a lowercase SHA-256 digest.",
        )
        return False
    return True


def _integer(
    value: Any,
    path: str,
    findings: List[Finding],
    *,
    minimum: int = 0,
) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _finding(
            findings,
            path,
            "invalid_integer",
            f"Value must be an integer greater than or equal to {minimum}.",
        )
        return False
    return True


def _number(value: Any, path: str, findings: List[Finding]) -> bool:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        _finding(findings, path, "invalid_number", "Value must be finite.")
        return False
    return True


def _enum(
    value: Any,
    allowed: Iterable[str],
    path: str,
    findings: List[Finding],
) -> bool:
    choices = frozenset(allowed)
    if value not in choices:
        _finding(
            findings,
            path,
            "invalid_enum",
            f"Value must be one of: {', '.join(sorted(choices))}.",
        )
        return False
    return True


def _strict_fields(
    value: Mapping[str, Any],
    path: str,
    findings: List[Finding],
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required_set = frozenset(required)
    allowed = required_set | frozenset(optional)
    for key in sorted(required_set - set(value)):
        _finding(
            findings,
            f"{path}.{key}",
            "missing_required_field",
            "Required field is missing.",
        )
    unknown = sorted(set(value) - allowed)
    for key in unknown:
        _finding(
            findings,
            f"{path}.{key}",
            "unknown_field",
            "Unknown fields are not accepted.",
        )


def _schema_version(value: Mapping[str, Any], path: str, findings: List[Finding]) -> None:
    if value.get("schemaVersion") != ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION:
        _finding(
            findings,
            f"{path}.schemaVersion",
            "unsupported_schema_version",
            f"schemaVersion must equal {ASSEMBLY_KNOWLEDGE_SCHEMA_VERSION}.",
        )


def _validate_finding(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"findingId", "severity", "code", "message"},
        optional={"subjectRefs", "evidenceRefs", "details"},
    )
    _identifier(value.get("findingId"), f"{path}.findingId", findings)
    _enum(value.get("severity"), {"info", "warning", "error"}, f"{path}.severity", findings)
    _identifier(value.get("code"), f"{path}.code", findings)
    _string(value.get("message"), f"{path}.message", findings)
    for field in ("subjectRefs", "evidenceRefs"):
        if field in value and _list(value[field], f"{path}.{field}", findings):
            for index, item in enumerate(value[field]):
                _identifier(item, f"{path}.{field}[{index}]", findings)


def _validate_claim(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={
            "claimId",
            "subjectRef",
            "predicate",
            "objectRefs",
            "value",
            "knowledgeStatus",
            "authority",
            "evidenceRefs",
            "assumptionIds",
            "generatedBy",
            "reviewStatus",
        },
    )
    for field in ("claimId", "subjectRef", "predicate"):
        _identifier(value.get(field), f"{path}.{field}", findings)
    for field in ("objectRefs", "evidenceRefs", "assumptionIds"):
        if _list(value.get(field), f"{path}.{field}", findings):
            for index, item in enumerate(value[field]):
                _identifier(item, f"{path}.{field}[{index}]", findings)
    _enum(
        value.get("knowledgeStatus"),
        KNOWLEDGE_STATUSES,
        f"{path}.knowledgeStatus",
        findings,
    )
    _enum(value.get("authority"), AUTHORITIES, f"{path}.authority", findings)
    _enum(
        value.get("reviewStatus"),
        REVIEW_STATUSES,
        f"{path}.reviewStatus",
        findings,
    )
    generated = value.get("generatedBy")
    if _object(generated, f"{path}.generatedBy", findings):
        _strict_fields(
            generated,
            f"{path}.generatedBy",
            findings,
            required={"kind", "generatorId", "version"},
        )
        _enum(
            generated.get("kind"),
            {"deterministic", "model", "user"},
            f"{path}.generatedBy.kind",
            findings,
        )
        _string(generated.get("generatorId"), f"{path}.generatedBy.generatorId", findings)
        _string(generated.get("version"), f"{path}.generatedBy.version", findings)


def _validate_package(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={
            "schemaVersion",
            "packageId",
            "productId",
            "sourceRevision",
            "packageRevision",
            "extractorVersion",
            "adapterVersion",
            "bridgePackageSchemaVersion",
            "enrichmentPolicyVersion",
            "promptVersion",
            "modelProvider",
            "modelId",
            "readiness",
            "productionEligible",
            "documentHashes",
            "assetHashes",
        },
        optional={"enrichmentReceipt"},
    )
    _schema_version(value, path, findings)
    if not isinstance(value.get("packageId"), str) or _PACKAGE_ID_RE.fullmatch(
        value["packageId"]
    ) is None:
        _finding(
            findings,
            f"{path}.packageId",
            "invalid_package_id",
            "packageId must be an akp-prefixed stable hash.",
        )
    _identifier(value.get("productId"), f"{path}.productId", findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    _sha256(value.get("packageRevision"), f"{path}.packageRevision", findings)
    for field in (
        "extractorVersion",
        "adapterVersion",
        "bridgePackageSchemaVersion",
        "enrichmentPolicyVersion",
        "promptVersion",
    ):
        _string(value.get(field), f"{path}.{field}", findings, maximum=120)
    for field in ("modelProvider", "modelId"):
        if value.get(field) is not None:
            _string(value.get(field), f"{path}.{field}", findings, maximum=160)
    _enum(value.get("readiness"), READINESS_LEVELS, f"{path}.readiness", findings)
    if not isinstance(value.get("productionEligible"), bool):
        _finding(
            findings,
            f"{path}.productionEligible",
            "invalid_boolean",
            "productionEligible must be a boolean.",
        )
    for field in ("documentHashes", "assetHashes"):
        hashes = value.get(field)
        if _object(hashes, f"{path}.{field}", findings):
            for key, digest in hashes.items():
                _string(key, f"{path}.{field}.<path>", findings, maximum=500)
                _sha256(digest, f"{path}.{field}.{key}", findings)
    receipt = value.get("enrichmentReceipt")
    if receipt is not None and _object(
        receipt, f"{path}.enrichmentReceipt", findings
    ):
        _strict_fields(
            receipt,
            f"{path}.enrichmentReceipt",
            findings,
            required={
                "authorizationId",
                "requestFingerprint",
                "cacheKey",
                "evidenceFingerprint",
                "policyVersion",
                "promptVersion",
                "provider",
                "model",
                "imageHashes",
                "usage",
                "pricingConfidence",
                "estimatedMaximumCostUsd",
                "fromCache",
            },
        )
        for field in (
            "authorizationId",
            "policyVersion",
            "promptVersion",
            "provider",
            "model",
            "pricingConfidence",
        ):
            _string(
                receipt.get(field),
                f"{path}.enrichmentReceipt.{field}",
                findings,
                maximum=160,
            )
        for field in ("requestFingerprint", "cacheKey", "evidenceFingerprint"):
            _sha256(
                receipt.get(field),
                f"{path}.enrichmentReceipt.{field}",
                findings,
            )
        if _list(
            receipt.get("imageHashes"),
            f"{path}.enrichmentReceipt.imageHashes",
            findings,
        ):
            for index, digest in enumerate(receipt["imageHashes"]):
                _sha256(
                    digest,
                    f"{path}.enrichmentReceipt.imageHashes[{index}]",
                    findings,
                )
        usage = receipt.get("usage")
        if _object(usage, f"{path}.enrichmentReceipt.usage", findings):
            _strict_fields(
                usage,
                f"{path}.enrichmentReceipt.usage",
                findings,
                required={
                    "inputTokens",
                    "outputTokens",
                    "totalTokens",
                    "imageCount",
                    "providerAttempts",
                    "schemaCorrections",
                },
            )
            for field in (
                "inputTokens",
                "outputTokens",
                "totalTokens",
                "imageCount",
                "providerAttempts",
                "schemaCorrections",
            ):
                _integer(
                    usage.get(field),
                    f"{path}.enrichmentReceipt.usage.{field}",
                    findings,
                )
        estimated_cost = receipt.get("estimatedMaximumCostUsd")
        if estimated_cost is not None:
            _number(
                estimated_cost,
                f"{path}.enrichmentReceipt.estimatedMaximumCostUsd",
                findings,
            )
        if not isinstance(receipt.get("fromCache"), bool):
            _finding(
                findings,
                f"{path}.enrichmentReceipt.fromCache",
                "invalid_boolean",
                "fromCache must be a boolean.",
            )


def _validate_source_manifest(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={
            "schemaVersion",
            "productId",
            "rootAssembly",
            "configuration",
            "sources",
            "extractor",
            "sourceRevision",
            "preflightFingerprint",
            "findings",
        },
    )
    _schema_version(value, path, findings)
    _identifier(value.get("productId"), f"{path}.productId", findings)
    for field in ("sourceRevision", "preflightFingerprint"):
        _sha256(value.get(field), f"{path}.{field}", findings)
    root = value.get("rootAssembly")
    if _object(root, f"{path}.rootAssembly", findings):
        _strict_fields(
            root,
            f"{path}.rootAssembly",
            findings,
            required={"sourceId", "path", "sha256", "size", "kind", "available"},
        )
        _identifier(root.get("sourceId"), f"{path}.rootAssembly.sourceId", findings)
        _string(root.get("path"), f"{path}.rootAssembly.path", findings, maximum=1000)
        _sha256(root.get("sha256"), f"{path}.rootAssembly.sha256", findings)
        _integer(root.get("size"), f"{path}.rootAssembly.size", findings)
        _enum(
            root.get("kind"),
            {"assembly"},
            f"{path}.rootAssembly.kind",
            findings,
        )
        if not isinstance(root.get("available"), bool):
            _finding(
                findings,
                f"{path}.rootAssembly.available",
                "invalid_boolean",
                "available must be a boolean.",
            )
    config = value.get("configuration")
    if _object(config, f"{path}.configuration", findings):
        _strict_fields(
            config,
            f"{path}.configuration",
            findings,
            required={"active", "available"},
        )
        _string(config.get("active"), f"{path}.configuration.active", findings)
        if _list(config.get("available"), f"{path}.configuration.available", findings):
            for index, item in enumerate(config["available"]):
                _string(item, f"{path}.configuration.available[{index}]", findings)
    if _list(value.get("sources"), f"{path}.sources", findings):
        seen = set()
        for index, source in enumerate(value["sources"]):
            item_path = f"{path}.sources[{index}]"
            if not _object(source, item_path, findings):
                continue
            _strict_fields(
                source,
                item_path,
                findings,
                required={"sourceId", "path", "sha256", "size", "kind", "available"},
            )
            source_id = source.get("sourceId")
            if _identifier(source_id, f"{item_path}.sourceId", findings):
                if source_id in seen:
                    _finding(
                        findings,
                        f"{item_path}.sourceId",
                        "duplicate_source_id",
                        "sourceId must be unique.",
                    )
                seen.add(source_id)
            _string(source.get("path"), f"{item_path}.path", findings, maximum=1000)
            _sha256(source.get("sha256"), f"{item_path}.sha256", findings)
            _integer(source.get("size"), f"{item_path}.size", findings)
            _enum(
                source.get("kind"),
                {
                    "assembly",
                    "part",
                    "routing",
                    "stage_details",
                    "inspection_plan",
                    "test_procedure",
                    "resource_register",
                    "assumption_register",
                    "work_instruction",
                },
                f"{item_path}.kind",
                findings,
            )
            if not isinstance(source.get("available"), bool):
                _finding(
                    findings,
                    f"{item_path}.available",
                    "invalid_boolean",
                    "available must be a boolean.",
                )
    extractor = value.get("extractor")
    if _object(extractor, f"{path}.extractor", findings):
        _strict_fields(
            extractor,
            f"{path}.extractor",
            findings,
            required={
                "name",
                "version",
                "adapterVersion",
                "packageSchemaVersion",
                "solidWorksVersion",
            },
        )
        for field in extractor:
            _string(extractor[field], f"{path}.extractor.{field}", findings, maximum=160)
    if _list(value.get("findings"), f"{path}.findings", findings):
        for index, item in enumerate(value["findings"]):
            _validate_finding(item, f"{path}.findings[{index}]", findings)


def _validate_transform(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"translation", "rotation", "scale"},
        optional={"quaternion"},
    )
    for field, length in (("translation", 3), ("rotation", 9), ("quaternion", 4)):
        if field not in value:
            continue
        if _list(value[field], f"{path}.{field}", findings):
            if len(value[field]) != length:
                _finding(
                    findings,
                    f"{path}.{field}",
                    "invalid_vector_length",
                    f"{field} must contain {length} values.",
                )
            for index, item in enumerate(value[field]):
                _number(item, f"{path}.{field}[{index}]", findings)
    _number(value.get("scale"), f"{path}.scale", findings)


def _validate_product_structure(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={
            "schemaVersion",
            "productId",
            "sourceRevision",
            "configuration",
            "rootOccurrenceId",
            "occurrences",
        },
    )
    _schema_version(value, path, findings)
    _identifier(value.get("productId"), f"{path}.productId", findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    _string(value.get("configuration"), f"{path}.configuration", findings)
    _identifier(value.get("rootOccurrenceId"), f"{path}.rootOccurrenceId", findings)
    occurrence_ids = set()
    occurrences = value.get("occurrences")
    if _list(occurrences, f"{path}.occurrences", findings):
        for index, occurrence in enumerate(occurrences):
            item_path = f"{path}.occurrences[{index}]"
            if not _object(occurrence, item_path, findings):
                continue
            _strict_fields(
                occurrence,
                item_path,
                findings,
                required={
                    "occurrenceId",
                    "sourceOccurrenceId",
                    "parentOccurrenceId",
                    "itemId",
                    "name",
                    "kind",
                    "level",
                    "sourceId",
                    "sourcePath",
                    "sourceHash",
                    "configuration",
                    "quantity",
                    "state",
                    "transform",
                    "properties",
                },
            )
            occurrence_id = occurrence.get("occurrenceId")
            if _identifier(occurrence_id, f"{item_path}.occurrenceId", findings):
                if occurrence_id in occurrence_ids:
                    _finding(
                        findings,
                        f"{item_path}.occurrenceId",
                        "duplicate_occurrence_id",
                        "occurrenceId must be unique.",
                    )
                occurrence_ids.add(occurrence_id)
            for field in ("sourceOccurrenceId", "itemId", "sourceId"):
                _identifier(occurrence.get(field), f"{item_path}.{field}", findings)
            parent = occurrence.get("parentOccurrenceId")
            if parent is not None:
                _identifier(parent, f"{item_path}.parentOccurrenceId", findings)
            _string(occurrence.get("name"), f"{item_path}.name", findings)
            _enum(
                occurrence.get("kind"),
                OCCURRENCE_KINDS,
                f"{item_path}.kind",
                findings,
            )
            _integer(occurrence.get("level"), f"{item_path}.level", findings)
            _string(
                occurrence.get("sourcePath"),
                f"{item_path}.sourcePath",
                findings,
                maximum=1000,
            )
            _sha256(occurrence.get("sourceHash"), f"{item_path}.sourceHash", findings)
            _string(
                occurrence.get("configuration"),
                f"{item_path}.configuration",
                findings,
                allow_empty=True,
            )
            _integer(
                occurrence.get("quantity"),
                f"{item_path}.quantity",
                findings,
                minimum=1,
            )
            state = occurrence.get("state")
            if _object(state, f"{item_path}.state", findings):
                _strict_fields(
                    state,
                    f"{item_path}.state",
                    findings,
                    required={"resolved", "lightweight", "suppressed", "hidden", "virtual"},
                )
                for field in state:
                    if state[field] is not None and not isinstance(state[field], bool):
                        _finding(
                            findings,
                            f"{item_path}.state.{field}",
                            "invalid_boolean",
                            f"{field} must be a boolean or null when unavailable.",
                        )
            if occurrence.get("transform") is not None:
                _validate_transform(
                    occurrence.get("transform"),
                    f"{item_path}.transform",
                    findings,
                )
            if not isinstance(occurrence.get("properties"), dict):
                _finding(
                    findings,
                    f"{item_path}.properties",
                    "expected_object",
                    "properties must be an object.",
                )
        for index, occurrence in enumerate(occurrences):
            if not isinstance(occurrence, dict):
                continue
            parent = occurrence.get("parentOccurrenceId")
            if parent is not None and parent not in occurrence_ids:
                _finding(
                    findings,
                    f"{path}.occurrences[{index}].parentOccurrenceId",
                    "dangling_parent_occurrence",
                    "parentOccurrenceId does not reference a known occurrence.",
                )
    if value.get("rootOccurrenceId") not in occurrence_ids:
        _finding(
            findings,
            f"{path}.rootOccurrenceId",
            "unknown_root_occurrence",
            "rootOccurrenceId must reference a known occurrence.",
        )


def _validate_interface_graph(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"schemaVersion", "sourceRevision", "mates", "interfaces"},
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    if _list(value.get("mates"), f"{path}.mates", findings):
        seen = set()
        for index, mate in enumerate(value["mates"]):
            item_path = f"{path}.mates[{index}]"
            if not _object(mate, item_path, findings):
                continue
            _strict_fields(
                mate,
                item_path,
                findings,
                required={
                    "mateId",
                    "displayName",
                    "type",
                    "occurrenceRefs",
                    "suppressed",
                    "alignment",
                    "distance",
                    "angle",
                    "entities",
                    "identityStrength",
                },
            )
            mate_id = mate.get("mateId")
            if _identifier(mate_id, f"{item_path}.mateId", findings):
                if mate_id in seen:
                    _finding(
                        findings,
                        f"{item_path}.mateId",
                        "duplicate_mate_id",
                        "mateId must be unique.",
                    )
                seen.add(mate_id)
            _string(mate.get("displayName"), f"{item_path}.displayName", findings)
            _string(mate.get("type"), f"{item_path}.type", findings)
            if _list(mate.get("occurrenceRefs"), f"{item_path}.occurrenceRefs", findings):
                if len(mate["occurrenceRefs"]) != 2:
                    _finding(
                        findings,
                        f"{item_path}.occurrenceRefs",
                        "invalid_mate_arity",
                        "A v1 mate must identify two participating occurrences.",
                    )
                for ref_index, ref in enumerate(mate["occurrenceRefs"]):
                    _identifier(
                        ref,
                        f"{item_path}.occurrenceRefs[{ref_index}]",
                        findings,
                    )
            if not isinstance(mate.get("suppressed"), bool):
                _finding(
                    findings,
                    f"{item_path}.suppressed",
                    "invalid_boolean",
                    "suppressed must be a boolean.",
                )
            _string(
                mate.get("alignment"),
                f"{item_path}.alignment",
                findings,
                allow_empty=True,
            )
            _number(mate.get("distance"), f"{item_path}.distance", findings)
            _number(mate.get("angle"), f"{item_path}.angle", findings)
            _enum(
                mate.get("identityStrength"),
                {"strong", "weak"},
                f"{item_path}.identityStrength",
                findings,
            )
            if _list(mate.get("entities"), f"{item_path}.entities", findings):
                for entity_index, entity in enumerate(mate["entities"]):
                    entity_path = f"{item_path}.entities[{entity_index}]"
                    if not _object(entity, entity_path, findings):
                        continue
                    _strict_fields(
                        entity,
                        entity_path,
                        findings,
                        required={
                            "occurrenceRef",
                            "entityType",
                            "geometryType",
                            "point",
                            "direction",
                            "radius",
                        },
                    )
                    _identifier(
                        entity.get("occurrenceRef"),
                        f"{entity_path}.occurrenceRef",
                        findings,
                    )
                    _string(
                        entity.get("entityType"),
                        f"{entity_path}.entityType",
                        findings,
                    )
                    if entity.get("geometryType") is not None:
                        _string(
                            entity.get("geometryType"),
                            f"{entity_path}.geometryType",
                            findings,
                        )
                    for field in ("point", "direction"):
                        if _list(entity.get(field), f"{entity_path}.{field}", findings):
                            if len(entity[field]) not in (0, 3):
                                _finding(
                                    findings,
                                    f"{entity_path}.{field}",
                                    "invalid_vector_length",
                                    f"{field} must be empty or contain three values.",
                                )
                            for item_index, item in enumerate(entity[field]):
                                _number(
                                    item,
                                    f"{entity_path}.{field}[{item_index}]",
                                    findings,
                                )
                    _number(entity.get("radius"), f"{entity_path}.radius", findings)
    if _list(value.get("interfaces"), f"{path}.interfaces", findings):
        for index, interface in enumerate(value["interfaces"]):
            item_path = f"{path}.interfaces[{index}]"
            if not _object(interface, item_path, findings):
                continue
            _strict_fields(
                interface,
                item_path,
                findings,
                required={
                    "interfaceId",
                    "occurrenceRefs",
                    "mateRefs",
                    "geometryRefs",
                    "status",
                },
            )
            _identifier(interface.get("interfaceId"), f"{item_path}.interfaceId", findings)
            for field in ("occurrenceRefs", "mateRefs", "geometryRefs"):
                if _list(interface.get(field), f"{item_path}.{field}", findings):
                    for ref_index, ref in enumerate(interface[field]):
                        _identifier(ref, f"{item_path}.{field}[{ref_index}]", findings)
            _enum(
                interface.get("status"),
                {"derived", "candidate", "unknown"},
                f"{item_path}.status",
                findings,
            )


def _validate_generic_claim_document(
    value: Any,
    path: str,
    findings: List[Finding],
    *,
    extra_required: Iterable[str] = (),
    extra_optional: Iterable[str] = (),
) -> None:
    if not _object(value, path, findings):
        return
    required = {
        "schemaVersion",
        "sourceRevision",
        "evidenceFingerprint",
        "claims",
    } | set(extra_required)
    _strict_fields(
        value,
        path,
        findings,
        required=required,
        optional=set(extra_optional),
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    _sha256(
        value.get("evidenceFingerprint"),
        f"{path}.evidenceFingerprint",
        findings,
    )
    if _list(value.get("claims"), f"{path}.claims", findings):
        seen = set()
        for index, claim in enumerate(value["claims"]):
            _validate_claim(claim, f"{path}.claims[{index}]", findings)
            if isinstance(claim, dict) and isinstance(claim.get("claimId"), str):
                if claim["claimId"] in seen:
                    _finding(
                        findings,
                        f"{path}.claims[{index}].claimId",
                        "duplicate_claim_id",
                        "claimId must be unique.",
                    )
                seen.add(claim["claimId"])


def _validate_work_instruction_benchmarks(
    value: Any,
    path: str,
    findings: List[Finding],
) -> None:
    if not _list(value, path, findings):
        return
    seen_stage_ids: set[str] = set()
    seen_operation_ids: set[str] = set()
    for stage_index, stage in enumerate(value):
        stage_path = f"{path}[{stage_index}]"
        if not _object(stage, stage_path, findings):
            continue
        _strict_fields(
            stage,
            stage_path,
            findings,
            required={
                "stageOperationId",
                "benchmarkStatus",
                "operationPages",
                "authorization",
                "documentId",
                "documentRevision",
                "sourceRef",
                "evidenceRef",
                "evidenceClass",
                "benchmarkHash",
            },
        )
        stage_id = stage.get("stageOperationId")
        if _identifier(stage_id, f"{stage_path}.stageOperationId", findings):
            if stage_id in seen_stage_ids:
                _finding(
                    findings,
                    f"{stage_path}.stageOperationId",
                    "duplicate_work_instruction_benchmark",
                    "Benchmark stage IDs must be unique.",
                )
            seen_stage_ids.add(stage_id)
        _enum(
            stage.get("benchmarkStatus"),
            {"approved_for_synthetic_demonstration"},
            f"{stage_path}.benchmarkStatus",
            findings,
        )
        for field in (
            "documentId",
            "documentRevision",
            "sourceRef",
            "evidenceRef",
            "evidenceClass",
        ):
            _string(stage.get(field), f"{stage_path}.{field}", findings)
        _sha256(stage.get("benchmarkHash"), f"{stage_path}.benchmarkHash", findings)
        authorization = stage.get("authorization")
        if _object(authorization, f"{stage_path}.authorization", findings):
            _strict_fields(
                authorization,
                f"{stage_path}.authorization",
                findings,
                required={
                    "status",
                    "approvedForSyntheticDemonstration",
                    "manufacturingApproval",
                    "controlledReleaseAuthority",
                    "scope",
                    "limitation",
                },
            )
            _enum(
                authorization.get("status"),
                {"approved_for_synthetic_demonstration"},
                f"{stage_path}.authorization.status",
                findings,
            )
            if authorization.get("approvedForSyntheticDemonstration") is not True:
                _finding(
                    findings,
                    f"{stage_path}.authorization.approvedForSyntheticDemonstration",
                    "invalid_demo_authority",
                    "Synthetic demonstration approval must be explicit.",
                )
            for field in ("manufacturingApproval", "controlledReleaseAuthority"):
                if authorization.get(field) is not False:
                    _finding(
                        findings,
                        f"{stage_path}.authorization.{field}",
                        "invalid_production_authority",
                        f"{field} must remain false for synthetic evidence.",
                    )
            _string(
                authorization.get("scope"),
                f"{stage_path}.authorization.scope",
                findings,
            )
            _string(
                authorization.get("limitation"),
                f"{stage_path}.authorization.limitation",
                findings,
            )
        operations = stage.get("operationPages")
        if not _list(operations, f"{stage_path}.operationPages", findings):
            continue
        for operation_index, operation in enumerate(operations):
            operation_path = f"{stage_path}.operationPages[{operation_index}]"
            if not _object(operation, operation_path, findings):
                continue
            _strict_fields(
                operation,
                operation_path,
                findings,
                required={
                    "operationId",
                    "sequenceLabel",
                    "title",
                    "predecessorOperationIds",
                    "parts",
                    "resourceRefs",
                    "tools",
                    "materials",
                    "ppe",
                    "actions",
                    "keyPoints",
                    "specifications",
                    "qualityChecks",
                    "safetyControls",
                    "recordRequirement",
                    "scene",
                },
                optional={"transitionGate"},
            )
            operation_id = operation.get("operationId")
            if _identifier(
                operation_id,
                f"{operation_path}.operationId",
                findings,
            ):
                if operation_id in seen_operation_ids:
                    _finding(
                        findings,
                        f"{operation_path}.operationId",
                        "duplicate_work_instruction_operation",
                        "Benchmark operation IDs must be package-unique.",
                    )
                seen_operation_ids.add(operation_id)
            _string(
                operation.get("sequenceLabel"),
                f"{operation_path}.sequenceLabel",
                findings,
            )
            _string(operation.get("title"), f"{operation_path}.title", findings)
            for list_field in (
                "predecessorOperationIds",
                "resourceRefs",
                "ppe",
                "actions",
                "keyPoints",
            ):
                rows = operation.get(list_field)
                if _list(rows, f"{operation_path}.{list_field}", findings):
                    for row_index, row in enumerate(rows):
                        validator = _identifier if list_field in {
                            "predecessorOperationIds",
                            "resourceRefs",
                        } else _string
                        validator(
                            row,
                            f"{operation_path}.{list_field}[{row_index}]",
                            findings,
                        )
            for collection, required_fields in (
                ("parts", {"partNumber", "quantity", "role"}),
                ("tools", {"toolId", "description"}),
                ("materials", {"materialId", "description"}),
                (
                    "specifications",
                    {"specificationId", "label", "value", "sourceLocator"},
                ),
                (
                    "qualityChecks",
                    {"checkId", "method", "criterion", "recordField"},
                ),
                (
                    "safetyControls",
                    {"controlId", "signalWord", "text"},
                ),
            ):
                rows = operation.get(collection)
                if not _list(rows, f"{operation_path}.{collection}", findings):
                    continue
                for row_index, row in enumerate(rows):
                    row_path = f"{operation_path}.{collection}[{row_index}]"
                    if not _object(row, row_path, findings):
                        continue
                    _strict_fields(
                        row,
                        row_path,
                        findings,
                        required=required_fields,
                    )
                    for field in required_fields - {"quantity"}:
                        _string(row.get(field), f"{row_path}.{field}", findings)
                    if "quantity" in required_fields:
                        _integer(
                            row.get("quantity"),
                            f"{row_path}.quantity",
                            findings,
                            minimum=1,
                        )
            record = operation.get("recordRequirement")
            if _object(record, f"{operation_path}.recordRequirement", findings):
                _strict_fields(
                    record,
                    f"{operation_path}.recordRequirement",
                    findings,
                    required={"recordId", "fields"},
                )
                _string(
                    record.get("recordId"),
                    f"{operation_path}.recordRequirement.recordId",
                    findings,
                )
                fields = record.get("fields")
                if _list(
                    fields,
                    f"{operation_path}.recordRequirement.fields",
                    findings,
                ):
                    for field_index, field in enumerate(fields):
                        _string(
                            field,
                            f"{operation_path}.recordRequirement.fields[{field_index}]",
                            findings,
                        )
            transition_gate = operation.get("transitionGate")
            if transition_gate is not None and _object(
                transition_gate,
                f"{operation_path}.transitionGate",
                findings,
            ):
                gate_path = f"{operation_path}.transitionGate"
                _strict_fields(
                    transition_gate,
                    gate_path,
                    findings,
                    required={
                        "gateId",
                        "targetStageOperationId",
                        "requiredCheckIds",
                        "requiredRecordId",
                        "satisfiedState",
                        "failureState",
                        "blocking",
                    },
                )
                for field in (
                    "gateId",
                    "targetStageOperationId",
                    "requiredRecordId",
                ):
                    _identifier(
                        transition_gate.get(field),
                        f"{gate_path}.{field}",
                        findings,
                    )
                required_check_ids = transition_gate.get("requiredCheckIds")
                if _list(
                    required_check_ids,
                    f"{gate_path}.requiredCheckIds",
                    findings,
                ):
                    if not required_check_ids:
                        _finding(
                            findings,
                            f"{gate_path}.requiredCheckIds",
                            "empty_transition_gate_checks",
                            "A transition gate must require at least one quality check.",
                        )
                    for check_index, check_id in enumerate(required_check_ids):
                        _identifier(
                            check_id,
                            f"{gate_path}.requiredCheckIds[{check_index}]",
                            findings,
                        )
                _enum(
                    transition_gate.get("satisfiedState"),
                    {"eligible_for_main_integration"},
                    f"{gate_path}.satisfiedState",
                    findings,
                )
                _enum(
                    transition_gate.get("failureState"),
                    {"hold_for_engineering_review"},
                    f"{gate_path}.failureState",
                    findings,
                )
                if transition_gate.get("blocking") is not True:
                    _finding(
                        findings,
                        f"{gate_path}.blocking",
                        "nonblocking_transition_gate",
                        "A benchmark exit gate must remain blocking.",
                    )
            scene = operation.get("scene")
            if _object(scene, f"{operation_path}.scene", findings):
                _strict_fields(
                    scene,
                    f"{operation_path}.scene",
                    findings,
                    required={
                        "cameraPreset",
                        "pose",
                        "explodeFactor",
                        "visiblePartNumbers",
                        "focusPartNumbers",
                        "calloutPartNumbers",
                    },
                )
                _enum(
                    scene.get("cameraPreset"),
                    {"front", "right", "top", "isometric"},
                    f"{operation_path}.scene.cameraPreset",
                    findings,
                )
                _enum(
                    scene.get("pose"),
                    {"assembled", "exploded"},
                    f"{operation_path}.scene.pose",
                    findings,
                )
                if _number(
                    scene.get("explodeFactor"),
                    f"{operation_path}.scene.explodeFactor",
                    findings,
                ) and not 0.0 <= float(scene["explodeFactor"]) <= 1.0:
                    _finding(
                        findings,
                        f"{operation_path}.scene.explodeFactor",
                        "invalid_explode_factor",
                        "explodeFactor must be between 0 and 1.",
                    )
                for field in (
                    "visiblePartNumbers",
                    "focusPartNumbers",
                    "calloutPartNumbers",
                ):
                    rows = scene.get(field)
                    if _list(rows, f"{operation_path}.scene.{field}", findings):
                        for row_index, row in enumerate(rows):
                            _string(
                                row,
                                f"{operation_path}.scene.{field}[{row_index}]",
                                findings,
                            )


def _validate_process_candidates(
    value: Any,
    path: str,
    findings: List[Finding],
) -> None:
    _validate_generic_claim_document(
        value,
        path,
        findings,
        extra_required={
            "branches",
            "intermediateResults",
            "operationFamilies",
            "assumptions",
            "unresolvedQuestions",
        },
        extra_optional={
            "presentation",
            "requirements",
            "resources",
            "stageDetails",
            "workInstructionBenchmarks",
        },
    )
    if not isinstance(value, dict):
        return
    presentation = value.get("presentation")
    if presentation is not None and _object(
        presentation, f"{path}.presentation", findings
    ):
        _strict_fields(
            presentation,
            f"{path}.presentation",
            findings,
            required={"mode", "showOccurrenceInputs"},
        )
        _enum(
            presentation.get("mode"),
            {"detailed", "high_level"},
            f"{path}.presentation.mode",
            findings,
        )
        if not isinstance(presentation.get("showOccurrenceInputs"), bool):
            _finding(
                findings,
                f"{path}.presentation.showOccurrenceInputs",
                "invalid_boolean",
                "showOccurrenceInputs must be a boolean.",
            )
    for field, identifier_field, required_fields in (
        (
            "requirements",
            "requirementId",
            {"requirementId", "text", "sourceRef", "evidenceClass"},
        ),
        (
            "resources",
            "resourceId",
            {"resourceId", "name", "kind", "sourceRef", "evidenceClass"},
        ),
    ):
        rows = value.get(field, [])
        if not _list(rows, f"{path}.{field}", findings):
            continue
        seen: set[str] = set()
        for index, item in enumerate(rows):
            item_path = f"{path}.{field}[{index}]"
            if not _object(item, item_path, findings):
                continue
            _strict_fields(
                item,
                item_path,
                findings,
                required=required_fields,
            )
            identifier = item.get(identifier_field)
            if _identifier(identifier, f"{item_path}.{identifier_field}", findings):
                if identifier in seen:
                    _finding(
                        findings,
                        f"{item_path}.{identifier_field}",
                        "duplicate_process_reference",
                        f"{identifier_field} must be unique.",
                    )
                seen.add(identifier)
            for text_field in required_fields - {identifier_field}:
                _string(item.get(text_field), f"{item_path}.{text_field}", findings)

    stage_details = value.get("stageDetails", [])
    if _list(stage_details, f"{path}.stageDetails", findings):
        seen_stage_ids: set[str] = set()
        seen_step_ids: set[str] = set()
        for stage_index, stage in enumerate(stage_details):
            stage_path = f"{path}.stageDetails[{stage_index}]"
            if not _object(stage, stage_path, findings):
                continue
            _strict_fields(
                stage,
                stage_path,
                findings,
                required={
                    "stageOperationId",
                    "detailMapLabel",
                    "resultLabel",
                    "presentation",
                    "requiredOccurrenceIds",
                    "branches",
                    "intermediateResults",
                    "operationFamilies",
                    "stageDetailHash",
                },
            )
            stage_id = stage.get("stageOperationId")
            if _identifier(stage_id, f"{stage_path}.stageOperationId", findings):
                if stage_id in seen_stage_ids:
                    _finding(
                        findings,
                        f"{stage_path}.stageOperationId",
                        "duplicate_stage_detail",
                        "stageOperationId must be unique.",
                    )
                seen_stage_ids.add(stage_id)
            _string(stage.get("detailMapLabel"), f"{stage_path}.detailMapLabel", findings)
            _string(stage.get("resultLabel"), f"{stage_path}.resultLabel", findings)
            _sha256(stage.get("stageDetailHash"), f"{stage_path}.stageDetailHash", findings)
            stage_presentation = stage.get("presentation")
            if _object(stage_presentation, f"{stage_path}.presentation", findings):
                _strict_fields(
                    stage_presentation,
                    f"{stage_path}.presentation",
                    findings,
                    required={"mode", "showOccurrenceInputs"},
                )
                _enum(
                    stage_presentation.get("mode"),
                    {"stage_detail"},
                    f"{stage_path}.presentation.mode",
                    findings,
                )
                if stage_presentation.get("showOccurrenceInputs") is not False:
                    _finding(
                        findings,
                        f"{stage_path}.presentation.showOccurrenceInputs",
                        "invalid_stage_detail_presentation",
                        "Stage-detail occurrence inputs must remain hidden.",
                    )
            required_occurrences = stage.get("requiredOccurrenceIds", [])
            if _list(
                required_occurrences,
                f"{stage_path}.requiredOccurrenceIds",
                findings,
            ):
                for ref_index, ref in enumerate(required_occurrences):
                    _identifier(
                        ref,
                        f"{stage_path}.requiredOccurrenceIds[{ref_index}]",
                        findings,
                    )
            detail_operations = stage.get("operationFamilies", [])
            if _list(
                detail_operations,
                f"{stage_path}.operationFamilies",
                findings,
            ):
                for operation_index, operation in enumerate(detail_operations):
                    operation_path = (
                        f"{stage_path}.operationFamilies[{operation_index}]"
                    )
                    if not _object(operation, operation_path, findings):
                        continue
                    operation_id = operation.get("operationId")
                    if _identifier(
                        operation_id,
                        f"{operation_path}.operationId",
                        findings,
                    ):
                        if operation_id in seen_step_ids:
                            _finding(
                                findings,
                                f"{operation_path}.operationId",
                                "duplicate_stage_detail_step",
                                "Detailed operation IDs must be package-unique.",
                            )
                        seen_step_ids.add(operation_id)
                    _string(operation.get("label"), f"{operation_path}.label", findings)
                    _string(
                        operation.get("description"),
                        f"{operation_path}.description",
                        findings,
                    )
                    _enum(
                        operation.get("operationType"),
                        {"operation", "inspection", "decision", "input", "output"},
                        f"{operation_path}.operationType",
                        findings,
                    )
            for collection in ("branches", "intermediateResults"):
                _list(stage.get(collection), f"{stage_path}.{collection}", findings)

    benchmarks = value.get("workInstructionBenchmarks", [])
    _validate_work_instruction_benchmarks(
        benchmarks,
        f"{path}.workInstructionBenchmarks",
        findings,
    )


def _validate_geometry_summary(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"schemaVersion", "sourceRevision", "occurrences", "findings"},
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    if _list(value.get("occurrences"), f"{path}.occurrences", findings):
        for index, item in enumerate(value["occurrences"]):
            item_path = f"{path}.occurrences[{index}]"
            if not _object(item, item_path, findings):
                continue
            _strict_fields(
                item,
                item_path,
                findings,
                required={
                    "occurrenceId",
                    "bounds",
                    "massProperties",
                    "featureSummary",
                    "candidateInterfaces",
                },
            )
            _identifier(item.get("occurrenceId"), f"{item_path}.occurrenceId", findings)
            for field in ("bounds", "massProperties", "featureSummary"):
                if not isinstance(item.get(field), dict):
                    _finding(
                        findings,
                        f"{item_path}.{field}",
                        "expected_object",
                        f"{field} must be an object.",
                    )
            if not isinstance(item.get("candidateInterfaces"), list):
                _finding(
                    findings,
                    f"{item_path}.candidateInterfaces",
                    "expected_array",
                    "candidateInterfaces must be an array.",
                )
    if _list(value.get("findings"), f"{path}.findings", findings):
        for index, item in enumerate(value["findings"]):
            _validate_finding(item, f"{path}.findings[{index}]", findings)


def _validate_visual_manifest(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"schemaVersion", "sourceRevision", "views", "contactSheets", "findings"},
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    if _list(value.get("views"), f"{path}.views", findings):
        seen = set()
        for index, view in enumerate(value["views"]):
            item_path = f"{path}.views[{index}]"
            if not _object(view, item_path, findings):
                continue
            _strict_fields(
                view,
                item_path,
                findings,
                required={
                    "viewId",
                    "kind",
                    "assetPath",
                    "assetHash",
                    "maskAssetPath",
                    "maskAssetHash",
                    "camera",
                    "projection",
                    "width",
                    "height",
                    "visibleOccurrenceIds",
                    "colorLegend",
                    "mateIds",
                    "featureIds",
                },
            )
            view_id = view.get("viewId")
            if _identifier(view_id, f"{item_path}.viewId", findings):
                if view_id in seen:
                    _finding(
                        findings,
                        f"{item_path}.viewId",
                        "duplicate_view_id",
                        "viewId must be unique.",
                    )
                seen.add(view_id)
            _enum(
                view.get("kind"),
                {"presentation", "identity_mask", "interface_crop", "part"},
                f"{item_path}.kind",
                findings,
            )
            for field in ("assetPath", "maskAssetPath"):
                if view.get(field) is not None:
                    _string(view.get(field), f"{item_path}.{field}", findings, maximum=500)
            for field in ("assetHash", "maskAssetHash"):
                if view.get(field) is not None:
                    _sha256(view.get(field), f"{item_path}.{field}", findings)
            if not isinstance(view.get("camera"), dict):
                _finding(
                    findings,
                    f"{item_path}.camera",
                    "expected_object",
                    "camera must be an object.",
                )
            _enum(
                view.get("projection"),
                {"orthographic", "perspective", "unknown"},
                f"{item_path}.projection",
                findings,
            )
            _integer(view.get("width"), f"{item_path}.width", findings, minimum=1)
            _integer(view.get("height"), f"{item_path}.height", findings, minimum=1)
            for field in ("visibleOccurrenceIds", "mateIds", "featureIds"):
                if _list(view.get(field), f"{item_path}.{field}", findings):
                    for ref_index, ref in enumerate(view[field]):
                        _identifier(ref, f"{item_path}.{field}[{ref_index}]", findings)
            legend = view.get("colorLegend")
            if _object(legend, f"{item_path}.colorLegend", findings):
                for color, occurrence_id in legend.items():
                    if not isinstance(color, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", color) is None:
                        _finding(
                            findings,
                            f"{item_path}.colorLegend.{color}",
                            "invalid_mask_color",
                            "Mask legend keys must be six-digit hex colors.",
                        )
                    _identifier(
                        occurrence_id,
                        f"{item_path}.colorLegend.{color}",
                        findings,
                    )
    for field in ("contactSheets", "findings"):
        if _list(value.get(field), f"{path}.{field}", findings):
            if field == "findings":
                for index, item in enumerate(value[field]):
                    _validate_finding(item, f"{path}.{field}[{index}]", findings)


def _validate_evidence_catalog(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"schemaVersion", "sourceRevision", "evidenceFingerprint", "sources"},
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    _sha256(
        value.get("evidenceFingerprint"),
        f"{path}.evidenceFingerprint",
        findings,
    )
    if _list(value.get("sources"), f"{path}.sources", findings):
        seen = set()
        for index, source in enumerate(value["sources"]):
            item_path = f"{path}.sources[{index}]"
            if not _object(source, item_path, findings):
                continue
            _strict_fields(
                source,
                item_path,
                findings,
                required={
                    "evidenceId",
                    "sourceType",
                    "authority",
                    "subjectRefs",
                    "sourceRefs",
                    "details",
                },
            )
            evidence_id = source.get("evidenceId")
            if _identifier(evidence_id, f"{item_path}.evidenceId", findings):
                if evidence_id in seen:
                    _finding(
                        findings,
                        f"{item_path}.evidenceId",
                        "duplicate_evidence_id",
                        "evidenceId must be unique.",
                    )
                seen.add(evidence_id)
            _enum(
                source.get("sourceType"),
                SOURCE_TYPES,
                f"{item_path}.sourceType",
                findings,
            )
            _enum(source.get("authority"), AUTHORITIES, f"{item_path}.authority", findings)
            for field in ("subjectRefs", "sourceRefs"):
                if _list(source.get(field), f"{item_path}.{field}", findings):
                    for ref_index, ref in enumerate(source[field]):
                        _identifier(ref, f"{item_path}.{field}[{ref_index}]", findings)
            if not isinstance(source.get("details"), dict):
                _finding(
                    findings,
                    f"{item_path}.details",
                    "expected_object",
                    "details must be an object.",
                )


def _validate_unresolved(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"schemaVersion", "sourceRevision", "findings", "assumptions", "questions"},
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    if _list(value.get("findings"), f"{path}.findings", findings):
        for index, item in enumerate(value["findings"]):
            _validate_finding(item, f"{path}.findings[{index}]", findings)
    for field in ("assumptions", "questions"):
        if _list(value.get(field), f"{path}.{field}", findings):
            for index, item in enumerate(value[field]):
                item_path = f"{path}.{field}[{index}]"
                if not _object(item, item_path, findings):
                    continue
                _strict_fields(
                    item,
                    item_path,
                    findings,
                    required={"id", "text", "status", "subjectRefs"},
                )
                _identifier(item.get("id"), f"{item_path}.id", findings)
                _string(item.get("text"), f"{item_path}.text", findings)
                _enum(
                    item.get("status"),
                    {"open", "resolved", "deferred"},
                    f"{item_path}.status",
                    findings,
                )
                if _list(item.get("subjectRefs"), f"{item_path}.subjectRefs", findings):
                    for ref_index, ref in enumerate(item["subjectRefs"]):
                        _identifier(ref, f"{item_path}.subjectRefs[{ref_index}]", findings)


def _validate_review_receipt(value: Any, path: str, findings: List[Finding]) -> None:
    if not _object(value, path, findings):
        return
    _strict_fields(
        value,
        path,
        findings,
        required={"schemaVersion", "sourceRevision", "packageRevision", "events"},
    )
    _schema_version(value, path, findings)
    _sha256(value.get("sourceRevision"), f"{path}.sourceRevision", findings)
    _sha256(value.get("packageRevision"), f"{path}.packageRevision", findings)
    if _list(value.get("events"), f"{path}.events", findings):
        for index, event in enumerate(value["events"]):
            item_path = f"{path}.events[{index}]"
            if not _object(event, item_path, findings):
                continue
            _strict_fields(
                event,
                item_path,
                findings,
                required={
                    "eventId",
                    "claimId",
                    "action",
                    "actor",
                    "timestamp",
                    "before",
                    "after",
                },
            )
            _identifier(event.get("eventId"), f"{item_path}.eventId", findings)
            _identifier(event.get("claimId"), f"{item_path}.claimId", findings)
            _enum(
                event.get("action"),
                {"confirm", "edit", "reject", "mark_unknown", "defer"},
                f"{item_path}.action",
                findings,
            )
            _string(event.get("actor"), f"{item_path}.actor", findings)
            _string(event.get("timestamp"), f"{item_path}.timestamp", findings)


_VALIDATORS: Dict[str, Validator] = {
    "package.json": _validate_package,
    "source_manifest.json": _validate_source_manifest,
    "product_structure.json": _validate_product_structure,
    "interface_graph.json": _validate_interface_graph,
    "geometry_summary.json": _validate_geometry_summary,
    "visual_manifest.json": _validate_visual_manifest,
    "functional_context.json": lambda value, path, findings: _validate_generic_claim_document(
        value,
        path,
        findings,
        extra_required={"relationships"},
    ),
    "process_candidates.json": _validate_process_candidates,
    "evidence_catalog.json": _validate_evidence_catalog,
    "unresolved.json": _validate_unresolved,
    "review_receipt.json": _validate_review_receipt,
}


def validate_document(name: str, value: Any) -> List[Finding]:
    validator = _VALIDATORS.get(name)
    if validator is None:
        return [
            {
                "severity": "error",
                "code": "unknown_document_type",
                "path": "$",
                "message": f"Unsupported package document: {name}.",
            }
        ]
    findings: List[Finding] = []
    validator(value, "$", findings)
    return findings


def require_valid_document(name: str, value: Any) -> None:
    findings = validate_document(name, value)
    errors = [item for item in findings if item.get("severity") == "error"]
    if errors:
        raise AssemblyKnowledgeSchemaError(errors)


def validate_package_documents(
    documents: Mapping[str, Any],
    *,
    require_complete: bool = True,
) -> List[Finding]:
    findings: List[Finding] = []
    if require_complete:
        for name in sorted(set(_VALIDATORS) - set(documents)):
            _finding(
                findings,
                f"$.{name}",
                "missing_package_document",
                "Required package document is missing.",
            )
    for name, value in sorted(documents.items()):
        for item in validate_document(name, value):
            enriched = dict(item)
            enriched["document"] = name
            findings.append(enriched)
    return findings
