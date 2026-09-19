"""Coordinate-free circulation intent and deterministic aisle compilation.

Sage resolves authored route intent here. The compiler, not the model, owns
world coordinates and emits the existing validated Facility Layout operations.
"""

from __future__ import annotations

from copy import deepcopy
import heapq
import hashlib
import json
import math
import re
from typing import Any, Literal, Mapping, Sequence

try:
    from shapely.errors import GEOSException
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    from shapely.prepared import prep
except ImportError:  # pragma: no cover - deployment preflight owns this failure.
    GEOSException = RuntimeError
    LineString = None
    Point = None
    Polygon = None
    box = None
    unary_union = None
    prep = None

from .canonical import (
    canonicalize_layout,
    layout_revision,
    trusted_canonical_layout_revision,
)
from .operations import apply_facility_layout_operations
from .routing import plan_forklift_route


G2_FACILITY_CIRCULATION_TOOL = "generate_facility_circulation_draft"
G2_CIRCULATION_SCOPE = "primary_circulation"
G2_ROUTE_KINDS = frozenset({"material", "forklift", "pedestrian"})
G2_DIRECTIONS = frozenset({"one_way", "two_way"})
G2_MAXIMUM_WAYPOINTS = 50
G2_COORDINATE_TOLERANCE_METERS = 1e-6
G21_CONFLICT_SCOPE = "mixed_traffic"
G21_ADJUSTMENT_MODES = frozenset({"auto_shortest", "pedestrian", "material"})
G21_GEOMETRY_EPSILON_METERS = 1e-7
G22_OBSTACLE_SCOPE = "static_geometry"
G22_MAXIMUM_OBSTACLES = 5000
G22_MAXIMUM_CONTEXT_BYTES = 1_048_576
G22_MAXIMUM_VEHICLE_GRID_CELLS_PER_AXIS = 120
G23_NETWORK_SCOPE = "route_network"
G22_PROTECTED_MARKING_TERMS = frozenset(
    {
        "egress",
        "exit_route",
        "keep_clear",
        "no_entry",
        "restricted",
        "safety_boundary",
    }
)
G22_PROTECTED_ZONE_TERMS = frozenset(
    {
        "exclusion",
        "egress",
        "keep_clear",
        "no_entry",
        "restricted",
        "safety",
        "safety_restricted",
    }
)

CirculationTurnKind = Literal[
    "build",
    "ask",
    "refuse",
    "read_only",
    "not_applicable",
]

_SPACE = re.compile(r"\s+")
_CIRCULATION_NOUN = re.compile(
    r"\b(?:aisles?|routes?|lanes?|walkways?|paths?|corridors?|detours?|"
    r"circulation|material\s+flow)\b",
    re.IGNORECASE,
)
_MUTATION_VERB = re.compile(
    r"\b(?:add|build|create|draw|install|make|mark|put|route|run|connect|"
    r"link|need|want|change|edit|update|resize|widen|narrow|set|reduce|"
    r"increase|reroute|re-route|avoid|detour)\w*\b",
    re.IGNORECASE,
)
_NEGATED_ACTION = re.compile(
    r"\b(?:do\s+not|don't|dont|without)\s+(?:add|build|create|draw|"
    r"change|edit|update|route|run|connect)\b|\bjust\s+(?:explain|describe)\b",
    re.IGNORECASE,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:what\s+if|what\s+would\s+happen\s+if|hypothetical(?:ly)?|suppose|"
    r"(?:would|could)\s+(?:this|that|it|an?|the|adding|building|creating))\b",
    re.IGNORECASE,
)
_READ_QUESTION = re.compile(
    r"^\s*(?:what|which|where|how|why|does|do|is|are|was|were|has|have)\b",
    re.IGNORECASE,
)
_CODE_POLICY = re.compile(
    r"\b(?:fire|egress|code|required\s+by\s+code|regulation|regulatory|"
    r"osha|nfpa)\b",
    re.IGNORECASE,
)
_COORDINATE = re.compile(
    r"(?:\b[xyz]\s*[=:]\s*-?\d|\bcoordinates?\b|\bworld\s+point\b|"
    r"\bfrom\s*\(\s*-?\d|\bto\s*\(\s*-?\d)",
    re.IGNORECASE,
)
_WIDTH = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?|one|two|three|four|five|six|seven|"
    r"eight|nine|ten|eleven|twelve)(?:\s*-\s*|\s*)"
    r"(?P<unit>mm|millimet(?:er|re)s?|m|met(?:er|re)s?|ft|feet|foot|"
    r"in|inch(?:es)?)(?:\s*-\s*wide|\s+wide)?\b",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"\b(?:that|this|the|same|last|previous|recent)\s+"
    r"(?:aisle|route|lane|walkway|path|corridor)\b",
    re.IGNORECASE,
)
_EXPLICIT_ROUTE_LABEL = re.compile(
    r"\b(?:aisle|route|lane|walkway|path|corridor)\s+named\s+"
    r"(?P<label>.+?)\s+from\b",
    re.IGNORECASE,
)
_DIRECTION_ONE = re.compile(
    r"\bone[-\s]?way\b|\bunidirectional\b|\bsingle[-\s]?direction\b",
    re.IGNORECASE,
)
_DIRECTION_TWO = re.compile(
    r"\btwo[-\s]?way\b|\bbidirectional\b|\bboth\s+directions?\b",
    re.IGNORECASE,
)
_CONFLICT_NOUN = re.compile(
    r"\b(?:conflicts?|crossings?|overlaps?|intersections?|shared\s+segments?)\b",
    re.IGNORECASE,
)
_CONFLICT_RESOLUTION = re.compile(
    r"\b(?:separate|resolve|remove|eliminate|avoid|reroute|re-route)\w*\b",
    re.IGNORECASE,
)
_MIXED_TRAFFIC = re.compile(
    r"\b(?:mixed\s+traffic|pedestrian(?:s|\s+walkways?)?.{0,50}forklifts?|"
    r"forklifts?.{0,50}pedestrian(?:s|\s+walkways?)?)\b",
    re.IGNORECASE,
)
_OBSTACLE_NOUN = re.compile(
    r"\b(?:obstacles?|machines?|equipment|columns?|walls?|doors?|docks?|"
    r"keep[-\s]?clear|restricted(?:\s+(?:area|region|zone))?|no[-\s]?entry|"
    r"blocked\s+(?:area|region|zone)|static\s+geometry)\b",
    re.IGNORECASE,
)
_OBSTACLE_ANALYSIS = re.compile(
    r"\b(?:hit|hits|hitting|intersect|intersects|cross|crosses|overlap|"
    r"overlaps|collide|collides|blocked|conflict|conflicts|clear\s+of|"
    r"avoid|avoids)\b",
    re.IGNORECASE,
)
_TURNING_REQUIREMENT = re.compile(
    r"\b(?:turning\s+radius|swept\s+(?:path|volume|envelope)|vehicle\s+profile)\b",
    re.IGNORECASE,
)
_VEHICLE_PROFILE_REF = re.compile(
    r"\bvehicle\s+profile\s+(?P<identifier>[A-Za-z0-9][A-Za-z0-9._:-]{0,127})"
    r"(?:\s+(?:at|revision|rev\.?)[\s:]+(?P<revision>[0-9a-f]{64}))?\b",
    re.IGNORECASE,
)
_ROUTING_AUTHORITY_CONTEXT = re.compile(
    r"\b(?:aisles?|routes?|lanes?|walkways?|paths?|corridors?|detours?|"
    r"rerout\w*|circulation|clearance|separation|turning|forklifts?)\b",
    re.IGNORECASE,
)
_UNBOUND_VEHICLE_AUTHORITY = re.compile(
    r"\b(?:safe|suitable|compatible)\s+for\b.{0,60}\bforklift\b|"
    r"\b(?:turning\s+radius|swept\s+(?:path|volume|envelope))\b.{0,80}"
    r"\b(?:any|(?:a\s+)?typical)\s+(?:warehouse\s+)?forklift\b",
    re.IGNORECASE,
)
_NETWORK_NOUN = re.compile(
    r"\b(?:network|connectivity|connected\s+components?|reachable|reachability|"
    r"unreachable|disconnected|unconnected|dead[-\s]?ends?|terminals?|junctions?)\b",
    re.IGNORECASE,
)
_NETWORK_REACHABILITY = re.compile(
    r"\b(?:can|could|may|does|do|is|are|which|what|where|show|list)\b.{0,80}"
    r"\b(?:reach|reachable|travel|move|drive|walk|get|go|connect(?:ed)?)\b",
    re.IGNORECASE,
)
_CROSSING_MARKING = re.compile(
    r"\b(?:crosswalk|pedestrian\s+crossing|marked\s+crossing|crossing\s+marking)\b",
    re.IGNORECASE,
)
_CROSSING_COVERAGE = re.compile(
    r"\b(?:marked|unmarked|crosswalk\s+coverage|crossing\s+coverage)\b",
    re.IGNORECASE,
)
_CROSSING_DIMENSIONS = re.compile(
    r"\b(?P<width>\d+(?:\.\d+)?)\s*"
    r"(?P<width_unit>mm|millimet(?:er|re)s?|m|met(?:er|re)s?|ft|feet|foot|"
    r"in|inch(?:es)?)?\s*(?:x|by)\s*"
    r"(?P<depth>\d+(?:\.\d+)?)\s*"
    r"(?P<depth_unit>mm|millimet(?:er|re)s?|m|met(?:er|re)s?|ft|feet|foot|"
    r"in|inch(?:es)?)\b",
    re.IGNORECASE,
)
_CROSSING_DIMENSIONS_WORDS = re.compile(
    r"\b(?P<width>\d+(?:\.\d+)?)\s*"
    r"(?P<width_unit>mm|millimet(?:er|re)s?|m|met(?:er|re)s?|ft|feet|foot|"
    r"in|inch(?:es)?)\s+wide\s+(?:and|by)\s+"
    r"(?P<depth>\d+(?:\.\d+)?)\s*"
    r"(?P<depth_unit>mm|millimet(?:er|re)s?|m|met(?:er|re)s?|ft|feet|foot|"
    r"in|inch(?:es)?)\s+(?:deep|long)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_OPERATIONAL_CLAIM = re.compile(
    r"\b(?:safe(?:st|ty)?\s+(?:crossing|route|network)|traffic\s+capacity|"
    r"throughput|congestion|travel\s+time|stopping\s+distance|"
    r"operational(?:ly)?\s+optimal|optimal\s+(?:route|network))\b",
    re.IGNORECASE,
)
_SAFETY_ADEQUACY_TERM = re.compile(
    r"\b(?:safe(?:ty)?|adequate|compliant|compliance)\b",
    re.IGNORECASE,
)
_POLICY_CONFORMANCE = re.compile(
    r"\b(?:comply|complies|compliant|meet|meets|satisfy|satisfies)\b",
    re.IGNORECASE,
)
_FACILITY_OPERATIONAL_CONTEXT = re.compile(
    r"\b(?:facility|plant|layout|floor|aisle|route|network|crossing|crosswalk|"
    r"walkway|path|corridor|circulation)\b",
    re.IGNORECASE,
)

_NUMBER_WORDS = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
}


class FacilityCirculationError(ValueError):
    """Fail-closed circulation intent or deterministic geometry error."""

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


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{hashlib.sha256(_canonical_bytes(value)).hexdigest()[:24]}"


def _clean_label(value: Any, field: str, maximum: int = 160) -> str:
    text = _SPACE.sub(" ", str(value or "")).strip()
    if not text or len(text) > maximum:
        raise FacilityCirculationError(
            "facility_circulation_label_invalid",
            f"{field} must contain between 1 and {maximum} characters.",
        )
    return text


def _finite_positive(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise FacilityCirculationError(
            "facility_circulation_number_invalid",
            f"{field} must be a positive number.",
        )
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise FacilityCirculationError(
            "facility_circulation_number_invalid",
            f"{field} must be a positive number.",
        ) from exc
    if not math.isfinite(result) or result <= 0:
        raise FacilityCirculationError(
            "facility_circulation_number_invalid",
            f"{field} must be a positive number.",
        )
    return result


def _unit(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    aliases = {
        "m": "m",
        "meter": "m",
        "meters": "m",
        "metre": "m",
        "metres": "m",
        "mm": "mm",
        "millimeter": "mm",
        "millimeters": "mm",
        "millimetre": "mm",
        "millimetres": "mm",
        "ft": "ft",
        "foot": "ft",
        "feet": "ft",
        "in": "in",
        "inch": "in",
        "inches": "in",
    }
    result = aliases.get(normalized)
    if result is None:
        raise FacilityCirculationError(
            "facility_circulation_unit_invalid",
            "Circulation width unit must be m, mm, ft, or in.",
        )
    return result


def _to_meters(value: float, source_unit: str) -> float:
    factor = {"m": 1.0, "mm": 0.001, "ft": 0.3048, "in": 0.0254}[
        source_unit
    ]
    return float(value) * factor


def _zone_records(layout: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = []
    for raw in layout.get("zones", []):
        if not isinstance(raw, Mapping):
            continue
        zone_id = str(raw.get("zoneId") or "").strip()
        label = _SPACE.sub(" ", str(raw.get("label") or "")).strip()
        boundary = raw.get("boundary")
        if not zone_id or not label or not isinstance(boundary, list) or len(boundary) < 3:
            continue
        try:
            xs = [float(point["x"]) for point in boundary]
            zs = [float(point["z"]) for point in boundary]
        except (KeyError, TypeError, ValueError):
            continue
        records.append(
            {
                "zoneId": zone_id,
                "label": label,
                "key": label.casefold(),
                "minimumX": min(xs),
                "maximumX": max(xs),
                "minimumZ": min(zs),
                "maximumZ": max(zs),
                "centerX": (min(xs) + max(xs)) / 2.0,
                "centerZ": (min(zs) + max(zs)) / 2.0,
            }
        )
    return records


def _positioned_zone_labels(
    message: str,
    zones: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int, str]]:
    lowered = message.casefold()
    matches: list[tuple[int, int, int, str]] = []
    for zone in zones:
        label = str(zone["label"])
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(label.casefold()) + r"(?![a-z0-9])"
        )
        found = pattern.search(lowered)
        if found:
            matches.append((found.start(), found.end(), -len(label), label))
    matches.sort(key=lambda item: (item[0], item[2], item[1], item[3].casefold()))
    selected: list[tuple[int, int, str]] = []
    for start, end, _, label in matches:
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in selected):
            continue
        selected.append((start, end, label))
    return selected


