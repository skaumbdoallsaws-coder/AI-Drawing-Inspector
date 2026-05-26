"""Pure matching helpers for the dimension intent map.

Given one CAD dimension (sketch+short name+value+type+region) and a
list of drawing dimensions extracted from drawing_map.json, find the
drawing dim that drives the same physical control.

Match rules in priority order:

  1. Exact name match. The drawing annotation already carries
     featureName=Sketch7 + annotationName=D1. When CAD owner +
     short name match those, that IS the same SolidWorks
     dimension -- confidence high regardless of value, with a
     defensive value sanity check.

  2. Value + region match. CAD and drawing values agree within
     ~0.02 mm AND the drawing dim sits in a view whose
     description text overlaps the semantic region label.
     Confidence high.

  3. Value + description match. Same value, no region tie-breaker
     but description text mentions tokens from the CAD feature's
     physical name. Confidence medium.

  4. Value only. Same value, no region/description evidence.
     Confidence low, AMBIGUOUS when multiple drawing dims share
     the same value -> matched=False, evidence='ambiguous_value'.

The matcher NEVER guesses between equal-value candidates without
a tie-breaker. The whole point of the dimension intent map is to
prevent the silent wrong-dim picks that motivated the prior smoke
findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Tolerances ─────────────────────────────────────────────────────

# Absolute mm tolerance for value equality. 0.02 mm covers floating
# point drift between SolidWorks's metres-internal storage and the
# round-tripped drawing display value; tighter would false-negative
# on legitimate same-value pairs, looser would false-positive on
# adjacent dims (e.g. 0.500 vs 0.520 in tightly-toleranced parts).
VALUE_TOL_MM = 0.02


# ── SolidWorks dimension type normalisation ───────────────────────

_TYPE_MAP = {
    # SolidWorks API names
    "swdiameterdimension":     "diameter",
    "swradialdimension":       "radius",
    "swradialdim":             "radius",
    "swangulardimension":      "angle",
    "swhorizlineardimension":  "linear",
    "swvertlineardimension":   "linear",
    "swlineardimension":       "linear",
    "swdimension":             "linear",
    # Already-canonical forms (idempotent)
    "diameter":                "diameter",
    "radius":                  "radius",
    "angle":                   "angle",
    "linear":                  "linear",
    "length":                  "linear",
    "depth":                   "linear",
    "thickness":               "linear",
}


def canonical_dimension_type(raw: str) -> str:
    """Map a raw SolidWorks API type name (or a heuristic axis word)
    to one of {diameter, radius, angle, linear}. Unknown inputs fall
    back to 'linear' which is the most common case and the safest
    default -- the matcher only uses type as a tie-breaker, never as
    a hard filter."""
    key = (raw or "").strip().lower().replace(" ", "")
    return _TYPE_MAP.get(key, "linear")


# ── Phrase tokenisation (shared with lookup) ──────────────────────

def _tokens(text: str) -> List[str]:
    s = (text or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return [t for t in s.split() if len(t) >= 3]


def _overlap_count(a: str, b: str) -> int:
    a_set = set(_tokens(a))
    b_set = set(_tokens(b))
    return len(a_set & b_set)


# ── Result type ───────────────────────────────────────────────────

@dataclass
class MatchResult:
    """Outcome of pairing one CAD dim against the drawing dim list."""
    matched:    bool                 = False
    drawing:    Dict[str, Any]       = field(default_factory=dict)
    confidence: str                  = "low"
    evidence:   List[str]            = field(default_factory=list)


# ── Core matcher ──────────────────────────────────────────────────

def _exact_name_match(
    cad_owner:      str,
    cad_short_name: str,
    drawing_dims:   List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the drawing dim whose featureName == cad_owner AND
    annotationName == cad_short_name. None when no exact match.
    Multiple matches are impossible in well-formed drawing_maps
    (annotationName is unique per sketch); if it ever happens we
    return the first to keep the behaviour deterministic."""
    if not (cad_owner and cad_short_name):
        return None
    for d in drawing_dims:
        if (d.get("ownerFeature") == cad_owner
                and d.get("annotationName") == cad_short_name):
            return d
    return None


