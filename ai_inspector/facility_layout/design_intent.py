"""Coordinate-free Sage intent contracts for the Facility design loop.

The language model may identify objectives, named entities, preferences, and an
exact proposal selected by the user.  It never supplies geometry, metric
verdicts, candidate operations, or persistence authority through this surface.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from .design_base import facility_design_base_ref, validate_facility_design_base
from .design_brief import (
    FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
    FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
    FACILITY_DESIGN_METRIC_IDS,
    validate_facility_design_brief,
)


FACILITY_DESIGN_INTENT_SCHEMA_VERSION = "facility-design-intent-v1"
INSPECT_FACILITY_DESIGN_BRIEF_TOOL = "inspect_facility_design_brief"
UPDATE_FACILITY_DESIGN_BRIEF_TOOL = "update_facility_design_brief"
RUN_FACILITY_DESIGN_PREVIEW_TOOL = "run_facility_design_preview"
APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL = (
    "apply_facility_design_proposal_draft"
)

FACILITY_DESIGN_TOOLS = frozenset(
    {
        INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
        UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
        RUN_FACILITY_DESIGN_PREVIEW_TOOL,
        APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL,
    }
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COORDINATE_KEYS = frozenset(
    {
        "x",
        "y",
        "z",
        "position",
        "coordinates",
        "centerline",
        "boundary",
        "transform",
        "quaternion",
        "waypoints",
    }
)
_INITIAL_OBJECTIVE = re.compile(
    r"\b(?:reduce|cut|shorten|minimi[sz]e|optimi[sz]e|improve|lower)\b"
    r"[^.!?]{0,100}\b(?:loaded\s+)?(?:material\s+)?"
    r"(?:travel|movement|handling|route\s+distance)\b",
    re.IGNORECASE,
)
_HYPOTHETICAL_QUESTION = re.compile(
    r"\b(?:what\s+if|what\s+would\s+happen\s+if|"
    r"would\s+(?:it|this|that|the\s+[^.!?]{1,40}))\b",
    re.IGNORECASE,
)
_LOCK = re.compile(
    r"\b(?:keep|hold|lock|preserve|leave)\b[^.!?]{0,120}"
    r"\b(?:fixed|unchanged|where\s+(?:it\s+is|they\s+are)|in\s+place)\b"
    r"|\b(?:must\s+not|do\s+not|don['\u2019]?t)\s+move\b",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"\bprefer\b|\bfewer\s+(?:equipment\s+)?moves?\b|"
    r"\blower\s+disruption\b|\bshort(?:er|est)\s+(?:route|travel)\b",
    re.IGNORECASE,
)
_OPTIONS = re.compile(
    r"\b(?:best|remaining|alternative|option|proposal|trade[-\s]?off|compare|rank)\w*\b",
    re.IGNORECASE,
)
_APPLY = re.compile(
    r"\b(?:apply|install|use|select|accept)\b[^.!?]{0,140}"
    r"\b(?:proposal|alternative|option|one|it|that)\b",
    re.IGNORECASE,
)
_NEGATED_APPLY = re.compile(
    r"\b(?:do\s+not|don['\u2019]?t|not\s+yet|without)\b"
    r"[^.!?]{0,40}\b(?:apply|install|accept)\b"
    r"|\b(?:apply|install|accept)\b[^.!?]{0,24}\bnot\s+yet\b",
    re.IGNORECASE,
)
_UNDO = re.compile(
    r"^\s*(?:please\s+)?(?:undo|revert|roll\s+back)\b",
    re.IGNORECASE,
)
_INSPECT = re.compile(
    r"\b(?:show|inspect|summari[sz]e|explain|what(?:'s|\s+is))\b"
    r"[^.!?]{0,100}\b(?:design\s+brief|objective|constraints?|locks?|priorities)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_CLAIM = re.compile(
    r"\b(?:safe|safety|compliant|compliance|osha|fire\s+code|"
    r"throughput|capacity|staffing|production\s+rate|optimal)\b",
    re.IGNORECASE,
)
_FAST_PATH_UNRESOLVED_QUALIFIER = re.compile(
    r"\b(?:but|except|unless|either|or|not\s+both|only\s+one|"
    r"at\s+most|at\s+least|no\s+more\s+than|up\s+to|within)\b",
    re.IGNORECASE,
)
_SAFE_NEGATED_COMMIT_CLAUSE = re.compile(
    r"\bbut\s+(?:do\s+not|don['\u2019]?t)\s+"
    r"(?:apply|save)\b[^.!?]*",
    re.IGNORECASE,
)
_CHANGE_PERMISSION = re.compile(
    r"\b(?:you\s+)?(?:may|can|could|(?:are\s+)?allowed\s+to)\s+"
    r"(?:move|relocate|reposition|reroute|change|rebuild)\b",
    re.IGNORECASE,
)
_CHANGE_DIRECTIVE = re.compile(
    r"\b(?:move|relocate|reposition|reroute|change|rebuild)\b",
    re.IGNORECASE,
)
_CHANGE_PERMISSION_CLAUSE = re.compile(
    r"\b(?:you\s+)?(?:may|can|could|(?:are\s+)?allowed\s+to)\s+"
    r"(?P<verb>move|relocate|reposition|reroute|change|rebuild)\s+"
    r"(?P<targets>.+?)"
    r"(?=(?:,\s*)?(?:and\s+)?(?:you\s+)?"
    r"(?:may|can|could|(?:are\s+)?allowed\s+to)\s+"
    r"(?:move|relocate|reposition|reroute|change|rebuild)\b|$)",
    re.IGNORECASE,
)
_LOCK_TARGET_CLAUSE = re.compile(
    r"\b(?:keep|hold|lock|preserve|leave)\s+"
    r"(?P<targets>.+?)\s+"
    r"(?:(?:exactly\s+)?(?:fixed|unchanged|in\s+place)|"
    r"(?:exactly\s+)?where\s+(?:it\s+is|they\s+are))\b",
    re.IGNORECASE,
)
_MOVE_PERMISSION = re.compile(
    r"\b(?:may|can|could|allowed\s+to)\s+"
    r"(?:move|relocate|reposition)\b",
    re.IGNORECASE,
)
_METRIC_PATTERNS = (
    (
        re.compile(
            r"\bfewer\s+(?:equipment\s+)?moves?\b|"
            r"\blower\s+disruption\b",
            re.IGNORECASE,
        ),
        "movedPlacementCount",
    ),
    (
        re.compile(
            r"\bshort(?:er|est)\s+(?:loaded\s+)?(?:route|travel)\b|"
            r"\b(?:loaded\s+)?route\s+distance\b|"
            r"\bloaded\s+material\s+travel\b",
            re.IGNORECASE,
        ),
        "loadedRouteDistanceMeters",
    ),
)


class FacilityDesignIntentError(ValueError):
    """Stable failure for model-visible design intent compilation."""

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


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignIntentError(code, message, details=details)


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _has_unresolved_fast_path_qualifier(value: str) -> bool:
    semantic_text = _SAFE_NEGATED_COMMIT_CLAUSE.sub(" ", value)
    return bool(_FAST_PATH_UNRESOLVED_QUALIFIER.search(semantic_text))


def _identifier(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if (
        not result
        or len(result) > 160
        or not result[0].isalnum()
        or any(not (item.isalnum() or item in "._:-") for item in result)
    ):
        _fail("facility_design_intent_invalid", f"{field} is malformed.", field=field)
    return result


def _turn_identifier(value: Any) -> str:
    raw = _normalized(value)
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "-", raw).strip("-.")
    if cleaned and cleaned[0].isalnum():
        return cleaned[:160]
    return "turn-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _assert_coordinate_free(value: Any, path: str = "$.intent") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in _COORDINATE_KEYS:
                _fail(
                    "facility_design_coordinate_ownership",
                    "Sage cannot author Facility design coordinates.",
                    path=f"{path}.{key}",
                )
            _assert_coordinate_free(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, nested in enumerate(value):
            _assert_coordinate_free(nested, f"{path}[{index}]")


def _label_array(value: Any, field: str, *, maximum: int = 20) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail(
            "facility_design_intent_invalid",
            f"{field} must be a bounded array.",
            field=field,
        )
    labels = [_normalized(item) for item in value]
    if any(not item or len(item) > 200 for item in labels):
        _fail("facility_design_intent_invalid", f"{field} contains an invalid label.")
    if len({item.casefold() for item in labels}) != len(labels):
        _fail("facility_design_intent_invalid", f"{field} contains duplicates.")
    return labels


def canonicalize_facility_design_intent(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the small semantic surface exposed to Sage."""

    if not isinstance(value, Mapping):
        _fail("facility_design_intent_invalid", "Facility design intent must be an object.")
    _assert_coordinate_free(value)
    result = deepcopy(dict(value))
    allowed = {
        "schema_version",
        "operation",
        "brief_id",
        "expected_brief_revision",
        "source_label",
        "target_label",
        "loaded_trips_per_shift",
        "shift_name",
        "locked_entity_labels",
        "movable_placement_labels",
        "mutable_route_labels",
        "target_labels",
        "preference_metric_ids",
    }
    if set(result) - allowed:
        _fail(
            "facility_design_intent_invalid",
            "Facility design intent contains unsupported fields.",
            fields=sorted(set(result) - allowed),
        )
    if result.get("schema_version") != FACILITY_DESIGN_INTENT_SCHEMA_VERSION:
        _fail("facility_design_intent_invalid", "Facility design intent version is unsupported.")
    operation = str(result.get("operation") or "")
    if operation not in {
        "create_material_travel_brief",
        "add_geometry_locks",
        "set_preference_order",
    }:
        _fail(
            "facility_design_intent_invalid",
            "Facility design intent operation is unsupported.",
            operation=operation,
        )
    result["operation"] = operation
    if result.get("brief_id") is not None:
        result["brief_id"] = _identifier(result["brief_id"], "brief_id")
    revision = result.get("expected_brief_revision")
    if revision is not None and not _HASH_RE.fullmatch(str(revision)):
        _fail("facility_design_intent_invalid", "expected_brief_revision must be a SHA-256 hash.")
    if operation == "create_material_travel_brief":
        for field in ("source_label", "target_label"):
            text = _normalized(result.get(field))
            if not text or len(text) > 200:
                _fail("facility_design_intent_invalid", f"{field} is required.")
            result[field] = text
        trips = result.get("loaded_trips_per_shift")
        if isinstance(trips, bool) or not isinstance(trips, int) or trips < 1 or trips > 1_000_000:
            _fail(
                "facility_design_intent_invalid",
                "loaded_trips_per_shift must be a positive integer.",
            )
        result["shift_name"] = _normalized(result.get("shift_name"))
        if not result["shift_name"] or len(result["shift_name"]) > 120:
            _fail("facility_design_intent_invalid", "shift_name is required.")
        result["locked_entity_labels"] = _label_array(
            result.get("locked_entity_labels"), "locked_entity_labels"
        )
        result["movable_placement_labels"] = _label_array(
            result.get("movable_placement_labels"), "movable_placement_labels"
        )
        result["mutable_route_labels"] = _label_array(
            result.get("mutable_route_labels"), "mutable_route_labels"
        )
    elif operation == "add_geometry_locks":
        result["target_labels"] = _label_array(
            result.get("target_labels"), "target_labels"
        )
        if not result["target_labels"]:
            _fail("facility_design_intent_invalid", "At least one lock target is required.")
    else:
        metrics = _label_array(
            result.get("preference_metric_ids"),
            "preference_metric_ids",
            maximum=8,
        )
        if not metrics or any(item not in FACILITY_DESIGN_METRIC_IDS for item in metrics):
            _fail(
                "facility_design_metric_unsupported",
                "Preference order contains an unsupported metric.",
                metricIds=metrics,
            )
        result["preference_metric_ids"] = metrics
    return result