def _route_label_order(
    message: str,
    zones: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Resolve source/target grammar while retaining authored via order."""

    lowered = message.casefold()
    positioned = _positioned_zone_labels(message, zones)
    if len(positioned) < 2:
        return [item[2] for item in positioned]
    from_match = re.search(r"\bfrom\b", lowered)
    to_matches = list(re.finditer(r"\bto\b", lowered))
    source = None
    target = None
    if from_match is not None:
        source = next(
            (
                label
                for position, _, label in positioned
                if position >= from_match.end()
            ),
            None,
        )
    if to_matches:
        for token in to_matches:
            candidate = next(
                (
                    label
                    for position, _, label in positioned
                    if position >= token.end()
                ),
                None,
            )
            if candidate and candidate != source:
                target = candidate
    source = source or positioned[0][2]
    if target is None:
        via_token = re.search(
            r"\b(?:via|through|passing\s+through)\b",
            lowered,
        )
        before_via = [
            label
            for position, _, label in positioned
            if via_token is None or position < via_token.start()
        ]
        if len(before_via) >= 2:
            target = before_via[1]
    target = target or positioned[-1][2]
    via = [
        label
        for _, _, label in positioned
        if label.casefold() not in {source.casefold(), target.casefold()}
    ]
    return [source, *via, target]


def _route_kind(message: str) -> str | None:
    lowered = message.casefold()
    if re.search(r"\b(?:forklift|fork\s*truck|lift\s*truck|vehicle)\b", lowered):
        return "forklift"
    if re.search(r"\b(?:pedestrian|people|personnel|walking|walkway|foot\s*traffic)\b", lowered):
        return "pedestrian"
    if re.search(r"\b(?:material|pallet|part|product|goods|flow)\b", lowered):
        return "material"
    return None


def _width_from_message(message: str) -> tuple[float, str] | None:
    match = _WIDTH.search(message)
    if match is None:
        return None
    source_unit = _unit(match.group("unit"))
    raw_value = match.group("value").casefold()
    value = _NUMBER_WORDS.get(raw_value, raw_value)
    return _finite_positive(value, "width"), source_unit


def _crossing_dimensions_from_message(
    message: str,
) -> tuple[float, float, str, str] | None:
    match = _CROSSING_DIMENSIONS.search(message)
    if match is None:
        match = _CROSSING_DIMENSIONS_WORDS.search(message)
    if match is None:
        return None
    width_unit = _unit(match.group("width_unit") or match.group("depth_unit"))
    depth_unit = _unit(match.group("depth_unit"))
    return (
        _finite_positive(match.group("width"), "crossing width"),
        _finite_positive(match.group("depth"), "crossing depth"),
        width_unit,
        depth_unit,
    )


def circulation_tool_spec() -> dict[str, Any]:
    """Return the closed, coordinate-free browser tool contract."""

    return {
        "name": G2_FACILITY_CIRCULATION_TOOL,
        "description": (
            "Add or amend one unsaved Facility Layout circulation aisle, resolve "
            "mixed pedestrian/material geometric conflicts, or reroute one generated "
            "aisle around revision-bound static obstacles, or mark one exact mixed-"
            "traffic point crossing on the active generated "
            "draft. Supply semantic intent only. Never supply coordinates, route "
            "points, obstacle polygons, or unverified policy values; InspectorPro "
            "computes and validates them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "edit_recent",
                        "resolve_conflicts",
                        "avoid_obstacles",
                        "add_crossing",
                    ],
                },
                "route_kind": {
                    "type": ["string", "null"],
                    "enum": [None, *sorted(G2_ROUTE_KINDS)],
                },
                "width": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "source_unit": {
                    "type": ["string", "null"],
                    "enum": [None, "m", "mm", "ft", "in"],
                },
                "source_department": {"type": ["string", "null"]},
                "target_department": {"type": ["string", "null"]},
                "via_departments": {
                    "type": "array",
                    "maxItems": G2_MAXIMUM_WAYPOINTS,
                    "items": {"type": "string"},
                },
                "direction": {
                    "type": ["string", "null"],
                    "enum": [None, *sorted(G2_DIRECTIONS)],
                },
                "label": {"type": ["string", "null"]},
                "conflict_scope": {
                    "type": ["string", "null"],
                    "enum": [None, G21_CONFLICT_SCOPE],
                },
                "minimum_separation": {
                    "type": ["number", "null"],
                    "minimum": 0,
                },
                "separation_unit": {
                    "type": ["string", "null"],
                    "enum": [None, "m", "mm", "ft", "in"],
                },
                "preserve_departments": {"type": ["boolean", "null"]},
                "adjust_route_kind": {
                    "type": ["string", "null"],
                    "enum": [None, *sorted(G21_ADJUSTMENT_MODES)],
                },
                "obstacle_scope": {
                    "type": ["string", "null"],
                    "enum": [None, G22_OBSTACLE_SCOPE],
                },
                "minimum_clearance": {
                    "type": ["number", "null"],
                    "minimum": 0,
                },
                "clearance_unit": {
                    "type": ["string", "null"],
                    "enum": [None, "m", "mm", "ft", "in"],
                },
                "preserve_route_identity": {"type": ["boolean", "null"]},
                "route_id": {"type": ["string", "null"]},
                "vehicle_profile_id": {"type": ["string", "null"]},
                "vehicle_profile_revision": {"type": ["string", "null"]},
                "allow_reverse": {"type": ["boolean", "null"]},
                "network_scope": {
                    "type": ["string", "null"],
                    "enum": [None, G23_NETWORK_SCOPE],
                },
                "crossing_route_ids": {
                    "type": "array",
                    "maxItems": 2,
                    "items": {"type": "string"},
                },
                "crossing_width": {
                    "type": ["number", "null"],
                    "exclusiveMinimum": 0,
                },
                "crossing_depth": {
                    "type": ["number", "null"],
                    "exclusiveMinimum": 0,
                },
                "crossing_width_unit": {
                    "type": ["string", "null"],
                    "enum": [None, "m", "mm", "ft", "in"],
                },
                "crossing_depth_unit": {
                    "type": ["string", "null"],
                    "enum": [None, "m", "mm", "ft", "in"],
                },
                "preserve_routes": {"type": ["boolean", "null"]},
                "execution_mode": {
                    "type": "string",
                    "enum": ["authorized_draft_run"],
                },
            },
            "required": [
                "action",
                "route_kind",
                "width",
                "source_unit",
                "source_department",
                "target_department",
                "via_departments",
                "direction",
                "label",
                "conflict_scope",
                "minimum_separation",
                "separation_unit",
                "preserve_departments",
                "adjust_route_kind",
                "obstacle_scope",
                "minimum_clearance",
                "clearance_unit",
                "preserve_route_identity",
                "route_id",
                "vehicle_profile_id",
                "vehicle_profile_revision",
                "allow_reverse",
                "network_scope",
                "crossing_route_ids",
                "crossing_width",
                "crossing_depth",
                "crossing_width_unit",
                "crossing_depth_unit",
                "preserve_routes",
                "execution_mode",
            ],
            "additionalProperties": False,
        },
    }


def normalize_circulation_request(
    request: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {
        "action",
        "route_kind",
        "width",
        "source_unit",
        "source_department",
        "target_department",
        "via_departments",
        "direction",
        "label",
        "conflict_scope",
        "minimum_separation",
        "separation_unit",
        "preserve_departments",
        "adjust_route_kind",
        "obstacle_scope",
        "minimum_clearance",
        "clearance_unit",
        "preserve_route_identity",
        "route_id",
        "vehicle_profile_id",
        "vehicle_profile_revision",
        "allow_reverse",
        "network_scope",
        "crossing_route_ids",
        "crossing_width",
        "crossing_depth",
        "crossing_width_unit",
        "crossing_depth_unit",
        "preserve_routes",
        "execution_mode",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise FacilityCirculationError(
            "facility_circulation_unknown_fields",
            "Circulation intent contains unsupported fields.",
            details={"fields": unknown},
        )
    action = str(request.get("action") or "").strip()
    if action not in {
        "create",
        "edit_recent",
        "resolve_conflicts",
        "avoid_obstacles",
        "add_crossing",
    }:
        raise FacilityCirculationError(
            "facility_circulation_action_invalid",
            "Circulation action is unsupported.",
        )
    if action == "add_crossing":
        if str(request.get("network_scope") or "") != G23_NETWORK_SCOPE:
            raise FacilityCirculationError(
                "facility_circulation_network_scope_invalid",
                "Crossing creation currently supports route_network only.",
            )
        if request.get("preserve_departments") is not True:
            raise FacilityCirculationError(
                "facility_circulation_department_preservation_required",
                "Crossing creation must preserve department geometry.",
            )
        if request.get("preserve_routes") is not True:
            raise FacilityCirculationError(
                "facility_circulation_route_preservation_required",
                "Crossing creation must preserve every route.",
            )
        route_ids = request.get("crossing_route_ids")
        if (
            not isinstance(route_ids, list)
            or len(route_ids) != 2
            or len({str(item) for item in route_ids}) != 2
        ):
            raise FacilityCirculationError(
                "facility_circulation_crossing_pair_required",
                "Crossing creation requires exactly two distinct route IDs.",
            )
        route_ids = sorted(
            _clean_label(item, "crossing_route_id", 128) for item in route_ids
        )
        width_value = _finite_positive(
            request.get("crossing_width"), "crossing_width"
        )
        depth_value = _finite_positive(
            request.get("crossing_depth"), "crossing_depth"
        )
        width_unit = _unit(request.get("crossing_width_unit"))
        depth_unit = _unit(request.get("crossing_depth_unit"))
        width_meters = _to_meters(width_value, width_unit)
        depth_meters = _to_meters(depth_value, depth_unit)
        if max(width_meters, depth_meters) > 1000:
            raise FacilityCirculationError(
                "facility_circulation_crossing_size_out_of_bounds",
                "Crossing dimensions may not exceed 1000 meters.",
            )
        network = analyze_primary_circulation_network(layout)
        candidates = [
            item
            for item in network["crossings"]
            if sorted(item["routeIds"]) == route_ids
            and item["intersectionType"] == "point"
            and item["mixedPedestrianMaterialTraffic"] is True
        ]
        if len(candidates) != 1:
            raise FacilityCirculationError(
                "facility_circulation_crossing_ambiguous",
                "The selected routes must have exactly one mixed-traffic point crossing.",
                details={"routeIds": route_ids, "candidateCount": len(candidates)},
            )
        candidate = candidates[0]
        if candidate["crosswalkCoverageStatus"] == "marked":
            raise FacilityCirculationError(
                "facility_circulation_crossing_already_marked",
                "The selected point crossing already has a crosswalk marking.",
                details={"crossingId": candidate["crossingId"]},
            )
        label = request.get("label")
        if label is not None:
            label = _clean_label(label, "label")
        return {
            "scope": G2_CIRCULATION_SCOPE,
            "action": action,
            "routeKind": None,
            "sourceWidth": None,
            "sourceUnit": None,
            "widthMeters": None,
            "sourceDepartment": None,
            "targetDepartment": None,
            "viaDepartments": [],
            "direction": None,
            "label": label,
            "executionMode": "authorized_draft_run",
            "areaAccounting": "overlay",
            "widthAuthority": None,
            "networkScope": G23_NETWORK_SCOPE,
            "crossingRouteIds": route_ids,
            "crossingId": candidate["crossingId"],
            "crossingPosition": deepcopy(candidate["position"]),
            "crossingWidth": width_value,
            "crossingDepth": depth_value,
            "crossingWidthUnit": width_unit,
            "crossingDepthUnit": depth_unit,
            "crossingWidthMeters": width_meters,
            "crossingDepthMeters": depth_meters,
            "crossingDimensionAuthority": "user_authored",
            "crossingPositionAuthority": "derived_route_centerline_intersection",
            "preserveDepartments": True,
            "preserveRoutes": True,
        }
    if action == "resolve_conflicts":
        if str(request.get("conflict_scope") or "") != G21_CONFLICT_SCOPE:
            raise FacilityCirculationError(
                "facility_circulation_conflict_scope_invalid",
                "Conflict resolution currently supports mixed_traffic only.",
            )
        if request.get("preserve_departments") is not True:
            raise FacilityCirculationError(
                "facility_circulation_department_preservation_required",
                "Conflict resolution must preserve department geometry.",
            )
        adjustment_mode = str(
            request.get("adjust_route_kind") or "auto_shortest"
        )
        if adjustment_mode not in G21_ADJUSTMENT_MODES:
            raise FacilityCirculationError(
                "facility_circulation_adjustment_mode_invalid",
                "Conflict resolution adjustment must be auto_shortest, pedestrian, or material.",
            )
        raw_separation = request.get("minimum_separation")
        if raw_separation is None:
            separation_meters = 0.0
            separation_unit = None
            separation_value = None
            separation_authority = "geometric_non_overlap_only"
        else:
            if isinstance(raw_separation, bool):
                raise FacilityCirculationError(
                    "facility_circulation_number_invalid",
                    "minimum_separation must be zero or a positive number.",
                )
            try:
                separation_value = float(raw_separation)
            except (TypeError, ValueError) as exc:
                raise FacilityCirculationError(
                    "facility_circulation_number_invalid",
                    "minimum_separation must be zero or a positive number.",
                ) from exc
            if not math.isfinite(separation_value) or separation_value < 0:
                raise FacilityCirculationError(
                    "facility_circulation_number_invalid",
                    "minimum_separation must be zero or a positive number.",
                )
            separation_unit = _unit(request.get("separation_unit"))
            separation_meters = _to_meters(separation_value, separation_unit)
            separation_authority = "user_authored"
        return {
            "scope": G2_CIRCULATION_SCOPE,
            "action": action,
            "routeKind": None,
            "sourceWidth": None,
            "sourceUnit": None,
            "widthMeters": None,
            "sourceDepartment": None,
            "targetDepartment": None,
            "viaDepartments": [],
            "direction": None,
            "label": None,
            "executionMode": "authorized_draft_run",
            "areaAccounting": "overlay",
            "widthAuthority": None,
            "conflictScope": G21_CONFLICT_SCOPE,
            "minimumSeparation": separation_value,
            "separationUnit": separation_unit,
            "minimumSeparationMeters": separation_meters,
            "separationAuthority": separation_authority,
            "preserveDepartments": True,
            "adjustRouteKind": adjustment_mode,
        }
    if action == "avoid_obstacles":
        if str(request.get("obstacle_scope") or "") != G22_OBSTACLE_SCOPE:
            raise FacilityCirculationError(
                "facility_circulation_obstacle_scope_invalid",
                "Obstacle-aware routing currently supports static_geometry only.",
            )
        if request.get("preserve_departments") is not True:
            raise FacilityCirculationError(
                "facility_circulation_department_preservation_required",
                "Obstacle-aware routing must preserve department geometry.",
            )
        if request.get("preserve_route_identity") is not True:
            raise FacilityCirculationError(
                "facility_circulation_route_identity_required",
                "Obstacle-aware routing must preserve route identity.",
            )
        raw_clearance = request.get("minimum_clearance")
        if raw_clearance is None:
            clearance_value = None
            clearance_unit = None
            clearance_meters = 0.0
            clearance_authority = "geometric_non_overlap_only"
        else:
            if isinstance(raw_clearance, bool):
                raise FacilityCirculationError(
                    "facility_circulation_number_invalid",
                    "minimum_clearance must be zero or a positive number.",
                )
            try:
                clearance_value = float(raw_clearance)
            except (TypeError, ValueError) as exc:
                raise FacilityCirculationError(
                    "facility_circulation_number_invalid",
                    "minimum_clearance must be zero or a positive number.",
                ) from exc
            if not math.isfinite(clearance_value) or clearance_value < 0:
                raise FacilityCirculationError(
                    "facility_circulation_number_invalid",
                    "minimum_clearance must be zero or a positive number.",
                )
            clearance_unit = _unit(request.get("clearance_unit"))
            clearance_meters = _to_meters(clearance_value, clearance_unit)
            clearance_authority = "user_authored"
        routes = [
            item
            for item in layout.get("routes", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("extensions"), Mapping)
            and isinstance(item["extensions"].get("facilityAisle"), Mapping)
        ]
        requested_route_id = str(request.get("route_id") or "").strip()
        if requested_route_id:
            route = next(
                (
                    item
                    for item in routes
                    if str(item.get("routeId") or "") == requested_route_id
                ),
                None,
            )
            if route is None:
                raise FacilityCirculationError(
                    "facility_circulation_route_not_found",
                    "The requested generated route is not in the active draft.",
                    details={"routeId": requested_route_id},
                )
        elif routes:
            route = routes[-1]
            requested_route_id = str(route.get("routeId") or "")
        else:
            raise FacilityCirculationError(
                "facility_circulation_recent_route_missing",
                "There is no active generated aisle to reroute.",
            )
        vehicle_id = str(request.get("vehicle_profile_id") or "").strip()
        vehicle_revision = str(
            request.get("vehicle_profile_revision") or ""
        ).strip().lower()
        if bool(vehicle_id) != bool(vehicle_revision):
            raise FacilityCirculationError(
                "facility_circulation_vehicle_profile_incomplete",
                "A vehicle profile ID and published revision are both required.",
            )
        if vehicle_revision and re.fullmatch(r"[0-9a-f]{64}", vehicle_revision) is None:
            raise FacilityCirculationError(
                "facility_circulation_vehicle_profile_invalid",
                "Vehicle profile revision must be a canonical revision hash.",
            )
        route_kind = _aisle_kind_for_route(route)
        if vehicle_id and route_kind != "forklift":
            raise FacilityCirculationError(
                "facility_circulation_vehicle_profile_route_mismatch",
                "Vehicle profiles may be applied only to forklift routes.",
            )
        allow_reverse = request.get("allow_reverse")
        if allow_reverse is not None and not isinstance(allow_reverse, bool):
            raise FacilityCirculationError(
                "facility_circulation_reverse_policy_invalid",
                "allow_reverse must be true, false, or omitted.",
            )
        return {
            "scope": G2_CIRCULATION_SCOPE,
            "action": action,
            "routeKind": route_kind,
            "sourceWidth": None,
            "sourceUnit": None,
            "widthMeters": float(route.get("corridorWidth") or 0.0),
            "sourceDepartment": None,
            "targetDepartment": None,
            "viaDepartments": [],
            "direction": None,
            "label": None,
            "executionMode": "authorized_draft_run",
            "areaAccounting": "overlay",
            "widthAuthority": None,
            "obstacleScope": G22_OBSTACLE_SCOPE,
            "minimumClearance": clearance_value,
            "clearanceUnit": clearance_unit,
            "minimumClearanceMeters": clearance_meters,
            "clearanceAuthority": clearance_authority,
            "preserveDepartments": True,
            "preserveRouteIdentity": True,
            "routeId": requested_route_id,
            "vehicleProfileId": vehicle_id or None,
            "vehicleProfileRevision": vehicle_revision or None,
            "allowReverse": allow_reverse,
        }
    route_kind = str(request.get("route_kind") or "").strip().lower()
    if route_kind not in G2_ROUTE_KINDS:
        raise FacilityCirculationError(
            "facility_circulation_kind_invalid",
            "Circulation route kind is unsupported.",
        )
    direction = str(request.get("direction") or "two_way").strip().lower()
    if direction not in G2_DIRECTIONS:
        raise FacilityCirculationError(
            "facility_circulation_direction_invalid",
            "Circulation direction is unsupported.",
        )
    source_unit = _unit(request.get("source_unit"))
    source_width = _finite_positive(request.get("width"), "width")
    width_meters = _to_meters(source_width, source_unit)
    if width_meters > 1000:
        raise FacilityCirculationError(
            "facility_circulation_width_out_of_bounds",
            "Circulation width may not exceed 1000 meters.",
        )
    zones = _zone_records(layout)
    zone_by_key = {item["key"]: item for item in zones}
    source = request.get("source_department")
    target = request.get("target_department")
    via = request.get("via_departments")
    if not isinstance(via, list) or len(via) > G2_MAXIMUM_WAYPOINTS:
        raise FacilityCirculationError(
            "facility_circulation_via_invalid",
            f"via_departments must contain at most {G2_MAXIMUM_WAYPOINTS} labels.",
        )
    if action == "create":
        source = _clean_label(source, "source_department")
        target = _clean_label(target, "target_department")
        via_labels = [_clean_label(item, "via_department") for item in via]
        authored_labels = [source, *via_labels, target]
        if len({item.casefold() for item in authored_labels}) != len(authored_labels):
            raise FacilityCirculationError(
                "facility_circulation_repeated_department",
                "A circulation route cannot repeat a department in the same path.",
            )
        missing = [label for label in authored_labels if label.casefold() not in zone_by_key]
        if missing:
            raise FacilityCirculationError(
                "facility_circulation_department_not_found",
                "One or more circulation departments are not in the active draft.",
                details={"labels": missing},
            )
    else:
        route = _recent_aisle(layout)
        aisle = route["extensions"]["facilityAisle"]
        zone_by_id = {item["zoneId"]: item for item in zones}
        current_zone_ids = [str(aisle.get("sourceZoneId") or "")]
        current_zone_ids.extend(str(item) for item in aisle.get("viaZoneIds", []))
        current_zone_ids.append(str(aisle.get("targetZoneId") or ""))
        if any(zone_id not in zone_by_id for zone_id in current_zone_ids):
            raise FacilityCirculationError(
                "facility_circulation_department_bindings_missing",
                "The active route has incomplete department bindings.",
            )
        current_labels = [zone_by_id[zone_id]["label"] for zone_id in current_zone_ids]
        path_change_requested = request.get("source_department") is not None or (
            request.get("target_department") is not None
        )
        if path_change_requested:
            source = _clean_label(request.get("source_department"), "source_department")
            target = _clean_label(request.get("target_department"), "target_department")
            via_labels = [_clean_label(item, "via_department") for item in via]
            authored_labels = [source, *via_labels, target]
            if len({item.casefold() for item in authored_labels}) != len(authored_labels):
                raise FacilityCirculationError(
                    "facility_circulation_repeated_department",
                    "A circulation route cannot repeat a department in the same path.",
                )
            missing = [
                label
                for label in authored_labels
                if label.casefold() not in zone_by_key
            ]
            if missing:
                raise FacilityCirculationError(
                    "facility_circulation_department_not_found",
                    "One or more circulation departments are not in the active draft.",
                    details={"labels": missing},
                )
        else:
            source = current_labels[0]
            target = current_labels[-1]
            via_labels = current_labels[1:-1]
        path_changed = [source, *via_labels, target] != current_labels
    label = request.get("label")
    if label is not None:
        label = _clean_label(label, "label")
    return {
        "scope": G2_CIRCULATION_SCOPE,
        "action": action,
        "routeKind": route_kind,
        "sourceWidth": source_width,
        "sourceUnit": source_unit,
        "widthMeters": width_meters,
        "sourceDepartment": source,
        "targetDepartment": target,
        "viaDepartments": via_labels,
        "direction": direction,
        "label": label,
        "executionMode": "authorized_draft_run",
        "areaAccounting": "overlay",
        "widthAuthority": "user_authored",
        "pathChanged": bool(path_changed) if action == "edit_recent" else False,
        "preserveRouteIdentity": action == "edit_recent",
    }


def parse_circulation_turn(
    message: str,
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify and, when complete, normalize one circulation request."""

    text = _SPACE.sub(" ", str(message or "")).strip()
    if not text:
        return {"kind": "not_applicable"}
    zones = _zone_records(layout)
    routing_authority_context = _ROUTING_AUTHORITY_CONTEXT.search(text) is not None
    if _COORDINATE.search(text) and routing_authority_context:
        return {
            "kind": "refuse",
            "code": "facility_circulation_model_geometry_refused",
            "response": (
                "**I cannot accept authored route coordinates from chat.** Name the "
                "start department, end department, optional departments to pass "
                "through, route type, and width; InspectorPro will compute the geometry."
            ),
        }
    if _UNBOUND_VEHICLE_AUTHORITY.search(text):
        return {
            "kind": "refuse",
            "code": "facility_circulation_vehicle_profile_required",
            "response": (
                "**I cannot validate this route for an unspecified forklift.** "
                "Provide the exact published vehicle-profile ID and revision; "
                "InspectorPro will not infer its footprint, turning radius, or reverse "
                "policy. Nothing changed."
            ),
        }
    unsupported_authority_question = bool(
        _READ_QUESTION.search(text)
        and (
            _SAFETY_ADEQUACY_TERM.search(text)
            or (
                _CODE_POLICY.search(text)
                and _POLICY_CONFORMANCE.search(text)
            )
        )
    )
    operational_authority_context = bool(
        routing_authority_context
        or _NETWORK_NOUN.search(text)
        or _CROSSING_MARKING.search(text)
        or _CONFLICT_NOUN.search(text)
        or _FACILITY_OPERATIONAL_CONTEXT.search(text)
        or _CODE_POLICY.search(text)
    )
    if (
        _UNSUPPORTED_OPERATIONAL_CLAIM.search(text)
        or unsupported_authority_question
    ) and operational_authority_context:
        return {
            "kind": "refuse",
            "code": "facility_circulation_operational_authority_missing",
            "response": (
                "**I cannot claim that a facility layout, route network, or crossing is "
                "safe, adequate, compliant, or operationally optimal from static "
                "geometry alone.** Connect the "
                "applicable traffic study, controlled policy, or acceptance criteria; "
                "nothing changed."
            ),
        }
    if (
        _CODE_POLICY.search(text)
        and routing_authority_context
        and (
            re.search(
                r"\b(?:whatever|code\s+requires?|required|required\s+by|applies)\b",
                text,
                re.IGNORECASE,
            )
            or _CONFLICT_RESOLUTION.search(text)
        )
    ):
        return {
            "kind": "refuse",
            "code": "facility_circulation_policy_authority_missing",
            "response": (
                "**I cannot add code-required circulation without an authored policy.** "
                "Provide the applicable route type and width or connect the controlled "
                "facility policy; no clearance value was invented and nothing changed."
            ),
        }
    positioned_departments = _positioned_zone_labels(text, zones)
    network_language = (
        _NETWORK_NOUN.search(text) is not None
        or _CROSSING_COVERAGE.search(text) is not None
        or (
            _NETWORK_REACHABILITY.search(text) is not None
            and len(positioned_departments) >= 1
        )
    )
    if (
        _CIRCULATION_NOUN.search(text) is None
        and _CONFLICT_NOUN.search(text) is None
        and _MIXED_TRAFFIC.search(text) is None
        and _OBSTACLE_NOUN.search(text) is None
        and not network_language
        and _CROSSING_MARKING.search(text) is None
    ):
        return {"kind": "not_applicable"}
    labels = [item["label"] for item in zones]
    crossing_marking_language = _CROSSING_MARKING.search(text) is not None
    if crossing_marking_language and _MUTATION_VERB.search(text):
        dimensions = _crossing_dimensions_from_message(text)
        if dimensions is None:
            return {
                "kind": "ask",
                "code": "facility_circulation_crossing_dimensions_required",
                "response": (
                    "**What exact crosswalk dimensions should I use?** Give width and "
                    "depth with units, such as 4 m by 3 m. InspectorPro will derive the "
                    "position from the route intersection but will not infer marking "
                    "dimensions or a safety standard."
                ),
            }
        network = analyze_primary_circulation_network(layout)
        candidates = [
            item
            for item in network["crossings"]
            if item["intersectionType"] == "point"
            and item["mixedPedestrianMaterialTraffic"] is True
            and item["crosswalkCoverageStatus"] == "unmarked"
        ]
        route_mentions = []
        lowered = text.casefold()
        for route in layout.get("routes", []):
            if not isinstance(route, Mapping):
                continue
            route_id = str(route.get("routeId") or "")
            label = _SPACE.sub(" ", str(route.get("label") or "")).strip()
            if route_id and label and label.casefold() in lowered:
                route_mentions.append(route_id)
        if route_mentions:
            mentioned = set(route_mentions)
            candidates = [
                item
                for item in candidates
                if mentioned.issubset(set(item["routeIds"]))
            ]
        if len(candidates) != 1:
            return {
                "kind": "ask",
                "code": "facility_circulation_crossing_ambiguous",
                "response": (
                    "**Which mixed pedestrian/material point crossing should be "
                    "marked?** Name both route labels. InspectorPro found "
                    f"{len(candidates)} eligible unmarked crossings and will not choose "
                    "one silently."
                ),
            }
        candidate = candidates[0]
        raw = {
            "action": "add_crossing",
            "route_kind": None,
            "width": None,
            "source_unit": None,
            "source_department": None,
            "target_department": None,
            "via_departments": [],
            "direction": None,
            "label": None,
            "conflict_scope": None,
            "minimum_separation": None,
            "separation_unit": None,
            "preserve_departments": True,
            "adjust_route_kind": None,
            "obstacle_scope": None,
            "minimum_clearance": None,
            "clearance_unit": None,
            "preserve_route_identity": None,
            "route_id": None,
            "vehicle_profile_id": None,
            "vehicle_profile_revision": None,
            "allow_reverse": None,
            "network_scope": G23_NETWORK_SCOPE,
            "crossing_route_ids": candidate["routeIds"],
            "crossing_width": dimensions[0],
            "crossing_depth": dimensions[1],
            "crossing_width_unit": dimensions[2],
            "crossing_depth_unit": dimensions[3],
            "preserve_routes": True,
            "execution_mode": "authorized_draft_run",
        }
        return {
            "kind": "build",
            "request": normalize_circulation_request(raw, layout),
        }
    if network_language and (
        _READ_QUESTION.search(text) or _NETWORK_REACHABILITY.search(text)
    ):
        ordered = _route_label_order(text, zones)
        return {
            "kind": "read_only",
            "mode": "network",
            "query": {
                "sourceDepartment": ordered[0] if ordered else None,
                "targetDepartment": ordered[-1] if len(ordered) >= 2 else None,
                "routeKind": _route_kind(text),
                "deadEnds": re.search(
                    r"\bdead[-\s]?ends?|\bterminals?\b", text, re.IGNORECASE
                ) is not None,
                "crossingCoverage": _CROSSING_COVERAGE.search(text) is not None,
            },
        }
    obstacle_language = _OBSTACLE_NOUN.search(text) is not None
    if (
        obstacle_language
        and _CIRCULATION_NOUN.search(text) is None
        and _OBSTACLE_ANALYSIS.search(text) is None
        and _CONFLICT_RESOLUTION.search(text) is None
        and _TURNING_REQUIREMENT.search(text) is None
    ):
        return {"kind": "not_applicable"}
    if (
        obstacle_language
        and _READ_QUESTION.search(text)
        and (
            _CIRCULATION_NOUN.search(text) is not None
            or _OBSTACLE_ANALYSIS.search(text) is not None
        )
    ):
        return {"kind": "read_only", "mode": "obstacles"}
    if obstacle_language and _CONFLICT_RESOLUTION.search(text):
        profile_match = _VEHICLE_PROFILE_REF.search(text)
        profile_id = (
            profile_match.group("identifier") if profile_match else None
        )
        profile_revision = (
            profile_match.group("revision") if profile_match else None
        )
        if _TURNING_REQUIREMENT.search(text) and not (
            profile_id and profile_revision
        ):
            return {
                "kind": "ask",
                "code": "facility_circulation_vehicle_profile_required",
                "response": (
                    "**Which published vehicle profile should govern this route?** "
                    "Turning radius, footprint, load envelope, and reverse policy "
                    "must come from one revision-bound profile; InspectorPro will not "
                    "infer them from the word forklift."
                ),
            }
        clearance = _width_from_message(text)
        routes = [
            route
            for route in layout.get("routes", [])
            if isinstance(route, Mapping)
            and isinstance(route.get("extensions"), Mapping)
            and isinstance(route["extensions"].get("facilityAisle"), Mapping)
        ]
        if not routes:
            return {
                "kind": "ask",
                "code": "facility_circulation_recent_route_missing",
                "response": (
                    "**There is no generated route to reroute around the static "
                    "obstacles.** Create the route first, including its departments, "
                    "type, and width."
                ),
            }
        raw = {
            "action": "avoid_obstacles",
            "route_kind": None,
            "width": None,
            "source_unit": None,
            "source_department": None,
            "target_department": None,
            "via_departments": [],
            "direction": None,
            "label": None,
            "conflict_scope": None,
            "minimum_separation": None,
            "separation_unit": None,
            "preserve_departments": True,
            "adjust_route_kind": None,
            "obstacle_scope": G22_OBSTACLE_SCOPE,
            "minimum_clearance": clearance[0] if clearance else None,
            "clearance_unit": clearance[1] if clearance else None,
            "preserve_route_identity": True,
            "route_id": str(routes[-1].get("routeId") or ""),
            "vehicle_profile_id": profile_id,
            "vehicle_profile_revision": profile_revision,
            "allow_reverse": None,
            "execution_mode": "authorized_draft_run",
        }
        normalized = normalize_circulation_request(raw, layout)
        assumptions = []
        if clearance is None:
            assumptions.append(
                "Geometric non-overlap was used with no additional clearance "
                "because no distance or approved policy was supplied."
            )
        normalized["assumptions"] = assumptions
        return {"kind": "build", "request": normalized}
    conflict_language = (
        _CONFLICT_NOUN.search(text) is not None
        or _MIXED_TRAFFIC.search(text) is not None
    )
    if conflict_language and _CONFLICT_RESOLUTION.search(text):
        explicit_separation = _width_from_message(text)
        if re.search(
            r"\b(?:reroute|move|adjust|shift)\w*\s+(?:the\s+)?(?:pedestrian|walkway)\b|"
            r"\bkeep\s+(?:the\s+)?(?:forklift|material)\s+(?:lane|route|aisle)?\s*fixed\b",
            text,
            re.IGNORECASE,
        ):
            adjustment_mode = "pedestrian"
        elif re.search(
            r"\b(?:reroute|move|adjust|shift)\w*\s+(?:the\s+)?(?:forklift|material)\b|"
            r"\bkeep\s+(?:the\s+)?(?:pedestrian|walkway)\s+(?:lane|route|aisle)?\s*fixed\b",
            text,
            re.IGNORECASE,
        ):
            adjustment_mode = "material"
        else:
            adjustment_mode = "auto_shortest"
        raw = {
            "action": "resolve_conflicts",
            "route_kind": None,
            "width": None,
            "source_unit": None,
            "source_department": None,
            "target_department": None,
            "via_departments": [],
            "direction": None,
            "label": None,
            "conflict_scope": G21_CONFLICT_SCOPE,
            "minimum_separation": (
                explicit_separation[0] if explicit_separation else None
            ),
            "separation_unit": (
                explicit_separation[1] if explicit_separation else None
            ),
            "preserve_departments": True,
            "adjust_route_kind": adjustment_mode,
            "execution_mode": "authorized_draft_run",
        }
        normalized = normalize_circulation_request(raw, layout)
        assumptions = []
        if not explicit_separation:
            assumptions.append(
                "Geometric non-overlap was used with no additional clearance "
                "because no separation distance or approved policy was supplied."
            )
        if adjustment_mode == "auto_shortest":
            assumptions.append(
                "InspectorPro compared pedestrian and material reroutes and selected "
                "the shorter feasible centerline; this is not an operational optimum."
            )
        normalized["assumptions"] = assumptions
        return {"kind": "build", "request": normalized}
    if conflict_language and _READ_QUESTION.search(text):
        return {"kind": "read_only", "mode": "conflicts"}
    if _NEGATED_ACTION.search(text):
        return {
            "kind": "read_only",
            "mode": "options",
            "response": (
                "**No route was added.** Circulation can be expressed as a direct "
                "department-to-department aisle, an ordered multi-stop material path, "
                "a forklift lane, or a pedestrian walkway. Name the endpoints and width "
                "when you want InspectorPro to build one."
            ),
        }
    if _HYPOTHETICAL.search(text) and re.search(
        r"\b(?:go\s+ahead|do\s+it|build\s+it|create\s+it|add\s+it\s+now)\b",
        text,
        re.IGNORECASE,
    ) is None:
        return {
            "kind": "read_only",
            "mode": "hypothetical",
            "response": (
                "**No circulation candidate has been computed, so no travel benefit is "
                "claimed.** A route could change connectivity and travel distance, but "
                "InspectorPro needs named endpoints, a route type, and a width before it "
                "can calculate and compare geometry. Nothing changed."
            ),
        }
    if _READ_QUESTION.search(text):
        return {"kind": "read_only", "mode": "analysis"}
    follow_up = _FOLLOW_UP.search(text) is not None
    mutation = _MUTATION_VERB.search(text) is not None
    if not mutation:
        return {"kind": "read_only", "mode": "analysis"}
    width = _width_from_message(text)
    route_kind = _route_kind(text)
    if follow_up:
        existing = [
            route
            for route in layout.get("routes", [])
            if isinstance(route, Mapping)
            and isinstance(route.get("extensions"), Mapping)
            and isinstance(route["extensions"].get("facilityAisle"), Mapping)
        ]
        if not existing:
            return {
                "kind": "ask",
                "code": "facility_circulation_recent_route_missing",
                "response": (
                    "**There is no active generated aisle to amend.** Name the source "
                    "and target departments so I can create one."
                ),
            }
        latest = existing[-1]
        extension = latest["extensions"]["facilityAisle"]
        zones_by_id = {item["zoneId"]: item for item in zones}
        current_zone_ids = [str(extension.get("sourceZoneId") or "")]
        current_zone_ids.extend(str(item) for item in extension.get("viaZoneIds", []))
        current_zone_ids.append(str(extension.get("targetZoneId") or ""))
        current_labels = [
            zones_by_id[zone_id]["label"]
            for zone_id in current_zone_ids
            if zone_id in zones_by_id
        ]
        path_change_language = re.search(
            r"\b(?:via|through|passing\s+through)\b",
            text,
            re.IGNORECASE,
        ) is not None
        desired_labels = current_labels
        if path_change_language:
            mentioned = [item[2] for item in _positioned_zone_labels(text, zones)]
            if not mentioned:
                return {
                    "kind": "ask",
                    "code": "facility_circulation_via_department_required",
                    "response": (
                        "**Which department should this route pass through?** Name the "
                        "department; InspectorPro will recompute the centerline while "
                        "preserving the route identity and every unaffected entity."
                    ),
                }
            if re.search(r"\bfrom\b", text, re.IGNORECASE) and re.search(
                r"\bto\b", text, re.IGNORECASE
            ):
                desired_labels = _route_label_order(text, zones)
            elif len(current_labels) >= 2:
                requested_vias = [
                    label
                    for label in mentioned
                    if label.casefold()
                    not in {
                        current_labels[0].casefold(),
                        current_labels[-1].casefold(),
                    }
                ]
                existing_vias = (
                    []
                    if re.search(r"\binstead\b", text, re.IGNORECASE)
                    else current_labels[1:-1]
                )
                combined_vias = []
                for label in [*existing_vias, *requested_vias]:
                    if label.casefold() not in {
                        item.casefold() for item in combined_vias
                    }:
                        combined_vias.append(label)
                desired_labels = [
                    current_labels[0],
                    *combined_vias,
                    current_labels[-1],
                ]
        existing_width = _finite_positive(
            latest.get("corridorWidth"),
            "existing route width",
        )
        if width is not None and re.search(r"\bby\b", text, re.IGNORECASE):
            delta = _to_meters(width[0], width[1])
            if re.search(r"\b(?:narrow|reduce|decrease)\w*\b", text, re.IGNORECASE):
                delta = -delta
            elif re.search(r"\b(?:widen|increase)\w*\b", text, re.IGNORECASE) is None:
                return {
                    "kind": "ask",
                    "code": "facility_circulation_relative_width_ambiguous",
                    "response": (
                        "**Should that amount widen or narrow the route?** State the "
                        "direction of the width change, or give the exact final width."
                    ),
                }
            final_width = existing_width + delta
            if final_width <= 0:
                return {
                    "kind": "ask",
                    "code": "facility_circulation_width_nonpositive",
                    "response": (
                        "**That change would make the route width zero or negative.** "
                        "Give a smaller reduction or an exact positive final width."
                    ),
                }
            width = (final_width, "m")
        elif width is None:
            width = (existing_width, "m")
        route_kind = route_kind or str(extension.get("aisleKind") or "material")
        direction = (
            "one_way" if _DIRECTION_ONE.search(text)
            else "two_way" if _DIRECTION_TWO.search(text)
            else str(extension.get("direction") or "two_way")
        )
        raw = {
            "action": "edit_recent",
            "route_kind": route_kind,
            "width": width[0],
            "source_unit": width[1],
            "source_department": (
                desired_labels[0] if path_change_language else None
            ),
            "target_department": (
                desired_labels[-1] if path_change_language else None
            ),
            "via_departments": (
                desired_labels[1:-1] if path_change_language else []
            ),
            "direction": direction,
            "label": None,
            "execution_mode": "authorized_draft_run",
        }
        return {"kind": "build", "request": normalize_circulation_request(raw, layout)}
    if width is None:
        return {
            "kind": "ask",
            "code": "facility_circulation_width_required",
            "response": (
                "**What route width should I use?** Give the width with a unit, such as "
                "5 m or 12 ft; InspectorPro will not infer a safety or handling clearance."
            ),
        }
    matched = _route_label_order(text, zones)
    if len(matched) < 2:
        available = ", ".join(labels[:8])
        suffix = f" Available departments include {available}." if available else ""
        return {
            "kind": "ask",
            "code": "facility_circulation_endpoints_required",
            "response": (
                "**Which departments should the route connect?** Name a source and "
                "target, and list any departments it must pass through." + suffix
            ),
        }
    if route_kind is None:
        return {
            "kind": "ask",
            "code": "facility_circulation_kind_required",
            "response": (
                "**What kind of circulation is this?** Specify material, forklift, or "
                "pedestrian so InspectorPro can apply the correct semantic route type."
            ),
        }
    direction = (
        "one_way" if _DIRECTION_ONE.search(text)
        else "two_way"
    )
    explicit_label = _EXPLICIT_ROUTE_LABEL.search(text)
    raw = {
        "action": "create",
        "route_kind": route_kind,
        "width": width[0],
        "source_unit": width[1],
        "source_department": matched[0],
        "target_department": matched[-1],
        "via_departments": matched[1:-1],
        "direction": direction,
        "label": explicit_label.group("label") if explicit_label else None,
        "execution_mode": "authorized_draft_run",
    }
    normalized = normalize_circulation_request(raw, layout)
    assumptions = []
    if _DIRECTION_ONE.search(text) is None and _DIRECTION_TWO.search(text) is None:
        assumptions.append("Two-way circulation was used because direction was omitted.")
    normalized["assumptions"] = assumptions
    return {"kind": "build", "request": normalized}


def _plan_dimensions(layout: Mapping[str, Any]) -> tuple[float, float]:
    extensions = layout.get("extensions")
    plan = extensions.get("facilityPlan") if isinstance(extensions, Mapping) else None
    if not isinstance(plan, Mapping):
        raise FacilityCirculationError(
            "facility_circulation_envelope_required",
            "Circulation requires a generated facility envelope.",
        )
    return (
        _finite_positive(plan.get("widthMeters"), "facility width"),
        _finite_positive(plan.get("depthMeters"), "facility depth"),
    )


def _point(x: float, z: float) -> dict[str, float]:
    return {"x": round(float(x), 6), "y": 0.0, "z": round(float(z), 6)}


def _aisle_centerline_for_compiler(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4096:
        raise FacilityCirculationError(
            "facility_circulation_centerline_invalid",
            "Compiled circulation geometry must contain between 2 and 4096 points.",
        )
    result = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"x", "y", "z"}:
            raise FacilityCirculationError(
                "facility_circulation_centerline_invalid",
                "Compiled circulation points must contain x, y, and z.",
            )
        try:
            point = {axis: float(raw[axis]) for axis in ("x", "y", "z")}
        except (TypeError, ValueError) as exc:
            raise FacilityCirculationError(
                "facility_circulation_centerline_invalid",
                "Compiled circulation coordinates must be finite numbers.",
            ) from exc
        if not all(math.isfinite(point[axis]) for axis in point):
            raise FacilityCirculationError(
                "facility_circulation_centerline_invalid",
                "Compiled circulation coordinates must be finite numbers.",
            )
        result.append({axis: round(point[axis], 6) for axis in point})
    return result


def _orthogonal_centerline(
    centers: Sequence[tuple[float, float]],
) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for index, (x, z) in enumerate(centers):
        if index == 0:
            points.append(_point(x, z))
            continue
        prior = points[-1]
        if abs(float(prior["x"]) - x) > G2_COORDINATE_TOLERANCE_METERS:
            candidate = _point(x, float(prior["z"]))
            if candidate != points[-1]:
                points.append(candidate)
        candidate = _point(x, z)
        if candidate != points[-1]:
            points.append(candidate)
    if len(points) < 2:
        raise FacilityCirculationError(
            "facility_circulation_geometry_degenerate",
            "The requested departments do not produce a route with measurable length.",
        )
    return points


def _recent_aisle(layout: Mapping[str, Any]) -> Mapping[str, Any]:
    aisles = [
        item
        for item in layout.get("routes", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("extensions"), Mapping)
        and isinstance(item["extensions"].get("facilityAisle"), Mapping)
    ]
    if not aisles:
        raise FacilityCirculationError(
            "facility_circulation_recent_route_missing",
            "There is no active generated aisle to amend.",
        )
    return aisles[-1]


def _require_geometry_engine() -> None:
    if any(
        item is None
        for item in (LineString, Point, Polygon, box, unary_union, prep)
    ):
        raise FacilityCirculationError(
            "facility_circulation_geometry_engine_unavailable",
            "Conflict-aware circulation requires the configured geometry engine.",
        )


def _aisle_kind_for_route(route: Mapping[str, Any]) -> str:
    extensions = route.get("extensions")
    aisle = (
        extensions.get("facilityAisle")
        if isinstance(extensions, Mapping)
        and isinstance(extensions.get("facilityAisle"), Mapping)
        else {}
    )
    kind = str(aisle.get("aisleKind") or route.get("routeKind") or "").strip()
    return {"operator": "pedestrian"}.get(kind, kind)


def _movement_class(route: Mapping[str, Any]) -> str:
    kind = _aisle_kind_for_route(route)
    if kind == "pedestrian":
        return "pedestrian"
    if kind in {"forklift", "material"}:
        return "material"
    return kind or "unknown"


def _route_line(route: Mapping[str, Any]):
    _require_geometry_engine()
    points = []
    for raw in route.get("centerline", []):
        if not isinstance(raw, Mapping):
            continue
        try:
            points.append((float(raw["x"]), float(raw["z"])))
        except (KeyError, TypeError, ValueError):
            continue
    if len(points) < 2:
        return None
    try:
        return LineString(points)
    except (TypeError, ValueError, GEOSException):
        return None


def _route_corridor(route: Mapping[str, Any], extra: float = 0.0):
    line = _route_line(route)
    if line is None:
        return None
    try:
        width = _finite_positive(route.get("corridorWidth"), "route width")
        return line.buffer(
            width / 2.0 + max(0.0, float(extra)),
            cap_style=2,
            join_style=2,
        )
    except (TypeError, ValueError, GEOSException):
        return None


def _semantic_term(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _matches_semantic_vocabulary(
    terms: set[str],
    vocabulary: frozenset[str],
) -> bool:
    return any(
        f"_{candidate}_" in f"_{term}_"
        for term in terms
        for candidate in vocabulary
        if term and candidate
    )


def _polygon_from_boundary(value: Any, field: str):
    _require_geometry_engine()
    if not isinstance(value, list) or len(value) < 3:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_geometry_invalid",
            f"{field} must contain at least three points.",
        )
    points = []
    try:
        for raw in value:
            if not isinstance(raw, Mapping):
                raise TypeError
            point = (float(raw["x"]), float(raw["z"]))
            if not all(math.isfinite(item) for item in point):
                raise ValueError
            points.append(point)
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_geometry_invalid",
            f"{field} contains invalid coordinates.",
        ) from exc
    try:
        polygon = Polygon(points)
    except (TypeError, ValueError, GEOSException) as exc:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_geometry_invalid",
            f"{field} is not a usable polygon.",
        ) from exc
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_geometry_invalid",
            f"{field} must be a valid non-degenerate polygon.",
        )
    return polygon


