"""Deterministic intent boundary for Facility Layout chat requests.

This classifier is an authorization guard, not the semantic planner. It only
decides whether a turn may enter the preview-capable generation workflow.
False negatives are safer than treating a report, chart, or explanation as a
request to modify the layout.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Literal, Mapping, Sequence


FacilityLayoutIntent = Literal["generation", "analysis", "unrelated"]
FacilityActionMode = Literal["READ_ONLY", "PREVIEW", "COMMIT"]
FacilityRequestKind = Literal[
    "inspect",
    "measure",
    "compare",
    "recommend",
    "simulate",
    "exact_transform",
    "modify",
    "navigate",
    "render",
]

_COUNT_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_COUNT_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}
_COUNT_WORD_PATTERN = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|(?:twenty|thirty|forty)(?:[-\s](?:one|two|three|four|"
    r"five|six|seven|eight|nine))?|fifty)"
)
_FACILITY_DIMENSION_UNIT_PATTERN = (
    r"(?:mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|"
    r"m|met(?:er|re)s?|ft|feet|foot|in|inch(?:es)?)"
)
_COMPLETE_FACILITY_ACTION = re.compile(
    r"\b(?:build|create|generate|design|draft|make|replace|rebuild|"
    r"resize|change|update|reconfigure|start)\w*\b|\bnew\b",
    re.IGNORECASE,
)
_COMPLETE_FACILITY_TARGET = re.compile(
    r"\b(?:facility|factory|plant|warehouse)(?:\s+layout)?\b",
    re.IGNORECASE,
)
_COMPLETE_FACILITY_DIMENSIONS = re.compile(
    rf"\b(?P<width>\d+(?:\.\d+)?)\s*"
    rf"(?P<unit1>{_FACILITY_DIMENSION_UNIT_PATTERN})?\s*"
    rf"(?:x|\u00d7|by)\s*"
    rf"(?P<depth>\d+(?:\.\d+)?)\s*"
    rf"(?P<unit2>{_FACILITY_DIMENSION_UNIT_PATTERN})?\b",
    re.IGNORECASE,
)
_COMPLETE_DEPARTMENT_COUNT = re.compile(
    rf"\b(?P<count>\d{{1,2}}|{_COUNT_WORD_PATTERN})\s+"
    r"(?:(?:equal|equally)(?:[-\s]+sized)?\s+)?"
    r"(?:macro\s+)?departments?\b",
    re.IGNORECASE,
)
_COMPLETE_DEPARTMENT_TARGET = re.compile(
    r"\b(?:divide|partition|split|organize|organise|lay\s+out)\w*\b"
    r"|\b(?:with|into)\b[^.;!?]{0,80}\bdepartments?\b",
    re.IGNORECASE,
)
_DEPARTMENT_LABELS = re.compile(
    r"\b(?:macro\s+)?departments?\s+"
    r"(?:named|called|labelled|labeled)\s+(?P<labels>[^.!?]+)",
    re.IGNORECASE,
)
_EQUAL_DEPARTMENTS = re.compile(
    r"\b(?:equal|equally)(?:[-\s]+sized)?\s+(?:macro\s+)?departments?\b"
    r"|\bdepartments?\s+(?:of\s+)?(?:equal|the\s+same)\s+(?:area|size)\b",
    re.IGNORECASE,
)

_SPACE = re.compile(r"\s+")
_FACILITY_SCOPE = re.compile(
    r"\b(?:facilit(?:y|ies)|warehouses?|plants?|factories?|"
    r"2d\s*(?:/|and)\s*3d\s+(?:placements?|transforms?|render(?:ers?|ing)?)|"
    r"workcells?|work\s*cells?|manufacturing\s*cells?|layouts?|"
    r"machining\s+halls?|automation\s+(?:halls?|departments?|zones?)|"
    r"departments?|zones?|aisles?|routes?|floor\s+markings?|"
    r"cells?|stations?|configurations?|racks?|machines?|equipment|"
    r"assets?|workstations?|cncs?|"
    r"forklifts?|production\s+lines?|material\s+flow|clearances?|"
    r"utilities?)\b"
)
_PRESENTATION_TARGET = re.compile(
    r"\b(?:bar\s+charts?|pie\s+charts?|donut\s+charts?|heat\s*maps?|"
    r"charts?|graphs?|plots?|tables?|reports?|"
    r"summar(?:y|ies)|analys(?:is|es)|audits?|dashboards?|"
    r"visuali[sz]ations?|paretos?|histograms?|kpis?)\b"
)
_PRESENTATION_REFINEMENT = re.compile(
    r"\b(?:legends?|labels?|value(?:s|\s+labels?)?|counts?|"
    r"percent(?:age)?s?(?:\s+labels?)?|axes?|axis|series|categories|"
    r"colou?rs?|palettes?|sort(?:ed|ing)?|ascending|descending|"
    r"regenerat(?:e|ed|ing)|re-?render(?:ed|ing)?|re-?plot(?:ted|ting)?|"
    r"retry)\b"
)
_SPATIAL_TARGET = re.compile(
    r"\b(?:facilit(?:y|ies)|factor(?:y|ies)|plants?|"
    r"facility\s+layouts?|factory\s+layouts?|plant\s+layouts?|"
    r"warehouse\s+layouts?|layouts?|manufacturing\s+cells?|work\s*cells?|"
    r"workcells?|departments?|zones?|aisles?|routes?|floor\s+markings?|"
    r"racks?|machines?|equipment|assets?|placements?|workstations?|"
    r"cncs?|forklifts?|production\s+lines?|cells?)\b"
)
_DIRECT_MUTATION = re.compile(
    r"\b(?:mov(?:e|es|ed|ing)|plac(?:e|es|ed|ing)|add(?:s|ed|ing)?|"
    r"remov(?:e|es|ed|ing)|delet(?:e|es|ed|ing)|"
    r"resiz(?:e|es|ed|ing)|rotat(?:e|es|ed|ing)|"
    r"duplicat(?:e|es|ed|ing)|mirror(?:s|ed|ing)?|"
    r"swap(?:s|ped|ping)?|stack(?:s|ed|ing)?|attach(?:es|ed|ing)?|"
    r"(?<!keep-)clear(?:s|ed|ing)?|shift(?:s|ed|ing)?|reposition(?:s|ed|ing)?|"
    r"relocat(?:e|es|ed|ing))\b"
)
_AMBIGUOUS_ACTION = re.compile(
    r"\b(?:(?:build|create|generate|design|draft|propose|arrange|"
    r"optimi[sz]e|rearrange|improve|modify|update|draw|make|produce)\w*|"
    r"lay\s+out)\b"
)
_PREVIEW_TARGET = re.compile(
    r"\b(?:ghost\s+preview|layout\s+preview|spatial\s+preview|"
    r"2d(?:/3d|\s+and\s+3d)?\s+preview|proposal)\b"
)
_NEGATED_CLAUSE = re.compile(
    r"\b(?:do\s+not|don't|without|never)\b[^.;!?]*(?:[.;!?]|$)"
)
_READ_ONLY_CUE = re.compile(
    r"\b(?:review|inspect|audit|analy[sz]e|explain|compare|count|"
    r"list|summari[sz]e|report|show|identify|which|what|where|how|"
    r"capacity|fit|feasible|possible)\b"
)
_READ_ONLY_FEASIBILITY = re.compile(
    r"^(?:can|could|would)\s+(?:we|this|that|the|these|those|"
    r"(?!you\b)[a-z0-9_-]+)\b[^.;!?]*\b(?:add|fit|increase|expand|"
    r"accommodate|capacity|room|space)\b"
)
_READ_ONLY_ROUTE_FEASIBILITY = re.compile(
    r"^(?:can|could|would)\s+[^.;!?]{0,80}\b"
    r"(?:move|travel|reach|get|go|walk|drive|fly)\b[^.;!?]{0,80}"
    r"\b(?:from|to|between|through|along|across)\b"
)
_FOLLOW_UP_CUE = re.compile(
    r"^(?:yes|yeah|yep|sure|okay|ok|no|nope|continue|go\s+on|"
    r"show\s+me|do\s+that|that\s+one|the\s+same|more|why|how|"
    r"what\s+about)\b|\b(?:it|that|those|these|same|above|former|"
    r"latter|instead|rather\s+than)\b"
)
_SOCIAL_TURN = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|"
    r"thanks|thank\s+you|got\s+it|sounds\s+good)[.!?\s]*$"
)
_INTERROGATIVE_PREFIX = re.compile(
    r"^(?:what|which|where|when|why|how)\b"
)
_COMMIT_ACTION = re.compile(
    r"\b(?:apply|approve|commit|save|accept)\b[^.;!?]*"
    r"\b(?:preview|proposal|alternative|changes?)\b"
    r"|\b(?:apply|approve|commit|save|accept)\s+(?:it|that|this)\b"
)
_AFFIRMATIVE_FOLLOW_UP = re.compile(
    r"^(?:yes|yeah|yep|sure|ok|okay|please|go\s+ahead|do\s+that|"
    r"continue|proceed)[.!?\s]*$"
)
_PENDING_OFFER = re.compile(
    r"\b(?:would\s+you\s+like|do\s+you\s+want|want\s+me\s+to|"
    r"shall\s+i|should\s+i|may\s+i|i\s+can|let\s+me|"
    r"i\s+need\s+to|next\s+i\s+can)\b"
)
_NAVIGATION_REQUEST = re.compile(
    r"\b(?:take\s+me\s+to|fly\s+to|walk\s+to|navigate\s+to|"
    r"focus\s+(?:on|the\s+camera)|zoom\s+(?:to|in\s+on)|"
    r"show\s+(?:it|this|that|the\s+selected\s+\w+)\s+in\s+3d|"
    r"enter\s+(?:drone|walkthrough)|switch\s+to\s+(?:drone|walkthrough)|"
    r"start\s+(?:drone|walkthrough))\b"
)
_SIMULATION_REQUEST = re.compile(
    r"\b(?:simulat(?:e|ion)|what\s+would|alternative|scenario|"
    r"ghost\s+preview|preview\s+(?:an?|the)|propose\s+(?:an?|the)|"
    r"show\s+(?:an?|the)\s+(?:possible|candidate)\s+layout)\b"
)
_RECOMMENDATION_REQUEST = re.compile(
    r"\b(?:recommend|recommendation|suggest|advis(?:e|able)|"
    r"what\s+(?:would|should)\s+(?:you|we)\s+(?:change|check|improve|do)|"
    r"what\s+changes?\s+would\s+you\s+make|"
    r"highest[-\s]priority\s+(?:changes?|recommendations?))\b"
)
_COMPARISON_REQUEST = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|difference\s+between|"
    r"better\s+than|least|most|rank)\b"
)
_MEASUREMENT_REQUEST = re.compile(
    r"\b(?:measure|measurement|area|space|footprint|density|"
    r"utili[sz]ation|occupancy|distance|clearance|width|length|"
    r"percentage|percent|capacity|how\s+many|how\s+much|narrowest|"
    r"largest|smallest|longest|shortest)\b"
)
_PRECISE_TRANSLATION_ACTION = re.compile(
    r"\b(?:move|shift|reposition|relocate)\b"
)
_PRECISE_TRANSLATION_DISTANCE = re.compile(
    r"\b(?:\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?:mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|"
    r"m|met(?:er|re)s?|ft|feet|foot|in|inch(?:es)?)\b"
)
_PRECISE_TRANSLATION_DIRECTION = re.compile(
    r"\b(?:east|west|north|south|up|down|upward|downward)\b"
)
_NON_TRANSLATION_EDIT = re.compile(
    r"\b(?:add|build|clear|create|delete|duplicate|generate|mirror|"
    r"pattern|remove|resize|rotate|scale|stack|swap)\b"
)
_CURRENT_SELECTION_CUE = re.compile(
    r"\b(?:selected|selection|this\s+(?:machine|asset|equipment|"
    r"placement|item)|these\s+(?:machines|assets|placements|items))\b"
)

_FACILITY_METRIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "department_operational_utilization",
        re.compile(
            r"\b(?:operational(?:ly)?\s+(?:space\s+)?utili[sz]ation|"
            r"operationally\s+usable\s+(?:free\s+)?(?:area|space)|"
            r"usable\s+(?:free\s+)?space|usable\s+area)\b"
        ),
    ),
    (
        "department_known_planning_utilization",
        re.compile(
            r"\b(?:known\s+planning\s+(?:space\s+)?utili[sz]ation|"
            r"planning\s+(?:free\s+)?(?:area|space))\b"
        ),
    ),
    (
        "department_physical_occupancy",
        re.compile(
            r"\b(?:equipment|asset|physical)\s+(?:footprint|coverage|"
            r"occupancy|density|utili[sz]ation)|\boccupied\s+by\s+"
            r"(?:equipment|assets|machines)\b"
        ),
    ),
    (
        "contiguous_free_space",
        re.compile(
            r"\b(?:contiguous|continuous)\s+(?:open|free|usable)\s+"
            r"(?:area|space|region)|\blargest\s+(?:open|free)\s+region\b"
        ),
    ),
    (
        "actual_edge_clearance",
        re.compile(
            r"\b(?:actual|smallest|minimum|least|edge[-\s]to[-\s]edge)"
            r"[^.;!?]{0,60}\bclearance|\bclearance\s+between\b"
        ),
    ),
    (
        "route_usable_width",
        re.compile(
            r"\b(?:aisle|route|boulevard|walkway)[^.;!?]{0,50}"
            r"\b(?:width|narrowest)|\bnarrowest\s+(?:point|width)\b"
        ),
    ),
    (
        "placement_count",
        re.compile(
            r"\b(?:placement|asset|machine|equipment|station|rack|cell)"
            r"\s+counts?\b|\bhow\s+many\s+(?:placements?|assets?|"
            r"machines?|equipment|stations?|racks?|cells?)\b"
        ),
    ),
    (
        "department_gross_area",
        re.compile(
            r"\b(?:department|zone|facility|floor)\s+(?:gross\s+)?area\b|"
            r"\b(?:area|space|size)\s+(?:of|by|for)\s+(?:the\s+)?"
            r"(?:six\s+)?departments?\b|\bhow\s+much\s+space\s+does\b"
        ),
    ),
    (
        "geometric_free_area",
        re.compile(r"\b(?:geometric\s+)?free\s+(?:area|space)\b"),
    ),
)

_FACILITY_SPATIAL_ANALYSIS_PATTERNS: tuple[
    tuple[str, re.Pattern[str]], ...
] = (
    (
        "render_consistency",
        re.compile(
            r"\b(?:2d\s*(?:/|and|versus|vs\.?)\s*3d|"
            r"render(?:er|ing)?\s+(?:consistency|mismatch)|"
            r"placement\s+transforms?\s+.*mismatch)\b"
        ),
    ),
    (
        "drone_clearance",
        re.compile(
            r"\b(?:drone|flythrough|flight)\b[^.;!?]{0,100}"
            r"\b(?:clearance|collider|pass|fit|between|under|overhead|"
            r"obstruction|altitude)\b|"
            r"\b(?:clearance|collider|pass|between|under|overhead)\b"
            r"[^.;!?]{0,100}\bdrone\b"
        ),
    ),
    (
        "route_crossings",
        re.compile(
            r"\b(?:cross(?:ing|ings|es)?|intersect(?:ion|ions|s|ed|ing)?|"
            r"cross\s+traffic)\b"
            r"[^.;!?]{0,100}\b(?:routes?|paths?|pedestrian|forklift|"
            r"material)|\b(?:pedestrian|forklift|material)"
            r"[^.;!?]{0,100}\b(?:cross(?:ing|ings|es)?|"
            r"intersect(?:ion|ions|s|ed|ing)?)\b"
        ),
    ),
    (
        "route_widths",
        re.compile(
            r"\b(?:narrowest|minimum|usable)\b[^.;!?]{0,60}"
            r"\b(?:aisle|route|boulevard|walkway|corridor)\b|"
            r"\b(?:aisle|route|boulevard|walkway|corridor)\b"
            r"[^.;!?]{0,60}\b(?:width|narrowest|pinch\s+point)\b"
        ),
    ),
    (
        "route_access",
        re.compile(
            r"\b(?:reach|reachable|path|route|travel|move|drive|walk|get|go)"
            r"\b[^.;!?]{0,100}"
            r"\b(?:from|to|between|end\s+to\s+end)\b|"
            r"\b(?:from|between)\b[^.;!?]{0,100}\b(?:to|and)\b"
            r"[^.;!?]{0,100}\b(?:routes?|paths?|aisles?)\b|"
            r"\b(?:continuous|continuity|dead\s+ends?|access)\b"
            r"[^.;!?]{0,80}\b(?:aisle|route|department|zone|rack|cell)\b"
        ),
    ),
    (
        "asset_access",
        re.compile(
            r"\b(?:machines?|equipment|assets?)\b[^.;!?]{0,100}"
            r"\b(?:service|maintenance|operator|loading|input|output|"
            r"front|rear)\s+(?:side|access|approach)|"
            r"\b(?:hardest|easiest)\b[^.;!?]{0,60}\b(?:service|maintain)\b|"
            r"\b(?:service|maintenance|operator|loading)\s+side\b"
        ),
    ),
    (
        "cell_access",
        re.compile(
            r"\b(?:robot|manufacturing|assembly|work)[-\s]*cells?\b"
            r"[^.;!?]{0,140}\b(?:gates?|entrances?|open\s+side|loading|"
            r"service\s+access|rear\s+access)|"
            r"\b(?:gates?|entrances?|open\s+side)\b[^.;!?]{0,100}"
            r"\b(?:cells?|guarding)\b"
        ),
    ),
    (
        "protected_intrusions",
        re.compile(
            r"\b(?:keep[-\s]clear|protected|restricted|pedestrian|"
            r"forklift|material)\b[^.;!?]{0,100}"
            r"\b(?:intrusions?|occupied|obstructed|blocked|overlap)|"
            r"\b(?:equipment|assets?|footprints?)\b[^.;!?]{0,100}"
            r"\b(?:route|keep[-\s]clear|protected\s+area)\b"
        ),
    ),
    (
        "clearances",
        re.compile(
            r"\b(?:actual|smallest|minimum|least|edge[-\s]to[-\s]edge)"
            r"[^.;!?]{0,80}\bclearances?\b|"
            r"\bclearance\s+between\b|\bphysically\s+overlapping\b"
        ),
    ),
    (
        "free_space",
        re.compile(
            r"\b(?:free|open|usable|contiguous|continuous)\s+"
            r"(?:area|space|regions?)\b|\blargest\s+(?:open|free)\b"
        ),
    ),
    (
        "pattern_provenance",
        re.compile(
            r"\bpatterns?\b[^.;!?]{0,100}\b(?:created|authored|"
            r"provenance|parameters?|seed|spacing|count|drift|edited|"
            r"used)\b|\b(?:created|authored|provenance|parameters?|seed|"
            r"spacing|count|drift|edited|used)\b[^.;!?]{0,100}"
            r"\bpatterns?\b|\b(?:came|come)\s+from\s+(?:a\s+)?patterns?\b|"
            r"\b(?:spacing|count)\b[^.;!?]{0,100}"
            r"\b(?:rows?|instances?|patterns?)\b"
        ),
    ),
    (
        "cell_layout_provenance",
        re.compile(
            r"\b(?:strategy|layout\s+type)\b[^.;!?]{0,120}"
            r"\b(?:created|authored|used)\b[^.;!?]{0,120}"
            r"\b(?:assembly|manufacturing|robot|work)?[-\s]*cells?\b|"
            r"\b(?:assembly|manufacturing|robot|work)?[-\s]*cells?\b"
            r"[^.;!?]{0,120}\b(?:created|authored|used)\b"
            r"[^.;!?]{0,80}\b(?:strategy|layout\s+type)\b"
        ),
    ),
    (
        "layout_provenance",
        re.compile(
            r"\b(?:authored|original(?:ly)?|created|provenance|pattern)\b"
            r"[^.;!?]{0,100}\b(?:strategy|parameters?|seed|spacing|count|"
            r"drift|edited)|\b(?:strategy|pattern)\b[^.;!?]{0,100}"
            r"\b(?:created|authored|drift|parameters?)\b"
        ),
    ),
    (
        "operator_travel",
        re.compile(
            r"\b(?:operator|worker)\b[^.;!?]{0,80}"
            r"\b(?:walking|travel|path|distance)|"
            r"\b(?:walking|travel)\b[^.;!?]{0,80}\b(?:cell|operator)\b"
        ),
    ),
    (
        "cell_alternatives",
        re.compile(
            r"\b(?:compare|alternative|reconfigure|configuration)\b"
            r"[^.;!?]{0,120}\b(?:u[-\s]shaped?|l[-\s]shaped?|"
            r"straight|line|cell)|\b(?:u[-\s]shaped?|l[-\s]shaped?)\b"
            r"[^.;!?]{0,120}\b(?:compare|alternative|configuration)\b"
        ),
    ),
    (
        "module_fit",
        re.compile(
            r"\b(?:how\s+many|additional|another|more)\b"
            r"[^.;!?]{0,100}\b(?:robot|manufacturing|assembly|work)\s*cells?\b"
            r"[^.;!?]{0,80}\b(?:fit|accommodate|space|room)?\b"
        ),
    ),
)


def _normalized(message: str) -> str:
    return _SPACE.sub(" ", str(message or "").strip().lower())


def _parse_bounded_count(value: str) -> int | None:
    compact = re.sub(r"[-\s]+", " ", str(value or "").strip().lower())
    if compact.isdigit():
        parsed = int(compact)
        return parsed if 1 <= parsed <= 50 else None
    tokens = compact.split()
    if len(tokens) == 1:
        parsed = _COUNT_UNITS.get(tokens[0], _COUNT_TENS.get(tokens[0]))
    elif len(tokens) == 2 and tokens[0] in _COUNT_TENS:
        unit = _COUNT_UNITS.get(tokens[1])
        parsed = _COUNT_TENS[tokens[0]] + unit if unit is not None else None
    else:
        parsed = None
    return parsed if parsed is not None and 1 <= parsed <= 50 else None


def _canonical_dimension_unit(value: str) -> tuple[str, float] | None:
    unit = str(value or "").strip().lower()
    aliases = {
        "m": ("m", 1.0),
        "meter": ("m", 1.0),
        "meters": ("m", 1.0),
        "metre": ("m", 1.0),
        "metres": ("m", 1.0),
        "mm": ("mm", 1.0),
        "millimeter": ("mm", 1.0),
        "millimeters": ("mm", 1.0),
        "millimetre": ("mm", 1.0),
        "millimetres": ("mm", 1.0),
        "cm": ("mm", 10.0),
        "centimeter": ("mm", 10.0),
        "centimeters": ("mm", 10.0),
        "centimetre": ("mm", 10.0),
        "centimetres": ("mm", 10.0),
        "ft": ("ft", 1.0),
        "foot": ("ft", 1.0),
        "feet": ("ft", 1.0),
        "in": ("in", 1.0),
        "inch": ("in", 1.0),
        "inches": ("in", 1.0),
    }
    return aliases.get(unit)


def _parse_department_labels(value: str, count: int) -> list[str] | None:
    raw = str(value or "").strip().strip(" .")
    raw = re.sub(r"\s+respectively\s*$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(
        r"\s+(?:(?:in|as|using)\s+(?:a\s+)?(?:single\s+)?"
        r"(?:rows?|columns?|grid)(?:\s+(?:layout|arrangement))?"
        r"|arranged\s+(?:horizontally|vertically))\s*$",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    pieces = [
        re.sub(r"^\s*and\s+", "", item, flags=re.IGNORECASE)
        .strip()
        .strip("\"'")
        for item in re.split(r"\s*[,;]\s*", raw)
    ]
    labels = [item for item in pieces if item]
    if len(labels) != count:
        return None
    folded = [item.casefold() for item in labels]
    if len(set(folded)) != len(folded):
        return None
    return labels


def parse_complete_facility_generation_request(
    message: str,
) -> dict[str, Any] | None:
    """Parse explicit whole-facility intent without authoring geometry.

    This parser is a deterministic tool-selection guard for requests that
    already contain an envelope and a macro-department program. It does not
    infer missing dimensions, reconcile contradictory units, split ambiguous
    labels, or create coordinates. Incomplete requests remain available to the
    conversational planner for clarification.
    """

    text = _SPACE.sub(" ", str(message or "").strip())
    normalized = text.lower()
    positive = " ".join(_positive_clauses(normalized))
    if not (
        positive
        and _COMPLETE_FACILITY_ACTION.search(positive)
        and _COMPLETE_FACILITY_TARGET.search(positive)
        and _COMPLETE_DEPARTMENT_TARGET.search(positive)
    ):
        return None
    presentation_target = _PRESENTATION_TARGET.search(positive)
    facility_target = _COMPLETE_FACILITY_TARGET.search(positive)
    if (
        presentation_target is not None
        and facility_target is not None
        and presentation_target.start() < facility_target.start()
    ):
        return None
    if classify_facility_layout_request(text) != "generation":
        return None

    dimensions = _COMPLETE_FACILITY_DIMENSIONS.search(positive)
    department_count = _COMPLETE_DEPARTMENT_COUNT.search(positive)
    labels_match = _DEPARTMENT_LABELS.search(text)
    if dimensions is None or department_count is None or labels_match is None:
        return None

    count = _parse_bounded_count(department_count.group("count"))
    if count is None:
        return None
    labels = _parse_department_labels(labels_match.group("labels"), count)
    if labels is None:
        return None

    raw_unit1 = dimensions.group("unit1") or dimensions.group("unit2")
    raw_unit2 = dimensions.group("unit2") or dimensions.group("unit1")
    unit1 = _canonical_dimension_unit(raw_unit1)
    unit2 = _canonical_dimension_unit(raw_unit2)
    if unit1 is None or unit2 is None or unit1[0] != unit2[0]:
        return None
    width = float(dimensions.group("width")) * unit1[1]
    depth = float(dimensions.group("depth")) * unit2[1]

    arrangement = "deterministic_grid"
    if re.search(r"\b(?:in|as)\s+(?:a\s+)?(?:single\s+)?rows?\b", positive):
        arrangement = "rows"
    elif re.search(
        r"\b(?:in|as)\s+(?:a\s+)?(?:single\s+)?columns?\b",
        positive,
    ):
        arrangement = "columns"
    orientation = "auto"
    if re.search(r"\b(?:horizontal|horizontally)\b", positive):
        orientation = "horizontal"
    elif re.search(r"\b(?:vertical|vertically)\b", positive):
        orientation = "vertical"

    return {
        "facility_envelope": {
            "width": width,
            "depth": depth,
            "source_unit": unit1[0],
            "display_name": "Facility Layout",
            "grid_size": None,
        },
        "departments": {
            "count": count,
            "labels": labels,
            "proportions": (
                [1.0 / count] * count
                if _EQUAL_DEPARTMENTS.search(positive)
                else None
            ),
            "arrangement": arrangement,
            "orientation": orientation,
        },
        "execution_mode": (
            "preview_only"
            if re.search(
                r"\b(?:preview[-\s]+only|stage[-\s]+by[-\s]+stage|guided)\b",
                positive,
            )
            else "authorized_draft_run"
        ),
    }


def _positive_clauses(message: str) -> list[str]:
    """Return clauses after removing explicitly negated action clauses."""

    positive = _NEGATED_CLAUSE.sub(" ", message)
    return [
        clause.strip()
        for clause in re.split(r"[.;!?]+|\b(?:and\s+then|then)\b", positive)
        if clause.strip()
    ]


def _first_target_after_action(clause: str, action_end: int) -> str | None:
    """Classify the first presentation or spatial object after one action."""

    tail = clause[action_end : action_end + 180]
    presentation = _PRESENTATION_TARGET.search(tail)
    spatial = _SPATIAL_TARGET.search(tail)
    if presentation is None and spatial is None:
        return None
    if presentation is not None and spatial is not None:
        # "facility layout chart" names a presentation artifact, while
        # "build a layout and include a chart" names the layout first and
        # separates the chart as an additional deliverable.
        between = tail[spatial.end() : presentation.start()]
        compact_presentation = (
            spatial.start() < presentation.start()
            and len(between.split()) <= 2
            and not re.search(r"\b(?:and|with|plus)\b", between)
        )
        if compact_presentation:
            return "presentation"
        return (
            "presentation"
            if presentation.start() < spatial.start()
            else "spatial"
        )
    return "presentation" if presentation is not None else "spatial"


def classify_facility_layout_request(message: str) -> FacilityLayoutIntent:
    """Classify a Facility Layout turn without granting geometry authority."""

    normalized = _normalized(message)
    if not normalized:
        return "unrelated"

    clauses = _positive_clauses(normalized)
    positive_text = " ".join(clauses)
    has_facility_scope = bool(_FACILITY_SCOPE.search(normalized))

    # A named ghost/spatial preview is itself a request for a temporary visual
    # change, unless that preview request occurred only in a negated clause.
    if _PREVIEW_TARGET.search(positive_text) and re.search(
        r"\b(?:build|create|generate|show|prepare|produce|propose)\w*\b",
        positive_text,
    ):
        return "generation"

    for clause in clauses:
        presentation = _PRESENTATION_TARGET.search(clause)
        for mutation in _DIRECT_MUTATION.finditer(clause):
            # Interrogative descriptions such as "How does material move?"
            # and "Why are these racks arranged in rows?" ask for analysis.
            # They do not authorize a spatial preview merely because their
            # grammar contains a verb that is also an editing command.
            if (
                mutation.start() > 0
                and _INTERROGATIVE_PREFIX.search(clause)
                and not re.search(
                    r"\b(?:and|and\s+then|then)\s*$",
                    clause[: mutation.start()],
                )
            ):
                continue
            # "Can we add another CNC?" asks whether a constrained fit is
            # feasible. It does not authorize a preview or write. Requests
            # addressed to the agent ("Can you add...") remain mutations.
            if _READ_ONLY_FEASIBILITY.search(clause):
                continue
            if _READ_ONLY_ROUTE_FEASIBILITY.search(clause):
                continue
            # In "chart comparing placed assets", "placed" describes the
            # population; it is not an imperative. A conjunction introduces a
            # new command, as in "create a chart and move the machines".
            if presentation is not None and presentation.start() < mutation.start():
                between = clause[presentation.end() : mutation.start()]
                if not re.search(r"\b(?:and|then)\b", between):
                    continue
            if mutation.group(0).endswith("ed") and re.match(
                r"\s+(?:assets?|equipment|machines?|racks?|placements?)\b",
                clause[mutation.end() :],
            ) and _READ_ONLY_CUE.search(clause[: mutation.start()]):
                continue
            target = _first_target_after_action(clause, mutation.end())
            if target == "presentation":
                continue
            if target == "spatial" or has_facility_scope:
                return "generation"

        for action in _AMBIGUOUS_ACTION.finditer(clause):
            if action.group(0).startswith("plot"):
                continue
            if (
                action.start() > 0
                and _INTERROGATIVE_PREFIX.search(clause)
                and not re.search(
                    r"\b(?:and|and\s+then|then)\s*$",
                    clause[: action.start()],
                )
            ):
                continue
            target = _first_target_after_action(clause, action.end())
            if target == "spatial":
                return "generation"
            if target == "presentation":
                continue
            # Arrange/optimize/rearrange/improve/modify/update are spatial
            # actions when the clause has Facility scope and no presentation
            # object. Generic create/build/generate remain unprivileged.
            if re.fullmatch(
                r"(?:arrange|optimi[sz]e|rearrange|improve|modify|update)\w*",
                action.group(0),
            ) and _FACILITY_SCOPE.search(clause):
                return "generation"

        if presentation and not has_facility_scope:
            # A chart request alone is not necessarily about Facility Layout.
            continue

    if has_facility_scope and (
        _READ_ONLY_CUE.search(normalized)
        or _PRESENTATION_TARGET.search(normalized)
        or re.search(r"\?\s*$", str(message or ""))
    ):
        return "analysis"
    if has_facility_scope:
        # Trusted Facility context plus a non-mutating statement is still a
        # read-only turn. Only explicit spatial actions grant preview access.
        return "analysis"
    return "unrelated"


def resolve_facility_layout_turn(
    message: str,
    *,
    recent_turns: Sequence[Mapping[str, Any]] = (),
    workflow_state: Mapping[str, Any] | None = None,
) -> FacilityLayoutIntent:
    """Resolve conversational Facility scope without granting a write.

    The direct classifier remains the authorization boundary for spatial
    generation. This resolver only carries a read-only Facility workflow
    across short answers, corrections, presentation refinements, and social
    turns when recent conversation or durable workflow state establishes the
    scope. A follow-up can therefore request another chart or answer a prior
    question, but it can never inherit geometry authority from an older turn.
    """

    direct = classify_facility_layout_request(message)
    if direct != "unrelated":
        return direct

    normalized = _normalized(message)
    if not normalized:
        return "unrelated"
    state = workflow_state if isinstance(workflow_state, Mapping) else {}
    workflow_id = str(
        state.get("workflow_id")
        or state.get("workflowId")
        or ""
    ).strip()
    active_facility_workflow = workflow_id in {
        "facility-layout-analysis",
        "facility-layout-generation",
    }
    recent_has_facility_scope = False
    for turn in list(recent_turns)[-6:]:
        if not isinstance(turn, Mapping):
            continue
        text = _normalized(turn.get("text") or turn.get("content") or "")
        if _FACILITY_SCOPE.search(text):
            recent_has_facility_scope = True
            break

    is_continuation = bool(
        _FOLLOW_UP_CUE.search(normalized)
        or _SOCIAL_TURN.fullmatch(normalized)
        or _PRESENTATION_TARGET.search(normalized)
        or _PRESENTATION_REFINEMENT.search(normalized)
        or (active_facility_workflow and _READ_ONLY_CUE.search(normalized))
    )
    if is_continuation and (
        active_facility_workflow or recent_has_facility_scope
    ):
        return "analysis"
    return "unrelated"


def is_facility_layout_generation_request(message: str) -> bool:
    return classify_facility_layout_request(message) == "generation"


def facility_layout_action_mode(
    message: str,
    *,
    intent: FacilityLayoutIntent | None = None,
) -> FacilityActionMode:
    """Return the runtime authorization mode for one Facility turn.

    This is deliberately narrower than semantic routing. A model or router may
    choose an unsuitable workflow, but it cannot upgrade a raw read request to
    a visual or spatial action. Explicit layout edits enter PREVIEW first;
    COMMIT is reserved for an explicit approval of an existing proposal and is
    still subject to the authoritative transaction runtime.
    """

    normalized = _normalized(message)
    if _COMMIT_ACTION.search(normalized):
        return "COMMIT"
    resolved = intent or classify_facility_layout_request(message)
    if resolved == "generation":
        return "PREVIEW"
    return "READ_ONLY"


def facility_layout_tool_authorization(
    message: str,
    *,
    read_tool_names: Iterable[str],
    presentation_tool_names: Iterable[str] = (),
    preview_tool_name: str,
    move_tool_name: str,
    presentation_requested: bool = False,
) -> dict[str, Any]:
    """Return the closed chat-tool allowlist for one Facility turn.

    This pure policy is shared by the server runtime and source-bound release
    evaluation. It never exposes a chat-side commit tool, and viewport tools
    are deliberately absent in every mode.
    """

    intent = classify_facility_layout_request(message)
    mode = facility_layout_action_mode(message, intent=intent)
    request_kind = classify_facility_request_kind(message, intent=intent)
    precise_translation = request_kind == "exact_transform"
    from ai_inspector.facility_layout.orchestration import (
        build_facility_orchestration_plan,
    )

    plan = build_facility_orchestration_plan(
        operation_intent=request_kind,
        action_mode=mode,
        available_read_tools=read_tool_names,
        presentation_tools=presentation_tool_names,
        preview_tool_name=preview_tool_name,
        move_tool_name=move_tool_name,
        requested_metric=requested_facility_metric(message),
        spatial_analyses=requested_facility_spatial_analyses(message),
        table_requested=bool(
            presentation_requested
            or re.search(r"\btable\b", _normalized(message))
        ),
        chart_requested=bool(
            presentation_requested
            or re.search(
                r"\b(?:chart|graph|plot|heat\s*map|pareto|histogram|"
                r"pie|donut)\b",
                _normalized(message),
            )
        ),
    )
    return {
        "mode": mode,
        "intent": intent,
        "requestKind": request_kind,
        "preciseTranslation": bool(
            mode == "PREVIEW" and precise_translation
        ),
        "allowedToolNames": plan["allowedToolNames"],
        "chatCommitToolAvailable": plan["chatCommitToolAvailable"],
        "viewportNavigationAuthorized": plan[
            "viewportNavigationAuthorized"
        ],
        "orchestration": plan,
    }


def classify_facility_request_kind(
    message: str,
    *,
    intent: FacilityLayoutIntent | None = None,
) -> FacilityRequestKind:
    """Classify the requested operation independently from write authority."""

    normalized = _normalized(message)
    resolved = intent or classify_facility_layout_request(message)
    if _PRESENTATION_TARGET.search(normalized) and re.search(
        r"\b(?:chart|graph|plot|heat\s*map|pareto|histogram|pie|donut)\b",
        normalized,
    ):
        return "render"
    if _NAVIGATION_REQUEST.search(normalized):
        return "navigate"
    if is_precise_facility_translation_request(message):
        return "exact_transform"
    if _SIMULATION_REQUEST.search(normalized):
        return "simulate"
    if _RECOMMENDATION_REQUEST.search(normalized):
        return "recommend"
    if resolved == "generation":
        return "modify"
    if _COMPARISON_REQUEST.search(normalized):
        return "compare"
    if _MEASUREMENT_REQUEST.search(normalized):
        return "measure"
    return "inspect"


def requested_facility_metric(message: str) -> str | None:
    """Return the exact semantic metric requested by the user, if explicit."""

    normalized = _normalized(message)
    for metric_id, pattern in _FACILITY_METRIC_PATTERNS:
        if pattern.search(normalized):
            return metric_id
    return None


def requested_facility_spatial_analyses(message: str) -> tuple[str, ...]:
    """Return deterministic spatial-analysis modes implied by one question.

    This is a tool-planning hint, not an authorization decision. Multiple
    modes are retained when a question spans separate computations, such as
    robot-cell access plus keep-clear intrusion checks.
    """

    normalized = _normalized(message)
    return tuple(
        analysis
        for analysis, pattern in _FACILITY_SPATIAL_ANALYSIS_PATTERNS
        if pattern.search(normalized)
    )


def is_precise_facility_translation_request(message: str) -> bool:
    """Return whether one turn requests an exact world-space translation.

    This intentionally recognizes only a narrow command family. It grants no
    coordinate authority to the model: the model supplies a semantic cardinal
    direction and distance while the browser resolves current positions and
    the authoritative Facility transaction runtime validates the draft edit.
    """

    normalized = _normalized(message)
    if not normalized or _NEGATED_CLAUSE.fullmatch(normalized):
        return False
    if classify_facility_layout_request(message) != "generation":
        return False
    if not _PRECISE_TRANSLATION_ACTION.search(normalized):
        return False
    if not _PRECISE_TRANSLATION_DISTANCE.search(normalized):
        return False
    if not _PRECISE_TRANSLATION_DIRECTION.search(normalized):
        return False
    without_preservation = re.sub(
        r"\b(?:preserve|keep|maintain|retain|leave)\b[^.;!?]{0,60}"
        r"\b(?:rotation|orientation)\b",
        " ",
        normalized,
    )
    return not bool(_NON_TRANSLATION_EDIT.search(without_preservation))


def parse_precise_facility_translation(
    message: str,
) -> dict[str, Any] | None:
    """Parse the bounded deterministic payload for an exact translation."""

    if not is_precise_facility_translation_request(message):
        return None
    normalized = _normalized(message)
    distance = _PRECISE_TRANSLATION_DISTANCE.search(normalized)
    direction = _PRECISE_TRANSLATION_DIRECTION.search(normalized)
    if distance is None or direction is None:
        return None
    numeric = re.search(r"(?:\d+(?:\.\d+)?|\.\d+)", distance.group(0))
    if numeric is None:
        return None
    unit_text = distance.group(0)[numeric.end() :].strip()
    unit_aliases = {
        "millimeter": "mm",
        "millimeters": "mm",
        "millimetre": "mm",
        "millimetres": "mm",
        "centimeter": "cm",
        "centimeters": "cm",
        "centimetre": "cm",
        "centimetres": "cm",
        "meter": "m",
        "meters": "m",
        "metre": "m",
        "metres": "m",
        "foot": "ft",
        "feet": "ft",
        "inch": "in",
        "inches": "in",
    }
    unit = unit_aliases.get(unit_text, unit_text)
    if unit not in {"mm", "cm", "m", "ft", "in"}:
        return None
    direction_value = direction.group(0)
    direction_value = {
        "upward": "up",
        "downward": "down",
    }.get(direction_value, direction_value)
    return {
        "use_current_selection": bool(_CURRENT_SELECTION_CUE.search(normalized)),
        "direction": direction_value,
        "distance": float(numeric.group(0)),
        "unit": unit,
        "preserve_rotation": True,
    }


def resolve_facility_pending_follow_up(
    message: str,
    *,
    recent_turns: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """Resolve a short confirmation to one pending read-only analytical task.

    Assistant text is used only as conversational context. It never upgrades
    the current turn's action mode or authorizes a tool outside the read-only
    allowlist.
    """

    if not _AFFIRMATIVE_FOLLOW_UP.fullmatch(_normalized(message)):
        return None
    turns = [turn for turn in recent_turns if isinstance(turn, Mapping)]
    assistant_index: int | None = None
    assistant_text = ""
    for index in range(len(turns) - 1, -1, -1):
        role = _normalized(turns[index].get("role") or "")
        if role not in {"assistant", "sage", "agent"}:
            continue
        text = " ".join(
            str(
                turns[index].get("content")
                or turns[index].get("text")
                or ""
            ).split()
        )
        if text and (_PENDING_OFFER.search(text.casefold()) or "?" in text):
            assistant_index = index
            assistant_text = text[:800]
            break
    if assistant_index is None:
        return None

    prior_request = ""
    for index in range(assistant_index - 1, -1, -1):
        role = _normalized(turns[index].get("role") or "")
        if role and role != "user":
            continue
        text = " ".join(
            str(
                turns[index].get("content")
                or turns[index].get("text")
                or ""
            ).split()
        )
        if text:
            prior_request = text[:800]
            break
    if not prior_request or not _FACILITY_SCOPE.search(
        f"{prior_request} {assistant_text}".casefold()
    ):
        return None

    question_tail = assistant_text.rsplit("?", 1)[0].casefold()
    ambiguous = bool(
        re.search(r"\b(?:either|or)\b", question_tail)
        and not re.search(r"\b(?:yes\s+or\s+no|whether)\b", question_tail)
    )
    return {
        "priorUserRequest": prior_request,
        "assistantOffer": assistant_text,
        "ambiguous": ambiguous,
        "actionMode": "READ_ONLY",
    }


__all__ = [
    "FacilityActionMode",
    "FacilityLayoutIntent",
    "FacilityRequestKind",
    "classify_facility_layout_request",
    "classify_facility_request_kind",
    "facility_layout_action_mode",
    "facility_layout_tool_authorization",
    "is_facility_layout_generation_request",
    "is_precise_facility_translation_request",
    "parse_complete_facility_generation_request",
    "parse_precise_facility_translation",
    "requested_facility_metric",
    "requested_facility_spatial_analyses",
    "resolve_facility_pending_follow_up",
    "resolve_facility_layout_turn",
]