def classify_facility_design_turn(
    message: str,
    *,
    active_design: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one turn without upgrading it to geometry authority."""

    text = _normalized(message)
    active = bool(
        isinstance(active_design, Mapping)
        and active_design.get("briefId")
        and active_design.get("briefRevision")
    )
    if not text:
        return {"kind": "not_applicable"}
    initial_objective = bool(_INITIAL_OBJECTIVE.search(text))
    if initial_objective and _UNSUPPORTED_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_design_claim_unsupported",
            "response": (
                "I can compare revision-bound material-travel and disruption "
                "metrics, but I cannot claim safety, compliance, throughput, "
                "capacity, staffing, or global optimality from this design loop."
            ),
        }
    if _HYPOTHETICAL_QUESTION.search(text):
        return {"kind": "not_applicable"}
    if initial_objective:
        return {"kind": "design", "action": "create_and_preview"}
    if not active:
        return {"kind": "not_applicable"}
    if _UNDO.search(text):
        return {"kind": "design", "action": "undo"}
    if _APPLY.search(text) and not _NEGATED_APPLY.search(text):
        return {"kind": "design", "action": "apply"}
    if _LOCK.search(text):
        return {"kind": "design", "action": "update_and_preview"}
    if _PREFERENCE.search(text):
        return {"kind": "design", "action": "update_and_preview"}
    if _OPTIONS.search(text):
        return {"kind": "design", "action": "preview"}
    if _INSPECT.search(text):
        return {"kind": "design", "action": "inspect"}
    return {"kind": "not_applicable"}


def recover_facility_design_update_intent(
    message: str,
    *,
    active_design: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover a narrow update from explicit user-owned semantic language.

    This is a formatting backstop for provider-native tool calls, not a design
    inference path. Locks resolve only phrases already captured as exact active
    referents, and preference order uses only metric meanings explicitly named
    by the user.
    """

    turn = classify_facility_design_turn(message, active_design=active_design)
    if turn != {"kind": "design", "action": "update_and_preview"}:
        return None
    text = _normalized(message)
    if _LOCK.search(text):
        if _PREFERENCE.search(text) or _MOVE_PERMISSION.search(text):
            return None
        if _has_unresolved_fast_path_qualifier(text):
            return None
        clauses = list(_LOCK_TARGET_CLAUSE.finditer(text))
        if not _clauses_cover_text(text, clauses):
            return None
        matched: list[str] = []
        seen: set[str] = set()
        for clause in clauses:
            labels = _exact_active_referents_in_span(
                clause.group("targets"),
                active_design=active_design,
            )
            if labels is None:
                return None
            for phrase in labels:
                key = phrase.casefold()
                if key in seen:
                    continue
                seen.add(key)
                matched.append(phrase)
        if matched:
            return canonicalize_facility_design_intent({
                "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                "operation": "add_geometry_locks",
                "target_labels": matched,
            })
        return None
    if _PREFERENCE.search(text):
        metric_ids = _exact_preference_order(text)
        if metric_ids:
            return canonicalize_facility_design_intent({
                "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                "operation": "set_preference_order",
                "preference_metric_ids": metric_ids,
            })
    return None


def facility_design_allowed_tools(
    action: str,
    *,
    apply_enabled: bool,
) -> frozenset[str]:
    if action == "create_and_preview" or action == "update_and_preview":
        return frozenset(
            {
                INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
                UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
                RUN_FACILITY_DESIGN_PREVIEW_TOOL,
            }
        )
    if action == "preview":
        return frozenset(
            {
                INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
                RUN_FACILITY_DESIGN_PREVIEW_TOOL,
            }
        )
    if action == "apply":
        tools = {INSPECT_FACILITY_DESIGN_BRIEF_TOOL}
        if apply_enabled:
            tools.add(APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL)
        return frozenset(tools)
    if action == "inspect":
        return frozenset({INSPECT_FACILITY_DESIGN_BRIEF_TOOL})
    return frozenset()


def facility_design_agent_tool_specs(*, apply_enabled: bool) -> list[dict[str, Any]]:
    """Return provider-native closed schemas for the FDL surface."""

    identifier = {"type": "string", "minLength": 1, "maxLength": 160}
    revision = {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    label_array = {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "maxLength": 200},
        "maxItems": 20,
        "uniqueItems": True,
    }
    intent_properties = {
        "schema_version": {
            "type": "string",
            "enum": [FACILITY_DESIGN_INTENT_SCHEMA_VERSION],
        },
        "operation": {
            "type": "string",
            "enum": [
                "create_material_travel_brief",
                "add_geometry_locks",
                "set_preference_order",
            ],
        },
        "brief_id": identifier,
        "expected_brief_revision": revision,
        "source_label": {"type": "string", "minLength": 1, "maxLength": 200},
        "target_label": {"type": "string", "minLength": 1, "maxLength": 200},
        "loaded_trips_per_shift": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
        "shift_name": {"type": "string", "minLength": 1, "maxLength": 120},
        "locked_entity_labels": label_array,
        "movable_placement_labels": label_array,
        "mutable_route_labels": label_array,
        "target_labels": label_array,
        "preference_metric_ids": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(FACILITY_DESIGN_METRIC_IDS)},
            "minItems": 1,
            "maxItems": 8,
            "uniqueItems": True,
        },
    }
    specs = [
        {
            "name": INSPECT_FACILITY_DESIGN_BRIEF_TOOL,
            "description": (
                "Inspect the active revision-bound Facility design objective, "
                "locks, permitted changes, preferences, unknowns, and exact "
                "proposal references. This never changes layout or design state."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"brief_id": identifier, "brief_revision": revision},
                "additionalProperties": False,
            },
        },
        {
            "name": UPDATE_FACILITY_DESIGN_BRIEF_TOOL,
            "description": (
                "Create or revise the active FacilityDesignBrief from coordinate-free "
                "semantic intent. Use labels or stable IDs only; never provide geometry "
                "or deterministic metric verdicts."
            ),
            "input_schema": {
                "type": "object",
                "properties": intent_properties,
                "required": ["schema_version", "operation"],
                "additionalProperties": False,
            },
        },
        {
            "name": RUN_FACILITY_DESIGN_PREVIEW_TOOL,
            "description": (
                "Start or resume the bounded deterministic design workflow for the "
                "active brief and return baseline plus at most two unsaved proposals."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "brief_id": identifier,
                    "brief_revision": revision,
                    "run_id": identifier,
                    "mode": {"type": "string", "enum": ["production_sage", "lab"]},
                },
                "additionalProperties": False,
            },
        },
    ]
    if apply_enabled:
        specs.append(
            {
                "name": APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL,
                "description": (
                    "Install one exact proposal already shown and selected by the user "
                    "as an unsaved editor draft. This never saves the layout."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "proposal_id": identifier,
                        "proposal_revision": revision,
                    },
                    "required": ["proposal_id", "proposal_revision"],
                    "additionalProperties": False,
                },
            }
        )
    return specs


