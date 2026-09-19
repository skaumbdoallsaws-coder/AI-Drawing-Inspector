"""Closed, coordinate-free contracts for persistent Facility design briefs."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


FACILITY_DESIGN_BRIEF_SCHEMA_VERSION = "facility-design-brief-v1"
FACILITY_DESIGN_BRIEF_MAXIMUM_CANONICAL_BYTES = 65_536
FACILITY_DESIGN_BRIEF_MODEL_SLICE_MAXIMUM_BYTES = 8_192
FACILITY_DESIGN_BRIEF_MAXIMUM_HARD_CONSTRAINTS = 100
FACILITY_DESIGN_BRIEF_MAXIMUM_PREFERENCES = 32
FACILITY_DESIGN_BRIEF_MAXIMUM_PERMITTED_CHANGES = 100
FACILITY_DESIGN_BRIEF_MAXIMUM_ASSUMPTIONS = 100
FACILITY_DESIGN_BRIEF_MAXIMUM_UNKNOWNS = 100
FACILITY_DESIGN_BRIEF_MAXIMUM_DECISION_REFS = 100

FACILITY_DESIGN_OBJECTIVE_KINDS = frozenset(
    {"reduce_loaded_material_travel_v1"}
)
FACILITY_DESIGN_METRIC_IDS = frozenset(
    {
        "loadedRouteDistanceMeters",
        "loadedTravelMetersPerShift",
        "movedPlacementCount",
        "placementDisplacementMeters",
        "rotatedPlacementCount",
        "changedRouteCount",
        "affectedProcessBindingCount",
    }
)
FACILITY_DESIGN_CONSTRAINT_KINDS = frozenset(
    {
        "preserve_entity_geometry",
        "preserve_entity_identity",
        "preserve_route_geometry",
        "preserve_process_binding",
        "remain_inside_area",
    }
)
FACILITY_DESIGN_DEFERRED_CONSTRAINT_KINDS = frozenset(
    {"retain_required_adjacency", "retain_required_access"}
)
FACILITY_DESIGN_OPERATION_KINDS = frozenset(
    {
        "move_placement_within_area",
        "rotate_placement_fit",
        "edit_material_route",
        "move_route_bound_endpoint",
    }
)
FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION = "facility-design-constraints-v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COORDINATE_KEYS = frozenset(
    {
        "x",
        "y",
        "z",
        "position",
        "localPosition",
        "worldPosition",
        "coordinates",
        "coordinate",
        "centerline",
        "boundary",
        "transform",
        "quaternion",
    }
)
_BODY_FIELDS = frozenset(
    {
        "status",
        "tenantId",
        "siteId",
        "workspaceId",
        "layoutId",
        "baseStateRef",
        "objective",
        "scopeRefs",
        "hardConstraints",
        "preferences",
        "permittedChanges",
        "assumptions",
        "unknowns",
        "referents",
        "decisionRefs",
        "revisionVector",
    }
)
_RECORD_FIELDS = frozenset(
    {
        "schemaVersion",
        "briefId",
        "briefRevision",
        "parentBriefRevision",
        "briefSemanticFingerprint",
        "semanticBody",
        "sourceTurnRefs",
        "createdBy",
        "createdAt",
    }
)


class FacilityDesignBriefError(ValueError):
    """Stable fail-closed error for the Facility design-brief contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _fail(
    code: str,
    message: str,
    *,
    path: str | None = None,
    **details: Any,
) -> None:
    if path is not None:
        details["path"] = path
    raise FacilityDesignBriefError(code, message, details=details)


def canonical_design_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityDesignBriefError(
            "facility_design_not_canonical",
            "Facility design content is not canonical JSON.",
        ) from exc


def design_revision(value: Any) -> str:
    return hashlib.sha256(canonical_design_bytes(value)).hexdigest()


