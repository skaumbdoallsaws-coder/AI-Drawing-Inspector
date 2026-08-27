"""Generalized Facility Layout planning traces and held-out evaluation cases.

The records in this module teach Sage which deterministic capability to invoke
and how stages depend on one another. They intentionally exclude final world
coordinates from the recovered reference factory.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .knowledge_foundation import (
    FACILITY_GENERATION_STAGES,
    FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
    FacilityKnowledgeContractError,
    bytes4_estimate,
    canonical_facility_knowledge_bytes,
    facility_knowledge_registry,
)


FACILITY_KNOWLEDGE_TRACE_VERSION = 1
FACILITY_GOLD_TRACE_FIXTURE = Path(
    "tests/fixtures/facility_layout/knowledge_foundation/"
    "gold-execution-traces-v1.json"
)
FACILITY_HELD_OUT_FIXTURE = Path(
    "tests/fixtures/facility_layout/knowledge_foundation/"
    "held-out-intent-cases-v1.json"
)
FACILITY_REGRESSION_CASE_FIXTURE = Path(
    "tests/fixtures/facility_layout/semantic_intelligence/"
    "evaluation-cases-v1.json"
)

TRACE_KINDS = ("positive", "negative", "correction", "live_modification")
COMMAND_FAMILIES = (
    "facility_envelope",
    "macro_departments",
    "primary_circulation",
    "department_subdivisions",
    "department_resources",
    "seed_cells",
    "repeated_modules",
    "floor_communication",
    "deterministic_validation",
    "live_modification",
    "explicit_save",
    "clarification",
)

_FORBIDDEN_GEOMETRY_FIELDS = frozenset(
    {
        "x",
        "y",
        "z",
        "worldx",
        "worldy",
        "worldz",
        "screenx",
        "screeny",
        "position",
        "transform",
        "quaternion",
        "vertices",
        "boundary",
        "centerline",
        "coordinates",
    }
)
_DIMENSION_PAIR_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:x|by|\u00d7)\s*\d+(?:\.\d+)?\s*"
    r"(?:m|mm|ft|feet|foot|in|inch|inches)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FacilityKnowledgeContractError(
            "facility_trace_fixture_invalid",
            "Facility trace fixture must contain a JSON object.",
            details={"path": str(path)},
        )
    return value


def _content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _exact_fields(
    value: Mapping[str, Any],
    required: set[str],
    *,
    code: str,
    label: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        raise FacilityKnowledgeContractError(
            code,
            f"{label} fields are invalid.",
            details={"missing": missing, "unknown": unknown},
        )


def _reject_literal_geometry(value: Any, path: str = "trace") -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(
            str(key)
            for key in value
            if str(key).casefold() in _FORBIDDEN_GEOMETRY_FIELDS
        )
        if forbidden:
            raise FacilityKnowledgeContractError(
                "facility_trace_literal_geometry_forbidden",
                "Generalized Facility traces cannot preserve final coordinates.",
                details={"path": path, "fields": forbidden},
            )
        for key, nested in value.items():
            _reject_literal_geometry(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_literal_geometry(nested, f"{path}[{index}]")


def validate_gold_trace_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "facility_trace_bundle_invalid",
            "Gold trace bundle must be an object.",
        )
    required = {
        "schemaVersion",
        "recordKind",
        "traceSetId",
        "traceSetVersion",
        "description",
        "sourceReference",
        "traceContentSha256",
        "traces",
    }
    _exact_fields(
        value,
        required,
        code="facility_trace_bundle_shape_invalid",
        label="Gold trace bundle",
    )
    result = deepcopy(dict(value))
    if result["schemaVersion"] != FACILITY_KNOWLEDGE_TRACE_VERSION:
        raise FacilityKnowledgeContractError(
            "unsupported_schema_version",
            "Gold trace schema version is unsupported.",
        )
    if result["recordKind"] != "facility_gold_execution_traces":
        raise FacilityKnowledgeContractError(
            "facility_trace_bundle_kind_invalid",
            "Gold trace bundle record kind is invalid.",
        )
    traces = result["traces"]
    if not isinstance(traces, list) or not traces:
        raise FacilityKnowledgeContractError(
            "facility_trace_bundle_empty",
            "Gold trace bundle requires at least one trace.",
        )
    expected_hash = _content_hash(traces)
    if result["traceContentSha256"] != expected_hash:
        raise FacilityKnowledgeContractError(
            "facility_trace_hash_mismatch",
            "Gold trace content hash does not match its records.",
            details={
                "expected": expected_hash,
                "observed": result["traceContentSha256"],
            },
        )
    registry = facility_knowledge_registry()
    stage_ids = {item["stageId"] for item in FACILITY_GENERATION_STAGES}
    command_ids = {item["commandId"] for item in registry["commands"]}
    tool_ids = {item["commandId"] for item in registry["agentTools"]}
    known_commands = command_ids | tool_ids
    trace_ids: list[str] = []
    kinds: set[str] = set()
    for index, trace in enumerate(traces):
        if not isinstance(trace, Mapping):
            raise FacilityKnowledgeContractError(
                "facility_trace_invalid",
                "Each gold trace must be an object.",
                details={"index": index},
            )
        fields = {
            "traceId",
            "traceKind",
            "rolloutStage",
            "g1Eligible",
            "userIntent",
            "trustedStartingState",
            "resolvedEntities",
            "selectedSemanticCommand",
            "semanticConstraints",
            "expectedOperationFamily",
            "expectedReceipt",
            "resultingStateSummary",
            "validationResult",
            "correctionOrNextDependency",
            "illustrative",
            "productionEvidence",
        }
        _exact_fields(
            trace,
            fields,
            code="facility_trace_shape_invalid",
            label=f"Gold trace {index}",
        )
        trace_id = str(trace["traceId"])
        if not trace_id or trace_id in trace_ids:
            raise FacilityKnowledgeContractError(
                "facility_trace_id_invalid",
                "Gold trace IDs must be non-empty and unique.",
            )
        trace_ids.append(trace_id)
        trace_kind = str(trace["traceKind"])
        if trace_kind not in TRACE_KINDS:
            raise FacilityKnowledgeContractError(
                "facility_trace_kind_invalid",
                "Gold trace kind is unsupported.",
            )
        kinds.add(trace_kind)
        if trace["rolloutStage"] not in stage_ids:
            raise FacilityKnowledgeContractError(
                "facility_trace_stage_invalid",
                "Gold trace references an unknown generation stage.",
            )
        if trace["selectedSemanticCommand"] not in known_commands:
            raise FacilityKnowledgeContractError(
                "facility_trace_command_invalid",
                "Gold trace references an unknown semantic command.",
            )
        if not isinstance(trace["expectedOperationFamily"], list) or not trace[
            "expectedOperationFamily"
        ]:
            raise FacilityKnowledgeContractError(
                "facility_trace_operation_family_invalid",
                "Gold trace requires a deterministic operation family.",
            )
        if trace["illustrative"] is not True or trace["productionEvidence"] is not False:
            raise FacilityKnowledgeContractError(
                "facility_trace_authority_invalid",
                "Generated traces must remain illustrative and non-production evidence.",
            )
        _reject_literal_geometry(trace, f"traces[{index}]")
    if kinds != set(TRACE_KINDS):
        raise FacilityKnowledgeContractError(
            "facility_trace_kind_coverage_incomplete",
            "Gold traces must cover positive, negative, correction, and live modification behavior.",
            details={"observed": sorted(kinds)},
        )
    return result


def validate_held_out_case_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FacilityKnowledgeContractError(
            "facility_held_out_bundle_invalid",
            "Held-out case bundle must be an object.",
        )
    required = {
        "schemaVersion",
        "recordKind",
        "setId",
        "setVersion",
        "classification",
        "authorship",
        "frozenAtUtc",
        "contractRevision",
        "regressionCaseBinding",
        "caseContentSha256",
        "cases",
    }
    _exact_fields(
        value,
        required,
        code="facility_held_out_bundle_shape_invalid",
        label="Held-out case bundle",
    )
    result = deepcopy(dict(value))
    if result["schemaVersion"] != FACILITY_KNOWLEDGE_TRACE_VERSION:
        raise FacilityKnowledgeContractError(
            "unsupported_schema_version",
            "Held-out case schema version is unsupported.",
        )
    if result["recordKind"] != "facility_held_out_intent_cases":
        raise FacilityKnowledgeContractError(
            "facility_held_out_bundle_kind_invalid",
            "Held-out case record kind is invalid.",
        )
    if result["classification"] != "held_out_post_contract":
        raise FacilityKnowledgeContractError(
            "facility_held_out_classification_invalid",
            "Held-out cases must be explicitly classified post-contract.",
        )
    cases = result["cases"]
    if not isinstance(cases, list) or not cases:
        raise FacilityKnowledgeContractError(
            "facility_held_out_bundle_empty",
            "Held-out case bundle requires at least one case.",
        )
    expected_hash = _content_hash(cases)
    if result["caseContentSha256"] != expected_hash:
        raise FacilityKnowledgeContractError(
            "facility_held_out_hash_mismatch",
            "Held-out case content hash does not match its cases.",
            details={"expected": expected_hash, "observed": result["caseContentSha256"]},
        )
    ids: list[str] = []
    prompts: list[str] = []
    g1_count = 0
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise FacilityKnowledgeContractError(
                "facility_held_out_case_invalid",
                "Each held-out case must be an object.",
            )
        fields = {
            "id",
            "scope",
            "prompt",
            "expectedIntent",
            "expectedCommandFamily",
            "expectedStageId",
            "expectedExecutionMode",
            "requiredTools",
            "forbiddenActions",
            "notes",
        }
        _exact_fields(
            case,
            fields,
            code="facility_held_out_case_shape_invalid",
            label=f"Held-out case {index}",
        )
        case_id = str(case["id"])
        prompt = str(case["prompt"])
        if not case_id or case_id in ids or not prompt.strip():
            raise FacilityKnowledgeContractError(
                "facility_held_out_case_identity_invalid",
                "Held-out case IDs and prompts must be non-empty and unique.",
            )
        if prompt.casefold() in prompts:
            raise FacilityKnowledgeContractError(
                "facility_held_out_prompt_duplicate",
                "Held-out prompts must be unique.",
            )
        ids.append(case_id)
        prompts.append(prompt.casefold())
        if case["expectedCommandFamily"] not in COMMAND_FAMILIES:
            raise FacilityKnowledgeContractError(
                "facility_held_out_command_family_invalid",
                "Held-out case command family is unsupported.",
            )
        if case["expectedStageId"] is not None and case["expectedStageId"] not in {
            item["stageId"] for item in FACILITY_GENERATION_STAGES
        }:
            raise FacilityKnowledgeContractError(
                "facility_held_out_stage_invalid",
                "Held-out case references an unknown stage.",
            )
        if case["scope"] == "g1":
            g1_count += 1
    if g1_count < 12:
        raise FacilityKnowledgeContractError(
            "facility_g1_held_out_coverage_incomplete",
            "The held-out set requires at least twelve G1 cases.",
        )
    return result


def load_facility_trace_evidence(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    traces = validate_gold_trace_bundle(_read_json(root / FACILITY_GOLD_TRACE_FIXTURE))
    held_out = validate_held_out_case_bundle(_read_json(root / FACILITY_HELD_OUT_FIXTURE))
    registry_revision = facility_knowledge_registry()["registryRevision"]
    if held_out["contractRevision"] != registry_revision:
        raise FacilityKnowledgeContractError(
            "facility_held_out_contract_revision_mismatch",
            "Held-out cases are not bound to the current frozen Facility contract.",
            details={
                "expected": registry_revision,
                "observed": held_out["contractRevision"],
            },
        )
    regression_path = root / FACILITY_REGRESSION_CASE_FIXTURE
    regression_raw = regression_path.read_bytes()
    regression = json.loads(regression_raw.decode("utf-8"))
    cases = regression.get("cases") if isinstance(regression, Mapping) else None
    if not isinstance(cases, list) or len(cases) != 71:
        raise FacilityKnowledgeContractError(
            "facility_regression_case_inventory_mismatch",
            "The established Facility regression inventory must remain exactly 71 cases.",
        )
    regression_prompts = {
        str(item.get("prompt") or "").strip().casefold()
        for item in cases
        if isinstance(item, Mapping)
    }
    held_out_prompts = {
        str(item["prompt"]).strip().casefold() for item in held_out["cases"]
    }
    overlap = sorted(regression_prompts & held_out_prompts)
    if overlap:
        raise FacilityKnowledgeContractError(
            "facility_held_out_regression_overlap",
            "Regression-visible prompts cannot be relabeled as held out.",
            details={"overlap": overlap},
        )
    binding = held_out["regressionCaseBinding"]
    expected_binding = {
        "path": str(FACILITY_REGRESSION_CASE_FIXTURE).replace("\\", "/"),
        "classification": "regression_visible_not_held_out",
        "caseCount": 71,
        "sha256": hashlib.sha256(regression_raw).hexdigest(),
    }
    if binding != expected_binding:
        raise FacilityKnowledgeContractError(
            "facility_regression_case_binding_mismatch",
            "Held-out metadata is not bound to the current regression-visible fixture.",
            details={"expected": expected_binding, "observed": binding},
        )
    return {
        "schemaVersion": FACILITY_KNOWLEDGE_TRACE_VERSION,
        "recordKind": "facility_trace_evidence",
        "goldTraces": traces,
        "heldOut": held_out,
        "regressionVisible": {
            **expected_binding,
            "heldOut": False,
        },
    }


def classify_facility_trace_command_family(prompt: str) -> str:
    """Classify broad generation intent without calculating any geometry."""

    text = " ".join(str(prompt or "").casefold().split())
    if not text:
        return "clarification"
    if re.search(r"\b(save|persist|publish|commit)\b", text):
        return "explicit_save"
    if (
        ("percent" in text or "%" in text)
        and sum(float(item) for item in _PERCENT_RE.findall(text)) > 100.000001
    ):
        return "clarification"
    if re.search(r"\b(conflicting|contradictory|impossible|duplicate labels?)\b", text):
        return "clarification"
    if re.search(r"\b(rename|resize|remove|delete|add)\b", text) and re.search(
        r"\b(existing|current|department|zone)\b", text
    ):
        return "live_modification"
    facility_creation = bool(
        re.search(r"\b(create|build|start|make|set up|lay out)\b", text)
        and re.search(r"\b(factory|facility|plant|floor|building)\b", text)
    )
    if facility_creation and (
        _DIMENSION_PAIR_RE.search(text)
        or re.search(r"\b(width|depth|dimensions?|size)\b", text)
    ):
        return "facility_envelope"
    if re.search(r"\b(departments?|zones?|bands?|rows?|columns?|partition|divide)\b", text):
        return "macro_departments"
    if re.search(r"\b(markings?|paint|arrows?|keep.clear)\b", text):
        return "floor_communication"
    if re.search(r"\b(aisles?|routes?|crossings?|pedestrian paths?|circulation)\b", text):
        return "primary_circulation"
    if re.search(r"\b(subdivide|subdivision|nested zones?)\b", text):
        return "department_subdivisions"
    if re.search(r"\b(machines?|equipment|assets?|workstations?|racks?)\b", text):
        return "department_resources"
    if re.search(r"\b(cells?|workcells?)\b", text):
        return "seed_cells"
    if re.search(r"\b(pattern|repeat|replicate|array|module)\b", text):
        return "repeated_modules"
    if re.search(r"\b(validate|check|findings?|collision|overlap)\b", text):
        return "deterministic_validation"
    return "clarification"


def compile_facility_trace_context(
    repo_root: str | Path,
    stage_id: str,
    *,
    g1_only: bool = False,
    maximum_bytes: int = FACILITY_REGISTRY_SLICE_MAXIMUM_BYTES,
) -> dict[str, Any]:
    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes < 512:
        raise FacilityKnowledgeContractError(
            "invalid_trace_context_budget",
            "Trace context maximum_bytes must be an integer of at least 512.",
        )
    evidence = load_facility_trace_evidence(repo_root)
    stage_ids = {item["stageId"] for item in FACILITY_GENERATION_STAGES}
    if stage_id not in stage_ids:
        raise FacilityKnowledgeContractError(
            "unknown_facility_stage",
            "Trace context requested an unknown Facility stage.",
        )
    selected = [
        deepcopy(item)
        for item in evidence["goldTraces"]["traces"]
        if item["rolloutStage"] == stage_id
        and (not g1_only or item["g1Eligible"] is True)
    ]
    result = {
        "schemaVersion": FACILITY_KNOWLEDGE_TRACE_VERSION,
        "recordKind": "facility_stage_trace_context",
        "stageId": stage_id,
        "g1Only": bool(g1_only),
        "registryRevision": facility_knowledge_registry()["registryRevision"],
        "traceSetId": evidence["goldTraces"]["traceSetId"],
        "traceContentSha256": evidence["goldTraces"]["traceContentSha256"],
        "traces": selected,
        "measurement": {},
    }
    for _attempt in range(8):
        size = len(canonical_facility_knowledge_bytes(result))
        measured = {
            "canonicalBytes": size,
            "estimatedTokens": bytes4_estimate(size),
            "estimatorId": "bytes4-v1",
            "maximumBytes": maximum_bytes,
        }
        if result["measurement"] == measured:
            break
        result["measurement"] = measured
    payload = canonical_facility_knowledge_bytes(result)
    if len(payload) > maximum_bytes:
        raise FacilityKnowledgeContractError(
            "facility_trace_context_too_large",
            "Stage-specific Facility trace context exceeds its canonical byte budget.",
            details={
                "stageId": stage_id,
                "canonicalBytes": len(payload),
                "maximumBytes": maximum_bytes,
                "traceIds": [item["traceId"] for item in selected],
            },
        )
    return result


def evaluate_held_out_command_families(bundle: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_held_out_case_bundle(bundle)
    records = []
    for case in validated["cases"]:
        actual = classify_facility_trace_command_family(case["prompt"])
        records.append(
            {
                "id": case["id"],
                "scope": case["scope"],
                "expectedCommandFamily": case["expectedCommandFamily"],
                "actualCommandFamily": actual,
                "passed": actual == case["expectedCommandFamily"],
            }
        )
    passed = sum(item["passed"] for item in records)
    percent = round(passed / len(records) * 100.0, 6) if records else 0.0
    return {
        "setId": validated["setId"],
        "setVersion": validated["setVersion"],
        "caseContentSha256": validated["caseContentSha256"],
        "caseCount": len(records),
        "passedCount": passed,
        "failedCount": len(records) - passed,
        "passPercent": percent,
        "records": records,
    }


__all__ = [
    "COMMAND_FAMILIES",
    "FACILITY_GOLD_TRACE_FIXTURE",
    "FACILITY_HELD_OUT_FIXTURE",
    "FACILITY_KNOWLEDGE_TRACE_VERSION",
    "FACILITY_REGRESSION_CASE_FIXTURE",
    "TRACE_KINDS",
    "classify_facility_trace_command_family",
    "compile_facility_trace_context",
    "evaluate_held_out_command_families",
    "load_facility_trace_evidence",
    "validate_gold_trace_bundle",
    "validate_held_out_case_bundle",
]