def _entity_labels(layout: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for collection, kind, id_field in (
        ("placements", "placement", "placementId"),
        ("routes", "route", "routeId"),
        ("zones", "zone", "zoneId"),
    ):
        for item in layout.get(collection, []):
            if not isinstance(item, Mapping) or not item.get(id_field):
                continue
            labels = {str(item[id_field])}
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            for value in (
                item.get("label"),
                item.get("name"),
                metadata.get("instanceLabel"),
                metadata.get("displayName"),
            ):
                if isinstance(value, str) and value.strip():
                    labels.add(value.strip())
            aliases = metadata.get("semanticAliases")
            if isinstance(aliases, list):
                labels.update(
                    value.strip()
                    for value in aliases
                    if isinstance(value, str) and value.strip()
                )
            for label in labels:
                rows.append((kind, str(item[id_field]), label))
    return rows


def _resolve_entity(
    layout: Mapping[str, Any],
    label: str,
    *,
    allowed_kinds: Iterable[str],
) -> dict[str, str]:
    allowed = set(allowed_kinds)
    needle = _normalized(label).casefold()
    exact = {
        (kind, entity_id)
        for kind, entity_id, candidate in _entity_labels(layout)
        if kind in allowed and _normalized(candidate).casefold() == needle
    }
    if len(exact) != 1:
        code = (
            "facility_design_referent_missing"
            if not exact
            else "facility_design_referent_ambiguous"
        )
        _fail(
            code,
            "The Facility design referent did not resolve exactly once.",
            phrase=label,
            candidates=[
                {"entityKind": kind, "entityId": entity_id}
                for kind, entity_id in sorted(exact)
            ],
        )
    kind, entity_id = next(iter(exact))
    return {"entityKind": kind, "entityId": entity_id}


def _mentioned_entity_labels(
    layout: Mapping[str, Any],
    text: str,
    *,
    allowed_kinds: Iterable[str],
) -> list[str]:
    """Return exact layout labels explicitly present in one text span."""

    allowed = set(allowed_kinds)
    normalized_text = _normalized(text)
    matches: dict[tuple[str, str], tuple[int, int, str]] = {}
    for kind, entity_id, raw_label in _entity_labels(layout):
        if kind not in allowed:
            continue
        label = _normalized(raw_label)
        if not label:
            continue
        match = re.search(
            rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])",
            normalized_text,
            re.IGNORECASE,
        )
        if match is None:
            continue
        candidate = (match.start(), -len(label), label)
        key = (kind, entity_id)
        if key not in matches or candidate < matches[key]:
            matches[key] = candidate
    return [
        candidate[2]
        for _key, candidate in sorted(
            matches.items(),
            key=lambda item: (item[1][0], item[1][1], item[0]),
        )
    ]