def _closed(value: Mapping[str, Any], allowed: set[str] | frozenset[str], path: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        _fail(
            "facility_design_brief_invalid",
            "Facility design brief contains unsupported fields.",
            path=path,
            unsupportedFields=unknown,
        )


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("facility_design_brief_invalid", "Expected an object.", path=path)
    return deepcopy(dict(value))


def _array(value: Any, path: str, maximum: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        _fail("facility_design_brief_invalid", "Expected an array.", path=path)
    if maximum is not None and len(value) > maximum:
        _fail(
            "facility_design_brief_limit_exceeded",
            "Facility design brief collection exceeds its limit.",
            path=path,
            maximumItems=maximum,
            actualItems=len(value),
        )
    return deepcopy(value)


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _fail(
            "facility_design_brief_invalid",
            "Expected a stable identifier.",
            path=path,
        )
    return value


def _revision(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(
            "facility_design_brief_invalid",
            "Expected a lowercase SHA-256 revision.",
            path=path,
        )
    return value


def _text(value: Any, path: str, *, maximum: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(
            "facility_design_brief_invalid",
            "Expected non-empty bounded text.",
            path=path,
        )
    return value.strip()


def _timestamp(value: Any, path: str) -> str:
    if not isinstance(value, str):
        _fail("facility_design_brief_invalid", "Expected a UTC timestamp.", path=path)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FacilityDesignBriefError(
            "facility_design_brief_invalid",
            "Expected a UTC timestamp.",
            details={"path": path},
        ) from exc
    if parsed.tzinfo is None:
        _fail("facility_design_brief_invalid", "Expected a UTC timestamp.", path=path)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _assert_coordinate_free(value: Any, path: str = "$.semanticBody") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            if key in _COORDINATE_KEYS:
                _fail(
                    "facility_design_coordinates_forbidden",
                    "Facility design briefs cannot own geometry or coordinates.",
                    path=f"{path}.{key}",
                )
            _assert_coordinate_free(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_coordinate_free(child, f"{path}[{index}]")


def _entity_ref(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {"entityKind", "entityId", "sourceRevision"}
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Entity reference fields are invalid.", path=path)
    _identifier(result["entityKind"], f"{path}.entityKind")
    _identifier(result["entityId"], f"{path}.entityId")
    _revision(result["sourceRevision"], f"{path}.sourceRevision")
    return result


def _entity_refs(value: Any, path: str, *, maximum: int = 100) -> list[dict[str, Any]]:
    result = [
        _entity_ref(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path, maximum))
    ]
    keys = [(item["entityKind"], item["entityId"]) for item in result]
    if len(set(keys)) != len(keys):
        _fail("facility_design_brief_invalid", "Entity references must be unique.", path=path)
    return sorted(result, key=lambda item: (item["entityKind"], item["entityId"]))


def _stable_ids(value: Any, path: str, *, maximum: int) -> list[str]:
    result = [
        _identifier(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path, maximum))
    ]
    if len(set(result)) != len(result):
        _fail("facility_design_brief_invalid", "Identifiers must be unique.", path=path)
    return sorted(result)


def _base_state_ref(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {"baseId", "baseRevision", "baseKind", "layoutId", "layoutRevision"}
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Base-state reference fields are invalid.", path=path)
    _identifier(result["baseId"], f"{path}.baseId")
    _revision(result["baseRevision"], f"{path}.baseRevision")
    if result["baseKind"] not in {
        "saved_layout",
        "receipt_bound_draft",
        "editor_draft",
    }:
        _fail("facility_design_brief_invalid", "Base-state kind is unsupported.", path=f"{path}.baseKind")
    _identifier(result["layoutId"], f"{path}.layoutId")
    _revision(result["layoutRevision"], f"{path}.layoutRevision")
    return result


def _objective(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {
        "objectiveId",
        "objectiveKind",
        "targetRefs",
        "processBindingIds",
        "requestedMetricIds",
        "minimumImprovement",
        "evidenceRefs",
    }
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Objective fields are invalid.", path=path)
    _identifier(result["objectiveId"], f"{path}.objectiveId")
    if result["objectiveKind"] not in FACILITY_DESIGN_OBJECTIVE_KINDS:
        _fail("facility_design_objective_kind_unsupported", "Objective kind is unsupported.", path=f"{path}.objectiveKind")
    result["targetRefs"] = _entity_refs(result["targetRefs"], f"{path}.targetRefs")
    result["processBindingIds"] = _stable_ids(
        result["processBindingIds"], f"{path}.processBindingIds", maximum=20
    )
    result["requestedMetricIds"] = _stable_ids(
        result["requestedMetricIds"], f"{path}.requestedMetricIds", maximum=16
    )
    unknown_metrics = sorted(set(result["requestedMetricIds"]) - FACILITY_DESIGN_METRIC_IDS)
    if unknown_metrics:
        _fail(
            "facility_design_metric_unsupported",
            "Objective requests an unsupported metric.",
            path=f"{path}.requestedMetricIds",
            metricIds=unknown_metrics,
        )
    minimum = result["minimumImprovement"]
    if minimum is not None:
        minimum = _object(minimum, f"{path}.minimumImprovement")
        if set(minimum) != {"metricId", "value", "unit"}:
            _fail("facility_design_brief_invalid", "Minimum-improvement fields are invalid.", path=f"{path}.minimumImprovement")
        if minimum["metricId"] not in FACILITY_DESIGN_METRIC_IDS:
            _fail("facility_design_metric_unsupported", "Minimum-improvement metric is unsupported.", path=f"{path}.minimumImprovement.metricId")
        if isinstance(minimum["value"], bool) or not isinstance(minimum["value"], (int, float)):
            _fail("facility_design_brief_invalid", "Minimum improvement must be numeric.", path=f"{path}.minimumImprovement.value")
        _identifier(minimum["unit"], f"{path}.minimumImprovement.unit")
        result["minimumImprovement"] = minimum
    result["evidenceRefs"] = _stable_ids(
        result["evidenceRefs"], f"{path}.evidenceRefs", maximum=100
    )
    return result


def _hard_constraint(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {
        "constraintId",
        "constraintKind",
        "targetRefs",
        "predicateVersion",
        "authority",
        "evidenceRefs",
        "status",
        "sourceTurnRef",
        "supersededBy",
    }
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Hard-constraint fields are invalid.", path=path)
    _identifier(result["constraintId"], f"{path}.constraintId")
    kind = result["constraintKind"]
    if kind in FACILITY_DESIGN_DEFERRED_CONSTRAINT_KINDS:
        _fail(
            "facility_design_constraint_kind_unsupported",
            "This hard-constraint kind has no deterministic V1 predicate.",
            path=f"{path}.constraintKind",
            constraintKind=kind,
        )
    if kind not in FACILITY_DESIGN_CONSTRAINT_KINDS:
        _fail("facility_design_constraint_kind_unsupported", "Hard-constraint kind is unsupported.", path=f"{path}.constraintKind", constraintKind=kind)
    result["targetRefs"] = _entity_refs(result["targetRefs"], f"{path}.targetRefs")
    _identifier(result["predicateVersion"], f"{path}.predicateVersion")
    if result["predicateVersion"] != FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION:
        _fail(
            "facility_design_constraint_predicate_version_unsupported",
            "Hard constraint predicate version is unsupported.",
            path=f"{path}.predicateVersion",
            expectedPredicateVersion=FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
        )
    if result["authority"] not in {"user_authored", "reviewed_policy"}:
        _fail("facility_design_brief_invalid", "Hard-constraint authority is unsupported.", path=f"{path}.authority")
    result["evidenceRefs"] = _stable_ids(result["evidenceRefs"], f"{path}.evidenceRefs", maximum=100)
    if result["status"] not in {"active", "superseded", "withdrawn"}:
        _fail("facility_design_brief_invalid", "Hard-constraint status is unsupported.", path=f"{path}.status")
    _identifier(result["sourceTurnRef"], f"{path}.sourceTurnRef")
    if result["supersededBy"] is not None:
        _identifier(result["supersededBy"], f"{path}.supersededBy")
    return result


def _preference(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {"preferenceId", "metricId", "priority", "status", "sourceTurnRef"}
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Preference fields are invalid.", path=path)
    _identifier(result["preferenceId"], f"{path}.preferenceId")
    if result["metricId"] not in FACILITY_DESIGN_METRIC_IDS:
        _fail("facility_design_metric_unsupported", "Preference metric is unsupported.", path=f"{path}.metricId")
    if isinstance(result["priority"], bool) or not isinstance(result["priority"], int) or result["priority"] < 1:
        _fail("facility_design_brief_invalid", "Preference priority must be a positive integer.", path=f"{path}.priority")
    if result["status"] not in {"active", "superseded", "withdrawn"}:
        _fail("facility_design_brief_invalid", "Preference status is unsupported.", path=f"{path}.status")
    _identifier(result["sourceTurnRef"], f"{path}.sourceTurnRef")
    return result


def _permitted_change(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {
        "changeId",
        "targetRefs",
        "operationKinds",
        "containingAreaRef",
        "status",
        "sourceTurnRef",
        "withdrawnBy",
    }
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Permitted-change fields are invalid.", path=path)
    _identifier(result["changeId"], f"{path}.changeId")
    result["targetRefs"] = _entity_refs(result["targetRefs"], f"{path}.targetRefs")
    result["operationKinds"] = _stable_ids(result["operationKinds"], f"{path}.operationKinds", maximum=8)
    unsupported = sorted(set(result["operationKinds"]) - FACILITY_DESIGN_OPERATION_KINDS)
    if unsupported:
        _fail("facility_design_operation_kind_unsupported", "Permitted change names an unsupported operation.", path=f"{path}.operationKinds", operationKinds=unsupported)
    if result["containingAreaRef"] is not None:
        result["containingAreaRef"] = _entity_ref(result["containingAreaRef"], f"{path}.containingAreaRef")
    if result["status"] not in {"active", "superseded", "withdrawn"}:
        _fail("facility_design_brief_invalid", "Permitted-change status is unsupported.", path=f"{path}.status")
    _identifier(result["sourceTurnRef"], f"{path}.sourceTurnRef")
    if result["withdrawnBy"] is not None:
        _identifier(result["withdrawnBy"], f"{path}.withdrawnBy")
    return result


def _review_record(value: Any, path: str, id_field: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {id_field, "text", "reviewStatus", "evidenceRefs", "sourceTurnRef"}
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Review-record fields are invalid.", path=path)
    _identifier(result[id_field], f"{path}.{id_field}")
    result["text"] = _text(result["text"], f"{path}.text")
    if result["reviewStatus"] not in {"proposed", "accepted", "rejected"}:
        _fail("facility_design_brief_invalid", "Review status is unsupported.", path=f"{path}.reviewStatus")
    result["evidenceRefs"] = _stable_ids(result["evidenceRefs"], f"{path}.evidenceRefs", maximum=100)
    _identifier(result["sourceTurnRef"], f"{path}.sourceTurnRef")
    return result


def _unknown(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {"unknownId", "unknownKind", "text", "affectedRefIds", "sourceTurnRef"}
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Unknown-record fields are invalid.", path=path)
    _identifier(result["unknownId"], f"{path}.unknownId")
    _identifier(result["unknownKind"], f"{path}.unknownKind")
    result["text"] = _text(result["text"], f"{path}.text")
    result["affectedRefIds"] = _stable_ids(result["affectedRefIds"], f"{path}.affectedRefIds", maximum=100)
    _identifier(result["sourceTurnRef"], f"{path}.sourceTurnRef")
    return result


def _referent(value: Any, path: str) -> dict[str, Any]:
    result = _object(value, path)
    fields = {
        "referentId",
        "phrase",
        "targetRefs",
        "capturedLayoutRevision",
        "sourceTurnRef",
        "status",
    }
    if set(result) != fields:
        _fail("facility_design_brief_invalid", "Referent fields are invalid.", path=path)
    _identifier(result["referentId"], f"{path}.referentId")
    result["phrase"] = _text(result["phrase"], f"{path}.phrase", maximum=200)
    result["targetRefs"] = _entity_refs(result["targetRefs"], f"{path}.targetRefs")
    _revision(result["capturedLayoutRevision"], f"{path}.capturedLayoutRevision")
    _identifier(result["sourceTurnRef"], f"{path}.sourceTurnRef")
    if result["status"] not in {"active", "superseded", "withdrawn"}:
        _fail("facility_design_brief_invalid", "Referent status is unsupported.", path=f"{path}.status")
    return result


def _unique_records(records: Sequence[Mapping[str, Any]], id_field: str, path: str) -> None:
    ids = [str(record[id_field]) for record in records]
    if len(set(ids)) != len(ids):
        _fail("facility_design_brief_invalid", "Record IDs must be unique.", path=path)


def canonicalize_facility_design_semantic_body(value: Mapping[str, Any]) -> dict[str, Any]:
    body = _object(value, "$.semanticBody")
    if set(body) != _BODY_FIELDS:
        _fail("facility_design_brief_invalid", "Semantic-body fields are invalid.", path="$.semanticBody")
    _assert_coordinate_free(body)
    if body["status"] not in {"active", "archived"}:
        _fail("facility_design_brief_invalid", "Brief status is unsupported.", path="$.semanticBody.status")
    for field in ("tenantId", "siteId", "workspaceId", "layoutId"):
        _identifier(body[field], f"$.semanticBody.{field}")
    body["baseStateRef"] = _base_state_ref(body["baseStateRef"], "$.semanticBody.baseStateRef")
    if body["baseStateRef"]["layoutId"] != body["layoutId"]:
        _fail("facility_design_brief_invalid", "Base-state layout does not match the brief.", path="$.semanticBody.baseStateRef.layoutId")
    body["objective"] = _objective(body["objective"], "$.semanticBody.objective")
    body["scopeRefs"] = _entity_refs(body["scopeRefs"], "$.semanticBody.scopeRefs")

    body["hardConstraints"] = [
        _hard_constraint(item, f"$.semanticBody.hardConstraints[{index}]")
        for index, item in enumerate(_array(body["hardConstraints"], "$.semanticBody.hardConstraints", FACILITY_DESIGN_BRIEF_MAXIMUM_HARD_CONSTRAINTS))
    ]
    body["preferences"] = [
        _preference(item, f"$.semanticBody.preferences[{index}]")
        for index, item in enumerate(_array(body["preferences"], "$.semanticBody.preferences", FACILITY_DESIGN_BRIEF_MAXIMUM_PREFERENCES))
    ]
    body["permittedChanges"] = [
        _permitted_change(item, f"$.semanticBody.permittedChanges[{index}]")
        for index, item in enumerate(_array(body["permittedChanges"], "$.semanticBody.permittedChanges", FACILITY_DESIGN_BRIEF_MAXIMUM_PERMITTED_CHANGES))
    ]
    body["assumptions"] = [
        _review_record(item, f"$.semanticBody.assumptions[{index}]", "assumptionId")
        for index, item in enumerate(_array(body["assumptions"], "$.semanticBody.assumptions", FACILITY_DESIGN_BRIEF_MAXIMUM_ASSUMPTIONS))
    ]
    body["unknowns"] = [
        _unknown(item, f"$.semanticBody.unknowns[{index}]")
        for index, item in enumerate(_array(body["unknowns"], "$.semanticBody.unknowns", FACILITY_DESIGN_BRIEF_MAXIMUM_UNKNOWNS))
    ]
    body["referents"] = [
        _referent(item, f"$.semanticBody.referents[{index}]")
        for index, item in enumerate(_array(body["referents"], "$.semanticBody.referents", 100))
    ]
    body["decisionRefs"] = _stable_ids(body["decisionRefs"], "$.semanticBody.decisionRefs", maximum=FACILITY_DESIGN_BRIEF_MAXIMUM_DECISION_REFS)
    revision_vector = _object(body["revisionVector"], "$.semanticBody.revisionVector")
    if len(revision_vector) > 100:
        _fail("facility_design_brief_limit_exceeded", "Revision vector exceeds its limit.", path="$.semanticBody.revisionVector")
    body["revisionVector"] = {
        _identifier(key, f"$.semanticBody.revisionVector.{key}"): _revision(
            revision, f"$.semanticBody.revisionVector.{key}"
        )
        for key, revision in sorted(revision_vector.items())
    }

    collections = (
        ("hardConstraints", "constraintId"),
        ("preferences", "preferenceId"),
        ("permittedChanges", "changeId"),
        ("assumptions", "assumptionId"),
        ("unknowns", "unknownId"),
        ("referents", "referentId"),
    )
    for field, id_field in collections:
        _unique_records(body[field], id_field, f"$.semanticBody.{field}")
        if field == "preferences":
            body[field] = sorted(body[field], key=lambda item: (item["priority"], item[id_field]))
        else:
            body[field] = sorted(body[field], key=lambda item: item[id_field])

    active_locked_targets = {
        (ref["entityKind"], ref["entityId"])
        for constraint in body["hardConstraints"]
        if constraint["status"] == "active"
        and constraint["constraintKind"] in {
            "preserve_entity_geometry",
            "preserve_route_geometry",
        }
        for ref in constraint["targetRefs"]
    }
    conflicting_changes = [
        change["changeId"]
        for change in body["permittedChanges"]
        if change["status"] == "active"
        and any(
            (ref["entityKind"], ref["entityId"]) in active_locked_targets
            for ref in change["targetRefs"]
        )
    ]
    if conflicting_changes:
        _fail(
            "facility_design_brief_conflict",
            "An entity cannot be both geometry-locked and permitted to change.",
            path="$.semanticBody.permittedChanges",
            changeIds=sorted(conflicting_changes),
        )
    return body


def normalized_facility_design_semantics(value: Mapping[str, Any]) -> dict[str, Any]:
    body = canonicalize_facility_design_semantic_body(value)
    normalized = deepcopy(body)
    normalized["objective"].pop("objectiveId", None)
    normalized["baseStateRef"].pop("baseId", None)
    normalized["hardConstraints"] = [
        {
            key: deepcopy(item[key])
            for key in (
                "constraintKind",
                "targetRefs",
                "predicateVersion",
                "authority",
                "evidenceRefs",
            )
        }
        for item in normalized["hardConstraints"]
        if item.get("status") == "active"
    ]
    normalized["preferences"] = [
        {
            key: deepcopy(item[key])
            for key in ("metricId", "priority")
        }
        for item in normalized["preferences"]
        if item.get("status") == "active"
    ]
    normalized["permittedChanges"] = [
        {
            key: deepcopy(item[key])
            for key in ("targetRefs", "operationKinds", "containingAreaRef")
        }
        for item in normalized["permittedChanges"]
        if item.get("status") == "active"
    ]
    normalized["assumptions"] = [
        {
            key: deepcopy(item[key])
            for key in ("text", "reviewStatus", "evidenceRefs")
        }
        for item in normalized["assumptions"]
        if item["reviewStatus"] == "accepted"
    ]
    normalized["unknowns"] = [
        {
            key: deepcopy(item[key])
            for key in ("unknownKind", "text", "affectedRefIds")
        }
        for item in normalized["unknowns"]
    ]
    normalized["referents"] = [
        {
            key: deepcopy(item[key])
            for key in ("phrase", "targetRefs", "capturedLayoutRevision")
        }
        for item in normalized["referents"]
        if item.get("status") == "active"
    ]
    normalized["decisionRefs"] = []
    for field in (
        "hardConstraints",
        "preferences",
        "permittedChanges",
        "assumptions",
        "unknowns",
        "referents",
    ):
        normalized[field].sort(key=canonical_design_bytes)
    return normalized


def facility_design_semantic_fingerprint(value: Mapping[str, Any]) -> str:
    return design_revision(normalized_facility_design_semantics(value))


def _record_without_revision(record: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(record))
    result.pop("briefRevision", None)
    return result


def validate_facility_design_brief(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _object(value, "$")
    if set(record) != _RECORD_FIELDS:
        _fail("facility_design_brief_invalid", "Facility design brief record fields are invalid.", path="$")
    if record["schemaVersion"] != FACILITY_DESIGN_BRIEF_SCHEMA_VERSION:
        _fail("facility_design_brief_version_unsupported", "Facility design brief version is unsupported.", path="$.schemaVersion")
    _identifier(record["briefId"], "$.briefId")
    _revision(record["briefRevision"], "$.briefRevision")
    _revision(record["parentBriefRevision"], "$.parentBriefRevision", nullable=True)
    _revision(record["briefSemanticFingerprint"], "$.briefSemanticFingerprint")
    record["semanticBody"] = canonicalize_facility_design_semantic_body(record["semanticBody"])
    record["sourceTurnRefs"] = _stable_ids(record["sourceTurnRefs"], "$.sourceTurnRefs", maximum=100)
    created_by = _object(record["createdBy"], "$.createdBy")
    if set(created_by) != {"principalId", "authorityKind"}:
        _fail("facility_design_brief_invalid", "createdBy fields are invalid.", path="$.createdBy")
    _identifier(created_by["principalId"], "$.createdBy.principalId")
    if created_by["authorityKind"] not in {"user", "reviewed_policy", "system"}:
        _fail("facility_design_brief_invalid", "createdBy authority is unsupported.", path="$.createdBy.authorityKind")
    record["createdBy"] = created_by
    record["createdAt"] = _timestamp(record["createdAt"], "$.createdAt")
    expected_semantic = facility_design_semantic_fingerprint(record["semanticBody"])
    if record["briefSemanticFingerprint"] != expected_semantic:
        _fail("facility_design_brief_semantic_fingerprint_mismatch", "Brief semantic fingerprint does not match its active semantics.")
    expected_revision = design_revision(_record_without_revision(record))
    if record["briefRevision"] != expected_revision:
        _fail("facility_design_brief_revision_mismatch", "Brief revision does not match its immutable record bytes.")
    if len(canonical_design_bytes(record)) > FACILITY_DESIGN_BRIEF_MAXIMUM_CANONICAL_BYTES:
        _fail(
            "facility_design_brief_limit_exceeded",
            "Facility design brief exceeds its canonical byte limit.",
            maximumBytes=FACILITY_DESIGN_BRIEF_MAXIMUM_CANONICAL_BYTES,
        )
    return record


def create_facility_design_brief(
    *,
    brief_id: str,
    semantic_body: Mapping[str, Any],
    source_turn_refs: Sequence[str],
    principal_id: str,
    created_at: str,
    authority_kind: str = "user",
    parent_brief_revision: str | None = None,
) -> dict[str, Any]:
    body = canonicalize_facility_design_semantic_body(semantic_body)
    record = {
        "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
        "briefId": _identifier(brief_id, "$.briefId"),
        "briefRevision": "",
        "parentBriefRevision": parent_brief_revision,
        "briefSemanticFingerprint": facility_design_semantic_fingerprint(body),
        "semanticBody": body,
        "sourceTurnRefs": sorted({_identifier(item, "$.sourceTurnRefs") for item in source_turn_refs}),
        "createdBy": {
            "principalId": _identifier(principal_id, "$.createdBy.principalId"),
            "authorityKind": authority_kind,
        },
        "createdAt": _timestamp(created_at, "$.createdAt"),
    }
    _revision(parent_brief_revision, "$.parentBriefRevision", nullable=True)
    record["briefRevision"] = design_revision(_record_without_revision(record))
    return validate_facility_design_brief(record)


def facility_design_model_slice(value: Mapping[str, Any]) -> dict[str, Any]:
    record = validate_facility_design_brief(value)
    body = normalized_facility_design_semantics(record["semanticBody"])
    result = {
        "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
        "briefId": record["briefId"],
        "briefRevision": record["briefRevision"],
        "briefSemanticFingerprint": record["briefSemanticFingerprint"],
        "semanticBody": body,
    }
    if len(canonical_design_bytes(result)) > FACILITY_DESIGN_BRIEF_MODEL_SLICE_MAXIMUM_BYTES:
        _fail(
            "facility_design_brief_model_slice_exceeded",
            "Active Facility design brief exceeds the model-visible byte limit.",
            maximumBytes=FACILITY_DESIGN_BRIEF_MODEL_SLICE_MAXIMUM_BYTES,
        )
    return result


def _record_id_field(collection: str) -> str:
    fields = {
        "hardConstraints": "constraintId",
        "preferences": "preferenceId",
        "permittedChanges": "changeId",
        "assumptions": "assumptionId",
        "unknowns": "unknownId",
        "referents": "referentId",
    }
    if collection not in fields:
        _fail("facility_design_brief_patch_invalid", "Brief patch collection is unsupported.", collection=collection)
    return fields[collection]


def apply_facility_design_brief_patch(
    current: Mapping[str, Any],
    patch: Mapping[str, Any],
    *,
    source_turn_ref: str,
    principal_id: str,
    created_at: str,
) -> dict[str, Any]:
    record = validate_facility_design_brief(current)
    change = _object(patch, "$.patch")
    if set(change) != {"schemaVersion", "expectedBriefRevision", "operations"}:
        _fail("facility_design_brief_patch_invalid", "Brief patch fields are invalid.", path="$.patch")
    if change["schemaVersion"] != FACILITY_DESIGN_BRIEF_SCHEMA_VERSION:
        _fail("facility_design_brief_patch_invalid", "Brief patch version is unsupported.", path="$.patch.schemaVersion")
    if change["expectedBriefRevision"] != record["briefRevision"]:
        _fail(
            "facility_design_brief_revision_conflict",
            "Facility design brief changed after the patch was prepared.",
            expectedBriefRevision=change["expectedBriefRevision"],
            currentBriefRevision=record["briefRevision"],
        )
    operations = _array(change["operations"], "$.patch.operations", 100)
    if not operations:
        _fail("facility_design_brief_patch_invalid", "Brief patch requires at least one operation.", path="$.patch.operations")
    body = deepcopy(record["semanticBody"])
    turn = _identifier(source_turn_ref, "$.sourceTurnRef")
    for index, raw_operation in enumerate(operations):
        path = f"$.patch.operations[{index}]"
        operation = _object(raw_operation, path)
        if set(operation) != {"action", "collection", "recordId", "record"}:
            _fail("facility_design_brief_patch_invalid", "Brief patch operation fields are invalid.", path=path)
        collection = operation["collection"]
        id_field = _record_id_field(collection)
        action = operation["action"]
        records = body[collection]
        record_id = operation["recordId"]
        if record_id is not None:
            record_id = _identifier(record_id, f"{path}.recordId")
        matches = [item for item in records if item[id_field] == record_id]
        if action == "add":
            if record_id is not None or operation["record"] is None:
                _fail("facility_design_brief_patch_invalid", "Add requires record and no recordId.", path=path)
            candidate = deepcopy(operation["record"])
            if not isinstance(candidate, Mapping):
                _fail("facility_design_brief_patch_invalid", "Add record must be an object.", path=f"{path}.record")
            candidate = dict(candidate)
            candidate["sourceTurnRef"] = turn
            if any(item[id_field] == candidate.get(id_field) for item in records):
                _fail("facility_design_brief_conflict", "Brief record ID already exists.", path=path)
            records.append(candidate)
            if collection == "hardConstraints" and candidate.get("status") == "active":
                locked = {
                    (ref.get("entityKind"), ref.get("entityId"))
                    for ref in candidate.get("targetRefs", [])
                }
                for permitted in body["permittedChanges"]:
                    if permitted.get("status") == "active" and any(
                        (ref.get("entityKind"), ref.get("entityId")) in locked
                        for ref in permitted.get("targetRefs", [])
                    ):
                        permitted["status"] = "withdrawn"
                        permitted["withdrawnBy"] = candidate.get("constraintId")
        elif action in {"supersede", "withdraw", "correct", "reorder"}:
            if len(matches) != 1:
                _fail("facility_design_brief_patch_target_missing", "Brief patch target was not found exactly once.", path=path)
            target = matches[0]
            if action == "reorder":
                if collection != "preferences" or set(
                    _object(operation["record"], f"{path}.record")
                ) != {"priority"}:
                    _fail(
                        "facility_design_brief_patch_invalid",
                        "Reorder requires one preference priority.",
                        path=path,
                    )
                priority = operation["record"]["priority"]
                if (
                    isinstance(priority, bool)
                    or not isinstance(priority, int)
                    or priority < 1
                ):
                    _fail(
                        "facility_design_brief_patch_invalid",
                        "Preference priority must be a positive integer.",
                        path=f"{path}.record.priority",
                    )
                target["priority"] = priority
                target["sourceTurnRef"] = turn
            elif action == "withdraw":
                if operation["record"] is not None:
                    _fail("facility_design_brief_patch_invalid", "Withdraw cannot include a record.", path=path)
                if "status" not in target:
                    _fail("facility_design_brief_patch_invalid", "This record kind cannot be withdrawn.", path=path)
                target["status"] = "withdrawn"
                if collection == "permittedChanges":
                    target["withdrawnBy"] = turn
                elif collection == "hardConstraints":
                    target["supersededBy"] = turn
            else:
                if operation["record"] is None:
                    _fail("facility_design_brief_patch_invalid", "Replacement operation requires a record.", path=path)
                replacement = deepcopy(dict(_object(operation["record"], f"{path}.record")))
                replacement["sourceTurnRef"] = turn
                replacement_id = replacement.get(id_field)
                if replacement_id == record_id:
                    _fail("facility_design_brief_patch_invalid", "Replacement must use a new stable record ID.", path=path)
                if any(item[id_field] == replacement_id for item in records):
                    _fail("facility_design_brief_conflict", "Replacement record ID already exists.", path=path)
                if "status" in target:
                    target["status"] = "superseded"
                    if collection == "hardConstraints":
                        target["supersededBy"] = replacement_id
                    elif collection == "permittedChanges":
                        target["withdrawnBy"] = replacement_id
                records.append(replacement)
        else:
            _fail("facility_design_brief_patch_invalid", "Brief patch action is unsupported.", path=f"{path}.action")
    return create_facility_design_brief(
        brief_id=record["briefId"],
        semantic_body=body,
        source_turn_refs=[*record["sourceTurnRefs"], turn],
        principal_id=principal_id,
        created_at=created_at,
        parent_brief_revision=record["briefRevision"],
    )


__all__ = [
    "FACILITY_DESIGN_BRIEF_MAXIMUM_CANONICAL_BYTES",
    "FACILITY_DESIGN_BRIEF_MODEL_SLICE_MAXIMUM_BYTES",
    "FACILITY_DESIGN_BRIEF_SCHEMA_VERSION",
    "FACILITY_DESIGN_CONSTRAINT_KINDS",
    "FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION",
    "FACILITY_DESIGN_DEFERRED_CONSTRAINT_KINDS",
    "FACILITY_DESIGN_METRIC_IDS",
    "FACILITY_DESIGN_OBJECTIVE_KINDS",
    "FACILITY_DESIGN_OPERATION_KINDS",
    "FacilityDesignBriefError",
    "apply_facility_design_brief_patch",
    "canonical_design_bytes",
    "canonicalize_facility_design_semantic_body",
    "create_facility_design_brief",
    "design_revision",
    "facility_design_model_slice",
    "facility_design_semantic_fingerprint",
    "normalized_facility_design_semantics",
    "validate_facility_design_brief",
]