def _polygon_boundary(shape: Any) -> list[dict[str, float]]:
    coordinates = list(shape.exterior.coords)
    if coordinates and coordinates[0] == coordinates[-1]:
        coordinates.pop()
    return [
        {"x": round(float(x), 6), "z": round(float(z), 6)}
        for x, z in coordinates
    ]


def _floor_marking_polygon(marking: Mapping[str, Any]):
    for key in ("boundary", "polygon", "points"):
        if isinstance(marking.get(key), list):
            return _polygon_from_boundary(
                marking[key], f"floorMarking.{key}"
            )
    transform = marking.get("transform")
    position = (
        transform.get("position")
        if isinstance(transform, Mapping)
        and isinstance(transform.get("position"), Mapping)
        else None
    )
    if not isinstance(position, Mapping):
        return None
    try:
        center_x = float(position["x"])
        center_z = float(position["z"])
        width = float(marking["width"])
        depth = float(marking["depth"])
        rotation = math.radians(float(transform.get("rotationDegrees", 0.0)))
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or depth <= 0 or not all(
        math.isfinite(value)
        for value in (center_x, center_z, width, depth, rotation)
    ):
        return None
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    points = []
    for local_x, local_z in (
        (-width / 2.0, -depth / 2.0),
        (width / 2.0, -depth / 2.0),
        (width / 2.0, depth / 2.0),
        (-width / 2.0, depth / 2.0),
    ):
        points.append({
            "x": center_x + local_x * cosine - local_z * sine,
            "z": center_z + local_x * sine + local_z * cosine,
        })
    return _polygon_from_boundary(points, "floorMarking.transform")


