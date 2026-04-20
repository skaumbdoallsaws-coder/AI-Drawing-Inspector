"""Drawing Revision Diff Engine — MVP.

Compares two revisions of a drawing_map (Rev A vs Rev B) and produces a
structured diff covering:
  - Global cross-sheet view matching
  - Annotation identity matching + diff (dimensions, notes, GD&T, etc.)
  - Sheet-level metadata diff (title block, revision table, sheet notes)
  - Compare eligibility per matched view
  - Projected model delta (coarse bbox/centroid regions, advisory only)
  - Native visible primitive diff (Phase 4+, additive when present)
  - Conservative verdict engine

Contract version: 1.0
"""

from __future__ import annotations

import math
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CONTRACT_VERSION = "1.0"

# ── View matching constants ─────────────────────────────────────────────────

# View family groupings — views within the same family can match;
# cross-family matches are hard-gated.
_VIEW_FAMILIES = {
    "standard":   {"Standard", "Named", "Projected"},
    "section":    {"Section"},
    "detail":     {"Detail"},
    "isometric":  {"Isometric", "Trimetric", "Dimetric"},
    "auxiliary":  {"Auxiliary"},
}

_TYPE_TO_FAMILY: Dict[str, str] = {}
for fam, types in _VIEW_FAMILIES.items():
    for t in types:
        _TYPE_TO_FAMILY[t] = fam

# Standard orientations for compatibility check
_ORIENTATIONS = {"Front", "Top", "Right", "Back", "Bottom", "Left",
                 "Isometric", "Trimetric", "Dimetric"}

# Annotation types included in diff
_DIFFABLE_ANNOTATION_TYPES = {
    "displayDimension", "note", "gtol", "surfaceFinish",
    "datumTag", "datumTarget", "holeCallout",
}

# Annotation types excluded from diff
_EXCLUDED_ANNOTATION_TYPES = {"balloon", "centerMark", "centerLine"}

# Position tolerance for annotation identity matching:
# fraction of view-outline diagonal
_POSITION_TOL_FRACTION = 0.12

# Minimum confidence to accept a view match
_VIEW_MATCH_MIN_CONFIDENCE = 0.3


def _view_key(view_name: str, sheet_name: str) -> str:
    """Build a sheet-scoped stable identifier for a view.

    Bare viewName can collide across sheets (e.g. two sheets each have
    "Drawing View1"). Using viewName@sheetName prevents overwrites in
    per-view dicts.
    """
    return f"{view_name}@{sheet_name}"


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

def compute_drawing_diff(
    drawing_map_a: dict,
    drawing_map_b: dict,
    geometry_diff: Optional[dict] = None,
    part_json_a: Optional[dict] = None,
    part_json_b: Optional[dict] = None,
) -> dict:
    """Compare two drawing map revisions and return structured diff.

    Parameters
    ----------
    drawing_map_a : dict
        Normalized drawing map for Rev A (base/old).
    drawing_map_b : dict
        Normalized drawing map for Rev B (target/new).
    geometry_diff : dict, optional
        Cached 3D geometry diff result (from geometry_worker).
    part_json_a, part_json_b : dict, optional
        Part JSONs for bbox center computation (for projected model delta).

    Returns
    -------
    dict
        Structured compare artifact with contractVersion 1.0.
    """
    # ── Flatten views from both maps ────────────────────────────────────
    views_a = _flatten_views(drawing_map_a)
    views_b = _flatten_views(drawing_map_b)

    # ── Layer 1: View identity matching ─────────────────────────────────
    view_identity = _match_views(views_a, views_b)

    # ── Layer 2: Compare eligibility ────────────────────────────────────
    compare_eligibility = _compute_eligibility(view_identity)

    # ── Layer 3: Annotation diff per matched view ───────────────────────
    annotation_diff = _compute_annotation_diff(view_identity, compare_eligibility)

    # ── Layer 4: Sheet-level metadata diff ──────────────────────────────
    sheet_metadata_diff = _compute_sheet_metadata_diff(drawing_map_a, drawing_map_b)

    # ── Layer 5: Projected model delta (coarse) ─────────────────────────
    geometry_diff_section = _compute_projected_model_delta(
        view_identity, geometry_diff, drawing_map_b,
        part_json_a, part_json_b,
        eligibility=compare_eligibility,
    )
    geometry_diff_section = _refine_projected_model_delta_for_display(
        geometry_diff_section,
        annotation_diff,
    )

    native_geometry_priority = _compute_native_geometry_priority(
        view_identity,
        compare_eligibility,
        annotation_diff,
        geometry_diff_section,
        views_b,
    )

    # ── Layer 6: Verdict engine ─────────────────────────────────────────
    native_geometry_diff = _compute_native_geometry_diff(
        view_identity,
        compare_eligibility,
        views_a,
        views_b,
    )

    user_facing_findings = _compute_verdicts(
        view_identity, annotation_diff, geometry_diff_section, native_geometry_diff,
        compare_eligibility,
    )

    # ── Build summary ───────────────────────────────────────────────────
    summary = _build_summary(view_identity, annotation_diff,
                             geometry_diff_section, native_geometry_diff, user_facing_findings)

    # ── Sheet dimensions for self-contained overlay geometry ────────────
    # Per-sheet dims keyed by sheetName (handles multi-sheet drawings with
    # different sheet sizes). Also include global fallback dims.
    sheet_dims_a = _extract_per_sheet_dims(drawing_map_a)
    sheet_dims_b = _extract_per_sheet_dims(drawing_map_b)

    return {
        "contractVersion": CONTRACT_VERSION,
        "viewIdentity": view_identity,
        "compareEligibility": compare_eligibility,
        "annotationDiff": annotation_diff,
        "sheetMetadataDiff": sheet_metadata_diff,
        "geometryDiff": geometry_diff_section,
        "nativeGeometryPriority": native_geometry_priority,
        "nativeGeometryDiff": native_geometry_diff,
        "userFacingFindings": user_facing_findings,
        "summary": summary,
        "sheetDimsA": sheet_dims_a,
        "sheetDimsB": sheet_dims_b,
    }


