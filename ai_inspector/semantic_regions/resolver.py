"""Phrase -> semantic region resolver.

Pure read path: given a user phrase like "top wing" or "show me the
upper wing", look up the matching region in the persisted
{pn}_semantic_regions.json and return the IDs the highlight pipeline
needs (visualTargets.glbNodes for the 3D model, cadTargets.cadFeatureIds
for the future Sage CAD bridge).

Does NOT edit CAD, does NOT mutate the regions file, does NOT touch
HIGHLIGHT_FEATURES behavior. The agent loop calls into this resolver
from a NEW HIGHLIGHT_REGIONS marker; the existing cad_feature_id
resolution stays exactly as it was.

Match priority (first hit wins):
  1. regionId    exact, normalized
  2. label       exact, normalized
  3. alias       exact, normalized
  4. label       substring (either direction)
  5. alias       substring (either direction)
  6. regionId    substring (either direction)  -- last because IDs use
                 underscores and accidentally substring-match small
                 phrases ("wing" hits both top_wing and lower_wing).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .builder import semantic_regions_path


# Match kinds returned in ResolvedRegion.matchKind. Reserved literal
# tuple so downstream code can pattern-match without typos.
MATCH_KINDS = (
    "regionId",
    "label",
    "alias",
    "label_substring",
    "alias_substring",
    "regionId_substring",
)


@dataclass
class ResolvedRegion:
    """Result of a phrase -> region lookup. Equality-friendly so tests
    can assert against (regionId, matchKind, matchedAlias) tuples."""
    regionId:         str
    label:            str
    matchKind:        str
    matchedAlias:     Optional[str]   # populated when matchKind is alias / alias_substring
    glbNodes:         List[str]
    cadFeatureIds:    List[str]
    sourceFeatures:   List[str]
    confidence:       str
    reviewed:         bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regionId":       self.regionId,
            "label":          self.label,
            "matchKind":      self.matchKind,
            "matchedAlias":   self.matchedAlias,
            "glbNodes":       list(self.glbNodes),
            "cadFeatureIds":  list(self.cadFeatureIds),
            "sourceFeatures": list(self.sourceFeatures),
            "confidence":     self.confidence,
            "reviewed":       self.reviewed,
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"[\s_\-]+")


def _normalize(text: str) -> str:
    """Lowercase, replace any run of whitespace/underscore/hyphen with
    a single space, strip ends. So:
      'Top Wing'    -> 'top wing'
      'top_wing'    -> 'top wing'
      'upper-wing'  -> 'upper wing'
      'TopWing'     -> 'topwing'   (CamelCase NOT split; rare in our data)
    Phrases coming from the user/Sage normalize the same way the
    region labels/aliases/IDs do, so cross-format matches just work."""
    if not isinstance(text, str):
        return ""
    return _WS_RE.sub(" ", text.lower()).strip()


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def _load_regions_doc(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    """Return the parsed {pn}_semantic_regions.json document, or None
    when the file is missing / malformed. Never raises -- callers
    treat None as "no semantic data available; let the rest of the
    highlight pipeline take over."""
    p = semantic_regions_path(library_dir, pn, revision)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    return doc


def _region_to_resolved(region: Dict[str, Any], match_kind: str,
                        matched_alias: Optional[str]) -> ResolvedRegion:
    visual_targets = region.get("visualTargets") or {}
    cad_targets    = region.get("cadTargets") or {}
    glb_nodes = visual_targets.get("glbNodes")
    if not isinstance(glb_nodes, list):
        # Schema 1.0.0 -> 1.0.x compatibility: fall back to top-level
        # glbNodes if the structured pointer is missing.
        glb_nodes = region.get("glbNodes") or []
    cad_ids = cad_targets.get("cadFeatureIds")
    if not isinstance(cad_ids, list):
        cad_ids = []
    src_feats = cad_targets.get("sourceFeatures")
    if not isinstance(src_feats, list):
        src_feats = region.get("sourceFeatures") or []
    return ResolvedRegion(
        regionId       = str(region.get("regionId") or ""),
        label          = str(region.get("label") or ""),
        matchKind      = match_kind,
        matchedAlias   = matched_alias,
        glbNodes       = [str(x) for x in glb_nodes if isinstance(x, str)],
        cadFeatureIds  = [str(x) for x in cad_ids   if isinstance(x, str)],
        sourceFeatures = [str(x) for x in src_feats if isinstance(x, str)],
        confidence     = str(region.get("confidence") or "low"),
        reviewed       = bool(region.get("reviewed", False)),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def resolve_region_for_phrase(
    library_dir: Path,
    pn: str,
    revision: str,
    phrase: str,
) -> Optional[ResolvedRegion]:
    """Return the best-matching region for a user phrase, or None.

    Returns None when:
      - phrase is empty / non-str
      - {pn}_semantic_regions.json does not exist
      - file is malformed
      - no region's regionId / label / aliases match the phrase

    Match priority documented at the top of the module. Substring
    matches are bidirectional ("the upper wing" matches alias
    "upper wing" via phrase-contains-target; "wing" matches "top
    wing" via target-contains-phrase). Substring rules only fire
    when the candidate is at least 4 characters long so a stray
    "a" can't sweep the room."""
    if not isinstance(phrase, str):
        return None
    needle = _normalize(phrase)
    if not needle:
        return None

    doc = _load_regions_doc(library_dir, pn, revision)
    if not doc:
        return None
    regions = doc.get("regions")
    if not isinstance(regions, list) or not regions:
        return None

    # Phase 1: exact-match passes (regionId -> label -> alias).
    for r in regions:
        if not isinstance(r, dict):
            continue
        if _normalize(r.get("regionId") or "") == needle:
            return _region_to_resolved(r, "regionId", matched_alias=None)
    for r in regions:
        if not isinstance(r, dict):
            continue
        if _normalize(r.get("label") or "") == needle:
            return _region_to_resolved(r, "label", matched_alias=None)
    for r in regions:
        if not isinstance(r, dict):
            continue
        aliases = r.get("aliases") if isinstance(r.get("aliases"), list) else []
        for alias in aliases:
            if isinstance(alias, str) and _normalize(alias) == needle:
                return _region_to_resolved(r, "alias", matched_alias=alias)

    # Phase 2: substring passes. Only candidate>=4 chars, to avoid
    # noise matches on tiny words.
    def _substring_match(target: str) -> bool:
        t = _normalize(target)
        if len(t) < 4 or len(needle) < 4:
            return False
        return t in needle or needle in t

    for r in regions:
        if not isinstance(r, dict):
            continue
        if _substring_match(r.get("label") or ""):
            return _region_to_resolved(r, "label_substring", matched_alias=None)
    for r in regions:
        if not isinstance(r, dict):
            continue
        aliases = r.get("aliases") if isinstance(r.get("aliases"), list) else []
        for alias in aliases:
            if isinstance(alias, str) and _substring_match(alias):
                return _region_to_resolved(r, "alias_substring", matched_alias=alias)
    for r in regions:
        if not isinstance(r, dict):
            continue
        if _substring_match(r.get("regionId") or ""):
            return _region_to_resolved(r, "regionId_substring", matched_alias=None)

    return None


def resolve_regions_for_phrases(
    library_dir: Path,
    pn: str,
    revision: str,
    phrases: List[str],
) -> List[ResolvedRegion]:
    """Resolve a list of phrases, dropping any that don't match. Used
    by the HIGHLIGHT_REGIONS marker parser when Sage emits multiple
    region names on one line."""
    out: List[ResolvedRegion] = []
    seen_region_ids = set()
    for p in phrases or []:
        hit = resolve_region_for_phrase(library_dir, pn, revision, p)
        if hit is None:
            continue
        # Dedupe -- multiple phrases hitting the same region collapse.
        if hit.regionId in seen_region_ids:
            continue
        seen_region_ids.add(hit.regionId)
        out.append(hit)
    return out