def _labels_cover_target_span(
    target_span: str,
    labels: Sequence[str],
) -> bool:
    """Return true only when exact labels account for the whole target list."""

    residual = _normalized(target_span)
    if not residual or not labels:
        return False
    for label in sorted(labels, key=len, reverse=True):
        residual = re.sub(
            rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])",
            " ",
            residual,
            count=1,
            flags=re.IGNORECASE,
        )
    residual = re.sub(
        r"\b(?:and|both|the|current|existing|also|too)\b",
        " ",
        residual,
        flags=re.IGNORECASE,
    )
    return not re.sub(r"[\s,;]+", "", residual)


def _clauses_cover_text(
    text: str,
    clauses: Sequence[re.Match[str]],
) -> bool:
    if not clauses:
        return False
    cursor = 0
    residual_parts = []
    for clause in clauses:
        residual_parts.append(text[cursor:clause.start()])
        cursor = clause.end()
    residual_parts.append(text[cursor:])
    residual = " ".join(residual_parts)
    residual = re.sub(
        r"\b(?:and|also|too|please|now)\b",
        " ",
        residual,
        flags=re.IGNORECASE,
    )
    return not re.sub(r"[\s,;:.!?]+", "", residual)


def _exact_entity_labels_in_span(
    layout: Mapping[str, Any],
    target_span: str,
    *,
    allowed_kinds: Iterable[str],
) -> list[str] | None:
    labels = _mentioned_entity_labels(
        layout,
        target_span,
        allowed_kinds=allowed_kinds,
    )
    if not _labels_cover_target_span(target_span, labels):
        return None
    return labels


