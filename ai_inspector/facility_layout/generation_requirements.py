"""Bounded generation requirements, without granting admission or write authority."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import math
import re
from typing import Any, Mapping, NoReturn

from .canonical import layout_revision
from .design_brief import canonical_design_bytes, design_revision
from .operations import MAX_OPERATION_BATCH
from .plan_settings import PLAN_SETTINGS_EXTENSION_KEY, normalize_plan_settings


GENERATION_LEDGER_SCHEMA = "facility-generation-requirement-ledger-v1"
MAX_LEDGER_BYTES = 262_144
MAX_LEDGER_TURNS = 64
MAX_LEDGER_REQUIREMENTS = 256
MAX_LEDGER_REVISIONS = 256
EMPTY_COLLECTIONS = (
    "zones", "placements", "routes", "floorMarkings", "utilityNetworks",
    "processBindings", "dismissedSuggestions",
)
_ROOT_FIELDS = frozenset(EMPTY_COLLECTIONS) | {
    "schemaVersion", "layoutId", "displayName", "status", "association",
    "coordinateFrame", "sourceShellRef", "catalogSnapshotRevision", "policySetRef",
    "createdAt", "updatedAt", "extensions",
}
_CREATION_OPERATIONS = frozenset({
    "rename_layout", "set_plan_settings", "add_zone", "edit_zone", "place_asset",
    "move_placement", "rotate_placement", "set_position_mode", "set_snap_relationship",
    "add_route", "add_aisle", "edit_route", "edit_aisle", "add_floor_marking",
    "edit_floor_marking",
})
_BODY_FIELDS = frozenset({
    "schemaVersion", "ledgerId", "tenantId", "siteId", "workspaceId", "layoutId",
    "baseRevision", "authoringMode", "parentLedgerRevision", "sourceRefs", "turns",
    "requirements",
})
_UNITS = {"m": Decimal("1"), "mm": Decimal("0.001"),
          "ft": Decimal("0.3048"), "in": Decimal("0.0254")}


class GenerationRequirementError(ValueError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _fail(code: str, message: str, **details: Any) -> NoReturn:
    raise GenerationRequirementError(code, message, **details)


def _closed(value: Any, fields: set[str] | frozenset[str], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != fields:
        _fail("generation_requirement_fields_invalid", f"{name} must be an object with exactly {', '.join(sorted(fields))}.",
              field=name, requiredFields=sorted(fields), receivedFields=sorted(value) if isinstance(value, Mapping) else None)


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", value) is None:
        _fail("generation_requirement_identifier_invalid", f"{field} is not a stable ID.")
    return value


def revision(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail("generation_requirement_revision_invalid", f"{field} must be a SHA-256 revision.")
    return value


def _text(value: Any, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail("generation_requirement_text_invalid", f"{field} is empty or exceeds its limit.")


def _array(value: Any, field: str, maximum: int, *, nonempty: bool = True) -> None:
    if not isinstance(value, list) or len(value) > maximum or (nonempty and not value):
        _fail("generation_requirement_budget_exceeded", f"{field} violates its array bounds.")


def _dimensions(value: Any) -> tuple[Decimal, Decimal]:
    _closed(value, {"width", "depth", "sourceUnit"}, "dimensions")
    if not isinstance(value["sourceUnit"], str) or value["sourceUnit"] not in _UNITS:
        _fail("generation_requirement_unit_invalid", "Dimensions require m, mm, ft or in.")
    result = []
    for key in ("width", "depth"):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or (isinstance(number, float) and not math.isfinite(number)):
            _fail("generation_requirement_number_invalid", "Dimensions must be finite numbers.")
        meters = Decimal(str(number)) * _UNITS[value["sourceUnit"]]
        if not Decimal("0.5") <= meters <= Decimal("10000"):
            _fail("generation_requirement_number_invalid", "Dimensions exceed supported plan bounds.")
        result.append(meters)
    return result[0], result[1]


def _validate_predicate(predicate: Any, requirement_kind: str) -> None:
    _closed(predicate, {"kind", "subjectId", "parameters"}, "predicate")
    identifier(predicate["subjectId"], "predicate.subjectId")
    kind, parameters = predicate["kind"], predicate["parameters"]
    if not isinstance(kind, str):
        _fail("generation_requirement_predicate_unsupported", "Predicate kind must be a registered string.")
    if requirement_kind == "assumption" and kind != "unsaved_preview":
        _validate_predicate(predicate, "hard_constraint")
        return
    if kind == "envelope_dimensions" and requirement_kind == "hard_constraint":
        _dimensions(parameters)
    elif kind == "resource_quantity" and requirement_kind == "hard_constraint":
        _closed(parameters, {"quantity"}, "quantity")
        count = parameters["quantity"]
        if type(count) is not int or not 1 <= count <= 900:
            _fail("generation_requirement_number_invalid", "Resource quantity must be 1-900.")
    elif kind == "unsaved_preview" and requirement_kind == "permission":
        _closed(parameters, {"saveAllowed"}, "preview")
        if parameters["saveAllowed"] is not False:
            _fail("generation_requirement_authority_invalid", "A generation ledger cannot authorize Save.")
    elif kind == "resource_mapping" and requirement_kind == "hard_constraint":
        _closed(parameters, {"assetId", "assetDefinitionRevision", "processStepRefs", "targetArea"}, "resource mapping")
        identifier(parameters["assetId"], "assetId")
        revision(parameters["assetDefinitionRevision"], "assetDefinitionRevision")
        _text(parameters["targetArea"], "targetArea", 240)
        _array(parameters["processStepRefs"], "processStepRefs", 32)
        for item in parameters["processStepRefs"]:
            identifier(item, "processStepRef")
        if len(set(parameters["processStepRefs"])) != len(parameters["processStepRefs"]):
            _fail("generation_requirement_duplicate_id", "Duplicate process step reference.")
    elif kind == "department_allocation" and requirement_kind == "hard_constraint":
        _closed(parameters, {"label", "zoneType", "areaShare", "row"}, "department allocation")
        _text(parameters["label"], "label", 240)
        identifier(parameters["zoneType"], "zoneType")
        share = parameters["areaShare"]
        if type(share) not in (int, float) or not 0 < share <= 1 or not math.isfinite(share):
            _fail("generation_requirement_number_invalid", "Department share must be in (0, 1].")
        if type(parameters["row"]) is not int or not 1 <= parameters["row"] <= 50:
            _fail("generation_requirement_number_invalid", "Department row must be 1-50.")
    elif kind == "resource_pattern" and requirement_kind == "hard_constraint":
        _closed(parameters, {"placementPattern", "semanticOrientation"}, "resource pattern")
        from .industrial_patterns import INDUSTRIAL_PATTERN_IDS
        if not isinstance(parameters["placementPattern"], str) or parameters["placementPattern"] not in INDUSTRIAL_PATTERN_IDS:
            _fail("generation_requirement_predicate_unsupported", "Unknown deterministic placement pattern.")
        if parameters["semanticOrientation"] not in ("long_side_east_west", "long_side_north_south"):
            _fail("generation_requirement_predicate_unsupported", "Unsupported semantic orientation.")
    elif kind == "resource_spacing" and requirement_kind == "hard_constraint":
        _closed(parameters, {"value", "unit", "evidenceRef"}, "resource spacing")
        if not isinstance(parameters["unit"], str) or parameters["unit"] not in _UNITS:
            _fail("generation_requirement_unit_invalid", "Spacing unit is invalid.")
        number = parameters["value"]
        if type(number) not in (int, float) or not 0 <= number <= 10000 or not math.isfinite(number):
            _fail("generation_requirement_number_invalid", "Spacing must be finite and bounded.")
        identifier(parameters["evidenceRef"], "evidenceRef")
    elif kind == "planning_subject" and requirement_kind == "hard_constraint":
        _closed(parameters, {"productLabel"}, "planning subject")
        _text(parameters["productLabel"], "productLabel", 240)
    elif kind == "department_presence" and requirement_kind == "hard_constraint":
        _closed(parameters, {"label"}, "department presence")
        _text(parameters["label"], "label", 240)
    elif kind in {"catalog_only", "assumptions_disclosed"} and requirement_kind == "hard_constraint":
        _closed(parameters, {"required"}, kind)
        if parameters["required"] is not True:
            _fail("generation_requirement_predicate_unsupported", f"{kind} requires required=true.")
    elif kind == "source_consulted" and requirement_kind == "hard_constraint":
        _closed(parameters, {"url"}, "source consultation")
        from ai_inspector.research.web import public_url, ResearchError
        try:
            public_url(parameters["url"])
        except ResearchError as exc:
            _fail("generation_requirement_source_invalid", str(exc))
    elif kind == "preserve_prior_requirements" and requirement_kind == "hard_constraint":
        _closed(parameters, {"exceptRequirementIds"}, "preserved requirements")
        _array(parameters["exceptRequirementIds"], "exceptRequirementIds", 32, nonempty=False)
        for key in parameters["exceptRequirementIds"]:
            identifier(key, "exceptRequirementId")
        if len(set(parameters["exceptRequirementIds"])) != len(parameters["exceptRequirementIds"]):
            _fail("generation_requirement_preservation_invalid", "Preservation exceptions must be unique.")
    else:
        allowed = ["permission"] if kind == "unsaved_preview" else ["hard_constraint", "assumption"]
        _fail("generation_requirement_predicate_unsupported",
              f"Predicate {kind!r} does not support requirement kind {requirement_kind!r}; expected {allowed} for a registered predicate.",
              predicateKind=kind, requirementKind=requirement_kind, permittedRequirementKinds=allowed)


def build_generation_ledger(body: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a server-assembled ledger and assign its content revision.

    Spans use Unicode code-point offsets, with an exclusive end (not UTF-16).
    Coverage is structural, not proof of language comprehension or review.
    This function never admits a package or authorizes an editor operation.
    """
    _closed(body, _BODY_FIELDS, "ledger")
    if len(canonical_design_bytes(body)) > MAX_LEDGER_BYTES:
        _fail("generation_requirement_budget_exceeded", "Ledger exceeds the byte limit.")
    result = deepcopy(dict(body))
    if result["schemaVersion"] != GENERATION_LEDGER_SCHEMA:
        _fail("generation_requirement_schema_unsupported", "Unsupported ledger schema.")
    for key in ("ledgerId", "tenantId", "siteId", "workspaceId", "layoutId"):
        identifier(result[key], key)
    revision(result["baseRevision"], "baseRevision")
    if result["parentLedgerRevision"] is not None:
        revision(result["parentLedgerRevision"], "parentLedgerRevision")
    if result["authoringMode"] != "new_empty_layout":
        _fail("generation_authoring_mode_unsupported", "Only new-empty-layout is supported.")
    _array(result["sourceRefs"], "sourceRefs", 64)
    sources = set()
    for source in result["sourceRefs"]:
        _closed(source, {"sourceKind", "sourceId", "sourceRevision"}, "sourceRef")
        if not isinstance(source["sourceKind"], str) or source["sourceKind"] not in {"product", "process_map", "catalog", "shell", "policy", "evidence"}:
            _fail("generation_requirement_source_invalid", "Unknown source kind.")
        identifier(source["sourceId"], "sourceId")
        revision(source["sourceRevision"], "sourceRevision")
        key = (source["sourceKind"], source["sourceId"])
        if key in sources:
            _fail("generation_requirement_source_invalid", "Duplicate source identity.")
        sources.add(key)
    _array(result["turns"], "turns", MAX_LEDGER_TURNS)
    turns: dict[str, str] = {}
    for turn in result["turns"]:
        _closed(turn, {"turnId", "text"}, "turn")
        turn_id = identifier(turn["turnId"], "turnId")
        _text(turn["text"], "turn.text", 8192)
        if turn_id in turns:
            _fail("generation_requirement_duplicate_id", "Duplicate turn ID.")
        turns[turn_id] = turn["text"]
    _array(result["requirements"], "requirements", MAX_LEDGER_REQUIREMENTS)
    requirements = {}
    coverage = {key: set() for key in turns}
    for item in result["requirements"]:
        _closed(item, {"requirementId", "source", "kind", "disposition", "predicate",
                       "reason", "supersededBy"}, "requirement")
        key = identifier(item["requirementId"], "requirementId")
        if key in requirements:
            _fail("generation_requirement_duplicate_id", "Duplicate requirement ID.")
        requirements[key] = item
        _closed(item["source"], {"turnId", "start", "end"}, "source span")
        source = item["source"]
        identifier(source["turnId"], "source.turnId")
        text = turns.get(source["turnId"])
        start, end = source["start"], source["end"]
        if (text is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text) or not text[start:end].strip()):
            _fail("generation_requirement_span_invalid", "Source span must address retained user text.")
        coverage[source["turnId"]].update(range(start, end))
        if not isinstance(item["kind"], str) or item["kind"] not in {"hard_constraint", "preference", "permission", "assumption", "unknown"}:
            _fail("generation_requirement_kind_invalid", "Unsupported requirement classification.")
        state = item["disposition"]
        if not isinstance(state, str) or state not in {"represented", "needs_clarification", "unsupported", "superseded"}:
            _fail("generation_requirement_disposition_invalid", "Unknown requirement disposition.")
        _array(item["supersededBy"], "supersededBy", 16, nonempty=False)
        for successor in item["supersededBy"]:
            identifier(successor, "supersededBy")
        if len(set(item["supersededBy"])) != len(item["supersededBy"]):
            _fail("generation_requirement_supersession_invalid", "Duplicate successor.")
        if state == "represented":
            try:
                _validate_predicate(item["predicate"], item["kind"])
            except GenerationRequirementError as exc:
                raise GenerationRequirementError(exc.code, f"Requirement {key}: {exc}", requirementId=key, **exc.details) from exc
            if item["kind"] == "assumption":
                try:
                    _text(item["reason"], "assumption rationale", 1024)
                except GenerationRequirementError as exc:
                    raise GenerationRequirementError(exc.code, str(exc), requirementId=key, **exc.details) from exc
            if (item["reason"] is not None and item["kind"] != "assumption") or item["supersededBy"]:
                _fail("generation_requirement_disposition_invalid", "Active predicates cannot be superseded.")
        else:
            _text(item["reason"], "reason", 1024)
            if state == "superseded":
                if not item["supersededBy"]:
                    _fail("generation_requirement_supersession_invalid", "Supersession needs a successor.")
                if item["predicate"] is not None:
                    _validate_predicate(item["predicate"], item["kind"])
            elif item["predicate"] is not None or item["supersededBy"]:
                _fail("generation_requirement_disposition_invalid", "Unresolved clauses cannot claim a predicate.")
    turn_order = {key: index for index, key in enumerate(turns)}
    for item in requirements.values():
        for successor_id in item["supersededBy"]:
            successor = requirements.get(successor_id)
            if successor is None or turn_order[successor["source"]["turnId"]] <= turn_order[item["source"]["turnId"]]:
                _fail("generation_requirement_supersession_invalid", "Successors must reference a later turn.")
    for item in requirements.values():
        predicate = item["predicate"]
        if not predicate or predicate["kind"] != "preserve_prior_requirements":
            continue
        turn_id = item["source"]["turnId"]
        changed_here = {key for key, prior in requirements.items()
                        if any(requirements[ref]["source"]["turnId"] == turn_id for ref in prior["supersededBy"])}
        if (predicate["subjectId"] != result["ledgerId"] or turn_order[turn_id] == 0
                or set(predicate["parameters"]["exceptRequirementIds"]) != changed_here):
            _fail("generation_requirement_preservation_invalid",
                  "Preservation must target this ledger and name exactly the prior requirements explicitly superseded in this turn.",
                  requirementId=item["requirementId"], expectedSubjectId=result["ledgerId"],
                  expectedExceptions=sorted(changed_here))
    for turn_id, text in turns.items():
        missing = [index for index, character in enumerate(text) if not character.isspace() and index not in coverage[turn_id]]
        if missing:
            spans = []
            for index in missing:
                if spans and text[spans[-1][1]:index].isspace():
                    spans[-1][1] = index + 1
                elif spans and spans[-1][1] == index:
                    spans[-1][1] = index + 1
                else:
                    spans.append([index, index + 1])
            _fail("generation_requirement_clause_unaccounted", "Retained user text still needs a disposition; quote each uncovered clause.",
                  turnId=turn_id, uncovered=[{"start": start, "end": end, "text": text[start:end]} for start, end in spans[:16]])
    active_predicates = {}
    for item in requirements.values():
        if item["disposition"] != "represented":
            continue
        predicate = item["predicate"]
        if predicate["kind"] in {"envelope_dimensions", "unsaved_preview", "catalog_only", "assumptions_disclosed"} and predicate["subjectId"] != result["layoutId"]:
            _fail("generation_requirement_subject_invalid", f"Layout predicate must target layoutId {result['layoutId']!r}.",
                  requirementId=item["requirementId"], expectedSubjectId=result["layoutId"])
        key = (predicate["kind"], predicate["subjectId"])
        if predicate["kind"] == "preserve_prior_requirements":
            key += (item["source"]["turnId"],)
        signature = canonical_design_bytes(predicate["parameters"])
        if key in active_predicates and active_predicates[key] != signature:
            conflicts = [entry["requirementId"] for entry in requirements.values()
                         if entry["disposition"] == "represented" and entry["predicate"]["kind"] == predicate["kind"]
                         and entry["predicate"]["subjectId"] == predicate["subjectId"]]
            _fail("generation_requirement_conflict", "Conflicting active predicates require explicit resolution.",
                  predicateKind=predicate["kind"], subjectId=predicate["subjectId"], conflictingRequirementIds=conflicts[:16])
        active_predicates[key] = signature
    result["ledgerRevision"] = design_revision(result)
    return result


