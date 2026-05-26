"""Read-side helpers consumed by Sage's handoff generation.

Pure: no LLM, no network. Sage's handoff-prep path calls these to
resolve an operator phrase to a single exact CAD dimension when a
high-confidence or reviewed mapping exists. Ambiguous lookups
return None so the add-in's Preview Target still gets a chance to
require operator selection -- the dimension intent map is an
ENRICHMENT, never an authority that bypasses the safety gate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .builder import load_dimension_intent_map


def _tokens(text: Any) -> List[str]:
    s = str(text or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return [t for t in s.split() if len(t) >= 3]


def _mapping_phrases(mapping: Dict[str, Any]) -> List[str]:
    """Phrase pool used for scoring. physicalName and drawingDescription
    are the strongest hits; dimensionShortName is a weak fallback.
    semanticRegionLabel is intentionally NOT here -- many mappings
    share a region label, treating it as exact would auto-pick among
    siblings."""
    phrases: List[str] = []
    for key in ("physicalName", "drawingDescription"):
        v = mapping.get(key)
        if isinstance(v, str) and v.strip():
            phrases.append(v)
    return phrases


def _score_mapping(mapping: Dict[str, Any], phrase: str, region_id: Optional[str]) -> int:
    """Higher = better. 0 = no signal. Region filter (when supplied)
    is a hard prerequisite: a mapping outside the requested region
    scores 0 even when its phrases overlap, because cross-region
    bleed is exactly the bug we're trying to prevent."""
    if region_id:
        mr = mapping.get("semanticRegionId")
        if isinstance(mr, str) and mr and mr != region_id:
            return 0
    hay = (phrase or "").lower()
    if not hay:
        return 0
    best = 0
    for cand in _mapping_phrases(mapping):
        norm = cand.lower().strip()
        if not norm:
            continue
        if norm in hay:
            best = max(best, 100)
            continue
        toks = _tokens(norm)
        if len(toks) >= 2 and all(t in hay for t in toks):
            best = max(best, 80)
        elif toks and any(t in hay for t in toks):
            best = max(best, 40)
    # Confidence bumps: reviewed entries always beat heuristics, and
    # high beats medium beats low among ties.
    if mapping.get("reviewed") is True:
        best += 20
    conf = mapping.get("matchConfidence")
    if conf == "high":
        best += 10
    elif conf == "medium":
        best += 5
    return best


def lookup_dimension_intent(
    library_dir: Path,
    pn:          str,
    revision:    str,
    phrase:      str,
    region_id:   Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve a user phrase to a single dimension intent mapping.

    Returns the mapping dict on a unique hit, None on miss or tie.
    region_id (when provided) restricts the search to that semantic
    region -- callers that already know the region (e.g. Sage having
    resolved the phrase to a semantic region) should pass it to
    avoid cross-region bleed.

    Conservative by design: a tie returns None so the upstream
    handoff path defaults to operator selection rather than guessing.
    """
    if not phrase:
        return None
    doc = load_dimension_intent_map(library_dir, pn, revision)
    if not isinstance(doc, dict):
        return None
    mappings = doc.get("mappings")
    if not isinstance(mappings, list):
        return None
    scored: List[tuple] = []
    for m in mappings:
        if not isinstance(m, dict):
            continue
        score = _score_mapping(m, phrase, region_id)
        if score > 0:
            scored.append((score, m))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[0][0]
    winners = [m for s, m in scored if s == top]
    if len(winners) != 1:
        return None
    return winners[0]


def lookup_dimension_intent_for_cad_dimension(
    library_dir:         Path,
    pn:                  str,
    revision:            str,
    dimension_full_name: str,
) -> Optional[Dict[str, Any]]:
    """Return the mapping whose dimensionFullName equals the supplied
    one. Used by the add-in preview path to attach physicalName when
    a sketch dim is selected. Returns None when the map is absent or
    no mapping carries the requested name."""
    if not dimension_full_name:
        return None
    doc = load_dimension_intent_map(library_dir, pn, revision)
    if not isinstance(doc, dict):
        return None
    mappings = doc.get("mappings")
    if not isinstance(mappings, list):
        return None
    for m in mappings:
        if isinstance(m, dict) and m.get("dimensionFullName") == dimension_full_name:
            return m
    return None
