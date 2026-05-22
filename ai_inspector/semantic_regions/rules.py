"""Deterministic region-classification rules.

Two stages run in order, first match wins per node:

  Stage 1: aircraft-shape spatial heuristics
           (propeller, top_wing, lower_wing, tail_*, strut_*)
  Stage 2: name-based fallback buckets (everything not yet assigned)

Stage 1 is intentionally conservative -- a rule only fires when the
node's bbox CENTROID sits in a position the rule confidently
recognises. Ambiguous nodes drop through to Stage 2 and end up in
fallback buckets marked confidence:low / reviewed:false.

Axis frame: auto-detected from the part bbox. The longest extent is
treated as the LENGTH axis (e.g. fuselage length), the second-longest
as the LATERAL axis (wing span / mirror plane), and the shortest as
the VERTICAL axis. This makes the rules agnostic to whether the part
was modelled with Y or Z up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .glb_inspect import GlbNode, GlbSummary


# ---------------------------------------------------------------------------
# Static label / alias map. The aliases are the words a human is most
# likely to use when asking Sage about that region.
# ---------------------------------------------------------------------------
LABELS: Dict[str, Tuple[str, List[str]]] = {
    "propeller":                  ("Propeller",              ["nose", "prop", "spinner"]),
    "top_wing":                   ("Top wing",               ["upper wing", "main upper wing"]),
    "lower_wing":                 ("Lower wing",             ["bottom wing", "main lower wing"]),
    "tail_horizontal_stabilizer": ("Horizontal stabilizer",  ["elevator", "horizontal tail", "tailplane"]),
    "tail_vertical_stabilizer":   ("Vertical stabilizer",    ["rudder", "vertical tail", "fin"]),
    "tail_other":                 ("Tail (other)",           ["tail tip", "tail end", "tail cap"]),
    "strut_outer":                ("Outer wing strut",       ["outer post", "outboard strut"]),
    "strut_inner":                ("Inner wing strut",       ["inner brace", "inboard strut", "interplane strut"]),
    "fuselage_candidate":         ("Fuselage (review)",      ["body", "fuselage"]),
    "uncategorized":              ("Uncategorized (review)", []),
}


# ---------------------------------------------------------------------------
# Axis frame
# ---------------------------------------------------------------------------

@dataclass
class AxisFrame:
    """Maps semantic axes (length / vertical / lateral) onto raw 0/1/2
    indices. length = longest part-bbox extent, lateral = second
    longest, vertical = shortest. For a typical aircraft this resolves
    to length=fuselage, lateral=wingspan, vertical=height."""
    length_axis:   int   # 0=X, 1=Y, 2=Z
    lateral_axis:  int
    vertical_axis: int
    length_min:    float
    length_max:    float
    lateral_min:   float
    lateral_max:   float
    vertical_min:  float
    vertical_max:  float

    @property
    def length_range(self) -> float:
        return self.length_max - self.length_min

    @property
    def lateral_range(self) -> float:
        return self.lateral_max - self.lateral_min

    @property
    def vertical_range(self) -> float:
        return self.vertical_max - self.vertical_min


def detect_axis_frame(summary: GlbSummary) -> AxisFrame:
    """Pick length=largest extent, lateral=second, vertical=smallest."""
    extents = list(summary.overall_extent)
    # ranked: [(axis_idx, extent), ...] descending by extent
    ranked = sorted(enumerate(extents), key=lambda kv: kv[1], reverse=True)
    length_axis, _   = ranked[0]
    lateral_axis, _  = ranked[1]
    vertical_axis, _ = ranked[2]
    return AxisFrame(
        length_axis   = length_axis,
        lateral_axis  = lateral_axis,
        vertical_axis = vertical_axis,
        length_min    = summary.overall_min[length_axis],
        length_max    = summary.overall_max[length_axis],
        lateral_min   = summary.overall_min[lateral_axis],
        lateral_max   = summary.overall_max[lateral_axis],
        vertical_min  = summary.overall_min[vertical_axis],
        vertical_max  = summary.overall_max[vertical_axis],
    )


# ---------------------------------------------------------------------------
# Helpers that project a node's bbox into the semantic frame
# ---------------------------------------------------------------------------

def _proj(values: Tuple[float, float, float], axis: int) -> float:
    return values[axis]


def _node_position(node: GlbNode, frame: AxisFrame) -> Dict[str, float]:
    """Project a node's bbox into the semantic frame.

    Returns a flat dict keyed by axis label so the rules read like
    English instead of a soup of axis-index indirections."""
    c = node.centroid
    e = node.extent
    return {
        "length_centroid":   _proj(c, frame.length_axis),
        "length_extent":     _proj(e, frame.length_axis),
        "lateral_centroid":  _proj(c, frame.lateral_axis),
        "lateral_extent":    _proj(e, frame.lateral_axis),
        "vertical_centroid": _proj(c, frame.vertical_axis),
        "vertical_extent":   _proj(e, frame.vertical_axis),
    }


# ---------------------------------------------------------------------------
# Stage 1: aircraft-shape rules
# ---------------------------------------------------------------------------

# Rule outcome: (region_id, confidence) or None if rule did not fire.
RuleResult = Optional[Tuple[str, str]]


def _rule_propeller(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Near the FRONT of the length axis (top 15% by length value) AND
    # small lateral+vertical footprint. "Front" = whichever end of the
    # length axis has the largest centroid value (we assume the
    # propeller is at the +length end; symmetric so flip if needed by
    # checking which end has more nodes nearby in a later refinement).
    front_threshold = frame.length_max - 0.15 * frame.length_range
    if np_["length_centroid"] < front_threshold:
        return None
    max_xy = max(frame.lateral_range, frame.vertical_range)
    if np_["lateral_extent"] > 0.2 * max_xy:  return None
    if np_["vertical_extent"] > 0.2 * max_xy: return None
    return ("propeller", "high")


def _rule_top_wing(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # High on the vertical axis AND wide on the lateral axis.
    vertical_mid = 0.5 * (frame.vertical_min + frame.vertical_max)
    high_threshold = vertical_mid + 0.3 * frame.vertical_range
    if np_["vertical_centroid"] < high_threshold:
        return None
    if np_["lateral_extent"] < 0.5 * frame.lateral_range:
        return None
    return ("top_wing", "high")


def _rule_lower_wing(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Low on the vertical axis, in the main wing station, AND either:
    #   - wide across the center panel, or
    #   - a shorter outboard wing-tip/end-cap surface.
    # The second case catches lower-wing rounded ends that are modeled
    # as separate Surface-Revolve / Mirror operations rather than one
    # continuous full-span surface.
    vertical_mid = 0.5 * (frame.vertical_min + frame.vertical_max)
    low_threshold = vertical_mid - 0.3 * frame.vertical_range
    if np_["vertical_centroid"] > low_threshold:
        return None

    if frame.length_range <= 0:
        return None
    length_norm = (np_["length_centroid"] - frame.length_min) / frame.length_range
    if length_norm < 0.55 or length_norm > 0.85:
        return None

    lateral_mid = 0.5 * (frame.lateral_min + frame.lateral_max)
    is_wide_center = np_["lateral_extent"] >= 0.5 * frame.lateral_range
    is_outboard_tip = (
        np_["lateral_extent"] >= 0.09 * frame.lateral_range
        and abs(np_["lateral_centroid"] - lateral_mid) >= 0.25 * frame.lateral_range
    )
    if not (is_wide_center or is_outboard_tip):
        return None
    return ("lower_wing", "high")


def _rule_tail_horizontal_stabilizer(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Far back on the length axis (bottom 20%) AND at low-to-mid
    # vertical position.
    back_threshold = frame.length_min + 0.20 * frame.length_range
    if np_["length_centroid"] > back_threshold:
        return None
    vertical_mid = 0.5 * (frame.vertical_min + frame.vertical_max)
    if np_["vertical_centroid"] > vertical_mid + 0.2 * frame.vertical_range:
        return None
    return ("tail_horizontal_stabilizer", "medium")


def _rule_tail_vertical_stabilizer(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Far back AND high vertical AND near lateral center (symmetry plane).
    back_threshold = frame.length_min + 0.20 * frame.length_range
    if np_["length_centroid"] > back_threshold:
        return None
    vertical_mid = 0.5 * (frame.vertical_min + frame.vertical_max)
    if np_["vertical_centroid"] < vertical_mid + 0.2 * frame.vertical_range:
        return None
    lateral_mid = 0.5 * (frame.lateral_min + frame.lateral_max)
    if abs(np_["lateral_centroid"] - lateral_mid) > 0.08 * frame.lateral_range:
        return None
    return ("tail_vertical_stabilizer", "medium")


def _rule_tail_other(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Anything remaining in the very-far-back 10% of length.
    back_threshold = frame.length_min + 0.10 * frame.length_range
    if np_["length_centroid"] > back_threshold:
        return None
    return ("tail_other", "low")


def _rule_strut_outer(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Narrow lateral footprint at an OFF-CENTER lateral position
    # (toward a wingtip) AND tall vertical span (connecting wings).
    if np_["lateral_extent"] > 0.05 * frame.lateral_range:
        return None
    if np_["vertical_extent"] < 0.4 * frame.vertical_range:
        return None
    lateral_mid = 0.5 * (frame.lateral_min + frame.lateral_max)
    if abs(np_["lateral_centroid"] - lateral_mid) < 0.3 * frame.lateral_range:
        return None
    return ("strut_outer", "medium")


def _rule_strut_inner(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Less restrictive: tall vertical span AND moderate lateral span.
    # Catches diagonal braces from fuselage to wingtip.
    if np_["vertical_extent"] < 0.3 * frame.vertical_range:
        return None
    if np_["lateral_extent"] > 0.4 * frame.lateral_range:
        return None
    return ("strut_inner", "low")


def _rule_fuselage_candidate_by_geometry(np_: Dict[str, float], frame: AxisFrame) -> RuleResult:
    # Anything that spans most of the length axis.
    if np_["length_extent"] > 0.7 * frame.length_range:
        return ("fuselage_candidate", "low")
    return None


# Name-pattern-driven fuselage hint. Some CAD authors use construction
# features (Split-Line, Ruled Surface) to slice or trim the fuselage
# skin; we route those to the same fuselage_candidate bucket so the
# operator review can confirm.
_FUSELAGE_NAME_PATTERNS = (
    re.compile(r"^pline_split_line"),
    re.compile(r"^ruledsrffromedge_"),
)


def _rule_fuselage_candidate_by_name(node: GlbNode) -> RuleResult:
    for pat in _FUSELAGE_NAME_PATTERNS:
        if pat.match(node.name):
            return ("fuselage_candidate", "low")
    return None


# Order matters: most-specific rules first. Once a rule fires for a
# node it short-circuits the rest.
_AIRCRAFT_RULES = (
    _rule_propeller,
    _rule_top_wing,
    _rule_lower_wing,
    _rule_tail_vertical_stabilizer,    # higher specificity than horizontal_stabilizer
    _rule_tail_horizontal_stabilizer,
    _rule_tail_other,
    _rule_strut_outer,
    _rule_strut_inner,
    _rule_fuselage_candidate_by_geometry,
)


# Aircraft-shape gate: only attempt the spatial aircraft rules when
# the part's overall proportions look wing-like (lateral span notably
# wider than vertical height). A compact part (piston, gear, flange:
# lateral ~= vertical) has no meaningful "front", "wing", "tail", so
# the rules would only generate false positives. 1.8x is the
# threshold -- 1030034 Vintage Plane resolves to ~3.3x, well clear;
# 1020001 Piston is ~1.0x and is correctly excluded.
_AIRCRAFT_LATERAL_TO_VERTICAL_GATE = 1.8


def is_aircraft_shaped(frame: AxisFrame) -> bool:
    if frame.vertical_range <= 0:
        return False
    return (frame.lateral_range / frame.vertical_range) >= _AIRCRAFT_LATERAL_TO_VERTICAL_GATE


def classify_node_aircraft(node: GlbNode, frame: AxisFrame) -> RuleResult:
    """Try every aircraft-shape rule in priority order; return the
    first that fires, or None when no rule matches.

    The name-pattern fuselage hint runs even on non-aircraft parts
    (split-lines and ruled-surface constructions are uncommon enough
    that the bucket name is informative either way). The bbox-driven
    rules only fire when the part's overall proportions are
    wing-like (see is_aircraft_shaped)."""
    name_hit = _rule_fuselage_candidate_by_name(node)
    if name_hit is not None:
        return name_hit
    if not is_aircraft_shaped(frame):
        return None
    np_ = _node_position(node, frame)
    for rule in _AIRCRAFT_RULES:
        out = rule(np_, frame)
        if out is not None:
            return out
    return None


# ---------------------------------------------------------------------------
# Stage 2: name-based fallback bucket
# ---------------------------------------------------------------------------

# Match the leading lowercase-letter token (the SolidWorks type name
# prefix written by GlbExporter.GenerateFeatureId in C#). Stops at the
# first underscore, the first digit, or end-of-string. So:
#   netblend_boundary_surface3  -> netblend
#   ice_boss_extrude2           -> ice
#   mirrorsolid_mirror4         -> mirrorsolid
#   revolution_revolve1         -> revolution
#   dome1, sweep1, cirpattern1  -> dome, sweep, cirpattern
_NAME_PREFIX_RE = re.compile(r"^([a-z]+)(?:[_\d]|$)", re.IGNORECASE)


def fallback_bucket_id(node_name: str) -> str:
    """Group nodes by their feature-type prefix so the operator at
    least sees same-type nodes together. Uses only the leading type
    token (the part the C# extractor injects from GetTypeName2()) --
    not the slugified feature name -- because the type token is a
    single SolidWorks-defined word (NetBlend, Revolution, Sweep, ICE,
    MirrorSolid, ...) that operators recognise."""
    m = _NAME_PREFIX_RE.match(node_name)
    if m:
        return f"features_{m.group(1).lower()}"
    return "features_unknown"


def fallback_bucket_label(bucket_id: str) -> Tuple[str, List[str]]:
    """Human-facing label + aliases for a name-based bucket.
    Conservative -- no claims that aren't justified by the name."""
    if not bucket_id.startswith("features_"):
        return ("Features (review)", [])
    type_slug = bucket_id[len("features_"):].replace("_", " ").strip()
    if not type_slug:
        return ("Features (review)", [])
    return (f"{type_slug.title()} features (review)", [type_slug])