def validate_generation_ledger(value: Mapping[str, Any]) -> dict[str, Any]:
    _closed(value, _BODY_FIELDS | {"ledgerRevision"}, "ledger record")
    record = build_generation_ledger({key: item for key, item in value.items() if key != "ledgerRevision"})
    if value["ledgerRevision"] != record["ledgerRevision"]:
        _fail("generation_requirement_integrity_mismatch", "Ledger content does not match its revision.")
    return record


def validate_generation_amendment(previous: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    before, after = validate_generation_ledger(previous), validate_generation_ledger(current)
    identity = ("ledgerId", "tenantId", "siteId", "workspaceId", "layoutId", "baseRevision", "authoringMode")
    if any(before[key] != after[key] for key in identity) or after["parentLedgerRevision"] != before["ledgerRevision"]:
        _fail("generation_requirement_parent_conflict", "Correction must retain its identity and immutable base.")
    count = len(before["turns"])
    if len(after["turns"]) <= count or after["turns"][:count] != before["turns"]:
        _fail("generation_requirement_history_changed", "Corrections append user turns without rewriting history.")
    old = {item["requirementId"]: item for item in before["requirements"]}
    new = {item["requirementId"]: item for item in after["requirements"]}
    new_turns = {turn["turnId"] for turn in after["turns"][count:]}
    for key, item in old.items():
        updated = new.get(key)
        if updated == item:
            continue
        if (updated is None or item["disposition"] == "superseded"
                or updated["disposition"] != "superseded"
                or any(updated[field] != item[field] for field in ("requirementId", "source", "kind", "predicate"))
                or any(ref in old for ref in updated["supersededBy"])):
            _fail("generation_requirement_history_changed", "Earlier requirements need explicit supersession, not rewriting.")
    if any(item["source"]["turnId"] not in new_turns for key, item in new.items() if key not in old):
        _fail("generation_requirement_history_changed", "New requirements must originate in the correction turn.")


def evaluate_generation_requirements(ledger: Mapping[str, Any], package: Mapping[str, Any], *, execution_context=None) -> dict[str, Any]:
    """Compare predicates to a package; this is not source admission or geometry validation."""
    record = validate_generation_ledger(ledger)
    if not isinstance(package, Mapping):
        _fail("generation_requirement_package_invalid", "Package comparison requires an object.")
    checks = []
    execution_context = execution_context or {}
    for item in record["requirements"]:
        if item["disposition"] == "superseded":
            continue
        passed = False
        code = "generation_requirement_unresolved"
        if item["disposition"] == "represented":
            predicate = item["predicate"]
            code = "generation_requirement_not_satisfied"
            if predicate["kind"] == "unsaved_preview":
                passed = True  # Admission and editor adapters must independently enforce this policy.
            elif predicate["kind"] == "preserve_prior_requirements":
                # The immutable amendment and ledger validators check retention
                # at this turn; the surviving predicates are all evaluated below.
                passed = True
            elif predicate["kind"] == "planning_subject":
                passed = package.get("productRef", {}).get("displayName") == predicate["parameters"]["productLabel"]
            elif predicate["kind"] == "catalog_only":
                entries = package.get("equipmentRequirements", [])
                eligible = execution_context.get("catalogIdentities", [])
                passed = bool(entries) and all(
                    {key: (entry.get("selectedCatalogIdentity") or {}).get(key) for key in ("assetId", "assetDefinitionRevision")} in eligible
                    for entry in entries)
            elif predicate["kind"] == "source_consulted":
                passed = any(source.get("evidenceRef") == predicate["subjectId"] and source.get("url") == predicate["parameters"]["url"]
                             for source in execution_context.get("consultedSources", []))
            elif predicate["kind"] == "assumptions_disclosed":
                passed = execution_context.get("assumptionsDisclosed") is True
            elif predicate["kind"] == "resource_quantity":
                entries = package.get("equipmentRequirements", [])
                matches = [entry for entry in (entries if isinstance(entries, list) else [])
                           if isinstance(entry, Mapping) and entry.get("requirementId") == predicate["subjectId"]]
                passed = (len(matches) == 1 and type(matches[0].get("quantity")) is int
                          and matches[0]["quantity"] == predicate["parameters"]["quantity"])
            elif predicate["kind"] == "envelope_dimensions":
                envelope = package.get("facilityEnvelope", {})
                envelope = envelope if isinstance(envelope, Mapping) else {}
                try:
                    actual = _dimensions({key: envelope.get(key) for key in ("width", "depth", "sourceUnit")})
                    passed = actual == _dimensions(predicate["parameters"])
                except GenerationRequirementError:
                    passed = False
            else:
                kind = predicate["kind"]
                collection, key = (("departments", "departmentId") if kind in {"department_allocation", "department_presence"}
                                   else ("equipmentRequirements", "requirementId"))
                values = package.get(collection, [])
                matches = [entry for entry in (values if isinstance(values, list) else [])
                           if isinstance(entry, Mapping) and entry.get(key) == predicate["subjectId"]]
                if len(matches) == 1:
                    entry, wanted = matches[0], predicate["parameters"]
                    if kind == "resource_mapping":
                        identity = entry.get("selectedCatalogIdentity") or {}
                        passed = (isinstance(identity, Mapping) and identity.get("assetId") == wanted["assetId"]
                                  and identity.get("assetDefinitionRevision") == wanted["assetDefinitionRevision"]
                                  and entry.get("processStepRefs") == wanted["processStepRefs"]
                                  and entry.get("targetArea") == wanted["targetArea"])
                    elif kind == "resource_spacing":
                        passed = entry.get("authoredSpacing") == wanted
                    else:
                        passed = all(entry.get(field) == value for field, value in wanted.items())
        checks.append({"requirementId": item["requirementId"], "passed": passed,
                       "code": None if passed else code})
    return {"ledgerRevision": record["ledgerRevision"], "checks": checks,
            "requirementsSatisfied": bool(checks) and all(check["passed"] for check in checks),
            "admissionGranted": False}


def guard_empty_generation_base(layout: Mapping[str, Any], *, expected_revision: str,
                                editor_context: Mapping[str, Any], mode: str = "new_empty_layout") -> None:
    if mode != "new_empty_layout":
        _fail("generation_authoring_mode_unsupported", "Replacement and incremental generation are disabled.")
    if not isinstance(layout, Mapping) or set(layout) - _ROOT_FIELDS:
        _fail("generation_base_extension_unsupported", "Unknown layout fields require explicit classification.")
    for field in EMPTY_COLLECTIONS:
        if layout.get(field, [] if field == "floorMarkings" else None) != []:
            _fail("generation_base_not_empty", "Generation requires empty canonical collections.", field=field)
    extensions = layout.get("extensions", {})
    if not isinstance(extensions, Mapping) or set(extensions) - {PLAN_SETTINGS_EXTENSION_KEY}:
        _fail("generation_base_extension_unsupported", "Content-bearing or unknown extensions are not an empty base.")
    if PLAN_SETTINGS_EXTENSION_KEY in extensions:
        normalize_plan_settings(extensions[PLAN_SETTINGS_EXTENSION_KEY])
    if not isinstance(layout.get("status"), str) or layout["status"] not in {"draft", "active", "template"}:
        _fail("generation_base_read_only", "The selected layout is not writable.")
    revision(expected_revision, "expectedRevision")
    if layout_revision(layout) != expected_revision:
        _fail("generation_base_revision_conflict", "The empty base changed.")
    _closed(editor_context, {"baseRevision", "draftRevision", "dirty", "conflicted", "pending",
                            "generationRunId", "designTransactionId"}, "editorContext")
    if any(editor_context[field] != expected_revision for field in ("baseRevision", "draftRevision")):
        _fail("generation_base_revision_conflict", "The editor does not match the captured empty base.")
    if (any(editor_context[field] is not False for field in ("dirty", "conflicted", "pending"))
            or editor_context["generationRunId"] is not None or editor_context["designTransactionId"] is not None):
        _fail("generation_editor_not_clean", "Generation requires a clean editor with no active transaction.")


def guard_generation_operations(operations: Any) -> None:
    """Guard each kernel batch; field/geometry validation is still mandatory."""
    _array(operations, "operations", MAX_OPERATION_BATCH)
    for index, operation in enumerate(operations):
        if (not isinstance(operation, Mapping) or not isinstance(operation.get("op"), str)
                or operation["op"] not in _CREATION_OPERATIONS):
            _fail("generation_operation_unsupported", "Operation is outside the new-empty-layout slice.", operationIndex=index)
