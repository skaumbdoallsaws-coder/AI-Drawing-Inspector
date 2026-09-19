"""G5 manufacturing-cell feasibility and deterministic draft composition."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re
from typing import Any, Mapping, Sequence

from .canonical import (
    canonicalize_layout,
    layout_revision,
    trusted_canonical_layout_revision,
)
from .knowledge_foundation import (
    FacilityKnowledgeContractError,
    canonical_facility_knowledge_bytes,
)
from .operations import (
    apply_facility_layout_operations,
    apply_prevalidated_facility_layout_operations,
)
from .semantic_model import (
    CELL_FEASIBILITY_STRATEGIES,
    analyze_facility_cell_alternatives,
)
from .spatial import placement_clearance_records, placement_spatial_records


G5_CELL_COMPOSITION_SCOPE = "seed_cells"
G5_FACILITY_CELL_COMPOSITION_TOOL = "generate_facility_cell_draft"
G5_CELL_OBJECTIVES = frozenset(
    {
        "shortest_travel",
        "smallest_envelope",
        "minimum_movement",
        "maximum_expansion_reserve",
    }
)

_CELL_INTENT = re.compile(
    r"\b(?:manufacturing\s+cell|workcell|cell\s+layout|cell\s+arrangement|"
    r"(?:machining|assembly|inspection|production)\s+cell|arrange|reflow|"
    r"(?:this|the)\s+cell|re[-\s]?layout|organize|compose|compare|convert)\b",
    re.IGNORECASE,
)
_EXPLICIT_CELL = re.compile(
    r"\b(?:manufacturing\s+cell|workcell|cell\s+layout|cell\s+arrangement|"
    r"(?:machining|assembly|inspection|production)\s+cell|"
    r"(?:this|the)\s+cell)\b",
    re.IGNORECASE,
)
_COMPLETE_FACILITY = re.compile(
    r"\b(?:facility|plant(?:\s+floor)?|building)\b",
    re.IGNORECASE,
)
_DIMENSION_PAIR = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*(?:m|meters?|metres?|mm|ft|feet|inches?))?"
    r"\s*(?:by|x)\s*\d+(?:\.\d+)?",
    re.IGNORECASE,
)
_OTHER_GATE_ACTION = re.compile(
    r"\b(?:divide|split|subdivide|place|stage|install)\b",
    re.IGNORECASE,
)
_BUILD_INTENT = re.compile(
    r"\b(?:arrange|reflow|re[-\s]?layout|organize|compose|create|design|"
    r"draft|apply|use|convert)\b",
    re.IGNORECASE,
)
_COMPARE_INTENT = re.compile(
    r"\b(?:compare|evaluate|assess|show\s+(?:me\s+)?(?:the\s+)?options?)\b",
    re.IGNORECASE,
)
_COORDINATE = re.compile(
    r"(?:\b(?:x|z)\s*=\s*-?\d|\bcoordinates?\b|\bworld\s+point\b|"
    r"\b-?\d+(?:\.\d+)?\s*(?:degrees?|deg)\b)",
    re.IGNORECASE,
)
_UNSUPPORTED_CLAIM = re.compile(
    r"\b(?:safe|safety|compliant|compliance|osha|fire\s+code|building\s+code|"
    r"regulatory|throughput|capacity|ergonomic|ergonomics|optimal)\b",
    re.IGNORECASE,
)
_SPACING = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>m|meter|meters|metre|metres|mm|millimeter|millimeters|"
    r"millimetre|millimetres|ft|feet|foot|in|inch|inches)\b"
    r"[^.!?]{0,24}\b(?:gap|spacing|separation)\b|"
    r"\b(?:gap|spacing|separation)\b[^.!?]{0,24}"
    r"(?P<value_after>\d+(?:\.\d+)?)\s*"
    r"(?P<unit_after>m|meter|meters|metre|metres|mm|millimeter|millimeters|"
    r"millimetre|millimetres|ft|feet|foot|in|inch|inches)\b",
    re.IGNORECASE,
)
_PROCESS_SEQUENCE = re.compile(
    r"\bprocess\s+(?:order|flow|sequence)\s*(?:is|:|=)\s*(?P<value>[^.!?]+)",
    re.IGNORECASE,
)

_STRATEGY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("line", re.compile(r"\b(?:straight\s+line|i[-\s]?line|line)\b", re.I)),
    ("l", re.compile(r"\b(?:l[-\s]?shaped|l\s+layout|L)\b")),
    ("u", re.compile(r"\b(?:u[-\s]?shaped|u\s+layout|U)\b")),
    ("grid", re.compile(r"\bgrid\b", re.I)),
    ("parallel", re.compile(r"\bparallel(?:\s+rows?)?\b", re.I)),
    ("serpentine", re.compile(r"\bserpentine\b", re.I)),
    ("loop", re.compile(r"\b(?:closed\s+)?loop\b", re.I)),
    ("spine", re.compile(r"\bspine(?:\s+and\s+branch)?\b", re.I)),
    ("herringbone", re.compile(r"\bherringbone\b", re.I)),
    ("cluster", re.compile(r"\bcluster\b", re.I)),
)


class FacilityCellCompositionError(FacilityKnowledgeContractError):
    """A G5 cell request is ambiguous, unsupported, or infeasible."""


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_revision(value)[:24]}"


def _collection_revision(layout: Mapping[str, Any], field: str) -> str:
    return _revision(layout.get(field, []))


def _zone_index(layout: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("zoneId") or ""): deepcopy(dict(item))
        for item in layout.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }


def _resolve_zone(layout: Mapping[str, Any], value: str) -> dict[str, Any]:
    requested = str(value or "").strip()
    if not requested:
        raise FacilityCellCompositionError(
            "facility_cell_target_required",
            "Name one existing department or child area for the cell.",
        )
    exact_id = [
        item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping)
        and str(item.get("zoneId") or "") == requested
    ]
    if len(exact_id) == 1:
        return deepcopy(dict(exact_id[0]))
    matches = [
        item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping)
        and str(item.get("label") or "").strip().casefold()
        == requested.casefold()
    ]
    if len(matches) != 1:
        raise FacilityCellCompositionError(
            "facility_cell_target_ambiguous" if matches else "facility_cell_target_unknown",
            (
                f"Target area '{requested}' is ambiguous."
                if matches
                else f"Target area '{requested}' does not exist."
            ),
        )
    return deepcopy(dict(matches[0]))


def _catalog_index(
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in asset_catalog:
        if not isinstance(raw, Mapping):
            continue
        nested = raw.get("definition")
        definition = (
            deepcopy(dict(nested))
            if isinstance(nested, Mapping)
            else deepcopy(dict(raw))
        )
        asset_id = str(raw.get("assetId") or definition.get("assetId") or "")
        revision = str(
            raw.get("assetDefinitionRevision")
            or definition.get("assetDefinitionRevision")
            or ""
        )
        if not asset_id or not revision:
            continue
        definition["assetId"] = asset_id
        definition["assetDefinitionRevision"] = revision
        definition.setdefault(
            "displayName",
            str(raw.get("displayName") or definition.get("displayName") or asset_id),
        )
        result[(asset_id, revision)] = definition
    return result


def _record_payload(record: Any) -> dict[str, Any]:
    return {
        "recordId": str(record.record_id),
        "polygon": [
            {"x": float(point[0]), "z": float(point[1])}
            for point in record.polygon
        ],
        "minimumY": float(record.minimum_y),
        "maximumY": float(record.maximum_y),
        "authoritative": bool(record.authoritative),
    }


def _analysis_layout(
    layout: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    evidence_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = canonicalize_layout(deepcopy(dict(layout)))
    assets = _catalog_index(asset_catalog)
    result["assets"] = [deepcopy(item) for item in assets.values()]
    for placement in result.get("placements", []):
        if not isinstance(placement, dict):
            continue
        key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        asset = assets.get(key)
        if asset is None:
            continue
        try:
            physical = placement_spatial_records(placement, asset)
            clearances = placement_clearance_records(
                placement,
                asset,
                evidence_authority=evidence_authority,
            )
        except (TypeError, ValueError):
            continue
        placement["physicalGeometry"] = [
            _record_payload(item) for item in physical
        ]
        placement["clearanceGeometry"] = [
            _record_payload(item) for item in clearances
        ]
        placement["clearanceRecordCount"] = len(clearances)
    return result


def _member_placements(
    layout: Mapping[str, Any], target_zone_id: str
) -> list[dict[str, Any]]:
    members = []
    for raw in layout.get("placements", []):
        if not isinstance(raw, Mapping) or not raw.get("placementId"):
            continue
        metadata = raw.get("metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        zone_ids = {
            str(item) for item in raw.get("zoneIds", [])
        } if isinstance(raw.get("zoneIds"), list) else set()
        if (
            str(metadata.get("targetZoneId") or "") == target_zone_id
            or target_zone_id in zone_ids
        ):
            members.append(deepcopy(dict(raw)))
    return sorted(members, key=lambda item: str(item.get("placementId") or ""))


def _closed_request(request: Mapping[str, Any]) -> None:
    allowed = {
        "request_id",
        "target_area",
        "candidate_strategies",
        "selected_strategy",
        "objective",
        "preferred_gap_meters",
        "invert_u",
        "process_sequence_placement_ids",
        "preserve_departments",
        "preserve_routes",
        "preserve_markings",
        "preserve_locked_and_manual",
        "execution_mode",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise FacilityCellCompositionError(
            "facility_cell_model_geometry_refused",
            "G5 accepts cell intent, strategy, objective, and exact spacing only.",
            details={"fields": unknown},
        )


def normalize_cell_composition_request(
    request: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise FacilityCellCompositionError(
            "facility_cell_request_invalid", "G5 cell intent must be an object."
        )
    _closed_request(request)
    for field in (
        "preserve_departments",
        "preserve_routes",
        "preserve_markings",
        "preserve_locked_and_manual",
    ):
        if request.get(field) is not True:
            raise FacilityCellCompositionError(
                "facility_cell_preservation_required",
                "G5 must preserve departments, circulation, markings, and fixed placements.",
                details={"field": field},
            )
    if str(request.get("execution_mode") or "") != "authorized_draft_run":
        raise FacilityCellCompositionError(
            "facility_cell_execution_mode_invalid",
            "G5 requires authorized_draft_run mode.",
        )
    target = _resolve_zone(layout, str(request.get("target_area") or ""))
    members = _member_placements(layout, str(target.get("zoneId") or ""))
    if len(members) < 2:
        raise FacilityCellCompositionError(
            "facility_cell_resources_required",
            f"'{target.get('label')}' needs at least two exact placed resources before cell comparison.",
            details={"memberPlacementCount": len(members)},
        )
    fixed = [
        str(item.get("placementId") or "")
        for item in members
        if item.get("positionMode") in {"locked", "manual"}
    ]
    if fixed:
        raise FacilityCellCompositionError(
            "facility_cell_fixed_placements_require_bounded_reflow",
            "The target cell contains locked or manually positioned resources. G5 will not move or silently ignore them.",
            details={"placementIds": fixed},
        )
    raw_strategies = request.get("candidate_strategies")
    if not isinstance(raw_strategies, list) or not raw_strategies:
        raise FacilityCellCompositionError(
            "facility_cell_strategies_required",
            "Choose one or more registered cell strategies to compare.",
        )
    strategies = []
    for raw in raw_strategies:
        strategy = str(raw or "").strip().lower()
        if strategy not in CELL_FEASIBILITY_STRATEGIES:
            raise FacilityCellCompositionError(
                "facility_cell_strategy_invalid",
                "Cell strategies must come from the registered strategy set.",
                details={"strategy": strategy},
            )
        if strategy not in strategies:
            strategies.append(strategy)
    selected = request.get("selected_strategy")
    selected = str(selected).strip().lower() if selected is not None else None
    if selected in {"", "best"}:
        selected = None
    if selected is not None and selected not in strategies:
        raise FacilityCellCompositionError(
            "facility_cell_selected_strategy_not_compared",
            "The selected strategy must be included in candidate_strategies.",
        )
    objective = str(request.get("objective") or "").strip().lower()
    if objective not in G5_CELL_OBJECTIVES:
        raise FacilityCellCompositionError(
            "facility_cell_objective_required",
            "Choose shortest_travel, smallest_envelope, minimum_movement, or maximum_expansion_reserve.",
        )
    raw_gap = request.get("preferred_gap_meters")
    gap_assumption = None
    if raw_gap is None:
        gap = 0.0
        gap_assumption = "no_preferred_gap_supplied_physical_non_overlap_only"
    else:
        if isinstance(raw_gap, bool):
            raise FacilityCellCompositionError(
                "facility_cell_gap_invalid", "preferred_gap_meters must be numeric."
            )
        try:
            gap = float(raw_gap)
        except (TypeError, ValueError) as exc:
            raise FacilityCellCompositionError(
                "facility_cell_gap_invalid", "preferred_gap_meters must be numeric."
            ) from exc
        if not math.isfinite(gap) or gap < 0 or gap > 20:
            raise FacilityCellCompositionError(
                "facility_cell_gap_invalid",
                "preferred_gap_meters must be between 0 and 20.",
            )
    member_ids = [str(item.get("placementId") or "") for item in members]
    sequence = request.get("process_sequence_placement_ids")
    if sequence is None:
        sequence_ids: list[str] = []
    elif not isinstance(sequence, list):
        raise FacilityCellCompositionError(
            "facility_cell_process_sequence_invalid",
            "process_sequence_placement_ids must be an ordered array.",
        )
    else:
        sequence_ids = [str(item or "").strip() for item in sequence]
        if sequence_ids and (
            len(set(sequence_ids)) != len(sequence_ids)
            or not set(sequence_ids) <= set(member_ids)
        ):
            raise FacilityCellCompositionError(
                "facility_cell_process_sequence_incomplete",
                "An authored process sequence must contain unique placements from the target cell.",
                details={"memberPlacementIds": member_ids},
            )
    request_id = str(request.get("request_id") or "").strip() or _stable_id(
        "g5-request",
        {
            "targetZoneId": target.get("zoneId"),
            "strategies": strategies,
            "selected": selected,
            "objective": objective,
            "gap": gap,
            "invertU": request.get("invert_u") is True,
            "sequence": sequence_ids,
        },
    )
    assumptions = [gap_assumption] if gap_assumption else []
    return {
        "scope": G5_CELL_COMPOSITION_SCOPE,
        "requestId": request_id,
        "targetArea": str(target.get("label") or ""),
        "targetZoneId": str(target.get("zoneId") or ""),
        "candidateStrategies": strategies,
        "selectedStrategy": selected,
        "objective": objective,
        "preferredGapMeters": gap,
        "preferredGapAuthority": (
            "user_authored" if raw_gap is not None else "not_supplied"
        ),
        "invertU": request.get("invert_u") is True,
        "memberPlacementIds": member_ids,
        "processSequencePlacementIds": sequence_ids,
        "processSequenceAuthority": (
            "user_authored" if sequence_ids else "geometric_proxy"
        ),
        "assumptions": assumptions,
        "preserveDepartments": True,
        "preserveRoutes": True,
        "preserveMarkings": True,
        "preserveLockedAndManual": True,
        "executionMode": "authorized_draft_run",
    }


def cell_composition_tool_spec() -> dict[str, Any]:
    strategies = list(CELL_FEASIBILITY_STRATEGIES)
    return {
        "name": G5_FACILITY_CELL_COMPOSITION_TOOL,
        "description": (
            "Compare registered manufacturing-cell strategies and apply one "
            "deterministically validated arrangement to exact resources already "
            "placed in one named area. Supply no coordinates, transforms, angles, "
            "inferred clearances, safety conclusions, throughput claims, or approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_area": {"type": "string", "minLength": 1},
                "candidate_strategies": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": len(strategies),
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": strategies},
                },
                "selected_strategy": {
                    "type": ["string", "null"],
                    "enum": [*strategies, None],
                },
                "objective": {
                    "type": "string",
                    "enum": sorted(G5_CELL_OBJECTIVES),
                },
                "preferred_gap_meters": {
                    "type": ["number", "null"],
                    "minimum": 0,
                    "maximum": 20,
                },
                "invert_u": {"type": "boolean"},
                "process_sequence_placement_ids": {
                    "type": "array",
                    "maxItems": 500,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "preserve_departments": {"type": "boolean", "const": True},
                "preserve_routes": {"type": "boolean", "const": True},
                "preserve_markings": {"type": "boolean", "const": True},
                "preserve_locked_and_manual": {"type": "boolean", "const": True},
                "execution_mode": {
                    "type": "string",
                    "const": "authorized_draft_run",
                },
            },
            "required": [
                "target_area",
                "candidate_strategies",
                "selected_strategy",
                "objective",
                "preferred_gap_meters",
                "invert_u",
                "process_sequence_placement_ids",
                "preserve_departments",
                "preserve_routes",
                "preserve_markings",
                "preserve_locked_and_manual",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


def _target_from_message(message: str, layout: Mapping[str, Any]) -> str | None:
    matches = []
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping) or not zone.get("label"):
            continue
        label = str(zone["label"])
        for found in re.finditer(r"\b" + re.escape(label) + r"\b", message, re.I):
            matches.append((label, found.start(), len(label)))
    if not matches:
        if re.search(r"\b(?:it|this\s+cell|the\s+cell)\b", message, re.I):
            active = [
                str(zone.get("label") or "")
                for zone in layout.get("zones", [])
                if isinstance(zone, Mapping)
                and isinstance(zone.get("extensions"), Mapping)
                and isinstance(zone["extensions"].get("cellGroup"), Mapping)
                and zone.get("label")
            ]
            if len(active) == 1:
                return active[0]
        return None
    matches.sort(key=lambda item: (-item[2], item[1], item[0].casefold()))
    return matches[0][0]


def _strategies_from_message(message: str) -> list[str]:
    found = []
    for strategy, pattern in _STRATEGY_PATTERNS:
        if pattern.search(message) and strategy not in found:
            found.append(strategy)
    return [item for item in CELL_FEASIBILITY_STRATEGIES if item in found]


def _gap_from_message(message: str) -> float | None:
    match = _SPACING.search(message)
    if match is None:
        return None
    value = float(match.group("value") or match.group("value_after"))
    unit = str(match.group("unit") or match.group("unit_after")).casefold()
    if unit in {"mm", "millimeter", "millimeters", "millimetre", "millimetres"}:
        return value / 1000.0
    if unit in {"ft", "feet", "foot"}:
        return value * 0.3048
    if unit in {"in", "inch", "inches"}:
        return value * 0.0254
    return value


def _objective_from_message(message: str) -> str | None:
    if re.search(r"\b(?:shortest|least\s+travel|minimum\s+travel)\b", message, re.I):
        return "shortest_travel"
    if re.search(r"\b(?:smallest|most\s+compact|minimum\s+envelope)\b", message, re.I):
        return "smallest_envelope"
    if re.search(r"\b(?:least\s+movement|minimum\s+movement|move\s+the\s+least)\b", message, re.I):
        return "minimum_movement"
    if re.search(r"\b(?:most\s+expansion|maximum\s+reserve|largest\s+free\s+area)\b", message, re.I):
        return "maximum_expansion_reserve"
    return None


def _selected_strategy_from_message(
    message: str,
    strategies: Sequence[str],
    *,
    build: bool,
) -> str | None:
    if not build:
        return None
    if len(strategies) == 1:
        return str(strategies[0])
    command = re.search(
        r"\b(?:convert\b[^.!?]{0,80}\bto|"
        r"arrange\b[^.!?]{0,80}\bas)\b",
        message,
        re.IGNORECASE,
    )
    if command is None:
        return None
    tail = message[command.end():command.end() + 80]
    matches: list[tuple[int, str]] = []
    patterns = dict(_STRATEGY_PATTERNS)
    for strategy in strategies:
        found = patterns[str(strategy)].search(tail)
        if found is not None:
            matches.append((found.start(), str(strategy)))
    return min(matches)[1] if matches else None


def parse_cell_composition_turn(
    message: str,
    layout: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    if _CELL_INTENT.search(text) is None:
        return {"kind": "not_applicable"}
    if (
        _COMPLETE_FACILITY.search(text)
        and _DIMENSION_PAIR.search(text)
    ) or _OTHER_GATE_ACTION.search(text):
        return {"kind": "not_applicable"}
    strategy_mentions = _strategies_from_message(text)
    if _EXPLICIT_CELL.search(text) is None and not strategy_mentions:
        weak_target = _target_from_message(text, layout)
        if weak_target is None:
            return {"kind": "not_applicable"}
        try:
            weak_zone = _resolve_zone(layout, weak_target)
        except FacilityCellCompositionError:
            return {"kind": "not_applicable"}
        if len(
            _member_placements(
                layout,
                str(weak_zone.get("zoneId") or ""),
            )
        ) < 2:
            return {"kind": "not_applicable"}
    if _COORDINATE.search(text):
        return {
            "kind": "refuse",
            "code": "facility_cell_coordinate_ownership",
            "response": (
                "**I cannot accept cell coordinates, transforms, or angles from chat.** "
                "Name the target area, registered strategies, objective, and optional "
                "preferred spacing; InspectorPro will compute the geometry."
            ),
        }
    if _UNSUPPORTED_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_cell_unsupported_engineering_claim",
            "response": (
                "**I cannot claim that a cell is safe, compliant, ergonomic, optimal, "
                "or capable of a throughput from static geometry alone.** Bind the "
                "applicable controlled evidence and acceptance criteria; nothing changed."
            ),
        }
    target = _target_from_message(text, layout)
    if target is None:
        return {
            "kind": "ask",
            "code": "facility_cell_target_required",
            "response": "**Name one existing department or child area for the cell.** Nothing changed.",
        }
    try:
        zone = _resolve_zone(layout, target)
    except FacilityCellCompositionError as exc:
        return {
            "kind": "ask",
            "code": exc.code,
            "response": f"**I could not resolve the target cell area.** {exc} Nothing changed.",
        }
    members = _member_placements(layout, str(zone.get("zoneId") or ""))
    if len(members) < 2:
        return {
            "kind": "ask",
            "code": "facility_cell_resources_required",
            "response": (
                f"**Place at least two exact catalog resources in {target} first.** "
                "G5 compares and composes revision-bound resources; it does not invent a cell BOM."
            ),
        }
    strategies = strategy_mentions
    if not strategies:
        if re.search(r"\b(?:all|best|feasible\s+options?)\b", text, re.I):
            strategies = list(CELL_FEASIBILITY_STRATEGIES)
        else:
            return {
                "kind": "ask",
                "code": "facility_cell_strategies_required",
                "response": (
                    "**Name the cell strategies to compare, or ask for all registered "
                    "strategies.** Nothing changed."
                ),
            }
    objective = _objective_from_message(text)
    build = _BUILD_INTENT.search(text) is not None
    compare = _COMPARE_INTENT.search(text) is not None
    selected = _selected_strategy_from_message(
        text,
        strategies,
        build=build,
    )
    if selected is not None and objective is None:
        objective = "shortest_travel"
    if objective is None:
        if not build and compare:
            objective = "shortest_travel"
        else:
            return {
                "kind": "ask",
                "code": "facility_cell_objective_required",
                "response": (
                    "**Name the ranking objective: shortest travel, smallest envelope, "
                    "minimum movement, or maximum expansion reserve.** Nothing changed."
                ),
            }
    process_sequence_ids: list[str] = []
    sequence_match = _PROCESS_SEQUENCE.search(text)
    if sequence_match is not None:
        return {
            "kind": "ask",
            "code": "facility_cell_process_sequence_requires_exact_resources",
            "response": (
                "**The process sequence must bind every exact placement in the target "
                "cell.** Select or name the exact placement instances in order; nothing changed."
            ),
        }
    request = {
        "target_area": target,
        "candidate_strategies": strategies,
        "selected_strategy": selected,
        "objective": objective,
        "preferred_gap_meters": _gap_from_message(text),
        "invert_u": bool(re.search(r"\binvert(?:ed)?\s+u\b", text, re.I)),
        "process_sequence_placement_ids": process_sequence_ids,
        "preserve_departments": True,
        "preserve_routes": True,
        "preserve_markings": True,
        "preserve_locked_and_manual": True,
        "execution_mode": "authorized_draft_run",
    }
    try:
        normalized = normalize_cell_composition_request(request, layout)
        analysis = analyze_cell_composition_request(
            layout,
            normalized,
            asset_catalog,
        )
    except FacilityCellCompositionError as exc:
        return {
            "kind": "ask",
            "code": exc.code,
            "response": f"**I could not prepare that cell comparison.** {exc} Nothing changed.",
        }
    if not build and compare:
        return {"kind": "read_only", "request": normalized, "analysis": analysis}
    return {"kind": "build", "request": normalized, "analysis": analysis}


def _rank_key(record: Mapping[str, Any], objective: str) -> tuple[Any, ...]:
    metrics = record.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    if objective == "smallest_envelope":
        primary = float(metrics.get("cellEnvelopeAreaSquareMeters") or 0.0)
    elif objective == "minimum_movement":
        primary = float(metrics.get("totalPlacementMovementMeters") or 0.0)
    elif objective == "maximum_expansion_reserve":
        primary = -float(metrics.get("expansionReserveSquareMeters") or 0.0)
    else:
        primary = float(metrics.get("operatorTravelDistanceMeters") or 0.0)
    return (
        primary,
        float(metrics.get("cellEnvelopeAreaSquareMeters") or 0.0),
        CELL_FEASIBILITY_STRATEGIES.index(str(record.get("strategy") or "")),
    )


def analyze_cell_composition_request(
    layout: Mapping[str, Any],
    normalized: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    evidence_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = _analysis_layout(
        layout,
        asset_catalog,
        evidence_authority=evidence_authority,
    )
    try:
        analysis = analyze_facility_cell_alternatives(
            enriched,
            scope_ids=[str(normalized["targetZoneId"])],
            strategies=list(normalized["candidateStrategies"]),
            preferred_gap_meters=float(normalized["preferredGapMeters"]),
            invert_u=bool(normalized["invertU"]),
            sequence_placement_ids=list(
                normalized.get("processSequencePlacementIds") or []
            ),
        )
    except ValueError as exc:
        raise FacilityCellCompositionError(
            "facility_cell_process_sequence_incomplete",
            "The process sequence must cover every station in the target cell exactly once.",
        ) from exc
    records = list(analysis.get("rankedFeasibleRecords") or [])
    if not records:
        blockers = {
            str(code)
            for record in analysis.get("rejectedRecords", [])
            if isinstance(record, Mapping)
            for code in record.get("blockerCodes", [])
        }
        raise FacilityCellCompositionError(
            "facility_cell_no_feasible_strategy",
            "None of the requested registered strategies fits the current bounded geometry.",
            details={"blockerCodes": sorted(blockers)},
        )
    selected = normalized.get("selectedStrategy")
    if selected:
        selected_record = next(
            (item for item in records if item.get("strategy") == selected),
            None,
        )
        if selected_record is None:
            rejected = next(
                (
                    item
                    for item in analysis.get("rejectedRecords", [])
                    if item.get("strategy") == selected
                ),
                {},
            )
            raise FacilityCellCompositionError(
                "facility_cell_selected_strategy_rejected",
                f"The requested '{selected}' strategy is not geometrically feasible.",
                details={"blockerCodes": list(rejected.get("blockerCodes") or [])},
            )
    else:
        selected_record = min(
            records,
            key=lambda item: _rank_key(item, str(normalized["objective"])),
        )
    result = deepcopy(analysis)
    result["selectedStrategy"] = selected_record["strategy"]
    result["selectedRecord"] = deepcopy(selected_record)
    result["selectionObjective"] = normalized["objective"]
    result["processSequenceAuthority"] = normalized["processSequenceAuthority"]
    return result


def _cell_group_extension(
    zone: Mapping[str, Any], normalized: Mapping[str, Any]
) -> dict[str, Any]:
    extensions = deepcopy(dict(zone.get("extensions") or {}))
    existing = extensions.get("cellGroup")
    existing = deepcopy(dict(existing)) if isinstance(existing, Mapping) else {}
    auto_number = existing.get("autoNumber")
    if not isinstance(auto_number, Mapping):
        auto_number = {
            "seriesId": _stable_id(
                "series-g5", {"zoneId": normalized["targetZoneId"]}
            ),
            "baseName": str(normalized["targetArea"])[:80],
            "prefix": "C",
            "start": 1,
            "padding": 2,
            "sequence": 1,
        }
    cell_group = {
        "schemaVersion": 1,
        "groupKind": "manufacturing_cell",
        "membership": "geometric",
        "envelopePadding": 0.0,
        "autoNumber": deepcopy(dict(auto_number)),
    }
    if isinstance(existing.get("functionalInterfaces"), Mapping):
        cell_group["functionalInterfaces"] = deepcopy(
            dict(existing["functionalInterfaces"])
        )
    extensions["cellGroup"] = cell_group
    return extensions


def compile_cell_composition_program(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    evidence_authority: Mapping[str, Any] | None = None,
    defer_post_validation: bool = False,
    include_compiled_document: bool = False,
) -> dict[str, Any]:
    base = canonicalize_layout(deepcopy(dict(layout)))
    normalized = normalize_cell_composition_request(request, base)
    analysis = analyze_cell_composition_request(
        base,
        normalized,
        asset_catalog,
        evidence_authority=evidence_authority,
    )
    selected = analysis["selectedRecord"]
    sequence_ids = list(analysis.get("sequencePlacementIds") or [])
    authored_sequence_ids = list(normalized["processSequencePlacementIds"])
    if not authored_sequence_ids:
        normalized["processSequencePlacementIds"] = sequence_ids
    provenance = {
        "schemaVersion": 1,
        "command": "cell_layout",
        "authoredStrategy": selected["strategy"],
        "seedEntityIds": list(normalized["memberPlacementIds"]),
        "parameters": {
            "requestId": normalized["requestId"],
            "targetZoneId": normalized["targetZoneId"],
            "objective": normalized["objective"],
            "preferredGapMeters": normalized["preferredGapMeters"],
            "preferredGapAuthority": normalized["preferredGapAuthority"],
            "candidateStrategies": list(normalized["candidateStrategies"]),
            "processSequencePlacementIds": sequence_ids,
            "processSequenceAuthority": normalized["processSequenceAuthority"],
            "comparisonRevision": _revision(analysis["records"]),
        },
    }
    operations: list[dict[str, Any]] = []
    zones = _zone_index(base)
    target_zone = zones[normalized["targetZoneId"]]
    operations.append(
        {
            "op": "edit_zone",
            "zoneId": normalized["targetZoneId"],
            "patch": {
                "extensions": _cell_group_extension(target_zone, normalized)
            },
            "layoutProvenance": deepcopy(provenance),
        }
    )
    placements = {
        str(item.get("placementId") or ""): item
        for item in base.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    proposed = {
        str(item.get("placementId") or ""): item
        for item in selected.get("proposedTransforms", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    for placement_id in normalized["memberPlacementIds"]:
        target = proposed[placement_id]
        position = deepcopy(target["position"])
        operations.append(
            {
                "op": "move_placement",
                "placementId": placement_id,
                "position": position,
                "movementKind": "automatic",
                "layoutProvenance": deepcopy(provenance),
            }
        )
    if defer_post_validation:
        result = apply_prevalidated_facility_layout_operations(
            base,
            operations,
            base_revision=trusted_canonical_layout_revision(base),
        )
    else:
        result = apply_facility_layout_operations(
            base,
            operations,
            base_revision=layout_revision(base),
        )
    expected = {
        "scope": G5_CELL_COMPOSITION_SCOPE,
        "requestId": normalized["requestId"],
        "targetArea": normalized["targetArea"],
        "targetZoneId": normalized["targetZoneId"],
        "memberPlacementIds": list(normalized["memberPlacementIds"]),
        "processSequencePlacementIds": sequence_ids,
        "candidateStrategies": list(normalized["candidateStrategies"]),
        "selectedStrategy": selected["strategy"],
        "selectedStrategyLabel": str(
            selected.get("strategyLabel") or selected["strategy"]
        ),
        "objective": normalized["objective"],
        "preferredGapMeters": normalized["preferredGapMeters"],
        "preferredGapAuthority": normalized["preferredGapAuthority"],
        "invertU": normalized["invertU"],
        "validationStatus": selected["validationStatus"],
        "clearanceEvidenceComplete": selected["clearanceEvidenceComplete"],
        "selectedMetrics": deepcopy(selected["metrics"]),
        "rejectedStrategies": [
            {
                "strategy": item["strategy"],
                "blockerCodes": list(item.get("blockerCodes") or []),
            }
            for item in analysis.get("rejectedRecords", [])
        ],
        "preservedCollectionRevisions": {
            field: _collection_revision(base, field)
            for field in ("routes", "floorMarkings", "utilityNetworks", "processBindings")
        },
        "saved": False,
    }
    if not defer_post_validation:
        validation = validate_cell_composition_result(
            result["document"],
            expected,
            asset_catalog,
            base_layout=base,
            evidence_authority=evidence_authority,
        )
        if validation["status"] != "valid":
            raise FacilityCellCompositionError(
                "facility_cell_program_validation_failed",
                "Compiled G5 cell failed deterministic post-validation.",
                details={"errors": validation["errors"]},
            )
    replay_input: dict[str, Any] = {
        "scope": G5_CELL_COMPOSITION_SCOPE,
        "request": {
            "request_id": normalized["requestId"],
            "target_area": normalized["targetArea"],
            "candidate_strategies": list(normalized["candidateStrategies"]),
            "selected_strategy": selected["strategy"],
            "objective": normalized["objective"],
            "preferred_gap_meters": (
                normalized["preferredGapMeters"]
                if normalized["preferredGapAuthority"] == "user_authored"
                else None
            ),
            "invert_u": normalized["invertU"],
            "process_sequence_placement_ids": sequence_ids,
            "preserve_departments": True,
            "preserve_routes": True,
            "preserve_markings": True,
            "preserve_locked_and_manual": True,
            "execution_mode": "authorized_draft_run",
        },
        "assetCatalog": [deepcopy(dict(item)) for item in asset_catalog],
    }
    if isinstance(evidence_authority, Mapping):
        replay_input["evidenceAuthority"] = deepcopy(dict(evidence_authority))
    compiled_result = {
        "stageId": G5_CELL_COMPOSITION_SCOPE,
        "selectedCommandIds": ["cell-layout", "create-cell-group"],
        "operations": operations,
        "plannedInstanceCount": len(normalized["memberPlacementIds"]),
        "normalizedRequest": replay_input,
        "assumptions": list(normalized["assumptions"]),
        "validationPlan": [
            "registered_strategy_only",
            "target_zone_containment",
            "physical_collision_free",
            "protected_route_and_marking_preservation",
            "department_geometry_preservation",
            "placement_identity_and_rotation_preservation",
            "fixed_placement_preservation",
            "access_evidence_classification",
            "rejected_fit_explanations",
        ],
        "expectedSummary": expected,
    }
    if include_compiled_document:
        compiled_result["_compiledDocument"] = result["document"]
    return compiled_result


def validate_cell_composition_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
    asset_catalog: Sequence[Mapping[str, Any]],
    *,
    base_layout: Mapping[str, Any],
    evidence_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    current = canonicalize_layout(deepcopy(dict(layout)))
    base = canonicalize_layout(deepcopy(dict(base_layout)))
    target_id = str(expected.get("targetZoneId") or "")
    current_zones = _zone_index(current)
    base_zones = _zone_index(base)
    if set(current_zones) != set(base_zones):
        errors.append("zone_identity_changed")
    for zone_id, before in base_zones.items():
        after = current_zones.get(zone_id)
        if after is None:
            continue
        if zone_id == target_id:
            before = deepcopy(before)
            after = deepcopy(after)
            before_extensions = deepcopy(dict(before.get("extensions") or {}))
            after_extensions = deepcopy(dict(after.get("extensions") or {}))
            before_extensions.pop("cellGroup", None)
            after_extensions.pop("cellGroup", None)
            before_extensions.pop("layoutProvenance", None)
            after_extensions.pop("layoutProvenance", None)
            before["extensions"] = before_extensions
            after["extensions"] = after_extensions
        if before != after:
            errors.append(f"department_changed:{zone_id}")
    target = current_zones.get(target_id) or {}
    target_extensions = target.get("extensions")
    target_extensions = (
        target_extensions if isinstance(target_extensions, Mapping) else {}
    )
    target_provenance = target_extensions.get("layoutProvenance")
    if not isinstance(target_provenance, Mapping):
        errors.append("cell_layout_provenance_missing")
    else:
        if target_provenance.get("command") != "cell_layout":
            errors.append("cell_layout_provenance_command_invalid")
        if target_provenance.get("authoredStrategy") != expected.get(
            "selectedStrategy"
        ):
            errors.append("cell_layout_provenance_strategy_invalid")
        if set(target_provenance.get("seedEntityIds") or []) != set(
            expected.get("memberPlacementIds") or []
        ):
            errors.append("cell_layout_provenance_members_invalid")
    for field, revision in expected.get("preservedCollectionRevisions", {}).items():
        if _collection_revision(current, str(field)) != revision:
            errors.append(f"preserved_collection_changed:{field}")
    current_placements = {
        str(item.get("placementId") or ""): item
        for item in current.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    base_placements = {
        str(item.get("placementId") or ""): item
        for item in base.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    if set(current_placements) != set(base_placements):
        errors.append("placement_identity_changed")
    member_ids = set(expected.get("memberPlacementIds") or [])
    for placement_id, before in base_placements.items():
        after = current_placements.get(placement_id)
        if after is None:
            continue
        if placement_id not in member_ids:
            if before != after:
                errors.append(f"unrelated_placement_changed:{placement_id}")
            continue
        if before.get("assetId") != after.get("assetId") or before.get(
            "assetDefinitionRevision"
        ) != after.get("assetDefinitionRevision"):
            errors.append(f"placement_asset_identity_changed:{placement_id}")
        before_transform = before.get("transform")
        after_transform = after.get("transform")
        if isinstance(before_transform, Mapping) and isinstance(after_transform, Mapping):
            if before_transform.get("quaternion") != after_transform.get("quaternion"):
                errors.append(f"placement_rotation_changed:{placement_id}")
        if before.get("positionMode") in {"locked", "manual"} and before != after:
            errors.append(f"fixed_placement_changed:{placement_id}")
    request = {
        "target_area": expected.get("targetArea"),
        "candidate_strategies": list(expected.get("candidateStrategies") or []),
        "selected_strategy": expected.get("selectedStrategy"),
        "objective": expected.get("objective"),
        "preferred_gap_meters": (
            expected.get("preferredGapMeters")
            if expected.get("preferredGapAuthority") == "user_authored"
            else None
        ),
        "invert_u": expected.get("invertU") is True,
        "process_sequence_placement_ids": list(
            expected.get("processSequencePlacementIds") or []
        ),
        "preserve_departments": True,
        "preserve_routes": True,
        "preserve_markings": True,
        "preserve_locked_and_manual": True,
        "execution_mode": "authorized_draft_run",
    }
    try:
        normalized = normalize_cell_composition_request(request, current)
        analysis = analyze_cell_composition_request(
            current,
            normalized,
            asset_catalog,
            evidence_authority=evidence_authority,
        )
    except FacilityCellCompositionError as exc:
        errors.append(f"post_analysis_failed:{exc.code}")
        analysis = {}
    if analysis and analysis.get("selectedStrategy") != expected.get("selectedStrategy"):
        errors.append("selected_strategy_not_reproducible")
    if analysis:
        proposed = {
            str(item.get("placementId") or ""): item.get("position")
            for item in analysis.get("selectedRecord", {}).get(
                "proposedTransforms", []
            )
            if isinstance(item, Mapping) and item.get("placementId")
        }
        for placement_id in member_ids:
            placement = current_placements.get(placement_id, {})
            actual_position = (
                placement.get("transform", {}).get("position")
                if isinstance(placement.get("transform"), Mapping)
                else None
            )
            if actual_position != proposed.get(placement_id):
                errors.append(f"cell_transform_not_reproducible:{placement_id}")
    return {
        "status": "valid" if not errors else "invalid",
        "selectedStrategy": expected.get("selectedStrategy"),
        "memberPlacementCount": len(member_ids),
        "clearanceEvidenceComplete": expected.get("clearanceEvidenceComplete") is True,
        "errors": sorted(set(errors)),
    }


__all__ = [
    "G5_CELL_COMPOSITION_SCOPE",
    "G5_CELL_OBJECTIVES",
    "G5_FACILITY_CELL_COMPOSITION_TOOL",
    "FacilityCellCompositionError",
    "analyze_cell_composition_request",
    "cell_composition_tool_spec",
    "compile_cell_composition_program",
    "normalize_cell_composition_request",
    "parse_cell_composition_turn",
    "validate_cell_composition_result",
]