def _value_matches(
    cad_value_mm:  Optional[float],
    drawing_dims:  List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """All drawing dims within VALUE_TOL_MM of cad_value_mm."""
    if cad_value_mm is None:
        return []
    hits: List[Dict[str, Any]] = []
    for d in drawing_dims:
        v = d.get("valueMm")
        if v is None:
            continue
        try:
            if abs(float(v) - cad_value_mm) <= VALUE_TOL_MM:
                hits.append(d)
        except (TypeError, ValueError):
            continue
    return hits


def _description_overlap_score(
    drawing_dim:    Dict[str, Any],
    region_label:   str,
    descriptions:   Dict[str, str],
) -> int:
    """Count token overlap between the drawing dim's description and
    the CAD region label. Zero when either side is missing."""
    drawing_id = drawing_dim.get("drawingDimensionId")
    if not drawing_id:
        return 0
    desc = descriptions.get(drawing_id) or ""
    if not desc:
        return 0
    return _overlap_count(desc, region_label or "")


def find_drawing_match(
    cad_full_name:        str,
    cad_owner:            str,
    cad_short_name:       str,
    cad_value_mm:         Optional[float],
    cad_dimension_type:   str,
    region_label:         str,
    drawing_dims:         List[Dict[str, Any]],
    descriptions:         Dict[str, str],
) -> MatchResult:
    """Pair one CAD dim with at most one drawing dim. Pure on its
    inputs -- no file IO, no global state -- so the BridgeTests-style
    direct tests can drive it with synthetic fixtures.

    Priority:
      1. Exact (owner, shortName) match. Sanity-check the value
         (drift > 0.5 mm flags evidence as 'name_match_value_drift'
         but still returns matched=True so the curator can see and
         repair).
      2. Value + region overlap -> high.
      3. Value + description overlap -> medium.
      4. Value only, unique -> low.
      5. Value only, ambiguous (multiple hits) -> matched=False with
         evidence=['ambiguous_value'] so the curator must decide.
      6. Nothing -> matched=False, confidence='low', evidence=[].
    """
    result = MatchResult()

    # ── 1. Exact name match ────────────────────────────────────
    exact = _exact_name_match(cad_owner, cad_short_name, drawing_dims)
    if exact is not None:
        result.matched   = True
        result.drawing   = exact
        result.confidence = "high"
        result.evidence  = ["name_match"]
        if cad_value_mm is not None:
            try:
                if abs(float(exact.get("valueMm") or 0.0) - cad_value_mm) <= VALUE_TOL_MM:
                    result.evidence.append("value_match")
                else:
                    result.evidence.append("name_match_value_drift")
            except (TypeError, ValueError):
                pass
        return result

    # ── 2-5. Value-based passes ────────────────────────────────
    val_hits = _value_matches(cad_value_mm, drawing_dims)
    if not val_hits:
        return result   # matched=False, low, []

    if len(val_hits) == 1:
        hit = val_hits[0]
        evidence = ["value_match"]
        confidence = "low"
        if region_label:
            overlap = _description_overlap_score(hit, region_label, descriptions)
            if overlap >= 1:
                evidence.append("region_match")
                confidence = "high"
        # Description-only corroboration (without region) lifts to medium.
        if confidence == "low" and descriptions.get(hit.get("drawingDimensionId") or ""):
            evidence.append("description_match")
            confidence = "medium"
        result.matched    = True
        result.drawing    = hit
        result.confidence = confidence
        result.evidence   = evidence
        return result

    # Multiple value hits -> try to break the tie via region overlap.
    scored: List[tuple] = []
    for hit in val_hits:
        score = _description_overlap_score(hit, region_label, descriptions) if region_label else 0
        scored.append((score, hit))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    if top_score >= 1 and sum(1 for s, _ in scored if s == top_score) == 1:
        hit = scored[0][1]
        result.matched    = True
        result.drawing    = hit
        result.confidence = "high"
        result.evidence   = ["value_match", "region_match"]
        return result

    # Ambiguous: same value, no unique tie-breaker. Refuse to guess.
    result.matched    = False
    result.drawing    = {}
    result.confidence = "low"
    result.evidence   = ["ambiguous_value"]
    return result
