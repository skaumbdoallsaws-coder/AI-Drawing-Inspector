"""Deterministic intent boundary for Facility Layout motion playback.

The parser selects authored identities only. Geometry, vehicle behavior, and
validation remain owned by the routing and motion-package services.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .prototype_itinerary import (
    REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT,
    REFERENCE_COMPLETE_ACTIVITY_PRESET,
    REFERENCE_DOWNSTREAM_ACTIVITY_PRESET,
)
from .reference_finished_goods import (
    REFERENCE_FINISHED_GOODS_DISPATCH_PRESET,
    REFERENCE_FINISHED_GOODS_PRESETS,
    REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
)
from .reference_receiving import REFERENCE_RECEIVING_PUTAWAY_PRESET


FACILITY_MOTION_PLAYBACK_TOOL = "start_facility_motion_playback"
FACILITY_ACTIVITY_PLAYBACK_TOOL = "start_facility_activity_playback"
FACILITY_MOTION_PLAYBACK_QUALIFICATION = (
    "Playback replays revision-bound route-planner evidence. It does not prove "
    "traffic safety, regulatory compliance, throughput, congestion behavior, "
    "vehicle interaction, or continuous clearance."
)
FACILITY_ACTIVITY_PLAYBACK_QUALIFICATION = (
    "Prototype activity playback presents independently revision-bound route "
    "results on one shared clock. It does not simulate traffic, throughput, "
    "staffing, utilization, machine cycles, safety, or compliance."
)
FACILITY_REFERENCE_ACTIVITY_PRESET = "reference_candidate_navigation"
FACILITY_REFERENCE_LAYOUT_ID = "fl-reference-manual-20260812"

_SPACE = re.compile(r"\s+")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
_PROFILE = re.compile(
    rf"\b(?:vehicle\s+)?profile(?:\s+id)?\s+"
    rf"(?P<id>{_IDENTIFIER})\s+(?:at\s+)?revision\s+"
    r"(?P<revision>[0-9a-fA-F]{64})\b",
    re.IGNORECASE,
)
_PROFILE_ID = re.compile(
    rf"\b(?:vehicle\s+)?profile(?:\s+id)?\s+(?P<id>{_IDENTIFIER})\b",
    re.IGNORECASE,
)
_PROFILE_REVISION = re.compile(
    r"\b(?:profile\s+)?revision\s+(?P<revision>[0-9a-fA-F]+)\b",
    re.IGNORECASE,
)
_ROUTE_ID = re.compile(
    rf"\broute\s+id\s+(?P<id>{_IDENTIFIER})\b",
    re.IGNORECASE,
)
_VEHICLE_PLACEMENT = re.compile(
    rf"\b(?:vehicle\s+placement(?:\s+id)?|placement\s+id)\s+"
    rf"(?P<id>{_IDENTIFIER})\b",
    re.IGNORECASE,
)

_PLAYBACK_LANGUAGE = re.compile(
    r"\b(?:animate|animation|motion|playback|replay|watch|moving|drive|driving|"
    r"traverse|traversal|running)\b",
    re.IGNORECASE,
)
_VEHICLE_OR_ROUTE = re.compile(
    r"\b(?:forklift|fork\s*truck|lift\s*truck|vehicle|aisle|route|corridor|"
    r"traffic|crossing|network)\b",
    re.IGNORECASE,
)
_THROUGHPUT_CLAIM = re.compile(
    r"\b(?:throughput|capacity|pallets?\s+(?:an?|per)\s+hour|moves?\s+"
    r"(?:an?|per)\s+hour|cycle\s+time|units?\s+(?:an?|per)\s+hour)\b",
    re.IGNORECASE,
)
_SAFETY_OR_COMPLIANCE_CLAIM = re.compile(
    r"\b(?:safe|safely|safety|adequate|compliant|compliance|osha|nfpa|"
    r"fire\s+code|building\s+code|egress|regulatory|drivable|drivability)\b",
    re.IGNORECASE,
)
_SIMULATION_CLAIM = re.compile(
    r"\b(?:simulate|simulation|fleet|congestion|queue|queueing|queuing|"
    r"shift\s+change|vehicle\s+interaction|traffic\s+flow\s+rate)\b",
    re.IGNORECASE,
)
_CONTINUOUS_CLEARANCE_CLAIM = re.compile(
    r"\b(?:continuous|every\s+instant|at\s+every\s+point)\b[^.?!]{0,40}"
    r"\bclearance\b|\bclearance\b[^.?!]{0,40}\bcontinuous(?:ly)?\b",
    re.IGNORECASE,
)
_AUTHORED_TRAJECTORY = re.compile(
    r"(?:\b[xyz]\s*=\s*[-+]?\d|\bworld\s+(?:point|coordinate)|"
    r"\b(?:pose|heading|trajectory|waypoint)s?\s*(?:=|at|through|to)|"
    r"\b(?:route|move|drive|detour)\b[^.?!]{0,48}\b[xyz]\s*=)",
    re.IGNORECASE,
)
_AUTHORED_PHYSICAL_TIMING = re.compile(
    r"\b(?:drive|travel|vehicle|forklift)\b[^.?!]{0,50}"
    r"(?:\b\d+(?:\.\d+)?\s*(?:m/s|km/h|mph)\b|"
    r"\bin\s+\d+(?:\.\d+)?\s*(?:seconds?|minutes?)\b)",
    re.IGNORECASE,
)
_ACTIVITY_LANGUAGE = re.compile(
    r"\b(?:factory|facility|plant|shop[- ]floor)\s+activity\b|"
    r"\bactivity\s+(?:view|playback|presentation)\b|"
    r"\b(?:show|play|animate|watch|present|display)\b[^.?!]{0,50}"
    r"\b(?:vehicles?|forklifts?|people|operators?|mobile\s+equipment)\b"
    r"[^.?!]{0,90}\b(?:authored\s+)?(?:lanes?|aisles?|routes?)\b",
    re.IGNORECASE,
)
_REFERENCE_ACTIVITY_LANGUAGE = re.compile(
    r"\b(?:all|every)\s+(?:existing\s+)?(?:moving\s+objects?|mobile\s+actors?)\b|"
    r"\b(?:operators?|people)\b[^.?!]{0,48}\b(?:forklifts?|vehicles?)\b|"
    r"\b(?:movement|navigation)\s+(?:candidate\s+)?map\b",
    re.IGNORECASE,
)
_REFERENCE_DOWNSTREAM_ACTIVITY_LANGUAGE = re.compile(
    r"\b(?:inspection|packaging|finished\s+goods|downstream)\b"
    r"[^.?!]{0,140}\b(?:operators?|people|movement|activity|journeys?)\b|"
    r"\b(?:operators?|people|movement|activity|journeys?)\b"
    r"[^.?!]{0,140}\b(?:inspection|packaging|finished\s+goods|downstream)\b",
    re.IGNORECASE,
)
_REFERENCE_FINISHED_GOODS_ACTIVITY_LANGUAGE = re.compile(
    r"\bfinished\s+goods\b[^.?!]{0,220}"
    r"\b(?:forklift|pallet|rack|put[ -]?away|dispatch|shelf)\b|"
    r"\b(?:forklift|pallet|rack|put[ -]?away|dispatch|shelf)\b"
    r"[^.?!]{0,220}\bfinished\s+goods\b",
    re.IGNORECASE,
)
_REFERENCE_FINISHED_GOODS_DISPATCH_LANGUAGE = re.compile(
    r"\b(?:dispatch|retrieve|retrieval|pick\s+from\s+(?:the\s+)?shelf|"
    r"shelf\s+to\s+staging|outbound)\b",
    re.IGNORECASE,
)
_REFERENCE_RECEIVING_ACTIVITY_LANGUAGE = re.compile(
    r"\b(?:receiving|inbound)\b[^.?!]{0,220}"
    r"\b(?:forklift|pallet|rack|put[ -]?away|storage\s+bay|cross\s+aisle)\b|"
    r"\b(?:forklift|pallet|rack|put[ -]?away|storage\s+bay|cross\s+aisle)\b"
    r"[^.?!]{0,220}\b(?:receiving|inbound)\b",
    re.IGNORECASE,
)
_PROTOTYPE_LANGUAGE = re.compile(
    r"\b(?:prototype|demonstration|demo|illustrative|candidate|mockup)\b",
    re.IGNORECASE,
)
_MAXIMUM_ACTORS = re.compile(
    r"\b(?:up\s+to|maximum|max)\s+(?P<count>\d{1,2})\s+actors?\b",
    re.IGNORECASE,
)


def _routes(layout: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        route
        for route in layout.get("routes", [])
        if isinstance(route, Mapping)
        and str(route.get("routeId") or "").strip()
    ]


def _route_matches(
    text: str,
    routes: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    explicit = _ROUTE_ID.search(text)
    if explicit is not None:
        route_id = explicit.group("id")
        return [
            route
            for route in routes
            if str(route.get("routeId") or "").casefold()
            == route_id.casefold()
        ]
    lowered = text.casefold()
    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    for route in routes:
        label = str(route.get("label") or "").strip()
        if not label:
            continue
        match = re.search(
            r"(?<![a-z0-9])" + re.escape(label.casefold()) + r"(?![a-z0-9])",
            lowered,
        )
        if match is not None:
            candidates.append((match.start(), -len(label), route))
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2]["routeId"])))
    return [item[2] for item in candidates]


def _placement_exists(layout: Mapping[str, Any], placement_id: str) -> bool:
    return any(
        isinstance(item, Mapping)
        and str(item.get("placementId") or "") == placement_id
        for item in layout.get("placements", [])
    )


def motion_playback_tool_spec() -> dict[str, Any]:
    """Return the closed, coordinate-free browser presentation contract."""

    return {
        "name": FACILITY_MOTION_PLAYBACK_TOOL,
        "description": (
            "Replay one authored Facility Layout vehicle route using an exact "
            "revision-bound vehicle-profile ID and revision authorized by the "
            "current host mode. This is a read-only presentation. Never supply "
            "coordinates, poses, speeds, durations, inferred vehicle properties, "
            "or safety/compliance claims."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "route_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "vehicle_profile_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                },
                "vehicle_profile_revision": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "vehicle_placement_id": {
                    "type": ["string", "null"],
                    "minLength": 1,
                    "maxLength": 128,
                },
                "travel_direction": {
                    "type": "string",
                    "enum": ["forward", "reverse"],
                },
            },
            "required": [
                "route_id",
                "vehicle_profile_id",
                "vehicle_profile_revision",
                "travel_direction",
            ],
            "additionalProperties": False,
        },
    }


def activity_playback_tool_spec() -> dict[str, Any]:
    """Return the closed, coordinate-free multi-actor presentation contract."""

    return {
        "name": FACILITY_ACTIVITY_PLAYBACK_TOOL,
        "description": (
            "Present placed mobile actors on deterministic revision-bound candidate "
            "journeys using one shared display clock. The frozen manual reference may "
            "use its candidate inventory and explicit non-production vehicle profiles. "
    "Fixed machinery remains stationary. This is read-only and not a simulation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preset": {
                    "type": "string",
                    "enum": [
                        "mobile_actors_on_authored_routes",
                        REFERENCE_COMPLETE_ACTIVITY_PRESET,
                        FACILITY_REFERENCE_ACTIVITY_PRESET,
                        REFERENCE_DOWNSTREAM_ACTIVITY_PRESET,
                        *sorted(REFERENCE_FINISHED_GOODS_PRESETS),
                        REFERENCE_RECEIVING_PUTAWAY_PRESET,
                    ],
                },
                "prototype_mode": {"type": "boolean", "const": True},
                "maximum_actors": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 24,
                },
                "scenario_label": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                },
            },
            "required": [
                "preset",
                "prototype_mode",
                "maximum_actors",
                "scenario_label",
            ],
            "additionalProperties": False,
        },
    }


def parse_activity_playback_turn(
    message: str,
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify one multi-actor presentation request without inventing motion."""

    text = _SPACE.sub(" ", str(message or "")).strip()
    complete_request = bool(
        str(layout.get("layoutId") or "") == FACILITY_REFERENCE_LAYOUT_ID
        and _REFERENCE_ACTIVITY_LANGUAGE.search(text)
    )
    receiving_request = bool(
        str(layout.get("layoutId") or "") == FACILITY_REFERENCE_LAYOUT_ID
        and not complete_request
        and _REFERENCE_RECEIVING_ACTIVITY_LANGUAGE.search(text)
    )
    finished_goods_request = bool(
        str(layout.get("layoutId") or "") == FACILITY_REFERENCE_LAYOUT_ID
        and not receiving_request
        and _REFERENCE_FINISHED_GOODS_ACTIVITY_LANGUAGE.search(text)
    )
    downstream_request = bool(
        str(layout.get("layoutId") or "") == FACILITY_REFERENCE_LAYOUT_ID
        and not receiving_request
        and not finished_goods_request
        and _REFERENCE_DOWNSTREAM_ACTIVITY_LANGUAGE.search(text)
    )
    reference_request = bool(
        _REFERENCE_ACTIVITY_LANGUAGE.search(text)
        or downstream_request
        or finished_goods_request
        or receiving_request
    )
    if not text or (
        _ACTIVITY_LANGUAGE.search(text) is None and not reference_request
    ):
        return {"kind": "not_applicable"}
    if _THROUGHPUT_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_activity_throughput_authority_missing",
            "response": (
                "**Prototype activity playback cannot establish throughput, "
                "capacity, utilization, or cycle time.** Connect an approved flow "
                "model or measured operating study. Nothing changed."
            ),
        }
    if _SAFETY_OR_COMPLIANCE_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_activity_safety_authority_missing",
            "response": (
                "**Prototype activity playback cannot establish traffic safety or "
                "regulatory compliance.** Connect controlled traffic policy and "
                "acceptance criteria. Nothing changed."
            ),
        }
    if _SIMULATION_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_activity_simulation_unsupported",
            "response": (
                "**InspectorPro can present independent route traversals, but it "
                "does not simulate fleets, queues, congestion, interactions, "
                "staffing, or production behavior.** Nothing changed."
            ),
        }
    if _AUTHORED_TRAJECTORY.search(text) or _AUTHORED_PHYSICAL_TIMING.search(text):
        return {
            "kind": "refuse",
            "code": "facility_activity_model_trajectory_refused",
            "response": (
                "**Activity playback cannot accept chat-authored coordinates, "
                "poses, speeds, or durations.** It uses authored routes and the "
                "deterministic planner only. Nothing changed."
            ),
        }
    if _PROTOTYPE_LANGUAGE.search(text) is None:
        return {
            "kind": "ask",
            "code": "facility_activity_prototype_confirmation_required",
            "response": (
                "**Multi-actor activity is currently an explicit prototype "
                "presentation, not a production simulation.** Ask for a prototype "
                "activity view to continue; fixed machines without revision-bound "
                "kinematics will remain stationary. Nothing changed."
            ),
        }
    route_count = sum(
        isinstance(route, Mapping)
        and str(route.get("routeKind") or "")
        in {"forklift", "material", "operator", "pedestrian"}
        for route in layout.get("routes", [])
    )
    if route_count < 1:
        return {
            "kind": "ask",
            "code": "facility_activity_authored_routes_required",
            "response": (
                "**The active layout has no authored mobile-actor routes.** Create "
                "material or pedestrian routes before requesting activity playback. "
                "Nothing changed."
            ),
        }
    maximum_match = _MAXIMUM_ACTORS.search(text)
    maximum_actors = (
        int(maximum_match.group("count"))
        if maximum_match
        else 2 if receiving_request
        else 1 if finished_goods_request
        else 8 if downstream_request
        else REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT
        if complete_request
        else 20
    )
    if not 1 <= maximum_actors <= 24:
        return {
            "kind": "ask",
            "code": "facility_activity_actor_limit_invalid",
            "response": (
                "**Prototype activity supports between 1 and 24 actors.** Provide "
                "a maximum actor count in that range. Nothing changed."
            ),
        }
    use_reference_candidates = (
        complete_request
        and str(layout.get("layoutId") or "") == FACILITY_REFERENCE_LAYOUT_ID
    )
    finished_goods_preset = (
        REFERENCE_FINISHED_GOODS_DISPATCH_PRESET
        if _REFERENCE_FINISHED_GOODS_DISPATCH_LANGUAGE.search(text)
        else REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET
    )
    return {
        "kind": "build",
        "request": {
            "preset": (
                REFERENCE_RECEIVING_PUTAWAY_PRESET
                if receiving_request
                else finished_goods_preset
                if finished_goods_request
                else REFERENCE_DOWNSTREAM_ACTIVITY_PRESET
                if downstream_request
                else REFERENCE_COMPLETE_ACTIVITY_PRESET
                if use_reference_candidates
                else "mobile_actors_on_authored_routes"
            ),
            "prototypeMode": True,
            "maximumActors": maximum_actors,
            "scenarioLabel": (
                "Receiving pallet-to-rack cycles"
                if receiving_request
                else "Finished Goods dispatch cycle"
                if finished_goods_request
                and finished_goods_preset
                    == REFERENCE_FINISHED_GOODS_DISPATCH_PRESET
                else "Finished Goods put-away cycle"
                if finished_goods_request
                else "Downstream operator movement candidates"
                if downstream_request
                else "Complete reference movement"
                if use_reference_candidates
                else "Prototype factory activity"
            ),
        },
        "qualification": FACILITY_ACTIVITY_PLAYBACK_QUALIFICATION,
    }