def _extract_per_sheet_dims(drawing_map: dict) -> dict:
    """Extract per-sheet dimensions plus a global fallback."""
    global_w = drawing_map.get("sheetWidth")
    global_h = drawing_map.get("sheetHeight")
    per_sheet = {}
    for sheet in drawing_map.get("sheets", []):
        sn = sheet.get("sheetName", "Sheet1")
        per_sheet[sn] = {
            "sheetWidth": sheet.get("sheetWidth") or global_w,
            "sheetHeight": sheet.get("sheetHeight") or global_h,
        }
    return {
        "sheetWidth": global_w,
        "sheetHeight": global_h,
        "perSheet": per_sheet,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1: View Matching
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class _FlatView:
    """A view with sheet context, for cross-sheet matching."""
    view_name: str
    view_type: str
    view_orientation: str
    view_scale: float
    view_outline: List[float]      # [x_min, y_min, x_max, y_max]
    view_position: List[float]     # [x, y]
    sheet_name: str
    sheet_index: int
    sheet_width: float
    sheet_height: float
    annotations: List[dict]
    primitives: List[dict]
    raw: dict                      # original view dict


def _flatten_views(drawing_map: dict) -> List[_FlatView]:
    """Extract all views from all sheets into a flat list."""
    result = []
    for sheet in drawing_map.get("sheets", []):
        sheet_name = sheet.get("sheetName", "Sheet1")
        sheet_idx = sheet.get("sheetIndex", 1)
        sheet_w = sheet.get("sheetWidth", 0.5)
        sheet_h = sheet.get("sheetHeight", 0.4)
        for view in sheet.get("views", []):
            outline = view.get("viewOutline") or [0, 0, 0.1, 0.1]
            position = view.get("viewPosition") or [0, 0]
            result.append(_FlatView(
                view_name=view.get("viewName", ""),
                view_type=view.get("viewType", "Standard"),
                view_orientation=view.get("viewOrientation", ""),
                view_scale=view.get("viewScale", 1.0),
                view_outline=outline if len(outline) >= 4 else [0, 0, 0.1, 0.1],
                view_position=position if len(position) >= 2 else [0, 0],
                sheet_name=sheet_name,
                sheet_index=sheet_idx,
                sheet_width=sheet_w,
                sheet_height=sheet_h,
                annotations=view.get("annotations", []),
                primitives=view.get("primitives", []),
                raw=view,
            ))
    return result


def _view_family(view_type: str) -> str:
    """Map view type to family."""
    return _TYPE_TO_FAMILY.get(view_type, "standard")


def _normalize_view_name(name: str) -> str:
    """Normalize view name for comparison."""
    # Strip sheet qualifiers, lowercase, collapse whitespace
    n = re.sub(r'\s+', ' ', name.strip().lower())
    # Remove trailing numbers for fuzzy matching: "Drawing View1" -> "drawing view"
    n = re.sub(r'\d+$', '', n).strip()
    return n


def _view_name_similarity(name_a: str, name_b: str) -> float:
    """Score name similarity 0-1."""
    na = _normalize_view_name(name_a)
    nb = _normalize_view_name(name_b)
    if na == nb:
        return 1.0
    # Exact raw match
    if name_a.strip().lower() == name_b.strip().lower():
        return 1.0
    # One contains the other
    if na and nb and (na in nb or nb in na):
        return 0.7
    # Token overlap
    ta = set(na.split())
    tb = set(nb.split())
    if ta and tb:
        overlap = len(ta & tb) / max(len(ta | tb), 1)
        return overlap * 0.5
    return 0.0


def _outline_aspect_ratio(outline: List[float]) -> float:
    """Compute aspect ratio from viewOutline."""
    w = abs(outline[2] - outline[0]) if len(outline) >= 4 else 0.1
    h = abs(outline[3] - outline[1]) if len(outline) >= 4 else 0.1
    if h < 1e-9:
        return 999.0
    return w / h


def _outline_diagonal(outline: List[float]) -> float:
    """Compute diagonal length of viewOutline."""
    w = abs(outline[2] - outline[0]) if len(outline) >= 4 else 0.1
    h = abs(outline[3] - outline[1]) if len(outline) >= 4 else 0.1
    return math.sqrt(w * w + h * h)


def _score_view_pair(va: _FlatView, vb: _FlatView) -> Tuple[float, dict]:
    """Score how well two views match. Returns (score, evidence).

    Higher score = better match. Returns -1 for hard-gated incompatible pairs.
    """
    evidence = {}

    # ── Hard gates ──────────────────────────────────────────────────────
    fam_a = _view_family(va.view_type)
    fam_b = _view_family(vb.view_type)
    if fam_a != fam_b:
        return -1.0, {"reason": "family_mismatch", "famA": fam_a, "famB": fam_b}

    # Orientation mismatch within standard views
    if (va.view_orientation and vb.view_orientation
            and va.view_orientation in _ORIENTATIONS
            and vb.view_orientation in _ORIENTATIONS
            and va.view_orientation != vb.view_orientation):
        return -1.0, {"reason": "orientation_mismatch"}

    # ── Scoring ─────────────────────────────────────────────────────────
    score = 0.0

    # Name similarity (0-0.35)
    name_sim = _view_name_similarity(va.view_name, vb.view_name)
    score += name_sim * 0.35
    evidence["nameSimilarity"] = round(name_sim, 3)

    # View type match (0-0.15)
    type_score = 1.0 if va.view_type == vb.view_type else 0.3
    score += type_score * 0.15
    evidence["typeMatch"] = va.view_type == vb.view_type

    # Orientation match (0-0.15)
    if va.view_orientation and vb.view_orientation:
        orient_score = 1.0 if va.view_orientation == vb.view_orientation else 0.0
    elif not va.view_orientation and not vb.view_orientation:
        orient_score = 0.5  # both unknown — neutral
    else:
        orient_score = 0.2  # one known, one not — slight penalty
    score += orient_score * 0.15
    evidence["orientationMatch"] = va.view_orientation == vb.view_orientation

    # Scale similarity (0-0.1) — mismatch lowers confidence, doesn't block
    scale_a = va.view_scale or 1.0
    scale_b = vb.view_scale or 1.0
    scale_ratio = min(scale_a, scale_b) / max(scale_a, scale_b) if max(scale_a, scale_b) > 0 else 1.0
    score += scale_ratio * 0.1
    evidence["scaleRatio"] = round(scale_ratio, 3)

    # Aspect ratio similarity (0-0.1)
    ar_a = _outline_aspect_ratio(va.view_outline)
    ar_b = _outline_aspect_ratio(vb.view_outline)
    ar_ratio = min(ar_a, ar_b) / max(ar_a, ar_b) if max(ar_a, ar_b) > 0 else 1.0
    score += ar_ratio * 0.1
    evidence["aspectRatioSimilarity"] = round(ar_ratio, 3)

    # Normalized position similarity (0-0.1) — views in similar sheet positions
    pos_a = (va.view_position[0] / max(va.sheet_width, 0.01),
             va.view_position[1] / max(va.sheet_height, 0.01))
    pos_b = (vb.view_position[0] / max(vb.sheet_width, 0.01),
             vb.view_position[1] / max(vb.sheet_height, 0.01))
    pos_dist = math.sqrt((pos_a[0] - pos_b[0]) ** 2 + (pos_a[1] - pos_b[1]) ** 2)
    pos_score = max(0.0, 1.0 - pos_dist)
    score += pos_score * 0.1
    evidence["positionSimilarity"] = round(pos_score, 3)

    # Annotation count similarity (0-0.05) — tiebreaker
    n_a = len(va.annotations)
    n_b = len(vb.annotations)
    if max(n_a, n_b) > 0:
        ann_score = min(n_a, n_b) / max(n_a, n_b)
    else:
        ann_score = 1.0
    score += ann_score * 0.05
    evidence["annotationCountSimilarity"] = round(ann_score, 3)

    return round(score, 4), evidence


def _match_views(
    views_a: List[_FlatView],
    views_b: List[_FlatView],
) -> dict:
    """Global cross-sheet view matching using greedy best-score assignment.

    Returns structured viewIdentity section of the contract.
    """
    # Score all valid pairs
    scored_pairs: List[Tuple[float, int, int, dict]] = []
    for i, va in enumerate(views_a):
        for j, vb in enumerate(views_b):
            score, evidence = _score_view_pair(va, vb)
            if score >= _VIEW_MATCH_MIN_CONFIDENCE:
                scored_pairs.append((score, i, j, evidence))

    # Greedy assignment: highest score first, each view used at most once
    scored_pairs.sort(key=lambda x: x[0], reverse=True)
    used_a: set = set()
    used_b: set = set()
    matched: List[dict] = []
    ambiguous: List[dict] = []

    for score, i, j, evidence in scored_pairs:
        if i in used_a or j in used_b:
            continue
        va = views_a[i]
        vb = views_b[j]
        migrated = va.sheet_name != vb.sheet_name
        vk = _view_key(vb.view_name, vb.sheet_name)
        match_entry = {
            "viewKey": vk,
            "viewNameA": va.view_name,
            "viewNameB": vb.view_name,
            "sheetNameA": va.sheet_name,
            "sheetNameB": vb.sheet_name,
            "viewOutlineA": va.view_outline,
            "viewOutlineB": vb.view_outline,
            "confidence": score,
            "matchMethod": "global_score",
            "evidence": evidence,
            "migratedSheet": migrated,
            "viewType": va.view_type,
            "viewOrientation": va.view_orientation or vb.view_orientation or "",
            "viewScale": vb.view_scale,
        }
        # Check for ambiguity: is there another strong candidate?
        alternatives = [
            (s, ii, jj) for s, ii, jj, _ in scored_pairs
            if (ii == i and jj != j and jj not in used_b) or
               (jj == j and ii != i and ii not in used_a)
        ]
        best_alt = max((s for s, _, _ in alternatives), default=0.0)
        if best_alt > 0 and (score - best_alt) < 0.1:
            match_entry["ambiguous"] = True
            match_entry["ambiguityGap"] = round(score - best_alt, 3)
            ambiguous.append(match_entry)
        else:
            match_entry["ambiguous"] = False

        matched.append(match_entry)
        used_a.add(i)
        used_b.add(j)

    # Unmatched
    unmatched_base = [
        {"viewKey": _view_key(views_a[i].view_name, views_a[i].sheet_name),
         "viewName": views_a[i].view_name, "sheetName": views_a[i].sheet_name,
         "viewType": views_a[i].view_type}
        for i in range(len(views_a)) if i not in used_a
    ]
    unmatched_target = [
        {"viewKey": _view_key(views_b[j].view_name, views_b[j].sheet_name),
         "viewName": views_b[j].view_name, "sheetName": views_b[j].sheet_name,
         "viewType": views_b[j].view_type}
        for j in range(len(views_b)) if j not in used_b
    ]

    return {
        "matched": matched,
        "unmatchedBase": unmatched_base,
        "unmatchedTarget": unmatched_target,
        "ambiguous": [m for m in matched if m.get("ambiguous")],
        "totalViewsA": len(views_a),
        "totalViewsB": len(views_b),
        "_viewsA": views_a,
        "_viewsB": views_b,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2: Compare Eligibility
# ═══════════════════════════════════════════════════════════════════════════

def _compute_eligibility(view_identity: dict) -> dict:
    """Determine what compare operations are supported for each matched view."""
    per_view = {}
    for match in view_identity["matched"]:
        vk = match["viewKey"]
        vtype = match.get("viewType", "Standard")
        family = _view_family(vtype)
        confidence = match["confidence"]

        ann_eligible = confidence >= 0.4
        proj_eligible = (
            confidence >= 0.5
            and family in ("standard", "section", "detail")
        )
        geom_eligible = (
            confidence >= 0.5
            and family in ("standard", "detail")
        )

        reasons = []
        if not ann_eligible:
            reasons.append("view_match_confidence_too_low")
        if not proj_eligible:
            if confidence < 0.5:
                reasons.append("view_match_confidence_below_projection_threshold")
            if family not in ("standard", "section", "detail"):
                reasons.append(f"view_family_{family}_not_supported_for_projection")
        if not geom_eligible:
            if confidence < 0.5:
                reasons.append("view_match_confidence_below_native_geometry_threshold")
            if family not in ("standard", "detail"):
                reasons.append(f"view_family_{family}_not_supported_for_native_geometry")

        per_view[vk] = {
            "supportedForAnnotationDiff": ann_eligible,
            "supportedForProjectedModelReasoning": proj_eligible,
            "supportedForNativeGeometryDiff": geom_eligible,
            "eligibilityReasons": reasons,
            "viewMatchConfidence": confidence,
        }

    return {"perView": per_view}


def _compute_native_geometry_priority(
    view_identity: dict,
    compare_eligibility: dict,
    annotation_diff: dict,
    geometry_diff_section: dict,
    views_b: List[Any],
) -> dict:
    """Rank matched views by how worthwhile exact native-geometry extraction is.

    This is predictive rather than evidentiary. It uses only cheap upstream
    signals that are available before native primitive compare is required:
    match confidence, view family/scale, annotation diff, and projected-model
    delta quality.
    """
    per_view: Dict[str, dict] = {}
    lookup_b = { _view_key(v.view_name, v.sheet_name): v for v in views_b }

    for match in view_identity.get("matched", []):
        vk = match["viewKey"]
        elig = compare_eligibility.get("perView", {}).get(vk, {})
        ann_view = annotation_diff.get("perView", {}).get(vk, {})
        geom_view = geometry_diff_section.get("perView", {}).get(vk, {})

        family = _view_family(match.get("viewType", "Standard"))
        confidence = float(match.get("confidence") or 0.0)
        view_scale = float(match.get("viewScale") or 1.0)
        view_b = lookup_b.get(vk)

        ann_changed = bool(ann_view.get("hasChanges"))
        ann_change_count = (
            len(ann_view.get("modified", []) or [])
            + len(ann_view.get("added", []) or [])
            + len(ann_view.get("removed", []) or [])
        )

        displayed_proj_count = len(geom_view.get("projectedRegions", []) or [])
        all_proj_count = int(
            geom_view.get("allProjectedRegionsCount", displayed_proj_count) or 0
        )
        suppressed_proj_count = max(0, all_proj_count - displayed_proj_count)
        proj_delta_present = bool(geom_view.get("deltaPresent"))

        score = 0.0
        reasons: List[str] = []

        # Match confidence is useful, but only as a secondary signal.
        score += min(10.0, confidence * 10.0)
        if confidence >= 0.8:
            reasons.append("high_view_match_confidence")
        elif confidence >= 0.5:
            reasons.append("acceptable_view_match_confidence")

        # View family / scale priors.
        if family == "detail":
            score += 12.0
            reasons.append("detail_view_magnifies_local_geometry")
        elif family == "standard":
            score += 8.0
            reasons.append("standard_view_family_supported")
        elif family == "section":
            score += 4.0
            reasons.append("section_view_can_show_cut_geometry")

        if view_scale >= 1.0:
            score += 6.0
            reasons.append("high_view_scale")
        elif view_scale >= 0.5:
            score += 3.0
            reasons.append("moderate_view_scale")

        geometry_cues = _count_native_geometry_cues(view_b)
        if family == "detail" and geometry_cues > 0:
            score += min(24.0, 8.0 + geometry_cues * 3.0)
            reasons.append(f"detail_view_geometry_cues:{geometry_cues}")

        # Strongest predictor: explicit drawing evidence in the same view.
        if ann_changed:
            score += 45.0 + min(10.0, ann_change_count * 2.0)
            reasons.append(f"annotation_diff_present:{ann_change_count}")

        # Second-best predictor: model delta projects into this view.
        if displayed_proj_count > 0:
            score += 35.0 + min(10.0, displayed_proj_count * 2.0)
            reasons.append(f"projected_model_delta_displayed:{displayed_proj_count}")
        elif proj_delta_present:
            score += 8.0
            reasons.append("projected_model_delta_present_but_suppressed")

        # Suppressed-only projections are weaker duplicates; penalize them unless
        # the view also has local annotation evidence.
        if suppressed_proj_count and not ann_changed:
            score -= min(10.0, suppressed_proj_count * 2.5)
            reasons.append("projection_weaker_than_other_views")

        if not ann_changed and not proj_delta_present:
            score = max(0.0, score - 12.0)
            reasons.append("no_annotation_or_model_delta_evidence")

        supported = bool(elig.get("supportedForNativeGeometryDiff", False))
        if not supported:
            reasons.extend(elig.get("eligibilityReasons", []) or [])

        score = round(max(0.0, score), 2)
        if not supported:
            tier = "skip"
        elif score >= 60.0:
            tier = "extract_now"
        elif score >= 30.0:
            tier = "consider"
        else:
            tier = "skip"

        per_view[vk] = {
            "score": score,
            "tier": tier,
            "recommended": tier != "skip",
            "signals": {
                "viewFamily": family,
                "viewScale": round(view_scale, 4),
                "viewMatchConfidence": round(confidence, 3),
                "annotationDiffPresent": ann_changed,
                "annotationChangeCount": ann_change_count,
                "projectedModelDeltaPresent": proj_delta_present,
                "displayProjectedRegionsCount": displayed_proj_count,
                "suppressedProjectedRegionsCount": suppressed_proj_count,
                "nativeGeometrySupported": supported,
                "geometryCueCount": geometry_cues,
            },
            "reasons": reasons,
        }

    ranked = sorted(
        per_view.items(),
        key=lambda item: (-item[1]["score"], item[0]),
    )

    extract_now = [vk for vk, item in ranked if item["tier"] == "extract_now"]
    consider = [vk for vk, item in ranked if item["tier"] == "consider"]
    skip = [vk for vk, item in ranked if item["tier"] == "skip"]

    return {
        "perView": per_view,
        "preferredExtractionOrder": extract_now + consider,
        "extractNowViewKeys": extract_now,
        "considerViewKeys": consider,
        "skipViewKeys": skip,
    }


def _coerce_primitive_points(points: Any) -> List[Tuple[float, float]]:
    if not isinstance(points, list):
        return []
    out: List[Tuple[float, float]] = []
    for pt in points:
        if isinstance(pt, dict):
            x = pt.get("x")
            y = pt.get("y")
        elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
            x, y = pt[0], pt[1]
        else:
            continue
        try:
            out.append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    return out


def _count_native_geometry_cues(view: Any) -> int:
    """Count lightweight signals that a view is likely to expose exact geometry.

    This stays intentionally cheap and uses only already-extracted drawing data.
    It is most useful for detail views that may not receive a projected-model
    delta overlay cleanly but still magnify the changed feature.
    """
    if view is None:
        return 0

    score = 0
    for ann in getattr(view, "annotations", []) or []:
        ann_type = (ann.get("annotationType") or "").strip()
        dim_type = (ann.get("dimensionType") or "").strip().lower()
        dim_text = (ann.get("dimensionText") or "").upper()
        note_text = (ann.get("noteText") or "").upper()

        if ann_type == "holeCallout":
            score += 3
        elif ann_type == "centerMark":
            score += 2
        elif ann_type == "centerLine":
            score += 1

        if ann_type == "displayDimension":
            if dim_type in ("diametric", "radial"):
                score += 3
            if "<MOD-DIAM>" in dim_text or "<MOD DIAM>" in dim_text or "Ø" in dim_text:
                score += 2
            if "R " in dim_text or dim_text.startswith("R"):
                score += 1

        if "THRU" in dim_text or "THRU" in note_text:
            score += 1

    return score


def _primitive_local_signature(primitive: dict, tol: float) -> Optional[Tuple[Any, ...]]:
    primitive_type = (primitive.get("primitiveType") or "polyline").lower()
    source_kind = primitive.get("sourceKind") or "modelEdge"
    center = primitive.get("centerView")
    radius = primitive.get("radiusView")
    points = _coerce_primitive_points(primitive.get("pointsView"))
    if radius is not None:
        try:
            if isinstance(center, dict):
                cx = center["x"]
                cy = center["y"]
            elif isinstance(center, (list, tuple)) and len(center) >= 2:
                cx, cy = center[0], center[1]
            else:
                raise TypeError("Unsupported centerView shape")

            qx = round(float(cx) / tol)
            qy = round(float(cy) / tol)
            qr = round(float(radius) / tol)

            # Circles should not be keyed from sampled point loops. The tessellation
            # can vary slightly across revisions/extractions even when the actual
            # circle is unchanged, which produces false "all lines changed" overlays.
            if primitive_type == "circle":
                return ("circle", source_kind, qx, qy, qr)

            # Arcs benefit from stable center/radius matching too, but they also need
            # start/end discrimination so different sweeps at the same radius do not
            # collapse together.
            if primitive_type == "arc" and qr > 0:
                start = end = None
                if points:
                    start = (round(points[0][0] / tol), round(points[0][1] / tol))
                    end = (round(points[-1][0] / tol), round(points[-1][1] / tol))
                    if end < start:
                        start, end = end, start
                return ("arc", source_kind, qx, qy, qr, start, end)
        except (KeyError, TypeError, ValueError):
            return None

    if points:
        qpts = tuple((round(x / tol), round(y / tol)) for x, y in points)
        rqpts = tuple(reversed(qpts))
        if rqpts < qpts:
            qpts = rqpts
        return ("pts", primitive_type, source_kind, qpts)

    bounds = primitive.get("boundsView")
    if isinstance(bounds, list) and len(bounds) >= 4:
        try:
            qb = tuple(round(float(v) / tol) for v in bounds[:4])
            return ("bbox", primitive_type, source_kind, qb)
        except (TypeError, ValueError):
            return None
    return None


def _view_lookup(views: List[_FlatView]) -> Dict[str, _FlatView]:
    return {_view_key(v.view_name, v.sheet_name): v for v in views}


def _primitive_display_bounds(primitive: dict) -> Optional[List[float]]:
    bounds = primitive.get("boundsSheet")
    if isinstance(bounds, list) and len(bounds) >= 4:
        return bounds[:4]
    points = _coerce_primitive_points(primitive.get("pointsSheet"))
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _compute_native_geometry_diff(
    view_identity: dict,
    compare_eligibility: dict,
    views_a: List[_FlatView],
    views_b: List[_FlatView],
) -> dict:
    per_view: Dict[str, dict] = {}
    lookup_a = _view_lookup(views_a)
    lookup_b = _view_lookup(views_b)
    total_added = 0
    total_removed = 0

    for match in view_identity["matched"]:
        vk = match["viewKey"]
        elig = compare_eligibility.get("perView", {}).get(vk, {})
        if not elig.get("supportedForNativeGeometryDiff", False):
            per_view[vk] = {
                "skipped": True,
                "hasChanges": False,
                "added": [],
                "removed": [],
                "unchangedCount": 0,
            }
            continue

        key_a = _view_key(match["viewNameA"], match["sheetNameA"])
        view_a = lookup_a.get(key_a)
        view_b = lookup_b.get(vk)
        primitives_a = list(view_a.primitives if view_a else [])
        primitives_b = list(view_b.primitives if view_b else [])

        if not primitives_a or not primitives_b:
            per_view[vk] = {
                "skipped": True,
                "hasChanges": False,
                "added": [],
                "removed": [],
                "unchangedCount": 0,
            }
            continue

        tol = max(_outline_diagonal(match.get("viewOutlineB") or [0, 0, 0.1, 0.1]) * 0.002, 1e-5)
        buckets_a: Dict[Tuple[Any, ...], List[dict]] = {}
        buckets_b: Dict[Tuple[Any, ...], List[dict]] = {}

        for primitive in primitives_a:
            sig = _primitive_local_signature(primitive, tol)
            if sig is not None:
                buckets_a.setdefault(sig, []).append(primitive)

        for primitive in primitives_b:
            sig = _primitive_local_signature(primitive, tol)
            if sig is not None:
                buckets_b.setdefault(sig, []).append(primitive)

        removed: List[dict] = []
        added: List[dict] = []
        unchanged = 0
        all_sigs = set(buckets_a.keys()) | set(buckets_b.keys())
        for sig in all_sigs:
            list_a = buckets_a.get(sig, [])
            list_b = buckets_b.get(sig, [])
            shared = min(len(list_a), len(list_b))
            unchanged += shared
            if len(list_a) > shared:
                removed.extend(list_a[shared:])
            if len(list_b) > shared:
                added.extend(list_b[shared:])

        for primitive in removed:
            primitive.setdefault("displayBounds", _primitive_display_bounds(primitive))
        for primitive in added:
            primitive.setdefault("displayBounds", _primitive_display_bounds(primitive))

        total_removed += len(removed)
        total_added += len(added)
        per_view[vk] = {
            "skipped": False,
            "hasChanges": bool(added or removed),
            "added": added,
            "removed": removed,
            "unchangedCount": unchanged,
        }

    return {
        "available": any(not item.get("skipped", False) for item in per_view.values()),
        "perView": per_view,
        "totalAdded": total_added,
        "totalRemoved": total_removed,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3: Annotation Diff
# ═══════════════════════════════════════════════════════════════════════════

# ── Annotation matching thresholds ──────────────────────────────────────
_ANN_MATCH_STRONG = 0.5      # cost ≤ this → confident match
_ANN_MATCH_WEAK = 1.5        # cost ≤ this → acceptable match
_ANN_MATCH_ABSTAIN = 1.5     # cost > this → don't force; treat as removed + added
_ANN_AMBIGUITY_GAP = 0.3     # gap < this between best and second-best → ambiguous
_ANN_INF_COST = 1e6


def _ann_pos(ann: dict) -> Tuple[float, float]:
    """Extract (x, y) from annotation positionSheet."""
    pos = ann.get("positionSheet")
    if isinstance(pos, dict):
        return (pos.get("x", 0.0), pos.get("y", 0.0))
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return (float(pos[0]), float(pos[1]))
    return (0.0, 0.0)


def _ann_text(ann: dict) -> str:
    """Get the primary text content for an annotation."""
    for key in ("dimensionText", "noteText", "gtolText"):
        v = ann.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _normalize_ann_text(text: str) -> str:
    """Normalize annotation text for comparison."""
    import re as _re
    t = text.lower().strip()
    t = _re.sub(r'\s+', ' ', t)
    # Normalize common symbols
    t = t.replace('<mod-diam>', '\u2300').replace('⌀', '\u2300')
    return t


def _text_similarity(a: str, b: str) -> float:
    """Simple text similarity: 1.0 = identical, 0.0 = completely different."""
    na = _normalize_ann_text(a)
    nb = _normalize_ann_text(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # Character-level Jaccard on bigrams
    def bigrams(s):
        return set(s[i:i+2] for i in range(max(len(s)-1, 1)))
    ba, bb = bigrams(na), bigrams(nb)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def _ann_bounds_iou(a: dict, b: dict) -> float:
    """Intersection-over-union of boundsSheet, or -1 if either is missing."""
    ba = a.get("boundsSheet")
    bb = b.get("boundsSheet")
    if not ba or len(ba) < 4 or not bb or len(bb) < 4:
        return -1.0
    x1 = max(ba[0], bb[0])
    y1 = max(ba[1], bb[1])
    x2 = min(ba[2], bb[2])
    y2 = min(ba[3], bb[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, ba[2] - ba[0]) * max(0, ba[3] - ba[1])
    area_b = max(0, bb[2] - bb[0]) * max(0, bb[3] - bb[1])
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _annotation_position_distance(a: dict, b: dict) -> float:
    """Euclidean distance between annotation positions, or inf if unavailable."""
    ax, ay = _ann_pos(a)
    bx, by = _ann_pos(b)
    if (ax, ay) == (0.0, 0.0) and not a.get("positionSheet"):
        return float("inf")
    if (bx, by) == (0.0, 0.0) and not b.get("positionSheet"):
        return float("inf")
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _compute_ann_match_cost(
    ann_a: dict,
    ann_b: dict,
    view_diagonal: float,
) -> float:
    """Compute matching cost between two annotations. Lower = better match.

    Signals:
      - type compatibility (hard gate)
      - annotationName exact match (strong)
      - position proximity
      - dimension value similarity
      - text similarity
      - bounds overlap
    """
    # Hard gate: type must match
    type_a = ann_a.get("annotationType", "")
    type_b = ann_b.get("annotationType", "")
    if type_a != type_b:
        return _ANN_INF_COST

    cost = 0.0

    # ── annotationName match (weight: 0.35) ────────────────────────────
    name_a = ann_a.get("annotationName", "")
    name_b = ann_b.get("annotationName", "")
    if name_a and name_b and name_a == name_b:
        name_cost = 0.0  # Strong: same stable SolidWorks name
    elif name_a and name_b:
        name_cost = 1.0  # Different names — penalty
    else:
        name_cost = 0.5  # One or both missing — neutral
    cost += name_cost * 0.35

    # ── Position proximity (weight: 0.25) ──────────────────────────────
    px_a, py_a = _ann_pos(ann_a)
    px_b, py_b = _ann_pos(ann_b)
    dist = math.sqrt((px_a - px_b) ** 2 + (py_a - py_b) ** 2)
    pos_tol = max(view_diagonal * _POSITION_TOL_FRACTION, 0.002)
    if dist <= pos_tol:
        pos_cost = dist / pos_tol  # 0-1 within tolerance
    else:
        pos_cost = 1.0 + (dist - pos_tol) / pos_tol  # >1 beyond tolerance
    cost += min(pos_cost, 3.0) * 0.25

    # ── Value similarity (weight: 0.2, dimensions only) ────────────────
    val_a = ann_a.get("dimensionValue")
    val_b = ann_b.get("dimensionValue")
    if val_a is not None and val_b is not None:
        val_tol = 0.0001  # 0.1mm
        val_gap = abs(val_a - val_b)
        if val_gap <= val_tol:
            val_cost = 0.0
        elif val_gap <= val_tol * 10:
            val_cost = val_gap / val_tol * 0.1  # Moderate penalty
        else:
            val_cost = 2.0  # Large value difference — likely different dimensions
        cost += val_cost * 0.2
    elif val_a is not None or val_b is not None:
        cost += 0.5 * 0.2  # One has value, other doesn't
    # else: neither has value (notes, balloons) — skip

    # ── Text similarity (weight: 0.15) ─────────────────────────────────
    text_a = _ann_text(ann_a)
    text_b = _ann_text(ann_b)
    if text_a or text_b:
        text_sim = _text_similarity(text_a, text_b)
        text_cost = 1.0 - text_sim
    else:
        text_cost = 0.0  # Both empty — neutral
    cost += text_cost * 0.15

    # ── Bounds overlap (weight: 0.05, tiebreaker) ──────────────────────
    iou = _ann_bounds_iou(ann_a, ann_b)
    if iou >= 0:
        bounds_cost = 1.0 - iou
    else:
        bounds_cost = 0.5  # No bounds available — neutral
    cost += bounds_cost * 0.05

    return cost


def _annotation_comparison_fields(ann: dict) -> dict:
    """Extract mutable fields for comparison."""
    return {
        "dimensionValue": ann.get("dimensionValue"),
        "dimensionType": ann.get("dimensionType"),
        "dimensionText": ann.get("dimensionText", ""),
        "tolerancePlus": ann.get("tolerancePlus", 0),
        "toleranceMinus": ann.get("toleranceMinus", 0),
        "toleranceType": ann.get("toleranceType", ""),
        "noteText": ann.get("noteText", ""),
        "gtolText": ann.get("gtolText", ""),
        "isReference": ann.get("isReference", False),
        "annotationName": ann.get("annotationName", ""),
    }


def _diff_annotations_for_view(
    anns_a: List[dict],
    anns_b: List[dict],
    view_diagonal: float,
) -> dict:
    """Diff annotations within a single matched view pair.

    Uses multi-signal cost scoring with greedy assignment and abstention.
    Returns {added, removed, modified, unchanged, rollup}.
    """
    # Filter to diffable types
    fa = [a for a in anns_a if a.get("annotationType") in _DIFFABLE_ANNOTATION_TYPES]
    fb = [a for a in anns_b if a.get("annotationType") in _DIFFABLE_ANNOTATION_TYPES]

    if not fa and not fb:
        return {
            "added": [], "removed": [], "modified": [],
            "unchangedCount": 0, "rollup": {}, "hasChanges": False,
        }

    # Build cost matrix and run global minimum-cost assignment (Hungarian).
    n_a = len(fa)
    n_b = len(fb)
    size = max(n_a, n_b)

    # Pad to square with dummy costs
    _DUMMY_COST = _ANN_MATCH_ABSTAIN + 1.0
    import numpy as np
    cost_matrix = np.full((size, size), _DUMMY_COST)
    for i in range(n_a):
        for j in range(n_b):
            cost_matrix[i, j] = _compute_ann_match_cost(fa[i], fb[j], view_diagonal)

    from scipy.optimize import linear_sum_assignment
    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    # Filter: only accept assignments within the real range and below abstain threshold
    matched_a: set = set()
    matched_b: set = set()
    matches: List[Tuple[int, int, float]] = []

    for r, c_idx in zip(row_ind, col_ind):
        if r >= n_a or c_idx >= n_b:
            continue  # dummy assignment
        cost = cost_matrix[r, c_idx]
        if cost > _ANN_MATCH_ABSTAIN:
            continue  # too expensive — abstain

        # Ambiguity check: is there another close candidate for either side?
        alt_for_r = sorted(cost_matrix[r, j] for j in range(n_b) if j != c_idx)
        alt_for_c = sorted(cost_matrix[i, c_idx] for i in range(n_a) if i != r)
        best_alt = min(
            alt_for_r[0] if alt_for_r else _ANN_INF_COST,
            alt_for_c[0] if alt_for_c else _ANN_INF_COST,
        )
        gap = best_alt - cost
        if cost > _ANN_MATCH_STRONG and gap < _ANN_AMBIGUITY_GAP:
            # Dimensions can legitimately change value/text across revisions while
            # staying the closest positional counterpart in the view. In that case,
            # prefer the position-dominant pairing over a conservative abstain so
            # the UI shows a true modified pair instead of a red/green false split.
            accept_dimension_pair = False
            if (fa[r].get("annotationType") == "displayDimension"
                    and fb[c_idx].get("annotationType") == "displayDimension"):
                chosen_dist = _annotation_position_distance(fa[r], fb[c_idx])
                alt_row_dists = [
                    _annotation_position_distance(fa[r], fb[j])
                    for j in range(n_b)
                    if j != c_idx and fb[j].get("annotationType") == fa[r].get("annotationType")
                ]
                alt_col_dists = [
                    _annotation_position_distance(fa[i], fb[c_idx])
                    for i in range(n_a)
                    if i != r and fa[i].get("annotationType") == fb[c_idx].get("annotationType")
                ]
                finite_alt_dists = [d for d in alt_row_dists + alt_col_dists if math.isfinite(d)]
                best_alt_dist = min(finite_alt_dists) if finite_alt_dists else float("inf")
                pos_tol = max(view_diagonal * _POSITION_TOL_FRACTION, 0.002)
                if (math.isfinite(chosen_dist)
                        and chosen_dist <= pos_tol * 2.0
                        and (not math.isfinite(best_alt_dist) or chosen_dist <= best_alt_dist * 0.75)):
                    accept_dimension_pair = True

            if not accept_dimension_pair:
                continue  # ambiguous — abstain

        matches.append((r, c_idx, float(cost)))
        matched_a.add(r)
        matched_b.add(c_idx)

    # Build results
    added = []
    removed = []
    modified = []
    unchanged_count = 0

    for i, j, cost in matches:
        fields_a = _annotation_comparison_fields(fa[i])
        fields_b = _annotation_comparison_fields(fb[j])
        changes = _compare_annotation_fields(fields_a, fields_b)
        if changes:
            modified.append({
                "annotationNameA": fields_a["annotationName"],
                "annotationNameB": fields_b["annotationName"],
                "annotationType": fa[i].get("annotationType", ""),
                "changes": changes,
                "boundsSheetA": fa[i].get("boundsSheet"),
                "boundsSheetB": fb[j].get("boundsSheet"),
                "positionSheetA": _extract_pos(fa[i]),
                "positionSheetB": _extract_pos(fb[j]),
                "textExtentA": fa[i].get("textExtent"),
                "textExtentB": fb[j].get("textExtent"),
                "anchorKindA": fa[i].get("anchorKind"),
                "anchorKindB": fb[j].get("anchorKind"),
                "matchCost": round(cost, 3),
            })
        else:
            unchanged_count += 1

    # Unmatched A = removed
    for i in range(n_a):
        if i not in matched_a:
            removed.append(_make_removed_annotation(
                fa[i], fa[i].get("annotationType", "")))

    # Unmatched B = added
    for j in range(n_b):
        if j not in matched_b:
            added.append(_make_added_annotation(
                fb[j], fb[j].get("annotationType", "")))

    # Rollup counts by class
    rollup: Dict[str, Dict[str, int]] = {}
    for a in added:
        t = a["annotationType"]
        rollup.setdefault(t, {"added": 0, "removed": 0, "modified": 0})
        rollup[t]["added"] += 1
    for r in removed:
        t = r["annotationType"]
        rollup.setdefault(t, {"added": 0, "removed": 0, "modified": 0})
        rollup[t]["removed"] += 1
    for m in modified:
        t = m["annotationType"]
        rollup.setdefault(t, {"added": 0, "removed": 0, "modified": 0})
        rollup[t]["modified"] += 1

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchangedCount": unchanged_count,
        "rollup": rollup,
        "hasChanges": bool(added or removed or modified),
    }


def _compare_annotation_fields(fields_a: dict, fields_b: dict) -> List[dict]:
    """Compare mutable annotation fields. Returns list of field-level changes."""
    changes = []
    ta = (fields_a.get("dimensionText") or "").strip()
    tb = (fields_b.get("dimensionText") or "").strip()

    # Dimension value
    va = fields_a.get("dimensionValue")
    vb = fields_b.get("dimensionValue")
    if va is not None and vb is not None:
        if abs(va - vb) > 1e-6:
            changes.append({
                "field": "dimensionValue",
                "old": va, "new": vb,
                "delta": round(vb - va, 6),
            })
    elif (va is None) != (vb is None) and ta != tb:
        changes.append({"field": "dimensionValue", "old": va, "new": vb})

    # Dimension text
    if ta != tb and (ta or tb):
        changes.append({"field": "dimensionText", "old": ta, "new": tb})

    # Tolerances
    for tol_field in ("tolerancePlus", "toleranceMinus"):
        tva = fields_a.get(tol_field, 0) or 0
        tvb = fields_b.get(tol_field, 0) or 0
        if abs(tva - tvb) > 1e-7:
            changes.append({
                "field": tol_field, "old": tva, "new": tvb,
                "delta": round(tvb - tva, 7),
            })

    # Tolerance type
    tta = fields_a.get("toleranceType", "")
    ttb = fields_b.get("toleranceType", "")
    if tta != ttb:
        changes.append({"field": "toleranceType", "old": tta, "new": ttb})

    # Note text
    na = (fields_a.get("noteText") or "").strip()
    nb = (fields_b.get("noteText") or "").strip()
    if na != nb and (na or nb):
        changes.append({"field": "noteText", "old": na, "new": nb})

    # GD&T text
    ga = (fields_a.get("gtolText") or "").strip()
    gb = (fields_b.get("gtolText") or "").strip()
    if ga != gb and (ga or gb):
        changes.append({"field": "gtolText", "old": ga, "new": gb})

    # Reference dimension status — tracked but suppressed if it's the only change,
    # since isReference is an internal extraction property not visible on the drawing.
    ra = fields_a.get("isReference", False)
    rb = fields_b.get("isReference", False)
    if ra != rb:
        changes.append({"field": "isReference", "old": ra, "new": rb})

    # Suppress isReference-only changes — they are not visible on the drawing
    # and produce false-positive "modified" highlights.
    if len(changes) == 1 and changes[0]["field"] == "isReference":
        return []

    return changes


def _extract_pos(ann: dict) -> Optional[List[float]]:
    """Extract [x, y] from positionSheet."""
    pos = ann.get("positionSheet")
    if isinstance(pos, dict):
        x, y = pos.get("x"), pos.get("y")
        if x is not None and y is not None:
            return [float(x), float(y)]
    elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return [float(pos[0]), float(pos[1])]
    return None


def _make_added_annotation(ann: dict, ann_type: str) -> dict:
    return {
        "annotationName": ann.get("annotationName", ""),
        "annotationType": ann_type,
        "boundsSheet": ann.get("boundsSheet"),
        "positionSheet": _extract_pos(ann),
        "textExtent": ann.get("textExtent"),
        "anchorKind": ann.get("anchorKind"),
        "dimensionText": ann.get("dimensionText"),
        "noteText": ann.get("noteText"),
        "gtolText": ann.get("gtolText"),
    }


def _make_removed_annotation(ann: dict, ann_type: str) -> dict:
    return {
        "annotationName": ann.get("annotationName", ""),
        "annotationType": ann_type,
        "boundsSheet": ann.get("boundsSheet"),
        "positionSheet": _extract_pos(ann),
        "textExtent": ann.get("textExtent"),
        "anchorKind": ann.get("anchorKind"),
        "dimensionText": ann.get("dimensionText"),
        "noteText": ann.get("noteText"),
        "gtolText": ann.get("gtolText"),
    }


def _annotation_has_loc(ann: dict) -> bool:
    bounds = ann.get("boundsSheet")
    if isinstance(bounds, list) and len(bounds) >= 4:
        return True
    pos = _extract_pos(ann)
    return bool(pos)


def _rebuild_annotation_rollup(added: List[dict], removed: List[dict], modified: List[dict]) -> Dict[str, Dict[str, int]]:
    rollup: Dict[str, Dict[str, int]] = {}
    for a in added:
        t = a["annotationType"]
        rollup.setdefault(t, {"added": 0, "removed": 0, "modified": 0})
        rollup[t]["added"] += 1
    for r in removed:
        t = r["annotationType"]
        rollup.setdefault(t, {"added": 0, "removed": 0, "modified": 0})
        rollup[t]["removed"] += 1
    for m in modified:
        t = m["annotationType"]
        rollup.setdefault(t, {"added": 0, "removed": 0, "modified": 0})
        rollup[t]["modified"] += 1
    return rollup


def _suppress_low_confidence_orphan_dimensions(
    diff: dict,
    anns_a: List[dict],
    anns_b: List[dict],
    view_family: str,
) -> dict:
    """Suppress likely extractor-noise orphan dimensions in detail/section views.

    Per-annotation gate: an orphan is suppressed only when its own data is
    unreliable (no location AND no semantic anchor, or marked semantic-only,
    or anchored to a ghost view that doesn't exist in the same drawing).
    Suppressed orphans are kept on diff['suppressedOrphans'] so downstream
    consumers (verdicts, future UI) can still see what was filtered.
    """
    if view_family not in ("detail", "section"):
        return diff

    # Build set of valid view names per drawing for ghost-feature detection
    def _valid_view_names(anns: List[dict]) -> set:
        names = set()
        for ann in anns:
            vn = ann.get("viewName")
            if isinstance(vn, str) and vn.strip():
                names.add(vn.strip())
        return names

    valid_views_a = _valid_view_names(anns_a)
    valid_views_b = _valid_view_names(anns_b)

    def _orphan_is_low_confidence(ann: dict, sibling_view_names: set) -> bool:
        """Per-annotation confidence check. Only the orphan's own data matters."""
        if ann.get("annotationType") != "displayDimension":
            return False
        # Hard signals from the extractor itself
        if ann.get("geometrySource") == "semantic_only":
            return True
        # Ghost feature anchor: featureName references a view that doesn't exist
        feat = ann.get("featureName")
        if isinstance(feat, str) and feat.strip():
            feat_name = feat.strip()
            looks_like_view = feat_name.lower().startswith(("drawing view", "section view", "detail view"))
            if looks_like_view and feat_name not in sibling_view_names:
                return True
        # Geometry is fully empty (no location anywhere)
        if not _annotation_has_loc(ann):
            return True
        return False

    suppressed_removed: List[dict] = []
    suppressed_added: List[dict] = []
    changed = False

    if diff.get("removed"):
        kept, dropped = [], []
        for r in diff["removed"]:
            # Orphans on the removed side came from anns_a; check their data against valid_views_a
            if _orphan_is_low_confidence(r, valid_views_a):
                dropped.append(r)
            else:
                kept.append(r)
        if dropped:
            diff["removed"] = kept
            suppressed_removed.extend(dropped)
            changed = True

    if diff.get("added"):
        kept, dropped = [], []
        for a in diff["added"]:
            # Orphans on the added side came from anns_b; check against valid_views_b
            if _orphan_is_low_confidence(a, valid_views_b):
                dropped.append(a)
            else:
                kept.append(a)
        if dropped:
            diff["added"] = kept
            suppressed_added.extend(dropped)
            changed = True

    if changed:
        # Preserve evidence rather than silently delete
        existing = diff.get("suppressedOrphans") or {"added": [], "removed": []}
        existing.setdefault("added", []).extend(suppressed_added)
        existing.setdefault("removed", []).extend(suppressed_removed)
        diff["suppressedOrphans"] = existing
        diff["rollup"] = _rebuild_annotation_rollup(
            diff.get("added", []),
            diff.get("removed", []),
            diff.get("modified", []),
        )
        diff["hasChanges"] = bool(diff.get("added") or diff.get("removed") or diff.get("modified"))

    return diff


def _compute_annotation_diff(view_identity: dict, eligibility: dict) -> dict:
    """Compute annotation diff for all matched view pairs.

    Skips views where compareEligibility.supportedForAnnotationDiff is False.
    """
    views_a = view_identity.get("_viewsA", [])
    views_b = view_identity.get("_viewsB", [])

    # Build key->index lookups using sheet-scoped keys
    idx_a = {_view_key(v.view_name, v.sheet_name): i for i, v in enumerate(views_a)}
    idx_b = {_view_key(v.view_name, v.sheet_name): i for i, v in enumerate(views_b)}

    per_view = {}
    for match in view_identity["matched"]:
        vk = match["viewKey"]
        vk_a = _view_key(match["viewNameA"], match["sheetNameA"])

        # Enforce eligibility gate
        elig = eligibility.get("perView", {}).get(vk, {})
        if not elig.get("supportedForAnnotationDiff", True):
            per_view[vk] = {
                "added": [], "removed": [], "modified": [],
                "unchangedCount": 0, "rollup": {},
                "hasChanges": False,
                "skipped": True,
                "skipReason": "view_not_eligible_for_annotation_diff",
            }
            continue

        ia = idx_a.get(vk_a)
        ib = idx_b.get(vk)
        if ia is None or ib is None:
            continue

        va = views_a[ia]
        vb = views_b[ib]
        diag = _outline_diagonal(vb.view_outline)

        diff = _diff_annotations_for_view(va.annotations, vb.annotations, diag)
        diff = _suppress_low_confidence_orphan_dimensions(
            diff,
            va.annotations,
            vb.annotations,
            _view_family(match.get("viewType", "Standard")),
        )
        per_view[vk] = diff

    return {"perView": per_view}


# ═══════════════════════════════════════════════════════════════════════════
# Layer 4: Sheet Metadata Diff
# ═══════════════════════════════════════════════════════════════════════════

def _compute_sheet_metadata_diff(map_a: dict, map_b: dict) -> dict:
    """Diff sheet-level metadata: format, sheet count, sheet names."""
    sheets_a = map_a.get("sheets", [])
    sheets_b = map_b.get("sheets", [])

    result = {
        "sheetCountA": len(sheets_a),
        "sheetCountB": len(sheets_b),
        "sheetCountChanged": len(sheets_a) != len(sheets_b),
        "sheetChanges": [],
    }

    # Match sheets by name
    sa_map = {s.get("sheetName", ""): s for s in sheets_a}
    sb_map = {s.get("sheetName", ""): s for s in sheets_b}

    all_names = set(sa_map.keys()) | set(sb_map.keys())
    for name in sorted(all_names):
        sa = sa_map.get(name)
        sb = sb_map.get(name)

        if sa and not sb:
            result["sheetChanges"].append({
                "sheetName": name, "status": "removed",
            })
        elif sb and not sa:
            result["sheetChanges"].append({
                "sheetName": name, "status": "added",
            })
        else:
            # Both exist — compare metadata
            changes = []
            # Paper size / scale
            for field in ("paperSize", "scale"):
                va = sa.get(field)
                vb = sb.get(field)
                if va != vb:
                    changes.append({"field": field, "old": va, "new": vb})
            # Sheet dimensions
            for field in ("sheetWidth", "sheetHeight"):
                va = sa.get(field, 0)
                vb = sb.get(field, 0)
                if abs((va or 0) - (vb or 0)) > 1e-6:
                    changes.append({"field": field, "old": va, "new": vb})
            # Sheet format (title block, rev block)
            fmt_a = sa.get("sheetFormat") or {}
            fmt_b = sb.get("sheetFormat") or {}
            if fmt_a or fmt_b:
                for fk in ("titleBlockBounds", "revisionBlockBounds",
                           "borderInset", "drawableArea"):
                    fa = fmt_a.get(fk)
                    fb = fmt_b.get(fk)
                    if fa != fb:
                        changes.append({
                            "field": f"sheetFormat.{fk}",
                            "old": fa, "new": fb,
                        })
            # View count change
            va_count = len(sa.get("views", []))
            vb_count = len(sb.get("views", []))
            if va_count != vb_count:
                changes.append({
                    "field": "viewCount",
                    "old": va_count, "new": vb_count,
                })

            if changes:
                result["sheetChanges"].append({
                    "sheetName": name, "status": "modified",
                    "changes": changes,
                })

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Layer 5: Projected Model Delta (coarse/advisory)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_projected_model_delta(
    view_identity: dict,
    geometry_diff: Optional[dict],
    drawing_map_b: dict,
    part_json_a: Optional[dict],
    part_json_b: Optional[dict],
    eligibility: Optional[dict] = None,
) -> dict:
    """Project 3D geometry diff regions into matched 2D drawing views.

    MVP: coarse bbox/centroid projection only — not contour-accurate.
    Skips views where compareEligibility.supportedForProjectedModelReasoning is False.
    """
    if not geometry_diff or geometry_diff.get("identical", True):
        return {"available": False, "reason": "no_geometry_diff", "perView": {}}

    # Use sketch_dimension_matcher projection helpers
    from ai_inspector.comparison.sketch_dimension_matcher import (
        SW_VIEW_PROJECTIONS, _model_to_sheet,
    )

    # Prefer explicit per-region bbox output from geometry diff. Fall back to the
    # older centroid-only contract if region boxes are unavailable.
    changed_regions = _extract_changed_regions_from_diff(geometry_diff)

    # Get bbox center for projection (from part JSON or geometry diff)
    bbox_center = _get_bbox_center_from_diff(geometry_diff, part_json_b)

    views_b = view_identity.get("_viewsB", [])
    idx_b = {_view_key(v.view_name, v.sheet_name): v for v in views_b}

    elig_per_view = (eligibility or {}).get("perView", {})
    per_view = {}
    for match in view_identity["matched"]:
        vk = match["viewKey"]

        # Enforce eligibility gate
        elig = elig_per_view.get(vk, {})
        if not elig.get("supportedForProjectedModelReasoning", True):
            per_view[vk] = {
                "deltaPresent": False,
                "reason": "view_not_eligible_for_projection",
                "projectedRegions": [],
                "skipped": True,
            }
            continue

        vb = idx_b.get(vk)
        if not vb:
            continue

        orientation = (vb.view_orientation or "").lower()
        if orientation not in SW_VIEW_PROJECTIONS:
            per_view[vk] = {
                "deltaPresent": False,
                "reason": "unsupported_orientation",
                "projectedRegions": [],
            }
            continue

        # Build a mock view dict for _model_to_sheet
        mock_view = {
            "viewOrientation": vb.view_orientation,
            "viewPosition": vb.view_position,
            "viewScale": vb.view_scale,
        }

        # Project each changed 3D region into this view
        projected_regions = []
        for region in changed_regions:
            projected = _project_changed_region_to_view(
                region=region,
                view=mock_view,
                bbox_center_mm=bbox_center,
                view_outline=vb.view_outline,
                model_to_sheet_fn=_model_to_sheet,
            )
            if projected:
                projected_regions.append(projected)

        delta_present = len(projected_regions) > 0
        visibility = "high" if delta_present else "low"

        per_view[vk] = {
            "deltaPresent": delta_present,
            "expectedVisibility": visibility,
            "projectedRegions": projected_regions,
            "allProjectedRegionsCount": len(projected_regions),
            "reason": None,
        }

    return {
        "available": True,
        "identical": geometry_diff.get("identical", True),
        "addedVolumeMm3": geometry_diff.get("added_volume_mm3", 0),
        "removedVolumeMm3": geometry_diff.get("removed_volume_mm3", 0),
        "perView": per_view,
    }


def _extract_changed_regions_from_diff(geometry_diff: dict) -> List[dict]:
    """Normalize geometry diff change regions across contract versions."""
    regions = []
    for region in geometry_diff.get("changed_regions", []) or []:
        if isinstance(region, dict):
            regions.append(region)

    if regions:
        return regions

    # Backward compatibility: old geometry diff only exported centroids.
    for cc in geometry_diff.get("changed_centroids", []) or []:
        if isinstance(cc, dict):
            regions.append({
                "type": cc.get("type", "changed"),
                "centroid": cc.get("centroid"),
                "volume_mm3": cc.get("volume_mm3"),
                "region_index": len(regions) + 1,
            })
    return regions


def _bbox_corners_mm(bbox: dict) -> List[Tuple[float, float, float]]:
    mn = bbox.get("min") or []
    mx = bbox.get("max") or []
    if len(mn) < 3 or len(mx) < 3:
        return []
    return [
        (mn[0], mn[1], mn[2]),
        (mn[0], mn[1], mx[2]),
        (mn[0], mx[1], mn[2]),
        (mn[0], mx[1], mx[2]),
        (mx[0], mn[1], mn[2]),
        (mx[0], mn[1], mx[2]),
        (mx[0], mx[1], mn[2]),
        (mx[0], mx[1], mx[2]),
    ]


def _clip_sheet_bounds_to_outline(
    sheet_bounds: List[float],
    view_outline: List[float],
) -> Optional[List[float]]:
    if len(sheet_bounds) < 4 or len(view_outline) < 4:
        return None

    x1 = max(sheet_bounds[0], view_outline[0])
    y1 = max(sheet_bounds[1], view_outline[1])
    x2 = min(sheet_bounds[2], view_outline[2])
    y2 = min(sheet_bounds[3], view_outline[3])
    if x2 < x1 or y2 < y1:
        return None
    return [x1, y1, x2, y2]


def _project_changed_region_to_view(
    region: dict,
    view: dict,
    bbox_center_mm: Tuple[float, float, float],
    view_outline: List[float],
    model_to_sheet_fn,
) -> Optional[dict]:
    """Project one changed 3D region into a 2D drawing view.

    Returns a projected advisory region. Prefers bbox projection when 3D bounds
    are available; falls back to the legacy centroid-only point marker.
    """
    bbox_center_m = (
        bbox_center_mm[0] / 1000.0,
        bbox_center_mm[1] / 1000.0,
        bbox_center_mm[2] / 1000.0,
    )

    bbox = region.get("bbox") or {}
    corners_mm = _bbox_corners_mm(bbox)
    if corners_mm:
        projected_pts = []
        for corner_mm in corners_mm:
            pt = model_to_sheet_fn(
                (corner_mm[0] / 1000.0, corner_mm[1] / 1000.0, corner_mm[2] / 1000.0),
                view,
                bbox_center_m,
            )
            if pt is not None:
                projected_pts.append(pt)

        if projected_pts:
            xs = [pt[0] for pt in projected_pts]
            ys = [pt[1] for pt in projected_pts]
            sheet_bounds = [min(xs), min(ys), max(xs), max(ys)]
            clipped = _clip_sheet_bounds_to_outline(sheet_bounds, view_outline)
            if clipped:
                return {
                    "type": region.get("type", "changed"),
                    "regionIndex": region.get("region_index"),
                    "sheetBounds": [round(v, 6) for v in clipped],
                    "sheetPosition": [
                        round((clipped[0] + clipped[2]) / 2, 6),
                        round((clipped[1] + clipped[3]) / 2, 6),
                    ],
                    "source": "bbox_projection",
                    "confidence": "advisory",
                    "volumeMm3": region.get("volume_mm3"),
                }

    centroid_mm = region.get("centroid") or []
    if len(centroid_mm) >= 3:
        sheet_pt = model_to_sheet_fn(
            (centroid_mm[0] / 1000.0, centroid_mm[1] / 1000.0, centroid_mm[2] / 1000.0),
            view,
            bbox_center_m,
        )
        if (sheet_pt is not None and len(view_outline) >= 4
                and view_outline[0] <= sheet_pt[0] <= view_outline[2]
                and view_outline[1] <= sheet_pt[1] <= view_outline[3]):
            return {
                "type": region.get("type", "changed"),
                "regionIndex": region.get("region_index"),
                "sheetPosition": [round(sheet_pt[0], 6), round(sheet_pt[1], 6)],
                "source": "centroid_projection",
                "confidence": "advisory",
                "volumeMm3": region.get("volume_mm3"),
            }

    return None


def _refine_projected_model_delta_for_display(
    geometry_diff_section: dict,
    annotation_diff: dict,
) -> dict:
    """Reduce projected-model overlay noise while preserving verdict semantics.

    We keep deltaPresent as originally computed for conservative reasoning, but
    narrow the displayed projectedRegions to the strongest view per 3D region.
    This suppresses secondary projections that are mathematically valid but weak
    review evidence, such as edge-on slivers near unrelated annotations.
    """
    per_view = geometry_diff_section.get("perView", {})
    ann_per_view = annotation_diff.get("perView", {})

    # Pick the strongest display view for each changed 3D region.
    best_by_region: Dict[Tuple[str, Any], Tuple[float, str]] = {}
    for view_key, view_delta in per_view.items():
        ann_view = ann_per_view.get(view_key, {})
        for region in view_delta.get("projectedRegions", []) or []:
            region_key = (
                region.get("type", "changed"),
                region.get("regionIndex"),
            )
            score = _score_projected_region_for_display(region, ann_view)
            current = best_by_region.get(region_key)
            if current is None or score > current[0]:
                best_by_region[region_key] = (score, view_key)

    for view_key, view_delta in per_view.items():
        kept = []
        for region in view_delta.get("projectedRegions", []) or []:
            region_key = (
                region.get("type", "changed"),
                region.get("regionIndex"),
            )
            winner = best_by_region.get(region_key)
            if winner and winner[1] == view_key:
                kept.append(region)
        merged = _merge_projected_regions_for_view(kept)
        view_delta["projectedRegions"] = merged
        view_delta["displayProjectedRegionsCount"] = len(merged)
        view_delta["suppressedProjectedRegionsCount"] = max(
            0,
            view_delta.get("allProjectedRegionsCount", len(kept)) - len(merged),
        )

    return geometry_diff_section


def _score_projected_region_for_display(region: dict, ann_view: dict) -> float:
    """Rank the usefulness of a projected advisory region for UI display."""
    score = 0.0
    if ann_view.get("hasChanges"):
        score += 100.0

    bounds = region.get("sheetBounds") or []
    if len(bounds) >= 4:
        width = max(0.0, bounds[2] - bounds[0])
        height = max(0.0, bounds[3] - bounds[1])
        major = max(width, height)
        minor = min(width, height)
        aspect_balance = (minor / major) if major > 1e-9 else 0.0
        score += aspect_balance * 10.0
        score += width * height
    elif region.get("sheetPosition"):
        score += 0.1

    # Small tie-break in favor of bbox over centroid only.
    if region.get("source") == "bbox_projection":
        score += 0.5
    return score


def _merge_projected_regions_for_view(regions: List[dict]) -> List[dict]:
    """Merge exact/near-duplicate projected rectangles within one view."""
    rects = []
    points = []
    for region in regions:
        if region.get("sheetBounds") and len(region["sheetBounds"]) >= 4:
            rects.append(region)
        else:
            points.append(region)

    merged: List[dict] = []
    for region in rects:
        matched = False
        for existing in merged:
            if existing.get("type") != region.get("type"):
                continue
            if _bounds_almost_equal(existing.get("sheetBounds"), region.get("sheetBounds")):
                existing["volumeMm3"] = round(
                    (existing.get("volumeMm3") or 0.0) + (region.get("volumeMm3") or 0.0),
                    3,
                )
                existing["mergedCount"] = existing.get("mergedCount", 1) + 1
                matched = True
                break
        if not matched:
            item = dict(region)
            item["mergedCount"] = 1
            merged.append(item)

    return merged + points


def _bounds_almost_equal(
    a: Optional[List[float]],
    b: Optional[List[float]],
    eps: float = 1e-6,
) -> bool:
    if not a or not b or len(a) < 4 or len(b) < 4:
        return False
    return all(abs(a[i] - b[i]) <= eps for i in range(4))


def _get_bbox_center_from_diff(
    geometry_diff: dict,
    part_json: Optional[dict],
) -> Tuple[float, float, float]:
    """Get bbox center in mm from geometry diff or part JSON."""
    # Try geometry diff bbox_b first
    bbox = geometry_diff.get("bbox_b", {})
    if bbox.get("min") and bbox.get("max"):
        mn = bbox["min"]
        mx = bbox["max"]
        return (
            (mn[0] + mx[0]) / 2,
            (mn[1] + mx[1]) / 2,
            (mn[2] + mx[2]) / 2,
        )
    # Fallback to part JSON
    if part_json:
        bb = part_json.get("physical", {}).get("boundingBox", {})
        return (
            (bb.get("minX", 0) + bb.get("maxX", 0)) / 2 * 1000,
            (bb.get("minY", 0) + bb.get("maxY", 0)) / 2 * 1000,
            (bb.get("minZ", 0) + bb.get("maxZ", 0)) / 2 * 1000,
        )
    return (0.0, 0.0, 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Layer 6: Verdict Engine (conservative)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_verdicts(
    view_identity: dict,
    annotation_diff: dict,
    geometry_diff_section: dict,
    native_geometry_diff: dict,
    compare_eligibility: dict,
) -> dict:
    """Compute per-view verdicts. Conservative in MVP — prefer advisory labels."""
    per_view = {}

    for match in view_identity["matched"]:
        vk = match["viewKey"]
        confidence = match["confidence"]

        # Evidence summary
        ann_view = annotation_diff.get("perView", {}).get(vk, {})
        geom_view = geometry_diff_section.get("perView", {}).get(vk, {})
        native_view = native_geometry_diff.get("perView", {}).get(vk, {})
        elig = compare_eligibility.get("perView", {}).get(vk, {})

        ann_changed = ann_view.get("hasChanges", False)
        ann_skipped = ann_view.get("skipped", False)
        proj_delta = geom_view.get("deltaPresent", False)
        proj_skipped = geom_view.get("skipped", False)
        native_delta = native_view.get("hasChanges", False)
        native_skipped = native_view.get("skipped", False)

        evidence = {
            "viewChanged": ann_changed or proj_delta or native_delta,
            "annotationChanged": ann_changed,
            "annotationSkipped": ann_skipped,
            "projectedModelDeltaPresent": proj_delta,
            "projectedModelSkipped": proj_skipped,
            "nativeGeometryDeltaPresent": native_delta,
            "nativeGeometrySkipped": native_skipped,
            "viewMatchConfidence": confidence,
            "compareEligibility": elig,
        }

        # Interpretation — conservative MVP labels
        if match.get("ambiguous"):
            interpretation = "view_match_ambiguous"
        elif ann_skipped and proj_skipped and native_skipped:
            interpretation = "not_compared"
        elif not ann_changed and not proj_delta and not native_delta:
            interpretation = "unchanged"
        elif ann_changed and not proj_delta and not native_delta:
            interpretation = "annotation_only_change"
        elif native_delta and not ann_changed:
            interpretation = "native_geometry_changed"
        elif proj_delta and not ann_changed:
            interpretation = "model_delta_projects_into_view"
        elif (proj_delta or native_delta) and ann_changed:
            interpretation = "geometry_changed"
        else:
            interpretation = "needs_review"

        per_view[vk] = {
            "evidence": evidence,
            "interpretation": interpretation,
        }

    # Unmatched views — use their own viewKey
    for uv in view_identity.get("unmatchedBase", []):
        per_view[uv["viewKey"]] = {
            "evidence": {"viewChanged": True},
            "interpretation": "view_removed",
        }
    for uv in view_identity.get("unmatchedTarget", []):
        per_view[uv["viewKey"]] = {
            "evidence": {"viewChanged": True},
            "interpretation": "view_added",
        }

    return {"perView": per_view}


# ═══════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════

def _build_summary(
    view_identity: dict,
    annotation_diff: dict,
    geometry_diff_section: dict,
    native_geometry_diff: dict,
    user_facing_findings: dict,
) -> dict:
    """Build top-level summary for the compare artifact."""
    matched = view_identity["matched"]
    n_matched = len(matched)
    n_ambiguous = len(view_identity["ambiguous"])
    n_unmatched_a = len(view_identity["unmatchedBase"])
    n_unmatched_b = len(view_identity["unmatchedTarget"])

    # Count changed views
    n_changed = 0
    n_annotation_only = 0
    n_model_delta = 0
    interpretations: Dict[str, int] = {}

    for vn, finding in user_facing_findings.get("perView", {}).items():
        interp = finding.get("interpretation", "")
        interpretations[interp] = interpretations.get(interp, 0) + 1
        if interp not in ("unchanged", "view_match_ambiguous"):
            n_changed += 1
        if interp == "annotation_only_change":
            n_annotation_only += 1
        if interp in ("model_delta_projects_into_view", "native_geometry_changed", "geometry_changed"):
            n_model_delta += 1

    # Total annotation changes
    total_added = 0
    total_removed = 0
    total_modified = 0
    for vn, diff in annotation_diff.get("perView", {}).items():
        total_added += len(diff.get("added", []))
        total_removed += len(diff.get("removed", []))
        total_modified += len(diff.get("modified", []))

    total_native_added = native_geometry_diff.get("totalAdded", 0)
    total_native_removed = native_geometry_diff.get("totalRemoved", 0)

    parts = []
    if n_matched:
        parts.append(f"{n_matched} view(s) matched")
    if n_changed:
        parts.append(f"{n_changed} changed")
    if n_unmatched_a:
        parts.append(f"{n_unmatched_a} removed")
    if n_unmatched_b:
        parts.append(f"{n_unmatched_b} added")
    if total_modified or total_added or total_removed:
        ann_parts = []
        if total_modified:
            ann_parts.append(f"{total_modified} modified")
        if total_added:
            ann_parts.append(f"{total_added} added")
        if total_removed:
            ann_parts.append(f"{total_removed} removed")
        parts.append(f"annotations: {', '.join(ann_parts)}")
    if total_native_added or total_native_removed:
        geo_parts = []
        if total_native_added:
            geo_parts.append(f"{total_native_added} add")
        if total_native_removed:
            geo_parts.append(f"{total_native_removed} rem")
        parts.append(f"native geometry: {', '.join(geo_parts)}")

    return {
        "text": "; ".join(parts) if parts else "No changes detected",
        "matchedViews": n_matched,
        "ambiguousViews": n_ambiguous,
        "unmatchedBaseViews": n_unmatched_a,
        "unmatchedTargetViews": n_unmatched_b,
        "changedViews": n_changed,
        "annotationOnlyChanges": n_annotation_only,
        "modelDeltaViews": n_model_delta,
        "totalAnnotationsAdded": total_added,
        "totalAnnotationsRemoved": total_removed,
        "totalAnnotationsModified": total_modified,
        "totalNativeGeometryAdded": total_native_added,
        "totalNativeGeometryRemoved": total_native_removed,
        "interpretationCounts": interpretations,
        "geometryDiffAvailable": geometry_diff_section.get("available", False),
        "nativeGeometryDiffAvailable": native_geometry_diff.get("available", False),
    }