def _exact_active_referents_in_span(
    target_span: str,
    *,
    active_design: Mapping[str, Any] | None,
) -> list[str] | None:
    referents = (
        active_design.get("referents", [])
        if isinstance(active_design, Mapping)
        else []
    )
    candidates = []
    for referent in referents:
        if not isinstance(referent, Mapping):
            continue
        if str(referent.get("status") or "active") != "active":
            continue
        phrase = _normalized(referent.get("phrase"))
        if phrase:
            candidates.append(phrase)
    mentioned = []
    folded = _normalized(target_span)
    for phrase in candidates:
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])",
            folded,
            re.IGNORECASE,
        ):
            mentioned.append(phrase)
    mentioned.sort(
        key=lambda phrase: re.search(
            rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])",
            folded,
            re.IGNORECASE,
        ).start()
    )
    if not _labels_cover_target_span(target_span, mentioned):
        return None
    return mentioned


def _metric_id_for_exact_phrase(value: str) -> str | None:
    phrase = _normalized(value)
    matches: list[tuple[int, int, str]] = []
    residual = phrase
    for pattern, metric_id in _METRIC_PATTERNS:
        match = pattern.search(phrase)
        if match is None:
            continue
        matches.append((match.start(), match.end(), metric_id))
        residual = pattern.sub(" ", residual)
    metric_ids = {item[2] for item in matches}
    residual = re.sub(
        r"\b(?:the|a|an|please|now|instead)\b",
        " ",
        residual,
        flags=re.IGNORECASE,
    )
    if len(metric_ids) != 1 or re.sub(r"[\s,;]+", "", residual):
        return None
    return next(iter(metric_ids))


def _exact_preference_order(text: str) -> list[str] | None:
    rather_than = re.search(
        r"\brather\s+than\s+(?P<secondary>[^,.!?]+),?\s*"
        r"(?:please\s+|now\s+)?prefer\s+(?P<primary>[^.!?]+)",
        text,
        re.IGNORECASE,
    )
    if rather_than is not None:
        primary = _metric_id_for_exact_phrase(rather_than.group("primary"))
        secondary = _metric_id_for_exact_phrase(
            rather_than.group("secondary")
        )
        if primary and secondary and primary != secondary:
            return [primary, secondary]
        return None

    prefer_over = re.search(
        r"\bprefer\s+(?P<primary>[^.!?]+?)\s+over\s+"
        r"(?P<secondary>[^.!?]+)",
        text,
        re.IGNORECASE,
    )
    if prefer_over is not None:
        primary = _metric_id_for_exact_phrase(prefer_over.group("primary"))
        secondary = _metric_id_for_exact_phrase(prefer_over.group("secondary"))
        if primary and secondary and primary != secondary:
            return [primary, secondary]
        return None

    single = re.search(
        r"\bprefer\s+(?P<primary>[^.!?]+)",
        text,
        re.IGNORECASE,
    )
    if single is None:
        return None
    metric_id = _metric_id_for_exact_phrase(single.group("primary"))
    return [metric_id] if metric_id else None


