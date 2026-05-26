"""Lookup helpers for reviewed sketch-dimension names.

Conservative by design: a lookup returns a dimension only when the
operator's phrase clearly matches one reviewed entry, or when there is
exactly one weak candidate for the requested dimension axis. Ambiguous
matches return None so Sage/SolidWorks keeps the operator selector.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .builder import load_sketch_dimension_intent_map


def _norm(text: Any) -> str:
    s = str(text or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> List[str]:
    return [t for t in _norm(text).split() if len(t) >= 2]


def _entry_phrases(entry: Dict[str, Any]) -> List[str]:
    phrases: List[str] = []
    # controlType is intentionally NOT a strong phrase. Many entries can
    # share "diameter"; treating that as exact would auto-pick between
    # front/rear diameters. It is handled as a weak axis hint below.
    for key in ("displayName", "physicalName", "dimensionShortName"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            phrases.append(v)
    aliases = entry.get("aliases") or []
    if isinstance(aliases, list):
        for a in aliases:
            if isinstance(a, str) and a.strip():
                phrases.append(a)
    return phrases


def _score_entry(entry: Dict[str, Any], instruction: str, dimension_hint: str = "") -> int:
    hay = _norm(instruction)
    dim_hint = _norm(dimension_hint)
    best = 0

    for phrase in _entry_phrases(entry):
        p = _norm(phrase)
        if not p:
            continue
        if p and p in hay:
            best = max(best, 100)
            continue
        pts = _tokens(p)
        if len(pts) >= 2 and all(t in hay.split() for t in pts):
            best = max(best, 80)

    short = _norm(entry.get("dimensionShortName"))
    if short and re.search(rf"\b{re.escape(short)}\b", hay):
        best = max(best, 70)

    control_type = _norm(entry.get("controlType"))
    if control_type and dim_hint and control_type == dim_hint:
        best = max(best, 30)

    return best


def _normalise_dimension_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry)
    if not out.get("dimensionFullName") and out.get("dimensionShortName") and out.get("sketchFeature"):
        out["dimensionFullName"] = f"{out['dimensionShortName']}@{out['sketchFeature']}"
    return out


def list_sketch_dimension_intents(
    library_dir: Path,
    pn: str,
    revision: str,
    cad_feature_id: str,
) -> List[Dict[str, Any]]:
    """Return reviewed/curated sketch dimensions for one CAD feature."""
    if not cad_feature_id:
        return []
    doc = load_sketch_dimension_intent_map(library_dir, pn, revision)
    if not isinstance(doc, dict):
        return []
    dims = doc.get("dimensions")
    if not isinstance(dims, list):
        return []

    out: List[Dict[str, Any]] = []
    for entry in dims:
        if not isinstance(entry, dict):
            continue
        if entry.get("cadFeatureId") != cad_feature_id:
            continue
        if not isinstance(entry.get("sketchFeature"), str) or not entry.get("sketchFeature").strip():
            continue
        if not isinstance(entry.get("dimensionShortName"), str) or not entry.get("dimensionShortName").strip():
            continue
        out.append(_normalise_dimension_entry(entry))
    return out


def lookup_sketch_dimension_intent(
    library_dir: Path,
    pn: str,
    revision: str,
    cad_feature_id: str,
    instruction: str = "",
    dimension_hint: str = "",
) -> Optional[Dict[str, Any]]:
    """Return a single reviewed sketch-dimension match, or None.

    Matching rules:
    - exact/alias phrase match wins;
    - dimension short name match wins;
    - a weak controlType match is allowed only when it is unique;
    - ties return None.
    """
    candidates = list_sketch_dimension_intents(library_dir, pn, revision, cad_feature_id)
    if not candidates:
        return None

    scored: List[Tuple[int, Dict[str, Any]]] = []
    for entry in candidates:
        score = _score_entry(entry, instruction, dimension_hint)
        if score > 0:
            scored.append((score, entry))
    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    top = [entry for score, entry in scored if score == top_score]
    if len(top) != 1:
        return None
    return top[0]