def parse_motion_playback_turn(
    message: str,
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify one motion request without authoring geometry or behavior."""

    text = _SPACE.sub(" ", str(message or "")).strip()
    if not text:
        return {"kind": "not_applicable"}
    playback_context = bool(
        _PLAYBACK_LANGUAGE.search(text) and _VEHICLE_OR_ROUTE.search(text)
    )
    simulation_context = bool(
        _SIMULATION_CLAIM.search(text)
        and (_VEHICLE_OR_ROUTE.search(text) or _PLAYBACK_LANGUAGE.search(text))
    )
    motion_context = playback_context or simulation_context
    if motion_context and _THROUGHPUT_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_motion_throughput_authority_missing",
            "response": (
                "**Motion playback cannot establish route throughput or capacity.** "
                "Connect an approved flow model or measured operating study; no "
                "pallet rate, cycle time, or capacity was inferred. Nothing changed."
            ),
        }
    if motion_context and _SAFETY_OR_COMPLIANCE_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_motion_safety_authority_missing",
            "response": (
                "**Motion playback cannot establish traffic safety, drivability, or "
                "regulatory compliance.** Connect the applicable controlled policy "
                "and acceptance criteria; static route evidence is not an approval. "
                "Nothing changed."
            ),
        }
    if simulation_context:
        return {
            "kind": "refuse",
            "code": "facility_motion_simulation_unsupported",
            "response": (
                "**InspectorPro does not simulate fleets, congestion, queues, or "
                "vehicle interactions in this workflow.** It can replay one "
                "revision-bound deterministic route result at a time. Nothing changed."
            ),
        }
    if motion_context and _CONTINUOUS_CLEARANCE_CLAIM.search(text):
        return {
            "kind": "refuse",
            "code": "facility_motion_continuous_clearance_unsupported",
            "response": (
                "**I cannot claim continuous clearance between validated samples.** "
                "Playback reports clearance only at the published sampled positions "
                "and states their spacing. Nothing changed."
            ),
        }
    if motion_context and (
        _AUTHORED_TRAJECTORY.search(text)
        or _AUTHORED_PHYSICAL_TIMING.search(text)
    ):
        return {
            "kind": "refuse",
            "code": "facility_motion_model_trajectory_refused",
            "response": (
                "**I cannot accept chat-authored poses, coordinates, vehicle speed, "
                "or travel duration.** Name an authored route and an exact published "
                "vehicle-profile ID and revision; InspectorPro will plan and validate "
                "the trajectory. Nothing changed."
            ),
        }

    if not playback_context:
        return {"kind": "not_applicable"}

    routes = _routes(layout)
    matches = _route_matches(text, routes)
    if len(matches) > 1:
        return {
            "kind": "ask",
            "code": "facility_motion_route_ambiguous",
            "response": (
                "**I found more than one authored route in that request.** Name one "
                "exact route label or route ID for playback. Nothing changed."
            ),
        }
    if not matches:
        explicit_route = _ROUTE_ID.search(text)
        return {
            "kind": "ask",
            "code": (
                "facility_motion_route_not_found"
                if explicit_route is not None
                else "facility_motion_route_required"
            ),
            "response": (
                "**I need one exact authored route label or route ID for playback.** "
                "I will not infer a route from proximity or department names. Nothing "
                "changed."
            ),
        }
    route = matches[0]
    route_kind = str(route.get("routeKind") or "")
    if route_kind not in {"forklift", "material"}:
        return {
            "kind": "refuse",
            "code": "facility_motion_route_not_vehicle_traversable",
            "response": (
                "**The selected route is not authored as a vehicle-traversable "
                "route.** Choose a forklift or material route. Nothing changed."
            ),
        }

    profile = _PROFILE.search(text)
    if profile is None:
        partial_id = _PROFILE_ID.search(text)
        partial_revision = _PROFILE_REVISION.search(text)
        detail = (
            "The revision must be the exact 64-character published revision hash. "
            if partial_revision is not None
            and not _HASH.fullmatch(partial_revision.group("revision").casefold())
            else ""
        )
        return {
            "kind": "ask",
            "code": "facility_motion_vehicle_profile_required",
            "response": (
                "**I need the exact published vehicle-profile ID and 64-character "
                "revision for playback.** "
                + detail
                + (
                    "The profile ID is present, but its exact revision is missing. "
                    if partial_id is not None
                    else ""
                )
                + "InspectorPro will not infer vehicle footprint, turning radius, "
                "speed, or reverse policy. Nothing changed."
            ),
        }
    profile_id = profile.group("id")
    profile_revision = profile.group("revision").casefold()

    placement_match = _VEHICLE_PLACEMENT.search(text)
    vehicle_placement_id = (
        placement_match.group("id") if placement_match is not None else None
    )
    real_vehicle_language = re.search(
        r"\b(?:this|selected|actual|placed)\s+(?:forklift|vehicle)\b",
        text,
        re.IGNORECASE,
    )
    if real_vehicle_language is not None and vehicle_placement_id is None:
        return {
            "kind": "ask",
            "code": "facility_motion_vehicle_placement_required",
            "response": (
                "**A real placed vehicle requires its exact vehicle placement ID.** "
                "Provide that stable identity, or ask for a profile-derived proxy "
                "playback. Nothing changed."
            ),
        }
    if vehicle_placement_id is not None and not _placement_exists(
        layout, vehicle_placement_id
    ):
        return {
            "kind": "ask",
            "code": "facility_motion_vehicle_placement_not_found",
            "response": (
                "**That vehicle placement ID is not present in the active layout "
                "revision.** Select an existing placement or use a profile-derived "
                "proxy. Nothing changed."
            ),
        }

    reverse = re.search(
        r"\b(?:in\s+reverse|reverse\s+direction|backwards?|from\s+end\s+to\s+start)\b",
        text,
        re.IGNORECASE,
    ) is not None
    route_id = str(route["routeId"])
    route_label = str(route.get("label") or route_id)
    request: dict[str, Any] = {
        "routeId": route_id,
        "vehicleProfileRef": {
            "vehicleProfileId": profile_id,
            "vehicleProfileRevision": profile_revision,
        },
        "travelDirection": "reverse" if reverse else "forward",
    }
    if vehicle_placement_id is not None:
        request["vehiclePlacementId"] = vehicle_placement_id
    return {
        "kind": "build",
        "request": request,
        "routeLabel": route_label,
        "proxy": vehicle_placement_id is None,
        "qualification": FACILITY_MOTION_PLAYBACK_QUALIFICATION,
    }


__all__ = [
    "FACILITY_ACTIVITY_PLAYBACK_QUALIFICATION",
    "FACILITY_ACTIVITY_PLAYBACK_TOOL",
    "FACILITY_MOTION_PLAYBACK_QUALIFICATION",
    "FACILITY_MOTION_PLAYBACK_TOOL",
    "REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT",
    "REFERENCE_COMPLETE_ACTIVITY_PRESET",
    "REFERENCE_FINISHED_GOODS_DISPATCH_PRESET",
    "REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET",
    "REFERENCE_RECEIVING_PUTAWAY_PRESET",
    "activity_playback_tool_spec",
    "motion_playback_tool_spec",
    "parse_activity_playback_turn",
    "parse_motion_playback_turn",
]
