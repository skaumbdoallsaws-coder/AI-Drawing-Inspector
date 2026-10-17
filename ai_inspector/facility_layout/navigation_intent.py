"""Bounded NAV8 Sage intent and tool contracts.

Sage may resolve and combine stable navigation identities. It never authors
path coordinates, actor geometry, clearance values, or operational approval.
All geometry-bearing results remain in opaque server packages.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .navigation_contract import FACILITY_NAVIGATION_LIMITS
from .activity_scenario import FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS


OBSERVE_NAVIGATION_CONTEXT_TOOL = "observe_navigation_context"
COMPILE_NAVIGATION_SNAPSHOT_TOOL = "compile_navigation_snapshot"
PLAN_ACTOR_JOURNEY_TOOL = "plan_actor_journey"
VALIDATE_ACTOR_JOURNEY_TOOL = "validate_actor_journey"
COMPARE_JOURNEY_ALTERNATIVES_TOOL = "compare_journey_alternatives"
PROPOSE_NAVIGATION_INTENT_TOOL = "propose_navigation_intent"
BUILD_ACTIVITY_SCENARIO_TOOL = "build_activity_scenario"

NAVIGATION_READ_TOOL_NAMES = frozenset({
    OBSERVE_NAVIGATION_CONTEXT_TOOL,
    COMPILE_NAVIGATION_SNAPSHOT_TOOL,
    PLAN_ACTOR_JOURNEY_TOOL,
    VALIDATE_ACTOR_JOURNEY_TOOL,
    COMPARE_JOURNEY_ALTERNATIVES_TOOL,
})
NAVIGATION_TERMINAL_TOOL_NAMES = frozenset({
    PROPOSE_NAVIGATION_INTENT_TOOL,
    BUILD_ACTIVITY_SCENARIO_TOOL,
})

FACILITY_NAVIGATION_SAGE_CONTRACT_VERSION = "facility-navigation-sage-v1"
FACILITY_NAVIGATION_SAGE_QUALIFICATION = (
    "Revision-bound navigation identity and topology evidence only. It does "
    "not establish safety, staffing, throughput, timing, clearance adequacy, "
    "regulatory compliance, or operational optimality."
)

_ID = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
_PROGRAM_ID = re.compile(r"\bnmp-[A-Za-z0-9._:-]{1,124}\b", re.I)
_JOURNEY_ID = re.compile(r"\bnjs-[A-Za-z0-9._:-]{1,124}\b", re.I)
_ANCHOR_ID = re.compile(r"\bna-[A-Za-z0-9._:-]{1,125}\b", re.I)
_HANDOFF_ID = re.compile(r"\bnhp-[A-Za-z0-9._:-]{1,124}\b", re.I)
_COORDINATE = re.compile(
    r"(?:\b(?:x|z)\s*[:=]\s*-?\d|\bworld\s+(?:point|coordinate)|"
    r"\b(?:put|place|route|detour|waypoint)\b[^.!?]{0,80}"
    r"\b(?:x|z)\s*[:=]?\s*-?\d)",
    re.I,
)
_UNSUPPORTED_ENGINEERING = re.compile(
    r"\b(?:safe(?:ty)?|osha|fire\s*code|code[- ]compliant|compliance|"
    r"adequate|optimal|throughput|capacity|staffing|"
    r"whatever\s+(?:clearance|code)|typical\s+(?:forklift|vehicle)|"
    r"any\s+(?:forklift|vehicle))\b",
    re.I,
)
_NAVIGATION_NOUN = re.compile(
    r"\b(?:actor|operator|pedestrian|forklift|vehicle|journey|path|route|"
    r"aisle|guide|detour|navigation|waypoint|service\s+point|station|fifo|"
    r"handoff|crossing|egress|movement\s+program|activity\s+scenario|motion)\b",
    re.I,
)
_NAVIGATION_VERB = re.compile(
    r"\b(?:route|send|walk|travel|replan|plan|validate|check|compare|"
    r"play|show|animate|move|reach|avoid|use|keep|lock|assign)\b",
    re.I,
)
_NAV8_EXPLICIT_TERM = re.compile(
    r"\b(?:movement\s+programs?|actor\s+journeys|navigation\s+anchors?|"
    r"manual\s+path\s+constraints?|navigation\s+activity|"
    r"navigation\s+snapshots?|plan[- ]authored\s+(?:motion\s+)?paths?)\b",
    re.I,
)
_NAV8_TASK_TARGET = re.compile(
    r"\b(?:anchors?|stations?|fifos?|service\s+points?|handoff\s+endpoints?|"
    r"actor\s+homes?|vehicle\s+parking|vehicle\s+turnarounds?|"
    r"destinations?|stops?|tables?|workbenches?|machines?|equipment|"
    r"workstations?|cells?)\b",
    re.I,
)
_SELECTED_DESTINATION_REQUEST = re.compile(
    r"\b(?:selected\s+(?:destinations?|stops?|tables?|workbenches?|stations?|"
    r"machines?|equipment|items?)|destinations?\s+in\s+selection\s+order|"
    r"through\s+(?:these|the\s+selected)|via\s+(?:these|the\s+selected))\b",
    re.I,
)
_NAV8_ACTIVITY_PRESENTATION = re.compile(
    r"\b(?:prototype\s+factory\s+activity|up\s+to\s+\d+\s+actors?|"
    r"machines?\b[^.!?]{0,80}\bstationary)\b",
    re.I,
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean(value: Any, maximum: int = 160) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _bounded_ids(values: Iterable[Any], maximum: int = 20) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and re.fullmatch(_ID, text) and text not in result:
            result.append(text)
        if len(result) >= maximum:
            break
    return result


def _placement_label(item: Mapping[str, Any]) -> str:
    metadata = item.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return _clean(
        metadata.get("instanceLabel")
        or metadata.get("label")
        or item.get("assetId")
        or item.get("placementId"),
        120,
    )


def _placement_actor_class(
    placement: Mapping[str, Any],
    program: Mapping[str, Any] | None = None,
) -> str | None:
    if isinstance(program, Mapping):
        value = str(program.get("actorClass") or "")
        if value in {"pedestrian", "vehicle"}:
            return value
    metadata = placement.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    hinted = str(metadata.get("activityActorType") or "")
    if hinted == "operator":
        return "pedestrian"
    if hinted in {"vehicle", "mobile_equipment"}:
        return "vehicle"
    tokens = " ".join((
        str(placement.get("assetId") or ""),
        str(metadata.get("instanceLabel") or ""),
        str(metadata.get("displayName") or ""),
    )).casefold()
    if re.search(r"\b(?:operator|person|worker|pedestrian)\b", tokens):
        return "pedestrian"
    if re.search(r"\b(?:forklift|vehicle|truck|tugger|agv|cart)\b", tokens):
        return "vehicle"
    return None


def _owner_label_indexes(layout: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    return {
        "placement": {
            str(item.get("placementId")): _placement_label(item)
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        },
        "zone": {
            str(item.get("zoneId")): _clean(
                item.get("label") or item.get("zoneId"), 120
            )
            for item in layout.get("zones", [])
            if isinstance(item, Mapping) and item.get("zoneId")
        },
        "route": {
            str(item.get("routeId")): _clean(
                item.get("label") or item.get("routeId"), 120
            )
            for item in layout.get("routes", [])
            if isinstance(item, Mapping) and item.get("routeId")
        },
        "marking": {
            str(item.get("markingId")): _clean(
                item.get("label") or item.get("markingId"), 120
            )
            for item in layout.get("floorMarkings", [])
            if isinstance(item, Mapping) and item.get("markingId")
        },
    }


def _extension(layout: Mapping[str, Any]) -> Mapping[str, Any]:
    extensions = layout.get("extensions")
    value = (
        extensions.get("facilityNavigation")
        if isinstance(extensions, Mapping)
        else None
    )
    return value if isinstance(value, Mapping) else {
        "anchors": [],
        "movementPrograms": [],
        "manualPathConstraints": [],
        "handoffPrograms": [],
    }


def navigation_context_summary(
    layout: Mapping[str, Any],
    *,
    query: str = "",
    actor_class: str | None = None,
    maximum_records: int = 20,
) -> dict[str, Any]:
    """Return a coordinate-free, byte-bounded navigation observation."""

    maximum = max(1, min(int(maximum_records), 50))
    query_key = _normalized(query)
    extension = _extension(layout)
    owners = _owner_label_indexes(layout)
    programs = [
        deepcopy(dict(item))
        for item in extension.get("movementPrograms", [])
        if isinstance(item, Mapping)
        and (not actor_class or item.get("actorClass") == actor_class)
    ]
    program_by_actor = {
        str(item.get("actorPlacementId")): item for item in programs
    }
    actors = []
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping) or not placement.get("placementId"):
            continue
        placement_id = str(placement["placementId"])
        program = program_by_actor.get(placement_id)
        inferred_class = _placement_actor_class(placement, program)
        if inferred_class not in {"pedestrian", "vehicle"}:
            continue
        if actor_class and inferred_class != actor_class:
            continue
        label = _placement_label(placement)
        haystack = _normalized(" ".join((placement_id, label, inferred_class)))
        if query_key and query_key not in haystack:
            continue
        missing = []
        if program is None:
            missing.append("movement_program")
        elif not program.get("orderedStops"):
            missing.append("ordered_stops")
        if inferred_class == "vehicle" and not (
            program and isinstance(program.get("actorProfileRef"), Mapping)
        ):
            missing.append("published_vehicle_profile")
        actors.append({
            "actorPlacementId": placement_id,
            "label": label,
            "actorClass": inferred_class,
            "movementProgramId": (
                str(program.get("movementProgramId")) if program else None
            ),
            "missingSemantics": missing,
        })
    actors.sort(key=lambda item: (item["label"].casefold(), item["actorPlacementId"]))

    anchors = []
    for anchor in extension.get("anchors", []):
        if not isinstance(anchor, Mapping):
            continue
        owner = anchor.get("ownerRef")
        owner = owner if isinstance(owner, Mapping) else {}
        owner_kind = str(owner.get("ownerKind") or "")
        owner_id = str(owner.get("ownerId") or "")
        owner_label = owners.get(owner_kind, {}).get(owner_id, owner_id)
        record = {
            "navigationAnchorId": str(anchor.get("navigationAnchorId") or ""),
            "anchorKind": str(anchor.get("anchorKind") or ""),
            "ownerKind": owner_kind,
            "ownerId": owner_id,
            "ownerLabel": owner_label,
            "interactionKind": str(anchor.get("interactionKind") or ""),
            "actorClasses": list(anchor.get("actorClasses") or []),
            "positionAuthority": str(anchor.get("positionAuthority") or ""),
            "reviewStatus": str(anchor.get("reviewStatus") or ""),
        }
        haystack = _normalized(" ".join(str(value) for value in record.values()))
        if not query_key or query_key in haystack:
            anchors.append(record)
    anchors.sort(key=lambda item: (item["ownerLabel"].casefold(), item["navigationAnchorId"]))

    compact_programs = []
    for program in programs:
        actor_id = str(program.get("actorPlacementId") or "")
        record = {
            "movementProgramId": str(program.get("movementProgramId") or ""),
            "actorPlacementId": actor_id,
            "actorLabel": owners["placement"].get(actor_id, actor_id),
            "actorClass": str(program.get("actorClass") or ""),
            "orderedAnchorIds": [
                str(item.get("navigationAnchorId") or "")
                for item in program.get("orderedStops", [])
                if isinstance(item, Mapping)
            ],
            "loopMode": str(program.get("loopMode") or ""),
            "requiredRouteIds": list(program.get("requiredRouteIds") or []),
            "forbiddenZoneIds": list(program.get("forbiddenZoneIds") or []),
            "manualOverrideCount": len(program.get("manualPathConstraintIds") or []),
            "reviewStatus": str(program.get("reviewStatus") or ""),
        }
        haystack = _normalized(" ".join(str(value) for value in record.values()))
        if not query_key or query_key in haystack:
            compact_programs.append(record)
    compact_programs.sort(key=lambda item: item["movementProgramId"])

    handoffs = []
    for item in extension.get("handoffPrograms", []):
        if not isinstance(item, Mapping):
            continue
        record = {
            "handoffProgramId": str(item.get("handoffProgramId") or ""),
            "sourceMovementProgramId": str(
                item.get("sourceMovementProgramId") or ""
            ),
            "targetMovementProgramId": str(
                item.get("targetMovementProgramId") or ""
            ),
            "sourceAnchorId": str(item.get("sourceAnchorId") or ""),
            "targetAnchorId": str(item.get("targetAnchorId") or ""),
            "sequencePolicy": str(item.get("sequencePolicy") or ""),
            "timingAuthority": str(item.get("timingAuthority") or ""),
            "reviewStatus": str(item.get("reviewStatus") or ""),
        }
        haystack = _normalized(" ".join(str(value) for value in record.values()))
        if not query_key or query_key in haystack:
            handoffs.append(record)
    handoffs.sort(key=lambda item: item["handoffProgramId"])

    result = {
        "schemaVersion": "facility-navigation-context-summary-v1",
        "contractVersion": FACILITY_NAVIGATION_SAGE_CONTRACT_VERSION,
        "counts": {
            "actors": len(actors),
            "anchors": len(anchors),
            "movementPrograms": len(compact_programs),
            "handoffPrograms": len(handoffs),
        },
        "actors": actors[:maximum],
        "anchors": anchors[:maximum],
        "movementPrograms": compact_programs[:maximum],
        "handoffPrograms": handoffs[:maximum],
        "truncated": any(
            len(values) > maximum
            for values in (actors, anchors, compact_programs, handoffs)
        ),
        "qualification": FACILITY_NAVIGATION_SAGE_QUALIFICATION,
    }
    size = len(_canonical_bytes(result))
    while size > FACILITY_NAVIGATION_LIMITS["sageSummaryBytes"] and maximum > 1:
        maximum = max(1, maximum // 2)
        for key in ("actors", "anchors", "movementPrograms", "handoffPrograms"):
            result[key] = result[key][:maximum]
        result["truncated"] = True
        size = len(_canonical_bytes(result))
    result["canonicalBytes"] = size
    return result


def compare_journey_summaries(
    journeys: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    records = []
    for journey in journeys:
        records.append({
            "journeySolutionId": str(journey.get("journeySolutionId") or ""),
            "movementProgramId": str(journey.get("movementProgramId") or ""),
            "actorPlacementId": str(journey.get("actorPlacementId") or ""),
            "outcome": str(journey.get("outcome") or ""),
            "distanceMeters": float(journey.get("distanceMeters") or 0),
            "turnCount": int(journey.get("turnCount") or 0),
            "reverseUsed": journey.get("reverseUsed") is True,
            "solutionFingerprint": str(journey.get("solutionFingerprint") or ""),
        })
    records.sort(key=lambda item: item["journeySolutionId"])
    return {
        "schemaVersion": "facility-navigation-journey-comparison-v1",
        "records": records,
        "distanceOrder": [
            item["journeySolutionId"]
            for item in sorted(
                records,
                key=lambda item: (
                    item["distanceMeters"], item["turnCount"], item["journeySolutionId"]
                ),
            )
        ],
        "turnCountOrder": [
            item["journeySolutionId"]
            for item in sorted(
                records,
                key=lambda item: (
                    item["turnCount"], item["distanceMeters"], item["journeySolutionId"]
                ),
            )
        ],
        "operationalOptimalityClaimed": False,
        "qualification": FACILITY_NAVIGATION_SAGE_QUALIFICATION,
    }


def is_navigation_semantic_request(message: Any) -> bool:
    text = str(message or "")
    if _NAV8_ACTIVITY_PRESENTATION.search(text) and not (
        _PROGRAM_ID.search(text) or _JOURNEY_ID.search(text)
    ):
        return False
    if any(pattern.search(text) for pattern in (
        _PROGRAM_ID,
        _JOURNEY_ID,
        _ANCHOR_ID,
        _HANDOFF_ID,
        _NAV8_EXPLICIT_TERM,
    )):
        return True
    return bool(
        re.search(r"\b(?:operator|pedestrian|forklift|vehicle|actor)\b", text, re.I)
        and _NAV8_TASK_TARGET.search(text)
        and (
            _NAVIGATION_VERB.search(text)
            or _COORDINATE.search(text)
            or _UNSUPPORTED_ENGINEERING.search(text)
        )
    )


def navigation_action_mode(message: Any) -> str:
    """Classify semantic intent editing separately from read-only playback."""

    text = _normalized(message)
    if not is_navigation_semantic_request(message):
        return "READ_ONLY"
    if re.search(r"\b(?:play|show|animate|preview)\b", text) and re.search(
        r"\b(?:existing|selected|authored)\b[^.!?]{0,100}"
        r"\b(?:path|program|journey|navigation)\b",
        text,
    ):
        return "READ_ONLY"
    if re.search(
        r"\b(?:through|via|avoid|assign|keep|lock|require|forbid|"
        r"use the|use route|return on|then to|followed by)\b",
        text,
    ):
        return "PREVIEW"
    return "READ_ONLY"


def navigation_deterministic_refusal(message: Any) -> dict[str, Any] | None:
    """Return a named refusal before any provider or browser tool can run."""

    text = str(message or "")
    if not is_navigation_semantic_request(text):
        return None
    if _COORDINATE.search(text):
        return {
            "code": "facility_navigation_coordinate_authority_forbidden",
            "response": (
                "**I cannot accept navigation coordinates from chat.** Draw or "
                "edit the guide in Plan, or refer to an existing authored anchor, "
                "route, zone, or path constraint by name or stable ID."
            ),
        }
    unsupported_best_route = bool(
        re.search(r"\bbest\s+route\b", text, re.I)
        and not _SELECTED_DESTINATION_REQUEST.search(text)
    )
    if _UNSUPPORTED_ENGINEERING.search(text) or unsupported_best_route:
        return {
            "code": "facility_navigation_engineering_authority_unavailable",
            "response": (
                "**I cannot claim this navigation is safe, compliant, adequate, "
                "capacity-proven, or operationally optimal.** Provide the exact "
                "approved policy or published actor/vehicle profile. I can compare "
                "deterministic distance and turn count without making that claim."
            ),
        }
    return None


def _explicit_ids(pattern: re.Pattern[str], message: str) -> list[str]:
    return _bounded_ids(match.group(0) for match in pattern.finditer(message))


def classify_navigation_tool_intent(
    message: Any,
    layout: Mapping[str, Any],
    *,
    selected_actor_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Resolve only high-confidence NAV8 turns; ambiguous turns fail closed."""

    text = _clean(message, 2_000)
    refusal = navigation_deterministic_refusal(text)
    if refusal is not None:
        return {"kind": "refuse", **refusal}
    if not is_navigation_semantic_request(text):
        return {"kind": "not_applicable"}

    programs = _explicit_ids(_PROGRAM_ID, text)
    journeys = _explicit_ids(_JOURNEY_ID, text)
    anchors = _explicit_ids(_ANCHOR_ID, text)
    handoffs = _explicit_ids(_HANDOFF_ID, text)
    normalized = _normalized(text)

    selected_order = _bounded_ids(selected_actor_ids, maximum=20)
    automatic_selection_request = bool(
        _SELECTED_DESTINATION_REQUEST.search(text)
        and _NAVIGATION_VERB.search(text)
    )
    if automatic_selection_request and not (programs or journeys or anchors):
        if not selected_order:
            return {
                "kind": "ask",
                "code": "facility_navigation_actor_not_selected",
                "response": (
                    "**Select one existing operator, then Ctrl-click the tables, "
                    "workstations, or handoff assets in task order.** Ask me to "
                    "calculate and play the route again. Nothing was changed or saved."
                ),
            }
        placements = {
            str(item.get("placementId") or ""): item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        non_placement_ids = [
            item for item in selected_order if item not in placements
        ]
        if non_placement_ids:
            return {
                "kind": "ask",
                "code": "facility_navigation_destination_selection_invalid",
                "response": (
                    "The automatic route selection must contain only one existing "
                    "operator and its destination assets. Deselect zones, routes, "
                    "and markings, then try again. Nothing was changed or saved."
                ),
            }
        selected_actors = []
        for placement_id in selected_order:
            actor_matches = navigation_context_summary(
                layout,
                query=placement_id,
                maximum_records=2,
            )["actors"]
            exact = next(
                (
                    item for item in actor_matches
                    if item["actorPlacementId"] == placement_id
                ),
                None,
            )
            if exact is not None:
                selected_actors.append(exact)
        if len(selected_actors) != 1:
            return {
                "kind": "ask",
                "code": "facility_navigation_actor_ambiguous",
                "response": (
                    "Select exactly one existing operator, then Ctrl-click its "
                    "destination assets in task order. Nothing was changed or saved."
                ),
            }
        actor = selected_actors[0]
        targets = [
            placement_id for placement_id in selected_order
            if placement_id != actor["actorPlacementId"]
        ]
        if not targets:
            return {
                "kind": "ask",
                "code": "facility_navigation_destinations_not_selected",
                "response": (
                    "The operator is selected, but no destinations are selected. "
                    "Ctrl-click the tables, workstations, or handoff assets in task "
                    "order, then try again. Nothing was changed or saved."
                ),
            }
        same_path_return = bool(re.search(
            r"\b(?:same\s+path|backtrack|retrace)\b",
            normalized,
        ))
        returns_to_start = bool(re.search(
            r"\b(?:return|back\s+to\s+(?:the\s+)?start|loop|repeat|cycle)\b",
            normalized,
        ))
        return {
            "kind": "tool",
            "tool": PROPOSE_NAVIGATION_INTENT_TOOL,
            "arguments": {
                "actorPlacementId": actor["actorPlacementId"],
                "movementProgramId": actor.get("movementProgramId"),
                "orderedTargetPlacementIds": targets,
                "loopMode": (
                    "out_and_return" if same_path_return
                    else "task_cycle" if returns_to_start
                    else "one_way"
                ),
                "requiredRouteIds": [],
                "forbiddenZoneIds": [],
                "forbiddenRouteIds": [],
                "playAfterProposal": bool(re.search(
                    r"\b(?:play|show|animate|preview|watch|demonstrate)\b",
                    normalized,
                )),
            },
        }

    if "compare" in normalized and len(journeys) >= 2:
        return {
            "kind": "tool",
            "tool": COMPARE_JOURNEY_ALTERNATIVES_TOOL,
            "arguments": {"journeySolutionIds": journeys},
        }
    if re.search(r"\b(?:validate|check|why|cannot|can not|unreachable)\b", normalized):
        if len(journeys) == 1:
            return {
                "kind": "tool",
                "tool": VALIDATE_ACTOR_JOURNEY_TOOL,
                "arguments": {"journeySolutionId": journeys[0]},
            }
        if len(programs) == 1:
            return {
                "kind": "tool",
                "tool": COMPILE_NAVIGATION_SNAPSHOT_TOOL,
                "arguments": {"movementProgramId": programs[0]},
            }
    if re.search(r"\b(?:play|show|animate|preview)\b", normalized) and (
        journeys or programs
    ):
        return {
            "kind": "tool",
            "tool": BUILD_ACTIVITY_SCENARIO_TOOL,
            "arguments": {
                "journeySolutionIds": journeys,
                "movementProgramIds": programs,
                "handoffResultIds": handoffs,
                "prototypeMode": True,
                "scenarioLabel": "Sage navigation activity",
            },
        }
    if re.search(r"\b(?:play|show|animate|preview)\b", normalized):
        selected_ids = set(selected_order)
        selection_bound_request = bool(re.search(
            r"\bselected\b|\bplan authored\b",
            normalized,
        ))
        if selection_bound_request and not selected_ids:
            return {
                "kind": "ask",
                "code": "facility_navigation_actor_not_selected",
                "response": (
                    "**No operator or vehicle is selected in the current "
                    "Facility Layout.** Open a populated layout, select one "
                    "existing actor, draw and apply its Motion Path in Plan, "
                    "then request playback again. Nothing was changed or saved."
                ),
            }
        selected_programs = [
            item
            for item in _extension(layout).get("movementPrograms", [])
            if isinstance(item, Mapping)
            and str(item.get("actorPlacementId") or "") in selected_ids
        ]
        if len(selected_programs) == 1:
            selected_program = selected_programs[0]
            if not selected_program.get("manualPathConstraintIds"):
                return {
                    "kind": "ask",
                    "code": "facility_navigation_manual_path_unavailable",
                    "response": (
                        "The selected actor has no existing Plan-authored motion "
                        "path. Draw and apply one in Plan before requesting "
                        "playback."
                    ),
                }
            return {
                "kind": "tool",
                "tool": BUILD_ACTIVITY_SCENARIO_TOOL,
                "arguments": {
                    "journeySolutionIds": [],
                    "movementProgramIds": [
                        str(selected_program["movementProgramId"])
                    ],
                    "handoffResultIds": [],
                    "prototypeMode": True,
                    "scenarioLabel": "Sage selected navigation activity",
                },
            }
        if len(selected_programs) > 1:
            return {
                "kind": "ask",
                "code": "facility_navigation_actor_ambiguous",
                "response": (
                    "Select exactly one existing operator or vehicle before "
                    "requesting its Plan-authored path playback."
                ),
            }
        if selection_bound_request and selected_ids:
            return {
                "kind": "ask",
                "code": "facility_navigation_manual_path_unavailable",
                "response": (
                    "**The selected object has no applied Plan-authored Motion "
                    "Path.** Select an existing operator or vehicle, use Motion "
                    "Path in Plan to draw and apply its route, then request "
                    "playback again. Nothing was changed or saved."
                ),
            }
    if programs and not anchors:
        return {
            "kind": "tool",
            "tool": COMPILE_NAVIGATION_SNAPSHOT_TOOL,
            "arguments": {"movementProgramId": programs[0]},
        }
    if anchors:
        context = navigation_context_summary(layout, maximum_records=50)
        actor_matches = [
            item for item in context["actors"]
            if _normalized(item["label"]) in normalized
            or _normalized(item["actorPlacementId"]) in normalized
        ]
        if len(actor_matches) != 1:
            return {
                "kind": "ask",
                "code": "facility_navigation_actor_ambiguous",
                "response": (
                    "Which existing operator or vehicle should use these anchors? "
                    "Select one actor or name its exact label."
                ),
            }
        actor = actor_matches[0]
        return {
            "kind": "tool",
            "tool": PROPOSE_NAVIGATION_INTENT_TOOL,
            "arguments": {
                "actorPlacementId": actor["actorPlacementId"],
                "movementProgramId": actor.get("movementProgramId"),
                "orderedAnchorIds": anchors,
                "loopMode": "task_cycle",
                "requiredRouteIds": [],
                "forbiddenZoneIds": [],
                "forbiddenRouteIds": [],
            },
        }
    return {
        "kind": "tool",
        "tool": OBSERVE_NAVIGATION_CONTEXT_TOOL,
        "arguments": {"query": text, "maximumRecords": 20},
    }


def navigation_agent_tool_specs() -> list[dict[str, Any]]:
    """Return the closed NAV8 provider tool schemas."""

    stable_id = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
    stable_ids_20 = {
        "type": "array",
        "minItems": 1,
        "maxItems": 20,
        "uniqueItems": True,
        "items": stable_id,
    }
    read_qualification = (
        " Returns a compact coordinate-free summary. Full geometry remains "
        "behind an opaque package ID. Never infer safety, capacity, timing, "
        "clearance adequacy, compliance, or optimality."
    )
    return [
        {
            "name": OBSERVE_NAVIGATION_CONTEXT_TOOL,
            "description": (
                "Observe existing mobile actors, authored anchors, movement "
                "programs, handoffs, and missing semantics by stable identity."
                + read_qualification
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "maxLength": 160},
                    "actorClass": {"enum": ["pedestrian", "vehicle"]},
                    "maximumRecords": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
        },
        {
            "name": COMPILE_NAVIGATION_SNAPSHOT_TOOL,
            "description": (
                "Compile or retrieve one immutable revision-bound navigation "
                "snapshot for an existing movement program."
                + read_qualification
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["movementProgramId"],
                "properties": {
                    "movementProgramId": stable_id,
                    "prototypeMode": {"type": "boolean"},
                },
            },
        },
        {
            "name": PLAN_ACTOR_JOURNEY_TOOL,
            "description": (
                "Plan one existing movement program against one opaque "
                "navigation snapshot. No path points are accepted."
                + read_qualification
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["navigationPackageId", "movementProgramId"],
                "properties": {
                    "navigationPackageId": stable_id,
                    "movementProgramId": stable_id,
                    "prototypeMode": {"type": "boolean"},
                    "allowReverse": {"type": "boolean"},
                },
            },
        },
        {
            "name": VALIDATE_ACTOR_JOURNEY_TOOL,
            "description": (
                "Validate one journey identity against the active revision and "
                "report topology, direction, physical, authority, and stale findings."
                + read_qualification
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["journeySolutionId"],
                "properties": {"journeySolutionId": stable_id},
            },
        },
        {
            "name": COMPARE_JOURNEY_ALTERNATIVES_TOOL,
            "description": (
                "Compare 2-16 accepted or refused journey results by published "
                "distance and turn count only; never select an operational optimum."
                + read_qualification
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["journeySolutionIds"],
                "properties": {
                    "journeySolutionIds": {
                        **stable_ids_20,
                        "minItems": 2,
                        "maxItems": 16,
                    },
                },
            },
        },
        {
            "name": PROPOSE_NAVIGATION_INTENT_TOOL,
            "description": (
                "Create one unsaved semantic movement-program proposal using "
                "an existing actor plus either existing anchor IDs or ordered "
                "destination-placement IDs. Destination placements are resolved "
                "to deterministic obstacle-free access points; Sage never supplies "
                "coordinates. Existing manual path records remain stored, while an "
                "automatic proposal does not bind them to the selected program."
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "actorPlacementId",
                    "loopMode",
                    "requiredRouteIds",
                    "forbiddenZoneIds",
                    "forbiddenRouteIds",
                ],
                "properties": {
                    "actorPlacementId": stable_id,
                    "movementProgramId": {"anyOf": [stable_id, {"type": "null"}]},
                    "orderedAnchorIds": stable_ids_20,
                    "orderedTargetPlacementIds": stable_ids_20,
                    "loopMode": {
                        "enum": ["one_way", "closed_loop", "out_and_return", "paired_lane_return", "task_cycle"]
                    },
                    "requiredRouteIds": {**stable_ids_20, "minItems": 0},
                    "forbiddenZoneIds": {**stable_ids_20, "minItems": 0},
                    "forbiddenRouteIds": {**stable_ids_20, "minItems": 0},
                    "playAfterProposal": {"type": "boolean"},
                },
                "oneOf": [
                    {"required": ["orderedAnchorIds"]},
                    {"required": ["orderedTargetPlacementIds"]},
                ],
            },
        },
        {
            "name": BUILD_ACTIVITY_SCENARIO_TOOL,
            "description": (
                "Load accepted journey IDs into shared Plan/3D playback. For a "
                "deterministic one-call browser continuation, existing movement "
                "program IDs may be supplied and are compiled and validated before "
                "playback. This is a read-only prototype presentation."
            ),
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prototypeMode", "scenarioLabel"],
                "properties": {
                    "journeySolutionIds": {
                        "type": "array", "maxItems": FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS, "uniqueItems": True,
                        "items": stable_id,
                    },
                    "movementProgramIds": {
                        "type": "array", "maxItems": FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS, "uniqueItems": True,
                        "items": stable_id,
                    },
                    "handoffResultIds": {
                        "type": "array", "maxItems": 20, "uniqueItems": True,
                        "items": stable_id,
                    },
                    "prototypeMode": {"const": True},
                    "scenarioLabel": {"type": "string", "minLength": 1, "maxLength": 120},
                },
                "anyOf": [
                    {"required": ["journeySolutionIds"]},
                    {"required": ["movementProgramIds"]},
                ],
            },
        },
    ]


__all__ = [
    "BUILD_ACTIVITY_SCENARIO_TOOL",
    "COMPARE_JOURNEY_ALTERNATIVES_TOOL",
    "COMPILE_NAVIGATION_SNAPSHOT_TOOL",
    "FACILITY_NAVIGATION_SAGE_CONTRACT_VERSION",
    "FACILITY_NAVIGATION_SAGE_QUALIFICATION",
    "NAVIGATION_READ_TOOL_NAMES",
    "NAVIGATION_TERMINAL_TOOL_NAMES",
    "OBSERVE_NAVIGATION_CONTEXT_TOOL",
    "PLAN_ACTOR_JOURNEY_TOOL",
    "PROPOSE_NAVIGATION_INTENT_TOOL",
    "VALIDATE_ACTOR_JOURNEY_TOOL",
    "classify_navigation_tool_intent",
    "compare_journey_summaries",
    "is_navigation_semantic_request",
    "navigation_action_mode",
    "navigation_agent_tool_specs",
    "navigation_context_summary",
    "navigation_deterministic_refusal",
]