def recover_facility_design_create_intent(
    message: str,
    *,
    layout: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover an initial brief only from explicit, exact user-owned language."""

    if not isinstance(layout, Mapping):
        return None
    if classify_facility_design_turn(message) != {
        "kind": "design",
        "action": "create_and_preview",
    }:
        return None
    text = _normalized(message)
    if _has_unresolved_fast_path_qualifier(text):
        return None
    transfer = re.search(
        r"\bfrom\b(?P<source>[^.!?]{1,240}?)\bto\b"
        r"(?P<target>[^.!?]{1,240})",
        text,
        re.IGNORECASE,
    )
    if transfer is None:
        return None
    source_labels = _exact_entity_labels_in_span(
        layout,
        transfer.group("source"),
        allowed_kinds={"placement"},
    )
    target_labels = _exact_entity_labels_in_span(
        layout,
        transfer.group("target"),
        allowed_kinds={"placement"},
    )
    if (
        source_labels is None
        or target_labels is None
        or len(source_labels) != 1
        or len(target_labels) != 1
    ):
        return None

    locked_labels: list[str] = []
    movable_labels: list[str] = []
    mutable_route_labels: list[str] = []
    for sentence_match in re.finditer(r"[^.!?]+", text):
        sentence = _normalized(sentence_match.group(0))
        if _LOCK.search(sentence):
            lock_clauses = list(_LOCK_TARGET_CLAUSE.finditer(sentence))
            if not _clauses_cover_text(sentence, lock_clauses):
                return None
            for clause in lock_clauses:
                labels = _exact_entity_labels_in_span(
                    layout,
                    clause.group("targets"),
                    allowed_kinds={"placement", "route"},
                )
                if labels is None:
                    return None
                locked_labels.extend(labels)
        permission_matches = list(_CHANGE_PERMISSION.finditer(sentence))
        if permission_matches:
            permission_clauses = list(
                _CHANGE_PERMISSION_CLAUSE.finditer(sentence)
            )
            if (
                len(permission_clauses) != len(permission_matches)
                or not _clauses_cover_text(sentence, permission_clauses)
            ):
                return None
            for clause in permission_clauses:
                verb = clause.group("verb").casefold()
                placement_change = verb in {
                    "move",
                    "relocate",
                    "reposition",
                }
                labels = _exact_entity_labels_in_span(
                    layout,
                    clause.group("targets"),
                    allowed_kinds=(
                        {"placement"} if placement_change else {"route"}
                    ),
                )
                if labels is None:
                    return None
                if placement_change:
                    movable_labels.extend(labels)
                else:
                    mutable_route_labels.extend(labels)
        elif _CHANGE_DIRECTIVE.search(sentence) and not _LOCK.search(sentence):
            return None

    trips = re.search(
        r"\b(?P<count>[1-9][0-9]*)\s+(?:loaded\s+)?"
        r"(?:trips?|transfers?)\s+(?:per|during|each)\s+"
        r"(?P<shift>[A-Za-z][A-Za-z0-9 _-]{0,60}?)"
        r"(?=[.,;!?]|$)",
        text,
        re.IGNORECASE,
    )
    if trips is None:
        return None

    def unique(values: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        result = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    try:
        return canonicalize_facility_design_intent(
            {
                "schema_version": FACILITY_DESIGN_INTENT_SCHEMA_VERSION,
                "operation": "create_material_travel_brief",
                "source_label": source_labels[0],
                "target_label": target_labels[0],
                "loaded_trips_per_shift": int(trips.group("count")),
                "shift_name": _normalized(trips.group("shift")),
                "locked_entity_labels": unique(locked_labels),
                "movable_placement_labels": unique(movable_labels),
                "mutable_route_labels": unique(mutable_route_labels),
            }
        )
    except FacilityDesignIntentError:
        return None


def _ref(kind: str, entity_id: str, revision: str) -> dict[str, str]:
    return {
        "entityKind": kind,
        "entityId": entity_id,
        "sourceRevision": revision,
    }


def _record_id(prefix: str, value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:80]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{slug or 'item'}-{digest}"


def _polygon_area(boundary: Sequence[Mapping[str, Any]]) -> float:
    total = 0.0
    for index, point in enumerate(boundary):
        nxt = boundary[(index + 1) % len(boundary)]
        total += float(point["x"]) * float(nxt["z"])
        total -= float(nxt["x"]) * float(point["z"])
    return abs(total) / 2.0


def _point_inside(x: float, z: float, boundary: Sequence[Mapping[str, Any]]) -> bool:
    inside = False
    previous = boundary[-1]
    for current in boundary:
        x1, z1 = float(previous["x"]), float(previous["z"])
        x2, z2 = float(current["x"]), float(current["z"])
        if (z1 > z) != (z2 > z):
            crossing = (x2 - x1) * (z - z1) / (z2 - z1) + x1
            if x <= crossing:
                inside = not inside
        previous = current
    return inside


def _containing_area_ref(
    layout: Mapping[str, Any], placement_id: str, revision: str
) -> dict[str, str] | None:
    placement = next(
        (item for item in layout.get("placements", []) if item.get("placementId") == placement_id),
        None,
    )
    if not isinstance(placement, Mapping):
        return None
    position = placement.get("transform", {}).get("position", {})
    try:
        x, z = float(position["x"]), float(position["z"])
    except (KeyError, TypeError, ValueError):
        return None
    matches = []
    for zone in layout.get("zones", []):
        boundary = zone.get("boundary") if isinstance(zone, Mapping) else None
        if (
            isinstance(boundary, list)
            and len(boundary) >= 3
            and _point_inside(x, z, boundary)
        ):
            matches.append((_polygon_area(boundary), str(zone.get("zoneId") or "")))
    matches = [item for item in matches if item[1]]
    if not matches:
        return None
    _area, zone_id = sorted(matches)[0]
    return _ref("zone", zone_id, revision)


def compile_facility_design_brief_body(
    *,
    intent: Mapping[str, Any],
    design_base: Mapping[str, Any],
    source_turn_ref: str,
) -> dict[str, Any]:
    """Resolve one initial semantic intent against exact base identities."""

    request = canonicalize_facility_design_intent(intent)
    if request["operation"] != "create_material_travel_brief":
        _fail("facility_design_intent_invalid", "Initial brief intent must create the material-travel objective.")
    base = validate_facility_design_base(design_base)
    layout = base["document"]
    revision = base["layoutRevision"]
    turn = _turn_identifier(source_turn_ref)
    source = _resolve_entity(layout, request["source_label"], allowed_kinds={"placement"})
    target = _resolve_entity(layout, request["target_label"], allowed_kinds={"placement"})
    locked = [
        _resolve_entity(layout, label, allowed_kinds={"placement", "route"})
        for label in request["locked_entity_labels"]
    ]
    movable = [
        _resolve_entity(layout, label, allowed_kinds={"placement"})
        for label in request["movable_placement_labels"]
    ]
    routes = [
        _resolve_entity(layout, label, allowed_kinds={"route"})
        for label in request["mutable_route_labels"]
    ]
    selected_ids = {
        source["entityId"],
        target["entityId"],
        *(item["entityId"] for item in locked),
        *(item["entityId"] for item in movable),
        *(item["entityId"] for item in routes),
    }
    bindings = [
        item
        for item in layout.get("processBindings", [])
        if isinstance(item, Mapping)
        and (
            selected_ids.intersection(str(value) for value in item.get("placementIds", []))
            or selected_ids.intersection(str(value) for value in item.get("routeIds", []))
        )
    ]
    if not bindings:
        _fail(
            "facility_design_process_binding_unavailable",
            "The selected transfer has no persisted process binding.",
        )
    binding_ids = sorted(str(item["processBindingId"]) for item in bindings)
    process_revisions = sorted({str(item.get("processMapRevision") or "") for item in bindings})
    if len(process_revisions) != 1 or not _HASH_RE.fullmatch(process_revisions[0]):
        _fail(
            "facility_design_process_binding_stale",
            "Selected process bindings do not share one exact Process Map revision.",
        )
    binding_refs = [_ref("process_binding", item, revision) for item in binding_ids]
    all_entities = [source, target, *locked, *movable, *routes]
    unique_entities = {
        (item["entityKind"], item["entityId"]): item for item in all_entities
    }
    hard_constraints = []
    for entity in sorted(locked, key=lambda item: (item["entityKind"], item["entityId"])):
        kind = (
            "preserve_route_geometry"
            if entity["entityKind"] == "route"
            else "preserve_entity_geometry"
        )
        hard_constraints.append(
            {
                "constraintId": _record_id("constraint-lock", entity["entityId"]),
                "constraintKind": kind,
                "targetRefs": [_ref(entity["entityKind"], entity["entityId"], revision)],
                "predicateVersion": FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
                "authority": "user_authored",
                "evidenceRefs": [],
                "status": "active",
                "sourceTurnRef": turn,
                "supersededBy": None,
            }
        )
    hard_constraints.append(
        {
            "constraintId": "constraint-preserve-process-bindings",
            "constraintKind": "preserve_process_binding",
            "targetRefs": binding_refs,
            "predicateVersion": FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
            "authority": "user_authored",
            "evidenceRefs": [],
            "status": "active",
            "sourceTurnRef": turn,
            "supersededBy": None,
        }
    )
    permitted_changes = []
    for entity in sorted(movable, key=lambda item: item["entityId"]):
        permitted_changes.append(
            {
                "changeId": _record_id("change", entity["entityId"]),
                "targetRefs": [_ref("placement", entity["entityId"], revision)],
                "operationKinds": [
                    "move_placement_within_area",
                    "move_route_bound_endpoint",
                ],
                "containingAreaRef": _containing_area_ref(
                    layout, entity["entityId"], revision
                ),
                "status": "active",
                "sourceTurnRef": turn,
                "withdrawnBy": None,
            }
        )
    for entity in sorted(routes, key=lambda item: item["entityId"]):
        permitted_changes.append(
            {
                "changeId": _record_id("change", entity["entityId"]),
                "targetRefs": [_ref("route", entity["entityId"], revision)],
                "operationKinds": ["edit_material_route"],
                "containingAreaRef": None,
                "status": "active",
                "sourceTurnRef": turn,
                "withdrawnBy": None,
            }
        )
    referents = []
    seen_phrases: set[str] = set()
    for phrase, entity in [
        (request["source_label"], source),
        (request["target_label"], target),
        *zip(request["locked_entity_labels"], locked),
        *zip(request["movable_placement_labels"], movable),
        *zip(request["mutable_route_labels"], routes),
    ]:
        key = phrase.casefold()
        if key in seen_phrases:
            continue
        seen_phrases.add(key)
        referents.append(
            {
                "referentId": _record_id("referent", phrase),
                "phrase": phrase,
                "targetRefs": [_ref(entity["entityKind"], entity["entityId"], revision)],
                "capturedLayoutRevision": revision,
                "sourceTurnRef": turn,
                "status": "active",
            }
        )
    shift_id = _record_id("shift", request["shift_name"])
    evidence_id = f"evidence-loaded-trips-{request['loaded_trips_per_shift']}-{shift_id}"
    policy_revision = str(layout.get("policySetRef", {}).get("policySetRevision") or "")
    if not _HASH_RE.fullmatch(policy_revision):
        _fail("facility_design_policy_evidence_unavailable", "The base layout has no exact policy revision.")
    target_refs = [
        _ref(source["entityKind"], source["entityId"], revision),
        _ref(target["entityKind"], target["entityId"], revision),
        *[_ref("route", item["entityId"], revision) for item in routes],
    ]
    scope_refs = [
        _ref(kind, entity_id, revision)
        for kind, entity_id in sorted(unique_entities)
    ] + binding_refs
    return {
        "status": "active",
        "tenantId": base["tenantId"],
        "siteId": base["siteId"],
        "workspaceId": base["workspaceId"],
        "layoutId": base["layoutId"],
        "baseStateRef": facility_design_base_ref(base),
        "objective": {
            "objectiveId": "objective-reduce-loaded-material-travel",
            "objectiveKind": "reduce_loaded_material_travel_v1",
            "targetRefs": target_refs,
            "processBindingIds": binding_ids,
            "requestedMetricIds": sorted(FACILITY_DESIGN_METRIC_IDS),
            "minimumImprovement": None,
            "evidenceRefs": [evidence_id],
        },
        "scopeRefs": scope_refs,
        "hardConstraints": hard_constraints,
        "preferences": [],
        "permittedChanges": permitted_changes,
        "assumptions": [],
        "unknowns": [],
        "referents": referents,
        "decisionRefs": [
            f"decision-loaded-trips-{request['loaded_trips_per_shift']}-{shift_id}"
        ],
        "revisionVector": {
            "layout": revision,
            "processMap": process_revisions[0],
            "policy": policy_revision,
        },
    }


def compile_facility_design_brief_patch(
    *,
    intent: Mapping[str, Any],
    current_brief: Mapping[str, Any],
    design_base: Mapping[str, Any],
    source_turn_ref: str,
) -> dict[str, Any]:
    """Resolve one coordinate-free correction into the closed brief patch."""

    request = canonicalize_facility_design_intent(intent)
    brief = validate_facility_design_brief(current_brief)
    base = validate_facility_design_base(design_base)
    if brief["semanticBody"]["baseStateRef"] != facility_design_base_ref(base):
        _fail("facility_design_base_mismatch", "Brief correction is bound to another base.")
    expected = request.get("expected_brief_revision")
    if expected is not None and expected != brief["briefRevision"]:
        _fail(
            "facility_design_brief_revision_conflict",
            "The Facility design brief changed before this correction.",
            expectedBriefRevision=expected,
            currentBriefRevision=brief["briefRevision"],
        )
    turn = _turn_identifier(source_turn_ref)
    operations: list[dict[str, Any]] = []
    body = brief["semanticBody"]
    if request["operation"] == "add_geometry_locks":
        resolved = [
            _resolve_entity(
                base["document"], label, allowed_kinds={"placement", "route"}
            )
            for label in request["target_labels"]
        ]
        active_locked = {
            (ref["entityKind"], ref["entityId"])
            for constraint in body["hardConstraints"]
            if constraint["status"] == "active"
            and constraint["constraintKind"]
            in {"preserve_entity_geometry", "preserve_route_geometry"}
            for ref in constraint["targetRefs"]
        }
        for entity in resolved:
            key = (entity["entityKind"], entity["entityId"])
            if key in active_locked:
                continue
            constraint_id = _record_id(
                f"constraint-lock-{turn[:24]}", entity["entityId"]
            )
            operations.append(
                {
                    "action": "add",
                    "collection": "hardConstraints",
                    "recordId": None,
                    "record": {
                        "constraintId": constraint_id,
                        "constraintKind": (
                            "preserve_route_geometry"
                            if entity["entityKind"] == "route"
                            else "preserve_entity_geometry"
                        ),
                        "targetRefs": [
                            _ref(
                                entity["entityKind"],
                                entity["entityId"],
                                base["layoutRevision"],
                            )
                        ],
                        "predicateVersion": FACILITY_DESIGN_CONSTRAINT_PREDICATE_VERSION,
                        "authority": "user_authored",
                        "evidenceRefs": [],
                        "status": "active",
                        "sourceTurnRef": turn,
                        "supersededBy": None,
                    },
                }
            )
    elif request["operation"] == "set_preference_order":
        active = {
            item["metricId"]: item
            for item in body["preferences"]
            if item["status"] == "active"
        }
        for priority, metric_id in enumerate(
            request["preference_metric_ids"], start=1
        ):
            current = active.get(metric_id)
            if current is None:
                operations.append(
                    {
                        "action": "add",
                        "collection": "preferences",
                        "recordId": None,
                        "record": {
                            "preferenceId": _record_id("preference", metric_id),
                            "metricId": metric_id,
                            "priority": priority,
                            "status": "active",
                            "sourceTurnRef": turn,
                        },
                    }
                )
            elif current["priority"] != priority:
                operations.append(
                    {
                        "action": "reorder",
                        "collection": "preferences",
                        "recordId": current["preferenceId"],
                        "record": {"priority": priority},
                    }
                )
    else:
        _fail(
            "facility_design_intent_invalid",
            "An existing brief cannot be replaced by an initial objective intent.",
        )
    if not operations:
        _fail(
            "facility_design_brief_no_change",
            "The requested design-brief correction is already active.",
        )
    return {
        "schemaVersion": FACILITY_DESIGN_BRIEF_SCHEMA_VERSION,
        "expectedBriefRevision": brief["briefRevision"],
        "operations": operations,
    }


__all__ = [
    "APPLY_FACILITY_DESIGN_PROPOSAL_DRAFT_TOOL",
    "FACILITY_DESIGN_INTENT_SCHEMA_VERSION",
    "FACILITY_DESIGN_TOOLS",
    "INSPECT_FACILITY_DESIGN_BRIEF_TOOL",
    "RUN_FACILITY_DESIGN_PREVIEW_TOOL",
    "UPDATE_FACILITY_DESIGN_BRIEF_TOOL",
    "FacilityDesignIntentError",
    "canonicalize_facility_design_intent",
    "classify_facility_design_turn",
    "compile_facility_design_brief_body",
    "compile_facility_design_brief_patch",
    "facility_design_agent_tool_specs",
    "facility_design_allowed_tools",
    "recover_facility_design_create_intent",
    "recover_facility_design_update_intent",
]