def normalize_circulation_obstacle_context(
    context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate the revision-bound external geometry snapshot for G2.2."""

    source = dict(context or {})
    allowed = {
        "schemaVersion",
        "obstacles",
        "sourceRevisions",
        "vehicleProfile",
        "contextRevision",
    }
    unknown = sorted(set(source) - allowed)
    if unknown:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_context_invalid",
            "Obstacle context contains unsupported fields.",
            details={"fields": unknown},
        )
    if source and source.get("schemaVersion") != 1:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_context_invalid",
            "Obstacle context schemaVersion must be 1.",
        )
    raw_obstacles = source.get("obstacles", [])
    if not isinstance(raw_obstacles, list) or len(raw_obstacles) > G22_MAXIMUM_OBSTACLES:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_context_limit_exceeded",
            f"Obstacle context may contain at most {G22_MAXIMUM_OBSTACLES} records.",
        )
    obstacles = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_obstacles):
        if not isinstance(raw, Mapping):
            raise FacilityCirculationError(
                "facility_circulation_obstacle_context_invalid",
                "Obstacle records must be objects.",
            )
        obstacle_id = _clean_label(raw.get("obstacleId"), "obstacleId", 128)
        if obstacle_id in seen:
            raise FacilityCirculationError(
                "facility_circulation_obstacle_context_invalid",
                "Obstacle IDs must be unique.",
                details={"obstacleId": obstacle_id},
            )
        seen.add(obstacle_id)
        shape = _polygon_from_boundary(
            raw.get("boundary"), f"obstacles[{index}].boundary"
        )
        kind = _clean_label(raw.get("obstacleKind"), "obstacleKind", 64)
        evidence_status = str(raw.get("evidenceStatus") or "unknown")
        if evidence_status not in {"authored", "derived", "unknown"}:
            raise FacilityCirculationError(
                "facility_circulation_obstacle_context_invalid",
                "Obstacle evidence status is unsupported.",
            )
        obstacles.append({
            "obstacleId": obstacle_id,
            "obstacleKind": kind,
            "boundary": _polygon_boundary(shape),
            "evidenceStatus": evidence_status,
            "sourceRef": str(raw.get("sourceRef") or obstacle_id)[:256],
        })
    source_revisions = source.get("sourceRevisions", {})
    if not isinstance(source_revisions, Mapping):
        raise FacilityCirculationError(
            "facility_circulation_obstacle_context_invalid",
            "Obstacle sourceRevisions must be an object.",
        )
    normalized = {
        "schemaVersion": 1,
        "obstacles": sorted(obstacles, key=lambda item: item["obstacleId"]),
        "sourceRevisions": {
            str(key): str(value)
            for key, value in sorted(source_revisions.items())
        },
        "vehicleProfile": deepcopy(source.get("vehicleProfile")),
    }
    if len(_canonical_bytes(normalized)) > G22_MAXIMUM_CONTEXT_BYTES:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_context_limit_exceeded",
            "Obstacle context exceeds the durable snapshot byte limit.",
        )
    normalized["contextRevision"] = hashlib.sha256(
        _canonical_bytes(normalized)
    ).hexdigest()
    return normalized


def _static_obstacle_records(
    layout: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_circulation_obstacle_context(context)
    result = [deepcopy(item) for item in normalized["obstacles"]]
    seen = {item["obstacleId"] for item in result}
    for marking in layout.get("floorMarkings", []):
        if not isinstance(marking, Mapping):
            continue
        terms = {
            _semantic_term(marking.get("markingType")),
            _semantic_term(marking.get("semanticRole")),
        }
        if not _matches_semantic_vocabulary(
            terms, G22_PROTECTED_MARKING_TERMS
        ):
            continue
        shape = _floor_marking_polygon(marking)
        marking_id = str(marking.get("markingId") or "").strip()
        obstacle_id = f"floor-marking:{marking_id}"
        if shape is None or not marking_id or obstacle_id in seen:
            continue
        seen.add(obstacle_id)
        result.append({
            "obstacleId": obstacle_id,
            "obstacleKind": "protected_floor_marking",
            "boundary": _polygon_boundary(shape),
            "evidenceStatus": "authored",
            "sourceRef": marking_id,
        })
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping):
            continue
        terms = {
            _semantic_term(zone.get("zoneType")),
            _semantic_term(zone.get("semanticType")),
            _semantic_term(zone.get("label")),
        }
        if not _matches_semantic_vocabulary(terms, G22_PROTECTED_ZONE_TERMS):
            continue
        zone_id = str(zone.get("zoneId") or "").strip()
        obstacle_id = f"protected-zone:{zone_id}"
        if not zone_id or obstacle_id in seen:
            continue
        shape = _polygon_from_boundary(
            zone.get("boundary"), f"zone[{zone_id}].boundary"
        )
        seen.add(obstacle_id)
        result.append({
            "obstacleId": obstacle_id,
            "obstacleKind": "protected_zone",
            "boundary": _polygon_boundary(shape),
            "evidenceStatus": "authored",
            "sourceRef": zone_id,
        })
    result.sort(key=lambda item: item["obstacleId"])
    return result


def analyze_primary_circulation_obstacles(
    layout: Mapping[str, Any],
    obstacle_context: Mapping[str, Any] | None = None,
    *,
    minimum_clearance_meters: float = 0.0,
) -> dict[str, Any]:
    """Return exact route-corridor conflicts with static authored geometry."""

    clearance = float(minimum_clearance_meters)
    if not math.isfinite(clearance) or clearance < 0:
        raise FacilityCirculationError(
            "facility_circulation_number_invalid",
            "Obstacle clearance must be zero or positive.",
        )
    obstacles = _static_obstacle_records(layout, obstacle_context)
    obstacle_shapes = {
        item["obstacleId"]: _polygon_from_boundary(
            item["boundary"], f"obstacle[{item['obstacleId']}].boundary"
        )
        for item in obstacles
    }
    conflicts = []
    for route in layout.get("routes", []):
        if not isinstance(route, Mapping) or not route.get("routeId"):
            continue
        corridor = _route_corridor(route)
        if corridor is None:
            continue
        for obstacle in obstacles:
            shape = obstacle_shapes[obstacle["obstacleId"]]
            distance = float(corridor.distance(shape))
            limited = shape.buffer(clearance) if clearance else shape
            interior = limited.buffer(-G21_GEOMETRY_EPSILON_METERS)
            if interior.is_empty or not corridor.intersects(interior):
                continue
            intersection = corridor.intersection(limited)
            position = intersection.representative_point()
            conflicts.append({
                "conflictId": _stable_id(
                    "route-obstacle-conflict",
                    {
                        "routeId": route["routeId"],
                        "obstacleId": obstacle["obstacleId"],
                        "clearanceMeters": round(clearance, 6),
                    },
                ),
                "routeId": str(route["routeId"]),
                "routeLabel": str(route.get("label") or route["routeId"]),
                "routeKind": _aisle_kind_for_route(route),
                "obstacleId": obstacle["obstacleId"],
                "obstacleKind": obstacle["obstacleKind"],
                "obstacleSourceRef": obstacle["sourceRef"],
                "obstacleEvidenceStatus": obstacle["evidenceStatus"],
                "minimumDistanceMeters": round(distance, 6),
                "requiredClearanceMeters": round(clearance, 6),
                "overlapAreaSquareMeters": round(float(intersection.area), 6),
                "position": {
                    "x": round(float(position.x), 6),
                    "z": round(float(position.y), 6),
                },
                "evidenceStatus": "derived",
            })
    conflicts.sort(key=lambda item: item["conflictId"])
    affected_routes = sorted({item["routeId"] for item in conflicts})
    return {
        "status": "conflict" if conflicts else "clear",
        "routeObstacleConflictCount": len(conflicts),
        "affectedRouteIds": affected_routes,
        "evaluatedRouteCount": len([
            route for route in layout.get("routes", [])
            if isinstance(route, Mapping) and route.get("routeId")
        ]),
        "evaluatedObstacleCount": len(obstacles),
        "minimumClearanceMeters": round(clearance, 6),
        "conflicts": conflicts,
        "qualification": (
            "Static route corridors were compared with revision-bound physical "
            "footprints, protected layout regions, and authored clearance envelopes. "
            "This does not establish regulatory compliance, traffic capacity, or "
            "vehicle turning adequacy unless a published vehicle profile is also "
            "validated."
        ),
    }


def analyze_primary_circulation_conflicts(
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Return exact static corridor conflicts without safety interpretation."""

    _require_geometry_engine()
    routes = [
        route for route in layout.get("routes", [])
        if isinstance(route, Mapping) and str(route.get("routeId") or "")
    ]
    records: list[dict[str, Any]] = []
    mixed_pair_separations: list[float] = []
    for left_index, left in enumerate(routes):
        left_line = _route_line(left)
        left_corridor = _route_corridor(left)
        if left_line is None or left_corridor is None:
            continue
        for right in routes[left_index + 1:]:
            right_line = _route_line(right)
            right_corridor = _route_corridor(right)
            if right_line is None or right_corridor is None:
                continue
            left_class = _movement_class(left)
            right_class = _movement_class(right)
            mixed = {left_class, right_class} == {"material", "pedestrian"}
            corridor_distance = float(left_corridor.distance(right_corridor))
            if mixed:
                mixed_pair_separations.append(corridor_distance)
            try:
                line_intersection = left_line.intersection(right_line)
                corridor_intersection = left_corridor.intersection(right_corridor)
            except (TypeError, ValueError, GEOSException):
                continue
            shared_length = float(getattr(line_intersection, "length", 0.0))
            overlap_area = float(getattr(corridor_intersection, "area", 0.0))
            centerlines_intersect = not line_intersection.is_empty
            requires_resolution = mixed and (
                centerlines_intersect
                or overlap_area > G21_GEOMETRY_EPSILON_METERS
            )
            if not requires_resolution:
                continue
            geometry_type = (
                "shared_segment"
                if shared_length > G21_GEOMETRY_EPSILON_METERS
                else "crossing"
                if centerlines_intersect
                else "corridor_overlap"
            )
            geometry = (
                line_intersection
                if centerlines_intersect
                else corridor_intersection
            )
            centroid = geometry.centroid
            left_id = str(left.get("routeId"))
            right_id = str(right.get("routeId"))
            records.append({
                "conflictId": _stable_id(
                    "circulation-conflict",
                    {"routeIds": sorted([left_id, right_id]), "type": geometry_type},
                ),
                "routeIds": [left_id, right_id],
                "routeLabels": [
                    str(left.get("label") or left_id),
                    str(right.get("label") or right_id),
                ],
                "routeKinds": [
                    _aisle_kind_for_route(left),
                    _aisle_kind_for_route(right),
                ],
                "movementClasses": sorted({left_class, right_class}),
                "conflictType": geometry_type,
                "position": {
                    "x": round(float(centroid.x), 6),
                    "z": round(float(centroid.y), 6),
                },
                "sharedCenterlineLengthMeters": round(shared_length, 6),
                "corridorOverlapAreaSquareMeters": round(overlap_area, 6),
                "corridorEdgeSeparationMeters": round(corridor_distance, 6),
                "mixedPedestrianMaterialTraffic": True,
                "evidenceStatus": "derived",
            })
    records.sort(key=lambda item: item["conflictId"])
    return {
        "status": "conflict" if records else "clear",
        "routeCount": len(routes),
        "mixedTrafficConflictCount": len(records),
        "sharedSegmentConflictCount": sum(
            item["conflictType"] == "shared_segment" for item in records
        ),
        "pointCrossingConflictCount": sum(
            item["conflictType"] == "crossing" for item in records
        ),
        "corridorOverlapConflictCount": sum(
            item["conflictType"] == "corridor_overlap" for item in records
        ),
        "mixedTrafficPairMinimumSeparationMeters": (
            round(min(mixed_pair_separations), 6)
            if mixed_pair_separations else None
        ),
        "conflicts": records,
        "qualification": (
            "This is static geometry-derived overlap and crossing evidence. "
            "It does not establish traffic safety, capacity, turning adequacy, "
            "or regulatory compliance."
        ),
    }


def _route_crossing_points(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    geometry_type = str(getattr(geometry, "geom_type", ""))
    if geometry_type == "Point":
        return [geometry]
    if geometry_type == "MultiPoint":
        return sorted(
            list(geometry.geoms),
            key=lambda point: (float(point.x), float(point.y)),
        )
    if geometry_type == "GeometryCollection":
        return sorted(
            [item for item in geometry.geoms if item.geom_type == "Point"],
            key=lambda point: (float(point.x), float(point.y)),
        )
    return []


def analyze_primary_circulation_network(
    layout: Mapping[str, Any],
    *,
    source_department: str | None = None,
    target_department: str | None = None,
    route_kind: str | None = None,
) -> dict[str, Any]:
    """Derive exact route-binding reachability and crossing coverage."""

    _require_geometry_engine()
    if route_kind is not None and route_kind not in G2_ROUTE_KINDS:
        raise FacilityCirculationError(
            "facility_circulation_kind_invalid",
            "Circulation route kind is unsupported.",
        )
    zones = _zone_records(layout)
    zone_by_id = {item["zoneId"]: item for item in zones}
    zone_by_key = {item["key"]: item for item in zones}
    filtered_routes = [
        route
        for route in layout.get("routes", [])
        if isinstance(route, Mapping)
        and str(route.get("routeId") or "")
        and (route_kind is None or _aisle_kind_for_route(route) == route_kind)
    ]
    directed: dict[str, set[str]] = {zone_id: set() for zone_id in zone_by_id}
    undirected: dict[str, set[str]] = {zone_id: set() for zone_id in zone_by_id}
    edge_routes: dict[tuple[str, str], list[str]] = {}
    unresolved_bindings = []
    network_edges = []
    for route in filtered_routes:
        route_id = str(route.get("routeId") or "")
        aisle = (
            route.get("extensions", {}).get("facilityAisle")
            if isinstance(route.get("extensions"), Mapping)
            else None
        )
        if not isinstance(aisle, Mapping):
            unresolved_bindings.append(route_id)
            continue
        zone_ids = _zone_ids_for_route(route)
        if len(zone_ids) < 2 or any(zone_id not in zone_by_id for zone_id in zone_ids):
            unresolved_bindings.append(route_id)
            continue
        direction = str(aisle.get("direction") or "two_way")
        for left, right in zip(zone_ids, zone_ids[1:]):
            directed[left].add(right)
            undirected[left].add(right)
            undirected[right].add(left)
            edge_routes.setdefault((left, right), []).append(route_id)
            if direction == "two_way":
                directed[right].add(left)
                edge_routes.setdefault((right, left), []).append(route_id)
            network_edges.append({
                "routeId": route_id,
                "fromZoneId": left,
                "toZoneId": right,
                "direction": direction,
            })

    components = []
    unseen = set(zone_by_id)
    while unseen:
        seed = min(unseen)
        pending = [seed]
        members = []
        while pending:
            zone_id = pending.pop()
            if zone_id not in unseen:
                continue
            unseen.remove(zone_id)
            members.append(zone_id)
            pending.extend(sorted(undirected[zone_id] & unseen, reverse=True))
        members.sort()
        components.append({
            "componentId": _stable_id("route-network-component", members),
            "zoneIds": members,
            "departmentLabels": [zone_by_id[item]["label"] for item in members],
            "departmentCount": len(members),
        })
    components.sort(key=lambda item: item["componentId"])

    source = None
    target = None
    if source_department is not None:
        source = zone_by_key.get(str(source_department).casefold())
        if source is None:
            raise FacilityCirculationError(
                "facility_circulation_department_not_found",
                "The source department is not in the active draft.",
                details={"label": source_department},
            )
    if target_department is not None:
        target = zone_by_key.get(str(target_department).casefold())
        if target is None:
            raise FacilityCirculationError(
                "facility_circulation_department_not_found",
                "The target department is not in the active draft.",
                details={"label": target_department},
            )

    reachable_ids: list[str] = []
    query_path = None
    if source is not None:
        source_id = source["zoneId"]
        pending = [source_id]
        predecessor: dict[str, tuple[str, str] | None] = {source_id: None}
        while pending:
            current = pending.pop(0)
            for neighbor in sorted(directed[current]):
                if neighbor in predecessor:
                    continue
                route_ids = sorted(edge_routes.get((current, neighbor), []))
                predecessor[neighbor] = (
                    current,
                    route_ids[0] if route_ids else "",
                )
                pending.append(neighbor)
        reachable_ids = sorted(predecessor)
        if target is not None and target["zoneId"] in predecessor:
            cursor = target["zoneId"]
            path_zone_ids = [cursor]
            path_route_ids = []
            while predecessor[cursor] is not None:
                prior, route_id = predecessor[cursor]
                path_route_ids.append(route_id)
                path_zone_ids.append(prior)
                cursor = prior
            path_zone_ids.reverse()
            path_route_ids.reverse()
            query_path = {
                "zoneIds": path_zone_ids,
                "departmentLabels": [
                    zone_by_id[item]["label"] for item in path_zone_ids
                ],
                "routeIds": path_route_ids,
            }

    crosswalk_shapes = {
        str(marking.get("markingId") or ""): _floor_marking_polygon(marking)
        for marking in layout.get("floorMarkings", [])
        if isinstance(marking, Mapping)
        and str(marking.get("markingType") or "") == "crosswalk"
        and str(marking.get("markingId") or "")
    }
    crossings = []
    for left_index, left in enumerate(filtered_routes):
        left_line = _route_line(left)
        if left_line is None:
            continue
        for right in filtered_routes[left_index + 1:]:
            right_line = _route_line(right)
            if right_line is None:
                continue
            intersection = left_line.intersection(right_line)
            if intersection.is_empty:
                continue
            left_id = str(left.get("routeId") or "")
            right_id = str(right.get("routeId") or "")
            route_ids = sorted([left_id, right_id])
            left_class = _movement_class(left)
            right_class = _movement_class(right)
            mixed = {left_class, right_class} == {"material", "pedestrian"}
            points = _route_crossing_points(intersection)
            if points:
                for point in points:
                    position = {
                        "x": round(float(point.x), 6),
                        "z": round(float(point.y), 6),
                    }
                    marking_ids = sorted(
                        marking_id
                        for marking_id, shape in crosswalk_shapes.items()
                        if shape is not None and shape.intersects(point)
                    )
                    crossings.append({
                        "crossingId": _stable_id(
                            "route-crossing",
                            {"routeIds": route_ids, "position": position},
                        ),
                        "routeIds": route_ids,
                        "routeLabels": [
                            str(left.get("label") or left_id),
                            str(right.get("label") or right_id),
                        ],
                        "routeKinds": [
                            _aisle_kind_for_route(left),
                            _aisle_kind_for_route(right),
                        ],
                        "movementClasses": sorted({left_class, right_class}),
                        "intersectionType": "point",
                        "position": position,
                        "mixedPedestrianMaterialTraffic": mixed,
                        "crosswalkMarkingIds": marking_ids,
                        "crosswalkCoverageStatus": (
                            "marked" if marking_ids else "unmarked"
                        ),
                        "evidenceStatus": "derived",
                    })
            else:
                centroid = intersection.centroid
                crossings.append({
                    "crossingId": _stable_id(
                        "route-crossing",
                        {"routeIds": route_ids, "type": "shared_segment"},
                    ),
                    "routeIds": route_ids,
                    "routeLabels": [
                        str(left.get("label") or left_id),
                        str(right.get("label") or right_id),
                    ],
                    "routeKinds": [
                        _aisle_kind_for_route(left),
                        _aisle_kind_for_route(right),
                    ],
                    "movementClasses": sorted({left_class, right_class}),
                    "intersectionType": "shared_segment",
                    "position": {
                        "x": round(float(centroid.x), 6),
                        "z": round(float(centroid.y), 6),
                    },
                    "mixedPedestrianMaterialTraffic": mixed,
                    "crosswalkMarkingIds": [],
                    "crosswalkCoverageStatus": "not_applicable",
                    "evidenceStatus": "derived",
                })
    crossings.sort(key=lambda item: item["crossingId"])

    isolated_ids = sorted(
        zone_id for zone_id, neighbors in undirected.items() if not neighbors
    )
    terminal_ids = sorted(
        zone_id for zone_id, neighbors in undirected.items() if len(neighbors) == 1
    )
    active_ids = [zone_id for zone_id in zone_by_id if undirected[zone_id]]
    mutually_reachable = all(
        all(
            target_id in _reachable_zone_ids(directed, source_id)
            for target_id in active_ids
        )
        for source_id in active_ids
    ) if active_ids else False
    return {
        "status": "complete" if not unresolved_bindings else "incomplete",
        "routeKindFilter": route_kind,
        "departmentCount": len(zones),
        "routeCount": len(filtered_routes),
        "networkComponentCount": len(components),
        "components": components,
        "edgeCount": len(network_edges),
        "edges": network_edges,
        "unconnectedDepartmentIds": isolated_ids,
        "unconnectedDepartmentLabels": [
            zone_by_id[item]["label"] for item in isolated_ids
        ],
        "topologicalDeadEndDepartmentIds": terminal_ids,
        "topologicalDeadEndDepartmentLabels": [
            zone_by_id[item]["label"] for item in terminal_ids
        ],
        "directionallyMutuallyReachable": mutually_reachable,
        "unresolvedRouteBindingIds": sorted(set(unresolved_bindings)),
        "crossingCount": len(crossings),
        "mixedTrafficPointCrossingCount": sum(
            item["intersectionType"] == "point"
            and item["mixedPedestrianMaterialTraffic"] is True
            for item in crossings
        ),
        "unmarkedMixedTrafficPointCrossingCount": sum(
            item["intersectionType"] == "point"
            and item["mixedPedestrianMaterialTraffic"] is True
            and item["crosswalkCoverageStatus"] == "unmarked"
            for item in crossings
        ),
        "crossings": crossings,
        "query": {
            "sourceDepartment": source["label"] if source else None,
            "targetDepartment": target["label"] if target else None,
            "reachable": (
                target["zoneId"] in reachable_ids
                if source is not None and target is not None
                else None
            ),
            "reachableDepartmentLabels": [
                zone_by_id[item]["label"] for item in reachable_ids
            ],
            "path": query_path,
        },
        "qualification": (
            "Reachability and dead ends are derived from authored route-to-department "
            "bindings and route direction. Crosswalk coverage means an authored "
            "crosswalk polygon covers an exact centerline intersection. These results "
            "do not establish traffic safety, capacity, travel time, or regulatory "
            "compliance."
        ),
    }


def _reachable_zone_ids(
    graph: Mapping[str, set[str]],
    source_zone_id: str,
) -> set[str]:
    seen = {source_zone_id}
    pending = [source_zone_id]
    while pending:
        current = pending.pop()
        for neighbor in graph.get(current, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return seen


def _zone_ids_for_route(route: Mapping[str, Any]) -> list[str]:
    extensions = route.get("extensions")
    aisle = (
        extensions.get("facilityAisle")
        if isinstance(extensions, Mapping)
        and isinstance(extensions.get("facilityAisle"), Mapping)
        else None
    )
    if not isinstance(aisle, Mapping):
        return []
    result = [str(aisle.get("sourceZoneId") or "")]
    result.extend(str(item) for item in aisle.get("viaZoneIds", []))
    result.append(str(aisle.get("targetZoneId") or ""))
    return [item for item in result if item]


def _collapse_orthogonal_path(
    points: Sequence[tuple[float, float]],
) -> list[dict[str, float]]:
    collapsed: list[tuple[float, float]] = []
    for point in points:
        rounded = (round(float(point[0]), 6), round(float(point[1]), 6))
        if collapsed and rounded == collapsed[-1]:
            continue
        collapsed.append(rounded)
        while len(collapsed) >= 3:
            a, b, c = collapsed[-3:]
            if (
                abs(a[0] - b[0]) <= G2_COORDINATE_TOLERANCE_METERS
                and abs(b[0] - c[0]) <= G2_COORDINATE_TOLERANCE_METERS
            ) or (
                abs(a[1] - b[1]) <= G2_COORDINATE_TOLERANCE_METERS
                and abs(b[1] - c[1]) <= G2_COORDINATE_TOLERANCE_METERS
            ):
                collapsed.pop(-2)
            else:
                break
    return [_point(x, z) for x, z in collapsed]


def _deterministic_free_path(
    layout: Mapping[str, Any],
    route: Mapping[str, Any],
    obstacle_routes: Sequence[Mapping[str, Any]],
    minimum_separation_meters: float,
    *,
    static_obstacle_shapes: Sequence[Any] = (),
) -> list[dict[str, float]]:
    """Route one corridor through bound zones on an exact orthogonal graph."""

    _require_geometry_engine()
    width, depth = _plan_dimensions(layout)
    route_width = _finite_positive(route.get("corridorWidth"), "route width")
    radius = route_width / 2.0
    if width <= route_width or depth <= route_width:
        raise FacilityCirculationError(
            "facility_circulation_conflict_resolution_infeasible",
            "The route corridor cannot fit inside the facility envelope.",
        )
    expanded_obstacles = []
    for obstacle_route in obstacle_routes:
        shape = _route_corridor(obstacle_route)
        if shape is not None:
            expanded_obstacles.append(
                shape.buffer(
                    radius + minimum_separation_meters,
                    cap_style=2,
                    join_style=2,
                )
            )
    for shape in static_obstacle_shapes:
        if shape is None or shape.is_empty:
            continue
        expanded_obstacles.append(
            shape.buffer(
                radius + minimum_separation_meters,
                cap_style=2,
                join_style=2,
            )
        )
    obstacle_union = (
        unary_union(expanded_obstacles) if expanded_obstacles else None
    )
    obstacle_interior = (
        obstacle_union.buffer(-G21_GEOMETRY_EPSILON_METERS)
        if obstacle_union is not None and not obstacle_union.is_empty
        else None
    )
    prepared_obstacle = (
        prep(obstacle_interior)
        if obstacle_interior is not None and not obstacle_interior.is_empty
        else None
    )
    zones = {item["zoneId"]: item for item in _zone_records(layout)}
    required_zone_ids = _zone_ids_for_route(route)
    if len(required_zone_ids) < 2 or any(
        zone_id not in zones for zone_id in required_zone_ids
    ):
        raise FacilityCirculationError(
            "facility_circulation_department_bindings_missing",
            "Conflict resolution requires complete route-to-department bindings.",
        )

    xs = {radius, width - radius}
    zs = {radius, depth - radius}
    # Unrelated zone boundaries are not obstacles and add a quadratic number
    # of lattice nodes on dense hierarchical layouts. Only bound zones supply
    # route anchors; obstacle edges supply the remaining deterministic lanes.
    for zone_id in required_zone_ids:
        zone = zones[zone_id]
        xs.update({
            min(max(float(zone["minimumX"]), radius), width - radius),
            min(max(float(zone["centerX"]), radius), width - radius),
            min(max(float(zone["maximumX"]), radius), width - radius),
        })
        zs.update({
            min(max(float(zone["minimumZ"]), radius), depth - radius),
            min(max(float(zone["centerZ"]), radius), depth - radius),
            min(max(float(zone["maximumZ"]), radius), depth - radius),
        })
    for shape in expanded_obstacles:
        minimum_x, minimum_z, maximum_x, maximum_z = shape.bounds
        xs.update({
            min(max(minimum_x, radius), width - radius),
            min(max(maximum_x, radius), width - radius),
        })
        zs.update({
            min(max(minimum_z, radius), depth - radius),
            min(max(maximum_z, radius), depth - radius),
        })
    x_values = sorted(round(value, 6) for value in xs)
    z_values = sorted(round(value, 6) for value in zs)

    def point_is_free(x: float, z: float) -> bool:
        if not (
            radius - G2_COORDINATE_TOLERANCE_METERS
            <= x
            <= width - radius + G2_COORDINATE_TOLERANCE_METERS
            and radius - G2_COORDINATE_TOLERANCE_METERS
            <= z
            <= depth - radius + G2_COORDINATE_TOLERANCE_METERS
        ):
            return False
        return not (
            prepared_obstacle is not None
            and prepared_obstacle.covers(Point(x, z))
        )

    nodes = sorted(
        (x, z)
        for x in x_values
        for z in z_values
        if point_is_free(x, z)
    )
    node_set = set(nodes)
    adjacency: dict[tuple[float, float], list[tuple[float, float]]] = {
        node: [] for node in nodes
    }

    def segment_is_free(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return not (
            prepared_obstacle is not None
            and prepared_obstacle.intersects(LineString([a, b]))
        )

    for z in z_values:
        row = [(x, z) for x in x_values if (x, z) in node_set]
        for left, right in zip(row, row[1:]):
            if segment_is_free(left, right):
                adjacency[left].append(right)
                adjacency[right].append(left)
    for x in x_values:
        column = [(x, z) for z in z_values if (x, z) in node_set]
        for lower, upper in zip(column, column[1:]):
            if segment_is_free(lower, upper):
                adjacency[lower].append(upper)
                adjacency[upper].append(lower)
    for neighbours in adjacency.values():
        neighbours.sort()

    anchors: list[tuple[float, float]] = []
    for zone_id in required_zone_ids:
        zone = zones[zone_id]
        candidates = [
            node for node in nodes
            if (
                float(zone["minimumX"]) - G2_COORDINATE_TOLERANCE_METERS
                <= node[0]
                <= float(zone["maximumX"]) + G2_COORDINATE_TOLERANCE_METERS
                and float(zone["minimumZ"]) - G2_COORDINATE_TOLERANCE_METERS
                <= node[1]
                <= float(zone["maximumZ"]) + G2_COORDINATE_TOLERANCE_METERS
            )
        ]
        if not candidates:
            raise FacilityCirculationError(
                "facility_circulation_conflict_resolution_infeasible",
                "No conflict-free route anchor is available in a bound department.",
                details={"zoneId": zone_id, "label": zone["label"]},
            )
        anchors.append(min(
            candidates,
            key=lambda item: (
                abs(item[0] - float(zone["centerX"]))
                + abs(item[1] - float(zone["centerZ"])),
                item,
            ),
        ))

    def shortest_path(
        start: tuple[float, float],
        goal: tuple[float, float],
    ) -> list[tuple[float, float]]:
        def heuristic(node: tuple[float, float]) -> float:
            return abs(node[0] - goal[0]) + abs(node[1] - goal[1])

        queue: list[tuple[Any, ...]] = [
            (heuristic(start), 0.0, 0, start, "")
        ]
        best: dict[
            tuple[tuple[float, float], str | None], tuple[float, int]
        ] = {
            (start, None): (0.0, 0)
        }
        previous: dict[
            tuple[tuple[float, float], str],
            tuple[tuple[float, float], str | None],
        ] = {}
        final_state: tuple[tuple[float, float], str | None] | None = None
        while queue:
            _estimated, distance, turns, node, heading_key = heapq.heappop(queue)
            heading = heading_key or None
            state = (node, heading)
            if best.get(state) != (distance, turns):
                continue
            if node == goal:
                final_state = state
                break
            for neighbour in adjacency.get(node, []):
                next_heading = "x" if neighbour[0] != node[0] else "z"
                edge = abs(neighbour[0] - node[0]) + abs(neighbour[1] - node[1])
                candidate = (
                    round(distance + edge, 6),
                    turns + int(heading is not None and heading != next_heading),
                )
                next_state = (neighbour, next_heading)
                if next_state in best and best[next_state] <= candidate:
                    continue
                best[next_state] = candidate
                previous[next_state] = state
                heapq.heappush(
                    queue,
                    (
                        round(candidate[0] + heuristic(neighbour), 6),
                        candidate[0],
                        candidate[1],
                        neighbour,
                        next_heading,
                    ),
                )
        if final_state is None:
            raise FacilityCirculationError(
                "facility_circulation_conflict_resolution_infeasible",
                "No deterministic conflict-free path satisfies the route bindings.",
            )
        path = [final_state[0]]
        state = final_state
        while state[0] != start:
            state = previous[(state[0], state[1])]
            path.append(state[0])
        path.reverse()
        return path

    complete: list[tuple[float, float]] = []
    for start, goal in zip(anchors, anchors[1:]):
        segment = shortest_path(start, goal)
        complete.extend(segment if not complete else segment[1:])
    result = _collapse_orthogonal_path(complete)
    if len(result) < 2:
        raise FacilityCirculationError(
            "facility_circulation_conflict_resolution_infeasible",
            "Conflict resolution produced a degenerate route.",
        )
    return result


def _route_heading(
    points: Sequence[Mapping[str, Any]],
    *,
    from_start: bool,
) -> float:
    segments = list(zip(points, points[1:]))
    pairs = segments if from_start else reversed(segments)
    for first, second in pairs:
        delta_x = float(second["x"]) - float(first["x"])
        delta_z = float(second["z"]) - float(first["z"])
        if (
            abs(delta_x) > G2_COORDINATE_TOLERANCE_METERS
            or abs(delta_z) > G2_COORDINATE_TOLERANCE_METERS
        ):
            return math.atan2(delta_z, delta_x)
    raise FacilityCirculationError(
        "facility_circulation_geometry_degenerate",
        "The route has no measurable heading for vehicle validation.",
    )


def _published_vehicle_profile(
    normalized_request: Mapping[str, Any],
    obstacle_context: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str | None]:
    profile_id = normalized_request.get("vehicleProfileId")
    profile_revision = normalized_request.get("vehicleProfileRevision")
    if profile_id is None and profile_revision is None:
        return None, None
    raw = obstacle_context.get("vehicleProfile")
    if not isinstance(raw, Mapping):
        raise FacilityCirculationError(
            "facility_circulation_vehicle_profile_unavailable",
            "The requested published vehicle profile is unavailable.",
        )
    document = raw.get("document")
    revision = str(raw.get("revision") or "")
    if (
        raw.get("status") != "published"
        or not isinstance(document, Mapping)
        or str(document.get("vehicleProfileId") or "") != str(profile_id)
        or revision != str(profile_revision)
    ):
        raise FacilityCirculationError(
            "facility_circulation_vehicle_profile_unavailable",
            "Vehicle routing requires the exact published profile revision.",
        )
    profile = deepcopy(dict(document))
    profile["vehicleProfileRevision"] = revision
    return profile, revision


def _vehicle_obstacle_aware_path(
    layout: Mapping[str, Any],
    route: Mapping[str, Any],
    obstacle_shapes: Sequence[tuple[str, Any]],
    *,
    clearance_meters: float,
    vehicle_profile: Mapping[str, Any],
    vehicle_revision: str,
    allow_reverse: bool | None,
    context_revision: str,
) -> dict[str, Any]:
    points = [
        point
        for point in route.get("centerline", [])
        if isinstance(point, Mapping)
    ]
    if len(points) < 2:
        raise FacilityCirculationError(
            "facility_circulation_geometry_degenerate",
            "Vehicle routing requires an existing route centerline.",
        )
    width, depth = _plan_dimensions(layout)
    corridor_width = _finite_positive(
        route.get("corridorWidth"), "route width"
    )
    # The heading-lattice validates the full vehicle footprint. Expanding the
    # obstacles by the requested corridor radius is conservative, but it means
    # every accepted vehicle route also keeps the displayed corridor clear.
    expansion = corridor_width / 2.0 + clearance_meters
    expanded_obstacles = []
    for obstacle_id, shape in obstacle_shapes:
        expanded = shape.buffer(expansion, cap_style=2, join_style=2)
        if expanded.is_empty:
            continue
        expanded_obstacles.append({
            "obstacleId": obstacle_id,
            "boundary": _polygon_boundary(expanded),
        })
    start = {
        "x": float(points[0]["x"]),
        "y": float(points[0].get("y", 0.0)),
        "z": float(points[0]["z"]),
        "heading": _route_heading(points, from_start=True),
    }
    goal = {
        "x": float(points[-1]["x"]),
        "y": float(points[-1].get("y", 0.0)),
        "z": float(points[-1]["z"]),
        "heading": _route_heading(points, from_start=False),
    }
    minimum_resolution = max(width, depth) / float(
        G22_MAXIMUM_VEHICLE_GRID_CELLS_PER_AXIS
    )
    grid_resolution = max(
        0.5,
        math.ceil(minimum_resolution * 2.0 - 1e-12) / 2.0,
    )
    result = plan_forklift_route(
        start,
        goal,
        vehicle_profile,
        traversable_polygons=[[
            {"x": 0.0, "z": 0.0},
            {"x": width, "z": 0.0},
            {"x": width, "z": depth},
            {"x": 0.0, "z": depth},
        ]],
        obstacles=expanded_obstacles,
        allow_reverse=allow_reverse,
        grid_resolution_meters=grid_resolution,
        source_revisions={
            "layout": layout_revision(layout),
            "obstacleContext": context_revision,
            "vehicle": vehicle_revision,
        },
    )
    if result.get("accepted") is not True:
        raise FacilityCirculationError(
            "facility_circulation_vehicle_route_infeasible",
            "No route satisfies the published vehicle envelope and turning constraints.",
            details={"findings": deepcopy(result.get("findings") or [])},
        )
    result["gridResolutionMeters"] = grid_resolution
    return result


def compile_obstacle_aware_circulation_operations(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    obstacle_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reroute one generated aisle around static revision-bound geometry."""

    normalized = (
        deepcopy(dict(request))
        if request.get("scope") == G2_CIRCULATION_SCOPE
        and request.get("action") == "avoid_obstacles"
        else normalize_circulation_request(request, layout)
    )
    context = normalize_circulation_obstacle_context(obstacle_context)
    route_id = str(normalized.get("routeId") or "")
    route = next(
        (
            item
            for item in layout.get("routes", [])
            if isinstance(item, Mapping)
            and str(item.get("routeId") or "") == route_id
        ),
        None,
    )
    if route is None:
        raise FacilityCirculationError(
            "facility_circulation_route_not_found",
            "The route selected for obstacle avoidance is not in the active draft.",
        )
    aisle_extension = (route.get("extensions") or {}).get("facilityAisle")
    original_binding = {
        key: deepcopy(aisle_extension.get(key))
        for key in ("sourceZoneId", "targetZoneId", "viaZoneIds")
        if isinstance(aisle_extension, Mapping)
    }
    canonical_before = canonicalize_layout(layout)
    department_geometry_revision = hashlib.sha256(
        _canonical_bytes(canonical_before.get("zones", []))
    ).hexdigest()
    static_layout_revision = hashlib.sha256(
        _canonical_bytes({
            "floorMarkings": canonical_before.get("floorMarkings", []),
            "placements": canonical_before.get("placements", []),
        })
    ).hexdigest()
    clearance = float(normalized.get("minimumClearanceMeters") or 0.0)
    obstacles = _static_obstacle_records(layout, context)
    obstacle_shapes = [
        (
            item["obstacleId"],
            _polygon_from_boundary(
                item["boundary"], f"obstacle[{item['obstacleId']}].boundary"
            ),
        )
        for item in obstacles
    ]
    before = analyze_primary_circulation_obstacles(
        layout,
        context,
        minimum_clearance_meters=clearance,
    )
    route_conflicts = [
        item for item in before["conflicts"] if item["routeId"] == route_id
    ]
    vehicle_profile, vehicle_revision = _published_vehicle_profile(
        normalized, context
    )
    if not route_conflicts and vehicle_profile is None:
        return {
            "stageId": "primary_circulation",
            "selectedCommandIds": ["aisle"],
            "operations": [],
            "plannedInstanceCount": 0,
            "normalizedRequest": normalized,
            "assumptions": list(normalized.get("assumptions") or []),
            "validationPlan": ["static_obstacle_geometry_already_clear"],
            "expectedSummary": {
                "routeId": route_id,
                "beforeConflictCount": 0,
                "afterConflictCount": 0,
                "modifiedRouteIds": [],
                "minimumClearanceMeters": clearance,
                "clearanceAuthority": normalized.get("clearanceAuthority"),
                "vehicleTurningValidated": False,
                "obstacleContextRevision": context["contextRevision"],
                "routeWidthMeters": float(route.get("corridorWidth") or 0.0),
                "departmentBinding": original_binding,
                "departmentGeometryRevision": department_geometry_revision,
                "staticLayoutRevision": static_layout_revision,
                "saved": False,
            },
        }
    if vehicle_profile is not None and vehicle_revision is not None:
        planned = _vehicle_obstacle_aware_path(
            layout,
            route,
            obstacle_shapes,
            clearance_meters=clearance,
            vehicle_profile=vehicle_profile,
            vehicle_revision=vehicle_revision,
            allow_reverse=normalized.get("allowReverse"),
            context_revision=context["contextRevision"],
        )
        centerline = _aisle_centerline_for_compiler(planned["centerline"])
        vehicle_validated = True
        swept_summary = {
            "schemaVersion": 1,
            "status": "validated",
            "routingEngineVersion": str(planned["routingEngineVersion"]),
            "routerVersion": str(planned["routerVersion"]),
            "poseCount": len(planned.get("poses") or []),
            "minimumTurningRadiusMeters": float(
                (vehicle_profile.get("steeringLimits") or {})[
                    "minimumTurningRadiusMeters"
                ]
            ),
            "gridResolutionMeters": float(
                planned["gridResolutionMeters"]
            ),
            "reverseUsed": bool(planned.get("reverseUsed")),
        }
    else:
        centerline = _deterministic_free_path(
            layout,
            route,
            [],
            clearance,
            static_obstacle_shapes=[shape for _, shape in obstacle_shapes],
        )
        vehicle_validated = False
        swept_summary = None
    awareness = {
        "schemaVersion": 1,
        "mode": "static_geometry",
        "obstacleContextRevision": context["contextRevision"],
        "minimumClearanceMeters": round(clearance, 6),
        "clearanceAuthority": str(normalized.get("clearanceAuthority")),
        "evaluatedObstacleIds": [item["obstacleId"] for item in obstacles],
        "avoidedObstacleIds": sorted({
            item["obstacleId"] for item in route_conflicts
        }),
        "vehicleTurningValidated": vehicle_validated,
    }
    patch: dict[str, Any] = {
        "centerline": centerline,
        "obstacleAwareness": awareness,
    }
    if vehicle_validated:
        patch.update({
            "routingMode": "vehicle",
            "vehicleProfileRef": {
                "vehicleProfileId": normalized["vehicleProfileId"],
                "vehicleProfileRevision": normalized[
                    "vehicleProfileRevision"
                ],
            },
            "sweptEnvelope": swept_summary,
        })
    operation = {"op": "edit_aisle", "routeId": route_id, "patch": patch}
    result = apply_facility_layout_operations(
        layout,
        [operation],
        base_revision=layout_revision(layout),
    )["document"]
    after = analyze_primary_circulation_obstacles(
        result,
        context,
        minimum_clearance_meters=clearance,
    )
    remaining = [
        item for item in after["conflicts"] if item["routeId"] == route_id
    ]
    if remaining:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_avoidance_infeasible",
            "A static obstacle conflict remains after deterministic rerouting.",
            details={"conflicts": remaining},
        )
    return {
        "stageId": "primary_circulation",
        "selectedCommandIds": ["aisle"],
        "operations": [operation],
        "plannedInstanceCount": 1,
        "normalizedRequest": normalized,
        "assumptions": list(normalized.get("assumptions") or []),
        "validationPlan": [
            "route_identity_preserved",
            "route_width_preserved",
            "department_bindings_preserved",
            "department_geometry_byte_parity",
            "placement_and_protected_region_byte_parity",
            "static_obstacle_geometric_non_overlap",
            (
                "published_vehicle_swept_volume_and_turning_radius"
                if vehicle_validated
                else "vehicle_turning_not_claimed"
            ),
            "authored_clearance_exact" if clearance else "no_clearance_claim",
        ],
        "expectedSummary": {
            "routeId": route_id,
            "beforeConflictCount": len(route_conflicts),
            "afterConflictCount": 0,
            "modifiedRouteIds": [route_id],
            "minimumClearanceMeters": clearance,
            "clearanceAuthority": normalized.get("clearanceAuthority"),
            "vehicleTurningValidated": vehicle_validated,
            "vehicleProfileId": normalized.get("vehicleProfileId"),
            "vehicleProfileRevision": normalized.get(
                "vehicleProfileRevision"
            ),
            "obstacleContextRevision": context["contextRevision"],
            "routeWidthMeters": float(route.get("corridorWidth") or 0.0),
            "departmentBinding": original_binding,
            "departmentGeometryRevision": department_geometry_revision,
            "staticLayoutRevision": static_layout_revision,
            "evaluatedObstacleCount": len(obstacles),
            "avoidedObstacleIds": awareness["avoidedObstacleIds"],
            "centerline": deepcopy(centerline),
            "saved": False,
            "qualification": after["qualification"],
        },
    }


def compile_obstacle_aware_circulation_network_operations(
    layout: Mapping[str, Any],
    route_ids: Sequence[str],
    obstacle_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reflow a route set on one shared deterministic obstacle graph."""

    _require_geometry_engine()
    canonical = canonicalize_layout(layout)
    selected_ids = [str(item or "").strip() for item in route_ids]
    if (
        not selected_ids
        or len(selected_ids) != len(set(selected_ids))
        or any(not item for item in selected_ids)
    ):
        raise FacilityCirculationError(
            "facility_circulation_network_routes_invalid",
            "Network reflow requires unique route IDs.",
        )
    by_id = {
        str(item.get("routeId") or ""): item
        for item in canonical.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    if any(item not in by_id for item in selected_ids):
        raise FacilityCirculationError(
            "facility_circulation_route_not_found",
            "A route selected for network reflow is not in the active draft.",
        )
    routes = [by_id[item] for item in selected_ids]
    if any(route.get("vehicleProfileRef") for route in routes):
        raise FacilityCirculationError(
            "facility_circulation_vehicle_profile_required",
            "Vehicle-bound routes require the exact vehicle-aware compiler.",
        )

    context = normalize_circulation_obstacle_context(obstacle_context)
    obstacles = _static_obstacle_records(canonical, context)
    obstacle_shapes = [
        _polygon_from_boundary(
            item["boundary"], f"obstacle[{item['obstacleId']}].boundary"
        )
        for item in obstacles
    ]
    before = analyze_primary_circulation_obstacles(canonical, context)
    conflicts_by_route = {item: [] for item in selected_ids}
    for finding in before["conflicts"]:
        route_id = str(finding.get("routeId") or "")
        if route_id in conflicts_by_route:
            conflicts_by_route[route_id].append(finding)

    width, depth = _plan_dimensions(canonical)
    routing_width = max(
        _finite_positive(item.get("corridorWidth"), "route width")
        for item in routes
    )
    radius = routing_width / 2.0
    if width <= routing_width or depth <= routing_width:
        raise FacilityCirculationError(
            "facility_circulation_conflict_resolution_infeasible",
            "The route network cannot fit inside the facility envelope.",
        )
    expanded = [
        shape.buffer(radius, cap_style=2, join_style=2)
        for shape in obstacle_shapes
        if shape is not None and not shape.is_empty
    ]
    obstacle_union = unary_union(expanded) if expanded else None
    obstacle_interior = (
        obstacle_union.buffer(-G21_GEOMETRY_EPSILON_METERS)
        if obstacle_union is not None and not obstacle_union.is_empty
        else None
    )
    prepared_obstacle = (
        prep(obstacle_interior)
        if obstacle_interior is not None and not obstacle_interior.is_empty
        else None
    )
    zones = {item["zoneId"]: item for item in _zone_records(canonical)}
    bound_zone_ids = list(
        dict.fromkeys(
            zone_id
            for route in routes
            for zone_id in _zone_ids_for_route(route)
        )
    )
    if any(item not in zones for item in bound_zone_ids):
        raise FacilityCirculationError(
            "facility_circulation_department_bindings_missing",
            "Network reflow requires complete route-to-department bindings.",
        )

    grid = max(1.0, min(2.0, routing_width / 2.0))

    def regular_axis(limit: float) -> set[float]:
        usable = limit - 2.0 * radius
        count = max(1, int(math.floor(usable / grid)))
        result = {
            round(radius + index * grid, 6)
            for index in range(count + 1)
        }
        result.add(round(limit - radius, 6))
        return result

    xs = regular_axis(width)
    zs = regular_axis(depth)
    for zone_id in bound_zone_ids:
        zone = zones[zone_id]
        xs.add(round(min(max(float(zone["centerX"]), radius), width - radius), 6))
        zs.add(round(min(max(float(zone["centerZ"]), radius), depth - radius), 6))
    x_values = sorted(xs)
    z_values = sorted(zs)

    def is_free_point(x: float, z: float) -> bool:
        return not (
            prepared_obstacle is not None
            and prepared_obstacle.covers(Point(x, z))
        )

    nodes = [
        (x, z)
        for x in x_values
        for z in z_values
        if is_free_point(x, z)
    ]
    node_set = set(nodes)
    adjacency = {item: [] for item in nodes}

    def is_free_segment(
        left: tuple[float, float], right: tuple[float, float]
    ) -> bool:
        return not (
            prepared_obstacle is not None
            and prepared_obstacle.intersects(LineString([left, right]))
        )

    for z in z_values:
        row = [(x, z) for x in x_values if (x, z) in node_set]
        for left, right in zip(row, row[1:]):
            if is_free_segment(left, right):
                adjacency[left].append(right)
                adjacency[right].append(left)
    for x in x_values:
        column = [(x, z) for z in z_values if (x, z) in node_set]
        for lower, upper in zip(column, column[1:]):
            if is_free_segment(lower, upper):
                adjacency[lower].append(upper)
                adjacency[upper].append(lower)
    for neighbours in adjacency.values():
        neighbours.sort()

    def anchor(zone_id: str) -> tuple[float, float]:
        zone = zones[zone_id]
        candidates = [
            node
            for node in nodes
            if (
                float(zone["minimumX"]) - G2_COORDINATE_TOLERANCE_METERS
                <= node[0]
                <= float(zone["maximumX"]) + G2_COORDINATE_TOLERANCE_METERS
                and float(zone["minimumZ"]) - G2_COORDINATE_TOLERANCE_METERS
                <= node[1]
                <= float(zone["maximumZ"]) + G2_COORDINATE_TOLERANCE_METERS
            )
        ]
        if not candidates:
            raise FacilityCirculationError(
                "facility_circulation_conflict_resolution_infeasible",
                "No conflict-free network anchor is available in a bound area.",
                details={"zoneId": zone_id, "label": zone["label"]},
            )
        return min(
            candidates,
            key=lambda item: (
                abs(item[0] - float(zone["centerX"]))
                + abs(item[1] - float(zone["centerZ"])),
                item,
            ),
        )

    def shortest_path(
        start: tuple[float, float], goal: tuple[float, float]
    ) -> list[tuple[float, float]]:
        def heuristic(node: tuple[float, float]) -> float:
            return abs(node[0] - goal[0]) + abs(node[1] - goal[1])

        queue: list[tuple[Any, ...]] = [(heuristic(start), 0.0, 0, start, "")]
        best = {(start, None): (0.0, 0)}
        previous: dict[
            tuple[tuple[float, float], str],
            tuple[tuple[float, float], str | None],
        ] = {}
        final_state = None
        while queue:
            _estimate, distance, turns, node, heading_key = heapq.heappop(queue)
            heading = heading_key or None
            state = (node, heading)
            if best.get(state) != (distance, turns):
                continue
            if node == goal:
                final_state = state
                break
            for neighbour in adjacency.get(node, []):
                next_heading = "x" if neighbour[0] != node[0] else "z"
                candidate = (
                    round(
                        distance
                        + abs(neighbour[0] - node[0])
                        + abs(neighbour[1] - node[1]),
                        6,
                    ),
                    turns + int(heading is not None and heading != next_heading),
                )
                next_state = (neighbour, next_heading)
                if next_state in best and best[next_state] <= candidate:
                    continue
                best[next_state] = candidate
                previous[next_state] = state
                heapq.heappush(
                    queue,
                    (
                        round(candidate[0] + heuristic(neighbour), 6),
                        candidate[0],
                        candidate[1],
                        neighbour,
                        next_heading,
                    ),
                )
        if final_state is None:
            raise FacilityCirculationError(
                "facility_circulation_conflict_resolution_infeasible",
                "No deterministic conflict-free network path satisfies the route bindings.",
            )
        result = [final_state[0]]
        state = final_state
        while state[0] != start:
            state = previous[(state[0], state[1])]
            result.append(state[0])
        result.reverse()
        return result

    operations = []
    for route in routes:
        route_anchors = [anchor(item) for item in _zone_ids_for_route(route)]
        complete: list[tuple[float, float]] = []
        for start, goal in zip(route_anchors, route_anchors[1:]):
            segment = shortest_path(start, goal)
            complete.extend(segment if not complete else segment[1:])
        centerline = _collapse_orthogonal_path(complete)
        if len(centerline) < 2:
            raise FacilityCirculationError(
                "facility_circulation_conflict_resolution_infeasible",
                "Network reflow produced a degenerate route.",
            )
        route_id = str(route["routeId"])
        operations.append(
            {
                "op": "edit_aisle",
                "routeId": route_id,
                "patch": {
                    "centerline": centerline,
                    "obstacleAwareness": {
                        "schemaVersion": 1,
                        "mode": "static_geometry",
                        "obstacleContextRevision": context["contextRevision"],
                        "minimumClearanceMeters": 0.0,
                        "clearanceAuthority": "geometric_non_overlap_only",
                        "evaluatedObstacleIds": [item["obstacleId"] for item in obstacles],
                        "avoidedObstacleIds": sorted(
                            {
                                str(item["obstacleId"])
                                for item in conflicts_by_route[route_id]
                            }
                        ),
                        "vehicleTurningValidated": False,
                    },
                },
            }
        )
    result = apply_facility_layout_operations(
        canonical,
        operations,
        base_revision=layout_revision(canonical),
    )["document"]
    after = analyze_primary_circulation_obstacles(result, context)
    remaining = [
        item
        for item in after["conflicts"]
        if str(item.get("routeId") or "") in set(selected_ids)
    ]
    if remaining:
        raise FacilityCirculationError(
            "facility_circulation_obstacle_avoidance_infeasible",
            "A static obstacle conflict remains after network reflow.",
            details={"conflicts": remaining[:50], "total": len(remaining)},
        )
    return {
        "stageId": "primary_circulation",
        "selectedCommandIds": ["aisle"],
        "operations": operations,
        "plannedInstanceCount": len(operations),
        "validationPlan": [
            "route_identity_preserved",
            "route_width_preserved",
            "department_bindings_preserved",
            "shared_static_obstacle_geometric_non_overlap",
            "vehicle_turning_not_claimed",
            "no_clearance_claim",
        ],
        "expectedSummary": {
            "routeIds": selected_ids,
            "beforeConflictCount": sum(len(item) for item in conflicts_by_route.values()),
            "afterConflictCount": 0,
            "obstacleContextRevision": context["contextRevision"],
            "evaluatedObstacleCount": len(obstacles),
            "gridResolutionMeters": grid,
            "routingEnvelopeWidthMeters": routing_width,
            "vehicleTurningValidated": False,
            "saved": False,
            "qualification": after["qualification"],
        },
    }


def validate_obstacle_aware_circulation_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
    obstacle_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    route_id = str(expected.get("routeId") or "")
    route = next(
        (
            item
            for item in layout.get("routes", [])
            if isinstance(item, Mapping)
            and str(item.get("routeId") or "") == route_id
        ),
        None,
    )
    errors = []
    if route is None:
        errors.append("route_missing")
    else:
        if abs(
            float(route.get("corridorWidth") or 0.0)
            - float(expected.get("routeWidthMeters") or 0.0)
        ) > G2_COORDINATE_TOLERANCE_METERS:
            errors.append("route_width_changed")
        aisle = (route.get("extensions") or {}).get("facilityAisle")
        expected_binding = expected.get("departmentBinding")
        if not isinstance(aisle, Mapping):
            errors.append("aisle_metadata_missing")
        elif isinstance(expected_binding, Mapping):
            for key in ("sourceZoneId", "targetZoneId", "viaZoneIds"):
                if aisle.get(key) != expected_binding.get(key):
                    errors.append(f"department_binding_changed:{key}")
            awareness = aisle.get("obstacleAwareness")
            if expected.get("modifiedRouteIds") and not isinstance(
                awareness, Mapping
            ):
                errors.append("obstacle_awareness_missing")
            elif isinstance(awareness, Mapping):
                if awareness.get("obstacleContextRevision") != expected.get(
                    "obstacleContextRevision"
                ):
                    errors.append("obstacle_context_revision_mismatch")
                if bool(awareness.get("vehicleTurningValidated")) != bool(
                    expected.get("vehicleTurningValidated")
                ):
                    errors.append("vehicle_turning_status_mismatch")
    canonical_result = canonicalize_layout(layout)
    if hashlib.sha256(
        _canonical_bytes(canonical_result.get("zones", []))
    ).hexdigest() != expected.get("departmentGeometryRevision"):
        errors.append("department_geometry_changed")
    if hashlib.sha256(
        _canonical_bytes({
            "floorMarkings": canonical_result.get("floorMarkings", []),
            "placements": canonical_result.get("placements", []),
        })
    ).hexdigest() != expected.get("staticLayoutRevision"):
        errors.append("static_obstacle_geometry_changed")
    analysis = analyze_primary_circulation_obstacles(
        layout,
        obstacle_context,
        minimum_clearance_meters=float(
            expected.get("minimumClearanceMeters") or 0.0
        ),
    )
    remaining = [
        item for item in analysis["conflicts"] if item["routeId"] == route_id
    ]
    if len(remaining) != int(expected.get("afterConflictCount") or 0):
        errors.append("static_obstacle_conflict_remains")
    if expected.get("vehicleTurningValidated"):
        if not isinstance(route, Mapping) or not isinstance(
            route.get("vehicleProfileRef"), Mapping
        ):
            errors.append("vehicle_profile_binding_missing")
        else:
            ref = route["vehicleProfileRef"]
            if (
                ref.get("vehicleProfileId") != expected.get("vehicleProfileId")
                or ref.get("vehicleProfileRevision")
                != expected.get("vehicleProfileRevision")
            ):
                errors.append("vehicle_profile_binding_mismatch")
            swept = route.get("sweptEnvelope")
            if not isinstance(swept, Mapping) or swept.get("status") != "validated":
                errors.append("vehicle_swept_validation_missing")
    return {
        "status": "valid" if not errors else "invalid",
        "layoutRevision": layout_revision(layout),
        "routeId": route_id,
        "routeObstacleConflictCount": len(remaining),
        "vehicleTurningValidated": bool(
            expected.get("vehicleTurningValidated")
        ),
        "errors": errors,
        "qualification": analysis["qualification"],
    }


def compile_circulation_conflict_resolution_operations(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = (
        deepcopy(dict(request))
        if request.get("scope") == G2_CIRCULATION_SCOPE
        and request.get("action") == "resolve_conflicts"
        else normalize_circulation_request(request, layout)
    )
    before = analyze_primary_circulation_conflicts(layout)
    if before["mixedTrafficConflictCount"] == 0:
        return {
            "stageId": "primary_circulation",
            "selectedCommandIds": ["aisle"],
            "operations": [],
            "plannedInstanceCount": 0,
            "normalizedRequest": normalized,
            "assumptions": list(normalized.get("assumptions") or []),
            "validationPlan": ["mixed_traffic_geometry_already_clear"],
            "expectedSummary": {
                "beforeConflictCount": 0,
                "afterConflictCount": 0,
                "modifiedRouteIds": [],
                "minimumSeparationMeters": float(
                    normalized.get("minimumSeparationMeters") or 0.0
                ),
                "saved": False,
            },
        }
    routes = [
        deepcopy(dict(route)) for route in layout.get("routes", [])
        if isinstance(route, Mapping)
    ]
    route_by_id = {str(route.get("routeId") or ""): route for route in routes}
    separation = float(normalized.get("minimumSeparationMeters") or 0.0)

    def total_length(document: Mapping[str, Any]) -> float:
        return round(sum(
            float(line.length)
            for route in document.get("routes", [])
            if isinstance(route, Mapping)
            for line in [_route_line(route)]
            if line is not None
        ), 6)

    before_length = total_length(layout)

    def build_alternative(adjustable_class: str) -> dict[str, Any]:
        adjustable_ids = sorted({
            route_id
            for conflict in before["conflicts"]
            for route_id in conflict["routeIds"]
            if route_id in route_by_id
            and _movement_class(route_by_id[route_id]) == adjustable_class
        })
        obstacle_class = (
            "material" if adjustable_class == "pedestrian" else "pedestrian"
        )
        if not adjustable_ids:
            return {
                "candidateId": f"reroute_{adjustable_class}",
                "adjustedMovementClass": adjustable_class,
                "status": "infeasible",
                "errorCode": "adjustable_route_missing",
            }
        working = deepcopy(dict(layout))
        operations: list[dict[str, Any]] = []
        try:
            for route_id in adjustable_ids:
                current_route = next(
                    route for route in working.get("routes", [])
                    if isinstance(route, Mapping)
                    and route.get("routeId") == route_id
                )
                obstacles = [
                    route for route in working.get("routes", [])
                    if isinstance(route, Mapping)
                    and _movement_class(route) == obstacle_class
                ]
                centerline = _deterministic_free_path(
                    working,
                    current_route,
                    obstacles,
                    separation,
                )
                operation = {
                    "op": "edit_aisle",
                    "routeId": route_id,
                    "patch": {"centerline": centerline},
                }
                operations.append(operation)
                working = apply_facility_layout_operations(
                    working,
                    [operation],
                    base_revision=layout_revision(working),
                )["document"]
            after = analyze_primary_circulation_conflicts(working)
            actual = after.get("mixedTrafficPairMinimumSeparationMeters")
            if after["mixedTrafficConflictCount"] != 0:
                raise FacilityCirculationError(
                    "facility_circulation_conflict_resolution_infeasible",
                    "A mixed-traffic conflict remains after deterministic rerouting.",
                )
            if separation > 0 and (
                actual is None
                or float(actual) + G2_COORDINATE_TOLERANCE_METERS < separation
            ):
                raise FacilityCirculationError(
                    "facility_circulation_separation_not_satisfied",
                    "The authored route separation could not be satisfied.",
                )
        except FacilityCirculationError as exc:
            return {
                "candidateId": f"reroute_{adjustable_class}",
                "adjustedMovementClass": adjustable_class,
                "status": "infeasible",
                "errorCode": exc.code,
            }
        candidate_length = total_length(working)
        return {
            "candidateId": f"reroute_{adjustable_class}",
            "adjustedMovementClass": adjustable_class,
            "status": "feasible",
            "modifiedRouteIds": adjustable_ids,
            "operationCount": len(operations),
            "totalCenterlineLengthMeters": candidate_length,
            "centerlineLengthDeltaMeters": round(
                candidate_length - before_length, 6
            ),
            "minimumSeparationMeters": actual,
            "operations": operations,
            "document": working,
        }

    alternatives = [
        build_alternative("pedestrian"),
        build_alternative("material"),
    ]
    adjustment_mode = str(normalized.get("adjustRouteKind") or "auto_shortest")
    feasible = [item for item in alternatives if item["status"] == "feasible"]
    if adjustment_mode == "auto_shortest":
        candidates = feasible
    else:
        candidates = [
            item for item in feasible
            if item["adjustedMovementClass"] == adjustment_mode
        ]
    if not candidates:
        raise FacilityCirculationError(
            "facility_circulation_conflict_resolution_infeasible",
            "No deterministic conflict-free alternative satisfies the requested adjustment.",
            details={
                "adjustRouteKind": adjustment_mode,
                "alternatives": [
                    {key: value for key, value in item.items()
                     if key not in {"operations", "document"}}
                    for item in alternatives
                ],
            },
        )
    selected = min(
        candidates,
        key=lambda item: (
            item["totalCenterlineLengthMeters"],
            item["operationCount"],
            item["candidateId"],
        ),
    )
    operations = selected["operations"]
    modified_ids = selected["modifiedRouteIds"]
    actual_separation = selected["minimumSeparationMeters"]
    public_alternatives = [
        {key: value for key, value in item.items()
         if key not in {"operations", "document"}}
        for item in alternatives
    ]
    return {
        "stageId": "primary_circulation",
        "selectedCommandIds": ["aisle"],
        "operations": operations,
        "plannedInstanceCount": len(operations),
        "normalizedRequest": normalized,
        "assumptions": list(normalized.get("assumptions") or []),
        "validationPlan": [
            "route_identity_preserved",
            "route_width_preserved",
            "department_bindings_preserved",
            "department_geometry_byte_parity",
            "mixed_traffic_geometric_non_overlap",
            "authored_separation_exact" if separation else "no_clearance_claim",
            "alternative_lengths_compared",
        ],
        "expectedSummary": {
            "beforeConflictCount": before["mixedTrafficConflictCount"],
            "afterConflictCount": 0,
            "modifiedRouteIds": modified_ids,
            "minimumSeparationMeters": separation,
            "actualMinimumSeparationMeters": actual_separation,
            "separationAuthority": normalized.get("separationAuthority"),
            "adjustmentMode": adjustment_mode,
            "selectedAlternativeId": selected["candidateId"],
            "alternatives": public_alternatives,
            "selectionQualification": (
                "The selected alternative minimizes total authored centerline "
                "length among feasible deterministic candidates. It does not prove "
                "operational optimality, capacity, safety, or compliance."
            ),
            "saved": False,
        },
    }


def _crossing_rotation_degrees(
    layout: Mapping[str, Any],
    route_ids: Sequence[str],
    position: Mapping[str, Any],
) -> float:
    routes = {
        str(route.get("routeId") or ""): route
        for route in layout.get("routes", [])
        if isinstance(route, Mapping)
    }
    ordered_ids = sorted(
        route_ids,
        key=lambda route_id: (
            0 if _aisle_kind_for_route(routes.get(route_id, {})) == "pedestrian" else 1,
            route_id,
        ),
    )
    crossing_point = Point(float(position["x"]), float(position["z"]))
    for route_id in ordered_ids:
        route = routes.get(route_id)
        if route is None:
            continue
        points = [
            (float(item["x"]), float(item["z"]))
            for item in route.get("centerline", [])
            if isinstance(item, Mapping) and "x" in item and "z" in item
        ]
        for left, right in zip(points, points[1:]):
            segment = LineString([left, right])
            if segment.distance(crossing_point) <= G2_COORDINATE_TOLERANCE_METERS:
                return round(
                    math.degrees(
                        math.atan2(right[1] - left[1], right[0] - left[0])
                    ),
                    6,
                )
    return 0.0


def _crossing_route_signature(route: Mapping[str, Any]) -> dict[str, Any]:
    extensions = route.get("extensions")
    aisle = (
        extensions.get("facilityAisle")
        if isinstance(extensions, Mapping)
        else None
    )
    aisle = aisle if isinstance(aisle, Mapping) else {}
    return {
        "routeId": route.get("routeId"),
        "label": route.get("label"),
        "corridorWidth": route.get("corridorWidth"),
        "centerline": deepcopy(route.get("centerline") or []),
        "sourceEndpoint": deepcopy(route.get("sourceEndpoint")),
        "targetEndpoint": deepcopy(route.get("targetEndpoint")),
        "aisleKind": aisle.get("aisleKind"),
        "direction": aisle.get("direction"),
        "sourceZoneId": aisle.get("sourceZoneId"),
        "targetZoneId": aisle.get("targetZoneId"),
        "viaZoneIds": deepcopy(aisle.get("viaZoneIds") or []),
        "areaAccounting": aisle.get("areaAccounting"),
        "widthAuthority": aisle.get("widthAuthority"),
    }


def compile_circulation_crossing_operations(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    defer_post_validation: bool = False,
) -> dict[str, Any]:
    """Compile one explicit crosswalk at an exact mixed-traffic point crossing."""

    normalized = (
        deepcopy(dict(request))
        if request.get("scope") == G2_CIRCULATION_SCOPE
        else normalize_circulation_request(request, layout)
    )
    if normalized.get("action") != "add_crossing":
        raise FacilityCirculationError(
            "facility_circulation_action_invalid",
            "Crossing compilation requires add_crossing.",
        )
    network = analyze_primary_circulation_network(layout)
    candidate = next(
        (
            item
            for item in network["crossings"]
            if item["crossingId"] == normalized["crossingId"]
            and sorted(item["routeIds"]) == sorted(normalized["crossingRouteIds"])
        ),
        None,
    )
    if candidate is None or candidate["intersectionType"] != "point":
        raise FacilityCirculationError(
            "facility_circulation_crossing_stale",
            "The selected point crossing changed before the marking was compiled.",
        )
    if candidate["crosswalkCoverageStatus"] == "marked":
        raise FacilityCirculationError(
            "facility_circulation_crossing_already_marked",
            "The selected crossing already has a crosswalk marking.",
        )
    canonical_before = canonicalize_layout(layout)
    marking_id = _stable_id(
        "fm-g23",
        {
            "layoutId": canonical_before.get("layoutId"),
            "crossingId": candidate["crossingId"],
        },
    )
    rotation = _crossing_rotation_degrees(
        canonical_before,
        candidate["routeIds"],
        candidate["position"],
    )
    label = normalized.get("label") or "Pedestrian crossing"
    network_revision = (
        trusted_canonical_layout_revision(canonical_before)
        if defer_post_validation
        else layout_revision(canonical_before)
    )
    marking = {
        "markingId": marking_id,
        "markingType": "crosswalk",
        "label": label,
        "semanticRole": "pedestrian_lane",
        "transform": {
            "position": {
                "x": float(candidate["position"]["x"]),
                "y": 0.0,
                "z": float(candidate["position"]["z"]),
            },
            "rotationDegrees": rotation,
        },
        "width": float(normalized["crossingWidthMeters"]),
        "depth": float(normalized["crossingDepthMeters"]),
        "fillColor": "#f8fafc",
        "strokeColor": "#0f172a",
        "opacity": 0.9,
        "text": "",
        "positionMode": "auto",
        "metadata": {
            "generatedBy": "facility_circulation_g23",
            "crossingId": candidate["crossingId"],
            "routeIds": list(candidate["routeIds"]),
            "positionAuthority": normalized["crossingPositionAuthority"],
            "dimensionAuthority": normalized["crossingDimensionAuthority"],
            "sourceWidth": normalized["crossingWidth"],
            "sourceDepth": normalized["crossingDepth"],
            "sourceWidthUnit": normalized["crossingWidthUnit"],
            "sourceDepthUnit": normalized["crossingDepthUnit"],
            "networkRevision": network_revision,
            "qualification": (
                "Marks an authored crossing location only; does not establish "
                "traffic safety or regulatory compliance."
            ),
        },
        "evidence": [],
    }
    expected = {
        "markingId": marking_id,
        "crossingId": candidate["crossingId"],
        "routeIds": list(candidate["routeIds"]),
        "position": deepcopy(marking["transform"]["position"]),
        "rotationDegrees": rotation,
        "widthMeters": marking["width"],
        "depthMeters": marking["depth"],
        "beforeRouteSignatures": {
            str(route.get("routeId") or ""): _crossing_route_signature(route)
            for route in canonical_before.get("routes", [])
            if isinstance(route, Mapping) and route.get("routeId")
        },
        "beforeRouteHash": hashlib.sha256(
            _canonical_bytes(canonical_before.get("routes", []))
        ).hexdigest(),
        "beforeZoneHash": hashlib.sha256(
            _canonical_bytes(canonical_before.get("zones", []))
        ).hexdigest(),
        "beforeFloorMarkingCount": len(canonical_before.get("floorMarkings", [])),
        "saved": False,
    }
    operation = {"op": "add_floor_marking", "floorMarking": marking}
    if not defer_post_validation:
        applied = apply_facility_layout_operations(
            canonical_before,
            [operation],
            base_revision=network_revision,
        )["document"]
        validation = validate_circulation_crossing_result(applied, expected)
        if validation["status"] != "valid":
            raise FacilityCirculationError(
                "facility_circulation_crossing_validation_failed",
                "The deterministic crossing marking failed post-condition validation.",
                details={"errors": validation["errors"]},
            )
    return {
        "stageId": "primary_circulation",
        "selectedCommandIds": ["floor-marking"],
        "operations": [operation],
        "plannedInstanceCount": 1,
        "normalizedRequest": normalized,
        "assumptions": [],
        "validationPlan": [
            "exact_point_crossing",
            "user_authored_dimensions",
            "route_identity_and_geometry_preserved",
            "department_geometry_preserved",
            "crosswalk_coverage_without_safety_claim",
        ],
        "expectedSummary": expected,
    }


def validate_circulation_crossing_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    canonical = canonicalize_layout(layout)
    markings = [
        item
        for item in canonical.get("floorMarkings", [])
        if isinstance(item, Mapping)
    ]
    marking = next(
        (
            item
            for item in markings
            if item.get("markingId") == expected.get("markingId")
        ),
        None,
    )
    errors = []
    expected_routes = expected.get("beforeRouteSignatures")
    current_routes = {
        str(route.get("routeId") or ""): _crossing_route_signature(route)
        for route in canonical.get("routes", [])
        if isinstance(route, Mapping) and route.get("routeId")
    }
    if (
        isinstance(expected_routes, Mapping)
        and current_routes != expected_routes
    ):
        errors.append("route_geometry_changed")
    if hashlib.sha256(_canonical_bytes(canonical.get("zones", []))).hexdigest() != (
        expected.get("beforeZoneHash")
    ):
        errors.append("department_geometry_changed")
    if len(markings) != int(expected.get("beforeFloorMarkingCount") or 0) + 1:
        errors.append("floor_marking_count_mismatch")
    if marking is None:
        errors.append("crosswalk_marking_missing")
    else:
        if marking.get("markingType") != "crosswalk":
            errors.append("crosswalk_marking_type_mismatch")
        if abs(float(marking.get("width") or 0) - float(expected["widthMeters"])) > (
            G2_COORDINATE_TOLERANCE_METERS
        ):
            errors.append("crosswalk_width_mismatch")
        if abs(float(marking.get("depth") or 0) - float(expected["depthMeters"])) > (
            G2_COORDINATE_TOLERANCE_METERS
        ):
            errors.append("crosswalk_depth_mismatch")
        metadata = marking.get("metadata")
        if not isinstance(metadata, Mapping) or sorted(metadata.get("routeIds", [])) != (
            sorted(expected.get("routeIds", []))
        ):
            errors.append("crosswalk_route_binding_mismatch")
        shape = _floor_marking_polygon(marking)
        point = Point(
            float(expected["position"]["x"]),
            float(expected["position"]["z"]),
        )
        if shape is None or not shape.intersects(point):
            errors.append("crosswalk_does_not_cover_crossing")
    network = analyze_primary_circulation_network(canonical)
    crossing = next(
        (
            item
            for item in network["crossings"]
            if item["crossingId"] == expected.get("crossingId")
        ),
        None,
    )
    if crossing is None or expected.get("markingId") not in (
        crossing.get("crosswalkMarkingIds") if crossing else []
    ):
        errors.append("crosswalk_coverage_not_derived")
    return {
        "status": "valid" if not errors else "invalid",
        "layoutRevision": layout_revision(canonical),
        "markingId": expected.get("markingId"),
        "crossingId": expected.get("crossingId"),
        "errors": errors,
        "qualification": (
            "The marking covers the exact route-centerline crossing. This does not "
            "establish safety, capacity, visibility, or regulatory compliance."
        ),
    }


def compile_primary_circulation_operations(
    layout: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    obstacle_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile one normalized request to existing route operations."""

    normalized = (
        deepcopy(dict(request))
        if request.get("scope") == G2_CIRCULATION_SCOPE
        else normalize_circulation_request(request, layout)
    )
    if normalized.get("action") == "resolve_conflicts":
        return compile_circulation_conflict_resolution_operations(
            layout, normalized
        )
    if normalized.get("action") == "avoid_obstacles":
        return compile_obstacle_aware_circulation_operations(
            layout,
            normalized,
            obstacle_context,
        )
    if normalized.get("action") == "add_crossing":
        return compile_circulation_crossing_operations(layout, normalized)
    width, depth = _plan_dimensions(layout)
    corridor_width = _finite_positive(normalized.get("widthMeters"), "widthMeters")
    half_width = corridor_width / 2.0
    if corridor_width > min(width, depth):
        raise FacilityCirculationError(
            "facility_circulation_width_exceeds_envelope",
            "The requested route width is larger than the facility's smaller dimension.",
            details={"widthMeters": corridor_width, "facility": [width, depth]},
        )
    assumptions = list(normalized.get("assumptions") or [])
    if normalized["action"] == "edit_recent":
        route = _recent_aisle(layout)
        route_id = str(route.get("routeId") or "")
        patch = {
            "corridorWidth": corridor_width,
            "aisleKind": normalized["routeKind"],
            "direction": normalized["direction"],
            "widthAuthority": normalized["widthAuthority"],
        }
        expected_centerline = None
        if normalized.get("pathChanged") is True:
            zones = _zone_records(layout)
            zone_by_key = {item["key"]: item for item in zones}
            authored = [
                normalized["sourceDepartment"],
                *normalized["viaDepartments"],
                normalized["targetDepartment"],
            ]
            selected = [zone_by_key[str(label).casefold()] for label in authored]
            centers = [
                (
                    min(
                        max(float(zone["centerX"]), half_width),
                        width - half_width,
                    ),
                    min(
                        max(float(zone["centerZ"]), half_width),
                        depth - half_width,
                    ),
                )
                for zone in selected
            ]
            expected_centerline = _orthogonal_centerline(centers)
            patch.update({
                "centerline": expected_centerline,
                "sourceZoneId": selected[0]["zoneId"],
                "targetZoneId": selected[-1]["zoneId"],
                "viaZoneIds": [item["zoneId"] for item in selected[1:-1]],
                "obstacleAwareness": None,
            })
        operation = {
            "op": "edit_aisle",
            "routeId": route_id,
            "patch": patch,
        }
        resulting_aisle = patch
        source_zone_id = str(
            resulting_aisle.get("sourceZoneId")
            or route["extensions"]["facilityAisle"].get("sourceZoneId")
            or ""
        )
        target_zone_id = str(
            resulting_aisle.get("targetZoneId")
            or route["extensions"]["facilityAisle"].get("targetZoneId")
            or ""
        )
        via_zone_ids = list(
            resulting_aisle.get("viaZoneIds")
            if "viaZoneIds" in resulting_aisle
            else route["extensions"]["facilityAisle"].get("viaZoneIds") or []
        )
        unaffected_routes = [
            item
            for item in canonicalize_layout(layout).get("routes", [])
            if isinstance(item, Mapping) and item.get("routeId") != route_id
        ]
        return {
            "stageId": "primary_circulation",
            "selectedCommandIds": ["aisle"],
            "operations": [operation],
            "plannedInstanceCount": 1,
            "normalizedRequest": normalized,
            "assumptions": assumptions,
            "validationPlan": [
                "route_identity_preserved",
                "route_width_exact",
                "facility_containment",
                "department_bindings_preserved",
                "unaffected_routes_preserved",
            ],
            "expectedSummary": {
                "routeId": route_id,
                "routeCount": len(layout.get("routes", [])),
                "sourceZoneId": source_zone_id,
                "targetZoneId": target_zone_id,
                "viaZoneIds": via_zone_ids,
                "widthMeters": corridor_width,
                "centerline": expected_centerline,
                "pathChanged": normalized.get("pathChanged") is True,
                "unaffectedRouteHash": hashlib.sha256(
                    _canonical_bytes(unaffected_routes)
                ).hexdigest(),
                "saved": False,
            },
        }
    zones = _zone_records(layout)
    zone_by_key = {item["key"]: item for item in zones}
    authored = [
        normalized["sourceDepartment"],
        *normalized["viaDepartments"],
        normalized["targetDepartment"],
    ]
    selected = [zone_by_key[str(label).casefold()] for label in authored]
    centers = []
    for zone in selected:
        x = min(max(float(zone["centerX"]), half_width), width - half_width)
        z = min(max(float(zone["centerZ"]), half_width), depth - half_width)
        centers.append((x, z))
    internal_centerline = normalized.get("compiledCenterline")
    centerline = (
        _aisle_centerline_for_compiler(internal_centerline)
        if internal_centerline is not None
        else _orthogonal_centerline(centers)
    )
    source = selected[0]
    target = selected[-1]
    via = selected[1:-1]
    route_label = normalized.get("label") or (
        f"{source['label']} to {target['label']} "
        f"{normalized['routeKind']} aisle"
    )
    route_id = str(normalized.get("routeId") or "").strip() or _stable_id(
        "rt-g2",
        {
            "layoutId": layout.get("layoutId"),
            "sourceZoneId": source["zoneId"],
            "targetZoneId": target["zoneId"],
            "viaZoneIds": [item["zoneId"] for item in via],
            "routeKind": normalized["routeKind"],
            "existingRouteIds": sorted(
                str(item.get("routeId") or "")
                for item in layout.get("routes", [])
                if isinstance(item, Mapping)
            ),
        },
    )
    operation = {
        "op": "add_aisle",
        "routeId": route_id,
        "aisle": {
            "label": route_label,
            "aisleKind": normalized["routeKind"],
            "direction": normalized["direction"],
            "corridorWidth": corridor_width,
            "centerline": centerline,
            "color": {
                "material": "#d9a514",
                "forklift": "#169fd5",
                "pedestrian": "#2f9d62",
            }[normalized["routeKind"]],
            "clearanceEvidenceStatus": "unverified",
            "sourceZoneId": source["zoneId"],
            "targetZoneId": target["zoneId"],
            "viaZoneIds": [item["zoneId"] for item in via],
            "areaAccounting": "overlay",
            "widthAuthority": normalized["widthAuthority"],
            "sourceRevisions": {
                "layoutBaseRevision": layout_revision(
                    canonicalize_layout(layout)
                )
            },
        },
    }
    return {
        "stageId": "primary_circulation",
        "selectedCommandIds": ["aisle"],
        "operations": [operation],
        "plannedInstanceCount": 1,
        "normalizedRequest": normalized,
        "assumptions": assumptions,
        "validationPlan": [
            "department_identity",
            "ordered_waypoints",
            "orthogonal_centerline",
            "facility_containment",
            "route_width_exact",
            "overlay_area_accounting",
        ],
        "expectedSummary": {
            "routeId": route_id,
            "routeCount": len(layout.get("routes", [])) + 1,
            "sourceZoneId": source["zoneId"],
            "targetZoneId": target["zoneId"],
            "viaZoneIds": [item["zoneId"] for item in via],
            "widthMeters": corridor_width,
            "centerline": deepcopy(centerline),
            "saved": False,
        },
    }


def validate_primary_circulation_result(
    layout: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    routes = [item for item in layout.get("routes", []) if isinstance(item, Mapping)]
    route = next(
        (item for item in routes if item.get("routeId") == expected.get("routeId")),
        None,
    )
    errors = []
    if route is None:
        errors.append("route_missing")
    else:
        extension = (
            (route.get("extensions") or {}).get("facilityAisle")
            if isinstance(route.get("extensions"), Mapping)
            else None
        )
        if not isinstance(extension, Mapping):
            errors.append("aisle_metadata_missing")
        else:
            if extension.get("sourceZoneId") != expected.get("sourceZoneId"):
                errors.append("source_zone_mismatch")
            if extension.get("targetZoneId") != expected.get("targetZoneId"):
                errors.append("target_zone_mismatch")
            if list(extension.get("viaZoneIds") or []) != list(expected.get("viaZoneIds") or []):
                errors.append("via_zone_mismatch")
            if extension.get("areaAccounting") != "overlay":
                errors.append("area_accounting_mismatch")
        if abs(float(route.get("corridorWidth") or 0) - float(expected["widthMeters"])) > G2_COORDINATE_TOLERANCE_METERS:
            errors.append("route_width_mismatch")
        if expected.get("centerline") is not None and list(
            route.get("centerline") or []
        ) != list(expected.get("centerline") or []):
            errors.append("route_centerline_mismatch")
        width, depth = _plan_dimensions(layout)
        margin = float(route.get("corridorWidth") or 0) / 2.0
        for point in route.get("centerline", []):
            x = float(point.get("x", -1))
            z = float(point.get("z", -1))
            if (
                x < margin - G2_COORDINATE_TOLERANCE_METERS
                or z < margin - G2_COORDINATE_TOLERANCE_METERS
                or x > width - margin + G2_COORDINATE_TOLERANCE_METERS
                or z > depth - margin + G2_COORDINATE_TOLERANCE_METERS
            ):
                errors.append("route_corridor_outside_envelope")
                break
    if len(routes) != int(expected["routeCount"]):
        errors.append("route_count_mismatch")
    if expected.get("unaffectedRouteHash") is not None:
        unaffected = [
            item
            for item in canonicalize_layout(layout).get("routes", [])
            if isinstance(item, Mapping)
            and item.get("routeId") != expected.get("routeId")
        ]
        if hashlib.sha256(_canonical_bytes(unaffected)).hexdigest() != expected.get(
            "unaffectedRouteHash"
        ):
            errors.append("unaffected_route_changed")
    return {
        "status": "valid" if not errors else "invalid",
        "layoutRevision": layout_revision(layout),
        "routeId": expected.get("routeId"),
        "routeCount": len(routes),
        "errors": errors,
    }


def validate_circulation_conflict_resolution_result(
    before_layout: Mapping[str, Any],
    after_layout: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    before_routes = {
        str(route.get("routeId") or ""): route
        for route in before_layout.get("routes", [])
        if isinstance(route, Mapping)
    }
    after_routes = {
        str(route.get("routeId") or ""): route
        for route in after_layout.get("routes", [])
        if isinstance(route, Mapping)
    }
    errors = []
    if before_layout.get("zones") != after_layout.get("zones"):
        errors.append("department_geometry_changed")
    if set(before_routes) != set(after_routes):
        errors.append("route_identity_changed")
    for route_id, before_route in before_routes.items():
        after_route = after_routes.get(route_id)
        if after_route is None:
            continue
        if before_route.get("corridorWidth") != after_route.get("corridorWidth"):
            errors.append(f"route_width_changed:{route_id}")
        before_aisle = (before_route.get("extensions") or {}).get("facilityAisle")
        after_aisle = (after_route.get("extensions") or {}).get("facilityAisle")
        for field in ("sourceZoneId", "targetZoneId", "viaZoneIds"):
            if (
                isinstance(before_aisle, Mapping)
                and isinstance(after_aisle, Mapping)
                and before_aisle.get(field) != after_aisle.get(field)
            ):
                errors.append(f"department_binding_changed:{route_id}:{field}")
    analysis = analyze_primary_circulation_conflicts(after_layout)
    if analysis["mixedTrafficConflictCount"] != int(
        expected.get("afterConflictCount") or 0
    ):
        errors.append("mixed_traffic_conflict_remains")
    separation = float(expected.get("minimumSeparationMeters") or 0.0)
    actual = analysis.get("mixedTrafficPairMinimumSeparationMeters")
    if separation > 0 and (
        actual is None
        or float(actual) + G2_COORDINATE_TOLERANCE_METERS < separation
    ):
        errors.append("authored_separation_not_met")
    return {
        "status": "valid" if not errors else "invalid",
        "layoutRevision": layout_revision(after_layout),
        "mixedTrafficConflictCount": analysis["mixedTrafficConflictCount"],
        "minimumSeparationMeters": actual,
        "modifiedRouteIds": list(expected.get("modifiedRouteIds") or []),
        "errors": errors,
        "qualification": analysis["qualification"],
    }


def connected_zone_ids(layout: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for route in layout.get("routes", []):
        if not isinstance(route, Mapping):
            continue
        extensions = route.get("extensions")
        aisle = extensions.get("facilityAisle") if isinstance(extensions, Mapping) else None
        if not isinstance(aisle, Mapping):
            continue
        for key in ("sourceZoneId", "targetZoneId"):
            value = str(aisle.get(key) or "").strip()
            if value:
                result.add(value)
        result.update(
            str(item).strip()
            for item in aisle.get("viaZoneIds", [])
            if str(item).strip()
        )
    return result


def disconnected_department_labels(layout: Mapping[str, Any]) -> list[str]:
    connected = connected_zone_ids(layout)
    return [
        str(zone["label"])
        for zone in _zone_records(layout)
        if str(zone["zoneId"]) not in connected
    ]


__all__ = [
    "G21_CONFLICT_SCOPE",
    "G22_OBSTACLE_SCOPE",
    "G23_NETWORK_SCOPE",
    "G2_CIRCULATION_SCOPE",
    "G2_DIRECTIONS",
    "G2_FACILITY_CIRCULATION_TOOL",
    "G2_ROUTE_KINDS",
    "FacilityCirculationError",
    "analyze_primary_circulation_conflicts",
    "analyze_primary_circulation_obstacles",
    "analyze_primary_circulation_network",
    "circulation_tool_spec",
    "compile_circulation_conflict_resolution_operations",
    "compile_obstacle_aware_circulation_operations",
    "compile_obstacle_aware_circulation_network_operations",
    "compile_circulation_crossing_operations",
    "compile_primary_circulation_operations",
    "connected_zone_ids",
    "disconnected_department_labels",
    "normalize_circulation_request",
    "normalize_circulation_obstacle_context",
    "parse_circulation_turn",
    "validate_circulation_conflict_resolution_result",
    "validate_obstacle_aware_circulation_result",
    "validate_circulation_crossing_result",
    "validate_primary_circulation_result",
]
